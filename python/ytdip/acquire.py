"""采集调度：本地文件 / 抖音 CDP / yt-dlp 通用站点，三条路汇成同一个结果结构。"""
import os
import re

from . import config, douyin_cdp, store, ytdlp_src
from .errors import BadInput

_DOUYIN_HOSTS = re.compile(r"(douyin\.com|iesdouyin\.com|amemv\.com)", re.I)
_HTTP = re.compile(r"^https?://", re.I)
_NUMERIC_ID = re.compile(r"^\d{15,25}$")

AUDIO_EXT = {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".opus", ".wma"}


def classify(source):
    """返回 local / douyin / generic。"""
    text = (source or "").strip()
    if not text:
        raise BadInput("没有提供链接或文件路径")
    if _HTTP.match(text):
        if _DOUYIN_HOSTS.search(text) and not config.DOUYIN_VIA_YTDLP:
            return "douyin"
        return "generic"
    if os.path.isfile(text):
        return "local"
    if _NUMERIC_ID.match(text):
        return "douyin"
    raise BadInput("链接格式不对：既不是 http(s) 地址，也不是本地文件")


def _local_meta(source, local_id=None):
    path = os.path.abspath(source)
    stem = os.path.splitext(os.path.basename(path))[0]
    video_id = store.sanitize_id(local_id or ("local-" + stem[:40]), fallback="local")
    duration, _ = douyin_cdp.probe_file(path)
    kind = "audio" if os.path.splitext(path)[1].lower() in AUDIO_EXT else "video"
    return {
        "kind": "local",
        "video_id": video_id,
        "title": stem,
        "duration_sec": float(duration or 0),
        "platform": "local",
        "media_path": path,
        "media_kind": kind,
    }


def resolve(source, local_id=None, log=print, cancel=None):
    """下载前先把 ID 定下来，才能上锁、才能命名目录。"""
    kind = classify(source)
    if kind == "local":
        return _local_meta(source, local_id=local_id)
    if kind == "douyin":
        video_id = douyin_cdp.parse_video_id(source)
        if not video_id:
            raise BadInput("抖音链接里找不到作品 ID（15-25 位数字）")
        return {"kind": "douyin", "video_id": video_id, "title": "", "duration_sec": 0,
                "platform": "douyin"}
    meta = ytdlp_src.probe(source, log=log, cancel=cancel)
    return {"kind": "generic", "video_id": meta["video_id"], "title": meta["title"],
            "duration_sec": meta["duration_sec"], "platform": meta["platform"], "meta": meta}


def acquire(source, resolved, audio_only=False, log=print, progress=None, cancel=None):
    if resolved["kind"] == "local":
        log(f"  本地文件 {os.path.basename(resolved['media_path'])}  "
            f"{resolved['duration_sec']:.1f} 秒")
        return {
            "video_id": resolved["video_id"],
            "source_url": "",
            "platform": "local",
            "title": resolved["title"],
            "duration_sec": resolved["duration_sec"],
            "cover_url": "",
            "cover_path": "",
            "audio_src": "",
            "media_path": resolved["media_path"],
            "media_kind": resolved["media_kind"],
        }

    if resolved["kind"] == "douyin":
        directory = store.asset_dir(resolved["video_id"])
        return douyin_cdp.acquire(source, directory, audio_only=audio_only, log=log,
                                  progress=progress, cancel=cancel)

    return ytdlp_src.acquire(source, audio_only=audio_only, log=log,
                             progress=progress, cancel=cancel,
                             meta=resolved.get("meta"))
