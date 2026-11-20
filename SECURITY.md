# Security policy

## Reporting a vulnerability

Open a private security advisory on GitHub
(`https://github.com/junliu3/dsh-video/security/advisories/new`) or email the
maintainer listed on the GitHub profile. Please do not open a public issue for
anything that could be exploited before a fix is available.

Useful reports include:

- command / argument injection through a link, title or config value
- path traversal in `<video_id>` handling or `video_library`
- a way for a downloaded file or page to execute code
- secrets leaking into logs, job files or generated documents

We aim to acknowledge within a few days. This is a volunteer project, so there
is no SLA.

## What this project does on your machine

Be aware of the blast radius before you install it:

- **Spawns local processes**: `python`, `ffmpeg`/`ffprobe`, and — for Douyin —
  a headless `msedge` with a temporary profile. Cancelling a job kills that
  process tree (`taskkill /T /F` on Windows).
- **Writes to disk**: the library directory (default `~/.dsh/data/yt-dip`),
  including downloaded video and transcripts.
- **Uses the network**: the link you provide, the site's CDN, and the model
  mirror (`hf-mirror.com` by default) when fetching Whisper weights.
- **Does not** read browser profiles or cookies, run as administrator, or send
  your media anywhere except back to the site you asked for.

## Scope

In scope for this project:

- the plugin layer in `lib/`
- the engine in `python/ytdip/`
- scripts in `scripts/`

Out of scope:

- yt-dlp extractor bugs (report upstream)
- FFmpeg or model vulnerabilities (report to their projects)
- Terms-of-service disputes with the sites you download from

## Responsible use

`dsh-video` is a personal archiving and transcription tool. You are responsible
for having the right to download and process whatever you point it at, and for
following the terms of service of each site. Do not use it to redistribute
copyrighted material or to circumvent paywalls and DRM.
