"""环境自检：给插件一个「一键体检」工具，而不是让用户猜为什么跑不起来。

    python -m ytdip.doctor          # 人类可读
    python -m ytdip.doctor --json   # 一行 JSON（Node 侧解析）
"""
import json
import os
import shutil
import subprocess
import sys

from . import config, douyin_cdp
from .errors import PipelineError


def _check(name, ok, detail, fix=""):
    return {"name": name, "ok": bool(ok), "detail": detail, "fix": fix if not ok else ""}


def _ffmpeg_version():
    try:
        result = subprocess.run([config.FFMPEG, "-version"], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=20)
        first = (result.stdout or "").splitlines()
        return first[0] if first else ""
    except Exception as exc:
        return f"error: {type(exc).__name__}"


def _ytdlp_version():
    vendor = config.VENDOR_DIR
    if os.path.isdir(vendor) and vendor not in sys.path:
        sys.path.insert(0, vendor)
    try:
        import yt_dlp
        return getattr(yt_dlp.version, "__version__", "unknown")
    except Exception as exc:
        return f"error: {type(exc).__name__}: {exc}"


def _models():
    root = config.MODEL_DIR
    if not os.path.isdir(root):
        return []
    found = []
    for name in os.listdir(root):
        if name.startswith("faster-whisper-") and \
                os.path.isfile(os.path.join(root, name, "model.bin")):
            found.append(name.replace("faster-whisper-", ""))
    return sorted(found)


def run():
    config.ensure_dirs()
    checks = []

    checks.append(_check("python", sys.version_info >= (3, 10),
                         f"{sys.version.split()[0]} @ {sys.prefix}",
                         "需要 Python 3.10+ 的虚拟环境"))

    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    checks.append(_check("venv", in_venv,
                         "独立虚拟环境" if in_venv else "正在使用全局解释器",
                         "用 python/.venv-asr 里的 python 运行"))

    try:
        import faster_whisper  # noqa: F401
        checks.append(_check("faster-whisper", True, "已安装"))
    except Exception as exc:
        checks.append(_check("faster-whisper", False, f"{type(exc).__name__}: {exc}",
                             "重新运行 bootstrap 安装依赖"))

    ffmpeg_ok = os.path.isfile(config.FFMPEG)
    checks.append(_check("ffmpeg", ffmpeg_ok,
                         _ffmpeg_version() if ffmpeg_ok else f"缺失: {config.FFMPEG}",
                         "安装 ffmpeg（winget install Gyan.FFmpeg / brew install ffmpeg），"
                         "或把 ffmpeg+ffprobe 放进 tools/ffmpeg/bin，或配置 ffmpegDir"))

    ffprobe_ok = os.path.isfile(config.FFPROBE)
    checks.append(_check("ffprobe", ffprobe_ok,
                         config.FFPROBE if ffprobe_ok else "缺失，需与 ffmpeg 同目录",
                         "确认 ffprobe 与 ffmpeg 在同一目录"))

    models = _models()
    want = config.DEFAULT_MODEL
    checks.append(_check("model", want in models,
                         f"已下载: {', '.join(models) or '无'}；默认 {want}",
                         f"运行 python -m ytdip.fetch_model {want}"))

    version = _ytdlp_version()
    checks.append(_check("yt-dlp", not version.startswith("error"),
                         version, "运行 npm run bootstrap（或 pip install yt-dlp）安装依赖"))

    if os.name == "nt":
        try:
            edge = douyin_cdp.find_edge()
            checks.append(_check("edge", True, edge))
        except PipelineError as exc:
            checks.append(_check("edge", False, exc.message,
                                 "安装 Edge，或用 edgePath 指定 msedge.exe"))
    else:
        checks.append(_check("edge", True, "非 Windows，抖音通道不可用"))

    try:
        probe = os.path.join(config.LIB_ROOT, ".write-test")
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("ok")
        os.remove(probe)
        usage = shutil.disk_usage(config.LIB_ROOT)
        free_gb = usage.free / (1024 ** 3)
        checks.append(_check("library", True,
                             f"{config.LIB_ROOT}（可写，剩余 {free_gb:.1f} GB）"))
    except Exception as exc:
        checks.append(_check("library", False, f"{type(exc).__name__}: {exc}",
                             "检查资料库目录权限或磁盘空间"))

    return {
        "ok": all(item["ok"] for item in checks),
        "checks": checks,
        "paths": config.snapshot(),
        "models": models,
    }


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    report = run()
    if "--json" in argv:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print("yt-dip 环境自检")
        for item in report["checks"]:
            mark = "OK  " if item["ok"] else "FAIL"
            print(f"  [{mark}] {item['name']:<14} {item['detail']}")
            if item["fix"]:
                print(f"         -> {item['fix']}")
        print("\n" + ("全部通过" if report["ok"] else "存在未通过项"))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
