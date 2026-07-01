/** capabilities reporting + the no-GPL-bundling contract. */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { capabilitiesTool } from '../server/tools/capabilities.mjs';

test('capabilities reports core + optional features with install hints', async () => {
  const c = await capabilitiesTool.handler({ action: 'get', args: {} });
  assert.ok(c.core);
  for (const k of ['ffmpeg', 'sharp', 'better-sqlite3']) {
    assert.ok('available' in c.optional[k], `${k} has availability`);
    assert.ok(c.optional[k].install, `${k} has an install hint`);
  }
});

test('package.json does NOT bundle GPL ffmpeg-static/ffprobe-static', () => {
  const pkgPath = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'package.json');
  const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));
  const allDeps = { ...pkg.dependencies, ...pkg.optionalDependencies };
  assert.ok(!('ffmpeg-static' in allDeps), 'ffmpeg-static must not be a dependency (GPL)');
  assert.ok(!('ffprobe-static' in allDeps), 'ffprobe-static must not be a dependency (GPL)');
});
