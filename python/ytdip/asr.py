"""转写层：faster-whisper，CPU 优先、CUDA 可选并自动回退。

沿用原项目踩过的四个坑的解法：
  1. PyAV 新版去掉 metadata_errors -> 自己读 PCM 成数组，绕开 av 解码
  2. ctranslate2 找不到 cublas/cudnn   -> 启动前注册 pip 装的 nvidia DLL 目录
  3. 长静音后反复念同一句             -> condition_on_previous_text=False + VAD
  4. 无语音时把提示词原样吐出来       -> 过滤与提示词重合的输出，并回退重试

插件化新增：模型实例缓存（避免每次重载）、按音频时长的进度回报、逐片段取消检查。
"""
import os
import re
import subprocess
import wave

from . import config
from .errors import Canceled, ModelMissing, PipelineError

INITIAL_PROMPT = "以下是普通话口语内容，请使用简体中文输出并加标点。"
_PUNCT = re.compile(r"[\s，。！？、；：,.!?;:…\-—_\"'“”‘’()（）\[\]【】]")

# 只留最近一个模型，避免 small + medium 同时常驻吃掉几个 G
_MODEL_CACHE = {}


# ---------------------------------------------------------------- 环境
def register_cuda_dlls(log=None):
    added = []
    root = os.path.join(os.sys.prefix, "Lib", "site-packages", "nvidia")
    if not os.path.isdir(root):
        return added
    for sub in ("cublas", "cudnn", "cuda_runtime", "cufft", "curand"):
        path = os.path.join(root, sub, "bin")
        if not os.path.isdir(path):
            continue
        try:
            os.add_dll_directory(path)
        except Exception:
            pass
        os.environ["PATH"] = path + os.pathsep + os.environ.get("PATH", "")
        added.append(path)
    if added and log:
        log(f"  已注册 CUDA 运行库: {len(added)} 个目录")
    return added


# ---------------------------------------------------------------- 音频
def load_wav(path, expect_sr=16000):
    import numpy as np

    with wave.open(path, "rb") as handle:
        sample_rate = handle.getframerate()
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        raw = handle.readframes(handle.getnframes())

    if width != 2:
        raise PipelineError(f"wav 位深不是 16bit: {width * 8}bit", code="AUDIO_INVALID")
    if sample_rate != expect_sr:
        raise PipelineError(f"wav 采样率是 {sample_rate}，需要 {expect_sr}", code="AUDIO_INVALID")

    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return audio


