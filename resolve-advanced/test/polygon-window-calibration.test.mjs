/** Polygon window — vertex geometry RE'd + registry claim CORRECTED.
 * Drew a 4-vertex polygon window on the the calibration rig 2026-06-22, Cmd+S, decoded the BARS grade.
 *
 * KEY FINDINGS:
 * - The registry's "POLYGON_WINDOW DECODED 2026-03-23" claim (vertices in 0x08B00006, corrector type 5,
 * {F1=X, F2=Y}) does NOT match live data — no 0x08B0 params appeared at all. That block is UNVALIDATED.
 * - The REAL polygon shape lives under CORRECTOR TYPE 6. Its vertices are in 0x08D00006/07/08 as F9.F1[]
 * point sub-messages — the SAME `0d<f32 x>15<f32 y>` codec as curve splines, but under F9 (splines F8) —
 * in FRAME-PIXELS from center. Each corner repeats ~3× (bezier handle ring) and the ring closes on the
 * first vertex. A 3×3 identity matrix sits at 0x88D00014 (same structural container as the gradient window).
 * - The 0x08D00xxx ids are registered under LUM_MIX.PARAM_1–11 (correctorType 5) in the registry. A sweeping
 * symbol rename is DEFERRED (the LUM_MIX/ct5 pathway is woven through the generator + drp-format and ct5↔ct6
 * id reuse wasn't measured safe). Instead the decoder RELABELS them as `polygonWindow.*` when they appear
 * under ct6 (POLYGON_NAME_BY_ID — the same ct-aware pattern as GRADIENT_NAME_BY_ID), and surfaces the actual
 * geometry additively via node.params.polygonVertices / polygonMatrix. */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { drxTool } from '../server/tools/drx.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const content = fs.readFileSync(path.join(here, 'fixtures', 'polygon-window.drx'), 'utf8');

const uniq = (pts) => {
  const seen = new Set();
  const out = [];
  for (const p of pts) {
    const k = `${Math.round(p.x * 10)}:${Math.round(p.y * 10)}`;
    if (!seen.has(k)) {
      seen.add(k);
      out.push(p);
    }
  }
  return out;
};

test('Polygon shape vertices decode (ct6, F9 point ring, frame-pixels)', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const node = r.nodes.find((n) => n.params?.polygonVertices);
  assert.ok(node, 'a node exposes params.polygonVertices');
  const verts = uniq(node.params.polygonVertices);
  assert.equal(verts.length, 4, '4 unique polygon corners');

  // Frame-pixel space (1920×1080 → |x| ≤ 960, |y| ≤ 540).
  for (const p of verts) {
    assert.ok(Math.abs(p.x) <= 960, `x in frame (got ${p.x})`);
    assert.ok(Math.abs(p.y) <= 540, `y in frame (got ${p.y})`);
  }

  // The drawn quadrilateral (measured), order-independent.
  const expected = [
    { x: -302.57, y: 280.16 },
    { x: 388.48, y: 179.3 },
    { x: 287.63, y: -410.89 },
    { x: -448.25, y: -313.77 },
  ];
  for (const e of expected) {
    assert.ok(
      verts.some((p) => Math.abs(p.x - e.x) < 1 && Math.abs(p.y - e.y) < 1),
      `vertex ~(${e.x}, ${e.y}) present`,
    );
  }
});

test('ct6 polygon params relabel to polygonWindow.* (not lumMix.*)', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const names = r.nodes.flatMap((n) => (n.correctors || []).filter((c) => c.type === 6).flatMap((c) => c.parameters.map((p) => p.name)));
  assert.ok(names.length > 0, 'ct6 corrector has params');
  assert.ok(
    names.some((n) => n.startsWith('polygonWindow.')),
    'params labeled polygonWindow.*',
  );
  assert.ok(!names.some((n) => n.startsWith('lumMix.')), 'no lumMix.* labels on the polygon corrector');
});

test('Polygon shape carries a 3×3 identity matrix (0x88D00014)', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const node = r.nodes.find((n) => n.params?.polygonMatrix);
  assert.ok(node, 'a node exposes params.polygonMatrix');
  assert.deepEqual(node.params.polygonMatrix, [1, 0, 0, 0, 1, 0, 0, 0, 1]);
});
