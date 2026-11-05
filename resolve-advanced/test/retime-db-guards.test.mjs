/** set_speed_ramp refuses what it cannot build faithfully: a trimmed clip (source in-point != 0)
 * and a ramp that would run into the next clip on the track. Dry runs, so Resolve need not be quit. */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { loadSqlite } from '../server/db-patch.mjs';
import { retimeDbAction } from '../server/retime-db.mjs';

const require = createRequire(import.meta.url);
const { identityTimemap } = require('../vendor/drp-format/media-timemap.js');
const FPS = 30;
const segments = [{ durationFrames: 30, speed: 1 }, { durationFrames: 60, speed: 0.5 }];

function fixture(items) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'retime-guards-'));
  const file = path.join(dir, 'Project.db');
  const Database = loadSqlite();
  const db = new Database(file);
  const fps = Buffer.alloc(8); fps.writeDoubleLE(FPS, 0);
  db.exec(`CREATE TABLE Sm2TiItem (Sm2TiItem_id TEXT, Name TEXT, Start TEXT, Duration TEXT, MediaTimemapBA BLOB, "In" TEXT, Sm2TiTrack_id TEXT);
    CREATE TABLE Sm2TiTrack (Sm2TiTrack_id TEXT, Sequence TEXT, Type INTEGER);
    CREATE TABLE Sm2Sequence (Sm2Sequence_id TEXT, Sm2Timeline_id TEXT, FrameRate BLOB);
    CREATE TABLE Sm2Timeline (Sm2Timeline_id TEXT, Name TEXT);`);
  db.prepare('INSERT INTO Sm2Timeline VALUES (?,?)').run('tl', 'T');
  db.prepare('INSERT INTO Sm2Sequence VALUES (?,?,?)').run('sq', 'tl', fps);
  db.prepare('INSERT INTO Sm2TiTrack VALUES (?,?,?)').run('tr', 'sq', 0);
  const ins = db.prepare('INSERT INTO Sm2TiItem VALUES (?,?,?,?,?,?,?)');
  for (const it of items) ins.run(it.id, it.id, String(it.start), String(it.duration), identityTimemap(it.frames, FPS), it.in ?? '0', 'tr');
  db.close();
  return { file, dir };
}
const run = (file, extra = {}) => retimeDbAction('set_speed_ramp', { projectDb: file, itemId: 'a', segments, dryRun: true, ...extra }, async (p) => p.projectDb);

test('a clip with no next clip ramps and reports no overlap', async () => {
  const { file, dir } = fixture([{ id: 'a', start: 0, duration: 300, frames: 300 }]);
  try {
    const r = await run(file);
    assert.equal(r.next.overlapFrames, 0);
    assert.equal(r.wouldRefuse, undefined);
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test('a trimmed clip (non-zero source in-point) is refused', async () => {
  const { file, dir } = fixture([{ id: 'a', start: 0, duration: 300, frames: 300, in: '47|0000eaffffffef3f' }]);
  try {
    await assert.rejects(run(file), /trimmed.*source in-point 47/);
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test('an unreadable in-point is refused, not read as zero', async () => {
  const { file, dir } = fixture([{ id: 'a', start: 0, duration: 300, frames: 300, in: 'garbage' }]);
  try {
    await assert.rejects(run(file), /cannot read the clip source in-point/);
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test('a ramp that lengthens the clip into the next one is reported and refused', async () => {
  // The ramp's record segments sum to 90 frames, the clip's new Duration; the next clip starts at 80.
  const { file, dir } = fixture([{ id: 'a', start: 0, duration: 300, frames: 300 }, { id: 'b', start: 80, duration: 50, frames: 50 }]);
  try {
    const r = await run(file);
    assert.equal(r.next.start, 80);
    assert.equal(r.next.overlapFrames, 10);
    assert.ok(r.next.overlapFrames > 0, 'overlap reported in the dry-run plan');
    assert.match(r.wouldRefuse, /overlap the next clip/);
    const fit = await run(file, { segments: [{ durationFrames: 30, speed: 1 }, { durationFrames: 20, speed: 2 }] });
    assert.equal(fit.next.overlapFrames, 0);
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});
