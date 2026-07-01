'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { findScale } = require('../compare/metrics');

// a centered square (high structure) on a flat field
function square(w, h, half) {
  const d = new Float64Array(w * h);
  const cx = (w - 1) / 2;
  const cy = (h - 1) / 2;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      d[y * w + x] = Math.abs(x - cx) < half && Math.abs(y - cy) < half ? 1 : 0.15;
    }
  }
  return d;
}

test('findScale: identical frames -> residual ~1.0', () => {
  const a = square(100, 100, 30);
  const r = findScale(a, a, null, 100, 100);
  assert.ok(Math.abs(r.residual - 1.0) < 0.01, `got ${r.residual}`);
});

test('findScale: a frame ~6% too small -> residual ~1.06 (enlarge to match)', () => {
  const a = square(120, 120, 36); // reference
  const b = square(120, 120, 36 / 1.06); // conformed, ~6% too small
  const r = findScale(a, b, null, 120, 120);
  assert.ok(Math.abs(r.residual - 1.06) < 0.025, `got ${r.residual}`);
  assert.ok(r.score > r.atOneScore, 'best scale should beat the zero-scale score');
});

test('findScale: a frame too big -> residual < 1 (shrink to match)', () => {
  const a = square(120, 120, 30);
  const b = square(120, 120, 30 * 1.1); // 10% too big
  const r = findScale(a, b, null, 120, 120);
  assert.ok(r.residual < 1.0, `got ${r.residual}`);
});
