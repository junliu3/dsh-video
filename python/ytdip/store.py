"""资料目录与元数据契约。

一条作品一个目录，目录名是纯 ASCII 的 video_id；中文标题只作为字段存在
media.json 里，绝不参与路径命名 —— 这条约定是整套资料库能搬迁、能去重的基础。
"""
import datetime
import json
import os
import re

from . import config

_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]+")
SCHEMA_VERSION = 1


def sanitize_id(raw, fallback="item"):
    """把站点返回的 ID 收敛成安全目录名；中文/空格/斜杠一律替换。"""
    text = _SAFE_ID.sub("-", str(raw or "")).strip("-")
    text = text[:80]
    return text or fallback


def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def asset_dir(video_id):
    path = os.path.join(config.LIB_ROOT, video_id)
    os.makedirs(path, exist_ok=True)
    return path


def save_json(path, obj):
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def media_json_path(directory):
    return os.path.join(directory, "media.json")


def write_media(directory, record):
    save_json(media_json_path(directory), record)


def read_media(directory):
    return load_json(media_json_path(directory), {})


def new_record(video_id, source_url, platform="douyin"):
    return {
        "schema_version": SCHEMA_VERSION,
        "video_id": video_id,
        "platform": platform,
        "source_url": source_url,
        "title": "",
        "duration_sec": 0.0,
        "cover_path": "",
        "media_path": "",
        "media_kind": "",
        "audio_path": "",
        "captured_at": now_iso(),
        "pipeline": {},
    }


# ---------------------------------------------------------------- 资料库浏览
_SKIP_DIRS = {".state", "__pycache__"}


def list_items(limit=50, keyword=""):
    """按采集时间倒序列出资料库条目，供 douyin_library 工具使用。"""
    root = config.LIB_ROOT
    if not os.path.isdir(root):
        return []
    keyword = (keyword or "").strip().lower()
    items = []
    for name in os.listdir(root):
        if name in _SKIP_DIRS or name.startswith("."):
            continue
        directory = os.path.join(root, name)
        if not os.path.isdir(directory):
            continue
        record = read_media(directory)
        title = record.get("title") or ""
        if keyword and keyword not in title.lower() and keyword not in name.lower():
            continue
        files = sorted(f for f in os.listdir(directory)
                       if not f.startswith(".") and not f.endswith((".part", ".lock")))
        items.append({
            "videoId": name,
            "title": title or name,
            "platform": record.get("platform", ""),
            "durationSec": record.get("duration_sec") or 0,
            "capturedAt": record.get("captured_at", ""),
            "hasReport": "report.md" in files,
            "files": files,
            "dir": directory,
        })
    items.sort(key=lambda x: x.get("capturedAt") or "", reverse=True)
    return items[:max(1, int(limit or 50))]


def read_document(video_id, max_chars=6000):
    """取一条资料的正文；优先 report.md，退化到 transcript.txt。"""
    directory = os.path.join(config.LIB_ROOT, video_id)
    if not os.path.isdir(directory):
        return None, ""
    for name in ("report.md", "transcript.txt"):
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            if max_chars and len(text) > max_chars:
                text = text[:max_chars] + "\n\n…（已截断）"
            return path, text
    return None, ""
