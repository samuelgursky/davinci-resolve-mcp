/**
 * P1.1 — Round-trip test for extractCustomCurves.
 *
 * Strategy:
 *   1. Use generateDRX to emit a DRX with known customCurves for one or
 *      more channels.
 *   2. Parse the DRX via drx-parser.parseDRXContent.
 *   3. Locate the Primary corrector (Type 1) carrying CUSTOM_CURVES.
 *   4. Call extractCustomCurves(corrector.parameters).
 *   5. Assert each decoded point is within 0.001 of the input x and y.
 *
 * No Resolve session required; uses the generator's own output as the
 * test fixture.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const { generateDRX } = require('../drx-generator');
const { parseDRXContent } = require('../drx-parser');
const { extractCustomCurves, _internals } = require('../extract-custom-curves');

const TOL = 0.002; // ~2/1023 — generator scales by 1023 with float32 noise

function pointsClose(a, b) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (Math.abs(a[i].x - b[i].x) > TOL) return false;
    if (Math.abs(a[i].y - b[i].y) > TOL) return false;
  }
  return true;
}

async function roundTrip(customCurves) {
  const drxXml = await generateDRX({ customCurves }, { label: 'curve-test' });
  const parsed = await parseDRXContent(drxXml);
  // Find the Primary corrector (type 1) on the first node that has curves
  // present. The generator emits one node per call.
  for (const node of parsed.nodes) {
    for (const corrector of node.correctors) {
      if (corrector.type !== 1) continue;
      const curves = extractCustomCurves(corrector.parameters);
      if (curves) return curves;
    }
  }
  throw new Error('round-trip: no curves found in any corrector');
}

test('extractCustomCurves: 2-point Y curve round-trips within tolerance', async () => {
  const input = { y: [{ x: 0.3, y: 0.4 }, { x: 0.7, y: 0.8 }] };
  const out = await roundTrip(input);
  assert.ok(out, 'should return non-null curves');
  assert.ok(pointsClose(out.y, input.y), `Y mismatch: got ${JSON.stringify(out.y)}`);
});

test('extractCustomCurves: per-channel sweep — R/G/B independent curves', async () => {
  const input = {
    r: [{ x: 0.2, y: 0.5 }],
    g: [{ x: 0.5, y: 0.3 }],
    b: [{ x: 0.8, y: 0.6 }],
  };
  const out = await roundTrip(input);
  assert.ok(out);
  assert.ok(pointsClose(out.r, input.r), `R mismatch: ${JSON.stringify(out.r)}`);
  assert.ok(pointsClose(out.g, input.g), `G mismatch: ${JSON.stringify(out.g)}`);
  assert.ok(pointsClose(out.b, input.b), `B mismatch: ${JSON.stringify(out.b)}`);
});

test('extractCustomCurves: multi-point Y curve (4 control points)', async () => {
  const input = {
    y: [
      { x: 0.1, y: 0.05 },
      { x: 0.3, y: 0.25 },
      { x: 0.6, y: 0.7 },
      { x: 0.9, y: 0.95 },
    ],
  };
  const out = await roundTrip(input);
  assert.ok(pointsClose(out.y, input.y), `4-point Y mismatch: ${JSON.stringify(out.y)}`);
});

test('extractCustomCurves: channels not in input return as empty arrays', async () => {
  const input = { y: [{ x: 0.5, y: 0.5 }] };
  const out = await roundTrip(input);
  assert.ok(out);
  assert.deepEqual(out.r, []);
  assert.deepEqual(out.g, []);
  assert.deepEqual(out.b, []);
  assert.ok(pointsClose(out.y, input.y));
});

test('extractCustomCurves: 10 hand-picked specs all round-trip', async () => {
  const cases = [
    { y: [{ x: 0.1, y: 0.05 }] },                            // crushed shadows
    { y: [{ x: 0.9, y: 0.7 }] },                             // rolloff highlights
    { y: [{ x: 0.5, y: 0.5 }] },                             // mid point identity
    { y: [{ x: 0.25, y: 0.4 }, { x: 0.75, y: 0.6 }] },       // S-curve
    { r: [{ x: 0.3, y: 0.5 }] },                             // red lift
    { g: [{ x: 0.5, y: 0.45 }] },                            // green pull-down
    { b: [{ x: 0.4, y: 0.35 }] },                            // blue cool shift
    { r: [{ x: 0.2, y: 0.5 }], g: [{ x: 0.8, y: 0.7 }] },    // two channels
    { y: [{ x: 0.3, y: 0.2 }, { x: 0.7, y: 0.85 }] },        // separate Y
    {
      y: [{ x: 0.5, y: 0.5 }],
      r: [{ x: 0.5, y: 0.4 }],
      g: [{ x: 0.5, y: 0.45 }],
      b: [{ x: 0.5, y: 0.55 }],
    },                                                         // all four channels
  ];
  for (let i = 0; i < cases.length; i++) {
    const input = cases[i];
    const out = await roundTrip(input);
    assert.ok(out, `case ${i}: should return non-null`);
    for (const ch of ['y', 'r', 'g', 'b']) {
      if (!input[ch] || input[ch].length === 0) {
        assert.deepEqual(out[ch], [], `case ${i} channel ${ch}: should be empty`);
      } else {
        assert.ok(
          pointsClose(out[ch], input[ch]),
          `case ${i} channel ${ch}: got ${JSON.stringify(out[ch])} expected ${JSON.stringify(input[ch])}`,
        );
      }
    }
  }
});

test('extractCustomCurves: returns null when no curves present', () => {
  // Run against a parameter list that has no spline IDs.
  const out = extractCustomCurves([
    { id: 100663320, value: 0.5, name: 'lift.r' },
  ]);
  assert.equal(out, null);
});

test('extractCustomCurves: handles malformed parameters gracefully', () => {
  assert.equal(extractCustomCurves(null), null);
  assert.equal(extractCustomCurves(undefined), null);
  assert.equal(extractCustomCurves([]), null);
});

test('internals.decodeSpline: empty buffer returns []', () => {
  assert.deepEqual(_internals.decodeSpline(Buffer.alloc(0)), []);
});

test('internals.decodeSpline: handles non-buffer input gracefully', () => {
  assert.deepEqual(_internals.decodeSpline(null), []);
  assert.deepEqual(_internals.decodeSpline('not a buffer'), []);
});
