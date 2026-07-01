'use strict';

/**
 * P4.5 ACCEPTANCE (patch / re-cut half) — on the real SAMPLE reel: ingest a
 * revised turnover that changes exactly two cuts (one source swap, one duration
 * change) and assert the lifecycle re-conforms ONLY the changed cuts, leaves the
 * other 325 untouched, re-derives the changed cuts correctly (Oracle), and
 * ripples the downstream record positions by the duration delta.
 *
 * Pure (Oracle math + diff; no media), so it runs anywhere. The VFX/Topaz insert
 * half of the umbrella P4.5-acceptance still needs real render artifacts.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const pkg = require('../index');
const oracle = require('../oracle');
const { diffTimelines, reverifyChanged, rippleUpdate } = require('../ops/patch');

const GOLDEN = JSON.parse(fs.readFileSync(path.join(pkg.reelFixtureDir(), 'golden_oracle.json'), 'utf8'));
const CTX = { ticksPerFrame: GOLDEN.ticksPerFrame, sequenceWidth: GOLDEN.sequence.width };

// CURRENT online: the 327 conformed cuts (sourceFrame = the Oracle/clip_where frame).
const sorted = [...GOLDEN.clips].sort((a, b) => a.seqstart - b.seqstart);
const CURRENT = sorted.map((c) => ({ ...c, sourceFrame: c.expected_source_start }));

test('P4.5 ACCEPTANCE (patch): a revised cut re-conforms ONLY changed cuts, ripples downstream', async () => {
  // Pick two real cuts to edit: a duration change early in the reel (so it has
  // downstream neighbours to ripple) and a source swap later.
  const durIdx = 40;
  const swapIdx = 120;
  const durSeq = CURRENT[durIdx].seqstart;
  const swapSeq = CURRENT[swapIdx].seqstart;
  // A donor cut with a genuinely different source for the swap.
  const donor = CURRENT.find((c) => c.source_basename !== CURRENT[swapIdx].source_basename);
  assert.ok(donor, 'a donor with a different source exists');

  const DELTA = 12;
  const REVISED = CURRENT.map((c) => {
    if (c.seqstart === durSeq) {
      // Duration change only (same source) → changed + drives ripple.
      return { ...c, seqend: c.seqend + DELTA };
    }
    if (c.seqstart === swapSeq) {
      // Source swap: graft the donor's source + Oracle inputs onto this slot,
      // keeping the original record position/duration (a content replacement).
      return {
        ...donor,
        seqstart: c.seqstart,
        seqend: c.seqend,
        source_basename: donor.source_basename,
        sourceFrame: donor.expected_source_start,
      };
    }
    return c;
  });

  // 1) DIFF — exactly the two edited cuts are flagged; the rest are unchanged.
  const d = diffTimelines(CURRENT, REVISED);
  assert.equal(d.added.length, 0);
  assert.equal(d.removed.length, 0);
  assert.equal(d.changed.length, 2, `expected 2 changed, got ${d.changed.map((x) => x.seqstart)}`);
  assert.equal(d.unchanged.length, 325);
  const changedSeqs = d.changed.map((x) => x.seqstart).sort((a, b) => a - b);
  assert.deepEqual(changedSeqs, [durSeq, swapSeq].sort((a, b) => a - b));

  // 2) RE-VERIFY — only changed cuts are re-conformed; the 325 unchanged are skipped.
  const reconformed = [];
  const out = await reverifyChanged(d, async (cut) => {
    const derived = oracle.derive(cut, CTX).derivedSourceFrame;
    reconformed.push({ seqstart: cut.seqstart, derived });
    return 'MATCH';
  });
  assert.equal(out.skipped, 325);
  assert.equal(out.reverified.length, 2);
  assert.deepEqual(reconformed.map((r) => r.seqstart).sort((a, b) => a - b), changedSeqs);
  // The swapped cut re-derives to the DONOR's source frame (the re-conform is correct,
  // not a stale carry-over of the old cut's frame).
  const swapReconform = reconformed.find((r) => r.seqstart === swapSeq);
  assert.equal(swapReconform.derived, donor.expected_source_start, 'swapped cut re-derived to the new source frame');

  // 3) RIPPLE — the +DELTA duration shifts every downstream cut by DELTA; the
  //    changed cut + its neighbour are marked touched.
  const { rippled, touched, totalShift } = rippleUpdate(CURRENT, d);
  assert.equal(totalShift, DELTA, `total downstream shift should equal the duration delta (${DELTA})`);
  const durOrdinal = sorted.findIndex((c) => c.seqstart === durSeq);
  // rippleUpdate preserves the sorted order; verify by ordinal: downstream shifts, upstream doesn't.
  rippled.forEach((r, i) => {
    if (i > durOrdinal) {
      assert.equal(r.seqstart, sorted[i].seqstart + DELTA, `downstream cut #${i} must shift by ${DELTA}`);
    } else if (i < durOrdinal) {
      assert.equal(r.seqstart, sorted[i].seqstart, `upstream cut #${i} must not move`);
    }
  });
  assert.ok(touched.includes(durSeq), 'the duration-changed cut is touched');

  // eslint-disable-next-line no-console
  console.log(`[P4.5] PATCH ACCEPTANCE: revised SAMPLE reel → 2/327 cuts re-conformed (swap@${swapSeq}, dur@${durSeq}), 325 skipped, downstream rippled +${DELTA}.`);
});
