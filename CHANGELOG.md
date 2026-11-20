# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] — 2026-11-20

First public release, packaging the previously local `yt-dip` toolchain as a
DeepSeek Harness plugin.

### Added

- DSH plugin (`dsh-video`) with six tools: `video_doctor`, `video_download`,
  `video_to_doc`, `video_job_status`, `video_job_cancel`, `video_library`.
- Job system: queue (1 concurrent by default), JSONL progress events, per-job
  logs, hard timeout, graceful cancel via `.cancel` marker, process-tree kill
  fallback on Windows.
- Generic site support through yt-dlp (Bilibili, YouTube, Weibo and anything
  else yt-dlp handles), including mp4 muxing and mp3 extraction.
- Douyin channel via headless Edge + CDP: 1080p watermark-free video, separate
  DASH audio/video streams, duration-validated stream selection.
- Transcription with faster-whisper: CPU int8 by default, optional CUDA with
  automatic fallback, VAD retry when no speech is detected, prompt-echo and
  duplicate filtering.
- Outputs per item: `report.md`, `report.docx`, `transcript.srt`,
  `transcript.txt`, `segments.json`, `media.json`.
- Library migration helper (`python -m ytdip.migrate`) that copies an old
  library and rewrites absolute paths in `media.json`.
- Environment self-check (`video_doctor` / `npm run doctor`) covering Python,
  faster-whisper, ffmpeg, ffprobe, models, yt-dlp, Edge and disk space.
- Library default moved to `~/.dsh/data/yt-dip`, decoupled from the source tree.
- English and Chinese READMEs, CONTRIBUTING, SECURITY, THIRD_PARTY_NOTICES,
  issue templates and a CI workflow.

### Changed

- Package, plugin id and tool names are now `dsh-video` / `video_*`; the
  pre-release name was `dsh-ytdip` / `douyin_*`.
- Python is invoked through environment variables (`YTDIP_LIB_ROOT`,
  `YTDIP_FFMPEG_DIR`, `YTDIP_MODEL`, `YTDIP_EDGE`, …) instead of relying on
  paths relative to `__file__`, so the same code works from the plugin, the CLI
  and a copied directory.
- The non-ASCII module `下载抖音.py` became `python/ytdip/douyin_cdp.py`.

### Fixed

- Cancelling during a CDP call used to hang until the host force-killed the
  process; a watchdog now closes the socket so cancellation lands in ~2 seconds
  and leaves no headless Edge or temporary profile behind.
- Cleanup waited 8 seconds on an already-killed Edge process, making every
  cancel look unresponsive.

### Notes

- Media engines (`python/.venv-asr`, `python/vendor`, `tools/ffmpeg`,
  `runtime/models`) are intentionally not committed. Run `npm run bootstrap`.
