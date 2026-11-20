"""每视频独占锁：防止同一 video_id 被两个作业同时写，互相覆盖 media.json。"""
import contextlib
import os

from . import store
from .errors import BusyError

if os.name == "nt":
    import msvcrt
else:
    import fcntl


@contextlib.contextmanager
def video_lock(video_id):
    path = os.path.join(store.asset_dir(video_id), ".lock")
    handle = open(path, "a+b")
    locked = False
    try:
        try:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError:
            raise BusyError(f"视频 {video_id} 正在处理中")
        yield path
    finally:
        if locked:
            try:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
        handle.close()
