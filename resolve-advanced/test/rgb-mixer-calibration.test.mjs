/** RGB Mixer 3x3 matrix — VALIDATE-WIRE pass.
 * The 9 matrix cells (0x860000a7–af) were wired since 2026-03-17 but never live-confirmed.
 * Live-measured 2026-06-22 on the calibration SMPTE-bars compound clip: each UI cell set to a
 * unique value (Red Out rr/gr/br = 0.11/0.12/0.13, Green Out rg/gg/bg = 0.14/0.15/0.16,
 * Blue Out rb/gb/bb = 0.17/0.18/0.19) → Cmd+S → decoded from Project.db. All 9 IDs + the
 * UI-column→input mapping + identity scale confirmed EXACTLY. Fixture is that live grade. */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { drxTool } from '../server/tools/drx.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const content = fs.readFileSync(path.join(here, 'fixtures', 'rgb-mixer-grid.drx'), 'utf8');

// channel → (id, expected live-measured value)
const EXPECTED = {
  rr: [0x860000a7, 0.11],
  gr: [0x860000a8, 0.12],
  br: [0x860000a9, 0.13],
  rg: [0x860000aa, 0.14],
  gg: [0x860000ab, 0.15],
  bg: [0x860000ac, 0.16],
  rb: [0x860000ad, 0.17],
  gb: [0x860000ae, 0.18],
  bb: [0x860000af, 0.19],
};

test('RGB Mixer: all 9 matrix cells decode to their live-measured values (identity scale)', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const params = {};
  for (const n of r.nodes)
    for (const c of n.correctors || [])
      for (const p of c.parameters || []) {
        params[p.id >>> 0] = { name: p.name, value: p.value };
      }
  for (const [ch, [id, want]] of Object.entries(EXPECTED)) {
    const got = params[id >>> 0];
    assert.ok(got, `0x${id.toString(16)} (rgbMixer.${ch}) must be present`);
    assert.equal(got.name, `rgbMixer.${ch}`, `0x${id.toString(16)} names rgbMixer.${ch}`);
    assert.ok(Math.abs(got.value - want) < 1e-4, `rgbMixer.${ch} ≈ ${want} (got ${got.value})`);
  }
});
