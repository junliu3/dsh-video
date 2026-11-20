"""人类入口：保留原来「粘个链接就出文档」的用法。

    python -m ytdip.cli "https://www.douyin.com/video/xxx"
    python -m ytdip.cli "https://www.bilibili.com/video/BVxxx" --audio
    python -m ytdip.cli --file "D:\\某个视频.mp4" --id 我的测试
    python -m ytdip.cli "链接" --json          # 机器模式（JSONL）
"""
import argparse
import os
import sys

from . import config, events, pipeline
from .errors import PipelineError


class ConsoleEvents:
    """把事件流翻译成人话；进度只在百分比跳变时打一行，避免刷屏。"""

    def __init__(self):
        self._last = {}
        self.canceled = False

    def start(self, **fields):
        pass

    def stage(self, name, msg=""):
        print(f"\n[{name}] {msg}")

    def progress(self, stage, done=None, total=None, msg=None, force=False):
        if not total:
            return
        pct = int(done * 100 / total)
        if pct // 10 == self._last.get(stage, -1) // 10 and not force:
            return
        self._last[stage] = pct
        sys.stdout.write(f"\r    {stage} {pct:3d}%")
        sys.stdout.flush()
        if pct >= 100:
            sys.stdout.write("\n")

    def log(self, msg, level="info"):
        print(msg)

    def result(self, data):
        pass

    def error(self, code, msg, hint=""):
        print(f"\n[失败] {code}: {msg}", file=sys.stderr)
        if hint:
            print(f"       {hint}", file=sys.stderr)


def build_job(args):
    return {
        "source": args.link or args.file,
        "id": args.local_id,
        "audioOnly": args.audio,
        "downloadOnly": args.download_only,
        "model": args.model,
        "device": args.device,
        "language": args.lang,
        "keepWav": args.keep_wav,
        "dropMedia": args.drop_media,
        "emitDocx": not args.no_docx,
    }


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(prog="ytdip", description="链接 → 下载 → 转写 → 文档")
    parser.add_argument("link", nargs="?", help="作品链接或 ID")
    parser.add_argument("--file", help="本地音视频，跳过下载")
    parser.add_argument("--id", dest="local_id", help="配合 --file 指定资料目录名")
    parser.add_argument("--audio", action="store_true", help="只下音频（mp3）")
    parser.add_argument("--download-only", action="store_true", help="只下载，不转写")
    parser.add_argument("--model", default=None,
                        help=f"Whisper 模型，默认 {config.DEFAULT_MODEL}")
    parser.add_argument("--device", default=None, choices=["auto", "cuda", "cpu"])
    parser.add_argument("--lang", default=None, help="语言代码，默认 zh；en / auto")
    parser.add_argument("--keep-wav", action="store_true", help="保留中间 wav")
    parser.add_argument("--drop-media", action="store_true", help="成文后删除原视频")
    parser.add_argument("--no-docx", action="store_true", help="不生成 Word")
    parser.add_argument("--json", action="store_true", help="输出 JSONL 事件（机器模式）")
    args = parser.parse_args(argv)

    if not args.link and not args.file:
        parser.print_help()
        return 2

    job = build_job(args)
    job["jobId"] = job.get("jobId") or ""

    if args.json:
        emit = events.Events(job_id="", stream=sys.stdout, echo=True)
        cancel = events.checker(emit, "")
        real_stdout = sys.stdout
        sys.stdout = sys.stderr
        try:
            result = pipeline.run(job, emit, cancel)
            emit.result(result)
            return 0
        except PipelineError as exc:
            emit.error(exc.code, exc.message, exc.hint)
            return 1
        except Exception as exc:
            emit.error("INTERNAL", f"{type(exc).__name__}: {exc}", "")
            return 1
        finally:
            sys.stdout = real_stdout

    emit = ConsoleEvents()
    try:
        result = pipeline.run(job, emit, None)
    except PipelineError as exc:
        emit.error(exc.code, exc.message, exc.hint)
        return 1
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        return 130

    print("\n" + "=" * 58)
    print("完成，产物目录：")
    print("  " + result["dir"])
    for name in result["files"]:
        print("   - " + name)
    meta = result.get("meta") or {}
    if meta:
        print(f"\n{meta.get('segments', 0)} 段 / 约 {meta.get('chars', 0)} 字"
              f" / 模型 {meta.get('asrModel', '')}")
    print(f"总耗时 {result['elapsedSec']:.1f} 秒")
    print("=" * 58)
    return 0


if __name__ == "__main__":
    sys.exit(main())
