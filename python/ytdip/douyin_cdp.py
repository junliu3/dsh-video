"""抖音采集通道：无头 Edge + CDP 读真实播放地址，再直接 HTTP 下载。

为什么不用 yt-dlp：抖音要签名请求头，Edge 的 cookie 又被系统级密钥加密，
yt-dlp 会报 "Fresh cookies are needed"。这条通道不需要登录、不需要 cookie，
实测能拿 1080P 无水印 mp4（H.264 + AAC）。

相比原版做了四处改造：
  1. 去掉了全局 print，改成 log/progress/cancel 回调
  2. CDP 端口默认动态分配（0 = 空闲端口），并发不再串台
  3. Edge 路径三级探测（配置 → 常见安装路径 → where msedge）
  4. 下载/等待流程里插入取消检查点
"""
import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time

import requests

from . import config
from .errors import BadInput, Canceled, EdgeMissing, NoStream, PipelineError

try:
    import websockets
    from websockets.exceptions import ConnectionClosed as _ConnectionClosed
    _CLOSED_ERRORS = (_ConnectionClosed, OSError)
except Exception:  # pragma: no cover - 依赖缺失时由 doctor 报出来
    websockets = None
    _CLOSED_ERRORS = (OSError,)

AUDIO_HINTS = ("media-audio", "media-mp3", "media-aac", "audio-und")
UA_FALLBACK = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")

_EDGE_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)


def headers_for(ua):
    return {
        "User-Agent": ua or UA_FALLBACK,
        "Referer": "https://www.douyin.com/",
        "Accept": "*/*",
    }


def find_edge():
    """配置优先；其次常见安装路径；最后问系统 PATH。"""
    if config.EDGE and os.path.isfile(config.EDGE):
        return config.EDGE
    for path in _EDGE_CANDIDATES:
        if os.path.isfile(path):
            return path
    found = shutil.which("msedge") or shutil.which("msedge.exe")
    if found:
        return found
    raise EdgeMissing("未找到 Microsoft Edge")


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def parse_video_id(text):
    match = re.search(r"(\d{15,25})", str(text or ""))
    return match.group(1) if match else ""


def page_url(video_id):
    return f"https://www.douyin.com/video/{video_id}"


