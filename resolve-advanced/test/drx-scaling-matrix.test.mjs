// THOROUGH scaling-alignment matrix: drives real generate→parse for every primary control
// across multiple magnitudes/channels, asserting the DECODED DRX == UI × calibrated factor
// (space:'ui', the default) and == raw (space:'drx'). Factors calibrated live vs Resolve 19
// panel readback (2026-07): lift ×2, gamma ×4, gain ×1, offset ×0.04, saturation ÷50.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { drxTool } from '../server/tools/drx.mjs';

const EPS = 2e-3;
const call = (action, args) => drxTool.handler({ action, args });
async function roundtrip(gradeParams) {
  const gen = await call('generate', { gradeParams });
  const parsed = await call('parse', { content: gen.content || gen });
  return parsed.nodes[0].params;
}
const near = (a, b, msg) => assert.ok(Math.abs(a - b) <= EPS, `${msg}: got ${a}, want ${b}`);

// UI magnitudes to sweep per wheel channel, and the calibrated UI→DRX factor.
const WHEELS = [
  { name: 'lift', factor: 2, neutral: 0, uiVals: [-0.05, -0.02, 0.03] },
  { name: 'gamma', factor: 4, neutral: 0, uiVals: [-0.05, 0.05, 0.1] },
  { name: 'gain', factor: 1, neutral: 1, uiVals: [0.9, 0.95, 1.1] },
];

for (const w of WHEELS) {
  for (const ch of ['master', 'r', 'g', 'b']) {
    for (const ui of w.uiVals) {
      test(`ui-space ${w.name}.${ch}=${ui} → DRX ${ui}×${w.factor}`, async () => {
        const p = await roundtrip({ [w.name]: { [ch]: ui } });
        near(p[w.name][ch], ui * w.factor, `${w.name}.${ch}`);
      });
      test(`drx-space ${w.name}.${ch}=${ui} stays raw`, async () => {
        const p = await roundtrip({ space: 'drx', [w.name]: { [ch]: ui } });
        near(p[w.name][ch], ui, `${w.name}.${ch} raw`);
      });
    }
  }
}

// Offset (r/g/b only, panel-delta ×0.04)
for (const ch of ['r', 'g', 'b']) {
  for (const ui of [-1.0, 0.5, 1.0]) {
    test(`ui-space offset.${ch}=${ui} → DRX ${ui}×0.04`, async () => {
      const p = await roundtrip({ offset: { [ch]: ui } });
      near(p.offset[ch], ui * 0.04, `offset.${ch}`);
    });
  }
}

// Saturation: ui 0-100 (÷50) and drx raw-float both decode to the same stored value.
for (const [uiSat, drxFloat] of [[40, 0.8], [52, 1.04], [60, 1.2]]) {
  test(`ui-space saturation=${uiSat} → decoded ${drxFloat}`, async () => {
    const p = await roundtrip({ saturation: uiSat });
    near(p.saturation, drxFloat, 'sat ui');
  });
  test(`drx-space saturation=${drxFloat} → decoded ${drxFloat}`, async () => {
    const p = await roundtrip({ space: 'drx', saturation: drxFloat });
    near(p.saturation, drxFloat, 'sat drx');
  });
}

// 1:1 controls — verified live vs Resolve panel (2026-07): temperature 2000→2000, tint 20→20,
// contrast 1.2→1.200, pivot 0.5→0.500, midtoneDetail 30→30, colorBoost 25→25. No scaling factor,
// so 'ui' and 'drx' are identical (the normalizer leaves them untouched). Parser only surfaces
// contrast/pivot as top-level params; the rest are panel-confirmed. Assert what round-trips:
for (const [ctl, val] of [['contrast', 1.2], ['contrast', 0.8], ['pivot', 0.5], ['pivot', 0.3]]) {
  test(`1:1 control ${ctl}=${val} round-trips unscaled (ui default)`, async () => {
    const p = await roundtrip({ [ctl]: val });
    near(p[ctl], val, ctl);
  });
  test(`1:1 control ${ctl}=${val} identical in space:drx`, async () => {
    const p = await roundtrip({ space: 'drx', [ctl]: val });
    near(p[ctl], val, `${ctl} drx`);
  });
}

