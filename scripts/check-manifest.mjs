#!/usr/bin/env node
/**
 * Manifest sanity check — runs in CI, no dependencies.
 *
 * Verifies that package.json, cordis.patch.yml and the tool table agree, so a
 * rename can never ship half-done.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { resolveConfig } from '../lib/config.js';
import { createTools } from '../lib/tools.js';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const errors = [];

const pkg = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8'));
const patch = fs.readFileSync(path.join(ROOT, 'cordis.patch.yml'), 'utf8');

const patchId = patch.match(/-\s+id:\s*([A-Za-z0-9._-]+)/)?.[1];
const patchName = patch.match(/name:\s*([A-Za-z0-9._-]+)/)?.[1];

if (patchId !== pkg.name) {
  errors.push(`cordis.patch.yml id "${patchId}" != package.json name "${pkg.name}"`);
}
if (patchName !== pkg.name) {
  errors.push(`cordis.patch.yml name "${patchName}" != package.json name "${pkg.name}"`);
}
if (!fs.existsSync(path.join(ROOT, pkg.main))) {
  errors.push(`package.json main "${pkg.main}" does not exist`);
}
if (!pkg.dsh?.bundle?.patch) {
  errors.push('package.json is missing dsh.bundle.patch');
}
if (!fs.existsSync(path.join(ROOT, pkg.dsh.bundle.patch))) {
  errors.push(`bundle patch "${pkg.dsh.bundle.patch}" does not exist`);
}

const cfg = resolveConfig({});
const tools = createTools({ cfg, manager: {} });
const names = tools.map((tool) => tool.name);

if (tools.length === 0) {
  errors.push('no tools registered');
}
if (new Set(names).size !== names.length) {
  errors.push(`duplicate tool names: ${names.join(', ')}`);
}
for (const tool of tools) {
  if (!/^[a-z][a-z0-9_]*$/.test(tool.name)) {
    errors.push(`tool name "${tool.name}" is not snake_case`);
  }
  if (typeof tool.description !== 'string' || tool.description.length < 10) {
    errors.push(`tool "${tool.name}" has a missing or too short description`);
  }
  if (tool.parameters?.type !== 'object') {
    errors.push(`tool "${tool.name}" parameters must be a JSON object schema`);
  }
  if (typeof tool.execute !== 'function') {
    errors.push(`tool "${tool.name}" has no execute()`);
  }
  if (typeof tool.output?.render !== 'function') {
    errors.push(`tool "${tool.name}" has no output.render`);
  }
}

if (errors.length) {
  console.error('manifest check failed:');
  for (const error of errors) console.error(`  - ${error}`);
  process.exit(1);
}

console.log(`manifest OK — ${pkg.name}@${pkg.version}, ${tools.length} tools: ${names.join(', ')}`);
