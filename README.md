# dsh-video

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](python/requirements.txt)
[![Node](https://img.shields.io/badge/node-20%2B-brightgreen)](package.json)
[![DSH](https://img.shields.io/badge/DSH-0.2.1--rc.5-purple)](https://github.com/deepseek-ai)
[![Version](https://img.shields.io/badge/version-1.0.0-informational)](CHANGELOG.md)

**English** | [简体中文](README_zh.md)

`dsh-video` is a [DeepSeek Harness](https://github.com/deepseek-ai) plugin that
turns a video link into a document you can actually read and search.

Paste a link in chat. The model downloads the video, extracts the audio,
transcribes it with Whisper, and writes `report.md`, `report.docx`,
`transcript.srt` and `transcript.txt` into a per-video folder. No timeline
scrubbing, no manual note-taking.

It works with **Douyin** (watermark-free 1080p, no cookies needed), with
**everything yt-dlp supports** (Bilibili, YouTube, Weibo and hundreds more), and
with **local files** you already have on disk.

```
link / local file
      │
      ├── Douyin ......... headless Edge + CDP → real stream URLs
      └── everything else  yt-dlp → mp4 (muxed) or mp3
      │
      ├── ffmpeg ......... 16 kHz mono wav
      ├── faster-whisper . segments with timestamps (CPU int8 by default)
      └── docgen ......... report.md / .docx / .srt / .txt / segments.json
```

## Features

| | |
| --- | --- |
| **Two download channels** | Douyin through CDP (no login, no cookies, DASH streams muxed back together); every other site through yt-dlp |
| **Local transcription** | faster-whisper runs on your machine. Audio never leaves it |
| **Structured output** | Paragraphs merged by pause length, timestamps kept, SRT ready for CapCut/PotPlayer, optional Word file |
| **Honest failure modes** | Music-only clips produce a document that says "no speech detected" instead of an error; every failure carries a code and a fix hint |
| **Built for chat** | Six tools, job queue with progress polling, cancellation that cleans up after itself |
| **No UI, no telemetry** | Configuration lives in `cordis.patch.yml`. Nothing is sent anywhere except the link you asked for |
| **Portable** | All paths come from environment variables; the same code runs from the plugin, the CLI, or a copied directory |

## Requirements

- **DSH** 0.2.1-rc.2 or newer (tested on 0.2.1-rc.5)
- **Node.js** 20+
- **Python** 3.11+ (3.12 recommended)
- **FFmpeg** and **ffprobe** — either on `PATH` or in `tools/ffmpeg/bin/`
- **~2.5 GB** disk for the Python environment, plus 0.5–3 GB per Whisper model
- **Microsoft Edge** only for the Douyin channel (Linux/macOS fall back to yt-dlp)

## Installation

### 1. Get the code

```bash
git clone https://github.com/junliu3/dsh-video.git
cd dsh-video
```

### 2. Build the Python environment

```bash
npm run bootstrap                 # venv + dependencies + small model
npm run bootstrap -- --skip-model # skip the model download
npm run bootstrap -- --model medium
```

`bootstrap` creates `python/.venv-asr/`, installs `python/requirements.txt`
(faster-whisper, yt-dlp, python-docx, requests, websockets) and fetches the
Whisper weights from `hf-mirror.com`. Existing environments are reused.

### 3. Install into DSH

```bash
dsh plugin --profile desktop add "C:\path\to\dsh-video"
```

Then make sure the profile lists it as a bundle — DSH only mounts plugins that
are in `dsh.profile.bundles`:

```jsonc
// ~/.dsh/profiles/desktop/package.json
"dsh": { "profile": { "bundles": [ ..., "dsh-video" ] } }
```

Restart DSH. Plugin trees are composed at boot.

### 4. Verify

Ask the model: *"check the video-to-document environment"* — or run it
yourself:

```bash
npm run doctor
```

Nine checks: Python, venv, faster-whisper, ffmpeg, ffprobe, model, yt-dlp,
Edge, library write access.

### Install from GitHub without cloning

```bash
dsh plugin --profile desktop add github:junliu3/dsh-video
# or
dsh plugin --profile desktop add https://codeload.github.com/junliu3/dsh-video/tar.gz/refs/heads/main
```

The Python environment still has to be built inside the installed package —
run `npm run bootstrap` from `~/.dsh/profiles/desktop/node_modules/dsh-video`.

## Usage

### In chat

| You say | What happens |
| --- | --- |
| "Turn this into a document: `https://www.douyin.com/video/...`" | `video_to_doc` downloads, transcribes, writes the full set of files |
| "What videos have I transcribed?" | `video_library` lists the library |
| "Show me the document for `BV1GJ411x7h7`" | `video_library` reads `report.md` back into the conversation |
| "Just download the audio: `https://youtu.be/...`" | `video_download` with `kind: audio` |
| "Is that one done yet?" | `video_job_status` |
| "Stop it" | `video_job_cancel` |

### Tools

| Tool | Purpose | Key parameters |
| --- | --- | --- |
| `video_doctor` | Environment self-check with fix hints | — |
| `video_download` | Media only, no transcript | `source`, `kind: video\|audio`, `wait` |
| `video_to_doc` | Full pipeline | `source`, `model`, `language`, `device`, `dropMedia`, `wait` |
| `video_job_status` | Stage, percent, result or failure | `jobId` |
| `video_job_cancel` | Stop and clean up | `jobId` |
| `video_library` | Browse or read past results | `action: list\|read`, `keyword`, `limit`, `videoId` |

`video_to_doc` waits up to `waitMs` (default 120 s) so short clips finish in one
call. Longer ones return a `jobId` and you poll `video_job_status`.

### Command line

The engine works without DSH:

```bash
cd python

.venv-asr/Scripts/python.exe -m ytdip.cli "https://www.douyin.com/video/xxx"
.venv-asr/Scripts/python.exe -m ytdip.cli "https://www.bilibili.com/video/BVxxx" --audio
.venv-asr/Scripts/python.exe -m ytdip.cli --file "D:\talk.mp4" --id team-sync
.venv-asr/Scripts/python.exe -m ytdip.cli "链接" --json      # JSONL events

.venv-asr/Scripts/python.exe -m ytdip.doctor                # same self-check
.venv-asr/Scripts/python.exe -m ytdip.fetch_model medium    # pre-download a model
.venv-asr/Scripts/python.exe -m ytdip.migrate --from "D:\old\资料库"
```

Useful flags: `--download-only`, `--audio`, `--model`, `--device cpu|cuda`,
`--lang zh|en|auto`, `--keep-wav`, `--drop-media`, `--no-docx`.

## Output

Everything lands in one folder per item, named after the site's video id — never
after the title, so long or emoji-laden titles cannot break paths:

```
~/.dsh/data/yt-dip/
└── 7700987993812749610/
    ├── 7700987993812749610.mp4    original media
    ├── report.md                  structured document (front-matter included)
    ├── report.docx                Word version
    ├── transcript.srt             subtitles
    ├── transcript.txt             plain text
    ├── segments.json              timed segments for downstream tools
    └── media.json                 metadata contract
```

`media.json` records the source URL, title, duration, capture time and which
model produced the transcript, so a result can always be reproduced or audited.

## Configuration

No settings page by design — override values in the profile patch layer:

```yaml
# ~/.dsh/profiles/desktop/cordis.patch.yml
- id: dsh-video
  config:
    dataDir: "D:\\media\\transcripts"
    model: "medium"
    device: "cpu"
    language: "zh"
    maxConcurrentJobs: 1
    jobTimeoutMs: 1800000
```

Do **not** add an `insert` block here; the bundle layer already provides it and
duplicating the id breaks settings persistence.

| Key | Default | Meaning |
| --- | --- | --- |
| `dataDir` | `~/.dsh/data/yt-dip` | Library root |
| `pythonPath` | `python/.venv-asr/Scripts/python.exe` | Interpreter to spawn |
| `ffmpegDir` | `tools/ffmpeg/bin` | Directory containing ffmpeg/ffprobe |
| `edgePath` | auto-detect | `msedge.exe`, for Douyin only |
| `model` | `small` | `tiny`, `base`, `small`, `medium`, `large-v3` |
| `device` | `cpu` | `cuda` is allowed and falls back to CPU on failure |
| `language` | `zh` | `auto` lets Whisper detect |
| `maxConcurrentJobs` | `1` | Transcription saturates the CPU; queue instead of racing |
| `jobTimeoutMs` | `900000` | Hard per-job limit |
| `waitMs` | `120000` | How long a tool call blocks before returning a job id |

## Models

Weights are stored under `runtime/models/` and are not committed.

| Size | Disk | Rough speed (CPU, 8 cores) | Notes |
| --- | --- | --- | --- |
| `small` | 464 MB | ~7× realtime | Default, good Chinese |
| `medium` | 1.5 GB | ~2× realtime | Better on accents and jargon |
| `large-v3` | 3.1 GB | under realtime | Best quality, heavy |

`cuda` is supported but was unstable on the development machine (same clip
anywhere from 12 s to 205 s), so CPU is the default.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Tools never appear | Is `dsh-video` in `dsh.profile.bundles`? Restart DSH after editing |
| `MODEL_MISSING` | `python -m ytdip.fetch_model small` inside `python/` |
| `EDGE_MISSING` | Install Edge or set `edgePath`. Other sites still work without it |
| `NO_STREAM` | Post deleted or page changed; the job log contains the page text |
| `LOGIN_REQUIRED` | Bilibili 1080p/member content needs cookies; not supported yet |
| `YTDLP_MISSING` | `npm run bootstrap`, or `pip install yt-dlp` in the venv |
| `FFMPEG_MISSING` | `winget install Gyan.FFmpeg`, or drop binaries into `tools/ffmpeg/bin` |
| Transcription is slow | Use `small`, or try `device: cuda` if you have a GPU |
| Job says `INTERRUPTED` | DSH restarted mid-job; submit it again |
| Need the raw failure | `<dataDir>/.state/logs/<jobId>.log` |

## Limitations

- One item per job. No playlists, collections or favourites.
- Transcription only. No summarisation, no slide/frame understanding.
- Douyin requires Edge and Windows-style process handling; on Linux/macOS that
  channel is unavailable and yt-dlp is used instead.
- Machine transcripts get names, numbers and jargon wrong. Check before quoting.

## Contributing

Bug reports, site support and output improvements are welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md). Run the same checks CI does:

```bash
python -m unittest discover -s tests -t . -v
node scripts/check-manifest.mjs
```

Security issues: [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © 2026 junliu3.

Third-party components keep their own licenses — see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). FFmpeg and the Whisper weights
are **not** distributed with this repository.

## Credits

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — site extraction and this
  repository's layout conventions
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — recognition
- [FFmpeg](https://ffmpeg.org/) — audio plumbing
- [DeepSeek Harness](https://github.com/deepseek-ai) — the plugin host

## Disclaimer

`dsh-video` is a personal archiving tool. Download and process only material you
have the right to use, and respect each site's terms of service. The authors are
not responsible for how you use it.
