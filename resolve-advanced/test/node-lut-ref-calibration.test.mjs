/** Node LUT reference — registry decoder VERIFIED LIVE. Attached the built-in
 * "FilmUnlimited_2383_Rec709_Finished" LUT to node 01 on the the calibration rig 2026-06-22 (right-click → LUT),
 * Cmd+S, decoded the BARS grade.
 *
 * Unlike the Color Warper / polygon registry claims (both WRONG when measured), the NODE_LUT_REF
 * "DECODED 2026-06-19" claim HOLDS against live R21 data:
 * - SLOT_META 0x860000A0 = varint 6 (present)
 * - LUT_PATH 0x860000A1 = the LUT basename in the value envelope's F5 string
 * `extract-lut-refs.js` (extractDrxLutRefs / extractNodeLutRef) resolves both end-to-end. */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { drxTool } from '../server/tools/drx.mjs';
import lutmod from '../vendor/drx-codec/extract-lut-refs.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const content = fs.readFileSync(path.join(here, 'fixtures', 'node-lut-ref.drx'), 'utf8');

test('extractDrxLutRefs resolves the attached node LUT (path + slot)', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const refs = lutmod.extractDrxLutRefs(r);
  assert.equal(refs.length, 1, 'one node LUT reference');
  assert.equal(refs[0].lutPath, 'FilmUnlimited_2383_Rec709_Finished.cube', 'LUT basename from F5');
  assert.equal(refs[0].slotMeta, 6, 'SLOT_META varint = 6');
  assert.equal(refs[0].source, 'drx_node');
});

test('extractNodeLutRef finds the LUT on the graded node', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const hit = r.nodes.map((n) => lutmod.extractNodeLutRef(n)).find(Boolean);
  assert.ok(hit, 'a node carries a LUT ref');
  assert.equal(hit.lutPath, 'FilmUnlimited_2383_Rec709_Finished.cube');
});
