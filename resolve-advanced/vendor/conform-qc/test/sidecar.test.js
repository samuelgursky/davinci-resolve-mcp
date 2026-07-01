'use strict';

/** Tier B TC-sidecar reference provider — client-free (synthetic frames). */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const { tcSidecarProvider } = require('../reference/sidecar');
const { verify } = require('../ops/verify');

const SYNTH_DIR = path.join(__dirname, '..', '__fixtures__', 'synthetic');
const SYNTH = JSON.parse(fs.readFileSync(path.join(SYNTH_DIR, 'golden_oracle.synth.json'), 'utf8'));
const SF = (name) => path.join(SYNTH_DIR, 'frames', name);

test('sidecar: maps a cut to its reference frame + source identity (no OCR)', () => {
  const sidecar = [
    { seqstart: 0, sourceTc: '01:00:00:00', sourceName: 'SYNTH_normal.mov', referenceFrame: 'match__reference.png', derivedFrame: 'match__derived.png', label: 'match' },
  ];
  const provider = tcSidecarProvider(sidecar, SF);
  const got = provider({ seqstart: 0 });
  assert.equal(got.tier, 'B');
  assert.equal(got.identity.sourceName, 'SYNTH_normal.mov');
  assert.equal(got.identity.sourceTc, '01:00:00:00');
  assert.ok(got.referencePath.endsWith('match__reference.png'));
  // A cut with no sidecar entry falls back to Tier C (null provider result).
  assert.equal(provider({ seqstart: 9999 }), null);
});

test('sidecar: drives the verify pass to a content-verified report carrying identity', async () => {
  const sidecar = SYNTH.clips.map((c, i) => ({
    seqstart: c.seqstart,
    sourceTc: `01:00:0${i}:00`,
    sourceName: `${c.key}.mov`,
    referenceFrame: i === 2 ? 'wrong__reference.png' : 'match__reference.png',
    derivedFrame: i === 2 ? 'wrong__derived.png' : 'match__derived.png',
    label: c.key,
  }));
  const rep = await verify(SYNTH, { referenceProvider: tcSidecarProvider(sidecar, SF) });
  // Every cut had a sidecar => Tier B with identity recorded.
  for (const c of rep.perCut) {
    assert.equal(c.tier, 'B');
    assert.ok(c.identity && c.identity.sourceName, 'identity from sidecar must be on the report');
  }
  // The matching cuts are content-verified; the one wrong pair is flagged.
  const matched = rep.perCut.filter((c) => c.status === 'MATCH');
  assert.ok(matched.length >= 3);
  assert.equal(matched[0].badge, 'content-verified');
  assert.equal(rep.summary.wrong, 1);
});
