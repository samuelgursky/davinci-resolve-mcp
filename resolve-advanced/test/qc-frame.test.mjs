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

// ── E107: sample clear of transition windows ───────────────────────────
// Inside a transition window the reference is a blend — or black, for a
// fade-in — so the cut's first record frame proves nothing: a fade-in read
// REF_OFFLINE ("offline upstream") and a dissolve read WRONG, both false.
import { pickQcFrame } from '../server/qc-frame.mjs';

test('pickQcFrame steps past the incoming window and advances the source frame at speed (E107)', () => {
  const fadeIn = { record_start: 0, record_end: 96, oracle_source_frame: 24, speed: 100, reverse: 0, xml_in: 24, xml_out: 120,
    transition: JSON.stringify({ in: { start: 0, end: 24, junction: 0 }, out: { start: 84, end: 108, junction: 96 } }) };
  assert.deepEqual(pickQcFrame(fadeIn), { recordFrame: 24, sourceFrame: 48, offset: 24, note: 'sampled at 24, clear of the transition window (cut starts 0)' });
  // A reversed clip walks backward through the source; a 50% clip advances half as far.
  assert.equal(pickQcFrame({ ...fadeIn, reverse: 1, oracle_source_frame: 100 }).sourceFrame, 76);
  assert.equal(pickQcFrame({ ...fadeIn, speed: 50 }).sourceFrame, 36);
  // Premiere-style XML: no speed param, but source span ≠ record span → derived ratio.
  assert.equal(pickQcFrame({ ...fadeIn, speed: null, xml_in: 24, xml_out: 216 }).sourceFrame, 72);
  // Null controls: no window → the record start, untouched; no transition column at all → same.
  assert.deepEqual(pickQcFrame({ record_start: 10, record_end: 50, oracle_source_frame: 5, transition: null }), { recordFrame: 10, sourceFrame: 5, offset: 0, note: null });
  assert.equal(pickQcFrame({ record_start: 10, record_end: 50, oracle_source_frame: 5 }).offset, 0);
  // A cut swallowed whole by its windows samples the midpoint and SAYS so.
  const tiny = { record_start: 90, record_end: 100, oracle_source_frame: 0, transition: JSON.stringify({ in: { start: 84, end: 108, junction: 96 }, out: null }) };
  const p = pickQcFrame(tiny);
  assert.equal(p.recordFrame, 95);
  assert.match(p.note, /entirely inside/);
});

test('qcSnapshot: a fade-in cut is judged clear of its window — MATCH, not REF_OFFLINE (E107)', async () => {
  const db = tmpDb();
  const xml = `<?xml version="1.0"?><xmeml version="5"><sequence><name>F</name><rate><timebase>24</timebase></rate>
<media><video><format><samplecharacteristics><width>640</width><height>360</height><rate><timebase>24</timebase></rate></samplecharacteristics></format>
<track>
<transitionitem><start>0</start><end>24</end><alignment>start-black</alignment><effect><effectid>Cross Dissolve</effectid></effect></transitionitem>
<clipitem id="c1"><name>A</name><start>-1</start><end>-1</end><in>24</in><out>120</out><pproTicksIn>${24 * TPF}</pproTicksIn>
<file id="f1"><name>A.mov</name><pathurl>file:///m/A.mov</pathurl><media><video><samplecharacteristics><width>640</width><height>360</height></samplecharacteristics></video></media></file></clipitem>
<transitionitem><start>84</start><end>108</end><alignment>center</alignment><effect><effectid>Cross Dissolve</effectid></effect></transitionitem>
<clipitem id="c2"><name>B</name><start>-1</start><end>192</end><in>0</in><out>96</out><pproTicksIn>0</pproTicksIn>
<file id="f2"><name>B.mov</name><pathurl>file:///m/B.mov</pathurl><media><video><samplecharacteristics><width>640</width><height>360</height></samplecharacteristics></video></media></file></clipitem>
</track></video></media></sequence></xmeml>`;
  const snap = ingestXml(db, writeXml(xml), { reel: 'R01', label: 'fade', now: 't' });
  // The reference render: black through the fade-in (frames 0-23), a 50/50 blend at the
  // dissolve junction (96), clean picture elsewhere. The sources are clean everywhere.
  const blend = () => { const a = tex(0), b = tex(2), d = new Float64Array(W * H); for (let i = 0; i < d.length; i++) d[i] = 0.5 * a[i] + 0.5 * b[i]; return d; };
  const refAt = (f) => (f < 24 ? black() : f >= 84 && f < 108 ? blend() : f < 96 ? tex(0) : tex(2));
  const sampled = [];
  const opts = {
    referenceRef: 'ref.mov', width: W, height: H, now: 't',
    satisfiability: () => ({ sourceOnline: true, frameInRange: true, aspectOk: true }),
    sampleReference: (cut) => { sampled.push(cut.qc_record_frame); return refAt(cut.qc_record_frame); },
    sampleConform: (cut) => (cut.source_basename === 'A.mov' ? tex(0) : tex(2)),
  };
  const r = await qcSnapshot(db, snap.snapshotId, opts);
  assert.deepEqual(sampled, [24, 108], 'both cuts sampled at the first frame clear of their incoming window');
  assert.equal(r.counts.MATCH, 2, JSON.stringify(r.results));
  assert.equal(r.counts.REF_OFFLINE, undefined);
  assert.equal(r.counts.WRONG, undefined);
  assert.equal(r.results[0].reference_frame, 24);
  assert.match(r.results[0].sample_note, /clear of the transition window/);
  // Counter-proof: the SAME reference judged at the record starts (the pre-E107 frames)
  // reads black for the fade-in and a blend for the dissolve — the false verdicts this closes.
  assert.equal(referenceIsBlank(refAt(0)), true);
  assert.equal(classifyCut(tex(2), refAt(96), { width: W, height: H }).verdict !== 'MATCH', true);
});


test('qcSnapshot: a flattened compound cut is review with a reason, never a false WRONG (E122)', async () => {
  const db = tmpDb();
  const snap = ingestXml(db, new URL('./fixtures/E120_resolve_nested_export.xml', import.meta.url).pathname, { reel: 'E122', now: 't', mediaFrames: { 'cut_src.mp4': 192 } });
  let sampled = 0;
  const r = await qcSnapshot(db, snap.snapshotId, {
    referenceRef: 'ref.mov', width: W, height: H, now: 't',
    satisfiability: () => ({ sourceOnline: true, frameInRange: true, aspectOk: true }),
    sampleConform: () => { sampled += 1; return tex(0); },
    sampleReference: () => tex(0),
  });
  assert.equal(sampled, 1, 'the compound cut is never sampled');
  assert.equal(r.results[0].verdict, 'MATCH');
  assert.equal(r.results[1].verdict, 'UNREADABLE');
  assert.equal(r.results[1].category, 'review');
  assert.match(r.results[1].sample_note, /compound clip "E57_OUT"/);
});
