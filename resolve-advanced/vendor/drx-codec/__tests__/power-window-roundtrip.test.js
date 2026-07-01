/**
 * P1.4 — extractPowerWindow tests.
 *
 * 2026-07-01: updated to the TRUE live-calibrated transform scales (multi-point
 * fit 2026-06-22; see test/power-window-transform-calibration.test.mjs):
 *   rotate = −UI°/180 · size = 1+(UI−50)×0.08 · aspect = (50−UI)/50 ·
 *   pan/tilt = (UI−50)/50 × 4096 · soft = UI × 16 (gradient soft = UI × 100).
 * The generator now writes these scales (registry window ranges were widened to
 * the real DRX spans, removing the old [-1,1] clamp), so generate→parse→extract
 * round-trips UI-exact AND matches what live Resolve stores.
 *
 * Synthesized-input tests exercise edge cases (Circle/Linear collision,
 * SOFT_REF vs SOFT_1 reconciliation); real round-trips live at the bottom.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const drxParams = require('../../drx-parameters');
const { extractPowerWindow, _internals } = require('../extract-power-window');
const { generateDRX } = require('../drx-generator');
const { parseDRXContent } = require('../drx-parser');

const { POWER_WINDOWS, GRADIENT_WINDOW } = drxParams;
const PW = POWER_WINDOWS;
const GW = GRADIENT_WINDOW;

// Mirrors buildWindowParams' TRUE scales. Builds the flattened param list
// (ct4 transform + ct3 mask + ct65554 gradient) the extractor sees.
function synthesize(w) {
  const params = [];
  const add = (id, value) => params.push({ id, value, name: 'pw' });
  const isGradient = w.type === 5;
  if (isGradient) {
    add(GW.TYPE, { F2: 2 });
    if (w.rotate !== undefined && w.rotate !== 0) add(GW.ROTATION, -w.rotate / 180);
    if (w.pan !== undefined && w.pan !== 50) add(GW.HANDLE_1_POS, ((w.pan - 50) / 50) * 4096);
    if (w.tilt !== undefined && w.tilt !== 50) add(GW.HANDLE_2_POS, ((w.tilt - 50) / 50) * 4096);
    if (w.soft1 !== undefined && w.soft1 !== 0) add(GW.SOFTNESS, w.soft1 * 100);
    return params;
  }
  if (w.type !== undefined) add(PW.WINDOW_TYPE, { F2: 2 }); // constant varint flag
  if (w.rotate !== undefined && w.rotate !== 0) add(PW.ROTATE, -w.rotate / 180);
  if (w.size !== undefined && w.size !== 50) add(PW.SIZE, 1 + (w.size - 50) * 0.08);
  if (w.aspect !== undefined && w.aspect !== 50) add(PW.ASPECT, (50 - w.aspect) / 50);
  if (w.pan !== undefined && w.pan !== 50) add(PW.PAN, ((w.pan - 50) / 50) * 4096);
  if (w.tilt !== undefined && w.tilt !== 50) add(PW.TILT, ((w.tilt - 50) / 50) * 4096);
  if (w.type === 2) {
    if (w.soft1 !== undefined && w.soft1 !== 0) add(PW.SOFT_1, w.soft1 * 16);
    if (w.soft2 !== undefined && w.soft2 !== 0) add(PW.SOFT_2, w.soft2 * 16);
    if (w.soft3 !== undefined && w.soft3 !== 0) add(PW.SOFT_3, w.soft3 * 16);
    if (w.soft4 !== undefined && w.soft4 !== 0) add(PW.SOFT_4, w.soft4 * 16);
  } else if (w.soft1 !== undefined && w.soft1 !== 0) {
    add(PW.SOFT_REF, w.soft1 * 16);
  }
  return params;
}

const TOL = 1e-3;
function close(a, b) {
  return Math.abs(a - b) < TOL;
}

test('extractPowerWindow: circle window — type round-trips', () => {
  const out = extractPowerWindow(synthesize({ type: 1 }));
  assert.ok(out);
  assert.equal(out.type, 1, 'wire flag 2 with no linear mask → Circle');
});

test('extractPowerWindow: linear window — disambiguated by linear-only softness params', () => {
  // The wire type flag is a constant 2 for BOTH circle and linear windows.
  // Without sibling params, the decoder defaults to Circle. With SOFT_2-4 (only
  // emitted by linear masks), Linear is recognized.
  const minimal = extractPowerWindow(synthesize({ type: 2 }));
  assert.equal(minimal.type, 1, 'pure flag alone is ambiguous; defaults to Circle');

  const withSoftness = extractPowerWindow(synthesize({ type: 2, soft2: 8 }));
  assert.equal(withSoftness.type, 2, 'SOFT_2 disambiguates → Linear');
});

test('extractPowerWindow: gradient window — type 5 via 0x08F0xxxx params', () => {
  const out = extractPowerWindow(synthesize({ type: 5, soft1: 10 }));
  assert.equal(out.type, 5);
  // Gradient softness uses ×100 scale, not ×16.
  assert.ok(close(out.soft1, 10), `expected soft1=10, got ${out.soft1}`);
});

test('extractPowerWindow: SIZE round-trips through 1+(UI−50)×0.08 encoding', () => {
  const out = extractPowerWindow(synthesize({ type: 1, size: 75 }));
  assert.ok(close(out.size, 75), `expected size=75, got ${out.size}`);
});

test('extractPowerWindow: ASPECT round-trips through (50−UI)/50 encoding', () => {
  const out = extractPowerWindow(synthesize({ type: 1, aspect: 75 }));
  assert.ok(close(out.aspect, 75), `expected aspect=75, got ${out.aspect}`);
});

test('extractPowerWindow: PAN/TILT round-trip through ±4096 pixel scaling', () => {
  const out = extractPowerWindow(synthesize({ type: 1, pan: 60, tilt: 40 }));
  assert.ok(close(out.pan, 60), `expected pan=60, got ${out.pan}`);
  assert.ok(close(out.tilt, 40), `expected tilt=40, got ${out.tilt}`);
});

test('extractPowerWindow: ROTATE round-trips through −UI/180 encoding', () => {
  const out = extractPowerWindow(synthesize({ type: 1, rotate: 45 }));
  assert.ok(close(out.rotate, 45));
});

test('extractPowerWindow: linear with all 4 softness values', () => {
  const input = { type: 2, soft1: 8, soft2: 12, soft3: 6, soft4: 4 };
  const out = extractPowerWindow(synthesize(input));
  assert.ok(close(out.soft1, 8), `soft1: got ${out.soft1}`);
  assert.ok(close(out.soft2, 12), `soft2: got ${out.soft2}`);
  assert.ok(close(out.soft3, 6), `soft3: got ${out.soft3}`);
  assert.ok(close(out.soft4, 4), `soft4: got ${out.soft4}`);
});

test('extractPowerWindow: SOFT_REF and SOFT_1 reconcile — prefer SOFT_REF', () => {
  const params = [
    { id: PW.WINDOW_TYPE, value: { F2: 2 }, name: 'type' },
    { id: PW.SOFT_REF, value: 16 * 10, name: 'softRef' },  // UI 10
    { id: PW.SOFT_1, value: 16 * 99, name: 'soft1' },      // wrong value to detect override
  ];
  const out = extractPowerWindow(params);
  assert.ok(close(out.soft1, 10), `SOFT_REF should win: got ${out.soft1}`);
});

test('extractPowerWindow: SOFT_1 alone (no SOFT_REF) surfaces', () => {
  const params = [
    { id: PW.WINDOW_TYPE, value: { F2: 2 }, name: 'type' },
    { id: PW.SOFT_1, value: 16 * 7, name: 'soft1' },
  ];
  const out = extractPowerWindow(params);
  assert.ok(close(out.soft1, 7));
});

test('extractPowerWindow: full linear spec round-trips', () => {
  const input = {
    type: 2,
    rotate: 15,
    size: 60,
    aspect: 80,
    pan: 55,
    tilt: 45,
    soft1: 10,
    soft2: 5,
    soft3: 3,
    soft4: 2,
  };
  const out = extractPowerWindow(synthesize(input));
  for (const [k, expected] of Object.entries(input)) {
    assert.ok(close(out[k], expected), `${k}: got ${out[k]} expected ${expected}`);
  }
});

test('extractPowerWindow: returns null on empty/non-window params', () => {
  assert.equal(extractPowerWindow([
    { id: 100663320, value: 0.5, name: 'lift.r' },
  ]), null);
});

test('extractPowerWindow: handles malformed input', () => {
  assert.equal(extractPowerWindow(null), null);
  assert.equal(extractPowerWindow(undefined), null);
  assert.equal(extractPowerWindow([]), null);
});

test('extractPowerWindow: handles BigInt varint type', () => {
  const out = extractPowerWindow([
    { id: PW.WINDOW_TYPE, value: 2n, name: 'type' },
  ]);
  assert.equal(out.type, 1, 'BigInt 2 → UI 1');
});

test('internals.drxToUiType: wire 2 → UI 1 (no linear softness) or UI 2 (with)', () => {
  assert.equal(_internals.drxToUiType(2), 1, 'default → Circle');
  assert.equal(_internals.drxToUiType(2, true), 2, 'with linear softness → Linear');
  assert.equal(_internals.drxToUiType(3), 3);
  assert.equal(_internals.drxToUiType(5), 5);
  assert.equal(_internals.drxToUiType(2n), 1);
});

test('internals.drxToSize: round-trips around UI 50 (neutral stored 1.0)', () => {
  assert.equal(_internals.drxToSize(1.0), 50);
  assert.ok(close(_internals.drxToSize(3.0), 75));
  assert.ok(close(_internals.drxToSize(-1.0), 25));
});

// ─── Real round-trip via generateDRX ─────────────────────────────────────

async function roundTrip(window) {
  const xml = await generateDRX({ window }, { label: 'win-rt' });
  const parsed = await parseDRXContent(xml);
  for (const node of parsed.nodes) {
    // Flatten across corrector blocks: ct4 transform + ct3 mask + ct65554 gradient.
    const params = (node.correctors || []).flatMap((c) => c.parameters || []);
    const out = extractPowerWindow(params);
    if (out) return out;
  }
  throw new Error('roundTrip: no window params found');
}

test('round-trip: circle window — full transform survives generate→parse→extract', async () => {
  // Same UI values as the live power-window-transform fixture (Size 75 / Aspect 30 /
  // Pan 35 / Tilt 88 / Rotate 49): the generator now stores the live-calibrated values.
  const input = { type: 1, rotate: 49, size: 75, aspect: 30, pan: 35, tilt: 88, soft1: 10 };
  const out = await roundTrip(input);
  assert.equal(out.type, 1);
  for (const k of ['rotate', 'size', 'aspect', 'pan', 'tilt', 'soft1']) {
    assert.ok(close(out[k], input[k]), `${k}: got ${out[k]} expected ${input[k]}`);
  }
});

test('round-trip: linear window — softness mask rides ct3', async () => {
  const input = { type: 2, soft1: 4.5, soft2: 6.25, soft3: 8.75, soft4: 11 };
  const out = await roundTrip(input);
  assert.equal(out.type, 2);
  for (const k of ['soft1', 'soft2', 'soft3', 'soft4']) {
    assert.ok(close(out[k], input[k]), `${k}: got ${out[k]} expected ${input[k]}`);
  }
});

test('round-trip: gradient window — ct65554 params', async () => {
  const input = { type: 5, pan: 81, tilt: 82, rotate: 83, soft1: 85, opacity: 84 };
  const out = await roundTrip(input);
  assert.equal(out.type, 5);
  for (const k of ['pan', 'tilt', 'rotate', 'soft1', 'opacity']) {
    assert.ok(close(out[k], input[k]), `${k}: got ${out[k]} expected ${input[k]}`);
  }
});
