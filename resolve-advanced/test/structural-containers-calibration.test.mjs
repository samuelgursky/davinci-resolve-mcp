/** Structural containers — completeness-sweep residuals NAMED 2026-06-22.
 * The full kitchen-sink completeness sweep left exactly two residual unknown_ params, both
 * nested structural/enable containers rather than scalar values:
 * - 0x0830006f (137363567) under the qualifier corrector (ct2): value envelope { F2: <varint> } =
 * an internal qualifier mode flag (registry MODE_FLAG; observed value 4). Now lifts as
 * qualifier.modeFlag with the bare varint.
 * - 0x88f0000d (2297430029) under the gradient corrector (ct65554): value envelope { F10: { F1..F9 } } =
 * a row-major 3×3 matrix (identity by default). Now lifts as gradientWindow.matrix → 9-cell array.
 * Both are RE'd off the gradient-window fixture (a live BARS capture that happens to carry an active
 * qualifier + an active gradient window), so this is a live-measured structural decode, not speculation.
 * The exact semantic role of the 3×3 matrix (color vs orientation) is unconfirmed; the STRUCTURE is. */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { drxTool } from '../server/tools/drx.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const content = fs.readFileSync(path.join(here, 'fixtures', 'gradient-window.drx'), 'utf8');

test('Structural containers decode named (no residual unknown_)', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const byId = {};
  for (const n of r.nodes)
    for (const c of n.correctors || []) {
      for (const p of c.parameters || []) byId[p.id >>> 0] = p;
    }

  // Qualifier mode flag (ct2) — lifted varint, named (not unknown_)
  const modeFlag = byId[0x0830006f];
  assert.equal(modeFlag?.name, 'qualifier.modeFlag');
  assert.equal(modeFlag.value, 4, 'observed internal mode flag = 4');

  // Gradient 3×3 matrix (ct65554) — lifted 9-cell array, identity in this fixture
  const matrix = byId[0x88f0000d];
  assert.equal(matrix?.name, 'gradientWindow.matrix');
  assert.deepEqual(matrix.value, [1, 0, 0, 0, 1, 0, 0, 0, 1], 'row-major identity matrix');

  // Neither should remain an unknown_ object
  assert.ok(!String(modeFlag.name).startsWith('unknown_'));
  assert.ok(!String(matrix.name).startsWith('unknown_'));
});

test('Gradient matrix is also surfaced on node.params.gradientMatrix', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const withMatrix = r.nodes.find((n) => n.params && n.params.gradientMatrix);
  assert.ok(withMatrix, 'a node exposes params.gradientMatrix');
  assert.equal(withMatrix.params.gradientMatrix.length, 9);
});
