/** Curve window SHAPE geometry. Drew a closed 4-point
 * Curve window on a fresh serial node (node 02) of the the calibration rig 2026-06-22, Cmd+S, decoded.
 *
 * KEY FINDING (measured, not assumed): the Curve window reuses the EXACT same storage as the polygon —
 * corrector type 6, ids 0x08D00002–0x08D00011 + the 3×3 matrix at 0x88D00014, with the freeform shape as
 * an F9.F1[] bezier vertex ring (corners + handles) in frame-pixels. So no new decoder was needed: the
 * existing polygon path (decodePolygonVertices → node.params.polygonVertices) + the ct6 polygonWindow.*
 * relabel cover it. Polygon vs Curve differ only by the window.type flag (3 vs 4) on the ct4 transform. */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { drxTool } from '../server/tools/drx.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const content = fs.readFileSync(path.join(here, 'fixtures', 'curve-window.drx'), 'utf8');

test('Curve window decodes as a ct6 frame-pixel vertex ring (shared polygon codec)', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  // The curve window is on the second node; find the node carrying ONLY the ct6 shape corrector.
  const curveNode = r.nodes.find((n) => (n.correctors || []).length >= 1 && (n.correctors || []).every((c) => c.type === 6));
  assert.ok(curveNode, 'a node holds only the ct6 curve/polygon shape corrector');
  const verts = curveNode.params.polygonVertices;
  assert.ok(Array.isArray(verts) && verts.length >= 4, `curve vertex ring decoded (got ${verts?.length})`);
  for (const p of verts) {
    assert.ok(Math.abs(p.x) <= 960 && Math.abs(p.y) <= 540, `vertex in frame-pixel space (${p.x},${p.y})`);
  }
});

test('Curve window ct6 params relabel to polygonWindow.* + carry the 3×3 matrix', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const curveNode = r.nodes.find((n) => (n.correctors || []).length >= 1 && (n.correctors || []).every((c) => c.type === 6));
  const names = curveNode.correctors.flatMap((c) => c.parameters.map((p) => p.name));
  assert.ok(
    names.some((n) => n.startsWith('polygonWindow.')),
    'ct6 params labeled polygonWindow.*',
  );
  assert.ok(!names.some((n) => n.startsWith('lumMix.')), 'no lumMix.* labels');
  assert.deepEqual(curveNode.params.polygonMatrix, [1, 0, 0, 0, 1, 0, 0, 0, 1]);
});
