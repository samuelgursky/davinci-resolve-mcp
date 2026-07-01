/** Color-group pre/post grades — STORAGE resolved. Added the calibration clip to a
 * color group 2026-06-22, applied a Pre-Clip group grade (Saturation 77), Cmd+S, inspected Project.db.
 *
 * KEY FINDING: a color-group's Pre-Clip / Post-Clip grades are NOT folded into the clip's own grade Body.
 * They are stored as SEPARATE `ListMgt::LmVersion` rows (HasCorrection=1) keyed to the group (Sm2Group),
 * in the SAME DRX Body format as a clip grade — so the existing decoder handles them unchanged (validated:
 * the Pre-Clip Saturation 77 decodes to 1.54 = UI/50). The only thing missing is a READ PATH (group →
 * LmVersion join, analogous to clip → pLmVerTable); there is no decoder gap. This fixture is that group
 * grade's Body, captured straight from the second LmVersion row. */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { drxTool } from '../server/tools/drx.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const content = fs.readFileSync(path.join(here, 'fixtures', 'group-preclip-grade.drx'), 'utf8');

test('a color-group Pre-Clip grade is a standard decodable DRX Body', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  assert.ok(r.nodes.length >= 1, 'group grade decodes a node graph');
  const sats = r.nodes.flatMap((n) => (n.correctors || []).flatMap((c) => c.parameters.filter((p) => /saturation/i.test(p.name)).map((p) => p.value)));
  assert.ok(
    sats.some((v) => Math.abs(v - 1.54) < 1e-3),
    `Pre-Clip Saturation 77 → 1.54 (got ${sats})`,
  );
});
