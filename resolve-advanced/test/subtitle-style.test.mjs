/**
 * subtitle-style codec + project_db.{list,set}_subtitle_style.
 *
 * Covers the caption style Resolve keeps on a subtitle track (Sm2TiTrack Type=2),
 * which the scripting API cannot read or write at all.
 *
 * Fixtures are SYNTHESISED from the documented wire structure (see
 * vendor/drp-format/subtitle-style.js) rather than copied out of a real project,
 * so the test carries no project-derived bytes. Both payload markers are
 * exercised: 0x80 raw and 0x81 zstd — Resolve 21 writes 0x81, and the encoder
 * deliberately emits 0x80 on the way back out.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';

import { projectDbTool } from '../server/tools/project_db.mjs';

const require = createRequire(import.meta.url);
const style = require('../vendor/drp-format/subtitle-style.js');
const { encodeKeyedDict } = require('../vendor/drp-format/keyed-dict.js');

// ---- fixture builders (mirror the documented protobuf shape) ---------------

function varint(v) {
  const out = [];
  let r = v;
  while (r > 0x7f) { out.push((r & 0x7f) | 0x80); r = Math.floor(r / 128); }
  out.push(r & 0x7f);
  return Buffer.from(out);
}
function lenField(field, payload) {
  return Buffer.concat([varint((field << 3) | 2), varint(payload.length), payload]);
}
function varintField(field, value) {
  return Buffer.concat([varint((field << 3) | 0), varint(value)]);
}
/** one parameter: f9 { f1 = id, f3 = { f1 = { <leaf> } } } */
function param(id, leaf) {
  return lenField(9, Buffer.concat([varintField(1, id), lenField(3, lenField(1, leaf))]));
}
function fontLeaf(descriptor) { return lenField(3, Buffer.from(descriptor, 'utf8')); }
function positionLeaf(x, y) {
  const b = Buffer.alloc(16);
  b.writeDoubleBE(x, 0);
  b.writeDoubleBE(y, 8);
  return lenField(7, b);
}
function intLeaf(v) { return varintField(1, v); }

function buildProtobuf(descriptor, x, y) {
  const effect = Buffer.concat([
    varintField(1, style.TEXT_STYLE_EFFECT),
    param(style.PARAM_FONT, fontLeaf(descriptor)),
    lenField(9, Buffer.alloc(0)), // positional placeholder — must survive round-trip
    param(19, intLeaf(96)), // opaque, unlabelled on purpose
    param(style.PARAM_POSITION, positionLeaf(x, y)),
  ]);
  return lenField(1, effect);
}

function buildFieldsBlob(descriptor, x, y, { compress = false } = {}) {
  const pb = buildProtobuf(descriptor, x, y);
  let payload;
  if (compress) {
    // Exercise the 0x81 path with a real zstd frame, as Resolve 21 writes.
    const compressed = zstdSync(pb);
    const head = Buffer.alloc(9);
    head.writeUInt32BE(2, 0);
    head.writeUInt32BE(compressed.length + 1, 4);
    head[8] = 0x81;
    payload = Buffer.concat([head, compressed]);
  } else {
    payload = style.wrapEffectFilters(pb);
  }
  return encodeKeyedDict({
    hdr: 1,
    count: 2,
    entries: [
      { key: 'NumLayers', type: 0x02, subType: 0, value: 2 },
      { key: 'EffectFiltersBA', type: 0x0c, subType: 0, value: payload.toString('hex') },
    ],
  });
}

// zstd-codec initialises asynchronously; prime it once, then compress synchronously.
let _zstdSimple = null;
function zstdSync(buf) {
  if (!_zstdSimple) throw new Error('zstd not primed — await primeZstd() first');
  return Buffer.from(_zstdSimple.compress(new Uint8Array(buf)));
}
function primeZstd() {
  const { ZstdCodec } = require('zstd-codec');
  return new Promise((resolve) => {
    ZstdCodec.run((zstd) => { _zstdSimple = new zstd.Simple(); resolve(); });
  });
}

/** An unstyled subtitle track: Resolve writes a NumLayers-only stub. */
function buildUnstyledBlob() {
  return encodeKeyedDict({ hdr: 1, count: 1, entries: [{ key: 'NumLayers', type: 0x02, subType: 0, value: 2 }] });
}

const DESCRIPTOR = 'Helvetica,13,-1,5,50,0,0,0,0,0,Regular';

// ---- codec ----------------------------------------------------------------

