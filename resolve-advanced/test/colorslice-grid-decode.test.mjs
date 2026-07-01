/** Tier-2 parser extension: the ColorSlice per-vector grid
 * (param 0x86000606, F24 → 7 sub-messages) was previously an opaque NaN scalar.
 * The parser now lifts it into named per-vector params (colorSlice.<vector>.{enabled,
 * sat,hue}). Fixture `colorslice-grid.drx` is a real grade captured live 2026-06-22
 * with per-vector Hue swept Red 0.61 → Magenta 0.89 (stored negated; decoder un-negates). */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { drxTool } from '../server/tools/drx.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const content = fs.readFileSync(path.join(here, 'fixtures', 'colorslice-grid.drx'), 'utf8');

const EXPECTED_HUE = { red: 0.61, skin: 0.67, yellow: 0.71, green: 0.73, cyan: 0.79, blue: 0.83, magenta: 0.89 };
const EXPECTED_CENTER = { red: 0.31, skin: 0.37, yellow: 0.41, green: 0.43, cyan: 0.47, blue: 0.53, magenta: 0.59 };

test('ColorSlice per-vector grid decodes hue + center into named params (not NaN)', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const cs = r.nodes.map((n) => n.params && n.params.colorSlice).find(Boolean);
  assert.ok(cs, 'node.params.colorSlice present');
  assert.equal(cs.length, 7, '7 vectors');
  for (const v of cs) {
    assert.ok(Math.abs(v.hue - EXPECTED_HUE[v.vector]) < 0.01, `${v.vector} hue ≈ ${EXPECTED_HUE[v.vector]} (got ${v.hue})`);
    assert.ok(Math.abs(v.center - EXPECTED_CENTER[v.vector]) < 0.01, `${v.vector} center ≈ ${EXPECTED_CENTER[v.vector]} (got ${v.center})`);
  }
});

test('no parameter decodes to NaN after the grid extension', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  for (const n of r.nodes)
    for (const c of n.correctors || [])
      for (const p of c.parameters || []) {
        assert.ok(!Number.isNaN(p.value), `${p.name} should not be NaN`);
      }
});
