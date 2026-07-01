/** 3D-mode qualifier — bounded attempt SUCCEEDED + Despill id CORRECTED.
 * Switched the qualifier to 3D mode on the the calibration rig 2026-06-22, drew a key stroke across the bars
 * (builds a 3D selection volume) and set Despill 35, Cmd+S, decoded the BARS grade.
 *
 * KEY FINDINGS:
 * - 3D-mode params DO serialize once a key stroke exists (the qualifier is actively keying) — not a hard
 * reach-limit. The selection VOLUME (0x0830002A) + extras (0x8830002E/32) + cspace (0x88300030) appear
 * as nested blobs; named (not deep-decoded — bounded scope).
 * - DESPILL id CORRECTED: the registry's 0x08300033 (137363507) is WRONG; the real id is 0x88300033
 * (2284847155). Despill 35 → stored 0.35 (scale /100).
 * Note: this fixture carries the RGB-mode ranges too (mode was switched without clearing) — harmless. */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { drxTool } from '../server/tools/drx.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const content = fs.readFileSync(path.join(here, 'fixtures', 'qualifier-3d.drx'), 'utf8');

function qualParams(nodes) {
  const out = {};
  for (const n of nodes) {
    for (const c of n.correctors || []) {
      if (c.type !== 2) continue;
      for (const p of c.parameters || []) out[p.name] = p.value;
    }
  }
  return out;
}

test('3D qualifier Despill decodes at the corrected id (0x88300033, /100)', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const q = qualParams(r.nodes);
  assert.ok(Math.abs(q['qualifier.despill3d'] - 0.35) < 1e-4, `Despill 0.35 (got ${q['qualifier.despill3d']})`);
});

test('3D selection volume + extras are named (no unknown_ on ct2)', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const q = qualParams(r.nodes);
  assert.ok('qualifier.volume3d' in q, '3D selection volume named');
  assert.ok('qualifier.cspace3d' in q, '3D cspace named');
  const names = Object.keys(q);
  assert.ok(!names.some((n) => n.startsWith('unknown_')), 'no unknown_ qualifier params');
});

test('3D selection volume BLOB decoded: header + sample point cloud (RE 2026-07-02)', async () => {
  // Byte-level RE off this fixture: value envelope {F5: buffer} = 9×uint64 BE header
  // (field 8 = sample count) + count × 3 float32 LE (x, y, radius) — the keyer's sampled
  // chroma-plane stroke path. This closes the last offline-reachable opaque blob.
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const vol = r.nodes.map((n) => n.params?.qualifier3d).find(Boolean);
  assert.ok(vol, 'qualifier3d lifted');
  assert.equal(vol.count, 8, 'header sample count 8');
  assert.equal(vol.samples.length, 8, '8 samples decoded');
  // First stroke sample of the fixture's key stroke; radius constant 0.015.
  assert.ok(Math.abs(vol.samples[0].x - 215) < 1e-3 && Math.abs(vol.samples[0].y - 99) < 1e-3, 'first sample (215, 99)');
  assert.ok(vol.samples.every((s) => Math.abs(s.radius - 0.015) < 1e-4), 'radius 0.015 on all samples');
});
