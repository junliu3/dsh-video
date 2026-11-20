# Contributing to dsh-video

Thanks for taking the time to help. This project is small on purpose: a thin
DSH plugin layer in JavaScript and a self-contained Python engine. Most changes
land in one of those two places.

Issues and pull requests in Chinese or English are both welcome.

## Before you start

- **Bug reports** need `npm run doctor` output and the job log
  (`<dataDir>/.state/logs/<jobId>.log`). Without them the cause is usually a
  guess.
- **New site support**: check first whether [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  already supports it. If it does, the fix is usually not code — it is a newer
  yt-dlp version, which belongs in `python/requirements.txt`.
- **Large features** (batch mode, summaries, new output formats) — open an issue
  first so we can agree on the tool surface before you write it.

## Project layout

```
lib/                 DSH plugin layer (ESM, no build step)
  index.js           apply(ctx, config): registers tools, owns cleanup
  config.js          path resolution + env passed to Python
  jobs.js            queue, spawn, JSONL parsing, cancel, timeouts
  tools.js           the six tool definitions
python/ytdip/        engine (pure Python, no DSH knowledge)
  worker.py          JSONL entry point used by jobs.js
  pipeline.py        resolve → acquire → extract → transcribe → compose
  acquire.py         routes to douyin_cdp / ytdlp_src / local file
  douyin_cdp.py      headless Edge + CDP channel
  ytdlp_src.py       generic site channel
  asr.py             ffmpeg + faster-whisper
  docgen.py          md / srt / txt / docx
  store.py           <video_id>/ layout and media.json contract
tests/               unittest, standard library only
```

Rule of thumb: **the Python engine must never import DSH, and the JS layer must
never contain media logic.** If a change crosses that line, it is probably in
the wrong file.

## Development setup

```bash
git clone https://github.com/junliu3/dsh-video.git
cd dsh-video

npm run bootstrap -- --skip-model   # creates python/.venv-asr, installs deps
npm run doctor                      # expect ffmpeg + model warnings until you add them
python -m ytdip.fetch_model small   # run from python/ if you want ASR
```

You need Node 20+, Python 3.11+ (3.12 recommended) and FFmpeg on `PATH` or in
`tools/ffmpeg/bin`.

## Running checks

Everything CI runs can be run locally:

```bash
python -m unittest discover -s tests -t . -v
node scripts/check-manifest.mjs
for f in lib/*.js scripts/*.mjs; do node --check "$f"; done
```

CI installs `python/requirements-dev.txt` (requests + websockets only) instead
of the full media stack; a bootstrap environment already contains them.

Optional, if you have the venv active:

```bash
node scripts/selftest.mjs              # registers tools with a fake ctx
node scripts/selftest.mjs --transcribe # also runs a local audio file end to end
```

## Changing the tool surface

DSH accepts only a **subset of JSON Schema** in `parameters`. Do not use
`minLength`, `maxLength`, `minimum` or `maximum` — the host rejects them. Stick
to `type`, `properties`, `required`, `items`, `enum`, `default`, `description`
and `additionalProperties`.

Two more constraints learned the hard way:

- `export const inject` must only list services that actually exist
  (`tools` is enough). Listing a missing service leaves the plugin pending and
  the host exits with code 1.
- Long work must go through `jobs.js`. A single `execute()` should not block for
  minutes; return a `jobId` and let the model poll `video_job_status`.

After changing a tool, update **both** README files and run
`node scripts/check-manifest.mjs`.

## Adding support for a site

1. Try it: `python -m ytdip.cli "<url>" --download-only`.
2. If yt-dlp handles it, only the version pin may need bumping.
3. If yt-dlp fails but the site is widely used, consider an extractor upstream
   first — that benefits every yt-dlp user.
4. Site-specific code beyond yt-dlp belongs in `python/ytdip/` as its own
   channel module, with the same `acquire(link, dest_dir, ...)` contract.

Please do not add request signing, cookie stealing or DRM circumvention. See
`SECURITY.md` for the project's scope.

## Commits and pull requests

- Keep commits focused; one logical change per commit.
- Message style: `area: what changed` (`asr: cache model instances`,
  `tools: rename douyin_* to video_*`).
- Fill in the PR template, including what you actually ran.
- Update `CHANGELOG.md` under `Unreleased`.

## License

By contributing you agree that your work is released under the MIT License
(`LICENSE`). Third-party code keeps its own license; see
`THIRD_PARTY_NOTICES.md`.
