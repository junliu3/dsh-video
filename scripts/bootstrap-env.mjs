#!/usr/bin/env node
/**
 * 首次环境自举：建 venv → 装依赖 → 拉模型 → 自检。
 *
 *   npm run bootstrap
 *   npm run bootstrap -- --model medium --skip-model
 *
 * 已有的 .venv-asr 会被复用，不会重装依赖；除非加 --force。
 */
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

import { PYTHON_DIR, resolveConfig } from '../lib/config.js';

const argv = process.argv.slice(2);
const force = argv.includes('--force');
const skipModel = argv.includes('--skip-model');
const modelFlag = argv.indexOf('--model');
const cfg = resolveConfig();
const model = modelFlag >= 0 ? argv[modelFlag + 1] : cfg.model;

const MIRROR = process.env.PIP_INDEX || 'https://pypi.tuna.tsinghua.edu.cn/simple';

function run(command, args, options = {}) {
  console.log(`\n> ${command} ${args.join(' ')}`);
  const result = spawnSync(command, args, { stdio: 'inherit', ...options });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`命令失败（exit ${result.status}）`);
}

function findBasePython() {
  const candidates = [
    ['py', ['-3.12', '-c', 'import sys;print(sys.executable)']],
    ['py', ['-3.11', '-c', 'import sys;print(sys.executable)']],
    ['python', ['-c', 'import sys;print(sys.executable)']],
  ];
  for (const [command, args] of candidates) {
    const result = spawnSync(command, args, { encoding: 'utf8' });
    if (result.status === 0 && result.stdout?.trim()) {
      return result.stdout.trim();
    }
  }
  return '';
}

function main() {
  fs.mkdirSync(PYTHON_DIR, { recursive: true });
  const venvPython = cfg.pythonPath;

  if (force && fs.existsSync(path.join(PYTHON_DIR, '.venv-asr'))) {
    console.log('--force：删除旧环境');
    fs.rmSync(path.join(PYTHON_DIR, '.venv-asr'), { recursive: true, force: true });
  }

  if (!fs.existsSync(venvPython)) {
    const base = findBasePython();
    if (!base) {
      console.error('找不到 Python 3.11/3.12。请先安装 Python 3.12，再重试。');
      process.exit(1);
    }
    console.log(`基础解释器 ${base}`);
    run(base, ['-m', 'venv', path.join(PYTHON_DIR, '.venv-asr')]);
  } else {
    console.log(`复用已有环境 ${venvPython}`);
  }

  run(venvPython, ['-m', 'pip', 'install', '-U', 'pip', '-i', MIRROR]);
  run(venvPython, ['-m', 'pip', 'install', '-r',
    path.join(PYTHON_DIR, 'requirements.txt'), '-i', MIRROR],
  { cwd: PYTHON_DIR });

  if (!skipModel) {
    run(venvPython, ['-m', 'ytdip.fetch_model', model], { cwd: PYTHON_DIR });
  }

  run(venvPython, ['-m', 'ytdip.doctor'], {
    cwd: PYTHON_DIR,
    env: cfg.env,
  });

  const ffmpeg = path.join(cfg.ffmpegDir, process.platform === 'win32' ? 'ffmpeg.exe' : 'ffmpeg');
  if (!fs.existsSync(ffmpeg)) {
    console.log('\n提示：没找到内置 ffmpeg。装一个系统版即可被自动识别：');
    console.log('  Windows: winget install Gyan.FFmpeg     macOS: brew install ffmpeg');
    console.log(`  或把 ffmpeg/ffprobe 放进 ${cfg.ffmpegDir}`);
  }

  console.log('\n环境就绪。接下来把插件装进 DSH：');
  console.log(`  dsh plugin --profile desktop add "${path.resolve(path.join(PYTHON_DIR, '..'))}"`);
}

main();
