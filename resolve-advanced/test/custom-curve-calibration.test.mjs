/** Custom Curve spline points — Blob RE.
 * Captured 2026-06-22 on node 2 of the the calibration rig with the Y curve bent upward (one added
 * control point). The spline data params (0x86000506–509) store points in F8.F1[] as sub-messages
 * `0d<f32 x> 15<f32 y>` (F1=x, F2=y, fixed32). Coordinates are ~0–1024 (10-bit) space — NOT the
 * 0.0–1.0 the registry comment claimed — with tangent/extrapolation handles beyond [0,1024].
 * The parser now lifts these into node.params.curvePoints['customCurves.ySpline'] = [{x,y}].
 * extractCustomCurves (the separate secondary decoder) is unaffected — this is additive. */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { drxTool } from '../server/tools/drx.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const content = fs.readFileSync(path.join(here, 'fixtures', 'custom-curve-y.drx'), 'utf8');

test('Custom curve spline points lift into node.params.curvePoints (10-bit coords, bent above identity)', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const cp = r.nodes.map((n) => n.params && n.params.curvePoints).find(Boolean);
  assert.ok(cp, 'node.params.curvePoints present');
  const y = cp['customCurves.ySpline'];
  assert.ok(Array.isArray(y) && y.length >= 3, `Y spline has points (got ${y && y.length})`);
  // endpoints span the ~0..1023 (10-bit) range, not 0..1
  const maxX = Math.max(...y.map((p) => p.x));
  assert.ok(maxX > 1000, `curve X coords are 10-bit (~1023), got max ${maxX}`);
  // the bend lifted at least one interior point above the identity line (y > x)
  assert.ok(
    y.some((p) => p.x > 50 && p.x < 1000 && p.y > p.x + 20),
    'an interior point sits above identity (curve bent up)',
  );
});
