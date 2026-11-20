"""通用站点采集通道：把随包的 yt-dlp 当库调用。

覆盖 B 站、YouTube、微博、小红书等 yt-dlp 支持的站点：
    - 解析：标题、时长、封面、站点、清晰度概况
    - 下载：视频（自动合流 mp4）或纯音频（转 mp3）
    - 进度：download 阶段按字节回报
    - 取消：进度钩子里抛异常中断，外层再确认一次

抖音仍默认走 CDP 通道（1080P 无水印、免 cookie）；把 YTDIP_DOUYIN_VIA_YTDLP
置 1 可以强制走这里。
"""
import glob
import os
import sys
import urllib.request

from . import config, store
from .errors import LoginRequired, NoStream, PipelineError, Canceled, UnsupportedSite

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")


def _load_ytdlp():
    vendor = config.VENDOR_DIR
    if os.path.isdir(vendor) and vendor not in sys.path:
        sys.path.insert(0, vendor)
    try:
        import yt_dlp  # noqa: WPS433 - 运行期导入，避免影响不下载的调用
        return yt_dlp
    except Exception as exc:
        raise PipelineError(
            f"yt-dlp 不可用: {type(exc).__name__}: {exc}",
            code="YTDLP_MISSING",
            hint="运行 npm run bootstrap（或 pip install yt-dlp）安装依赖；"
                 f"也可以把 yt_dlp 源码放到 {vendor}。")


def base_options():
    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "noprogress": True,
        "consoletitle": False,
        "ffmpeg_location": config.FFMPEG_DIR,
        "socket_timeout": 25,
        "retries": 3,
        "fragment_retries": 3,
        "extractor_retries": 2,
        "ignoreerrors": False,
        "windowsfilenames": True,
        "restrictfilenames": False,
    }


def _platform_of(info):
    name = (info.get("extractor_key") or info.get("extractor") or "web")
    return str(name).split(":")[0].strip().lower() or "web"


def _map_error(exc, url):
    text = str(exc)
    lowered = text.lower()
    if "login" in lowered or "sign in" in lowered or "cookies" in lowered or "会员" in text:
        return LoginRequired(f"站点要求登录/会员权限：{text[:160]}",
                             hint="B 站高清/大会员内容需要 Cookie，当前版本未接入 cookie 导入。")
    if "unsupported url" in lowered or "no suitable" in lowered:
        return UnsupportedSite(f"yt-dlp 不支持该链接：{text[:160]}")
    if "private" in lowered or "unavailable" in lowered or "not available" in lowered:
        return NoStream(f"内容不可用：{text[:160]}", hint="作品可能已删除、地区限制或仅粉丝可见。")
    return PipelineError(f"下载失败：{text[:200]}", code="DOWNLOAD_FAILED",
                         hint=f"原始链接：{url}")


def probe(url, log=print, cancel=None):
    """只解析不下载，用于预览与选路。"""
    yt_dlp = _load_ytdlp()
    options = base_options()
    options["skip_download"] = True
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
            info = ydl.sanitize_info(info)
    except Exception as exc:
        raise _map_error(exc, url)
    if cancel and cancel():
        raise Canceled("已取消")
    if not info:
        raise NoStream("解析不到任何内容")
    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            raise NoStream("列表里没有可下载的条目")
        info = entries[0]
    log(f"  站点: {_platform_of(info)}  标题: {info.get('title')}")
    return {
        "video_id": store.sanitize_id(info.get("id"), fallback="web"),
        "source_url": info.get("webpage_url") or url,
        "platform": _platform_of(info),
        "title": info.get("title") or "",
        "duration_sec": float(info.get("duration") or 0),
        "cover_url": info.get("thumbnail") or "",
        "is_live": bool(info.get("is_live")),
        "uploader": info.get("uploader") or info.get("channel") or "",
    }


def _download_file(url, dest):
    request = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read()
    if len(data) < 1024:
        return ""
    path = dest + ".jpg"
    with open(path, "wb") as handle:
        handle.write(data)
    return path


def acquire(url, audio_only=False, log=print, progress=None, cancel=None, meta=None):
    """下载一个作品，返回与抖音通道同构的元数据。"""
    yt_dlp = _load_ytdlp()
    meta = meta or probe(url, log=log, cancel=cancel)
    dest_dir = store.asset_dir(meta["video_id"])

    def hook(payload):
        if cancel and cancel():
            raise Canceled("已取消")
        if payload.get("status") != "downloading":
            return
        total = payload.get("total_bytes") or payload.get("total_bytes_estimate") or 0
        done = payload.get("downloaded_bytes") or 0
        if total and progress:
            progress(done, total)

    options = base_options()
    options.update({
        "paths": {"home": dest_dir},
        "outtmpl": "%(id)s.%(ext)s",
        "overwrites": True,
        "progress_hooks": [hook],
    })
    if audio_only:
        options["format"] = "bestaudio/best"
        options["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "0"},
            {"key": "FFmpegMetadata", "add_metadata": True},
        ]
    else:
        options["format"] = "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b"
        options["merge_output_format"] = "mp4"

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.extract_info(url, download=True)
    except Canceled:
        raise
    except Exception as exc:
        if cancel and cancel():
            raise Canceled("已取消")
        raise _map_error(exc, url)

    if cancel and cancel():
        raise Canceled("已取消")

    video_id = meta["video_id"]
    extension = ".mp3" if audio_only else ".mp4"
    target = os.path.join(dest_dir, video_id + extension)
    if not os.path.exists(target):
        candidates = [p for p in glob.glob(os.path.join(dest_dir, video_id + ".*"))
                      if not p.endswith((".part", ".ytdl", ".temp", ".jpg"))]
        candidates.sort(key=lambda p: os.path.getsize(p), reverse=True)
        target = candidates[0] if candidates else ""
    if not target or not os.path.exists(target):
        raise NoStream("下载完成但找不到产物文件", hint=f"目录：{dest_dir}")

    result = dict(meta)
    result["media_path"] = target
    result["media_kind"] = "audio" if audio_only else "video"
    result["audio_src"] = ""
    result["cover_path"] = ""
    if meta.get("cover_url"):
        try:
            result["cover_path"] = _download_file(meta["cover_url"],
                                                  os.path.join(dest_dir, video_id + ".cover"))
        except Exception as exc:
            log(f"  封面没抓到（不影响正文）: {type(exc).__name__}")
    log(f"  已保存 {os.path.basename(target)} "
        f"{os.path.getsize(target) / 1048576:.1f}MB")
    return result
