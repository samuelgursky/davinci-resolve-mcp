'use strict';

/** End-to-end verify-pass tests, incl. the advisory vision wiring. */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const pkg = require('../index');
const { verify } = require('../ops/verify');
const { FakeVisionValidator } = require('../adapters/vision-validator');

const SAMPLE = pkg.reelFixtureDir();
const GOLDEN = JSON.parse(fs.readFileSync(path.join(SAMPLE, 'golden_oracle.json'), 'utf8'));

const SYNTH_DIR = path.join(__dirname, '..', '__fixtures__', 'synthetic');
const SYNTH = JSON.parse(fs.readFileSync(path.join(SYNTH_DIR, 'golden_oracle.synth.json'), 'utf8'));
const SF = (name) => path.join(SYNTH_DIR, 'frames', name);

test('verify: Tier C (no reference) — all 327 SAMPLE clips MATH-VERIFIED, read-only', async () => {
  const rep = await verify(GOLDEN, {});
  assert.equal(rep.perCut.length, 327);
  assert.equal(rep.summary.mathVerified, 327);
  assert.equal(rep.summary.flagged, 0);
  for (const c of rep.perCut) {
    assert.equal(c.hasReference, false);
    assert.equal(c.tier, 'C');
    assert.equal(c.badge, 'math-verified'); // never content-verified without a picture
  }
  // Composition sanity: a known cut's derived source frame flows through.
  const first = rep.perCut.find((c) => c.seqstart === 192);
  assert.equal(first.derivedSourceFrame, 47962);
});

test('verify: client-free synthetic reel with a reference provider (MATCH + WRONG)', async () => {
  // Map each synthetic clip to a synthetic frame pair by index.
  const pairs = [
    { label: 'match', want: 'MATCH' },
    { label: 'darktrap', want: 'MATCH' },
    { label: 'wrong', want: 'WRONG' },
    { label: 'match', want: 'MATCH' },
  ];
  const referenceProvider = (clip) => {
    const idx = SYNTH.clips.findIndex((c) => c.seqstart === clip.seqstart);
    const p = pairs[idx % pairs.length];
    return { referencePath: SF(`${p.label}__reference.png`), derivedPath: SF(`${p.label}__derived.png`), tier: 'B', label: p.label };
  };
  const rep = await verify(SYNTH, { referenceProvider });
  assert.equal(rep.perCut.length, SYNTH.clips.length);
  rep.perCut.forEach((c, i) => {
    assert.equal(c.status, pairs[i].want, `clip ${i} want ${pairs[i].want} got ${c.status}`);
    assert.equal(c.hasReference, true);
  });
  assert.ok(rep.summary.matched >= 3 && rep.summary.wrong === 1);
});

test('verify: vision is consulted only on the cost-gated cuts (propose-only repair)', async () => {
  const fake = new FakeVisionValidator({ default: { verdict: 'MATCH', confidence: 0.8, rationale: 'same' } });
  // Clip 0: a normal clear MATCH (NOT a propose-only repair) — must NOT consult.
  // Clip 2 (wrong): flagged as a stubborn propose-only repair — MUST consult.
  const referenceProvider = (clip) => {
    const idx = SYNTH.clips.findIndex((c) => c.seqstart === clip.seqstart);
    if (idx === 0) return { referencePath: SF('match__reference.png'), derivedPath: SF('match__derived.png'), tier: 'B', label: 'match' };
    if (idx === 2) return { referencePath: SF('wrong__reference.png'), derivedPath: SF('wrong__derived.png'), tier: 'B', label: 'wrong', proposeOnlyRepair: true };
    return null;
  };
  const rep = await verify(SYNTH, { referenceProvider, visionValidator: fake });
  const c0 = rep.perCut[0];
  const c2 = rep.perCut[2];
  assert.equal(c0.visionConsulted, false, 'a clear MATCH must not spend a vision call');
  assert.equal(c2.visionConsulted, true, 'a stubborn propose-only repair must consult vision');
  // The wrong cut: deterministic WRONG, vision (fake) says MATCH => dispute => REVIEW (never flipped to MATCH).
  assert.equal(c2.status, 'REVIEW');
  assert.equal(c2.escalated, true);
  assert.ok(c2.advisory && c2.advisory.advisory === true);
  // Cost gate: the fake was called exactly once (only for clip 2).
  assert.equal(fake.calls.length, 1);
});

test('verify: a corroborating vision opinion leaves the deterministic verdict intact', async () => {
  const fake = new FakeVisionValidator({ wrong: { verdict: 'WRONG', confidence: 0.9, rationale: 'different shot' } });
  const referenceProvider = (clip) => {
    const idx = SYNTH.clips.findIndex((c) => c.seqstart === clip.seqstart);
    if (idx === 2) return { referencePath: SF('wrong__reference.png'), derivedPath: SF('wrong__derived.png'), tier: 'B', label: 'wrong', proposeOnlyRepair: true };
    return null;
  };
  const rep = await verify(SYNTH, { referenceProvider, visionValidator: fake });
  const c2 = rep.perCut[2];
  assert.equal(c2.visionConsulted, true);
  assert.equal(c2.status, 'WRONG'); // metric WRONG + vision WRONG => corroborated, stays WRONG
  assert.equal(c2.escalated, false);
});
