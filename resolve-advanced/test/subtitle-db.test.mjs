import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';
import childProcess from 'node:child_process';
import { createRequire } from 'node:module';
import { BuiltinSqlite, loadSqlite, requireResolveQuit, snapshotBackup } from '../server/db-patch.mjs';
import { projectDbTool } from '../server/tools/project_db.mjs';
const require = createRequire(import.meta.url);
const { field, decodeCaption, encodeCaption, checkCaptions } = require('../vendor/drp-format/subtitle-captions.js');
const { wrapEffectFilters, unwrapEffectFilters } = require('../vendor/drp-format/subtitle-style.js');
const { decodePreset, setPresetInputs, TEMPLATE } = require('../vendor/drp-format/subtitle-preset.js');
const { encodeKeyedDict } = require('../vendor/drp-format/keyed-dict.js');

function compBlob({ trailingSeparator = true } = {}) {
  const inner = Buffer.from('{ Template = TextPlus { Inputs = { Font = Input { Value = "Inter", }, Center = Input { Value = { 0.5, 0.4 }, }, HOutlineThickness = Input { Value = 0.02, }, StyledText = Input { SourceOp = "Animation", Source = "Value", }' + (trailingSeparator ? ',' : '') + ' }, UserControls = { Font = { LINKS_Name = "Font", }, }, }, Other = TextPlus { Inputs = { Font = Input { Value = "Keep me", }, }, }, }\0');
  const innerLen = Buffer.alloc(4); innerLen.writeUInt32LE(inner.length);
  const data = Buffer.concat([Buffer.from(`Composition { CustomData = { TEMPLATE_ID = "${TEMPLATE}" }, Compressed = true, }\0`), innerLen, zlib.deflateSync(inner)]);
  const outer = encodeKeyedDict({ entries: [{ key: '0_data', type: 12, value: data.toString('hex') }] });
  const len = Buffer.alloc(4); len.writeUInt32BE(outer.length);
  return Buffer.concat([len, zlib.deflateSync(outer)]);
}
function captionBlob({ original = false } = {}) {
  const inner = [field(13, 0), field(14, Buffer.from(' Old')), field(15, 200), field(16, 220), field(21, 100),
    field(50, Buffer.from('opaque'))];
  if (original) inner.push(field(18, Buffer.from(' AI')), field(19, 200), field(20, 220));
  return wrapEffectFilters(Buffer.concat([field(1, Buffer.concat(inner)), field(2, Buffer.from('opaque outer'))]));
}
const cue = (text, start, end) => ({ text, start, end, words: [{ text, start, end }] });
function fixture(t, { preset = false, fps = 30 } = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'subtitle-db-test-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const filename = path.join(dir, 'Project.db'), Database = loadSqlite();
  const db = new Database(filename);
  db.exec(`CREATE TABLE Sm2Timeline (Sm2Timeline_id TEXT PRIMARY KEY,Name TEXT);
    CREATE TABLE Sm2Sequence (Sm2Sequence_id TEXT PRIMARY KEY,Sm2Timeline_id TEXT,FrameRate BLOB);
    CREATE TABLE Sm2TiTrack (Sm2TiTrack_id TEXT PRIMARY KEY,Sequence TEXT,Type INTEGER);
    CREATE TABLE Sm2SequenceContainer_Sm2TiTrack (DbOwner TEXT,DbAssociate TEXT,DbPropertyName TEXT,DbIndex INTEGER);
    CREATE TABLE Sm2TiItem (Sm2TiItem_id TEXT PRIMARY KEY,DbType TEXT,Name TEXT,Start TEXT,Duration TEXT,
      FieldsBlob BLOB,Sm2TiTrack_id TEXT,CompositionTable TEXT,PrettyType TEXT,MarkersBA BLOB);
    CREATE TABLE Sm2TiItem_Sm2TiTrack (DbOwner TEXT NOT NULL,DbAssociate TEXT,DbPropertyName TEXT NOT NULL,
      DbIndex INTEGER NOT NULL CHECK(DbIndex>=0), PRIMARY KEY(DbOwner,DbPropertyName,DbIndex) ON CONFLICT REPLACE);
    CREATE TABLE Sm2TiCompositionTable (Sm2TiCompositionTable_id TEXT PRIMARY KEY,Sm2TiItem_id TEXT,CompositionBA BLOB);
    INSERT INTO Sm2Timeline VALUES ('tl','Reel');
    INSERT INTO Sm2TiTrack VALUES ('track2','sq',2),('track1','sq',2);
    INSERT INTO Sm2SequenceContainer_Sm2TiTrack VALUES ('container','track1','SubtitleTrackVec',0),('container','track2','SubtitleTrackVec',1);`);
  const fpsBlob = Buffer.alloc(16); fpsBlob.writeDoubleLE(fps);
  db.prepare('INSERT INTO Sm2Sequence VALUES (?,?,?)').run('sq', 'tl', fpsBlob);
  for (const [id, start, track] of [['a', 100, 'track1'], ['b', 120, 'track1'], ['foreign', 100, 'track2']]) {
    const blob = encodeCaption(captionBlob({ original: true }), cue('Old', start, start + 10), fps);
    db.prepare('INSERT INTO Sm2TiItem VALUES (?,?,?,?,?,?,?,?,?,?)').run(id, 'Sm2TiGenerator', ' stale name',
      String(start), '10', blob, track, null, 'Subtitle', Buffer.from('marker'));
    db.prepare('INSERT INTO Sm2TiItem_Sm2TiTrack VALUES (?,?,?,?)').run(track, id, 'Items', id === 'b' ? 1 : 0);
  }
  if (preset) {
    db.prepare('INSERT INTO Sm2TiItem VALUES (?,?,?,?,?,?,?,?,?,?)').run('holder', 'Sm2TiVideoClip', 'Fusion Title', '0', '150',
      Buffer.from('opaque preset fields'), 'track1', 'comp', 'Fusion Title', null);
    db.prepare('INSERT INTO Sm2TiCompositionTable VALUES (?,?,?)').run('comp', 'holder', compBlob());
    db.prepare('INSERT INTO Sm2TiItem_Sm2TiTrack VALUES (?,?,?,?)').run('track1', 'holder', 'FusionCompHolderItems', 0);
  }
  db.close();
  return filename;
}
const call = (projectDb, action, args = {}) => projectDbTool.handler({ action, args: { projectDb, timeline: 'Reel', ...args } });
function quit(t) { t.mock.method(childProcess, 'spawnSync', () => ({ status: 0, stdout: '' })); }

