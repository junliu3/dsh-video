"""yt-dip 转写引擎（DSH 插件内置版）。

模块：
    config      路径与默认参数（环境变量优先）
    errors      错误码与异常
    events      JSONL 事件出口
    locks       每视频独占锁
    store       资料目录与 media.json 契约
    douyin_cdp  抖音 CDP 采集通道
    ytdlp_src   yt-dlp 通用站点采集通道
    acquire     采集调度（本地 / 抖音 / 通用站点）
    asr         抽音轨 + faster-whisper 转写
    docgen      Markdown / SRT / TXT / Word
    pipeline    五段式编排
    worker      JSONL 机器入口
    cli         人类入口
    doctor      环境自检
    fetch_model 模型下载
    migrate     旧资料库迁移
"""
__version__ = "1.0.0"
