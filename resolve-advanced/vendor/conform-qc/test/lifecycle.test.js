'use strict';

/** P4.5 lifecycle: patch diff/ripple + element inserts (slot-match, alignment, topaz). */

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { diffTimelines, reverifyChanged, rippleUpdate } = require('../ops/patch');
const I = require('../ops/insert');
const compare = require('../compare');

const SF = (n) => path.join(__dirname, '..', '__fixtures__', 'synthetic', 'frames', n);

const CURRENT = [
  { seqstart: 0, seqend: 48, source_basename: 'A.mov', sourceFrame: 100 },
  { seqstart: 48, seqend: 96, source_basename: 'B.mov', sourceFrame: 200 },
  { seqstart: 96, seqend: 144, source_basename: 'C.mov', sourceFrame: 300 },
];

test('patch: diff identifies changed / added / removed / unchanged', () => {
  const revised = [
    { seqstart: 0, seqend: 48, source_basename: 'A.mov', sourceFrame: 100 }, // unchanged
    { seqstart: 48, seqend: 96, source_basename: 'B2.mov', sourceFrame: 250 }, // changed (source)
    { seqstart: 144, seqend: 192, source_basename: 'D.mov', sourceFrame: 400 }, // added
    // C.mov (96) removed
  ];
  const d = diffTimelines(CURRENT, revised);
  assert.equal(d.unchanged.length, 1);
  assert.equal(d.changed.length, 1);
  assert.equal(d.changed[0].seqstart, 48);
  assert.equal(d.added.length, 1);
  assert.equal(d.removed.length, 1);
  assert.equal(d.removed[0].seqstart, 96);
});

test('patch: re-verify touches ONLY changed + added cuts', async () => {
  const revised = [
    { seqstart: 0, seqend: 48, source_basename: 'A.mov', sourceFrame: 100 },
    { seqstart: 48, seqend: 96, source_basename: 'B2.mov', sourceFrame: 250 },
    { seqstart: 144, seqend: 192, source_basename: 'D.mov', sourceFrame: 400 },
  ];
  const d = diffTimelines(CURRENT, revised);
  const seen = [];
  const out = await reverifyChanged(d, async (cut) => { seen.push(cut.seqstart); return 'MATCH'; });
  assert.deepEqual(seen.sort((a, b) => a - b), [48, 144]); // only changed + added
  assert.equal(out.skipped, 1); // the 1 unchanged
});

test('patch: ripple shifts downstream cuts + marks touched + neighbours', () => {
  // Cut @48 grows from 48 frames to 60 (delta +12); @96 must ripple downstream.
  const revised = [{ seqstart: 48, seqend: 108, source_basename: 'B.mov', sourceFrame: 200 }];
  const d = diffTimelines(CURRENT, revised);
  const { rippled, touched, totalShift } = rippleUpdate(CURRENT, d);
  assert.equal(totalShift, 12);
  const c3 = rippled.find((c) => c.source_basename === 'C.mov');
  assert.equal(c3.seqstart, 108); // 96 + 12 shift
  assert.ok(touched.includes(48) && touched.includes(96));
});

test('insert: slot-match ladder (shot-id -> plate-tc -> edge-frame) + version resolve', () => {
  const timeline = [
    { cutId: 'c1', shotId: 'SH010', sourceTc: '01:00:00:00', edgeFrameKey: 'e1' },
    { cutId: 'c2', shotId: 'SH020', sourceTc: '01:00:10:00', edgeFrameKey: 'e2' },
  ];
  assert.equal(I.matchElementToSlot({ name: 'v', shotId: 'SH020' }, timeline).method, 'shot-id');
  assert.equal(I.matchElementToSlot({ name: 'v', plateSourceTc: '01:00:00:00' }, timeline).slot.cutId, 'c1');
  assert.equal(I.matchElementToSlot({ name: 'v', edgeFrameKey: 'e2' }, timeline).method, 'edge-frame');
  assert.equal(I.matchElementToSlot({ name: 'v', shotId: 'NOPE' }, timeline), null);
  // Version resolution: latest APPROVED.
  const latest = I.resolveLatestVersion([{ version: 1, approved: true }, { version: 3, approved: false }, { version: 2, approved: true }]);
  assert.equal(latest.version, 2); // v3 unapproved => latest approved is v2
});

test('insert: ALIGNMENT mode verifies range+handles+sizing (not pixels)', () => {
  const plate = { usedIn: 100, usedOut: 200, requiredHandles: 8, dims: { w: 3600, h: 2160 } };
  // A correctly-aligned VFX element: covers used range + 8-frame handles, right size.
  const ok = I.alignmentVerify({ sourceIn: 90, sourceOut: 210, dims: { w: 3600, h: 2160 } }, plate);
  assert.equal(ok.aligned, true);
  // A misaligned one: short handles.
  const bad = I.alignmentVerify({ sourceIn: 99, sourceOut: 201, dims: { w: 3600, h: 2160 } }, plate);
  assert.equal(bad.aligned, false);
  assert.ok(bad.reasons.some((r) => /handles/.test(r)));
  // VFX realign proposes the right range + handles.
  assert.deepEqual(I.vfxRealign(plate), { realignedIn: 92, realignedOut: 208, handles: 8 });
});

test('insert: res/format mismatch -> sizing patch + transcode', () => {
  const ok = I.resFormatReconcile({ dims: { w: 3600, h: 2160 }, codec: 'prores' }, { dims: { w: 3600, h: 2160 }, codec: 'prores' });
  assert.equal(ok.match, true);
  const bad = I.resFormatReconcile({ dims: { w: 1920, h: 1152 }, codec: 'h264' }, { dims: { w: 3600, h: 2160 }, codec: 'prores' });
  assert.equal(bad.match, false);
  assert.ok(bad.sizingPatch.scale > 1);
  assert.deepEqual(bad.transcode, { to: 'prores' });
});

test('insert: Topaz/regrade content-identity verify (enhanced-but-same) via comparator', async () => {
  // The synthetic match pair stands in for an enhanced-but-structurally-same upscale.
  const res = await I.topazContentVerify(SF('match__reference.png'), SF('match__derived.png'), { elementDims: { w: 3600, h: 2160 }, dims: { w: 3600, h: 2160 } }, compare.compareFrames);
  assert.equal(res.mode, 'content-identity');
  assert.equal(res.verdict, 'MATCH');
});

test('insert: element/slot record carries version + verify mode + verdict', () => {
  const rec = I.makeSlotRecord({ element: { name: 'SH020_vfx_v3.mov', kind: 'vfx_of', version: 3 }, slot: { cutId: 'c2' }, method: 'shot-id', verifyMode: 'alignment', verdict: 'aligned', provenance: { realigned: true } });
  assert.equal(rec.type, 'ElementSlot');
  assert.equal(rec.element.version, 3);
  assert.equal(rec.slotCutId, 'c2');
  assert.equal(rec.verifyMode, 'alignment');
});
