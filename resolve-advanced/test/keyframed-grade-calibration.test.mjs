/** Keyframed grade decode. Added a static keyframe to node 01
 * of the the calibration rig 2026-06-22, Cmd+S, decoded.
 *
 * KEY FINDING + FIX: keyframing RELOCATES each corrector's values — F6 becomes a REPEATED field (a static
 * base block + a keyframe-track block carrying an extra F1 marker). The old parser read `corrector.F6.F2`
 * which is undefined when F6 is an array → it returned 0 params for ANY keyframed grade (a silent
 * robustness hole behind drx.parse/toolBreakdown). The parser now reads params from the base block and sets
 * node.keyframed=true; the drx tool's valueFidelity marker surfaces the flag. Full per-time curve decode
 * (the keyframe-track block) remains deferred — this recovers the base-keyframe snapshot. */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { drxTool } from '../server/tools/drx.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const content = fs.readFileSync(path.join(here, 'fixtures', 'keyframed-grade.drx'), 'utf8');

test('a keyframed grade still decodes its base params (not empty) and is flagged', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const kfNode = r.nodes.find((n) => n.keyframed);
  assert.ok(kfNode, 'a node is flagged keyframed (repeated F6 detected)');
  const total = kfNode.correctors.reduce((s, c) => s + c.parameters.length, 0);
  assert.ok(total >= 40, `keyframed node recovers its base params (got ${total}, must not be 0)`);
});

test('valueFidelity reports the keyframed node', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  assert.equal(r.valueFidelity.keyframed, true);
  assert.ok(r.valueFidelity.keyframedNodeCount >= 1);
  assert.match(r.valueFidelity.warning, /KEYFRAMED/);
});

test('known calibrated params survive the keyframe relocation (base block intact)', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const names = r.nodes.flatMap((n) => (n.correctors || []).flatMap((c) => c.parameters.map((p) => p.name)));
  // The kitchen-sink base grade is still readable through the keyframe relocation.
  assert.ok(names.includes('colorWarper.pin0.chromaRange'), 'Color Warper base value present');
  assert.ok(
    names.some((n) => n.startsWith('qualifier.rgb')),
    'RGB qualifier base values present',
  );
});
