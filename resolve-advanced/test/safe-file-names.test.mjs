/**
 * GHSA-c3m4-m58c-4pc7: caller values (clip ids, group and scene names) were
 * interpolated into output file names, so an id like "../../x" wrote a DRX or
 * PNG outside outDir. Covers the shared helper, two matchers end to end, and a
 * guard that every interpolated output file name in the server is reviewed.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { fileInside, isSafeFileComponent, outputFileIn } from '../server/safe-path.mjs';
import { computeBlackBalance } from '../server/black-balance.mjs';
import { computeMatchToReference } from '../server/match-to-reference.mjs';

const require = createRequire(import.meta.url);
const sharp = require('sharp');
const SERVER = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'server');
const UNSAFE = ['../../outside', '..', '.', 'a/b', 'a\\b', '/etc/x', 'C:\\x', '', 'ok\n', 'x'.repeat(201)];

test('isSafeFileComponent accepts plain names and refuses separators and dot-segments', () => {
  for (const v of ['A001', 7, 'A001 C003', 'x.y-z_1', '3f2a-9c1e']) assert.ok(isSafeFileComponent(v), String(v));
  for (const v of UNSAFE) assert.equal(isSafeFileComponent(v), false, JSON.stringify(v));
});

test('fileInside and outputFileIn never leave the directory', () => {
  const dir = path.join(os.tmpdir(), 'safe-names');
  assert.equal(path.dirname(outputFileIn(dir, { group: 'G1', id: 'A001' }, '_wb.drx')), path.resolve(dir));
  assert.equal(path.basename(outputFileIn(dir, { group: 'G1', id: 'A001' }, '_wb.drx')), 'G1_A001_wb.drx');
  for (const v of UNSAFE) {
    assert.equal(fileInside(dir, v), null, JSON.stringify(v));
    assert.throws(() => outputFileIn(dir, { id: v }, '.drx'), /not a safe file name/, JSON.stringify(v));
    assert.throws(() => outputFileIn(dir, { group: v, id: 'A' }, '.drx'), /group/, JSON.stringify(v));
  }
});

async function twoTone(file, a, b, w = 32, h = 32) {
  const buf = Buffer.alloc(w * h * 3);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const c = y < h / 2 ? a : b, i = (y * w + x) * 3;
    buf[i] = c.r; buf[i + 1] = c.g; buf[i + 2] = c.b;
  }
  await sharp(buf, { raw: { width: w, height: h, channels: 3 } }).png().toFile(file);
}

test('matchers refuse a traversal clip id instead of writing outside outDir', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'safe-names-'));
  try {
    const png = path.join(dir, 't.png');
    const ref = path.join(dir, 'r.png');
    await twoTone(png, { r: 30, g: 20, b: 20 }, { r: 140, g: 130, b: 120 });
    await twoTone(ref, { r: 150, g: 110, b: 80 }, { r: 180, g: 140, b: 100 });
    const outDir = path.join(dir, 'a', 'b', 'out');
    await assert.rejects(computeBlackBalance([{ id: '../../escaped', png }], { outDir }), /not a safe file name/);
    await assert.rejects(
      computeMatchToReference([{ id: '../../escaped', png, reference: ref }], { outDir, skinGate: false }),
      /not a safe file name/,
    );
    for (const f of ['escaped_blackbal.drx', 'escaped_matchref.drx']) assert.equal(fs.existsSync(path.join(dir, 'a', f)), false, f);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

// Every template literal in the server that interpolates a value into a file
// name ending in a known extension. Each was reviewed: the value is server
// chosen, already sanitised, or the whole path is the caller's by design.
// A new one fails here until it is reviewed and listed.
const REVIEWED = new Set([
  'cdl-io.mjs: `${opts.outDir}/${id}.drx`', // id sanitised with [^\w.-] -> _
  'extract-frames.mjs: `${id}.png`', // checked by isSafeFileComponent
  'reverse-clip-db.mjs: `${String(itemId).replace(/[^A-Za-z0-9._-]/g, \'_\').slice(0, 120) || \'item\'}.txt`', // sanitised, fresh mkdtemp dir
  'qc-sampler.mjs: `ref-${n}.png`', // counter
  'qc-sampler.mjs: `conf-${n++}.png`', // counter
  'offline-ref-db.mjs: `${dbPath}.bak`', // the caller's own database path
  'offline-ref-db.mjs: `Sm2Timeline-${safeName}.sql`', // sanitised
  'db-patch.mjs: `${dbPath}.subtitle-${Date.now()}-${randomUUID()}.bak`', // the caller's own database path
  'db-patch.mjs: `${dbPath}.bak`',
  'offline-ref.mjs: `${filePath}.bak`', // the caller's own file
  'tools/drt.mjs: `${projectFolder}/SeqContainer${existingCount + injected + 1}.xml`', // zip entry, not a file
  'tools/drt.mjs: `SeqContainer/${cid}.xml`', // zip entry
  'tools/drt.mjs: `MediaPool/Master/${folder}/MpFolder.xml`', // zip entry
  "tools/color_trace.mjs: `trace-${String(i).padStart(4, '0')}.drx`", // counter
]);

function serverFiles(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) return e.name === 'node_modules' ? [] : serverFiles(p);
    return e.name.endsWith('.mjs') && e.name !== 'safe-path.mjs' ? [p] : [];
  });
}

test('every interpolated output file name in the server is reviewed', () => {
  const ext = '(drx|png|jpg|json|cube|txt|sql|wav|drp|drt|xml|csv|edl|aaf|otio|setting|comp|mov|mp4|log|jsonl|bak|db)';
  const literal = new RegExp('`[^`]*\\$\\{[^`]*\\.' + ext + '`', 'g');
  const found = [];
  for (const file of serverFiles(SERVER)) {
    const rel = path.relative(SERVER, file).split(path.sep).join('/');
    for (const m of fs.readFileSync(file, 'utf8').matchAll(literal)) found.push(`${rel}: ${m[0]}`);
  }
  const unreviewed = found.filter((f) => !REVIEWED.has(f));
  assert.deepEqual(unreviewed, [], `unreviewed interpolated file names:\n  ${unreviewed.join('\n  ')}`);
});