test('decodeSubtitleStyle: reads font descriptor and normalised position', () => {
  const blob = buildFieldsBlob(DESCRIPTOR, 0.5, 0.109);
  const dec = style.decodeSubtitleStyle(blob);
  assert.equal(dec.styled, true);
  assert.equal(dec.font.family, 'Helvetica');
  assert.equal(dec.font.pointSize, 13);
  assert.equal(dec.font.weight, 50);
  assert.equal(dec.font.italic, false);
  assert.equal(dec.font.styleName, 'Regular');
  assert.equal(dec.position.x, 0.5);
  assert.ok(Math.abs(dec.position.y - 0.109) < 1e-12);
});

test('decodeSubtitleStyle: unstyled track reports styled:false rather than throwing', () => {
  const dec = style.decodeSubtitleStyle(buildUnstyledBlob());
  assert.equal(dec.styled, false);
  assert.equal(dec.font, null);
  assert.equal(dec.position, null);
});

test('position vector is BIG-endian — little-endian misreads it as denormal garbage', () => {
  const blob = buildFieldsBlob(DESCRIPTOR, 0.5, 0.109);
  const dec = style.decodeSubtitleStyle(blob);
  // Guards the endianness split documented in the codec: reading these 8 bytes
  // as LE yields ~1e-319, which looks like a plausible float and is not.
  assert.ok(dec.position.x > 0.4 && dec.position.x < 0.6);
});

test('encodeSubtitleStyle: edits font, preserves opaque params and placeholders', () => {
  const blob = buildFieldsBlob(DESCRIPTOR, 0.5, 0.109);
  const before = style.decodeSubtitleStyle(blob);
  const out = style.encodeSubtitleStyle(blob, { family: 'Montserrat', pointSize: 48, italic: true });
  const after = style.decodeSubtitleStyle(out);
  assert.equal(after.font.family, 'Montserrat');
  assert.equal(after.font.pointSize, 48);
  assert.equal(after.font.italic, true);
  assert.equal(after.font.weight, 50, 'untouched descriptor fields survive');
  assert.deepEqual(after.opaque, before.opaque, 'unlabelled params round-trip untouched');
  assert.deepEqual(after.position, before.position, 'position untouched when not requested');
  // The positional placeholder (empty f9) must survive, or Resolve reads params off-by-one.
  assert.equal(after.effects[0].params.length, before.effects[0].params.length);
});

test('encodeSubtitleStyle: edits position without disturbing the font', () => {
  const blob = buildFieldsBlob(DESCRIPTOR, 0.5, 0.109);
  const out = style.encodeSubtitleStyle(blob, { position: { x: 0.25, y: 0.8 } });
  const after = style.decodeSubtitleStyle(out);
  assert.ok(Math.abs(after.position.x - 0.25) < 1e-12);
  assert.ok(Math.abs(after.position.y - 0.8) < 1e-12);
  assert.equal(after.font.raw, DESCRIPTOR);
});

test('encodeSubtitleStyle: identity edit is stable across repeated re-encodes', () => {
  const blob = buildFieldsBlob(DESCRIPTOR, 0.5, 0.109);
  const once = style.encodeSubtitleStyle(blob, { family: 'Helvetica' });
  const twice = style.encodeSubtitleStyle(once, { family: 'Helvetica' });
  assert.deepEqual(
    style.decodeSubtitleStyle(twice).effects,
    style.decodeSubtitleStyle(once).effects,
    're-encoding must converge, not drift',
  );
});

test('encodeSubtitleStyle: refuses an unstyled track instead of silently no-op-ing', () => {
  assert.throws(
    () => style.encodeSubtitleStyle(buildUnstyledBlob(), { family: 'Montserrat' }),
    /no EffectFiltersBA/i,
  );
});

test('zstd 0x81 payloads decode, and re-encode as uncompressed 0x80', async () => {
  await primeZstd();
  const blob = buildFieldsBlob(DESCRIPTOR, 0.5, 0.109, { compress: true });
  const dec = style.decodeSubtitleStyle(blob);
  assert.equal(dec.font.family, 'Helvetica', 'zstd payload decodes');
  const out = style.encodeSubtitleStyle(blob, { family: 'Inter' });
  assert.equal(style.decodeSubtitleStyle(out).font.family, 'Inter');
});

// ---- project_db actions ---------------------------------------------------

