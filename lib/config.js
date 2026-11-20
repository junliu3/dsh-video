import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const PLUGIN_ROOT = path.dirname(HERE);
export const PYTHON_DIR = path.join(PLUGIN_ROOT, 'python');

export const DEFAULTS = {
  dataDir: '',
  pythonPath: '',
  ffmpegDir: '',
  edgePath: '',
  model: 'small',
  device: 'cpu',
  language: 'zh',
  maxConcurrentJobs: 1,
  jobTimeoutMs: 900000,
  waitMs: 120000,
  verbose: false,
};

function isFile(candidate) {
  try {
    return fs.statSync(candidate).isFile();
  } catch {
    return false;
  }
}

function defaultPython() {
  const rel = process.platform === 'win32'
    ? ['Scripts', 'python.exe']
    : ['bin', 'python3'];
  return path.join(PYTHON_DIR, '.venv-asr', ...rel);
}

function defaultFfmpegDir() {
  return path.join(PLUGIN_ROOT, 'tools', 'ffmpeg', 'bin');
}

export function resolveConfig(raw = {}) {
  const merged = { ...DEFAULTS, ...(raw || {}) };
  const dshHome = process.env.DSH_HOME || path.join(os.homedir(), '.dsh');
  const dataDir = path.resolve(merged.dataDir || path.join(dshHome, 'data', 'yt-dip'));
  const pythonPath = merged.pythonPath || defaultPython();
  const ffmpegDir = merged.ffmpegDir || defaultFfmpegDir();
  const stateDir = path.join(dataDir, '.state');

  const env = {
    ...process.env,
    // 中文路径 + JSONL 输出必须显式声明编码
    PYTHONUTF8: '1',
    PYTHONIOENCODING: 'utf-8',
    PYTHONPATH: PYTHON_DIR,
    YTDIP_LIB_ROOT: dataDir,
    YTDIP_FFMPEG_DIR: ffmpegDir,
    YTDIP_MODEL: String(merged.model),
    YTDIP_DEVICE: String(merged.device),
    YTDIP_LANG: String(merged.language),
    YTDIP_CPU_THREADS: String(merged.cpuThreads || 0),
  };
  if (merged.edgePath) env.YTDIP_EDGE = merged.edgePath;

  return {
    ...merged,
    dshHome,
    dataDir,
    stateDir,
    logDir: path.join(stateDir, 'logs'),
    jobDir: path.join(stateDir, 'jobs'),
    pythonPath,
    pythonDir: PYTHON_DIR,
    ffmpegDir,
    env,
    ready: isFile(pythonPath),
  };
}

export function ensureStateDirs(cfg) {
  for (const dir of [cfg.dataDir, cfg.stateDir, cfg.logDir, cfg.jobDir]) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

export function describe(cfg) {
  return [
    `项目    ${PLUGIN_ROOT}`,
    `资料库  ${cfg.dataDir}`,
    `Python  ${cfg.pythonPath}${cfg.ready ? '' : '  (未找到)'}`,
    `ffmpeg  ${cfg.ffmpegDir}`,
    `模型    ${cfg.model} / ${cfg.device} / ${cfg.language}`,
  ].join('\n');
}
