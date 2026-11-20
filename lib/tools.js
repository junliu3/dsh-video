import { execFile } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { promisify } from 'node:util';

import { PLUGIN_ROOT } from './config.js';

const run = promisify(execFile);

const OUTPUT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    text: { type: 'string' },
    ok: { type: 'boolean' },
    data: { type: 'object', additionalProperties: true },
  },
  required: ['text', 'ok'],
};

const renderText = (_args, value) => [{ type: 'text', text: String(value?.text ?? '') }];

const SAFE_ID = /^[A-Za-z0-9_-]{1,80}$/;
const TERMINAL_STATES = new Set(['succeeded', 'failed', 'canceled', 'interrupted']);

function mmss(seconds) {
  const total = Math.round(Number(seconds) || 0);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function shortError(error) {
  if (!error) return '';
  const hint = error.hint ? `\n建议：${error.hint}` : '';
  return `失败 [${error.code}] ${error.msg}${hint}`;
}

function formatJob(status) {
  if (!status) return '找不到这个作业（可能已过期清理）。';
  if (status.state === 'succeeded') {
    return formatResult(status.result, status);
  }
  if (status.state === 'failed' || status.state === 'interrupted') {
    const tail = (status.logs || []).slice(-6).join('\n');
    return `${shortError(status.error)}\n作业 ${status.id}｜日志 ${status.logPath}${tail ? `\n---\n${tail}` : ''}`;
  }
  if (status.state === 'canceled') {
    return `作业 ${status.id} 已取消。`;
  }
  const queue = status.queuePosition ? `（排队第 ${status.queuePosition} 位）` : '';
  return `作业 ${status.id} 运行中${queue}｜阶段 ${status.stage}｜${status.pct}%｜${status.message || ''}｜已用时 ${status.elapsedSec}s`;
}

function formatResult(result, status = null) {
  if (!result) return '作业结束但没有返回结果。';
  if (result.downloadOnly) {
    return [
      `已下载：${result.title || result.videoId}`,
      `平台 ${result.platform}｜时长 ${mmss(result.durationSec)}｜${result.mediaKind}`,
      `文件 ${result.mediaPath}`,
      `目录 ${result.dir}`,
      `用时 ${result.elapsedSec}s`,
    ].join('\n');
  }
  const meta = result.meta || {};
  const lines = [
    `文档已生成：${result.title || result.videoId}`,
    `平台 ${result.platform}｜时长 ${mmss(result.durationSec)}｜${meta.segments ?? 0} 段 / 约 ${meta.chars ?? 0} 字`,
    `转写 ${meta.asrModel || ''}（${meta.asrDevice || ''}）｜用时 ${result.elapsedSec}s`,
    `目录 ${result.dir}`,
  ];
  if (meta.noSpeech) lines.push('提示：未识别到人声，正文已标注；元数据与媒体仍保留。');
  if (result.files?.length) lines.push(`文件 ${result.files.join('、')}`);
  if (status?.id) lines.push(`作业 ${status.id}`);
  return lines.join('\n');
}

function readMedia(dir) {
  try {
    return JSON.parse(fs.readFileSync(path.join(dir, 'media.json'), 'utf8'));
  } catch {
    return {};
  }
}

export function createTools({ cfg, manager, log = () => {} }) {
  return [
    {
      name: 'video_doctor',
      description:
        '检查「链接转文档」插件的运行环境：Python 虚拟环境、faster-whisper、ffmpeg、Whisper 模型、yt-dlp、Edge 浏览器、资料库写权限。当用户问「能不能用 / 报错了 / 环境是否正常」时先调用它。',
      parameters: { type: 'object', additionalProperties: false, properties: {} },
      timeoutMs: 60000,
      output: { schema: OUTPUT_SCHEMA, render: renderText },
      async execute() {
        if (!cfg.ready) {
          return {
            ok: false,
            text: `Python 环境缺失：找不到 ${cfg.pythonPath}\n请先运行 npm run bootstrap（或 scripts/bootstrap-env.mjs）建立 python/.venv-asr。`,
            data: { pythonPath: cfg.pythonPath },
          };
        }
        try {
          const { stdout } = await run(cfg.pythonPath, ['-m', 'ytdip.doctor', '--json'], {
            cwd: cfg.pythonDir,
            env: cfg.env,
            timeout: 45000,
            maxBuffer: 4 * 1024 * 1024,
            windowsHide: true,
          });
          const report = JSON.parse(stdout.trim());
          const lines = ['环境自检：' + (report.ok ? '全部通过' : '存在未通过项')];
          for (const item of report.checks || []) {
            lines.push(`  ${item.ok ? 'OK  ' : 'FAIL'} ${item.name}  ${item.detail}`);
            if (item.fix) lines.push(`       -> ${item.fix}`);
          }
          lines.push(`资料库 ${report.paths?.libRoot || cfg.dataDir}`);
          return { ok: Boolean(report.ok), text: lines.join('\n'), data: report };
        } catch (error) {
          const detail = error?.stdout || error?.message || String(error);
          return { ok: false, text: `自检执行失败：${detail}`, data: { error: String(detail) } };
        }
      },
    },

    {
      name: 'video_download',
      description:
        '只下载音视频，不出文档。支持抖音链接（走无水印通道）以及 yt-dlp 支持的其它站点（B 站、YouTube、微博等）。默认等待完成，超时则返回作业号。',
      parameters: {
        type: 'object',
        additionalProperties: false,
        properties: {
          source: { type: 'string', description: '作品链接、抖音作品 ID，或本地文件路径' },
          kind: { type: 'string', enum: ['video', 'audio'], default: 'video', description: 'video 下视频（mp4），audio 只下音频（mp3）' },
          wait: { type: 'boolean', default: true, description: '是否等待下载完成；false 立刻返回作业号' },
        },
        required: ['source'],
      },
      timeoutMs: 180000,
      output: { schema: OUTPUT_SCHEMA, render: renderText },
      async execute(args) {
        const record = manager.submit({
          source: String(args.source || '').trim(),
          audioOnly: args.kind === 'audio',
          downloadOnly: true,
        });
        log(`download job ${record.id}`);
        if (args.wait === false) {
          return { ok: true, text: `已提交下载作业 ${record.id}，用 video_job_status 查看进度。`, data: { jobId: record.id } };
        }
        const status = await manager.wait(record.id, Number(cfg.waitMs) || 120000);
        const done = status?.state === 'succeeded';
        return { ok: done, text: formatJob(status), data: { jobId: record.id, status } };
      },
    },

    {
      name: 'video_to_doc',
      description:
        '把一条视频转成结构化文档：下载 → 抽音轨 → Whisper 转写 → 生成 report.md / report.docx / transcript.srt / transcript.txt。支持抖音和 yt-dlp 支持的其它站点。视频较长时会返回作业号，用 video_job_status 轮询。',
      parameters: {
        type: 'object',
        additionalProperties: false,
        properties: {
          source: { type: 'string', description: '作品链接、抖音作品 ID，或本地音视频文件路径' },
          model: { type: 'string', enum: ['tiny', 'base', 'small', 'medium', 'large-v3'], description: 'Whisper 模型，默认沿用插件配置（small）' },
          language: { type: 'string', description: '语言代码：zh（默认）、en，或 auto 自动识别' },
          device: { type: 'string', enum: ['cpu', 'cuda'], description: '计算设备，默认 cpu（更稳）' },
          dropMedia: { type: 'boolean', default: false, description: '出完文档后删除视频原件，只留文字' },
          wait: { type: 'boolean', default: true, description: '是否等待完成；false 立刻返回作业号' },
        },
        required: ['source'],
      },
      timeoutMs: 180000,
      output: { schema: OUTPUT_SCHEMA, render: renderText },
      async execute(args) {
        const source = String(args.source || '').trim();
        if (!source) throw new Error('source 不能为空');
        const record = manager.submit({
          source,
          model: args.model || undefined,
          language: args.language || undefined,
          device: args.device || undefined,
          dropMedia: Boolean(args.dropMedia),
        });
        log(`to_doc job ${record.id} <- ${source}`);
        if (args.wait === false) {
          return {
            ok: true,
            text: `已提交转文档作业 ${record.id}。用 video_job_status 查看进度，完成后会给出产物目录。`,
            data: { jobId: record.id },
          };
        }
        const status = await manager.wait(record.id, Number(cfg.waitMs) || 120000);
        if (status?.state === 'succeeded') {
          return { ok: true, text: formatJob(status), data: { jobId: record.id, result: status.result } };
        }
        if (TERMINAL_STATES.has(status?.state)) {
          return { ok: false, text: formatJob(status), data: { jobId: record.id, status } };
        }
        return {
          ok: true,
          text: `作业 ${record.id} 仍在进行（${status?.stage} ${status?.pct}%）。用 video_job_status 继续查询。`,
          data: { jobId: record.id, status },
        };
      },
    },

    {
      name: 'video_job_status',
      description: '查询转写/下载作业的进度、结果或失败原因。',
      parameters: {
        type: 'object',
        additionalProperties: false,
        properties: {
          jobId: { type: 'string', description: 'video_to_doc / video_download 返回的作业号' },
        },
        required: ['jobId'],
      },
      timeoutMs: 15000,
      output: { schema: OUTPUT_SCHEMA, render: renderText },
      async execute(args) {
        const status = manager.status(String(args.jobId || '').trim());
        if (!status) return { ok: false, text: `找不到作业 ${args.jobId}` };
        return { ok: status.state === 'succeeded', text: formatJob(status), data: status };
      },
    },

    {
      name: 'video_job_cancel',
      description: '取消一个正在排队或运行中的作业，并清理中间临时文件与无头浏览器进程。',
      parameters: {
        type: 'object',
        additionalProperties: false,
        properties: {
          jobId: { type: 'string', description: '要取消的作业号' },
        },
        required: ['jobId'],
      },
      timeoutMs: 25000,
      output: { schema: OUTPUT_SCHEMA, render: renderText },
      async execute(args) {
        const status = await manager.cancel(String(args.jobId || '').trim());
        if (!status) return { ok: false, text: `找不到作业 ${args.jobId}` };
        return { ok: true, text: `作业 ${status.id} 状态：${status.state}`, data: status };
      },
    },

    {
      name: 'video_library',
      description:
        '浏览已生成的资料库。action=list 列出条目（可按关键词筛选），action=read 读取某条文档正文。用户问「之前转过哪些 / 把那份文档发我看看」时使用。',
      parameters: {
        type: 'object',
        additionalProperties: false,
        properties: {
          action: { type: 'string', enum: ['list', 'read'], default: 'list' },
          keyword: { type: 'string', description: 'list 时的标题/ID 关键词' },
          limit: { type: 'number', default: 20, description: 'list 返回条数，默认 20' },
          videoId: { type: 'string', description: 'read 时的作品 ID（目录名）' },
        },
        required: ['action'],
      },
      timeoutMs: 20000,
      output: { schema: OUTPUT_SCHEMA, render: renderText },
      async execute(args) {
        const action = args.action || 'list';
        if (action === 'read') {
          const id = String(args.videoId || '').trim();
          if (!SAFE_ID.test(id)) return { ok: false, text: 'videoId 不合法（只允许字母、数字、下划线和短横线）' };
          const dir = path.join(cfg.dataDir, id);
          for (const name of ['report.md', 'transcript.txt']) {
            const file = path.join(dir, name);
            if (fs.existsSync(file)) {
              let body = fs.readFileSync(file, 'utf8');
              if (body.length > 6000) body = `${body.slice(0, 6000)}\n\n…（已截断，完整内容见 ${file}）`;
              return { ok: true, text: body, data: { videoId: id, file } };
            }
          }
          return { ok: false, text: `目录 ${dir} 下没有 report.md 或 transcript.txt` };
        }

        const limit = Math.min(100, Math.max(1, Number(args.limit) || 20));
        const keyword = String(args.keyword || '').trim().toLowerCase();
        let names = [];
        try {
          names = fs.readdirSync(cfg.dataDir, { withFileTypes: true })
            .filter((entry) => entry.isDirectory() && !entry.name.startsWith('.'))
            .map((entry) => entry.name);
        } catch {
          return { ok: true, text: `资料库还是空的：${cfg.dataDir}`, data: { items: [] } };
        }

        const items = [];
        for (const name of names) {
          const dir = path.join(cfg.dataDir, name);
          const record = readMedia(dir);
          const title = record.title || name;
          if (keyword && !title.toLowerCase().includes(keyword) && !name.toLowerCase().includes(keyword)) continue;
          items.push({
            videoId: name,
            title,
            platform: record.platform || '',
            durationSec: record.duration_sec || 0,
            capturedAt: record.captured_at || '',
            hasReport: fs.existsSync(path.join(dir, 'report.md')),
            dir,
          });
        }
        items.sort((a, b) => String(b.capturedAt).localeCompare(String(a.capturedAt)));
        const page = items.slice(0, limit);
        if (page.length === 0) {
          return { ok: true, text: `没有匹配的条目（资料库 ${cfg.dataDir}）`, data: { items: [] } };
        }
        const lines = [`资料库共 ${items.length} 条，显示前 ${page.length} 条：`];
        for (const item of page) {
          lines.push(`- ${item.videoId}｜${item.title}｜${item.platform}｜${mmss(item.durationSec)}｜${item.capturedAt || '未知时间'}${item.hasReport ? '' : '｜无文档'}`);
        }
        return { ok: true, text: lines.join('\n'), data: { items: page, total: items.length, root: cfg.dataDir } };
      },
    },
  ];
}

export { PLUGIN_ROOT };
