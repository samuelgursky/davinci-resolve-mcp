'use strict';

/**
 * P0 ACCEPTANCE (spec §13 P0): on the SAMPLE reel, the Oracle reproduces Resolve's
 * source_start for all 327 cuts AND the comparator classifies the known matches /
 * the 1 genuine wrong correctly.
 *
 * The Oracle half runs client-free from golden_oracle.json (all 327). The
 * comparator half runs on the 4 representative golden_compare pairs (incl. the
 * 1 genuine WRONG = seq2983) and SKIPS-IF-ABSENT — the full-reel 326-match/1-wrong
 * sweep needs every reference frame (Tier-2/volumes), out of scope for Tier 1.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const pkg = require('../index');
const oracle = require('../oracle');
const compare = require('../compare');

const DIR = pkg.reelFixtureDir();
const GOLDEN = JSON.parse(fs.readFileSync(path.join(DIR, 'golden_oracle.json'), 'utf8'));
const COMPARE = JSON.parse(fs.readFileSync(path.join(DIR, 'golden_compare.json'), 'utf8'));
const CTX = { ticksPerFrame: GOLDEN.ticksPerFrame, sequenceWidth: GOLDEN.sequence.width };

const FRAMES = path.join(DIR, 'frames');
const HAVE_FRAMES = fs.existsSync(FRAMES) && fs.readdirSync(FRAMES).some((f) => f.endsWith('.png'));

test('P0 ACCEPTANCE (Oracle half): source_start + corrected scale for all 327', () => {
  let srcMismatch = 0;
  let scaleMismatch = 0;
  for (const c of GOLDEN.clips) {
    const out = oracle.derive(c, CTX);
    if (out.derivedSourceFrame !== c.expected_source_start) srcMismatch += 1;
    if (Math.abs(out.derivedScaleCorrected - c.expected_scale_corrected) > 0.001) scaleMismatch += 1;
  }
  assert.equal(srcMismatch, 0, `${srcMismatch} source_start mismatches`);
  assert.equal(scaleMismatch, 0, `${scaleMismatch} scale mismatches`);
  // eslint-disable-next-line no-console
  console.log('[P0] ACCEPTANCE Oracle: 327/327 source_start + 327/327 scale');
});

test('P0 ACCEPTANCE (comparator half): the 1 genuine WRONG and the matches classify correctly', { skip: HAVE_FRAMES ? false : 'frames/ absent — skipping comparator half' }, async () => {
  const verdicts = {};
  for (const c of COMPARE.cases) {
    const out = await compare.compareFrames(path.join(DIR, c.reference), path.join(DIR, c.derived));
    verdicts[c.label] = out.verdict;
    assert.equal(out.verdict, c.expected_verdict, `${c.label}: ${out.verdict} != ${c.expected_verdict}`);
  }
  // The genuine wrong (seq2983, 111 frames off) MUST be WRONG; the rest MATCH.
  assert.equal(verdicts.genuine_wrong, 'WRONG');
  const matches = Object.values(verdicts).filter((v) => v === 'MATCH').length;
  const wrongs = Object.values(verdicts).filter((v) => v === 'WRONG').length;
  assert.equal(matches, 3);
  assert.equal(wrongs, 1);
  // eslint-disable-next-line no-console
  console.log(`[P0] ACCEPTANCE comparator: ${matches} MATCH / ${wrongs} WRONG (representative golden set)`);
});
