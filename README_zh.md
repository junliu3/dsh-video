# dsh-video

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](python/requirements.txt)
[![Node](https://img.shields.io/badge/node-20%2B-brightgreen)](package.json)
[![DSH](https://img.shields.io/badge/DSH-0.2.1--rc.5-purple)](https://github.com/deepseek-ai)
[![Version](https://img.shields.io/badge/version-1.0.0-informational)](CHANGELOG.md)

[English](README.md) | **简体中文**

`dsh-video` 是一个 [DeepSeek Harness](https://github.com/deepseek-ai) 插件：
把一条视频链接变成**能读、能搜、能引用**的文档。

在对话里粘个链接，模型就会下载视频、抽出音轨、用 Whisper 转写，然后把
`report.md`、`report.docx`、`transcript.srt`、`transcript.txt` 写进这条视频
自己的目录。不用拖进度条，也不用边看边记。

支持三类来源：**抖音**（1080P 无水印、免登录免 Cookie）、**yt-dlp 支持的
所有站点**（B 站、YouTube、微博等）、以及**你本地的音视频文件**。

```
链接 / 本地文件
      │
      ├── 抖音 ............ 无头 Edge + CDP → 真实播放地址
      └── 其它站点 ........ yt-dlp → 合流 mp4 或抽 mp3
      │
      ├── ffmpeg .......... 16kHz 单声道 wav
      ├── faster-whisper .. 带时间戳的片段（默认 CPU int8）
      └── docgen .......... report.md / .docx / .srt / .txt / segments.json
```

## 功能特性

| | |
| --- | --- |
| **两条下载通道** | 抖音走 CDP（免登录、免 Cookie，DASH 画面/声音自动合流）；其余站点走 yt-dlp |
| **本地转写** | faster-whisper 全程在本机跑，音频不出门 |
| **结构化产物** | 按停顿合并段落、保留时间戳、SRT 可直接进剪映/PotPlayer，可选输出 Word |
| **失败也说人话** | 纯音乐作品照样出文档并标注「未识别到人声」；每种失败都带错误码和修复建议 |
| **为对话而生** | 6 个工具、作业队列、进度轮询、取消后自己收拾干净 |
| **没有 UI，没有遥测** | 配置写在 `cordis.patch.yml`；除了你给的链接，不往任何地方发数据 |
| **可搬迁** | 所有路径由环境变量注入，插件、命令行、复制到别处都能跑 |

## 环境要求

- **DSH** 0.2.1-rc.2 及以上（实测 0.2.1-rc.5）
- **Node.js** 20+
- **Python** 3.11+（推荐 3.12）
- **FFmpeg** 与 **ffprobe** —— 放进 `PATH` 或 `tools/ffmpeg/bin/` 均可
- **约 2.5 GB** 磁盘用于 Python 环境，另加每个 Whisper 模型 0.5–3 GB
- **Microsoft Edge** 仅抖音通道需要（Linux/macOS 自动退回 yt-dlp）

## 安装

### 1. 取代码

```bash
git clone https://github.com/junliu3/dsh-video.git
cd dsh-video
```

### 2. 建 Python 环境

```bash
npm run bootstrap                 # 建 venv + 装依赖 + 下 small 模型
npm run bootstrap -- --skip-model # 先不下模型
npm run bootstrap -- --model medium
```

`bootstrap` 会创建 `python/.venv-asr/`，安装 `python/requirements.txt`
（faster-whisper、yt-dlp、python-docx、requests、websockets），并从
`hf-mirror.com` 拉取模型。已有环境会被复用，不会重装。

### 3. 装进 DSH

```bash
dsh plugin --profile desktop add "C:\你的路径\dsh-video"
```

再确认 profile 把它列进 bundles —— DSH 只挂载 `dsh.profile.bundles` 里的插件：

```jsonc
// ~/.dsh/profiles/desktop/package.json
"dsh": { "profile": { "bundles": [ ..., "dsh-video" ] } }
```

改完重启 DSH。插件树只在启动时合成。

### 4. 验证

在对话里说「检查一下转文档环境」，或者自己跑：

```bash
npm run doctor
```

九项检查：Python、venv、faster-whisper、ffmpeg、ffprobe、模型、yt-dlp、Edge、
资料库写权限。

### 不克隆，直接从 GitHub 装

```bash
dsh plugin --profile desktop add github:junliu3/dsh-video
# 或
dsh plugin --profile desktop add https://codeload.github.com/junliu3/dsh-video/tar.gz/refs/heads/main
```

Python 环境仍要在装好的包目录里建一次：到
`~/.dsh/profiles/desktop/node_modules/dsh-video` 下执行 `npm run bootstrap`。

## 使用

### 对话里

| 你说 | 会发生什么 |
| --- | --- |
| 「把这个转成文档：`https://www.douyin.com/video/...`」 | `video_to_doc` 下载、转写、写全套文件 |
| 「我之前转过哪些视频？」 | `video_library` 列出资料库 |
| 「把 `BV1GJ411x7h7` 的文档给我看看」 | `video_library` 把 `report.md` 读回对话 |
| 「只要音频：`https://youtu.be/...`」 | `video_download` 带 `kind: audio` |
| 「那个好了吗？」 | `video_job_status` |
| 「停掉」 | `video_job_cancel` |

### 工具

| 工具 | 用途 | 主要参数 |
| --- | --- | --- |
| `video_doctor` | 环境自检，带修复建议 | — |
| `video_download` | 只要媒体，不转写 | `source`、`kind: video\|audio`、`wait` |
| `video_to_doc` | 全链路 | `source`、`model`、`language`、`device`、`dropMedia`、`wait` |
| `video_job_status` | 阶段、百分比、结果或失败原因 | `jobId` |
| `video_job_cancel` | 停止并清理 | `jobId` |
| `video_library` | 浏览或读取历史文档 | `action: list\|read`、`keyword`、`limit`、`videoId` |

`video_to_doc` 默认最多等 `waitMs`（120 秒），短视频一次调用就能出结果；
长视频会返回 `jobId`，之后用 `video_job_status` 轮询。

### 命令行

引擎不依赖 DSH 也能用：

```bash
cd python

.venv-asr/Scripts/python.exe -m ytdip.cli "https://www.douyin.com/video/xxx"
.venv-asr/Scripts/python.exe -m ytdip.cli "https://www.bilibili.com/video/BVxxx" --audio
.venv-asr/Scripts/python.exe -m ytdip.cli --file "D:\talk.mp4" --id 团队周会
.venv-asr/Scripts/python.exe -m ytdip.cli "链接" --json      # JSONL 事件流

.venv-asr/Scripts/python.exe -m ytdip.doctor                # 同上自检
.venv-asr/Scripts/python.exe -m ytdip.fetch_model medium    # 预下模型
.venv-asr/Scripts/python.exe -m ytdip.migrate --from "D:\旧资料库"
```

常用参数：`--download-only`、`--audio`、`--model`、`--device cpu|cuda`、
`--lang zh|en|auto`、`--keep-wav`、`--drop-media`、`--no-docx`。

## 产物

一条作品一个目录，目录名用站点给的 video_id，**绝不用标题**——中文、emoji、
超长标题都不会把路径搞坏：

```
~/.dsh/data/yt-dip/
└── 7700987993812749610/
    ├── 7700987993812749610.mp4    视频原件
    ├── report.md                  结构化文档（带 front-matter）
    ├── report.docx                Word 版
    ├── transcript.srt             字幕
    ├── transcript.txt             纯文本
    ├── segments.json              带时间戳的片段，供二次开发
    └── media.json                 元数据契约
```

`media.json` 记录了原始链接、标题、时长、采集时间，以及用了哪个模型转写，
任何时候都能复现或核对。

## 配置

刻意不做设置页——直接在 profile 补丁层覆盖：

```yaml
# ~/.dsh/profiles/desktop/cordis.patch.yml
- id: dsh-video
  config:
    dataDir: "D:\\媒体\\转写"
    model: "medium"
    device: "cpu"
    language: "zh"
    maxConcurrentJobs: 1
    jobTimeoutMs: 1800000
```

这里**不要**再写 `insert`：bundle 层已经插入过，重复的 id 会让设置存不上。

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `dataDir` | `~/.dsh/data/yt-dip` | 资料库根目录 |
| `pythonPath` | `python/.venv-asr/Scripts/python.exe` | 要 spawn 的解释器 |
| `ffmpegDir` | `tools/ffmpeg/bin` | 放 ffmpeg/ffprobe 的目录 |
| `edgePath` | 自动探测 | `msedge.exe`，只抖音通道用 |
| `model` | `small` | `tiny`、`base`、`small`、`medium`、`large-v3` |
| `device` | `cpu` | 允许 `cuda`，失败自动回退 CPU |
| `language` | `zh` | `auto` 交给 Whisper 判断 |
| `maxConcurrentJobs` | `1` | 转写会吃满 CPU，排队比抢核快 |
| `jobTimeoutMs` | `900000` | 单作业硬超时 |
| `waitMs` | `120000` | 工具调用最多阻塞多久后转作业号 |

## 模型

权重放在 `runtime/models/`，不进仓库。

| 尺寸 | 磁盘 | CPU 8 核实测 | 说明 |
| --- | --- | --- | --- |
| `small` | 464 MB | 约 7 倍速 | 默认，中文够用 |
| `medium` | 1.5 GB | 约 2 倍速 | 口音和专业词更稳 |
| `large-v3` | 3.1 GB | 低于实时 | 质量最好，也最重 |

支持 `cuda`，但在开发机上不稳定（同一段音频时而 12 秒时而 205 秒），
所以默认走 CPU。

## 排错

| 现象 | 处理 |
| --- | --- |
| 工具一直不出现 | `dsh.profile.bundles` 里有 `dsh-video` 吗？改完必须重启 DSH |
| `MODEL_MISSING` | 在 `python/` 下跑 `python -m ytdip.fetch_model small` |
| `EDGE_MISSING` | 装 Edge 或配置 `edgePath`；其它站点不受影响 |
| `NO_STREAM` | 作品已删或页面改版；作业日志里有当时的页面文本 |
| `LOGIN_REQUIRED` | B 站 1080P/会员内容需要 Cookie，当前不支持 |
| `YTDLP_MISSING` | `npm run bootstrap`，或在 venv 里 `pip install yt-dlp` |
| `FFMPEG_MISSING` | `winget install Gyan.FFmpeg`，或把二进制放进 `tools/ffmpeg/bin` |
| 转写太慢 | 换 `small`；有显卡可以试 `device: cuda` |
| 作业显示 `INTERRUPTED` | DSH 中途重启了，重新提交一次 |
| 想看原始失败 | `<dataDir>/.state/logs/<jobId>.log` |

## 边界

- 一次一条。不做播放列表、合集、收藏夹。
- 只做转写。不做摘要，不做画面/幻灯片理解。
- 抖音通道依赖 Edge 和 Windows 那套进程处理；Linux/macOS 上该通道不可用，
  会自动走 yt-dlp。
- 机器转写会听错人名、数字和术语，引用前请核对原片。

## 参与贡献

欢迎提 bug、补站点、改产物格式，先看 [CONTRIBUTING.md](CONTRIBUTING.md)。
提交前跑一遍和 CI 相同的检查：

```bash
python -m unittest discover -s tests -t . -v
node scripts/check-manifest.mjs
```

安全问题请按 [SECURITY.md](SECURITY.md) 私下报告。

## 许可证

[MIT](LICENSE) © 2026 junliu3。

第三方组件保留自己的许可证，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
FFmpeg 与 Whisper 权重**不随本仓库分发**。

## 致谢

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) —— 站点解析，以及本仓库的组织方式
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) —— 语音识别
- [FFmpeg](https://ffmpeg.org/) —— 音视频处理
- [DeepSeek Harness](https://github.com/deepseek-ai) —— 插件宿主

## 免责声明

`dsh-video` 是个人归档工具。请只下载和处理你有权使用的内容，并遵守各站点的
服务条款。作者不对使用方式负责。
