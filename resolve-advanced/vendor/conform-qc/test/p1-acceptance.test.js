'use strict';

/**
 * P1 ACCEPTANCE (spec §13 P1): run the verify pass on the SAMPLE reel and get a
 * per-cut report matching the manual finding — the dark cut MATCHes, the slow-mo
 * (via ticks) is correct, and the one genuine wrong is flagged.
 *
 * Runs on the 4 representative golden_compare cuts (the manual finding's
 * exemplars) via the verify pipeline end-to-end. SKIPS-IF-ABSENT (frames are
 * git-ignored). The full-reel 326/1 sweep needs every reference frame
 * (Tier-2/volumes), out of Tier-1 scope.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const pkg = require('../index');
const { verify } = require('../ops/verify');

const SAMPLE = pkg.reelFixtureDir();
const GOLDEN = JSON.parse(fs.readFileSync(path.join(SAMPLE, 'golden_oracle.json'), 'utf8'));
const COMPARE = JSON.parse(fs.readFileSync(path.join(SAMPLE, 'golden_compare.json'), 'utf8'));
const FRAMES = path.join(SAMPLE, 'frames');
const HAVE_FRAMES = fs.existsSync(FRAMES) && fs.readdirSync(FRAMES).some((f) => f.endsWith('.png'));
const SKIP = HAVE_FRAMES ? false : 'frames/ absent (git-ignored) — skipping P1 acceptance';

const TPF = GOLDEN.ticksPerFrame;

// Build a small "reel" model from the golden_compare exemplars. Oracle inputs are
// synthesized consistently from each case's derived_source_frame so the pipeline
// runs intact (the Oracle is separately verified on all 327 in oracle.test.js).
function modelFromCompare() {
  return {
    sequence: GOLDEN.sequence,
    ticksPerFrame: TPF,
    clips: COMPARE.cases.map((c) => ({
      seqstart: c.seqstart,
      label: c.label,
      xml_in: c.derived_source_frame,
      pproTicksIn: c.derived_source_frame * TPF,
      is_subclip: false,
      subclip_startoffset: 0,
      scale_premiere: 100,
      srcW: GOLDEN.sequence.width,
      srcH: GOLDEN.sequence.height,
    })),
  };
}

test('P1 ACCEPTANCE: verify report matches the manual finding on the golden reel', { skip: SKIP }, async () => {
  const model = modelFromCompare();
  const byLabel = Object.fromEntries(COMPARE.cases.map((c) => [c.seqstart, c]));
  const referenceProvider = (clip) => {
    const c = byLabel[clip.seqstart];
    return { referencePath: path.join(SAMPLE, c.reference), derivedPath: path.join(SAMPLE, c.derived), tier: 'A', label: c.label };
  };

  const rep = await verify(model, { referenceProvider, target: 'resolve' });

  const verdictBySeq = Object.fromEntries(rep.perCut.map((c) => [c.seqstart, c.status]));
  for (const c of COMPARE.cases) {
    assert.equal(verdictBySeq[c.seqstart], c.expected_verdict, `${c.label}: ${verdictBySeq[c.seqstart]} != ${c.expected_verdict}`);
  }
  // The manual finding, explicitly: dark grade MATCHes, slow-mo correct, 1 wrong.
  assert.equal(rep.summary.matched, 3);
  assert.equal(rep.summary.wrong, 1);
  // Tier A with a MATCH => content-verified badge (we had a picture).
  const dark = rep.perCut.find((c) => c.seqstart === 25748);
  assert.equal(dark.status, 'MATCH');
  assert.equal(dark.badge, 'content-verified');
  // eslint-disable-next-line no-console
  console.log(`[P1] ACCEPTANCE: ${rep.summary.matched} MATCH / ${rep.summary.wrong} WRONG (dark-grade MATCH, slow-mo correct)`);
});
