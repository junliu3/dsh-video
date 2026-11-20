"""五段式编排：采集 → 抽音轨 → 转写 → 成文 → 清理。

对外只有一个 run()：入参是作业字典，出参是可直接塞进工具返回值的摘要。
所有人类可读的话都走 emit.log（stderr），机器事件走 emit（stdout JSONL）。
"""
import os
import time

from . import acquire as acq
from . import asr, config, docgen, locks, store
from .errors import BadInput, Canceled, NoSpeech, PipelineError


def _check(cancel):
    if cancel and cancel():
        raise Canceled("任务已取消")


def _files(directory):
    return sorted(
        name for name in os.listdir(directory)
        if not name.startswith(".") and not name.endswith((".part", ".lock"))
    )


def run(job, emit, cancel=None):
    started = time.time()
    config.ensure_dirs()

    source = str(job.get("source") or "").strip()
    if not source:
        raise BadInput("没有提供链接或文件路径")

    audio_only = bool(job.get("audioOnly"))
    download_only = bool(job.get("downloadOnly"))
    keep_wav = bool(job.get("keepWav"))
    drop_media = bool(job.get("dropMedia"))
    emit_docx = job.get("emitDocx", True)
    model = job.get("model") or config.DEFAULT_MODEL
    device = job.get("device") or config.DEFAULT_DEVICE
    language = job.get("language") or config.DEFAULT_LANG

    emit.start(source=source, audioOnly=audio_only, downloadOnly=download_only,
               model=model, language=language)
    emit.stage("resolve", "解析链接")
    resolved = acq.resolve(source, local_id=job.get("id"), log=emit.log, cancel=cancel)
    video_id = resolved["video_id"]
    directory = store.asset_dir(video_id)
    emit.log(f"  作品 ID: {video_id}  落点: {directory}")

    try:
        with locks.video_lock(video_id):
            # ---------- 1. 采集 ----------
            _check(cancel)
            emit.stage("acquire", "采集" if resolved["kind"] != "local" else "使用本地文件")
            stage_start = time.time()

            def on_bytes(done, total):
                emit.progress("acquire", done=done, total=total)

            got = acq.acquire(source, resolved, audio_only=audio_only, log=emit.log,
                              progress=on_bytes, cancel=cancel)
            emit.progress("acquire", done=1, total=1, force=True)
            emit.log(f"  采集完成，用时 {time.time() - stage_start:.1f}s")

            record = store.new_record(video_id, got.get("source_url", ""),
                                      platform=got.get("platform", "douyin"))
            record.update({
                "title": got.get("title") or video_id,
                "duration_sec": float(got.get("duration_sec") or 0),
                "cover_path": got.get("cover_path", ""),
                "media_path": got.get("media_path", ""),
                "media_kind": got.get("media_kind", ""),
                "audio_path": "",
            })
            store.write_media(directory, record)
            media_path = record["media_path"]
            audio_src = got.get("audio_src") or ""

            if download_only:
                elapsed = time.time() - started
                return {
                    "videoId": video_id,
                    "title": record["title"],
                    "platform": record["platform"],
                    "durationSec": record["duration_sec"],
                    "mediaPath": media_path,
                    "mediaKind": record["media_kind"],
                    "dir": directory,
                    "files": _files(directory),
                    "elapsedSec": round(elapsed, 1),
                    "downloadOnly": True,
                }

            # ---------- 2. 抽音轨 ----------
            _check(cancel)
            emit.stage("extract", "提取音轨（16kHz 单声道）")
            stage_start = time.time()
            wav = asr.extract_audio(media_path, directory, prefer=audio_src)
            emit.log(f"  audio.wav {os.path.getsize(wav) / 1048576:.1f} MB，"
                     f"用时 {time.time() - stage_start:.1f}s")
            if audio_src and os.path.exists(audio_src) and \
                    os.path.abspath(audio_src) != os.path.abspath(media_path):
                try:
                    os.remove(audio_src)
                except Exception:
                    pass

            # ---------- 3. 转写 ----------
            _check(cancel)
            emit.stage("transcribe", "语音转文字")
            stage_start = time.time()
            try:
                def on_audio(done, total):
                    emit.progress("transcribe", done=round(done, 1), total=round(total, 1))

                outcome = asr.transcribe(wav, model_size=model, device=device,
                                         language=language, log=emit.log,
                                         progress=on_audio, cancel=cancel)
                raw_segments = outcome["segments"]
                segments = docgen.dedupe(raw_segments)
                asr_meta = outcome["meta"]
                emit.log(f"  {len(segments)} 段 / 模型 {asr_meta['model']} / "
                         f"{asr_meta['device']}，用时 {time.time() - stage_start:.1f}s")
            except NoSpeech as exc:
                # 没有人声不算失败：元数据和媒体都保留，文档里明确标注
                raw_segments, segments = [], []
                asr_meta = {
                    "model": model, "device": device, "compute_type": "",
                    "language": language,
                    "audio_duration": round(float(record.get("duration_sec") or 0), 2),
                    "segment_count": 0, "vad": False, "note": str(exc),
                }
                emit.log(f"  {exc}；仍然生成文档，正文处会标注未检出人声", level="warn")

            store.save_json(os.path.join(directory, "segments.json"), {
                "video_id": video_id,
                "asr": asr_meta,
                "segments": segments,
            })

            # ---------- 4. 成文 ----------
            _check(cancel)
            emit.stage("compose", "整理并生成文档")
            stage_start = time.time()
            paragraphs = docgen.build_paragraphs(segments, config.PARA_GAP, config.PARA_MAX_CHARS)
            counters = docgen.stats(segments, raw_segments, record.get("duration_sec") or 0)

            record["pipeline"] = {
                "asr_model": asr_meta["model"],
                "asr_device": asr_meta["device"],
                "asr_compute": asr_meta.get("compute_type", ""),
                "asr_lang": asr_meta.get("language", ""),
                "paragraphs": len(paragraphs),
                "finished_at": store.now_iso(),
            }
            record["audio_path"] = ""
            store.write_media(directory, record)

            outputs = [
                docgen.write_srt(segments, os.path.join(directory, "transcript.srt")),
                docgen.write_txt(paragraphs, os.path.join(directory, "transcript.txt")),
            ]
            report = docgen.write_md(record, segments, paragraphs,
                                     os.path.join(directory, "report.md"), counters)
            outputs.append(report)
            if emit_docx:
                docx_path = docgen.write_docx(record, paragraphs,
                                              os.path.join(directory, "report.docx"))
                if docx_path:
                    outputs.append(docx_path)
            emit.log(f"  {len(paragraphs)} 个段落，用时 {time.time() - stage_start:.1f}s")

            # ---------- 5. 清理 ----------
            emit.stage("cleanup", "清理中间文件")
            if not keep_wav:
                try:
                    os.remove(wav)
                except Exception:
                    pass
            if drop_media and record.get("media_kind") == "video":
                try:
                    os.remove(media_path)
                    record["media_path"] = ""
                    store.write_media(directory, record)
                except Exception:
                    pass

    except PipelineError:
        raise
    except OSError as exc:
        if getattr(exc, "errno", None) == 28:
            raise PipelineError("磁盘空间不足", code="DISK_FULL")
        raise

    elapsed = time.time() - started
    emit.progress("compose", done=1, total=1, force=True)
    return {
        "videoId": video_id,
        "title": record["title"],
        "platform": record["platform"],
        "durationSec": record["duration_sec"],
        "dir": directory,
        "report": report,
        "files": _files(directory),
        "elapsedSec": round(elapsed, 1),
        "meta": {
            "asrModel": asr_meta["model"],
            "asrDevice": asr_meta["device"],
            "language": asr_meta.get("language") or "",
            "segments": counters["segment_count"],
            "paragraphs": len(paragraphs),
            "chars": counters["chars"],
            "speechSec": round(counters["speech_sec"], 1),
            "speechRatio": round(counters["speech_ratio"], 1),
            "charsPerMin": round(counters["chars_per_min"], 1),
            "noSpeech": not segments,
        },
    }
