'use strict';

/**
 * Burn-in-free source-frame location (compare/locate). Fixture-free: a synthetic
 * "source" whose content drifts frame-to-frame stands in for footage; the injected
 * conformAt returns the source frame's grayscale. The locator must find the frame
 * whose content matches the reference, score its confidence, and flag ambiguity.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const { locateByContent } = require('../compare/locate');

const W = 80;
const H = 60;

// A frame whose pattern shifts continuously with the frame number — so each frame
// has a distinct, monotonically-drifting appearance (a panning/tilting shot).
function frameAt(n) {
  const d = new Float64Array(W * H);
  const phase = n * 0.06;
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      d[y * W + x] = 0.5 +
        0.3 * Math.sin(x * 0.2 + phase) +
        0.15 * Math.cos(y * 0.15 - phase * 0.7);
    }
  }
  return d;
}

test('locates the matching source frame by content (no burn-in)', async () => {
  const truth = 137;
  const ref = frameAt(truth);
  const conformAt = async (f) => frameAt(f);
  const r = await locateByContent(ref, conformAt, 0, 300, { coarseStep: 8 });
  assert.equal(r.frame, truth);
  assert.equal(r.confidence, 'high');
  assert.ok(r.evals < 100, `expected sub-linear evals over 300 frames, got ${r.evals}`);
});

test('a darker/brighter grade still matches (structure is luma-invariant)', async () => {
  const truth = 88;
  const ref = frameAt(truth);
  // The conform is a "temped grade": scaled down + lifted (brightness/contrast shift).
  const conformAt = async (f) => {
    const g = frameAt(f);
    const out = new Float64Array(g.length);
    for (let i = 0; i < g.length; i++) out[i] = g[i] * 0.4 + 0.1;
    return out;
  };
  const r = await locateByContent(ref, conformAt, 0, 200, { coarseStep: 8 });
  assert.equal(r.frame, truth);
  assert.equal(r.confidence, 'high');
});

test('a flat/ambiguous source yields low confidence (route to a wipe)', async () => {
  const ref = frameAt(50);
  // Every candidate is the same flat gray -> no distinguishing peak.
  const conformAt = async () => new Float64Array(W * H).fill(0.5);
  const r = await locateByContent(ref, conformAt, 0, 100, { coarseStep: 8 });
  assert.notEqual(r.confidence, 'high');
});
