'use strict';

/**
 * Fixture-free checks for the fast (coarse→fine) search paths in compare/metrics:
 *  - findOffset's pyramid path returns the SAME peak as an exhaustive brute force,
 *  - coarseToFinePeak finds a 1D peak with far fewer evaluations than a linear scan.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const Mx = require('../compare/metrics');

const W = 160;
const H = 120;

// A textured image (not separable, so shifts are unambiguous): mixed frequencies.
function texture(w, h) {
  const d = new Float64Array(w * h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      d[y * w + x] = 0.5 +
        0.25 * Math.sin(x * 0.21 + y * 0.07) +
        0.15 * Math.cos(x * 0.05 - y * 0.17) +
        0.08 * Math.sin((x + y) * 0.33);
    }
  }
  return d;
}

// Shift src by (sx, sy) into a w×h buffer (out-of-bounds -> 0).
function shifted(src, w, h, sx, sy) {
  const d = new Float64Array(w * h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const ox = x - sx;
      const oy = y - sy;
      d[y * w + x] = ox >= 0 && ox < w && oy >= 0 && oy < h ? src[oy * w + ox] : 0;
    }
  }
  return d;
}

test('findOffset pyramid path equals exhaustive brute force', () => {
  const a = texture(W, H);
  for (const [sx, sy] of [[20, -14], [-31, 25], [0, 0], [44, 7]]) {
    const b = shifted(a, W, H, sx, sy);
    const maxShift = 50; // > 16 -> exercises the pyramid path
    // Reference: exhaustive window search at full res.
    const brute = Mx.searchShiftWindow(a, b, null, W, H, -maxShift, maxShift, -maxShift, maxShift);
    const fast = Mx.findOffset(a, b, null, W, H, maxShift);
    assert.equal(fast.dx, brute.dx, `dx mismatch for shift (${sx},${sy})`);
    assert.equal(fast.dy, brute.dy, `dy mismatch for shift (${sx},${sy})`);
    // structureAtShift re-aligns b by (dx,dy), so b = a shifted by (sx,sy) peaks at (-sx,-sy).
    assert.equal(fast.dx, -sx || 0); // || 0 normalizes the -0 case
    assert.equal(fast.dy, -sy || 0);
  }
});

test('small maxShift stays exact brute force (unchanged behaviour)', () => {
  const a = texture(W, H);
  const b = shifted(a, W, H, 5, -3);
  const fast = Mx.findOffset(a, b, null, W, H, 12);
  const brute = Mx.searchShiftWindow(a, b, null, W, H, -12, 12, -12, 12);
  assert.equal(fast.dx, brute.dx);
  assert.equal(fast.dy, brute.dy);
  assert.equal(fast.dx, -5);
  assert.equal(fast.dy, 3);
});

test('coarseToFinePeak finds the peak with fewer evals than a linear scan', async () => {
  const lo = 0;
  const hi = 300;
  const peak = 211;
  let calls = 0;
  const scoreAt = (x) => { calls += 1; return -Math.abs(x - peak); }; // unimodal
  const r = await Mx.coarseToFinePeak(scoreAt, lo, hi, 8);
  assert.equal(r.x, peak);
  assert.ok(r.evals < hi - lo, `expected sub-linear evals, got ${r.evals}`);
  assert.ok(calls <= 70, `expected ~50 evals, got ${calls}`);
});

test('downsample averages and halves/quarters dimensions', () => {
  const a = texture(W, H);
  const d = Mx.downsample(a, W, H, 4);
  assert.equal(d.width, 40);
  assert.equal(d.height, 30);
  // A flat region averages to itself.
  const flat = new Float64Array(16).fill(0.5);
  const df = Mx.downsample(flat, 4, 4, 2);
  for (const v of df.data) assert.ok(Math.abs(v - 0.5) < 1e-9);
});
