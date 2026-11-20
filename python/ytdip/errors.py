"""统一错误码。Node 侧据此给用户可执行的建议，而不是抛一段英文栈。"""


class PipelineError(RuntimeError):
    code = "INTERNAL"
    hint = ""

    def __init__(self, message, code=None, hint=None):
        super().__init__(message)
        self.message = str(message)
        if code:
            self.code = code
        if hint:
            self.hint = hint


class BadInput(PipelineError):
    code = "BAD_INPUT"
    hint = "需要一个抖音链接/作品 ID、其它站点的 http(s) 链接，或本地音视频文件路径。"


class NoStream(PipelineError):
    code = "NO_STREAM"
    hint = "作品可能已删除、需要登录、或页面结构已改版。"


class LoginRequired(PipelineError):
    code = "LOGIN_REQUIRED"
    hint = "该站点要求登录或 Cookie；抖音请改用默认 CDP 通道。"


class UnsupportedSite(PipelineError):
    code = "UNSUPPORTED_SITE"
    hint = "yt-dlp 不支持该站点，或链接不是单个作品的地址。"


class EdgeMissing(PipelineError):
    code = "EDGE_MISSING"
    hint = "未找到 Microsoft Edge。可在插件配置里用 edgePath 指定 msedge.exe 的绝对路径。"


class FfmpegMissing(PipelineError):
    code = "FFMPEG_MISSING"
    hint = "缺少 ffmpeg。请确认 tools/ffmpeg/bin 存在，或在配置里指定 ffmpegDir。"


class ModelMissing(PipelineError):
    code = "MODEL_MISSING"
    hint = "本地没有该 Whisper 模型。运行 bootstrap 或 python -m ytdip.fetch_model <尺寸>。"


class BusyError(PipelineError):
    code = "BUSY"
    hint = "同一条视频正在处理中，等它结束后再试。"


class DiskFull(PipelineError):
    code = "DISK_FULL"
    hint = "磁盘空间不足，清理资料库后再试。"


class Canceled(PipelineError):
    code = "CANCELED"
    hint = "任务已被取消。"


class NoSpeech(PipelineError):
    """没有人声不算失败，上层据此仍然产出带说明的文档。"""
    code = "NO_SPEECH"
    hint = "纯音乐、纯画面或无对白作品；已保留元数据与媒体，可换更大模型重跑。"


def to_payload(exc):
    if isinstance(exc, PipelineError):
        return {"code": exc.code, "msg": exc.message, "hint": exc.hint}
    return {"code": "INTERNAL", "msg": f"{type(exc).__name__}: {exc}", "hint": ""}
