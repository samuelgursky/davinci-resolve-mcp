/** Linear window softness mask — corrector type CORRECTED + scale RE-CONFIRMED. Added a Linear power window on the the calibration rig 2026-06-22 and set asymmetric softness
 * (Soft 1/2/3/4 = 4.50 / 6.25 / 8.75 / 11.00), Cmd+S, decoded the BARS grade.
 *
 * KEY FINDINGS:
 * - The softness mask lives under CORRECTOR TYPE 3 (dumped corrector.F1 directly = 3). The registry's
 * "corrector type 65539 = 0x10003" claim is WRONG/version-stale for Resolve 21.
 * - SOFT_1–4 (0x08700009–0C) scale = UI × 16 (4.50→72, 6.25→100, 8.75→140, 11.00→176 — all ÷16 exact),
 * re-confirming the prior 2026-03-22 finding live.
 * - SOFT_PAN/TILT (0x15/16)=0, SOFT_WIDTH/HEIGHT (0x17/18)=1 at defaults; SOFT_BBOX (0x14)=nested blob.
 * These were defined-but-unmapped in the registry (decoded `unknown_`); now wired into PARAM_ID_MAP. */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { drxTool } from '../server/tools/drx.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const content = fs.readFileSync(path.join(here, 'fixtures', 'linear-window-softness.drx'), 'utf8');

function softParams(nodes) {
  const out = {};
  for (const n of nodes) {
    for (const c of n.correctors || []) {
      if (c.type !== 3) continue;
      for (const p of c.parameters || []) out[p.name] = p.value;
    }
  }
  return out;
}

test('Linear softness mask params decode named on corrector type 3 (UI × 16)', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const sp = softParams(r.nodes);
  // Soft 1-4 = UI × 16
  assert.equal(sp['window.soft1'], 72, 'Soft1 4.50 × 16');
  assert.equal(sp['window.soft2'], 100, 'Soft2 6.25 × 16');
  assert.equal(sp['window.soft3'], 140, 'Soft3 8.75 × 16');
  assert.equal(sp['window.soft4'], 176, 'Soft4 11.00 × 16');
});

test('Linear softness mask geometry defaults are named (not unknown_)', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const sp = softParams(r.nodes);
  assert.equal(sp['window.softPan'], 0);
  assert.equal(sp['window.softTilt'], 0);
  assert.equal(sp['window.softWidth'], 1);
  assert.equal(sp['window.softHeight'], 1);
  // No ct3 param should be left as unknown_.
  const names = Object.keys(sp);
  assert.ok(names.length >= 9, 'all ct3 soft params surfaced');
  assert.ok(!names.some((n) => n.startsWith('unknown_')), 'no unknown_ soft params');
});
