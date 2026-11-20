"""路径与默认参数。

原则：**环境变量优先**。DSH 插件在 spawn 时注入 YTDIP_* 变量，同一份代码
既能被插件调用，也能在命令行里直接跑（不设变量时回落到项目内布局）。
"""
import os
import shutil

HOME = os.path.expanduser("~")

# python/ 的上一层就是项目根
PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT = os.path.dirname(PY_DIR)


def _first(*values):
    for value in values:
        if value:
            return value
    return ""


def _bin(name):
    return name + ".exe" if os.name == "nt" else name


# ---------------------------------------------------------------- 资料库
# 默认落在 DSH 数据目录，与原项目的「桌面\大肥鱼\yt-dip\资料库」解耦
DEFAULT_LIB_ROOT = os.path.join(HOME, ".dsh", "data", "yt-dip")
LIB_ROOT = os.path.abspath(_first(os.environ.get("YTDIP_LIB_ROOT"), DEFAULT_LIB_ROOT))
LIB_MIGRATED_FROM = os.environ.get("YTDIP_MIGRATED_FROM", "")

# 作业状态与日志藏在 .state 下，不污染 <video_id> 目录列表
STATE_DIR = os.path.join(LIB_ROOT, ".state")
LOG_DIR = os.path.join(STATE_DIR, "logs")
JOB_DIR = os.path.join(STATE_DIR, "jobs")

# ---------------------------------------------------------------- 外部程序
_PREFERRED_FFMPEG_DIR = _first(os.environ.get("YTDIP_FFMPEG_DIR"),
                               os.path.join(PROJECT, "tools", "ffmpeg", "bin"))


def _resolve_tool(name, preferred_dir):
    """优先用项目内置；没有就退回系统 PATH（方便 clone 后直接用系统 ffmpeg）。"""
    candidate = os.path.join(preferred_dir, _bin(name))
    if os.path.isfile(candidate):
        return candidate
    found = shutil.which(name) or shutil.which(_bin(name))
    return found or candidate


FFMPEG = _resolve_tool("ffmpeg", _PREFERRED_FFMPEG_DIR)
FFPROBE = _resolve_tool("ffprobe", _PREFERRED_FFMPEG_DIR)
FFMPEG_DIR = os.path.dirname(FFMPEG)

# yt-dlp 源码随包放在 python/vendor，避免依赖外部安装
VENDOR_DIR = os.path.join(PY_DIR, "vendor")

# 空 = 自动探测 Edge
EDGE = os.environ.get("YTDIP_EDGE", "")
# 0 = 每次挑空闲端口
CDP_PORT = int(os.environ.get("YTDIP_CDP_PORT") or 0)

# ---------------------------------------------------------------- 模型
MODEL_DIR = _first(os.environ.get("YTDIP_MODEL_DIR"),
                   os.path.join(PROJECT, "runtime", "models"))
DEFAULT_MODEL = _first(os.environ.get("YTDIP_MODEL"), os.environ.get("ASR_MODEL"), "small")
# 本机实测 CUDA 路径不稳定（同一段音频时而 12s 时而 205s），默认 CPU
DEFAULT_DEVICE = _first(os.environ.get("YTDIP_DEVICE"), os.environ.get("ASR_DEVICE"), "cpu")
DEFAULT_LANG = _first(os.environ.get("YTDIP_LANG"), os.environ.get("ASR_LANG"), "zh")

# 转写线程数：0 = 自动取一半核数，避免把 DSH 自身挤死
_cpu = os.cpu_count() or 4
CPU_THREADS = int(os.environ.get("YTDIP_CPU_THREADS") or 0) or max(1, _cpu // 2)

# 段落合并参数
PARA_GAP = 1.2
PARA_MAX_CHARS = 220

# 抖音默认走 CDP（能拿 1080P 无水印、免 cookie）；置 1 可强制走 yt-dlp
DOUYIN_VIA_YTDLP = os.environ.get("YTDIP_DOUYIN_VIA_YTDLP", "") in ("1", "true", "yes")


def ensure_dirs():
    for path in (LIB_ROOT, STATE_DIR, LOG_DIR, JOB_DIR, MODEL_DIR):
        os.makedirs(path, exist_ok=True)


def snapshot():
    """给 doctor / 日志用的路径快照。"""
    return {
        "project": PROJECT,
        "libRoot": LIB_ROOT,
        "stateDir": STATE_DIR,
        "modelDir": MODEL_DIR,
        "ffmpeg": FFMPEG,
        "ffprobe": FFPROBE,
        "vendor": VENDOR_DIR,
        "edge": EDGE or "(auto)",
        "cdpPort": CDP_PORT or "auto",
        "python": os.sys.executable,
        "cpuThreads": CPU_THREADS,
    }
