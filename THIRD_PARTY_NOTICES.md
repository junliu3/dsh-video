# Third-party notices

`dsh-video` itself is MIT-licensed (see `LICENSE`). It depends on the following
projects at runtime. None of them are vendored in this repository except where
explicitly noted.

| Project | License | How it is used |
| --- | --- | --- |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Unlicense | Site extraction and download for everything except Douyin. Installed from PyPI (`yt-dlp`) by `npm run bootstrap`. |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | MIT | Speech recognition (CTranslate2 backend). |
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) | MIT | Inference engine used by faster-whisper. |
| [FFmpeg](https://ffmpeg.org/) | LGPL-2.1+ / GPL-2.0+ depending on build | Audio extraction, muxing, mp3 encoding. **Not distributed with this repository** — install it yourself (see README). Builds from gyan.dev are GPL; if you redistribute a binary build, you must also provide its source. |
| [python-docx](https://github.com/python-openxml/python-docx) | MIT | Optional `.docx` output. |
| [requests](https://github.com/psf/requests) | Apache-2.0 | HTTP downloads for the Douyin CDP channel. |
| [websockets](https://github.com/python-websockets/websockets) | BSD-3-Clause | Chrome DevTools Protocol client. |
| [Whisper models](https://huggingface.co/Systran) | MIT (model weights published by Systran) | Downloaded on demand by `python -m ytdip.fetch_model`. Not distributed with this repository. |
| [DeepSeek Harness](https://github.com/deepseek-ai) | MIT | Host application; `@deepseek-ai/cordis` is a peer dependency. |

## Notes on redistribution

- This repository intentionally does **not** contain `python/.venv-asr/`,
  `python/vendor/`, `tools/ffmpeg/`, or `runtime/models/`. They are listed in
  `.gitignore` because of size and licensing.
- If you fork and publish a packaged build that bundles FFmpeg or Whisper
  weights, you are responsible for complying with their licenses (including
  providing FFmpeg's corresponding source).
- `yt-dlp` is installed as a dependency, not copied into the tree. If you choose
  to vendor it, keep its Unlicense text alongside the code.
