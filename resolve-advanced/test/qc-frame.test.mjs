/**
 * Frame-level QC (Phases 6–8): classify, red/yellow/review categorization, snapshot QC
 * with an incremental cache + injected samplers, cross-version verdict propagation, and
 * the marker plan. Synthetic grayscale buffers stand in for sampled frames.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import fs from 'node:fs';

import { ingestXml } from '../server/lineage-db.mjs';
import { classifyCut, markerCategory, qcSnapshot, propagateVerdicts, markerPlan, referenceIsBlank } from '../server/qc-frame.mjs';

const W = 40,
  H = 30;
const tex = (phase = 0) => {
  const d = new Float64Array(W * H);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) d[y * W + x] = 0.5 + 0.3 * Math.sin(x * 0.4 + phase) + 0.15 * Math.cos(y * 0.3 - phase);
  return d;
};
const flat = () => new Float64Array(W * H).fill(0.5);
const black = () => new Float64Array(W * H).fill(0.0);
// genuinely uncorrelated content (different cut entirely) — no shift aligns it
const wrong = () => {
  const d = new Float64Array(W * H);
  for (let i = 0; i < d.length; i++) {
    const s = Math.sin(i * 12.9898) * 43758.5453;
    d[i] = 0.5 + 0.4 * (s - Math.floor(s) - 0.5);
  }
  return d;
};

test('classifyCut: MATCH / WRONG / UNREADABLE on synthetic frames', () => {
  const a = tex(0);
  assert.equal(classifyCut(a, a, { width: W, height: H }).verdict, 'MATCH');
  assert.equal(classifyCut(a, wrong(), { width: W, height: H }).verdict, 'WRONG');
  assert.equal(classifyCut(a, flat(), { width: W, height: H }).verdict, 'UNREADABLE');
});

test('markerCategory: red conform vs yellow turnover vs review vs ref-offline', () => {
  assert.deepEqual(markerCategory('WRONG', { sourceOnline: true, frameInRange: true, aspectOk: true }), { category: 'conform', color: 'Red' });
  assert.deepEqual(markerCategory('WRONG', { sourceOnline: false }), { category: 'turnover', color: 'Yellow' });
  assert.deepEqual(markerCategory('WRONG', { frameInRange: false }), { category: 'turnover', color: 'Yellow' });
  assert.equal(markerCategory('UNREADABLE').category, 'review');
  assert.deepEqual(markerCategory('REF_OFFLINE'), { category: 'ref_offline', color: 'Blue' });
  assert.equal(markerCategory('MATCH').category, 'ok');
});

test('referenceIsBlank: black is blank, textured/flat-gray are not, burn-in is masked off', () => {
  assert.equal(referenceIsBlank(black()), true);
  assert.equal(referenceIsBlank(tex(0)), false);
  assert.equal(referenceIsBlank(flat()), false); // featureless gray is UNREADABLE, not offline-black
  // a black frame with a bright TC slate block: blank once the burn-in pixels are masked
  const slate = black();
  const mask = new Uint8Array(W * H);
  for (let y = 2; y < 8; y++)
    for (let x = 14; x < 26; x++) {
      slate[y * W + x] = 1.0;
      mask[y * W + x] = 1;
    }
  assert.equal(referenceIsBlank(slate), false); // 72 bright px (6%) → not blank unmasked
  assert.equal(referenceIsBlank(slate, { mask }), true); // burn-in masked → blank
});

const TPF = 254016000000 / 24;
const xmeml = ({ in1 = 100 } = {}) => `<?xml version="1.0"?>
<xmeml version="4"><sequence><name>S</name><rate><timebase>24</timebase></rate><media><video>
 <format><samplecharacteristics><width>3600</width><height>2160</height></samplecharacteristics></format>
 <track>
 <clipitem id="c1"><name>A</name><start>0</start><end>48</end><in>${in1}</in><out>${in1 + 48}</out><pproTicksIn>${in1 * TPF}</pproTicksIn>
 <file id="f1"><name>A.mov</name><pathurl>file://localhost/m/A.mov</pathurl><media><video><samplecharacteristics><width>4096</width><height>2612</height></samplecharacteristics></video></media></file></clipitem>
 <clipitem id="c2"><name>B</name><start>48</start><end>96</end><in>500</in><out>548</out><pproTicksIn>${500 * TPF}</pproTicksIn>
 <file id="f2"><name>B.mov</name><pathurl>file://localhost/m/B.mov</pathurl><media><video><samplecharacteristics><width>4096</width><height>2612</height></samplecharacteristics></video></media></file></clipitem>
 </track></video></media></sequence></xmeml>`;
const tmpDb = () => path.join(os.tmpdir(), `qc-${process.pid}-${Math.floor(performance.now())}.db`);
const writeXml = (s) => {
  const p = path.join(os.tmpdir(), `qx-${process.pid}-${Math.floor(performance.now())}.xml`);
  fs.writeFileSync(p, s);
  return p;
};

// samplers: cut 0 matches the reference; cut 1 (the "bad" one) is wrong content
function samplers(badRecord = 48) {
  const refByRec = { 0: tex(0), [badRecord]: tex(0) };
  const confByRec = { 0: tex(0), [badRecord]: wrong() }; // cut 1 conform ≠ reference (wrong content)
  return {
    sampleConform: (cut) => confByRec[cut.record_start] || tex(0),
    sampleReference: (cut) => refByRec[cut.record_start] || tex(0),
  };
}

test('qcSnapshot: classifies all cuts, caches, and is incremental on re-run', async () => {
  const db = tmpDb();
  const snap = ingestXml(db, writeXml(xmeml()), { reel: 'R01', label: 'OG', now: 't' });
  const opts = {
    referenceRef: 'ref.mov',
    width: W,
    height: H,
    now: 't',
    satisfiability: () => ({ sourceOnline: true, frameInRange: true, aspectOk: true }),
    ...samplers(),
  };
  const r1 = await qcSnapshot(db, snap.snapshotId, opts);
  assert.equal(r1.scanned, 2);
  assert.equal(r1.counts.MATCH, 1);
  assert.equal(r1.counts.WRONG, 1);
  const bad = r1.results.find((v) => v.verdict === 'WRONG');
  assert.equal(bad.category, 'conform'); // satisfiable → red
  // re-run → all cached, nothing re-scanned
  const r2 = await qcSnapshot(db, snap.snapshotId, opts);
  assert.equal(r2.cached, 2);
  assert.equal(r2.scanned, 0);
});

test('qcSnapshot: a black reference → REF_OFFLINE (not a false WRONG) even when the source has picture', async () => {
  const db = tmpDb();
  const snap = ingestXml(db, writeXml(xmeml()), { reel: 'R01', label: 'OG', now: 't' });
  // cut 1 (record 48): reference is BLACK (shot offline in editorial) but the source DOES have picture
  const refByRec = { 0: tex(0), 48: black() };
  const confByRec = { 0: tex(0), 48: tex(2) };
  const opts = {
    referenceRef: 'ref.mov',
    width: W,
    height: H,
    now: 't',
    satisfiability: () => ({ sourceOnline: true, frameInRange: true, aspectOk: true }),
    sampleConform: (cut) => confByRec[cut.record_start] || tex(0),
    sampleReference: (cut) => refByRec[cut.record_start] || tex(0),
  };
  const r = await qcSnapshot(db, snap.snapshotId, opts);
  assert.equal(r.counts.MATCH, 1);
  assert.equal(r.counts.REF_OFFLINE, 1);
  assert.equal(r.counts.WRONG, undefined); // crucially NOT scored as a conform error
  const ro = r.results.find((v) => v.verdict === 'REF_OFFLINE');
  assert.equal(ro.category, 'ref_offline');
  assert.equal(ro.reference_frame, 48);
  // the marker plan surfaces it in Blue
  const plan = markerPlan(db, snap.snapshotId, 'ref.mov');
  assert.equal(plan.length, 1);
  assert.equal(plan[0].color, 'Blue');
  assert.equal(plan[0].record_start, 48);
});

test('propagateVerdicts: unchanged cuts carry over; changed cuts must re-QC', async () => {
  const db = tmpDb();
  const parent = ingestXml(db, writeXml(xmeml({ in1: 100 })), { reel: 'R01', label: 'v1', now: 'a' });
  await qcSnapshot(db, parent.snapshotId, { referenceRef: 'ref.mov', width: W, height: H, now: 'a', ...samplers() });
  // child: clip A (cut 0) changed; clip B (cut 1, rec 48) unchanged
  const child = ingestXml(db, writeXml(xmeml({ in1: 200 })), { reel: 'R01', label: 'v2', now: 'b' });
  const prop = propagateVerdicts(db, parent.snapshotId, child.snapshotId, 'ref.mov');
  assert.equal(prop.copied, 1); // only the unchanged B
  assert.deepEqual(prop.mustReQC, [0]); // record_start 0 (clip A) changed
});

test('markerPlan: emits red/yellow markers from verdicts (skips ok)', async () => {
  const db = tmpDb();
  const snap = ingestXml(db, writeXml(xmeml()), { reel: 'R01', now: 't' });
  await qcSnapshot(db, snap.snapshotId, {
    referenceRef: 'ref.mov',
    width: W,
    height: H,
    now: 't',
    satisfiability: () => ({ sourceOnline: false }),
    ...samplers(),
  });
  const plan = markerPlan(db, snap.snapshotId, 'ref.mov');
  assert.equal(plan.length, 1); // only the WRONG cut (the MATCH cut is skipped)
  assert.equal(plan[0].color, 'Yellow'); // unsatisfiable → turnover
  assert.equal(plan[0].record_start, 48);
});
