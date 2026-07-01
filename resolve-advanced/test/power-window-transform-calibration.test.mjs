/** Power Window transform — EXACT scales + SIZE/ASPECT swap fix.
 * Multi-point fit 2026-06-22 on the calibration circle window (isolate each param: vary one, hold the
 * rest neutral). Fixture state: Size 75 / Aspect 30 / Pan 35 / Tilt 88 / Rotate 49 (Opacity 100).
 *
 * KEY FINDING — SIZE and ASPECT param IDs were SWAPPED in the registry. Cross-referencing isolated
 * sweeps proved 0x08500004 follows the Aspect slider and 0x08500006 follows the Size slider:
 * - 0x08500004 = ASPECT, stored = (50 − UI)/50 (neutral 0; Aspect 30 → 0.40)
 * - 0x08500006 = SIZE, stored = 1 + (UI−50)×0.08 (neutral 1.0; Size 75 → 3.0)
 *
 * Other transforms (multi-point, exact):
 * - ROTATE 0x08500001 = −UI°/180 (Rotate 49 → −0.27222). The old "direct degrees" note was WRONG.
 * - PAN 0x0850000B / TILT 0x0850000C = (UI−50)/50 × 4096 (Pan 35 → −1228.8, Tilt 88 → 3112.96).
 * Registry + generator (drx-generator.js) both corrected to these scales. */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { drxTool } from '../server/tools/drx.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const content = fs.readFileSync(path.join(here, 'fixtures', 'power-window-transform.drx'), 'utf8');

const close = (a, b, eps = 1e-2) => Math.abs(a - b) < eps;

test('Power-window transform scales (size/aspect un-swapped, rotate/pan/tilt exact)', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const byId = {};
  for (const n of r.nodes)
    for (const c of n.correctors || []) {
      if (c.type !== 4) continue;
      for (const p of c.parameters || []) byId[p.id >>> 0] = { name: p.name, value: p.value };
    }

  // The swap fix: 0x08500004 is ASPECT, 0x08500006 is SIZE (previously reversed).
  assert.equal(byId[0x08500004].name, 'window.aspect');
  assert.equal(byId[0x08500006].name, 'window.size');

  // Exact measured scales.
  assert.ok(close(byId[0x08500004].value, (50 - 30) / 50), `aspect (50−30)/50=0.40 (got ${byId[0x08500004].value})`);
  assert.ok(close(byId[0x08500006].value, 1 + (75 - 50) * 0.08), `size 1+(75−50)×0.08=3.0 (got ${byId[0x08500006].value})`);
  assert.ok(close(byId[0x08500001].value, -49 / 180), `rotate −49/180 (got ${byId[0x08500001].value})`);
  assert.ok(close(byId[0x0850000b].value, ((35 - 50) / 50) * 4096), `pan −1228.8 (got ${byId[0x0850000b].value})`);
  assert.ok(close(byId[0x0850000c].value, ((88 - 50) / 50) * 4096), `tilt 3112.96 (got ${byId[0x0850000c].value})`);
});