// Niche/advanced controls — verified 2026-07 to round-trip 1:1 (direct float, no scaling
// factor; the normalizer correctly passes them raw). Value is located anywhere in the
// decoded node (they land under correctors[].parameters[].value, not top-level params).
function decodedHas(node, target, eps = 1e-3) {
  let found = false;
  const walk = (o) => {
    if (found || o == null) return;
    if (typeof o === 'number') { if (Math.abs(o - target) <= eps) found = true; return; }
    if (typeof o === 'object') for (const k of Object.keys(o)) { if (k !== '_raw') walk(o[k]); }
  };
  walk(node);
  return found;
}
for (const [ctl, gp, val] of [
  ['softClipHigh', { softClipHigh: 0.7 }, 0.7],
  ['softClipLow', { softClipLow: 0.13 }, 0.13],
  ['blackOffset', { blackOffset: 0.17 }, 0.17],
  ['rgbMixer.rr', { rgbMixer: { rr: 1.15 } }, 1.15],
  // Full-coverage additions 2026-07-02 (exhaustiveness audit): every remaining writable
  // scalar is 1:1 — panel-verified in Phase 1 where noted, now regression-locked too.
  ['temperature', { temperature: 2000 }, 2000], // panel-verified 2000
  ['tint', { tint: 20 }, 20], // panel-verified 20
  ['midtoneDetail', { midtoneDetail: 30 }, 30], // panel-verified 30
  ['colorBoost', { colorBoost: 25 }, 25], // panel-verified 25
  ['highlights', { highlights: 12 }, 12],
  ['shadows', { shadows: -14 }, -14],
  ['lumMixSlider', { lumMixSlider: 0.37 }, 0.37],
  ['logMid.g', { logMid: { g: 0.22 } }, 0.22],
  ['rgbMixer.gb (off-diagonal)', { rgbMixer: { gb: -0.2 } }, -0.2],
  ['rgbMixer.bb (diagonal ≠1)', { rgbMixer: { bb: 0.9 } }, 0.9],
  ['contrastLowRange', { contrast: 1.2, contrastLowRange: 0.28 }, 0.28],
  ['logShadow.r', { logShadow: { r: 0.34 } }, 0.34],
  ['logHigh.b', { logHigh: { b: 0.36 } }, 0.36],
]) {
  test(`niche control ${ctl} round-trips 1:1 (direct float)`, async () => {
    const g = await call('generate', { gradeParams: { space: 'drx', ...gp } });
    const node = (await call('parse', { content: g.content || g })).nodes[0];
    assert.ok(decodedHas(node, val), `${ctl}=${val} should decode 1:1`);
  });
}

// RESOLVED 2026-07-01 by live panel readback (both Phase-1 "known issues" were NOT encoder
// bugs — the encoder transforms are Resolve-faithful; the gap was space:'drx' compensation):
//  • hueRotate: encoder stores (UI−50)/50. Applied generated DRX with hueRotate 60 (stored
//    0.2) → Resolve Primaries panel reads Hue 60.00. In drx space the normalizer now inverts
//    (UI = 50 + 50×raw) so raw stored values round-trip.
//  • contrastHighRange: RESOLVE ITSELF stores 1−UI. Applied UI 0.70 (stored 0.30) → Log
//    palette reads ↑Rng 0.700 (and ↓Rng 0.280 for the 1:1 low range). The drx-space
//    normalizer now pre-inverts so raw stored values round-trip.
test('ui-space hueRotate=60 stores (60−50)/50 = 0.2 (panel-confirmed Hue 60.00)', async () => {
  const g = await call('generate', { gradeParams: { hueRotate: 60 } });
  const node = (await call('parse', { content: g.content || g })).nodes[0];
  assert.ok(decodedHas(node, 0.2), 'ui 60 → stored 0.2');
});
test('drx-space hueRotate=0.2 round-trips raw', async () => {
  const g = await call('generate', { gradeParams: { space: 'drx', hueRotate: 0.2 } });
  const node = (await call('parse', { content: g.content || g })).nodes[0];
  assert.ok(decodedHas(node, 0.2), 'raw 0.2 → stored 0.2');
});
test('ui-space contrastHighRange=0.7 stores 1−0.7 = 0.3 (panel-confirmed ↑Rng 0.700)', async () => {
  const g = await call('generate', { gradeParams: { contrast: 1.2, contrastHighRange: 0.7 } });
  const node = (await call('parse', { content: g.content || g })).nodes[0];
  assert.ok(decodedHas(node, 0.3), 'ui 0.7 → stored 0.3 (Resolve-native inversion)');
});
test('drx-space contrastHighRange=0.3 round-trips raw', async () => {
  const g = await call('generate', { gradeParams: { space: 'drx', contrast: 1.2, contrastHighRange: 0.3 } });
  const node = (await call('parse', { content: g.content || g })).nodes[0];
  assert.ok(decodedHas(node, 0.3), 'raw 0.3 → stored 0.3');
});

// Custom curves (structural) — fidelity round-trip: interior control points survive intact.
// Note the point format is {x,y} objects (NOT [x,y] arrays); endpoints 0,0/1,1 are implicit.
test('customCurves.y interior points round-trip 1:1', async () => {
  const pts = [{ x: 0, y: 0 }, { x: 0.25, y: 0.2 }, { x: 0.5, y: 0.55 }, { x: 0.75, y: 0.8 }, { x: 1, y: 1 }];
  const g = await call('generate', { gradeParams: { space: 'drx', customCurves: { y: pts } } });
  const y = (await call('parse', { content: g.content || g })).nodes[0].customCurves?.y || [];
  for (const p of pts.slice(1, -1)) {
    assert.ok(y.some((q) => Math.abs(q.x - p.x) < 0.01 && Math.abs(q.y - p.y) < 0.01), `curve point ${p.x},${p.y} should round-trip`);
  }
});

// Combined multi-control grade (the realistic shot-match shape) round-trips coherently.
test('combined ui-space grade round-trips on every axis at once', async () => {
  const p = await roundtrip({ lift: { master: -0.023, b: -0.01 }, gamma: { master: 0.02 }, gain: { g: 0.97 }, offset: { g: -0.5 }, saturation: 53 });
  near(p.lift.master, -0.046, 'lift.master');
  near(p.lift.b, -0.02, 'lift.b');
  near(p.gamma.master, 0.08, 'gamma.master');
  near(p.gain.g, 0.97, 'gain.g');
  near(p.offset.g, -0.02, 'offset.g');
  near(p.saturation, 1.06, 'saturation');
});
