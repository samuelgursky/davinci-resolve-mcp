/**
 * GHSA-h2fm-rcfg-jch9 — a tool caller chooses data, never the program the
 * server runs, and never a path the program would read as an option.
 *
 *  - the dispatcher refuses a binary-selecting key anywhere in the arguments,
 *    before any handler runs;
 *  - every `x || 'ffmpeg'`-style binary default in the source is covered by
 *    that key list, so a new binary option cannot slip past the boundary;
 *  - pg_dump comes from the operator's environment, and the backup lands in a
 *    fresh private directory however the database is named;
 *  - a caller path that would be parsed as an option is refused at each
 *    positional ffprobe/ffmpeg site.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

import { BINARY_OVERRIDE_KEYS, assertNoBinaryOverrides, assertNotOption } from '../server/spawn-guard.mjs';
import { callTool } from '../server/index.mjs';
import { unlinkInProject } from '../server/offline-ref-db.mjs';
import { probeStream } from '../server/extract-frames.mjs';

const require = createRequire(import.meta.url);
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

// ── the dispatcher boundary ─────────────────────────────────────────────────

test('every binary-selecting key is refused, at the top level and nested', () => {
  for (const key of BINARY_OVERRIDE_KEYS) {
    for (const args of [
      { [key]: '/tmp/evil' },
      { postgres: { database: 'x', [key]: '/tmp/evil' } },
      { cuts: [{ id: 1 }, { opts: { [key]: '/tmp/evil' } }] },
    ]) {
      assert.throws(() => assertNoBinaryOverrides(args), (e) => e.code === 'BINARY_OVERRIDE_REFUSED' && e.message.includes(key), key);
    }
  }
});

test('data under the same names is not a binary choice and passes', () => {
  // A probe result echoed back by a caller is an object, not a program.
  assertNoBinaryOverrides({ media: [{ path: '/m/a.mov', ffprobe: { codec: 'prores' } }], ffmpeg: true, python: null });
  assertNoBinaryOverrides({});
});

test('callTool refuses before the handler is reached', async () => {
  let reached = false;
  const tool = { name: 'spy', handler: async () => { reached = true; return { ok: true }; } };
  const refused = await callTool(tool, { action: 'link_in_project', args: { postgres: { database: 'd', pgDumpPath: '/bin/sh' } } });
  assert.equal(refused.isError, true);
  assert.match(refused.content[0].text, /cannot choose which program/);
  assert.equal(reached, false, 'the handler must not run');

  const allowed = await callTool(tool, { action: 'x', args: { postgres: { database: 'd' } } });
  assert.equal(allowed.isError, undefined);
  assert.equal(reached, true);
});

test('every binary default in the source is covered by the boundary key list', () => {
  // The shape that turns an option into a program: `ffmpegPath = 'ffmpeg'`,
  // `opts.ffprobe || 'ffprobe'`, `pg.pgDumpPath || 'pg_dump'`, `findPath = 'find'`.
  const RE = /([A-Za-z_][A-Za-z0-9_]*)\s*(?:\|\||\?\?|=)\s*['"](ffmpeg|ffprobe|pg_dump|find|python3?|node)['"]/g;
  const found = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (['node_modules', 'test', '__tests__', '__fixtures__'].includes(entry.name)) continue;
      const p = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(p);
      else if (/\.(mjs|cjs|js)$/.test(entry.name)) {
        for (const m of fs.readFileSync(p, 'utf8').matchAll(RE)) found.push({ file: path.relative(ROOT, p), key: m[1] });
      }
    }
  };
  walk(path.join(ROOT, 'server'));
  walk(path.join(ROOT, 'vendor'));
  assert.ok(found.length >= 10, `scan found too few binary defaults (${found.length}); the pattern is broken`);
  const uncovered = found.filter((f) => !BINARY_OVERRIDE_KEYS.includes(f.key));
  assert.deepEqual(uncovered, [], 'add these option names to BINARY_OVERRIDE_KEYS in server/spawn-guard.mjs');
});

// ── pg_dump and the backup path ─────────────────────────────────────────────

function fakeClient() {
  return {
    async query(sql, params = []) {
      if (sql.includes('information_schema')) return { rows: [{ ok: 1 }] };
      if (sql.startsWith('SELECT "Sm2Timeline_id" AS id')) return { rows: [{ id: 't1', Name: 'TL', OfflineClip: 'ref' }] };
      if (sql.includes('SELECT "OfflineClip" FROM')) return { rows: [{ OfflineClip: null }] };
      return { rows: [] };
    },
    async end() {},
  };
}

test('pg_dump is the operator\'s choice; a caller pgDumpPath is never run', { skip: process.platform === 'win32' }, async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'spawn-guard-'));
  const record = path.join(dir, 'argv.txt');
  const callerMarker = path.join(dir, 'caller-binary-ran');
  const operatorDump = path.join(dir, 'operator-pg_dump');
  const callerDump = path.join(dir, 'caller-binary');
  fs.writeFileSync(operatorDump, `#!/bin/sh\nprintf '%s\\n' "$@" > '${record}'\nexit 0\n`, { mode: 0o755 });
  fs.writeFileSync(callerDump, `#!/bin/sh\ntouch '${callerMarker}'\nexit 0\n`, { mode: 0o755 });
  const before = process.env.RESOLVE_ADVANCED_PG_DUMP;
  process.env.RESOLVE_ADVANCED_PG_DUMP = operatorDump;
  try {
    const result = await unlinkInProject({
      iConfirmProjectClosed: true,
      timelineId: 't1',
      postgres: { host: 'h', database: '../../../tmp/owned', pgDumpPath: callerDump, __client: fakeClient() },
    });
    assert.equal(fs.existsSync(callerMarker), false, 'the caller-named binary must not run');
    const argv = fs.readFileSync(record, 'utf8').trim().split('\n');
    const out = argv[argv.indexOf('-f') + 1];
    assert.equal(result.backup, out);
    // The database name shapes nothing: the file sits directly in a fresh dir under tmp.
    assert.equal(path.dirname(path.dirname(out)), os.tmpdir(), out);
    assert.ok(path.basename(path.dirname(out)).startsWith('offline-ref-backup-'), out);
    assert.equal(path.basename(out), 'Sm2Timeline-_________tmp_owned.sql');
    fs.rmSync(path.dirname(out), { recursive: true, force: true });
    // The real database name is still what pg_dump connects to.
    assert.equal(argv[argv.indexOf('-d') + 1], '../../../tmp/owned');
  } finally {
    if (before === undefined) delete process.env.RESOLVE_ADVANCED_PG_DUMP;
    else process.env.RESOLVE_ADVANCED_PG_DUMP = before;
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('offline_ref no longer advertises pgDumpPath', () => {
  const src = fs.readFileSync(path.join(ROOT, 'server/tools/offline_ref.mjs'), 'utf8');
  assert.equal(/pgDumpPath/.test(src), false);
});

// ── option-like caller paths ────────────────────────────────────────────────

test('assertNotOption refuses a leading dash and passes ordinary paths through', () => {
  assert.throws(() => assertNotOption('-report'), (e) => e.code === 'OPTION_LIKE_PATH_REFUSED');
  assert.throws(() => assertNotOption(''), /non-empty/);
  assert.equal(assertNotOption('/media/a-b.mov'), '/media/a-b.mov');
  assert.equal(assertNotOption('./-report'), './-report');
});

test('ffprobe positional sites refuse an option-like path before spawning', () => {
  assert.throws(() => probeStream('-report'), (e) => e.code === 'OPTION_LIKE_PATH_REFUSED');
  const { analyzeMediaList } = require('../vendor/conform-qc/repair/media-analysis.js');
  const [rec] = analyzeMediaList(['-report']);
  assert.equal(rec.ok, false);
  assert.match(rec.error, /refused/);
});

test('probeMedia refuses an option-like path', async (t) => {
  const { probeMedia } = await import('../server/ffprobe-media.mjs');
  try {
    probeMedia('/definitely/not/here.mov');
  } catch (e) {
    if (/ffmpeg|ffprobe/i.test(e.message) && !/starts with/.test(e.message)) {
      t.skip('ffprobe not installed; requireFfmpeg() refuses first');
      return;
    }
  }
  assert.throws(() => probeMedia('-report'), (e) => e.code === 'OPTION_LIKE_PATH_REFUSED');
});