function makeDb(dbPath, tracks) {
  let Database;
  try { Database = require('better-sqlite3'); } catch { return null; }
  const db = new Database(dbPath);
  db.exec(`
    CREATE TABLE Sm2TiTrack (Sm2TiTrack_id TEXT PRIMARY KEY, Type INTEGER, Sequence TEXT, FieldsBlob BLOB);
    CREATE TABLE Sm2Sequence (Sm2Sequence_id TEXT PRIMARY KEY, Sm2Timeline_id TEXT);
    CREATE TABLE Sm2Timeline (Sm2Timeline_id TEXT PRIMARY KEY, Name TEXT);
    INSERT INTO Sm2Timeline VALUES ('tl-1', 'SHORTS_V01');
    INSERT INTO Sm2Sequence VALUES ('sq-1', 'tl-1');
  `);
  const ins = db.prepare('INSERT INTO Sm2TiTrack VALUES (?, ?, ?, ?)');
  tracks.forEach(([id, type, blob]) => ins.run(id, type, 'sq-1', blob));
  db.close();
  return dbPath;
}

test('project_db.list_subtitle_styles + set_subtitle_style: dry-run, gate, write, verify', async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'subtitle-style-'));
  const dbPath = makeDb(path.join(dir, 'Project.db'), [
    ['tr-styled', 2, buildFieldsBlob(DESCRIPTOR, 0.5, 0.109)],
    ['tr-unstyled', 2, buildUnstyledBlob()],
    ['tr-video', 0, buildUnstyledBlob()], // not a subtitle track — must be ignored
  ]);
  if (!dbPath) { t.skip('better-sqlite3 not installed'); return; }

  const listed = await projectDbTool.handler({ action: 'list_subtitle_styles', args: { projectDb: dbPath } });
  assert.equal(listed.tracks.length, 2, 'only Type=2 tracks are listed');
  assert.equal(listed.tracks[0].track, 1);
  assert.equal(listed.tracks[0].font.family, 'Helvetica');
  assert.equal(listed.tracks[1].styled, false);
  assert.match(listed.note, /styled:false/);

  const dry = await projectDbTool.handler({
    action: 'set_subtitle_style',
    args: { projectDb: dbPath, timeline: 'SHORTS_V01', family: 'Montserrat', pointSize: 48, dryRun: true },
  });
  assert.equal(dry.dryRun, true);
  assert.equal(dry.backup, null);
  assert.match(dry.after.font, /^Montserrat,48,/);
  assert.equal(dry.opaqueParamsPreserved, true);
  const stillOld = await projectDbTool.handler({ action: 'list_subtitle_styles', args: { projectDb: dbPath } });
  assert.equal(stillOld.tracks[0].font.family, 'Helvetica', 'dry run wrote nothing');

  // Closed-project gate is enforced on writes.
  await assert.rejects(
    () => projectDbTool.handler({
      action: 'set_subtitle_style',
      args: { projectDb: dbPath, timeline: 'SHORTS_V01', family: 'Montserrat' },
    }),
    /close the project/i,
  );

  const wet = await projectDbTool.handler({
    action: 'set_subtitle_style',
    args: {
      projectDb: dbPath, timeline: 'SHORTS_V01', family: 'Montserrat', pointSize: 48,
      positionX: 0.5, positionY: 0.85, iConfirmProjectClosed: true,
    },
  });
  assert.equal(wet.dryRun, false);
  assert.ok(wet.backup, 'a backup is taken before writing');
  assert.equal(wet.opaqueParamsPreserved, true);
  assert.match(wet.note, /QUIT Resolve/);

  const after = await projectDbTool.handler({ action: 'list_subtitle_styles', args: { projectDb: dbPath } });
  assert.equal(after.tracks[0].font.family, 'Montserrat');
  assert.equal(after.tracks[0].font.pointSize, 48);
  assert.ok(Math.abs(after.tracks[0].position.y - 0.85) < 1e-12);

  fs.rmSync(dir, { recursive: true, force: true });
});

test('project_db.set_subtitle_style: rejects unknown timeline, lone position axis, empty change', async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'subtitle-style-err-'));
  const dbPath = makeDb(path.join(dir, 'Project.db'), [['tr-styled', 2, buildFieldsBlob(DESCRIPTOR, 0.5, 0.109)]]);
  if (!dbPath) { t.skip('better-sqlite3 not installed'); return; }

  await assert.rejects(
    () => projectDbTool.handler({
      action: 'set_subtitle_style',
      args: { projectDb: dbPath, timeline: 'NOPE', family: 'X', dryRun: true },
    }),
    /no subtitle track/i,
  );
  await assert.rejects(
    () => projectDbTool.handler({
      action: 'set_subtitle_style',
      args: { projectDb: dbPath, timeline: 'SHORTS_V01', positionX: 0.5, dryRun: true },
    }),
    /must be given together/i,
  );
  await assert.rejects(
    () => projectDbTool.handler({
      action: 'set_subtitle_style',
      args: { projectDb: dbPath, timeline: 'SHORTS_V01', dryRun: true },
    }),
    /nothing to change/i,
  );

  fs.rmSync(dir, { recursive: true, force: true });
});