test('caption codec preserves opaque fields and historical AI words, rebases moved captions', () => {
  const b = captionBlob({ original: true });
  const read = decodeCaption(b, { name: 'stale', start: 200, end: 210, fps: 30 });
  assert.equal(read.text, 'Old'); assert.equal(read.words[0].start, 200);
  assert.equal(read.originalWords[0].text, 'AI');
  const out = encodeCaption(b, cue('Hello', 400, 412), 30);
  const after = decodeCaption(out, { name: 'stale', start: 400, end: 412, fps: 30 });
  assert.equal(after.text, 'Hello'); assert.equal(after.words[0].start, 400); assert.equal(after.anchor, 400);
  assert.ok(unwrapEffectFilters(out).protobuf.includes(Buffer.from('opaque outer')));
  assert.ok(unwrapEffectFilters(out).protobuf.includes(Buffer.from('opaque')));
  assert.equal(after.originalWords[0].text, 'AI');
  assert.equal(decodeCaption(encodeCaption(b, cue('New', 100, 110), 30, { fresh: true }), { start: 100, end: 110, fps: 30 }).originalWords.length, 0);
});
test('caption codec handles zstd and rejects truncated/unknown envelopes', async () => {
  const protobuf = unwrapEffectFilters(captionBlob()).protobuf;
  const payload = zlib.zstdCompressSync ? zlib.zstdCompressSync(protobuf) : await new Promise((resolve) => {
    require('zstd-codec').ZstdCodec.run((zstd) => resolve(Buffer.from(new zstd.Simple().compress(protobuf))));
  });
  const head = Buffer.alloc(9); head.writeUInt32BE(2); head.writeUInt32BE(payload.length + 1, 4); head[8] = 0x81;
  assert.equal(decodeCaption(Buffer.concat([head, payload]), { start: 100, end: 110, fps: 30 }).text, 'Old');
  assert.throws(() => decodeCaption(wrapEffectFilters(Buffer.from([10, 99, 1])), { start: 0, end: 1, fps: 30 }), /truncated/);
});
test('QC flags gaps, invalid words, overlap and length without claiming pixel verification', () => {
  const qc = checkCaptions([{ id: 'x', text: 'A very long caption that overflows', start: 100, end: 120,
    words: [{ text: 'A', start: 100, end: 100 }, { text: 'B', start: 105, end: 118 }] }]);
  for (const code of ['overflow_length', 'word_gap', 'zero_or_negative_word_duration']) assert.ok(qc.issues.some((r) => r.code === code));
  assert.match(qc.note, /heuristic/);
});
test('preset codec updates scoped controls, preserves other tools and all framing', () => {
  const blob = compBlob();
  const inputs = { font: 'Test "Font"', position: [0.5, 0.8], highlightRed: 0.2, thickness: 0.08, textAlpha: 1 };
  const out = setPresetInputs(blob, inputs), read = decodePreset(out);
  for (const [k, v] of Object.entries(inputs)) assert.deepEqual(read.inputs[k], v);
  assert.equal(read.templateId, TEMPLATE);
  assert.deepEqual(setPresetInputs(out, inputs), out, 'identity re-encode converges');
  assert.throws(() => setPresetInputs(blob, { madeUp: 1 }), /unknown/);
});

