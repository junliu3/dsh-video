"""JSONL 事件出口。

stdout 只写「一行一个 JSON」（给 DSH 插件解析），人类可读日志走 stderr。
这样命令行直接跑的时候也能看见进度，而机器解析永远不会被中文日志污染。
"""
import json
import os
import sys
import threading
import time


class Events:
    def __init__(self, job_id="", stream=None, echo=True, throttle=0.4):
        self.job_id = job_id
        self.stream = stream if stream is not None else sys.stdout
        self.echo = echo          # 是否把人类可读文本镜像到 stderr
        self.throttle = throttle  # 同一 stage 的进度最小间隔（秒）
        self._lock = threading.Lock()
        self._last_emit = {}
        self._last_pct = {}
        self.canceled = False

    # ---------------------------------------------------------------- 底层
    def emit(self, kind, **fields):
        payload = {"t": kind}
        if self.job_id:
            payload["job"] = self.job_id
        payload.update({k: v for k, v in fields.items() if v is not None})
        line = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            try:
                self.stream.write(line + "\n")
                self.stream.flush()
            except Exception:
                pass
        return payload

    def _say(self, text):
        if not self.echo or not text:
            return
        try:
            sys.stderr.write(str(text) + "\n")
            sys.stderr.flush()
        except Exception:
            pass

    # ---------------------------------------------------------------- 语义
    def start(self, **fields):
        return self.emit("start", **fields)

    def stage(self, name, msg=""):
        self._last_emit.pop(name, None)
        self._last_pct.pop(name, None)
        self._say(f"[{name}] {msg}" if msg else f"[{name}]")
        return self.emit("stage", stage=name, msg=msg or None)

    def progress(self, stage, done=None, total=None, msg=None, force=False):
        now = time.time()
        pct = None
        if done is not None and total:
            pct = max(0.0, min(100.0, done * 100.0 / total))
        last = self._last_emit.get(stage, 0)
        last_pct = self._last_pct.get(stage)
        due = force or (now - last) >= self.throttle
        jumped = pct is not None and (last_pct is None or pct - last_pct >= 1.0)
        if not (due or jumped):
            return None
        self._last_emit[stage] = now
        if pct is not None:
            self._last_pct[stage] = pct
        return self.emit("progress", stage=stage, done=done, total=total,
                         pct=round(pct, 1) if pct is not None else None, msg=msg)

    def log(self, msg, level="info"):
        self._say(msg)
        return self.emit("log", level=level, msg=str(msg))

    def result(self, data):
        return self.emit("result", data=data)

    def error(self, code, msg, hint=""):
        return self.emit("error", code=code, msg=msg, hint=hint)


def checker(events, marker_path=""):
    """返回一个 cancel 判定函数：内存标记 或 取消文件存在 都算取消。

    用取消文件是为了让 Node 侧能「优雅取消」：先落标记，等 Python 自己
    收尾（删临时目录、杀 msedge），超时才强杀进程树。
    """
    def canceled():
        if events is not None and events.canceled:
            return True
        if marker_path and os.path.exists(marker_path):
            return True
        return False

    return canceled