def launch(edge, profile, page, port):
    return subprocess.Popen([
        edge, "--headless=new", f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}", "--no-first-run", "--disable-gpu",
        "--no-default-browser-check", "--autoplay-policy=no-user-gesture-required",
        "--mute-audio", "--window-size=1280,900", page,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ws_url(port, cancel=None, log=print):
    for _ in range(40):
        if cancel and cancel():
            raise Canceled("已取消")
        try:
            pages = requests.get(f"http://127.0.0.1:{port}/json/list", timeout=2).json()
            for item in pages:
                if item.get("type") == "page" and item.get("webSocketDebuggerUrl"):
                    return item["webSocketDebuggerUrl"]
        except Exception:
            pass
        time.sleep(0.5)
    return None


async def _probe(ws_endpoint, log, cancel):
    captured = []
    closed = {"why": ""}

    async with websockets.connect(ws_endpoint, max_size=40 * 1024 * 1024,
                                  open_timeout=15, close_timeout=1) as ws:
        counter = [0]

        async def watch():
            """取消/总超时看门狗：阻塞在 recv 上时只有关连接才能唤醒它。"""
            deadline = time.monotonic() + 180
            while True:
                if cancel and cancel():
                    closed["why"] = "cancel"
                    await ws.close()
                    return
                if time.monotonic() > deadline:
                    closed["why"] = "timeout"
                    await ws.close()
                    return
                await asyncio.sleep(0.4)

        async def call(method, params=None):
            counter[0] += 1
            mid = counter[0]
            await ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == mid:
                    return msg
                if msg.get("method") == "Network.requestWillBeSent":
                    url = msg["params"]["request"]["url"]
                    if ("douyinvod" in url or "/tos/" in url
                            or re.search(r"\.(mp4|m4a|mp3|webm)(\?|$)", url)):
                        captured.append(url)

        watcher = asyncio.create_task(watch())
        try:
            await call("Network.enable")
            await call("Runtime.enable")

            async def js(expr):
                result = await call("Runtime.evaluate", {"expression": expr, "returnByValue": True})
                return result.get("result", {}).get("result", {}).get("value")

            def audio_captured():
                return any(any(hint in u for hint in AUDIO_HINTS) for u in captured)

            title = ""
            deadline = time.time() + 30
            while time.time() < deadline:
                if cancel and cancel():
                    raise Canceled("已取消")
                await asyncio.sleep(1)
                current = (await js("document.title||''") or "").strip()
                if current and current not in ("抖音", "抖音-记录美好生活"):
                    title = current
                    break
                if audio_captured():
                    break
            settle = 3 if audio_captured() else 6   # DASH 的另一条流来得晚
            for _ in range(settle):
                if cancel and cancel():
                    raise Canceled("已取消")
                await asyncio.sleep(1)

            info = {"title": title or (await js("document.title||''") or "")}
            for key, expr in [
                ("ua", "navigator.userAgent"),
                ("sources", "Array.from(document.querySelectorAll('video source')).map(s=>s.src).join('\\n')"),
                ("poster", "((document.querySelector('video')||{}).poster)||''"),
                ("og_image", "((document.querySelector('meta[property=\"og:image\"]')||{}).content)||''"),
                ("og_title", "((document.querySelector('meta[property=\"og:title\"]')||{}).content)||''"),
                ("duration", "((document.querySelector('video')||{}).duration)||0"),
                ("text", "(document.body.innerText||'').slice(0,200)"),
            ]:
                info[key] = await js(expr)
            if not (info.get("title") or "").strip() and (info.get("og_title") or "").strip():
                info["title"] = info["og_title"]
            info["captured"] = list(dict.fromkeys(captured))
            return info
        except _CLOSED_ERRORS:
            if closed["why"] == "cancel" or (cancel and cancel()):
                raise Canceled("已取消")
            raise NoStream("CDP 连接中断（浏览器关闭或页面无响应）")
        finally:
            watcher.cancel()


def inspect_page(page, log=print, cancel=None):
    """开一个无头 Edge，读完页面信息就关掉。"""
    edge = find_edge()
    port = config.CDP_PORT or free_port()
    profile = tempfile.mkdtemp(prefix="dsh-ytdip-")
    log(f"  Edge CDP 端口 {port}")
    proc = launch(edge, profile, page, port)
    try:
        endpoint = ws_url(port, cancel=cancel, log=log)
        if not endpoint:
            raise NoStream("CDP 连不上（无头 Edge 没起来）", hint="检查 Edge 是否可用，或被安全软件拦截。")
        return asyncio.run(_probe(endpoint, log, cancel))
    finally:
        _kill_tree(proc.pid, proc)
        shutil.rmtree(profile, ignore_errors=True)


def _kill_tree(pid, proc=None):
    """强制清理 Edge 进程树。

    注意：taskkill /T /F 已经把整棵树杀掉，这里不能再 proc.wait(8) ——
    实测那会让取消多等 8 秒才退出，宿主会误判为「没响应」直接强杀。
    """
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=6)
        except Exception:
            pass
        if proc is not None:
            try:
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        return
    if proc is not None:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def head_info(url, ua):
    """只看响应头：拿到体积和类型就断开，用来给候选地址排大小。"""
    try:
        with requests.get(url, headers=headers_for(ua), stream=True, timeout=40,
                          allow_redirects=True) as response:
            if response.status_code not in (200, 206):
                return response.status_code, 0, ""
            return (response.status_code,
                    int(response.headers.get("Content-Length") or 0),
                    response.headers.get("Content-Type", ""))
    except Exception as exc:
        return 0, 0, f"error:{type(exc).__name__}"


