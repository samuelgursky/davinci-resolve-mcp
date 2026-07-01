/**
 * P1.2 — Round-trip test for extractHSLCurves.
 *
 * HSL curves use raw float space (NOT 0-1023 scaled). X is hue fraction
 * with wrap-around (~-0.08 to ~1.08), Y is 0.5-centered (0.5 = neutral).
 * Tests assert exact-equal points within float32 precision (~1e-7).
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const { generateDRX } = require('../drx-generator');
const { parseDRXContent } = require('../drx-parser');
const { extractHSLCurves, _internals } = require('../extract-hsl-curves');

const TOL = 1e-5; // float32 precision is ~1e-7; allow a small buffer

function pointsClose(a, b) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (Math.abs(a[i].x - b[i].x) > TOL) return false;
    if (Math.abs(a[i].y - b[i].y) > TOL) return false;
  }
  return true;
}

async function roundTrip(hslCurves) {
  const drxXml = await generateDRX({ hslCurves }, { label: 'hsl-test' });
  const parsed = await parseDRXContent(drxXml);
  for (const node of parsed.nodes) {
    for (const corrector of node.correctors) {
      const result = extractHSLCurves(corrector.parameters);
      if (result) return result;
    }
  }
  throw new Error('roundTrip: no HSL curves found in any corrector');
}

test('extractHSLCurves: hueVsSat round-trips at raw float precision', async () => {
  const input = {
    hueVsSat: [
      { x: 0.0, y: 0.5 },
      { x: 0.3, y: 0.7 },
      { x: 0.6, y: 0.4 },
      { x: 1.0, y: 0.5 },
    ],
  };
  const out = await roundTrip(input);
  assert.ok(out, 'result should be non-null');
  assert.ok(out.hueVsSat, 'hueVsSat should be present');
  assert.ok(pointsClose(out.hueVsSat, input.hueVsSat),
    `mismatch: got ${JSON.stringify(out.hueVsSat)}`);
});

test('extractHSLCurves: hueVsHue independent from other types', async () => {
  const input = {
    hueVsHue: [{ x: 0.2, y: 0.55 }, { x: 0.5, y: 0.5 }, { x: 0.8, y: 0.45 }],
  };
  const out = await roundTrip(input);
  assert.ok(out.hueVsHue);
  assert.ok(pointsClose(out.hueVsHue, input.hueVsHue));
  assert.equal(out.hueVsSat, undefined);
  assert.equal(out.hueVsLum, undefined);
});

test('extractHSLCurves: all 6 curve types in one DRX', async () => {
  const input = {
    hueVsHue: [{ x: 0.1, y: 0.51 }],
    hueVsSat: [{ x: 0.2, y: 0.52 }],
    hueVsLum: [{ x: 0.3, y: 0.53 }],
    lumVsSat: [{ x: 0.4, y: 0.54 }],
    satVsSat: [{ x: 0.5, y: 0.55 }],
    satVsLum: [{ x: 0.6, y: 0.56 }],
  };
  const out = await roundTrip(input);
  for (const k of Object.keys(input)) {
    assert.ok(out[k], `${k} missing in result`);
    assert.ok(pointsClose(out[k], input[k]),
      `${k} mismatch: ${JSON.stringify(out[k])}`);
  }
});

test('extractHSLCurves: wrap-around X values pass through', async () => {
  // Resolve allows X values outside [0, 1] for hue continuity.
  const input = {
    hueVsSat: [
      { x: -0.08, y: 0.5 },
      { x: 0.5, y: 0.6 },
      { x: 1.08, y: 0.5 },
    ],
  };
  const out = await roundTrip(input);
  assert.ok(pointsClose(out.hueVsSat, input.hueVsSat),
    `wrap-around mismatch: ${JSON.stringify(out.hueVsSat)}`);
});

test('extractHSLCurves: returns null when no HSL params present', () => {
  assert.equal(extractHSLCurves([
    { id: 100663320, value: 0.5, name: 'lift.r' },
  ]), null);
});

test('extractHSLCurves: handles malformed input gracefully', () => {
  assert.equal(extractHSLCurves(null), null);
  assert.equal(extractHSLCurves(undefined), null);
  assert.equal(extractHSLCurves([]), null);
});

test('internals.decodeHSLSpline: empty buffer returns []', () => {
  assert.deepEqual(_internals.decodeHSLSpline(Buffer.alloc(0)), []);
});

test('internals.decodeHSLSpline: non-buffer non-object returns []', () => {
  assert.deepEqual(_internals.decodeHSLSpline(null), []);
  assert.deepEqual(_internals.decodeHSLSpline('foo'), []);
  assert.deepEqual(_internals.decodeHSLSpline(42), []);
});
