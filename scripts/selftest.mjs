#!/usr/bin/env node
/**
 * 不启动 DSH 的自测：用假的 ctx 跑真实插件代码。
 *
 *   node scripts/selftest.mjs                # 只测工具注册 + doctor + 资料库
 *   node scripts/selftest.mjs --transcribe   # 额外跑一次本地音频转写
 */
import fs from 'node:fs';
import path from 'node:path';

import { apply } from '../lib/index.js';

const argv = process.argv.slice(2);
const withTranscribe = argv.includes('--transcribe');

const registered = [];
let cleanup = null;

const ctx = {
  logger: { debug: () => {} },
  tools: {
    register(tool) {
      registered.push(tool);
      return () => {};
    },
  },
  effect(factory) {
    cleanup = factory();
  },
};

const api = apply(ctx, {});
const cfg = api.cfg;
const byName = (name) => registered.find((tool) => tool.name === name);

const failures = [];
function check(label, ok, detail = '') {
  console.log(`  ${ok ? 'OK  ' : 'FAIL'} ${label}${detail ? `  ${detail}` : ''}`);
  if (!ok) failures.push(label);
}

console.log(`插件注册 ${registered.length} 个工具：${registered.map((t) => t.name).join(', ')}`);
check('注册 6 个工具', registered.length === 6);

const doctor = byName('video_doctor');
const doctorResult = await doctor.execute({}, {});
check('doctor 通过', doctorResult.ok === true,
  doctorResult.text.split('\n').filter((line) => line.includes('FAIL')).join(' ') || '');

const library = byName('video_library');
const listResult = await library.execute({ action: 'list', limit: 5 }, {});
check('library 可列出资料库', listResult.ok === true,
  (listResult.data?.items || []).map((item) => item.videoId).join(', '));

check('资料库落在 ~/.dsh/data/yt-dip', cfg.dataDir.endsWith(path.join('.dsh', 'data', 'yt-dip')), cfg.dataDir);

if (withTranscribe) {
  const sample = process.env.YTDIP_SAMPLE
    || path.join(process.env.USERPROFILE || process.env.HOME || '', 'Desktop', '大肥鱼', 'yt-dip', '资料库', '_sample_zh.mp3');
  if (!fs.existsSync(sample)) {
    console.log(`  跳过转写测试（找不到样例 ${sample}，可用 YTDIP_SAMPLE 指定）`);
  } else {
    const doc = byName('video_to_doc');
    const result = await doc.execute({ source: sample, wait: true }, {});
    check('本地音频转文档', result.ok === true, result.text.split('\n')[1] || result.text.slice(0, 120));
    if (result.ok) {
      const report = result.data?.result?.report;
      check('report.md 存在', Boolean(report && fs.existsSync(report)), report || '');
    }
  }
}

cleanup?.();
api.manager.dispose();

console.log(failures.length ? `\n${failures.length} 项未通过` : '\n自测全部通过');
process.exit(failures.length ? 1 : 0);
