import { spawn } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

import { ensureStateDirs } from './config.js';

const TERMINAL = new Set(['succeeded', 'failed', 'canceled']);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function jobId() {
  return `j_${Date.now().toString(36)}_${crypto.randomBytes(3).toString('hex')}`;
}

/**
 * 作业管理：排队 → spawn Python worker → 解析 JSONL → 取消/超时/落盘。
 *
 * 设计要点：
 *  - 一次只跑 maxConcurrentJobs 个（默认 1），CPU int8 转写会把核吃满
 *  - 取消先落 .cancel 文件让 Python 自己收尾，8 秒后才 taskkill /T /F 杀进程树
 *    （直接 kill 会留下孤儿 msedge，占住 CDP 端口）
 *  - 每个作业一份 stderr 日志，失败时能直接给出日志路径
 */
export class JobManager {
  constructor(cfg, logger = null) {
    this.cfg = cfg;
    this.logger = logger;
    this.jobs = new Map();
    this.queue = [];
    this.active = 0;
    this.disposed = false;
    ensureStateDirs(cfg);
    this._reapStale();
  }

  /** DSH 重启后，把上次没跑完的作业标成 interrupted，别让人以为还在跑。 */
  _reapStale() {
    try {
      for (const name of fs.readdirSync(this.cfg.jobDir)) {
        if (!name.endsWith('.json')) continue;
        const file = path.join(this.cfg.jobDir, name);
        const record = JSON.parse(fs.readFileSync(file, 'utf8'));
        if (record.state === 'running' || record.state === 'queued') {
          record.state = 'interrupted';
          record.error = { code: 'INTERRUPTED', msg: 'DSH 重启，作业已中断', hint: '重新提交一次即可' };
          fs.writeFileSync(file, JSON.stringify(record, null, 2));
        }
      }
    } catch {
      // 目录不存在或文件损坏都不影响启动
    }
  }

  submit(input) {
    if (this.disposed) throw new Error('插件已卸载，无法提交新作业');
    const id = jobId();
    const record = {
      id,
      input,
      state: 'queued',
      stage: 'queued',
      pct: 0,
      message: '排队中',
      createdAt: Date.now(),
      startedAt: 0,
      finishedAt: 0,
      result: null,
      error: null,
      canceled: false,
      child: null,
      timer: null,
      logs: [],
      logPath: path.join(this.cfg.logDir, `${id}.log`),
    };
    record.done = new Promise((resolve) => {
      record._resolve = resolve;
    });
    this.jobs.set(id, record);
    this.queue.push(record);
    this._persist(record);
    queueMicrotask(() => this._pump());
    return record;
  }

  _pump() {
    if (this.disposed) return;
    const limit = Math.max(1, Number(this.cfg.maxConcurrentJobs) || 1);
    while (this.active < limit && this.queue.length > 0) {
      this._start(this.queue.shift());
    }
  }