def rank_urls(urls, ua, log=print, cancel=None):
    """按体积从大到小排（抖音会混进几 MB 的预加载片段）。"""
    ranked = []
    for url in urls[:8]:
        if cancel and cancel():
            raise Canceled("已取消")
        code, size, ctype = head_info(url, ua)
        log(f"  候选 {size / 1048576:6.1f}MB  HTTP {code}  {ctype}")
        if code in (200, 206) and size > 0:
            ranked.append((size, url))
    ranked.sort(key=lambda item: -item[0])
    return [url for _, url in ranked]


def download(url, ua, dest_dir, base_name, ext=".mp4", min_bytes=30 * 1024,
             log=print, progress=None, cancel=None):
    try:
        with requests.get(url, headers=headers_for(ua), stream=True, timeout=90,
                          allow_redirects=True) as response:
            if response.status_code not in (200, 206):
                log(f"  HTTP {response.status_code} {url[:70]}")
                return None, 0
            total = int(response.headers.get("Content-Length") or 0)
            log(f"  HTTP {response.status_code} {response.headers.get('Content-Type','')} "
                f"{total / 1048576:.1f}MB")
            tmp = os.path.join(dest_dir, base_name + ".part")
            got = 0
            with open(tmp, "wb") as handle:
                for chunk in response.iter_content(1 << 16):
                    if cancel and cancel():
                        handle.close()
                        try:
                            os.remove(tmp)
                        except Exception:
                            pass
                        raise Canceled("下载已取消")
                    if chunk:
                        handle.write(chunk)
                        got += len(chunk)
                        if progress and total:
                            progress(got, total)
            if got < min_bytes:
                log(f"  太小（{got} 字节），跳过")
                os.remove(tmp)
                return None, 0
            final = os.path.join(dest_dir, base_name + ext)
            if os.path.exists(final):
                os.remove(final)
            os.replace(tmp, final)
            return final, got
    except Canceled:
        raise
    except Exception as exc:
        log(f"  异常 {type(exc).__name__}: {exc}")
        return None, 0


