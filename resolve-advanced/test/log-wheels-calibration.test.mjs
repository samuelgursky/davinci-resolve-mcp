/** Log Wheels + Log Range — VALIDATE-WIRE pass.
 * LOG_WHEELS (0x860000c2–ca) + CONTRAST.LOW/HIGH_RANGE (0xcb/0xcc) were wired but never
 * live-confirmed. Live-measured 2026-06-22 on the calibration SMPTE-bars compound clip:
 * Shadow/Midtone/Highlight RGB = 0.21–0.29, Low Range = 0.321, High Range UI 0.456.
 * All 9 wheel cells = identity; Low Range = identity; HIGH RANGE INVERTED (stored 0.544 =
 * 1.0 − 0.456) — confirming the registry's "DRX = 1.0 − UI" note. Fixture is that live grade
 * (also carries the prior RGB-mixer sweep on the same node; this test only checks log params). */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { drxTool } from '../server/tools/drx.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const content = fs.readFileSync(path.join(here, 'fixtures', 'log-wheels-grid.drx'), 'utf8');

// id → [name, expected stored value]
const EXPECTED = {
  0x860000c2: ['logShadow.r', 0.21],
  0x860000c3: ['logShadow.g', 0.22],
  0x860000c4: ['logShadow.b', 0.23],
  0x860000c5: ['logMidtone.r', 0.24],
  0x860000c6: ['logMidtone.g', 0.25],
  0x860000c7: ['logMidtone.b', 0.26],
  0x860000c8: ['logHighlight.r', 0.27],
  0x860000c9: ['logHighlight.g', 0.28],
  0x860000ca: ['logHighlight.b', 0.29],
  0x860000cb: ['lowRange.master', 0.321], // identity
  0x860000cc: ['highRange.master', 0.544], // INVERTED: 1.0 − UI(0.456)
};

test('Log wheels + ranges decode to live-measured values (incl. High Range 1.0−UI inversion)', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const params = {};
  for (const n of r.nodes)
    for (const c of n.correctors || [])
      for (const p of c.parameters || []) {
        params[p.id >>> 0] = { name: p.name, value: p.value };
      }
  for (const [id, [name, want]] of Object.entries(EXPECTED)) {
    const got = params[Number(id) >>> 0];
    assert.ok(got, `0x${Number(id).toString(16)} (${name}) must be present`);
    assert.equal(got.name, name, `0x${Number(id).toString(16)} names ${name}`);
    assert.ok(Math.abs(got.value - want) < 1e-3, `${name} ≈ ${want} (got ${got.value})`);
  }
});