  _start(record) {
    if (this.disposed) return;
    this.active += 1;
    record.state = 'running';
    record.stage = 'starting';
    record.startedAt = Date.now();
    record.message = '启动 worker';

    const payload = JSON.stringify({ ...record.input, jobId: record.id });
    const args = ['-m', 'ytdip.worker', '--job', payload, '--job-id', record.id];
    const child = spawn(this.cfg.pythonPath, args, {
      cwd: this.cfg.pythonDir,
      env: this.cfg.env,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    record.child = child;

    const logStream = fs.createWriteStream(record.logPath, { flags: 'a' });
    logStream.write(`# ${new Date().toISOString()} ${payload}\n`);

    let buffer = '';
    child.stdout.setEncoding('utf8');
    child.stdout.on('data', (chunk) => {
      buffer += chunk;
      let index = buffer.indexOf('\n');
      while (index >= 0) {
        const line = buffer.slice(0, index).trim();
        buffer = buffer.slice(index + 1);
        if (line) this._onLine(record, line);
        index = buffer.indexOf('\n');
      }
    });
    child.stderr.setEncoding('utf8');
    child.stderr.on('data', (chunk) => {
      logStream.write(chunk);
      for (const line of String(chunk).split('\n')) {
        const text = line.trim();
        if (!text) continue;
        record.logs.push(text);
        if (record.logs.length > 40) record.logs.shift();
      }
    });

    child.on('error', (err) => {
      record.error = { code: 'SPAWN_FAILED', msg: `无法启动 Python：${err.message}`, hint: this.cfg.pythonPath };
      this._finish(record, -1);
    });
    child.on('close', (code) => {
      logStream.end();
      this._finish(record, code);
    });

    record.timer = setTimeout(() => {
      if (!TERMINAL.has(record.state)) {
        this.logger?.(`job ${record.id} 超时，正在终止`);
        void this.cancel(record.id, 'timeout');
      }
    }, Math.max(30000, Number(this.cfg.jobTimeoutMs) || 900000));
  }

  _onLine(record, line) {
    let event;
    try {
      event = JSON.parse(line);
    } catch {
      record.logs.push(`[stdout] ${line.slice(0, 200)}`);
      return;
    }
    switch (event.t) {
      case 'start':
        record.stage = 'starting';
        break;
      case 'stage':
        record.stage = event.stage || record.stage;
        record.message = event.msg || '';
        record.pct = 0;
        break;
      case 'progress':
        record.stage = event.stage || record.stage;
        record.pct = typeof event.pct === 'number' ? event.pct : record.pct;
        if (event.msg) record.message = event.msg;
        break;
      case 'log':
        if (event.msg) {
          record.logs.push(String(event.msg));
          if (record.logs.length > 40) record.logs.shift();
        }
        break;
      case 'result':
        record.result = event.data || null;
        break;
      case 'error':
        record.error = { code: event.code || 'INTERNAL', msg: event.msg || '未知错误', hint: event.hint || '' };
        break;
      default:
        break;
    }
  }

  _finish(record, code) {
    if (TERMINAL.has(record.state)) return;
    if (record.timer) {
      clearTimeout(record.timer);
      record.timer = null;
    }
    record.child = null;
    record.finishedAt = Date.now();
    if (record.canceled) {
      record.state = 'canceled';
      record.message = '已取消';
    } else if (record.result) {
      record.state = 'succeeded';
      record.stage = 'done';
      record.pct = 100;
      record.message = '完成';
    } else {
      record.state = 'failed';
      if (!record.error) {
        record.error = {
          code: code === 0 ? 'NO_RESULT' : 'WORKER_EXIT',
          msg: `worker 退出（code=${code}），没有返回结果`,
          hint: '查看日志确认失败原因',
        };
      }
    }
    this.active = Math.max(0, this.active - 1);
    this._persist(record);
    record._resolve?.(this.status(record.id));
    this._pump();
  }

  _persist(record) {
    try {
      ensureStateDirs(this.cfg);
      const plain = {
        id: record.id,
        state: record.state,
        stage: record.stage,
        pct: record.pct,
        message: record.message,
        createdAt: record.createdAt,
        startedAt: record.startedAt,
        finishedAt: record.finishedAt,
        input: record.input,
        result: record.result,
        error: record.error,
        logPath: record.logPath,
      };
      fs.writeFileSync(path.join(this.cfg.jobDir, `${record.id}.json`),
        JSON.stringify(plain, null, 2));
    } catch {
      // 落盘失败不影响主流程
    }
  }

  status(id) {
    const record = this.jobs.get(id);
    if (!record) {
      const recovered = this._readPersisted(id);
      if (!recovered) return null;
      return recovered;
    }
    const queueIndex = this.queue.indexOf(record);
    return {
      id: record.id,
      state: record.state,
      stage: record.stage,
      pct: Math.round(record.pct),
      message: record.message,
      queuePosition: queueIndex >= 0 ? queueIndex + 1 : 0,
      elapsedSec: record.startedAt
        ? Math.round(((record.finishedAt || Date.now()) - record.startedAt) / 1000)
        : 0,
      result: record.result,
      error: record.error,
      logs: record.logs.slice(-12),
      logPath: record.logPath,
    };
  }

  _readPersisted(id) {
    if (!/^[A-Za-z0-9_-]+$/.test(String(id || ''))) return null;
    const file = path.join(this.cfg.jobDir, `${id}.json`);
    try {
      const record = JSON.parse(fs.readFileSync(file, 'utf8'));
      return {
        id: record.id,
        state: record.state,
        stage: record.stage,
        pct: record.pct || 0,
        message: record.message || '',
        queuePosition: 0,
        elapsedSec: record.startedAt
          ? Math.round(((record.finishedAt || Date.now()) - record.startedAt) / 1000)
          : 0,
        result: record.result || null,
        error: record.error || null,
        logs: [],
        logPath: record.logPath,
      };
    } catch {
      return null;
    }
  }

  async wait(id, timeoutMs) {
    const record = this.jobs.get(id);
    if (!record) return this.status(id);
    if (TERMINAL.has(record.state)) return this.status(id);
    await Promise.race([record.done, sleep(Math.max(0, timeoutMs))]);
    return this.status(id);
  }

  async cancel(id, reason = 'user') {
    const record = this.jobs.get(id);
    if (!record) return null;
    if (TERMINAL.has(record.state)) return this.status(id);

    record.canceled = true;
    record.message = reason === 'timeout' ? '超时，正在终止' : '正在取消';

    // 排队的作业不需要杀进程，直接出队收尾
    if (!record.child) {
      this.queue = this.queue.filter((item) => item !== record);
      this._finish(record, 0);
      return this.status(id);
    }

    // 先落取消标记，让 Python 自己清理临时目录和 msedge
    try {
      fs.writeFileSync(path.join(this.cfg.jobDir, `${id}.cancel`), reason);
    } catch {
      // 标记写不进去就退化为直接杀
    }
    await Promise.race([record.done, sleep(8000)]);
    if (!TERMINAL.has(record.state)) {
      this._killTree(record);
      await Promise.race([record.done, sleep(5000)]);
    }
    return this.status(id);
  }

  _killTree(record) {
    const pid = record.child?.pid;
    if (!pid) return;
    if (process.platform === 'win32') {
      try {
        spawn('taskkill', ['/PID', String(pid), '/T', '/F'], {
          windowsHide: true,
          stdio: 'ignore',
        });
      } catch {
        record.child?.kill('SIGKILL');
      }
      return;
    }
    try {
      process.kill(-pid, 'SIGKILL');
    } catch {
      try {
        record.child?.kill('SIGKILL');
      } catch {
        // 进程可能已经退出
      }
    }
  }

  dispose() {
    this.disposed = true;
    for (const record of this.jobs.values()) {
      if (!TERMINAL.has(record.state)) {
        record.canceled = true;
        this._killTree(record);
      }
    }
    this.queue = [];
  }
}