test('adding absent colour controls preserves Lua separators when the last input has no comma', () => {
  const out = setPresetInputs(compBlob({ trailingSeparator: false }), { textRed: 1, highlightBlue: 0 });
  const outer = zlib.inflateSync(out.subarray(4));
  const lengthOffset = outer.indexOf(0, outer.indexOf('Compressed = true, }')) + 1;
  const graph = zlib.inflateSync(outer.subarray(lengthOffset + 4)).toString();
  assert.doesNotMatch(graph, /}\s+[A-Za-z_]\w*\s*=/, 'table fields must be separated');
  assert.match(graph, /StyledText = Input \{ SourceOp = "Animation", Source = "Value", }\s*}/);
  assert.equal(decodePreset(out).inputs.textRed, 1);
  assert.equal(decodePreset(out).inputs.highlightBlue, 0);
});
test('caption actions: vector order, text over stale Name, dry-run, add/replace/delete, backup and readback', async (t) => {
  quit(t);
  const db = fixture(t, { preset: true });
  const before = fs.readFileSync(db), list = await call(db, 'list_captions');
  assert.equal(list.captions[0].text, 'Old'); assert.equal(list.captions[0].id, 'a');
  const args = { replace: [{ id: 'a', ...cue('Edited', 100, 112) }], delete: ['b'], add: [cue('Added', 140, 150)] };
  const dry = await call(db, 'write_captions', { ...args, dryRun: true });
  assert.equal(dry.backup, null); assert.deepEqual(fs.readFileSync(db), before);
  await assert.rejects(() => call(db, 'write_captions', args), /close the project/i);
  const result = await call(db, 'write_captions', { ...args, iConfirmProjectClosed: true });
  assert.equal(result.verified, true); assert.ok(fs.existsSync(result.backup));
  assert.equal((await call(result.backup, 'list_captions')).captions[0].text, 'Old');
  assert.deepEqual(result.captions.map((c) => c.text), ['Edited', 'Added']);
  assert.equal((await call(db, 'list_captions', { track: 2 })).captions[0].id, 'foreign');
  assert.equal((await call(db, 'list_subtitle_presets')).presets[0].preset.id, 'holder');
});
test('caption edits refuse wrong track IDs, conflict, gaps and quantised zero-length words without changing db', async (t) => {
  quit(t); const db = fixture(t), bytes = fs.readFileSync(db);
  for (const args of [
    { delete: ['foreign'] }, { delete: ['a'], replace: [{ id: 'a', ...cue('X', 100, 110) }] },
    { replace: [{ id: 'a', ...cue('X', 100, 110), words: [{ text: 'X', start: 101, end: 110 }] }] },
    { replace: [{ id: 'a', ...cue('X', 100, 110), words: [{ text: 'X', start: 100, end: 100.1 }] }] },
    { add: [cue('Overlap', 100, 115)] },
  ]) await assert.rejects(() => call(db, 'write_captions', { ...args, iConfirmProjectClosed: true }));
  assert.deepEqual(fs.readFileSync(db), bytes);
});
test('non-30fps timing converts through 60Hz ticks without introducing gaps', async (t) => {
  quit(t);
  for (const fps of [24, 25, 30000 / 1001]) {
    const db = fixture(t, { fps });
    const c = { text: 'One two', start: 101, end: 115, words: [{ text: 'One', start: 101, end: 108 }, { text: 'two', start: 108, end: 115 }] };
    const r = await call(db, 'write_captions', { replace: [{ id: 'a', ...c }], iConfirmProjectClosed: true });
    assert.equal(r.verified, true); assert.equal(r.captions[0].words[0].end, r.captions[0].words[1].start);
  }
});
test('reordering captions cannot lose neighbours to Resolve association ON CONFLICT REPLACE', async (t) => {
  quit(t); const db = fixture(t, { preset: true });
  const result = await call(db, 'write_captions', { replace: [
    { id: 'a', ...cue('Later', 120, 130) }, { id: 'b', ...cue('Earlier', 100, 110) },
  ], iConfirmProjectClosed: true });
  assert.deepEqual(result.captions.map((c) => c.id), ['b', 'a']);
  assert.equal((await call(db, 'list_subtitle_presets')).presets[0].preset.id, 'holder');
});
test('late SQL failure rolls back every caption mutation', async (t) => {
  quit(t); const filename = fixture(t), db = new (loadSqlite())(filename);
  db.exec("CREATE TRIGGER fail_insert BEFORE INSERT ON Sm2TiItem BEGIN SELECT RAISE(ABORT,'test rollback'); END;"); db.close();
  await assert.rejects(() => call(filename, 'write_captions', { delete: ['b'], replace: [{ id: 'a', ...cue('Changed', 100, 110) }],
    add: [cue('New', 160, 170)], iConfirmProjectClosed: true }), /test rollback/);
  const after = await call(filename, 'list_captions');
  assert.deepEqual(after.captions.map((c) => c.id), ['a', 'b']); assert.equal(after.captions[0].text, 'Old');
});
test('copy preset clones three rows with new identities, protects occupied targets and patches inputs', async (t) => {
  quit(t); const source = fixture(t, { preset: true }), target = fixture(t), sourceBefore = fs.readFileSync(source);
  const args = { sourceProjectDb: source, sourceTimeline: 'Reel', iConfirmProjectClosed: true };
  const copied = await call(target, 'copy_subtitle_preset', args);
  assert.equal(copied.verified, true); assert.equal(copied.holderDuration, 150);
  const listed = await call(target, 'list_subtitle_presets'); assert.notEqual(listed.presets[0].preset.id, 'holder');
  assert.deepEqual(fs.readFileSync(source), sourceBefore);
  await assert.rejects(() => call(target, 'copy_subtitle_preset', args), /already has a preset/);
  const changed = await call(target, 'set_subtitle_preset', { inputs: { font: 'New Font', textRed: 0.6 }, iConfirmProjectClosed: true });
  assert.equal(changed.after.inputs.font, 'New Font');
  assert.notEqual(changed.backup, copied.backup);
  await call(target, 'copy_subtitle_preset', { ...args, replace: true });
  const db = new (loadSqlite())(target);
  assert.equal(db.prepare('SELECT count(*) n FROM Sm2TiCompositionTable').get().n, 1); db.close();
});
test('running Resolve and unavailable process inspection both refuse before backup/write', async (t) => {
  const filename = fixture(t), bytes = fs.readFileSync(filename);
  t.mock.method(childProcess, 'spawnSync', () => ({ status: 0, stdout: process.platform === 'win32' ? '"Resolve.exe","123"\n' : '/opt/resolve/bin/resolve\n' }));
  await assert.rejects(() => call(filename, 'write_captions', { delete: ['a'], iConfirmProjectClosed: true }), /QUIT Resolve/);
  assert.deepEqual(fs.readFileSync(filename), bytes);
  assert.deepEqual(fs.readdirSync(path.dirname(filename)), ['Project.db']);
  childProcess.spawnSync.mock.mockImplementation(() => ({ status: 1, stdout: '' }));
  assert.throws(() => requireResolveQuit({ iConfirmProjectClosed: true }), /Cannot verify/);
});
test('built-in sqlite backend has readonly blobs and transaction rollback; snapshots include WAL', async (t) => {
  let builtin; try { builtin = require('node:sqlite'); } catch { builtin = null; }
  if (typeof builtin?.backup !== 'function') { t.skip('node:sqlite with backup() needs Node 22.16+ / 23.8+; native backend tested above'); return; }
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'sqlite-fallback-test-')); t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const filename = path.join(dir, 'Project.db'), db = new BuiltinSqlite(filename);
  db.exec('PRAGMA journal_mode=WAL; CREATE TABLE x (b BLOB)'); db.prepare('INSERT INTO x VALUES (?)').run(Buffer.from('one'));
  assert.throws(() => db.transaction(() => { db.exec('DELETE FROM x'); throw new Error('rollback'); })(), /rollback/);
  const backup = await snapshotBackup(filename), read = new BuiltinSqlite(backup, { readonly: true });
  assert.ok(Buffer.isBuffer(read.prepare('SELECT b FROM x').get().b));
  assert.equal(read.prepare('SELECT b FROM x').get().b.toString(), 'one');
  assert.throws(() => read.exec('DELETE FROM x'), /readonly|read-only/i);
  read.close(); db.close();
});
test('a running Resolve refuses the write even when another project is loaded', async (t) => {
  // Measured on Studio 19.1.3.7: a project loaded earlier in the session is
  // served from memory when reloaded, so a disk write to it is not seen and a
  // later save of the edited rows overwrites it. Only a full quit is safe.
  const filename = fixture(t), bytes = fs.readFileSync(filename);
  const running = process.platform === 'win32' ? '"Resolve.exe","123"\n' : '/opt/resolve/bin/resolve\n';
  t.mock.method(childProcess, 'spawnSync', () => ({ status: 0, stdout: running }));
  await assert.rejects(() => call(filename, 'write_captions',
    { delete: ['a'], iConfirmProjectClosed: true, allowWhileRunningIfNotLoaded: true }), /unrecognized_keys[^]*allowWhileRunningIfNotLoaded/);
  await assert.rejects(() => call(filename, 'write_captions', { delete: ['a'], iConfirmProjectClosed: true }), /QUIT Resolve/);
  assert.deepEqual(fs.readFileSync(filename), bytes);
  assert.deepEqual(fs.readdirSync(path.dirname(filename)), ['Project.db']);
});
