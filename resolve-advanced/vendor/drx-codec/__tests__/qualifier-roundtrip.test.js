/**
 * P1.3 — extractQualifier tests.
 *
 * Two test strategies coexist:
 *
 * 1. Synthesized inputs (tests 1-14 below): construct parameter lists
 *    matching what buildQualifierParams WOULD emit and run
 *    extractQualifier on them. Exercises edge cases the generator
 *    doesn't expose (BigInt values, duplicate hue params, etc).
 *
 * 2. Real round-trip (tests at the bottom, "generate→parse→extract"):
 *    SESSION 25 wired buildQualifierParams into createNode, so
 *    generateDRX({qualifier:...}) now actually emits a Type 2
 *    corrector. These tests round-trip through real generator + parser.
 *
 * Both strategies kept because synthesized is faster + covers BigInt
 * paths the generator doesn't currently produce; round-trip is the
 * ground-truth wire-format proof.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const drxParams = require('../../drx-parameters');
const { extractQualifier, _internals } = require('../extract-qualifier');
const { generateDRX } = require('../drx-generator');
const { parseDRXContent } = require('../drx-parser');

const { HSL_QUALIFIER } = drxParams;

// Build the parameter list that buildQualifierParams WOULD emit for a
// given UI input. Mirrors lines 2367-2395 of drx-generator.js exactly.
function synthesizeQualifierParams(q) {
  const params = [];
  const add = (id, ui) => {
    if (ui !== undefined) params.push({ id, value: ui / 100, name: 'q' });
  };
  add(HSL_QUALIFIER.HUE_CENTER, q.hueCenter);
  add(HSL_QUALIFIER.HUE_WIDTH, q.hueWidth);
  add(
    HSL_QUALIFIER.HUE_SYM,
    q.hueSymmetry !== undefined ? q.hueSymmetry : (q.hueCenter !== undefined ? 50 : undefined),
  );
  add(HSL_QUALIFIER.HUE_SOFT, q.hueSoft);
  add(HSL_QUALIFIER.SAT_HIGH, q.satHigh);
  add(HSL_QUALIFIER.SAT_LOW, q.satLow);
  add(HSL_QUALIFIER.SAT_HIGH_SOFT, q.satHighSoft);
  add(HSL_QUALIFIER.SAT_LOW_SOFT, q.satLowSoft);
  add(HSL_QUALIFIER.LUM_HIGH, q.lumHigh);
  add(HSL_QUALIFIER.LUM_LOW, q.lumLow);
  add(HSL_QUALIFIER.LUM_HIGH_SOFT, q.lumHighSoft);
  add(HSL_QUALIFIER.LUM_LOW_SOFT, q.lumLowSoft);
  if (q.hueWidth !== undefined) add(HSL_QUALIFIER.HUE_WIDTH_DUP, q.hueWidth);
  if (q.hueSoft !== undefined) add(HSL_QUALIFIER.HUE_SOFT_DUP, q.hueSoft);
  if (params.length > 0) {
    params.push({ id: HSL_QUALIFIER.MODE_FLAG, value: 4, name: 'modeFlag' });
    params.push({ id: HSL_QUALIFIER.QUALIFIER_MODE, value: 0, name: 'qualifierMode' });
  }
  return params;
}

const TOL = 1e-4;

function close(a, b) {
  return Math.abs(a - b) < TOL;
}

test('extractQualifier: hue-only selection (8-config 1/8)', () => {
  const input = { hueCenter: 30, hueWidth: 20 };
  const params = synthesizeQualifierParams(input);
  const out = extractQualifier(params);
  assert.ok(out, 'should return non-null');
  assert.ok(close(out.hueCenter, 30));
  assert.ok(close(out.hueWidth, 20));
  // Default hueSymmetry inserted by generator
  assert.ok(close(out.hueSymmetry, 50));
  // Mode flags surface
  assert.equal(out.modeFlag, 4);
  assert.equal(out.mode, 0);
});

test('extractQualifier: saturation-only selection (2/8)', () => {
  const input = { satLow: 25, satHigh: 75 };
  const out = extractQualifier(synthesizeQualifierParams(input));
  assert.ok(close(out.satLow, 25));
  assert.ok(close(out.satHigh, 75));
  assert.equal(out.hueCenter, undefined);
});

test('extractQualifier: luminance-only selection (3/8)', () => {
  const input = { lumLow: 30, lumHigh: 80 };
  const out = extractQualifier(synthesizeQualifierParams(input));
  assert.ok(close(out.lumLow, 30));
  assert.ok(close(out.lumHigh, 80));
});

test('extractQualifier: all three axes bounded (4/8)', () => {
  const input = {
    hueCenter: 45, hueWidth: 30,
    satLow: 20, satHigh: 80,
    lumLow: 15, lumHigh: 85,
  };
  const out = extractQualifier(synthesizeQualifierParams(input));
  for (const [k, expected] of Object.entries(input)) {
    assert.ok(close(out[k], expected), `${k}: got ${out[k]}, expected ${expected}`);
  }
});

test('extractQualifier: with softness on all axes (5/8)', () => {
  const input = {
    hueCenter: 30, hueWidth: 20, hueSoft: 10,
    satLow: 25, satHigh: 75, satLowSoft: 5, satHighSoft: 5,
    lumLow: 30, lumHigh: 70, lumLowSoft: 8, lumHighSoft: 8,
  };
  const out = extractQualifier(synthesizeQualifierParams(input));
  for (const [k, expected] of Object.entries(input)) {
    assert.ok(close(out[k], expected), `${k}: got ${out[k]}, expected ${expected}`);
  }
});

test('extractQualifier: extreme hue near 0 (6/8)', () => {
  const input = { hueCenter: 0, hueWidth: 10 };
  const out = extractQualifier(synthesizeQualifierParams(input));
  assert.ok(close(out.hueCenter, 0));
  assert.ok(close(out.hueWidth, 10));
});

test('extractQualifier: extreme hue near 100 (7/8)', () => {
  const input = { hueCenter: 100, hueWidth: 10 };
  const out = extractQualifier(synthesizeQualifierParams(input));
  assert.ok(close(out.hueCenter, 100));
});

test('extractQualifier: full-range cover-everything (8/8)', () => {
  const input = {
    hueCenter: 50, hueWidth: 100, hueSoft: 50, hueSymmetry: 50,
    satLow: 0, satHigh: 100, satLowSoft: 0, satHighSoft: 0,
    lumLow: 0, lumHigh: 100, lumLowSoft: 0, lumHighSoft: 0,
  };
  const out = extractQualifier(synthesizeQualifierParams(input));
  for (const [k, expected] of Object.entries(input)) {
    assert.ok(close(out[k], expected), `${k}: got ${out[k]}, expected ${expected}`);
  }
});

test('extractQualifier: returns null when no qualifier params present', () => {
  assert.equal(extractQualifier([
    { id: 100663320, value: 0.5, name: 'lift.r' },
  ]), null);
});

test('extractQualifier: handles malformed input', () => {
  assert.equal(extractQualifier(null), null);
  assert.equal(extractQualifier(undefined), null);
  assert.equal(extractQualifier([]), null);
});

test('extractQualifier: handles BigInt varint values', () => {
  // Parser surfaces varints as BigInt in some code paths.
  const params = [
    { id: HSL_QUALIFIER.MODE_FLAG, value: 4n, name: 'modeFlag' },
    { id: HSL_QUALIFIER.QUALIFIER_MODE, value: 0n, name: 'qualifierMode' },
  ];
  const out = extractQualifier(params);
  assert.equal(out.modeFlag, 4);
  assert.equal(out.mode, 0);
});

test('extractQualifier: duplicate hue params do not override canonical', () => {
  // HUE_WIDTH_DUP appears AFTER HUE_WIDTH in the generator's emission;
  // canonical should win. Test with a deliberately wrong dup value.
  const params = [
    { id: HSL_QUALIFIER.HUE_WIDTH, value: 0.25, name: 'hueWidth' },          // 25
    { id: HSL_QUALIFIER.HUE_WIDTH_DUP, value: 0.99, name: 'hueWidthDup' },   // wrong
  ];
  const out = extractQualifier(params);
  assert.ok(close(out.hueWidth, 25), `hueWidth canonical should win: got ${out.hueWidth}`);
});

test('internals.drxToUi: BigInt input handled', () => {
  assert.equal(_internals.drxToUi(0.5), 50);
  assert.equal(_internals.drxToUi(0.25), 25);
  // BigInt should be coerced
  assert.equal(_internals.drxToUi(BigInt(0)), 0);
});

test('internals.varintToNumber: handles BigInt and number', () => {
  assert.equal(_internals.varintToNumber(4n), 4);
  assert.equal(_internals.varintToNumber(4), 4);
  assert.equal(_internals.varintToNumber('foo'), 0);
});

// ─── Real round-trip via generateDRX (Session 25 wiring) ─────────────────

async function roundTrip(qualifier) {
  const xml = await generateDRX({ qualifier }, { label: 'qual-rt' });
  const parsed = await parseDRXContent(xml);
  for (const node of parsed.nodes) {
    for (const corrector of node.correctors) {
      if (corrector.type !== 2) continue;
      const out = extractQualifier(corrector.parameters);
      if (out) return out;
    }
  }
  throw new Error('roundTrip: no Type 2 qualifier corrector found');
}

test('round-trip: hue + sat + lum bounded survives generate→parse→extract', async () => {
  const input = { hueCenter: 30, hueWidth: 25, satLow: 20, satHigh: 80, lumLow: 10, lumHigh: 90 };
  const out = await roundTrip(input);
  for (const [k, v] of Object.entries(input)) {
    assert.ok(close(out[k], v), `${k}: got ${out[k]}, expected ${v}`);
  }
});

test('round-trip: full spec with softness on all axes', async () => {
  const input = {
    hueCenter: 45, hueWidth: 30, hueSoft: 15,
    satLow: 25, satHigh: 75, satLowSoft: 8, satHighSoft: 8,
    lumLow: 20, lumHigh: 80, lumLowSoft: 10, lumHighSoft: 10,
  };
  const out = await roundTrip(input);
  for (const [k, v] of Object.entries(input)) {
    assert.ok(close(out[k], v), `${k}: got ${out[k]}, expected ${v}`);
  }
});
