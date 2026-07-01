/** Sat-vs-Sat curve — IDENTITY of the corrector RESOLVED + scale.
 * Swept 2026-06-22 on the the calibration rig: Curves palette → "Sat vs Sat", added a control point at
 * Input Sat 0.25 and set Output Sat = 1.40, Cmd+S, decoded the BARS grade.
 *
 * KEY FINDING — the ledger's "SAT_VS_SAT = corrector type 3, params 0x08F000xx" was a MISLABEL. The real
 * Sat-vs-Sat CURVE writes the hslCurves spline 0x86000404 under corrector type 1 (+ meta 0x86000103),
 * exactly like the other HSL curves. The ct3 0x08F000xx ids are gradient-window's (ct65554) — their
 * "satVsSat.*" mapping in PARAM_ID_MAP is vestigial and is NOT what the Sat-vs-Sat curve emits.
 *
 * Scale: x = Input Sat (normalized; UI 0.25 → 0.2476), y neutral 0.5, and y = 1.0 − OutputSat/2
 * (OutputSat 1.40 → y 0.30, exact; OutputSat 1.0 → y 0.5). */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { drxTool } from '../server/tools/drx.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const content = fs.readFileSync(path.join(here, 'fixtures', 'hsl-curve-satsat.drx'), 'utf8');

test('Sat-vs-Sat curve emits the ct1 hslCurves spline 0x86000404 (not ct3 0x08F000xx)', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  let satSpline = null;
  for (const n of r.nodes)
    for (const c of n.correctors || [])
      for (const p of c.parameters || []) {
        if (p.id >>> 0 === 0x86000404) {
          satSpline = { p, ct: c.type };
        }
        // No corrector in this grade should be a ct3 sat-vs-sat with 0x08F000xx ids.
        assert.notEqual(c.type, 3, 'no ct3 corrector present for a Sat-vs-Sat curve');
      }
  assert.ok(satSpline, 'sat-vs-sat spline 0x86000404 present');
  assert.equal(satSpline.ct, 1, 'sat-vs-sat curve lives under corrector type 1 (hslCurves)');
  assert.equal(satSpline.p.name, 'hslCurves.satVsSatSpline');
});

test('Sat-vs-Sat scale: y = 1 − OutputSat/2 (Input 0.25 / Output 1.40 → x≈0.25, y≈0.30)', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const pts = r.nodes.find((n) => n.params?.curvePoints?.['hslCurves.satVsSatSpline']).params.curvePoints['hslCurves.satVsSatSpline'];
  // Neutral endpoints at y=0.5.
  assert.ok(
    pts.some((p) => Math.abs(p.y - 0.5) < 1e-4),
    'neutral y=0.5 endpoints',
  );
  // The adjusted plateau is OutputSat 1.40 → y = 1 − 1.40/2 = 0.30.
  const adjusted = pts.find((p) => Math.abs(p.x - 0.25) < 0.02);
  assert.ok(adjusted, 'a point near Input Sat 0.25');
  assert.ok(Math.abs(adjusted.y - 0.3) < 1e-3, `OutputSat 1.40 → y 0.30 (got ${adjusted.y})`);
});
