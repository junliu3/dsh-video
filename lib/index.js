import { resolveConfig } from './config.js';
import { JobManager } from './jobs.js';
import { createTools } from './tools.js';

export const name = 'dsh-video';

// 只依赖 tools。不要在这里写 attachments / llm / webServer：
// Cordis 会为每个 key 空等，插件会永久 pending，宿主退出码 1。
export const inject = ['tools'];

/**
 * 插件入口。
 *
 * 这一层刻意做得很薄：注册 6 个工具，把作业交给 JobManager，卸载时收干净。
 * 真正的业务全在 python/ytdip 里，改转写逻辑不需要碰 JS。
 */
export function apply(ctx, rawConfig = {}) {
  const cfg = resolveConfig(rawConfig);
  const log = (message) => {
    try {
      ctx.logger?.debug?.(`[dsh-video] ${message}`);
    } catch {
      // 宿主没提供 logger 就静默
    }
  };

  log(`boot dataDir=${cfg.dataDir} python=${cfg.pythonPath}`);

  const manager = new JobManager(cfg, (message) => log(message));
  const disposers = [];

  try {
    for (const tool of createTools({ cfg, manager, log })) {
      disposers.push(ctx.tools.register(tool));
      log(`registered tool ${tool.name}`);
    }
  } catch (error) {
    manager.dispose();
    throw error;
  }

  ctx.effect?.(() => () => {
    for (const dispose of disposers.reverse()) {
      try {
        dispose?.();
      } catch {
        // 卸载失败不该阻断宿主
      }
    }
    manager.dispose();
    log('disposed');
  });

  return { cfg, manager };
}

export default { name, inject, apply };
