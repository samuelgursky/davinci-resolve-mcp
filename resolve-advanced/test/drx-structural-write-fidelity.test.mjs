/** Structural WRITE-fidelity — Phase 2 of the DRX calibration program (2026-07-01).
 *
 * Phase 1 calibrated scalar/wheel scaling; this phase audited the STRUCTURAL write paths
 * (windows, qualifiers, HDR zones, HSL curves) against live Resolve 19/21 ground truth and
 * fixed the encoders. Every stored value asserted here was LIVE-CONFIRMED by applying a
 * generated .drx to a clip and reading the Resolve panel (Window palette: Size 60/Pan 35/
 * Tilt 75/Soft 5 exact; Qualifier palette: Center 33.1/Width 22/Low 12/High 88 exact;
 * HDR palette: Dark +0.80, Highlight −0.80 exact) — see CALIBRATION-STATUS.md.
 *
 * Encoder fixes locked here:
 *  • Power-window transforms now write the TRUE live-calibrated scales (rotate −UI/180,
 *    size 1+(UI−50)×0.08, aspect (50−UI)/50, pan/tilt (UI−50)/50×4096, softRef UI×16) —
 *    the registry window ranges were widened (they used to clamp pan/tilt to ±1).
 *  • Window shape flag 0x88500008 is a CONSTANT varint {F2:2} (all shapes); shape is
 *    expressed by which corrector blocks exist (linear mask → ct3, gradient → ct65554).
 *  • HDR zones: ALL zones share ONE ZONE_ADJUSTMENTS param (multi-zone grades used to
 *    silently keep only the last zone).
 *  • Qualifier mode flags are varint envelopes ({F2:4} / {F2:mode}), not float32.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { drxTool, canonicalizeHueAxisPoints } from '../server/tools/drx.mjs';

const call = (action, args) => drxTool.handler({ action, args });
const near = (a, b, msg, eps = 1e-3) => assert.ok(Math.abs(a - b) <= eps, `${msg}: got ${a}, want ${b}`);

async function roundtrip(gradeParams) {
  const g = await call('generate', { gradeParams });
  return call('parse', { content: g.content || g });
}
function paramsById(parsed) {
  const map = {};
  for (const n of parsed.nodes) {
    for (const c of n.correctors || []) {
      for (const p of c.parameters || []) map[p.id >>> 0] = { ct: c.type, value: p.value, name: p.name };
    }
  }
  return map;
}

test('circle window writes the live-calibrated transform values (panel-confirmed)', async () => {
  // Same UI values as the power-window-transform fixture — the generated stored values
  // must equal what live Resolve stored for those slider positions.
  const parsed = await roundtrip({ space: 'drx', window: { type: 1, pan: 35, tilt: 88, size: 75, aspect: 30, rotate: 49, soft1: 10 } });
  const byId = paramsById(parsed);
  near(byId[0x08500001].value, -49 / 180, 'rotate −UI/180');
  near(byId[0x08500006].value, 1 + (75 - 50) * 0.08, 'size 1+(UI−50)×0.08');
  near(byId[0x08500004].value, (50 - 30) / 50, 'aspect (50−UI)/50');
  near(byId[0x0850000b].value, ((35 - 50) / 50) * 4096, 'pan ×4096', 0.01);
  near(byId[0x0850000c].value, ((88 - 50) / 50) * 4096, 'tilt ×4096', 0.01);
  near(byId[0x08500005].value, 160, 'softRef UI×16');
  // Shape flag: constant varint {F2:2} — same wire form as every live fixture.
  assert.equal(byId[0x88500008].value?.F2, 2, 'window type flag varint {F2:2}');
  // The extractor inverts back to UI values.
  const w = parsed.nodes[0].powerWindow;
  for (const [k, v] of [['pan', 35], ['tilt', 88], ['size', 75], ['aspect', 30], ['rotate', 49], ['soft1', 10]]) {
    near(w[k], v, `extract ${k}`);
  }
});

test('linear window routes the softness mask to a ct3 block at UI×16', async () => {
  // Same UI values as the linear-window-softness fixture (stored 72/100/140/176).
  const parsed = await roundtrip({ space: 'drx', window: { type: 2, soft1: 4.5, soft2: 6.25, soft3: 8.75, soft4: 11 } });
  const byId = paramsById(parsed);
  for (const [id, stored] of [[0x08700009, 72], [0x0870000a, 100], [0x0870000b, 140], [0x0870000c, 176]]) {
    assert.equal(byId[id].ct, 3, `0x${id.toString(16)} lives under corrector type 3`);
    near(byId[id].value, stored, `soft mask ÷16 exact`);
  }
});

test('gradient window writes a ct65554 block with the live-calibrated values', async () => {
  // Same UI values as the gradient-window fixture (rotation −0.4611, handles 2539.52/2621.44,
  // softness 8500, opacity 0.84).
  const parsed = await roundtrip({ space: 'drx', window: { type: 5, pan: 81, tilt: 82, rotate: 83, soft1: 85, opacity: 84 } });
  const byId = paramsById(parsed);
  for (const [id, stored] of [[0x08f00003, -83 / 180], [0x08f00005, 2539.52], [0x08f00006, 2621.44], [0x08f0000b, 8500], [0x08f00011, 0.84]]) {
    assert.equal(byId[id].ct, 65554, `0x${id.toString(16)} lives under corrector type 65554`);
    near(byId[id].value, stored, `gradient 0x${id.toString(16)}`, 0.01);
  }
  assert.equal(byId[0x08f00001].value?.F2, 2, 'gradient subtype varint {F2:2}');
});

test('HDR zones: multiple zones survive in ONE ZONE_ADJUSTMENTS param (panel-confirmed)', async () => {
  const parsed = await roundtrip({
    space: 'drx',
    hdrDark: { exposure: 0.8 },
    hdrHighlight: { exposure: -0.8, colorBalanceX: 0.1 },
    hdrShadow: { saturation: 1.3 },
  });
  const zones = parsed.nodes[0].params?.hdrZones || [];
  const byName = Object.fromEntries(zones.map((z) => [z.name, z]));
  assert.equal(zones.length, 3, `all 3 zones decode (got ${zones.map((z) => z.name).join(',')})`);
  near(byName.Dark.exposure, 0.8, 'Dark exposure');
  near(byName.Highlight.exposure, -0.8, 'Highlight exposure');
  near(byName.Highlight.colorBalanceX, 0.1, 'Highlight cbX');
  near(byName.Shadow.saturation, 1.3, 'Shadow saturation');
});

test('HSL qualifier writes UI÷100 ranges + varint mode flags (panel-confirmed)', async () => {
  const parsed = await roundtrip({
    space: 'drx',
    qualifier: { hueCenter: 33, hueWidth: 22, hueSoft: 11, satLow: 12, satHigh: 88, lumLow: 20, lumHigh: 80 },
  });
  const q = parsed.nodes[0].qualifier;
  for (const [k, v] of [['hueCenter', 33], ['hueWidth', 22], ['hueSoft', 11], ['satLow', 12], ['satHigh', 88], ['lumLow', 20], ['lumHigh', 80], ['hueSymmetry', 50]]) {
    near(q[k], v, `qualifier ${k}`);
  }
  const byId = paramsById(parsed);
  assert.equal(byId[0x0830006f]?.value, 4, 'modeFlag varint 4 (parser lifts F2)');
  assert.equal(byId[0x88300001]?.value?.F2, 0, 'qualifier mode HSL varint {F2:0}');
});

test('HSL sat-axis curve round-trips with per-curve meta override (live: Sat vs Sat renders)', async () => {
  // Live-confirmed 2026-07-01: replicating the satVsSat fixture (meta {F2:2} + its point
  // list) renders in Resolve's Sat vs Sat panel with Input 0.25 / Output 1.40 exact.
  // NOTE: hue-AXIS curves (hueVsHue/hueVsSat/hueVsLum) are still NOT accepted by Resolve
  // from naive point lists — they need the canonical wrapped band structure (x ∈ [-1,1],
  // ~19-point handle ring). Write support for those remains EXPERIMENTAL.
  const pts = [{ x: 0, y: 0.5 }, { x: 0.2476, y: 0.3 }, { x: 1, y: 0.5 }];
  const parsed = await roundtrip({ space: 'drx', hslCurves: { satVsSat: pts }, hslCurveMeta: { satVsSat: 2 } });
  const byId = paramsById(parsed);
  assert.equal(byId[0x86000103]?.value?.F2, 2, 'satVsSat meta override {F2:2} (fixture value)');
  const got = parsed.nodes[0].hslCurves?.satVsSat || [];
  for (const p of pts) {
    assert.ok(got.some((g) => Math.abs(g.x - p.x) < 1e-4 && Math.abs(g.y - p.y) < 1e-4), `point ${p.x},${p.y} survives`);
  }
});

// ── Write paths added 2026-07-02 (RGB/luma qualifier, ColorSlice, Color Warper) ──

test('RGB qualifier writes live-corrected ids at UI÷100 + mode varint {F2:2} (panel-confirmed)', async () => {
  // Live-confirmed: applying this DRX switches the Qualifier palette to RGB mode with
  // Red 12/88 (soft 5/7), Green 22/78, Blue 32/68 — all exact.
  const parsed = await roundtrip({
    space: 'drx',
    rgbQualifier: { rLow: 12, rHigh: 88, rLowSoft: 5, rHighSoft: 7, gLow: 22, gHigh: 78, bLow: 32, bHigh: 68 },
  });
  const byId = paramsById(parsed);
  // Live-corrected per-channel layout from base id: [High, HighSoft, Low, LowSoft].
  for (const [id, v] of [[0x08300002, 0.88], [0x08300003, 0.07], [0x08300004, 0.12], [0x08300005, 0.05], [0x08300006, 0.78], [0x08300008, 0.22], [0x0830000a, 0.68], [0x0830000c, 0.32]]) {
    assert.equal(byId[id]?.ct, 2, `0x${id.toString(16)} under ct2`);
    near(byId[id].value, v, `rgb qualifier 0x${id.toString(16)}`);
  }
  assert.equal(byId[0x88300001]?.value?.F2, 2, 'qualifier mode RGB varint {F2:2}');
});

test('luma qualifier writes lum ranges + mode varint {F2:4}', async () => {
  const parsed = await roundtrip({ space: 'drx', lumaQualifier: { lumLow: 20, lumHigh: 80, lumLowSoft: 3 } });
  const byId = paramsById(parsed);
  assert.equal(byId[0x88300001]?.value?.F2, 4, 'qualifier mode luma varint {F2:4}');
  const q = parsed.nodes[0].qualifier;
  near(q.lumLow, 20, 'lumLow');
  near(q.lumHigh, 80, 'lumHigh');
  near(q.lumLowSoft, 3, 'lumLowSoft');
});

test('ColorSlice globals write identity scale with NEGATED hue (panel-confirmed)', async () => {
  // Live-confirmed: ColorSlice palette reads Den 0.30 / Sat 1.40 / Hue 0.25 exact, and
  // GetToolsInNode reports ["ColorSlice"]. Hue is stored negated (ui +0.25 → −0.25).
  const parsed = await roundtrip({ colorSlice: { density: 0.3, sat: 1.4, hue: 0.25 } });
  const byId = paramsById(parsed);
  near(byId[0x86000600].value, 0.3, 'density identity');
  near(byId[0x86000602].value, 1.4, 'sat identity');
  near(byId[0x86000605].value, -0.25, 'hue NEGATED');
  // drx space carries the raw stored (already-negated) value.
  const parsedDrx = await roundtrip({ space: 'drx', colorSlice: { hue: -0.25 } });
  near(paramsById(parsedDrx)[0x86000605].value, -0.25, 'drx-space hue raw');
});

test('Color Warper pin list round-trips through the R21 wire format (decode-only on R19)', async () => {
  // Matches the live R21 fixture byte layout (configA/B varints {F2:2}, pins under
  // 0x86000138 F27.F1[]). NOTE: Resolve 19.1.3 does NOT accept this format (no tool
  // registers) — the pin-list serialization is R21+; live verify on R21 pending.
  const pin = { id: 1, srcX: 0.1, srcY: 0.2, dstX: 0.15, dstY: 0.25, chromaRange: 0.12, exposure: 0.2, tonalLow: 0.34, tonalHigh: 0.56, tonalPivot: 0.25 };
  const parsed = await roundtrip({ space: 'drx', colorWarper: { pins: [pin] } });
  const got = parsed.nodes[0].params?.colorWarper?.[0];
  assert.ok(got, 'pin decodes back via decodeColorWarperPins');
  for (const k of Object.keys(pin)) near(got[k], pin[k], `pin.${k}`);
  const byId = paramsById(parsed);
  assert.equal(byId[0x86000136]?.value?.F2, 2, 'configA varint {F2:2}');
  assert.equal(byId[0x86000137]?.value?.F2, 2, 'configB varint {F2:2}');
  assert.equal(byId[0x86000133], undefined, 'no MODE_FLAG param unless requested (fixture-faithful)');
});

test('hue-axis HSL curve canonical decode structure is understood (write still experimental)', async () => {
  // The canonical R19 structure was captured live 2026-07-02 (authored Hue-vs-Sat green
  // band at Sat 1.50, grabbed via gallery): meta 0x860000B8={F2:2}, spline 0x86000401,
  // y = 1 − Sat/2 (bump y 0.25), six band anchors, bezier handle pairs, and PERIODIC
  // WRAP copies spanning x ∈ [-2/3, 4/3]. Reference preserved at
  // a live-captured Resolve 19 reference grade. A naive point list is
  // silently ignored by Resolve; a hand-built wrap approximation coincided with a
  // Resolve 19.1.3 crash — DO NOT iterate this write path on a production project
  // (use the DRX_CALIB rig). This test locks the codec-side fidelity only: points in,
  // points out, meta override honored.
  const pts = [{ x: -0.5, y: 0.5 }, { x: 1 / 6, y: 0.5 }, { x: 1 / 3, y: 0.25 }, { x: 0.5, y: 0.5 }, { x: 7 / 6, y: 0.5 }];
  // allowWrappedHueCage: pre-wrapped lists are refused by default (malformed cages can
  // crash Resolve 19) — the flag is the explicit verbatim-re-encode escape hatch.
  const parsed = await roundtrip({ space: 'drx', allowWrappedHueCage: true, hslCurves: { hueVsSat: pts }, hslCurveMeta: { hueVsSat: 2 } });
  const byId = paramsById(parsed);
  assert.equal(byId[0x860000b8]?.value?.F2, 2, 'hueVsSat meta override {F2:2} (canonical value)');
  const got = parsed.nodes[0].hslCurves?.hueVsSat || [];
  for (const p of pts) {
    assert.ok(got.some((g) => Math.abs(g.x - p.x) < 1e-4 && Math.abs(g.y - p.y) < 1e-4), `point ${p.x},${p.y} survives (incl. negative-x wrap)`);
  }
});

test('hue-axis canonical emitter: bezier control cage, LIVE-VERIFIED single band', async () => {
  // The hue-axis spline is a STRICT bezier control cage — live-bisected 2026-07-02 on a
  // throwaway rig: naive points → tool registers, renders flat; same count with plain
  // points → renders GARBAGE; the exact Resolve-serialized pattern → renders correct.
  // canonicalizeHueAxisPoints reproduces that pattern for a single band edit, VERIFIED
  // LIVE at (1/3, y 0.25/0.9 — reference replica exact to 1e-5) and (0.6, y 0.75 →
  // panel read Saturation 0.50 exact, blue bar visibly desaturated).
  const naive = [{ x: 1 / 3, y: 0.25 }];
  const canon = canonicalizeHueAxisPoints(naive);
  assert.equal(canon.length, 19, 'single-band cage is 19 points (reference layout)');
  assert.ok(canon.some((p) => Math.abs(p.x - 1 / 3) < 1e-9 && p.y === 0.25), 'user bump kept');
  assert.ok(Math.abs(canon[0].x - (1 / 3 - 1)) < 1e-9 && canon[0].y === 0.25, 'list starts on wrapped bump center (x−1)');
  assert.ok(Math.abs(canon[18].x - (1 / 3 + 1)) < 1e-9 && canon[18].y === 0.25, 'list ends on wrapped bump center (x+1)');
  // Load-bearing extras (their absence renders flat — bisected live):
  const TY = 0.5 + 0.72264 * (0.25 - 0.5);
  assert.ok(canon.some((p) => Math.abs(p.y - TY) < 1e-6 && p.x < 0), 'descending tangent sample in down-wrap');
  assert.ok(canon.some((p) => Math.abs(p.y - TY) < 1e-6 && p.x > 1), 'ascending tangent sample in up-wrap');
  assert.ok(canon.filter((p) => Math.abs(p.x - 5 / 6) < 1e-9).length === 2, 'core segment-end anchor doubled');
  assert.ok(canon.some((p) => Math.abs(p.x - 1 / 6) < 1e-9 && p.y === 0.5), 'neutral anchor added');
  for (let i = 1; i < canon.length; i++) assert.ok(canon[i].x >= canon[i - 1].x - 1e-9, 'path-ordered');
  // Already-canonical input (x outside [0,1]) passes through raw.
  const pre = [{ x: -0.5, y: 0.5 }, { x: 0.3, y: 0.4 }];
  assert.equal(canonicalizeHueAxisPoints(pre), pre, 'pre-wrapped input passthrough');
  // Multi-band canonicalizes too (LIVE-VERIFIED: 2 bands at 1/3+2/3 render exact —
  // approximate midpoint tangents suffice; between-bump gaps use the slope-through-anchor
  // form). Known pathology guarded: a bump EDGE landing exactly on a band slot (k/6)
  // renders flat, so that geometry passes through raw instead.
  const multi = canonicalizeHueAxisPoints([{ x: 1 / 3, y: 0.25 }, { x: 2 / 3, y: 0.7 }]);
  assert.equal(multi.length, 25, '2-band cage is 25 points (probe layout)');
  assert.ok(multi.some((p) => p.x > 0.4 && p.x < 0.5 && p.y > 0.25 && p.y < 0.5), 'between-bump tangent slot present');
  const edgeOnSlot = [{ x: 0.25, y: 0.3 }, { x: 0.7, y: 0.8 }]; // 0.25 − 1/12 = 1/6 exactly
  assert.equal(canonicalizeHueAxisPoints(edgeOnSlot), edgeOnSlot, 'edge-on-slot geometry passes through raw (renders flat if caged)');

  // End-to-end: a naive hueVsSat through generate gets the canonical cage + meta 2.
  const parsed = await roundtrip({ space: 'drx', hslCurves: { hueVsSat: naive } });
  const byId = paramsById(parsed);
  assert.equal(byId[0x860000b8]?.value?.F2, 2, 'meta defaults to canonical {F2:2}');
  const got = parsed.nodes[0].hslCurves?.hueVsSat || [];
  assert.equal(got.length, 19, `full cage encoded (got ${got.length})`);
  assert.ok(got.some((p) => p.x < 0) && got.some((p) => p.x > 1), 'wrap copies encoded');
});

test('hue-axis crash guard: pre-wrapped input REFUSED without allowWrappedHueCage; raw passthrough WARNS', async () => {
  // Malformed wrapped cages can crash Resolve 19 outright (live-bisected) — a caller-built
  // wrapped list must not sail through silently.
  const wrapped = [{ x: -0.5, y: 0.5 }, { x: 1 / 3, y: 0.25 }];
  await assert.rejects(
    () => call('generate', { gradeParams: { space: 'drx', hslCurves: { hueVsSat: wrapped } } }),
    /CRASH Resolve 19/,
  );
  // Same refuse via merge's newNodes path.
  const base = (await call('generate', { gradeParams: { saturation: 60 } })).content;
  await assert.rejects(
    () => call('merge', { baseContent: base, newNodes: [{ params: { space: 'drx', hslCurves: { hueVsSat: wrapped } } }] }),
    /CRASH Resolve 19/,
  );
  // The escape hatch encodes verbatim.
  const ok = await call('generate', { gradeParams: { space: 'drx', allowWrappedHueCage: true, hslCurves: { hueVsSat: wrapped } } });
  assert.ok(ok.content, 'allowWrappedHueCage encodes');
  // Unsupported-but-in-range geometry passes through raw AND surfaces a warning
  // (Resolve registers the curve but renders it flat — the caller must know).
  const edgeOnSlot = [{ x: 0.25, y: 0.3 }, { x: 0.7, y: 0.8 }]; // 0.25 − 1/12 = 1/6 exactly
  const warned = await call('generate', { gradeParams: { space: 'drx', hslCurves: { hueVsSat: edgeOnSlot } } });
  assert.ok(Array.isArray(warned.warnings) && /render it FLAT/.test(warned.warnings[0] || ''), `raw passthrough warns: ${JSON.stringify(warned.warnings)}`);
  // Canonicalizable input stays warning-free.
  const clean = await call('generate', { gradeParams: { space: 'drx', hslCurves: { hueVsSat: [{ x: 1 / 3, y: 0.25 }] } } });
  assert.equal(clean.warnings, undefined, 'canonical path emits no warnings');
});

test('Blur/Key/Motion-Effects write paths (panel-confirmed 2026-07-02)', async () => {
  // Live: Blur palette read Radius 0.60 / H-V 0.40 / Scaling 0.35 — confirming the
  // (UI−0.5)×2 scale as a TWO-point fit on both sides of neutral; Key read
  // 0.850/0.120/0.650/0.080 exact; Motion Effects read Frames 2 (varint = frames×2
  // CONFIRMED) with thresholds 27/27 + 21/21 exact. GetToolsInNode registered
  // "Noise Reduction", "Blur, Sharpen & Mist", and "Key".
  const parsed = await roundtrip({
    space: 'drx',
    blur: { radius: 0.6, hvRatio: 0.4, scaling: 0.35 },
    key: { inputGain: 0.85, inputOffset: 0.12, outputGain: 0.65, outputOffset: 0.08 },
    motionEffects: { spatialLuma: 27, spatialChroma: 27, spatialBlend: 0.15, temporalLuma: 21, temporalChroma: 21, temporalBlend: 0.25, frames: 2 },
  });
  const byId = paramsById(parsed);
  near(byId[0x86000052].value, (0.6 - 0.5) * 2, 'blur radius (UI−0.5)×2');
  near(byId[0x86000056].value, (0.4 - 0.5) * 2, 'blur hvRatio negative side');
  near(byId[0x8600005b].value, 0.35, 'blur scaling identity');
  assert.equal(byId[0x86000052].ct, 1, 'blur in ct1');
  for (const [id, v] of [[0x0c300019, 0.85], [0x0c30001a, 0.12], [0x0c30001d, 0.65], [0x0c30001e, 0.08]]) {
    assert.equal(byId[id].ct, 9, `key 0x${id.toString(16)} in ct9`);
    near(byId[id].value, v, `key identity ${v}`);
  }
  for (const [id, v] of [[0x0c400002, 27], [0x0c400003, 27], [0x0c400004, 0.15], [0x0c40000b, 21], [0x0c40000c, 21], [0x0c40000d, 0.25]]) {
    assert.equal(byId[id].ct, 15, `motionEffects 0x${id.toString(16)} in ct15`);
    near(byId[id].value, v, `motionEffects identity ${v}`);
  }
  assert.equal(byId[0x0c400007]?.value?.F2, 4, 'frames varint = frames×2 (UI 2 → 4)');
});
