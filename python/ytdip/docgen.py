"""成文层：把转写片段整理成段落，输出 Markdown / SRT / 纯文本 / Word。

整理规则不依赖大模型：按时间间隔断段、合并碎句、去掉相邻重复。
目的是保证「原文一字不改」，只是让它读起来像文章，而不是逐句字幕。
"""
import os
import re

_CJK_RANGE = "\u4e00-\u9fff"
# Whisper 的中文输出常用半角逗号，夹在汉字之间时换成全角，读起来才像中文
_COMMA_FIX = re.compile(rf"(?<=[{_CJK_RANGE}])\s*,\s*(?=[{_CJK_RANGE}])")
_PERIOD_FIX = re.compile(rf"(?<=[{_CJK_RANGE}])\.")


def normalize_text(text):
    """只做标点归一，不改任何字词。"""
    if not text:
        return text
    text = _COMMA_FIX.sub("，", text)
    text = _PERIOD_FIX.sub("。", text)
    return text.strip()


def fmt_mmss(sec):
    sec = int(round(float(sec or 0)))
    return f"{sec // 60:02d}:{sec % 60:02d}"


def fmt_hms(sec):
    sec = int(round(float(sec or 0)))
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def _srt_time(sec):
    ms = int(round(float(sec or 0) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def dedupe(segments):
    """去掉相邻完全重复的片段（长静音后常出现整句复读），顺手归一标点。"""
    out = []
    for segment in segments:
        segment = dict(segment)
        segment["text"] = normalize_text(segment["text"])
        if not segment["text"]:
            continue
        if out and out[-1]["text"] == segment["text"]:
            continue
        out.append(segment)
    return out


_END_PUNCT = set("。！？，、；：…—.!?,;:")


def _is_cjk(ch):
    return bool(ch) and "\u4e00" <= ch <= "\u9fff"


def _join(a, b):
    """合并两句时补最少的连接符：已有标点就直接拼，中文补逗号，英文补空格。"""
    if not a:
        return b
    if a[-1] in _END_PUNCT:
        return a + b
    if b[:1] in _END_PUNCT:
        return a + b
    return a + ("，" if (_is_cjk(a[-1]) or _is_cjk(b[:1])) else " ") + b


def build_paragraphs(segments, gap=1.2, max_chars=220):
    """按时间间隔和长度把片段并成段落。纯规则，不改写文字。"""
    paragraphs = []
    current = None
    for segment in segments:
        if current is None:
            current = {"start": segment["start"], "end": segment["end"], "text": segment["text"]}
            continue
        joinable = (segment["start"] - current["end"]) <= gap
        room = len(current["text"]) + len(segment["text"]) <= max_chars
        if joinable and room:
            current["end"] = segment["end"]
            current["text"] = _join(current["text"], segment["text"])
        else:
            paragraphs.append(current)
            current = {"start": segment["start"], "end": segment["end"], "text": segment["text"]}
    if current:
        paragraphs.append(current)
    return paragraphs


def write_srt(segments, path):
    lines = []
    for index, segment in enumerate(segments, 1):
        lines.append(str(index))
        lines.append(f"{_srt_time(segment['start'])} --> {_srt_time(segment['end'])}")
        lines.append(segment["text"])
        lines.append("")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return path


def write_txt(paragraphs, path):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n\n".join(item["text"] for item in paragraphs))
        handle.write("\n")
    return path


def stats(segments, segments_raw, duration):
    speech = sum(max(0.0, s["end"] - s["start"]) for s in segments)
    chars = sum(len(s["text"]) for s in segments)
    ratio = (speech / duration * 100) if duration else 0
    cpm = (chars / speech * 60) if speech else 0
    return {
        "segment_count": len(segments),
        "dropped_dupes": max(0, len(segments_raw) - len(segments)),
        "speech_sec": speech,
        "chars": chars,
        "speech_ratio": ratio,
        "chars_per_min": cpm,
    }


def write_md(record, segments, paragraphs, path, counters):
    title = record.get("title") or record.get("video_id")
    duration = record.get("duration_sec") or 0
    model = (record.get("pipeline") or {}).get("asr_model", "")
    device = (record.get("pipeline") or {}).get("asr_device", "")
    source = record.get("source_url") or "（本地文件，无原始链接）"
    platform = record.get("platform", "douyin")

    head = [
        "---",
        f'video_id: "{record.get("video_id", "")}"',
        f'platform: "{platform}"',
        f'title: "{title}"',
        f'source_url: "{record.get("source_url", "")}"',
        f'duration_sec: {round(float(duration), 2)}',
        f'captured_at: "{record.get("captured_at", "")}"',
        f'asr_model: "{model}"',
        f'asr_device: "{device}"',
        "tags: [语音转写]",
        "---",
        "",
    ]

    body = [
        f"# {title}",
        "",
        f"> 来源：{source}　时长 {fmt_mmss(duration)}　转写 {model}（{device}）",
        "",
    ]
    cover = record.get("cover_path") or ""
    if cover and os.path.exists(cover):
        # 用相对路径，整个资料目录搬走也不会断图
        body += [f"![封面]({os.path.basename(cover)})", ""]
    body += [
        "## 基本信息",
        "",
        "| 项 | 内容 |",
        "| --- | --- |",
        f"| 作品 ID | {record.get('video_id', '')} |",
        f"| 标题 | {title} |",
        f"| 平台 | {platform} |",
        f"| 时长 | {fmt_mmss(duration)} |",
        f"| 采集时间 | {record.get('captured_at', '')} |",
        f"| 原始链接 | {source} |",
        "",
        "## 内容概览",
        "",
        f"- 有效语音时长：{fmt_mmss(counters['speech_sec'])}（占全片 {counters['speech_ratio']:.0f}%）",
        f"- 转写片段：{counters['segment_count']} 段",
        f"- 正文字数：约 {counters['chars']} 字",
        f"- 语速：约 {counters['chars_per_min']:.0f} 字/分钟",
    ]
    if counters["dropped_dupes"]:
        body.append(f"- 已滤除相邻重复：{counters['dropped_dupes']} 段")
    body += [
        "",
        "## 正文（按时间分段）",
        "",
    ]
    if not paragraphs:
        body += [
            "> ⚠ 本条未识别到人声（可能是纯音乐、纯画面演示或无对白作品）。",
            "> 已保留元数据与媒体文件，可换用更大模型或人工确认后重跑。",
            "",
        ]
    for paragraph in paragraphs:
        body.append(f"**[{fmt_mmss(paragraph['start'])}]** {paragraph['text']}")
        body.append("")

    body += [
        "## 附件",
        "",
        "- `transcript.srt` — 字幕文件，可导入剪映/PotPlayer",
        "- `transcript.txt` — 纯文本，便于二次编辑",
        "- `segments.json` — 带时间戳的原始片段，供程序复用",
        "- `media.json` — 元数据",
        "",
        "> 本版为纯转写整理，未做语义摘要、未做画面理解。",
        "> 转写由机器生成，专有名词、数字可能有误，引用前请核对原片。",
    ]

    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(head + body) + "\n")
    return path


def write_docx(record, paragraphs, path):
    """可选产物。没装 python-docx 就静默跳过，不影响主流程。"""
    try:
        from docx import Document
        from docx.shared import Pt
    except Exception:
        return ""

    document = Document()
    document.add_heading(record.get("title") or record.get("video_id"), level=1)

    info = document.add_paragraph()
    info.add_run(
        f"来源：{record.get('source_url', '')}\n"
        f"时长：{fmt_mmss(record.get('duration_sec') or 0)}　"
        f"采集：{record.get('captured_at', '')}"
    ).font.size = Pt(9)

    document.add_heading("正文", level=2)
    for paragraph in paragraphs:
        item = document.add_paragraph()
        run = item.add_run(f"[{fmt_mmss(paragraph['start'])}] ")
        run.bold = True
        run.font.size = Pt(9)
        item.add_run(paragraph["text"])

    document.save(path)
    return path
