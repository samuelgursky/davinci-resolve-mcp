'use strict';

/**
 * Oracle tests — verified END-TO-END against the committed golden answer key
 * (golden_oracle.json: 327 SAMPLE clips, each with input fields + the
 * expected_source_start that Resolve's clip_where actually produced).
 *
 * No raw XML or frames needed — golden_oracle.json embeds the inputs, so these
 * run client-free on any machine.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const pkg = require('../index');
const oracle = require('../oracle');
const resolveTarget = require('../oracle/resolve');

const GOLDEN = JSON.parse(
  fs.readFileSync(path.join(pkg.reelFixtureDir(), 'golden_oracle.json'), 'utf8'),
);
const COMPARE = JSON.parse(
  fs.readFileSync(path.join(pkg.reelFixtureDir(), 'golden_compare.json'), 'utf8'),
);
const CTX = { ticksPerFrame: GOLDEN.ticksPerFrame, sequenceWidth: GOLDEN.sequence.width };

test('Oracle (resolve): source_start for all PLAIN (non-subclip) clips', () => {
  const plain = GOLDEN.clips.filter((c) => !c.is_subclip);
  assert.ok(plain.length > 0, 'fixture must contain non-subclip clips');
  let checked = 0;
  for (const c of plain) {
    const { derivedSourceFrame } = resolveTarget.derive(c, CTX);
    assert.equal(
      derivedSourceFrame,
      c.expected_source_start,
      `plain clip @seq${c.seqstart} (${c.source_basename}): derived ${derivedSourceFrame} != expected ${c.expected_source_start}`,
    );
    checked += 1;
  }
  // eslint-disable-next-line no-console
  console.log(`[oracle] plain clips verified: ${checked}/${plain.length}`);
});

test('Oracle (resolve): source_start for all SUBCLIP clips (startoffset + in)', () => {
  const subs = GOLDEN.clips.filter((c) => c.is_subclip);
  assert.ok(subs.length > 0, 'fixture must contain subclip clips (pickups)');
  for (const c of subs) {
    const { derivedSourceFrame } = resolveTarget.derive(c, CTX);
    assert.equal(
      derivedSourceFrame,
      c.expected_source_start,
      `subclip @seq${c.seqstart} (${c.source_basename}): derived ${derivedSourceFrame} != expected ${c.expected_source_start} (startoffset ${c.subclip_startoffset} + in ${c.xml_in})`,
    );
    // The subclip offset must actually participate (don't rewrite <in>).
    assert.equal(derivedSourceFrame, (c.subclip_startoffset || 0) + c.xml_in);
  }
  // eslint-disable-next-line no-console
  console.log(`[oracle] subclip clips verified: ${subs.length}`);
});

test('Oracle (resolve): ACCEPTANCE — source_start for ALL 327 clips, zero mismatches', () => {
  assert.equal(GOLDEN.clips.length, 327);
  const mismatches = [];
  for (const c of GOLDEN.clips) {
    const { derivedSourceFrame } = resolveTarget.derive(c, CTX);
    if (derivedSourceFrame !== c.expected_source_start) {
      mismatches.push({ seq: c.seqstart, derived: derivedSourceFrame, expected: c.expected_source_start });
    }
  }
  assert.deepEqual(mismatches, [], `expected 0 source_start mismatches, got ${mismatches.length}`);
  // eslint-disable-next-line no-console
  console.log(`[oracle] ACCEPTANCE: 327/327 source_start reproduced (0 mismatches)`);
});

test('Oracle (pluggable target): registry resolves "resolve" and errors on unknown', () => {
  assert.equal(oracle.DEFAULT_TARGET, 'resolve');
  assert.equal(oracle.getTarget('resolve').id, 'resolve');
  assert.throws(() => oracle.getTarget('premiere'), /unknown target "premiere"/);
  // Deriving via the registry must match the direct ruleset for all 327 clips.
  for (const c of GOLDEN.clips) {
    const viaRegistry = oracle.derive(c, CTX);
    const direct = resolveTarget.derive(c, CTX);
    assert.deepEqual(viaRegistry, direct, `registry vs direct mismatch @seq${c.seqstart}`);
  }
  // eslint-disable-next-line no-console
  console.log('[oracle] pluggable target: registry == direct for 327/327');
});

test('Oracle (resolve): corrected scale (double-count fix) for ALL 327, ±0.001', () => {
  const mismatches = [];
  for (const c of GOLDEN.clips) {
    const { derivedScaleCorrected } = resolveTarget.derive(c, CTX);
    if (Math.abs(derivedScaleCorrected - c.expected_scale_corrected) > 0.001) {
      mismatches.push({ seq: c.seqstart, derived: derivedScaleCorrected, expected: c.expected_scale_corrected });
    }
  }
  assert.deepEqual(mismatches, [], `expected 0 scale mismatches (±0.001), got ${mismatches.length}: ${JSON.stringify(mismatches.slice(0, 5))}`);
  // eslint-disable-next-line no-console
  console.log(`[oracle] corrected scale: 327/327 within ±0.001`);
});

test('Oracle (resolve): slow-mo via ticks — sample frame ~2*in, readback = in', () => {
  // The retimed clips: ticks/tpf diverges from <in> (50% slow-mo => ~2*in).
  const retimes = GOLDEN.clips.filter((c) => resolveTarget.isRetimed(c, CTX));
  assert.ok(retimes.length >= 1, 'fixture must contain at least one retimed clip');
  for (const c of retimes) {
    const out = resolveTarget.derive(c, CTX);
    // Readback (golden_oracle): Resolve reports the speed-adjusted media-in (= in).
    assert.equal(out.derivedSourceFrame, c.expected_source_start);
    assert.equal(out.derivedSourceFrame, c.xml_in);
    // Sample frame (the ticks path) is ~2x the in-frame for a 50% retime.
    const ratio = out.derivedSampleFrame / c.xml_in;
    assert.ok(ratio > 1.5 && ratio < 2.5, `retime @seq${c.seqstart} sample/in ratio ${ratio} not ~2`);
  }

  // Cross-check the named golden_compare slow-mo case (seqstart 7894): its
  // documented derived_source_frame (the sampled frame) must match the Oracle's
  // ticks-based sample frame within 1 frame (golden labels 2*in; ticks/tpf is
  // exact and lands within a frame of it).
  const sm = COMPARE.cases.find((x) => x.label === 'slowmo_via_ticks');
  const clip = GOLDEN.clips.find((x) => x.seqstart === sm.seqstart);
  assert.ok(clip, 'golden_oracle must contain the slowmo_via_ticks seqstart');
  const out = resolveTarget.derive(clip, CTX);
  assert.ok(
    Math.abs(out.derivedSampleFrame - sm.derived_source_frame) <= 1,
    `sample frame ${out.derivedSampleFrame} not within 1 of golden_compare ${sm.derived_source_frame}`,
  );
  assert.equal(out.retimed, true);
  // eslint-disable-next-line no-console
  console.log(
    `[oracle] retimes verified: ${retimes.length}; slowmo seq${sm.seqstart} ` +
      `sample=${out.derivedSampleFrame} (golden ${sm.derived_source_frame}), readback=${out.derivedSourceFrame}`,
  );
});
