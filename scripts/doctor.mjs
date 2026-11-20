#!/usr/bin/env node
/** 不启动 DSH 也能验证插件环境：npm run doctor */
import { spawnSync } from 'node:child_process';

import { describe, resolveConfig } from '../lib/config.js';

const cfg = resolveConfig();
console.log(describe(cfg));

if (!cfg.ready) {
  console.error(`\n找不到 Python：${cfg.pythonPath}\n先运行 npm run bootstrap`);
  process.exit(1);
}

const result = spawnSync(cfg.pythonPath, ['-m', 'ytdip.doctor', '--json'], {
  cwd: cfg.pythonDir,
  env: cfg.env,
  encoding: 'utf8',
});

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}

let report;
try {
  report = JSON.parse(result.stdout.trim());
} catch {
  console.error(result.stdout || result.stderr);
  process.exit(1);
}

for (const item of report.checks || []) {
  console.log(`  ${item.ok ? 'OK  ' : 'FAIL'} ${item.name.padEnd(14)} ${item.detail}`);
  if (item.fix) console.log(`       -> ${item.fix}`);
}
console.log(`\n${report.ok ? '全部通过' : '存在未通过项'}`);
process.exit(report.ok ? 0 : 1);
