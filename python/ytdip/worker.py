"""JSONL 机器入口：DSH 插件唯一的调用点。

    python -m ytdip.worker --job '{"source":"...","jobId":"j_01"}'

约定：
    stdout  每行一个 JSON 事件（start / stage / progress / log / result / error）
    stderr  人类可读日志、库的零散输出、异常栈
    退出码  0 成功或已取消；1 失败

取消有两种方式，任一生效：
    1. 进程收到 SIGTERM / SIGINT / SIGBREAK
    2. <STATE_DIR>/jobs/<jobId>.cancel 文件出现（Node 先落标记，等优雅收尾）
"""
import argparse
import json
import os
import signal
import sys
import traceback

from . import config, events, pipeline
from .errors import Canceled, PipelineError, to_payload


def _load_job(args):
    if args.job_file:
        with open(args.job_file, "r", encoding="utf-8") as handle:
            return json.load(handle)
    if args.job:
        return json.loads(args.job)
    if not sys.stdin.isatty():
        text = sys.stdin.read()
        if text.strip():
            return json.loads(text)
    raise SystemExit("需要 --job / --job-file，或从 stdin 传入 JSON")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ytdip.worker", description="yt-dip JSONL worker")
    parser.add_argument("--job", help="作业 JSON 字符串")
    parser.add_argument("--job-file", help="作业 JSON 文件路径")
    parser.add_argument("--job-id", default="", help="作业 ID（用于取消标记）")
    args = parser.parse_args(argv)

    try:
        config.ensure_dirs()
    except Exception:
        pass

    real_stdout = sys.stdout
    try:
        real_stdout.reconfigure(encoding="utf-8", newline="\n")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    job = _load_job(args)
    job_id = args.job_id or str(job.get("jobId") or "")
    emit = events.Events(job_id=job_id, stream=real_stdout)
    marker = os.path.join(config.JOB_DIR, job_id + ".cancel") if job_id else ""
    cancel = events.checker(emit, marker)

    # 库里的零散 print 一律改道 stderr，绝不污染 stdout 的 JSONL
    sys.stdout = sys.stderr

    def on_signal(_signum, _frame):
        emit.canceled = True

    for name in ("SIGTERM", "SIGINT", "SIGBREAK"):
        handler = getattr(signal, name, None)
        if handler is not None:
            try:
                signal.signal(handler, on_signal)
            except Exception:
                pass

    try:
        result = pipeline.run(job, emit, cancel)
        emit.result(result)
        return 0
    except Canceled as exc:
        emit.error("CANCELED", str(exc) or "任务已取消", "已按请求取消")
        return 0
    except PipelineError as exc:
        emit.error(exc.code, exc.message, exc.hint)
        return 1
    except Exception as exc:  # 兜底：保证宿主永远能拿到结构化错误
        payload = to_payload(exc)
        emit.error(payload["code"], payload["msg"], payload["hint"])
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
