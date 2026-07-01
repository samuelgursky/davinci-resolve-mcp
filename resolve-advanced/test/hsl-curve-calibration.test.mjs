/** HSL curves — spline-point decode VALIDATED + Hue-Rotate scale.
 * Swept 2026-06-22 on the the calibration rig: switched the Curves palette to "Hue vs Hue", selected the
 * RED band and set Hue Rotate = 33° via the numeric field, Cmd+S, decoded the BARS grade.
 *
 * Findings:
 * - decodeSplinePoints (already handling HSL spline IDs 0x86000400–405) lifts the Hue-vs-Hue spline
 * (0x86000400) into node.params.curvePoints['hslCurves.hueVsHueSpline'] — the SAME F8.F1[] point
 * format as custom curves. So HSL splines and custom splines share the decoder. ✓
 * - COORDINATE SPACE DIFFERS from custom curves: HSL Hue-vs-Hue points are NORMALIZED —
 * x ∈ [-1, 1] (hue axis), y ∈ [0, 1] with 0.5 = neutral — NOT the ~0–1024 (10-bit) space the
 * custom Y/R/G/B curves use. (The decoder is space-agnostic; it reads raw f32 x/y.)
 * - HUE-ROTATE SCALE (exact): a band rotated D degrees moves to y = 0.5 − D/360. Measured: red band
 * at Hue Rotate 33 → y = 0.5 − 33/360 = 0.408333 (decoded 0.40833333, exact). */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { drxTool } from '../server/tools/drx.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const content = fs.readFileSync(path.join(here, 'fixtures', 'hsl-curve-huehue.drx'), 'utf8');

test('HSL Hue-vs-Hue spline decodes into normalized curve points', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const node = r.nodes.find((n) => n.params?.curvePoints?.['hslCurves.hueVsHueSpline']);
  assert.ok(node, 'a node exposes hslCurves.hueVsHueSpline points');
  const pts = node.params.curvePoints['hslCurves.hueVsHueSpline'];
  assert.ok(pts.length >= 6, `expected several spline points, got ${pts.length}`);

  // Normalized space: x ∈ [-1,1] (hue), y ∈ [0,1] (0.5 neutral) — distinct from the custom curve's
  // ~0–1024 space. The hue axis is PERIODIC, so wrap-around tangent handles extend slightly beyond
  // ±1 (e.g. 1.0833 mirroring -0.9166), just as custom curves carry handles beyond [0,1024].
  for (const p of pts) {
    assert.ok(p.x >= -1.2 && p.x <= 1.2, `x ~ [-1,1] + wrap handles (got ${p.x})`);
    assert.ok(p.y >= -0.001 && p.y <= 1.001, `y in [0,1] (got ${p.y})`);
  }
  // Core band points (the 6 hue bands) sit within [-1,1].
  assert.ok(pts.filter((p) => p.x >= -1 && p.x <= 1).length >= 6, 'core band points within [-1,1]');
  // Neutral baseline present.
  assert.ok(
    pts.some((p) => Math.abs(p.y - 0.5) < 1e-4),
    'has neutral y=0.5 points',
  );
});

test('HSL Hue-Rotate scale: y = 0.5 − degrees/360 (red band at 33°)', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const pts = r.nodes.find((n) => n.params?.curvePoints?.['hslCurves.hueVsHueSpline']).params.curvePoints['hslCurves.hueVsHueSpline'];
  const expected = 0.5 - 33 / 360; // 0.408333…
  const minY = Math.min(...pts.map((p) => p.y));
  assert.ok(Math.abs(minY - expected) < 1e-4, `rotated band y ≈ ${expected} (got ${minY})`);
});
