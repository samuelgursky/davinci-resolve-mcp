/**
 * P1.5 — extractMatteFinesse tests.
 *
 * No generator emits MATTE_FINESSE params today, so synthesize the
 * parameter list the registry says Resolve emits. All scale: DRX = UI / 100
 * (TRAINED 2026-03-16, corrected 2026-03-22).
 *
 * External matte refs (file path / media pool ID / channel / invert /
 * expand) are a separate encoding not yet reverse-engineered.
 * Queued as deferred Resolve-fixture work — see
 * knowledge/resolve-verifications.md.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const drxParams = require('../../drx-parameters');
const { extractMatteFinesse, _internals } = require('../extract-matte-finesse');

const { MATTE_FINESSE } = drxParams;
const MF = MATTE_FINESSE;

function synthesize(spec) {
  const params = [];
  const add = (id, ui) => params.push({ id, value: ui / 100, name: 'mf' });
  if (spec.denoise !== undefined) add(MF.DENOISE, spec.denoise);
  if (spec.blackClip !== undefined) add(MF.BLACK_CLIP, spec.blackClip);
  if (spec.whiteClip !== undefined) add(MF.WHITE_CLIP, spec.whiteClip);
  if (spec.inOutRatio !== undefined) add(MF.IN_OUT_RATIO, spec.inOutRatio);
  if (spec.cleanBlack !== undefined) add(MF.CLEAN_BLACK, spec.cleanBlack);
  if (spec.cleanWhite !== undefined) add(MF.CLEAN_WHITE, spec.cleanWhite);
  if (spec.morphRadius !== undefined) add(MF.MORPH_RADIUS, spec.morphRadius);
  if (spec.preFilter !== undefined) add(MF.PRE_FILTER, spec.preFilter);
  if (spec.postFilter !== undefined) add(MF.POST_FILTER, spec.postFilter);
  if (spec.shadow !== undefined) add(MF.SHADOW, spec.shadow);
  if (spec.midtone !== undefined) add(MF.MIDTONE, spec.midtone);
  if (spec.highlight !== undefined) add(MF.HIGHLIGHT, spec.highlight);
  return params;
}

const TOL = 1e-3;
function close(a, b) {
  return Math.abs(a - b) < TOL;
}

test('extractMatteFinesse: denoise-only (training canary: 15 → 0.15)', () => {
  const out = extractMatteFinesse(synthesize({ denoise: 15 }));
  assert.ok(out);
  assert.ok(close(out.denoise, 15));
});

test('extractMatteFinesse: cleanBlack-only (training canary: 30 → 0.30)', () => {
  const out = extractMatteFinesse(synthesize({ cleanBlack: 30 }));
  assert.ok(close(out.cleanBlack, 30));
});

test('extractMatteFinesse: black/white clip pair', () => {
  const out = extractMatteFinesse(synthesize({ blackClip: 10, whiteClip: 90 }));
  assert.ok(close(out.blackClip, 10));
  assert.ok(close(out.whiteClip, 90));
});

test('extractMatteFinesse: zone-based fine tuning (shadow/mid/highlight)', () => {
  const out = extractMatteFinesse(synthesize({
    shadow: 20, midtone: 50, highlight: 80,
  }));
  assert.ok(close(out.shadow, 20));
  assert.ok(close(out.midtone, 50));
  assert.ok(close(out.highlight, 80));
});

test('extractMatteFinesse: filter chain (pre + morph + post)', () => {
  const out = extractMatteFinesse(synthesize({
    preFilter: 5, morphRadius: 3, postFilter: 7,
  }));
  assert.ok(close(out.preFilter, 5));
  assert.ok(close(out.morphRadius, 3));
  assert.ok(close(out.postFilter, 7));
});

test('extractMatteFinesse: full spec round-trips all 12 params', () => {
  const input = {
    denoise: 12, blackClip: 8, whiteClip: 92, inOutRatio: 50,
    cleanBlack: 25, cleanWhite: 35, morphRadius: 4,
    preFilter: 6, postFilter: 10,
    shadow: 22, midtone: 48, highlight: 78,
  };
  const out = extractMatteFinesse(synthesize(input));
  for (const [k, expected] of Object.entries(input)) {
    assert.ok(close(out[k], expected), `${k}: got ${out[k]}, expected ${expected}`);
  }
});

test('extractMatteFinesse: returns null when no matte params present', () => {
  assert.equal(extractMatteFinesse([
    { id: 100663320, value: 0.5, name: 'lift.r' },
  ]), null);
});

test('extractMatteFinesse: handles malformed input', () => {
  assert.equal(extractMatteFinesse(null), null);
  assert.equal(extractMatteFinesse(undefined), null);
  assert.equal(extractMatteFinesse([]), null);
});

test('extractMatteFinesse: handles BigInt values gracefully', () => {
  const out = extractMatteFinesse([
    // BigInt 0 maps to 0 — graceful, not crash.
    { id: MF.DENOISE, value: 0n, name: 'denoise' },
  ]);
  assert.equal(out.denoise, 0);
});

test('extractMatteFinesse: filters non-matte param IDs', () => {
  // 100663320 is LIFT.R, not in MATTE_FINESSE — must be ignored
  const out = extractMatteFinesse([
    { id: MF.DENOISE, value: 0.20, name: 'denoise' },
    { id: 100663320, value: 0.5, name: 'lift.r' },
  ]);
  assert.equal(Object.keys(out).length, 1);
  assert.ok(close(out.denoise, 20));
});

test('internals.drxToUi: round-trips and clamps non-finite', () => {
  assert.equal(_internals.drxToUi(0.15), 15);
  assert.equal(_internals.drxToUi(0.3), 30);
  assert.equal(_internals.drxToUi(NaN), 0);
  assert.equal(_internals.drxToUi(Infinity), 0);
});

// ─── Real round-trip via generateDRX (Session 25 wiring) ─────────────────

const { generateDRX } = require('../drx-generator');
const { parseDRXContent } = require('../drx-parser');

async function roundTrip(matteFinesse) {
  const xml = await generateDRX({ matteFinesse }, { label: 'matte-rt' });
  const parsed = await parseDRXContent(xml);
  for (const node of parsed.nodes) {
    for (const corrector of node.correctors) {
      if (corrector.type !== 9) continue;
      const out = extractMatteFinesse(corrector.parameters);
      if (out) return out;
    }
  }
  throw new Error('roundTrip: no Type 9 matte corrector found');
}

test('round-trip: denoise + cleanBlack via real generator', async () => {
  const input = { denoise: 15, cleanBlack: 30 };
  const out = await roundTrip(input);
  assert.ok(close(out.denoise, 15), `denoise: ${out.denoise}`);
  assert.ok(close(out.cleanBlack, 30), `cleanBlack: ${out.cleanBlack}`);
});

test('round-trip: all 12 matte params via real generator', async () => {
  const input = {
    denoise: 12, blackClip: 8, whiteClip: 92, inOutRatio: 50,
    cleanBlack: 25, cleanWhite: 35, morphRadius: 4,
    preFilter: 6, postFilter: 10,
    shadow: 22, midtone: 48, highlight: 78,
  };
  const out = await roundTrip(input);
  for (const [k, v] of Object.entries(input)) {
    assert.ok(close(out[k], v), `${k}: got ${out[k]}, expected ${v}`);
  }
});
