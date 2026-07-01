/** valueFidelity flag on the drx tool.
 * parse + export_cdl must carry a `valueFidelity` marker so decoded values aren't mistaken for
 * ground truth, and a keyframed grade (per-corrector params relocated to a track block the static
 * decoder doesn't read) must be flagged. Uses the live-captured kitchen-sink fixtures. */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { drxTool, computeValueFidelity, countKeyframedNodes } from '../server/tools/drx.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const colorWarper = fs.readFileSync(path.join(here, 'fixtures', 'color-warper.drx'), 'utf8');

test('parse output carries a calibrated-subset-only valueFidelity marker', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content: colorWarper } });
  assert.ok(r.valueFidelity, 'valueFidelity present');
  assert.equal(r.valueFidelity.level, 'calibrated-subset-only');
  assert.match(r.valueFidelity.note, /NOT ground truth/);
});

test('a non-keyframed grade is not flagged as keyframed', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content: colorWarper } });
  assert.ok(!r.valueFidelity.keyframed, 'clean grade not flagged keyframed');
});

test('export_cdl carries valueFidelity + the CDL-conversion caveat', async () => {
  const r = await drxTool.handler({ action: 'export_cdl', args: { content: colorWarper } });
  assert.ok(r.valueFidelity, 'valueFidelity present on export_cdl');
  assert.match(r.valueFidelity.cdlNote, /approximate by design/);
});

test('the keyframe-relocation signature is detected and flagged', async () => {
  // Keyframed node: ≥1 corrector present, all with 0 params, no lifted structured data.
  const keyframedNodes = [{ correctors: Array.from({ length: 12 }, (_, i) => ({ type: i + 1, parameters: [] })), params: {} }];
  assert.equal(countKeyframedNodes(keyframedNodes), 1);
  const f = computeValueFidelity(keyframedNodes);
  assert.equal(f.keyframed, true);
  assert.equal(f.keyframedNodeCount, 1);
  assert.match(f.warning, /KEYFRAMED/);
});

test('the keyframe signature is specific (clean + identity nodes not flagged)', async () => {
  // Real grade with populated correctors.
  const populated = [{ correctors: [{ type: 1, parameters: [{ id: 1, value: 1 }] }], params: {} }];
  assert.equal(countKeyframedNodes(populated), 0);
  // Identity node (no correctors at all) — not keyframed.
  assert.equal(countKeyframedNodes([{ correctors: [], params: {} }]), 0);
  // Node whose only output is lifted structured data (e.g. colorWarper) — not keyframed.
  const lifted = [{ correctors: [{ type: 1, parameters: [] }], params: { colorWarper: [{ id: 1 }] } }];
  assert.equal(countKeyframedNodes(lifted), 0);
});
