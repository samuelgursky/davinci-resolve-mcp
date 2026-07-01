/**
 * Sequence lineage store (Phase 1) — content-hashed snapshot ingest of an XMEML:
 * oracle source frame + corrected scale per cut, per-cut + per-snapshot hashes,
 * dedup on identical content, change detection on an edited cut.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import fs from 'node:fs';

import { createRequire } from 'node:module';
import { openStore, ingestXml, ingestLiveTimeline, listSnapshots, getSnapshot, diffSnapshots, rollbackPlan } from '../server/lineage-db.mjs';

const require2 = createRequire(import.meta.url);
// A tiny SQLite "project DB" with one timeline: a forward clip + a reversed clip.
function makeProjectDb() {
  const Database = require2('better-sqlite3');
  const p = path.join(os.tmpdir(), `proj-${process.pid}-${Math.floor(performance.now())}.db`);
  const db = new Database(p);
  db.exec(`CREATE TABLE Sm2Timeline ("Sm2Timeline_id" TEXT, "Sequence" TEXT);
 CREATE TABLE Sm2TiTrack ("Sm2TiTrack_id" TEXT, "Sequence" TEXT);
 CREATE TABLE Sm2TiItem ("Sm2TiItem_id" TEXT, "In" TEXT, "Start" TEXT, "MediaTimemapBA" BLOB, "Sm2TiTrack_id" TEXT, "MediaFilePath" TEXT);`);
  db.prepare('INSERT INTO Sm2Timeline VALUES (?,?)').run('T', 'seqA');
  db.prepare('INSERT INTO Sm2TiTrack VALUES (?,?)').run('trk', 'seqA');
  db.prepare('INSERT INTO Sm2TiItem VALUES (?,?,?,?,?,?)').run('a', '100', '0', Buffer.alloc(9), 'trk', '/m/A.mov');
  db.prepare('INSERT INTO Sm2TiItem VALUES (?,?,?,?,?,?)').run('b', '12420', '48', Buffer.alloc(660), 'trk', '/m/B.mov');
  db.close();
  return p;
}

const TPF = 254016000000 / 24;
const xmeml = ({ in1 = 100, bStart = 48 } = {}) => `<?xml version="1.0" encoding="UTF-8"?>
<xmeml version="4"><sequence><name>S</name><rate><timebase>24</timebase></rate>
 <media><video>
 <format><samplecharacteristics><width>3600</width><height>2160</height><rate><timebase>24</timebase></rate></samplecharacteristics></format>
 <track>
 <clipitem id="c1"><name>A</name><start>0</start><end>48</end><in>${in1}</in><out>${in1 + 48}</out>
 <pproTicksIn>${in1 * TPF}</pproTicksIn>
 <file id="f1"><name>A.mov</name><pathurl>file://localhost/m/A.mov</pathurl>
 <media><video><samplecharacteristics><width>4096</width><height>2612</height></samplecharacteristics></video></media></file>
 <filter><effect><name>Basic Motion</name><effectid>basic</effectid>
 <parameter><parameterid>scale</parameterid><value>100</value></parameter></effect></filter></clipitem>
 <clipitem id="c2"><name>B</name><start>${bStart}</start><end>${bStart + 15}</end><in>589</in><out>604</out>
 <pproTicksIn>${589 * TPF}</pproTicksIn>
 <subclipinfo><startoffset>34727</startoffset><endoffset>11832</endoffset></subclipinfo>
 <file id="f2"><name>B.mov</name><pathurl>file://localhost/m/B.mov</pathurl>
 <media><video><samplecharacteristics><width>2048</width><height>1306</height></samplecharacteristics></video></media></file>
 <filter><effect><name>Basic Motion</name><effectid>basic</effectid>
 <parameter><parameterid>reverse</parameterid><value>TRUE</value></parameter></effect></filter></clipitem>
 </track>
 </video></media></sequence></xmeml>`;

function tmpDb() {
  return path.join(os.tmpdir(), `lineage-${process.pid}-${Math.floor(performance.now())}.db`);
}
function writeXml(s) {
  const p = path.join(os.tmpdir(), `lx-${process.pid}-${Math.floor(performance.now())}.xml`);
  fs.writeFileSync(p, s);
  return p;
}

test('ingest derives oracle frames + scale, hashes, stores cuts', () => {
  const db = tmpDb();
  const r = ingestXml(db, writeXml(xmeml()), { reel: 'R01', label: 'OG', kind: 'editorial_xml', now: '2026-01-01T00:00:00Z' });
  assert.equal(r.deduped, false);
  assert.equal(r.cutCount, 2);
  const snap = getSnapshot(db, r.snapshotId);
  assert.equal(snap.cuts.length, 2);
  // forward clip A: oracle source = in = 100; scale corrected = 100*2612/2160 (narrower-by-height)
  const a = snap.cuts[0];
  assert.equal(a.oracle_source_frame, 100);
  assert.ok(Math.abs(a.scale_corrected - (100 * 2612) / 2160) < 0.01);
  assert.equal(a.reverse, 0);
  // reverse subclip B: no mediaFrames → oracle frame null, but raw fields captured
  const b = snap.cuts[1];
  assert.equal(b.reverse, 1);
  assert.equal(b.is_subclip, 1);
  assert.equal(b.subclip_endoffset, 11832);
  assert.equal(b.oracle_source_frame, null);
  assert.ok(a.cut_hash && b.cut_hash && a.cut_hash !== b.cut_hash);
});

test('reverse oracle frame is derived when mediaFrames supplied', () => {
  const db = tmpDb();
  const r = ingestXml(db, writeXml(xmeml()), { reel: 'R01', mediaFrames: { 'B.mov': 47849 }, now: 't' });
  const b = getSnapshot(db, r.snapshotId).cuts[1];
  // (masterFrames-1-endoffset)-in = 47849-1-11832-589 = 35427
  assert.equal(b.oracle_source_frame, 35427);
});

test('identical content dedups; an edited cut produces a new snapshot', () => {
  const db = tmpDb();
  const first = ingestXml(db, writeXml(xmeml()), { reel: 'R01', label: 'v01', now: 'a' });
  const same = ingestXml(db, writeXml(xmeml()), { reel: 'R01', label: 'v02', now: 'b' });
  assert.equal(same.deduped, true);
  assert.equal(same.snapshotId, first.snapshotId);
  // change clip A's in-point → different content
  const edited = ingestXml(db, writeXml(xmeml({ in1: 200 })), { reel: 'R01', label: 'v03', now: 'c' });
  assert.equal(edited.deduped, false);
  assert.notEqual(edited.contentHash, first.contentHash);
  assert.equal(listSnapshots(db, { reel: 'R01' }).length, 2); // OG-content + edited
});

test('store survives reopen (persistent sidecar)', () => {
  const db = tmpDb();
  const r = ingestXml(db, writeXml(xmeml()), { reel: 'R02', now: 'x' });
  // reopen a fresh handle
  openStore(db).close();
  assert.equal(getSnapshot(db, r.snapshotId).cuts.length, 2);
});

test('diff: self-diff is identical, all unchanged', () => {
  const db = tmpDb();
  const r = ingestXml(db, writeXml(xmeml()), { reel: 'R01', now: 'a' });
  const d = diffSnapshots(db, r.snapshotId, r.snapshotId);
  assert.equal(d.identical, true);
  assert.deepEqual(d.summary, { unchanged: 2, changed: 0, added: 0, removed: 0, moved: 0 });
});

test('diff: an edited source frame shows as a source_frame change', () => {
  const db = tmpDb();
  const og = ingestXml(db, writeXml(xmeml({ in1: 100 })), { reel: 'R01', label: 'OG', now: 'a' });
  const ed = ingestXml(db, writeXml(xmeml({ in1: 200 })), { reel: 'R01', label: 'v2', now: 'b' });
  const d = diffSnapshots(db, og.snapshotId, ed.snapshotId);
  assert.equal(d.summary.changed, 1);
  assert.equal(d.summary.unchanged, 1);
  assert.equal(d.changed[0].record_start, 0); // clip A
  assert.ok(d.changed[0].kinds.includes('source_frame'));
  assert.deepEqual(d.changed[0].deltas.oracle_source_frame, { from: 100, to: 200 });
});

test('live ingest: reads cuts from a project DB, detects reverse, uses API readbacks', async () => {
  const lineage = tmpDb();
  const project = makeProjectDb();
  const r = await ingestLiveTimeline(lineage, {
    projectDb: project,
    timelineId: 'T',
    reel: 'R01',
    label: 'live',
    now: 'l',
    sourceFrames: { 0: 100, 48: 35427 }, // API get_source_start_frame readbacks
  });
  const snap = getSnapshot(lineage, r.snapshotId);
  assert.equal(snap.kind, 'live_timeline');
  assert.equal(snap.cuts.length, 2);
  const [a, b] = snap.cuts;
  assert.equal(a.reverse, 0); // 9-byte timemap
  assert.equal(b.reverse, 1); // 660-byte reverse timemap
  assert.equal(b.record_start, 48);
  assert.equal(b.oracle_source_frame, 35427); // from the API readback, not the mirrored stored In (12420)
});

test('cross-kind diff (XML vs live) flags a reverted reverse frame', async () => {
  const lineage = tmpDb();
  const project = makeProjectDb();
  // XML baseline: reverse clip B should display 35427 (oracle via mediaFrames)
  const xml = ingestXml(lineage, writeXml(xmeml()), { reel: 'R01', label: 'OG', kind: 'editorial_xml', mediaFrames: { 'B.mov': 47849 }, now: 'a' });
  // live snapshot WITHOUT the readback for B → oracle falls back to the mirrored stored In (12420 = wrong)
  const live = await ingestLiveTimeline(lineage, { projectDb: project, timelineId: 'T', reel: 'R01', label: 'live', sourceFrames: { 0: 100 }, now: 'b' });
  const d = diffSnapshots(lineage, xml.snapshotId, live.snapshotId);
  const bChange = d.changed.find((c) => c.record_start === 48);
  assert.ok(bChange, 'reverse clip B should be flagged');
  assert.ok(bChange.kinds.includes('source_frame'));
  assert.deepEqual(bChange.deltas.oracle_source_frame, { from: 35427, to: 12420 });
});

test('rollbackPlan: how to get a wrong live state back to the good XML target', async () => {
  const lineage = tmpDb();
  const project = makeProjectDb();
  const good = ingestXml(lineage, writeXml(xmeml()), { reel: 'R01', label: 'OG', mediaFrames: { 'B.mov': 47849 }, now: 'a' });
  // supply A's transform (API readback) so only the reverse clip B differs;
  // A's XML scale_corrected = 100*2612/2160 = 120.92593
  const wrong = await ingestLiveTimeline(lineage, {
    projectDb: project,
    timelineId: 'T',
    reel: 'R01',
    label: 'live',
    sourceFrames: { 0: 100 },
    transforms: { 0: { scale_corrected: 120.92593 } },
    now: 'b',
  });
  const plan = rollbackPlan(lineage, wrong.snapshotId, good.snapshotId);
  assert.equal(plan.changeCount, 1);
  const ch = plan.changes[0];
  assert.equal(ch.record_start, 48);
  assert.equal(ch.target.oracle_source_frame, 35427);
  const fixAction = ch.suggestedActions.find((a) => a.tool === 'conform.fix_reverse_clip');
  assert.ok(fixAction && fixAction.targetFrame === 35427 && fixAction.reverse === true);
});

test('diff: a clip that moves record position is reported as moved', () => {
  const db = tmpDb();
  const og = ingestXml(db, writeXml(xmeml({ bStart: 48 })), { reel: 'R01', label: 'OG', now: 'a' });
  const mv = ingestXml(db, writeXml(xmeml({ bStart: 60 })), { reel: 'R01', label: 'mv', now: 'b' });
  const d = diffSnapshots(db, og.snapshotId, mv.snapshotId);
  assert.equal(d.summary.moved, 1);
  assert.equal(d.summary.removed, 0);
  assert.equal(d.summary.added, 0);
  assert.equal(d.moved[0].source_basename, 'B.mov');
  assert.deepEqual([d.moved[0].from, d.moved[0].to], [48, 60]);
});
