'use strict';

/**
 * Synthetic-fixture tests — the CLIENT-FREE coverage (P0-synthetic-fixture).
 *
 * Unlike the SAMPLE tests, these are NOT skip-if-absent: the synthetic fixture is
 * committed (it contains no client data), so the whole pipeline — parse, Oracle,
 * comparator — is exercised on every fresh clone with NO raw material present.
 * Regenerate with: node synthetic/generate.js
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const parse = require('../parse');
const oracle = require('../oracle');
const compare = require('../compare');

const DIR = path.join(__dirname, '..', '__fixtures__', 'synthetic');
const ORACLE = JSON.parse(fs.readFileSync(path.join(DIR, 'golden_oracle.synth.json'), 'utf8'));
const COMPARE = JSON.parse(fs.readFileSync(path.join(DIR, 'golden_compare.synth.json'), 'utf8'));
const XML = fs.readFileSync(path.join(DIR, 'turnover.synth.xml'), 'utf8');
const CTX = { ticksPerFrame: ORACLE.ticksPerFrame, sequenceWidth: ORACLE.sequence.width };

test('synthetic: Oracle derives source_start, sample frame + corrected scale (client-free)', () => {
  for (const c of ORACLE.clips) {
    const out = oracle.derive(c, CTX);
    assert.equal(out.derivedSourceFrame, c.expected_source_start, `${c.key} source_start`);
    assert.equal(out.derivedSampleFrame, c.expected_sample_frame, `${c.key} sample frame`);
    assert.ok(Math.abs(out.derivedScaleCorrected - c.expected_scale_corrected) < 1e-6, `${c.key} scale`);
  }
  // The slow-mo clip diverges (sample = 2*in) while its readback = in.
  const slow = ORACLE.clips.find((c) => c.key === 'slowmo');
  const so = oracle.derive(slow, CTX);
  assert.equal(so.retimed, true);
  assert.equal(so.derivedSampleFrame, slow.xml_in * 2);
  assert.equal(so.derivedSourceFrame, slow.xml_in);
});

test('synthetic: parser captures every field incl. file-id resolution (client-free)', () => {
  const parsed = parse.parseGeometry(XML);
  const bySeq = new Map(parsed.clips.map((c) => [c.seqstart, c]));
  for (const c of ORACLE.clips) {
    const pc = bySeq.get(c.seqstart);
    assert.ok(pc, `parsed clip @seq${c.seqstart}`);
    assert.equal(pc.xml_in, c.xml_in);
    assert.equal(pc.pproTicksIn, c.pproTicksIn);
    assert.equal(pc.is_subclip, c.is_subclip);
    assert.equal(pc.subclip_startoffset, c.subclip_startoffset);
    assert.equal(pc.scale_premiere, c.scale_premiere);
    assert.equal(pc.srcW, c.srcW);
    assert.ok(pc.source_basename, `${c.key} source_basename resolved`);
  }
  // The 'reframe' clip references file-1 self-closing — proves file-id resolution.
  const reframe = bySeq.get(144);
  assert.equal(reframe.fileId, 'file-1');
  assert.ok(reframe.source_basename.includes('SYNTH_normal'));
});

test('synthetic: parser captures center/crop/rotation reframe (client-free)', () => {
  const parsed = parse.parseGeometry(XML);
  const bySeq = new Map(parsed.clips.map((c) => [c.seqstart, c]));
  for (const c of ORACLE.clips) {
    const pc = bySeq.get(c.seqstart);
    assert.deepEqual(pc.center, c.center, `${c.key} center`);
    assert.equal(pc.rotation, c.rotation, `${c.key} rotation`);
    assert.deepEqual(pc.crop, c.crop, `${c.key} crop`);
  }
  // The reframe clip carries the non-zero values; the others are zero.
  const reframe = bySeq.get(144);
  assert.deepEqual(reframe.center, { h: 120, v: -60 });
  assert.equal(reframe.rotation, 5);
  assert.deepEqual(reframe.crop, { left: 10, top: 4, right: 8, bottom: 2 });
});

test('synthetic: Oracle derivedTransform carries scale + center/crop/rotation (client-free)', () => {
  const reframe = ORACLE.clips.find((c) => c.key === 'reframe');
  const t = oracle.derive(reframe, CTX).derivedTransform;
  assert.ok(Math.abs(t.scale - reframe.expected_scale_corrected) < 1e-6, 'normalized scale');
  assert.deepEqual(t.center, reframe.center);
  assert.deepEqual(t.crop, reframe.crop);
  assert.equal(t.rotation, reframe.rotation);
  // A clip with no reframe (golden_oracle-shaped) passes through null cleanly.
  const bare = oracle.derive({ pproTicksIn: 1000 * ORACLE.ticksPerFrame, xml_in: 1000, is_subclip: false, scale_premiere: 200, srcW: 960 }, CTX);
  assert.equal(bare.derivedTransform.center, null);
  assert.equal(bare.derivedTransform.rotation, null);
});

test('synthetic: comparator classifies match / dark-trap / wrong (client-free)', async () => {
  for (const c of COMPARE.cases) {
    const out = await compare.compareFrames(path.join(DIR, c.reference), path.join(DIR, c.derived));
    assert.equal(out.verdict, c.expected_verdict, `${c.label}: ${out.verdict} != ${c.expected_verdict}`);
  }
  // eslint-disable-next-line no-console
  console.log('[synthetic] client-free pipeline OK: parse + oracle + comparator (4 clips, 3 verdicts incl. dark trap)');
});