def _ffmpeg_extract_wav(src, dest):
    if not os.path.exists(config.FFMPEG):
        raise PipelineError("找不到 ffmpeg", code="FFMPEG_MISSING",
                            hint="确认 tools/ffmpeg/bin 存在，或在配置里指定 ffmpegDir。")
    command = [
        config.FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-i", src, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", dest,
    ]
    result = subprocess.run(command, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode != 0 or not os.path.exists(dest):
        tail = (result.stderr or "").strip().splitlines()
        raise PipelineError("抽音轨失败: " + (tail[-1] if tail else "未知错误"),
                            code="AUDIO_EXTRACT_FAILED")
    return dest


def extract_audio(media_path, asset_dir, prefer=None):
    """优先用独立的 m4a 音轨，没有就从视频抽。统一输出 audio.wav。"""
    source = prefer if (prefer and os.path.exists(prefer)) else media_path
    return _ffmpeg_extract_wav(source, os.path.join(asset_dir, "audio.wav"))


# ---------------------------------------------------------------- 模型
def model_ref(model_size):
    """只认本地目录：工具调用里静默下几个 G 的模型是不可接受的。"""
    local = os.path.join(config.MODEL_DIR, "faster-whisper-" + str(model_size))
    if os.path.isfile(os.path.join(local, "model.bin")):
        return local
    raise ModelMissing(
        f"本地没有 Whisper 模型 {model_size}",
        hint=f"运行 python -m ytdip.fetch_model {model_size} 下载到 {config.MODEL_DIR}，"
             f"或在配置里换一个已下载的尺寸。")


def _candidates(device):
    if device == "cuda":
        return [("cuda", "float16"), ("cpu", "int8")]
    return [("cpu", "int8")]


def _get_model(ref, device, compute, log):
    key = (ref, device, compute)
    cached = _MODEL_CACHE.get(key)
    if cached is not None:
        return cached
    from faster_whisper import WhisperModel

    _MODEL_CACHE.clear()   # 只保留一个实例
    log(f"  加载模型 {os.path.basename(ref)} ({device}/{compute}) ...")
    model = WhisperModel(ref, device=device, compute_type=compute,
                         download_root=config.MODEL_DIR,
                         cpu_threads=config.CPU_THREADS)
    _MODEL_CACHE[key] = model
    return model


# ---------------------------------------------------------------- 幻觉过滤
def _norm(text):
    return _PUNCT.sub("", text or "")


def is_echo_of_prompt(text):
    """无语音时 Whisper 会把 initial_prompt 原样输出，必须丢掉。"""
    target, prompt = _norm(text), _norm(INITIAL_PROMPT)
    if not target:
        return True
    if target in prompt:
        return True
    if len(target) >= 8 and len(set(target) & set(prompt)) / max(1, len(set(target))) > 0.85:
        return True
    return False


def _run(model, audio, vad, language, total=0.0, progress=None, cancel=None, log=print):
    segments_iter, info = model.transcribe(
        audio,
        language=language,
        beam_size=5,
        vad_filter=vad,
        vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 200} if vad else None,
        condition_on_previous_text=False,
        initial_prompt=INITIAL_PROMPT,
    )
    kept = []
    for segment in segments_iter:
        if cancel and cancel():
            raise Canceled("转写已取消")
        text = (segment.text or "").strip()
        if progress and total:
            progress(min(float(segment.end), total), total)
        if not text or is_echo_of_prompt(text):
            continue
        kept.append({
            "idx": len(kept),
            "start": round(float(segment.start), 2),
            "end": round(float(segment.end), 2),
            "text": text,
        })
    return kept, info


def transcribe(wav_path, model_size=None, device=None, language=None,
               log=print, progress=None, cancel=None):
    """返回 {segments, meta}。VAD 判定无人声时自动关掉 VAD 再试一次。"""
    model_size = model_size or config.DEFAULT_MODEL
    device = device or config.DEFAULT_DEVICE
    language = language if language is not None else config.DEFAULT_LANG
    if str(language).lower() in ("auto", "none", ""):
        language = None

    register_cuda_dlls(log)
    audio = load_wav(wav_path)
    total = round(len(audio) / 16000.0, 2)

    errors = []
    silence = []
    for dev, compute in _candidates(device):
        if cancel and cancel():
            raise Canceled("转写已取消")
        try:
            ref = model_ref(model_size)
            model = _get_model(ref, dev, compute, log)

            log("  转写中（VAD 开启）...")
            segments, info = _run(model, audio, True, language,
                                  total=total, progress=progress, cancel=cancel, log=log)
            used_vad = True

            if not segments and not (cancel and cancel()):
                log("  VAD 没检出语音，关闭 VAD 重试一次 ...")
                segments, info = _run(model, audio, False, language,
                                      total=total, progress=progress, cancel=cancel, log=log)
                used_vad = False

            if not segments:
                silence.append(f"{dev}: 无语音")
                log("  未识别到任何语音")
                continue

            meta = {
                "model": model_size,
                "device": dev,
                "compute_type": compute,
                "language": getattr(info, "language", language),
                "audio_duration": total,
                "segment_count": len(segments),
                "vad": used_vad,
            }
            log(f"  转写完成：{len(segments)} 个片段")
            return {"segments": segments, "meta": meta}
        except Canceled:
            raise
        except ModelMissing:
            raise
        except Exception as exc:
            message = f"{dev}/{compute} 失败: {type(exc).__name__}: {str(exc)[:160]}"
            log("  " + message)
            errors.append(message)

    if silence and not errors:
        from .errors import NoSpeech
        raise NoSpeech("整段没有识别到人声（可能是纯音乐、纯画面或无对白作品）")
    raise PipelineError("转写失败，所有设备都不可用 -> " + " | ".join(errors + silence),
                        code="ASR_FAILED")
