/**
 * conform.fix_reverse_clip — restore a reversed timeline clip the import dropped:
 * copy a generic reverse MediaTimemapBA blob + set the mirrored "In".
 * Covered: calibration math, a REAL temp SQLite project DB (actual SQL), the
 * conform tool action (locate→fix), and the PostgreSQL branch via a stubbed client.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import fs from 'node:fs';
import { createRequire } from 'node:module';

import { locateReverseClip, writeReverseClip, calibrateK, inForTarget } from '../server/reverse-clip-db.mjs';
import { conformTool } from '../server/tools/conform.mjs';

const require = createRequire(import.meta.url);

test('calibration math: K = probeIn + displayed; In = K - target', () => {
  const K = calibrateK(12419, 35427); // 47846
  assert.equal(K, 47846);
  assert.equal(inForTarget(K, 35427), 12419);
  assert.equal(inForTarget(K, 35412), 12434);
});

// ---- real temp SQLite project DB ----
function makeSqliteDb() {
  const Database = require('better-sqlite3');
  const p = path.join(os.tmpdir(), `revclip-${process.pid}-${Math.floor(performance.now())}.db`);
  const db = new Database(p);
  db.exec(`
 CREATE TABLE Sm2Timeline ("Sm2Timeline_id" TEXT, "Name" TEXT, "Sequence" TEXT);
 CREATE TABLE Sm2TiTrack ("Sm2TiTrack_id" TEXT, "Sequence" TEXT);
 CREATE TABLE Sm2TiItem ("Sm2TiItem_id" TEXT, "In" TEXT, "Start" TEXT, "MediaTimemapBA" BLOB, "Sm2TiTrack_id" TEXT, "MediaFilePath" TEXT);
 `);
  db.prepare('INSERT INTO Sm2Timeline VALUES (?,?,?)').run('tl1', 'REEL', 'seqA');
  db.prepare('INSERT INTO Sm2TiTrack VALUES (?,?)').run('trk1', 'seqA');
  // the reverted reverse clip in this timeline: tiny 9-byte timemap, In wrong
  db.prepare('INSERT INTO Sm2TiItem VALUES (?,?,?,?,?,?)').run('item1', '35414', '89191', Buffer.alloc(9), 'trk1', '/m/A01-A03.mov');
  // a generic reverse-blob source for the SAME media (any project/track): big blob
  db.prepare('INSERT INTO Sm2TiItem VALUES (?,?,?,?,?,?)').run('item2', '35427', '0', Buffer.alloc(660, 7), 'trkX', '/m/A01-A03.mov');
  // a clip in ANOTHER timeline (must NOT be returned by the timeline-scoped locate)
  db.prepare('INSERT INTO Sm2TiTrack VALUES (?,?)').run('trk2', 'seqB');
  db.prepare('INSERT INTO Sm2TiItem VALUES (?,?,?,?,?,?)').run('itemOther', '999', '0', Buffer.alloc(9), 'trk2', '/m/A01-A03.mov');
  db.close();
  return p;
}

test('sqlite: locate scoping excludes other timelines/tracks', async () => {
  const projectDb = makeSqliteDb();
  const r = await locateReverseClip({ projectDb, timelineId: 'tl1', mediaPathContains: 'A01-A03' });
  // tl1 -> seqA -> trk1 -> item1 only (item2 trkX has no track row; itemOther is seqB)
  assert.deepEqual(
    r.candidates.map((c) => c.id),
    ['item1'],
  );
  assert.ok(r.blobSource && r.blobSource.id === 'item2' && r.blobSource.tmlen === 660);
});

test('sqlite: fix restores the reverse blob + sets In, with backup', async () => {
  const projectDb = makeSqliteDb();
  const res = await writeReverseClip({
    projectDb,
    itemId: 'item1',
    setIn: '12419',
    restoreBlobFromItemId: 'item2',
    iConfirmProjectClosed: true,
  });
  assert.equal(res.before.tmlen, 9);
  assert.equal(res.after.tmlen, 660); // reverse blob restored
  assert.equal(res.after.inv, '12419'); // mirrored In set
  // backup captured the pre-state
  const bak = fs.readFileSync(res.backup, 'utf8');
  assert.match(bak, /^35414~~/);
});

test('sqlite: write refuses without iConfirmProjectClosed', async () => {
  const projectDb = makeSqliteDb();
  await assert.rejects(() => writeReverseClip({ projectDb, itemId: 'item1', setIn: '12419' }), /close the project/i);
});

test('conform tool: locate then fix (probe → calibrate → apply) over SQLite', async () => {
  const projectDb = makeSqliteDb();
  // locate
  const loc = await conformTool.handler({ action: 'fix_reverse_clip', args: { projectDb, timelineId: 'tl1', mediaPathContains: 'A01-A03', mode: 'locate' } });
  assert.equal(loc.candidates[0].id, 'item1');
  assert.equal(loc.blobSource.id, 'item2');
  // probe (no K): restores blob + sets In = targetFrame, asks for calibration
  const probe = await conformTool.handler({
    action: 'fix_reverse_clip',
    args: {
      projectDb,
      timelineId: 'tl1',
      mediaPathContains: 'A01-A03',
      mode: 'fix',
      itemId: 'item1',
      targetFrame: 35427,
      iConfirmProjectClosed: true,
    },
  });
  assert.equal(probe.calibration.needsCalibration, true);
  assert.equal(probe.after.inv, '35427'); // probe In
  assert.equal(probe.after.tmlen, 660); // reverse restored during probe
  // (agent reopens, reads get_source_start = e.g. 12419) → apply final
  const apply = await conformTool.handler({
    action: 'fix_reverse_clip',
    args: {
      projectDb,
      timelineId: 'tl1',
      mediaPathContains: 'A01-A03',
      mode: 'fix',
      itemId: 'item1',
      targetFrame: 35427,
      probeIn: 35427,
      displayedAtProbe: 12419,
      iConfirmProjectClosed: true,
    },
  });
  assert.equal(apply.K, 47846); // 35427 + 12419
  assert.equal(apply.setIn, 12419); // K - target
  assert.equal(apply.after.inv, '12419');
});

// ---- PostgreSQL branch via stubbed client ----
function fakePg({ candidates, blobSource }) {
  const state = { inv: '35414', tmlen: 9, queries: [] };
  return {
    state,
    async query(sql, params = []) {
      state.queries.push(sql.replace(/\s+/g, ' ').trim());
      if (sql.includes('information_schema')) return { rows: ['In', 'MediaTimemapBA', 'Sm2TiTrack_id', 'MediaFilePath'].map((c) => ({ column_name: c })) };
      if (sql.includes('JOIN "Sm2TiTrack"')) return { rows: candidates };
      if (sql.includes('ORDER BY tmlen DESC')) return { rows: blobSource ? [blobSource] : [] };
      if (sql.includes('encode(')) return { rows: [{ inv: state.inv, hex: 'deadbeef' }] };
      if (sql.startsWith('UPDATE "Sm2TiItem" t SET "MediaTimemapBA"')) {
        state.tmlen = blobSource.tmlen;
        return { rows: [] };
      }
      if (sql.startsWith('UPDATE "Sm2TiItem" SET "In"')) {
        state.inv = String(params[0]);
        return { rows: [] };
      }
      if (sql.includes('SELECT "In" AS inv, LENGTH')) return { rows: [{ inv: state.inv, tmlen: state.tmlen }] };
      return { rows: [] };
    },
    async end() {},
  };
}

test('postgres: locate + fix via stubbed client', async () => {
  const postgres = {
    host: 'h',
    database: 'd',
    __client: fakePg({ candidates: [{ id: 'i1', inv: '35414', start: '89191', tmlen: 9, path: '/m/A01-A03.mov' }], blobSource: { id: 'i2', tmlen: 660 } }),
  };
  const loc = await locateReverseClip({ postgres, timelineId: 'tl1', mediaPathContains: 'A01-A03' });
  assert.equal(loc.backend, 'postgres');
  assert.equal(loc.candidates[0].id, 'i1');
  assert.equal(loc.blobSource.id, 'i2');

  const res = await writeReverseClip({ postgres, itemId: 'i1', setIn: '12419', restoreBlobFromItemId: 'i2', iConfirmProjectClosed: true });
  assert.equal(res.before.tmlen, 9);
  assert.equal(res.after.tmlen, 660);
  assert.equal(res.after.inv, '12419');
});
