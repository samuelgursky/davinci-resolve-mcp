/** Gradient Window — VALIDATE-WIRE + collision finding.
 * Swept 2026-06-22 on a Gradient window (corrector type 65554) on node 2 of the the calibration rig:
 * Pan 81 / Tilt 82 / Rotate 83 / Opacity 84 / Soft1 85. Findings:
 * - SOFTNESS (0x08F0000B) ×100 CONFIRMED (Soft1 85 → 8500). Handles in pixels (Pan 81 → 2539.52).
 * - OPACITY (0x08F00011) was unwired → added as gradientWindow.opacity (/100, UI 84 → 0.84). It is
 * collision-free, so this assertion is exact.
 * - ⚠ KNOWN COLLISION: the other gradient params share IDs with SAT_VS_SAT.PARAM_1–7 (both 0x08F000xx);
 * the flat PARAM_ID_MAP mislabels them as satVsSat.* — proper fix is corrector-type-aware naming. */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { drxTool } from '../server/tools/drx.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const content = fs.readFileSync(path.join(here, 'fixtures', 'gradient-window.drx'), 'utf8');

test('Gradient window params decode with ct-aware names (not mislabeled satVsSat)', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const byId = {};
  for (const n of r.nodes)
    for (const c of n.correctors || []) {
      if (c.type !== 65554) continue;
      for (const p of c.parameters || []) byId[p.id >>> 0] = p;
    }
  // ct-aware naming resolves the GRADIENT_WINDOW ↔ SAT_VS_SAT id collision
  assert.equal(byId[0x08f0000b]?.name, 'gradientWindow.softness');
  assert.equal(byId[0x08f0000b].value, 8500, 'softness ×100 (Soft1 85 → 8500)');
  assert.equal(byId[0x08f00005]?.name, 'gradientWindow.handle1Pos');
  assert.equal(byId[0x08f00011]?.name, 'gradientWindow.opacity'); // collision-free
  assert.ok(Math.abs(byId[0x08f00011].value - 0.84) < 1e-3, `opacity 0.84 (got ${byId[0x08f00011].value})`);
  // none of these should carry a satVsSat name now
  for (const id of [0x08f00001, 0x08f00003, 0x08f00005, 0x08f00006, 0x08f0000b]) {
    assert.ok(!String(byId[id]?.name).startsWith('satVsSat'), `0x${id.toString(16)} not mislabeled satVsSat`);
  }
});