def probe_file(path):
    try:
        result = subprocess.run(
            [config.FFPROBE, "-v", "error", "-show_entries",
             "format=duration:stream=codec_type,codec_name,width,height",
             "-of", "json", path],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
        data = json.loads(result.stdout or "{}")
        duration = float(data.get("format", {}).get("duration") or 0)
        streams = [(s.get("codec_type"), s.get("codec_name"), s.get("width"), s.get("height"))
                   for s in data.get("streams", [])]
        return duration, streams
    except Exception as exc:
        return 0.0, [("probe-error", str(exc), 0, 0)]


def has_audio(streams):
    return any(stream[0] == "audio" for stream in streams)


def run_ffmpeg(args):
    return subprocess.run([config.FFMPEG, "-hide_banner", "-loglevel", "error", "-y"] + args,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def ffmpeg_tail(result):
    lines = [line for line in (result.stderr or "").strip().splitlines() if line.strip()]
    return lines[-1] if lines else "未知错误"


def pick_stream(urls, ua, dest_dir, name, ext, expect_dur, require_audio=False,
                log=print, progress=None, cancel=None):
    """按体积排序挨个下，用时长验证是不是完整那条；不对就丢掉换下一个。"""
    for index, url in enumerate(rank_urls(urls, ua, log=log, cancel=cancel), 1):
        path, size = download(url, ua, dest_dir, f"{name}.cand{index}", ext=ext,
                              log=log, progress=progress, cancel=cancel)
        if not path:
            continue
        duration, streams = probe_file(path)
        log(f"  第 {index} 个：{duration:.1f} 秒，{size / 1048576:.1f}MB，流 {streams}")
        if require_audio and not has_audio(streams):
            log("  这条没音轨，换下一个")
            os.remove(path)
            continue
        if expect_dur and duration and abs(duration - expect_dur) > max(3.0, expect_dur * 0.08):
            log(f"  时长对不上（页面是 {expect_dur:.1f} 秒），换下一个")
            os.remove(path)
            continue
        return path, size, duration, streams
    return None, 0, 0.0, []


def mux_av(video_path, audio_path, dest_mp4, title, log=print):
    """画面 + 声音合成一个 mp4（不重新编码）。"""
    result = run_ffmpeg(["-i", video_path, "-i", audio_path,
                         "-map", "0:v:0", "-map", "1:a:0", "-c", "copy",
                         "-movflags", "+faststart",
                         "-metadata", "title=" + (title or ""), dest_mp4])
    if result.returncode != 0 or not os.path.exists(dest_mp4):
        log("音视频合并不上: " + ffmpeg_tail(result))
        return None
    return dest_mp4


def fetch_cover(url, ua, dest_dir, log=print):
    """顺手抓封面图；只认 JPEG，其它格式 mp3 装不进。"""
    if not url:
        return None
    try:
        response = requests.get(url, timeout=30, headers=headers_for(ua))
        if response.ok and len(response.content) > 1024:
            path = os.path.join(dest_dir, "_cover.part")
            with open(path, "wb") as handle:
                handle.write(response.content)
            if response.content[:3] == b"\xff\xd8\xff":
                return path
            os.remove(path)
    except Exception as exc:
        log(f"  封面没抓到（不影响正文）: {type(exc).__name__}")
    return None


def to_mp3(src, title, cover_url, ua, dest_dir, out_base=None, log=print):
    if not os.path.exists(config.FFMPEG):
        log("找不到 ffmpeg，无法转 mp3")
        return None
    base = out_base or os.path.splitext(os.path.basename(src))[0]
    out = os.path.join(dest_dir, base + ".mp3")
    tmp = os.path.join(dest_dir, base + ".tmp.mp3")
    result = run_ffmpeg(["-i", src, "-vn", "-c:a", "libmp3lame", "-q:a", "0",
                         "-metadata", "title=" + (title or ""), "-metadata", "comment=douyin", tmp])
    if result.returncode != 0 or not os.path.exists(tmp):
        log("转 mp3 失败: " + ffmpeg_tail(result))
        return None
    cover = fetch_cover(cover_url, ua, dest_dir, log=log) if cover_url else None
    done = False
    if cover:
        second = run_ffmpeg(["-i", tmp, "-i", cover, "-map", "0:a", "-map", "1:v",
                             "-c", "copy", "-id3v2_version", "3",
                             "-metadata:s:v", "title=Album cover",
                             "-metadata:s:v", "comment=Cover (front)", out])
        os.remove(cover)
        done = second.returncode == 0 and os.path.exists(out)
        if not done:
            log("封面没嵌进去（mp3 照样能用）")
    if not done:
        if os.path.exists(out):
            os.remove(out)
        os.replace(tmp, out)
    elif os.path.exists(tmp):
        os.remove(tmp)
    return out


def split_urls(info):
    """把页面里拿到的地址分成「画面流」和「声音流」。"""
    urls = [u for u in (info.get("sources") or "").split("\n") if u.startswith("http")]
    urls += [u for u in (info.get("captured") or []) if u not in urls]
    audio = [u for u in urls if any(hint in u for hint in AUDIO_HINTS)]
    video = [u for u in urls if u not in audio]
    return video, audio


def acquire(link, dest_dir, audio_only=False, log=print, progress=None, cancel=None):
    """下载一条抖音作品，返回元数据。不负责转写。"""
    video_id = parse_video_id(link)
    if not video_id:
        raise BadInput("链接里找不到视频 ID（需要 15-25 位数字）")

    page = page_url(video_id)
    log(f"  视频 ID: {video_id}")
    info, video_urls, audio_urls = {}, [], []
    for attempt in range(1, 4):
        if cancel and cancel():
            raise Canceled("已取消")
        log(f"  第 {attempt} 次读取页面 ...")
        info = inspect_page(page, log=log, cancel=cancel)
        video_urls, audio_urls = split_urls(info)
        if video_urls or audio_urls:
            break
        log("  页面没给出播放地址，重试")
        time.sleep(3)

    if not video_urls and not audio_urls:
        raise NoStream("页面里没找到播放地址",
                       hint=f"作品可能已删除、需登录或页面改版。页面文本：{(info.get('text') or '')[:80]}")

    title = (info.get("title") or "").replace(" - 抖音", "").strip() or video_id
    ua = info.get("ua")
    poster = info.get("poster") or info.get("og_image") or ""
    try:
        expect = float(info.get("duration") or 0)
    except Exception:
        expect = 0.0

    log(f"  标题: {title}")
    log(f"  页面时长: {expect:.1f} 秒" if expect else "  页面时长: 未知")
    log(f"  候选流: 画面 {len(video_urls)} 条 / 声音 {len(audio_urls)} 条")

    def on_bytes(done, total):
        if progress:
            progress(done, total)

    track = (lambda d, t: on_bytes(d, t)) if progress else None

    # 声音流优先单独下：体积小、可校验画面完整性、也正好是 ASR 要的输入
    audio_path, audio_dur = "", 0.0
    if audio_urls:
        audio_path, _, audio_dur, _ = pick_stream(
            audio_urls, ua, dest_dir, video_id + ".audio", ".m4a", expect,
            require_audio=True, log=log, progress=track, cancel=cancel)
        audio_path = audio_path or ""
        if not audio_path:
            log("  声音流没下下来，将退回视频里的音轨")

    result = {
        "video_id": video_id,
        "source_url": page,
        "platform": "douyin",
        "title": title,
        "duration_sec": expect or audio_dur,
        "cover_url": poster,
        "cover_path": "",
        "audio_src": audio_path,
        "media_path": "",
        "media_kind": "",
    }

    if audio_only:
        source = audio_path
        if not source:
            log("  没有独立声音流，先下视频再抽音轨")
            video_path, _, _, _ = pick_stream(
                video_urls, ua, dest_dir, video_id + ".src", ".mp4", expect,
                require_audio=True, log=log, progress=track, cancel=cancel)
            if not video_path:
                raise NoStream("没有可用音轨")
            source = video_path
        mp3 = to_mp3(source, title, poster, ua, dest_dir, out_base=video_id, log=log)
        if not mp3:
            raise PipelineError("转 mp3 失败", code="FFMPEG_FAILED",
                                hint="检查 tools/ffmpeg/bin 是否完整。")
        result["media_path"] = mp3
        result["media_kind"] = "audio"
        result["audio_src"] = audio_path or ""
        cleanup(dest_dir, keep=(mp3,), log=log)
        return result

    # 要视频：画面流可能不带音轨，靠 mux 补
    video_path, _, video_dur, video_streams = pick_stream(
        video_urls, ua, dest_dir, video_id + ".src", ".mp4", expect or audio_dur,
        log=log, progress=track, cancel=cancel)
    if not video_path:
        raise NoStream("画面流下载失败")

    final = os.path.join(dest_dir, video_id + ".mp4")
    if has_audio(video_streams):
        if os.path.exists(final):
            os.remove(final)
        os.replace(video_path, final)
        log("  画面流自带音轨，直接使用")
    elif audio_path:
        log("  画面流无音轨，正在合流 ...")
        if not mux_av(video_path, audio_path, final, title, log=log):
            raise NoStream("音视频合流失败")
        try:
            os.remove(video_path)
        except Exception:
            pass
        log("  合流完成")
    else:
        raise NoStream("画面流无音轨且没有声音流可用")

    result["media_path"] = final
    result["media_kind"] = "video"
    cover = fetch_cover(poster, ua, dest_dir, log=log)
    if cover:
        cover_final = os.path.join(dest_dir, video_id + ".cover.jpg")
        try:
            os.replace(cover, cover_final)
            result["cover_path"] = cover_final
        except Exception:
            pass
    cleanup(dest_dir, keep=(final, audio_path), log=log)
    return result


def cleanup(directory, keep=(), log=print):
    """删掉候选流、.part 等中间文件，避免目录里堆垃圾。"""
    keep_names = {os.path.basename(item) for item in keep if item}
    for name in os.listdir(directory):
        if name in keep_names or name == ".lock":
            continue
        if ".cand" in name or name.endswith(".part") or name.endswith(".audio.m4a"):
            try:
                os.remove(os.path.join(directory, name))
            except Exception:
                pass
