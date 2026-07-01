/** Power Windows (circle) — VALIDATE-WIRE + NEW params.
 * Live-measured 2026-06-22 on the calibration SMPTE-bars compound clip with a Circle window:
 * Size 61 / Aspect 62 / Pan 63 / Tilt 64 / Rotate 65 / Opacity 66 / Soft1 67. Results (corr type 4):
 * - ROTATE/SIZE/ASPECT/PAN/TILT IDs (0x085000{01,04,06,0B,0C}) confirmed present but in normalized/
 * pixel space (Pan 63→1064.96, Tilt 64→1146.88) — exact scale needs a multi-point fit, not asserted.
 * - SOFT_REF (0x08500005) = Soft1 × 16 CONFIRMED (67 → 1072). REF_WIDTH (0x8850000D) = 288.
 * - BUG/GAP FIXED: OPACITY (0x08500012) was entirely missing → unknown_; UI 66 → 0.66 (/100), now wired.
 * - REF_WIDTH/UNK_0E/UNK_0F/TRACKING_BLOB were defined but absent from PARAM_ID_MAP (decoded unknown_);
 * now mapped (window.refWidth/unk0e/unk0f/trackingBlob). */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { drxTool } from '../server/tools/drx.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const content = fs.readFileSync(path.join(here, 'fixtures', 'power-window-circle.drx'), 'utf8');

test('Power window params decode to named (opacity /100, softRef = Soft1×16, refWidth 288)', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const byId = {};
  for (const n of r.nodes)
    for (const c of n.correctors || [])
      for (const p of c.parameters || []) {
        byId[p.id >>> 0] = { name: p.name, value: p.value };
      }
  // exact, scale-validated params
  assert.equal(byId[0x08500012].name, 'window.opacity');
  assert.ok(Math.abs(byId[0x08500012].value - 0.66) < 1e-3, `opacity 0.66 (got ${byId[0x08500012].value})`);
  assert.equal(byId[0x08500005].name, 'window.softRef');
  assert.equal(byId[0x08500005].value, 1072, 'softRef = Soft1(67) × 16');
  assert.equal(byId[0x8850000d].name, 'window.refWidth');
  assert.equal(byId[0x8850000d].value, 288);
  // IDs present + named. NOTE: 0x08500004 = ASPECT and 0x08500006 = SIZE (the registry had these
  // two SWAPPED; corrected 2026-06-22 — see power-window-transform-calibration.test.mjs).
  for (const [id, name] of [
    [0x08500001, 'window.rotate'],
    [0x08500004, 'window.aspect'],
    [0x08500006, 'window.size'],
    [0x0850000b, 'window.pan'],
    [0x0850000c, 'window.tilt'],
  ]) {
    assert.equal(byId[id]?.name, name, `0x${id.toString(16)} → ${name}`);
  }
});

test('no window param decodes as unknown_ after wiring opacity + the 4 unmapped constants', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  for (const n of r.nodes)
    for (const c of n.correctors || [])
      for (const p of c.parameters || []) {
        if (p.id >>> 0 >= 0x08500000 && p.id >>> 0 <= 0x88500010) {
          assert.ok(!String(p.name).startsWith('unknown_'), `${p.id >>> 0} (${p.name}) should be named`);
        }
      }
});
