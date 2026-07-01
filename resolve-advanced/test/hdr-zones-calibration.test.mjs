/** HDR Zones — Tier-2 parser extension + VALIDATE.
 * HDR zone Exp/Sat live in a NESTED protobuf blob (ZONE_ADJUSTMENTS 0x86000305), keyed by
 * embedded zone-name strings, so they previously surfaced as one opaque object (NaN-equivalent).
 * RE'd 2026-06-22 on the calibration SMPTE-bars compound clip: each F1[] zone sub-message is
 * 0a<len><name> 15<f32 exposure> 1d<f32 cbalY> 25<f32 cbalX> 3d<f32 saturation>.
 * Parser now lifts them into hdrZone.<zone>.{exposure,saturation,colorBalanceX/Y}. Swept
 * exposure Dark→Highlight = 1.1/1.2/1.3/1.4, Global = 1.5 (exact); Sat clamped at 2.0 (UI max,
 * NOT the 4.0 the registry comment claimed). */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { drxTool } from '../server/tools/drx.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const content = fs.readFileSync(path.join(here, 'fixtures', 'hdr-zones-grid.drx'), 'utf8');

const EXPECTED_EXPOSURE = { dark: 1.1, shadow: 1.2, light: 1.3, highlight: 1.4, global: 1.5 };

test('HDR zones decode into named per-zone params (not an opaque blob)', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const byName = {};
  for (const n of r.nodes)
    for (const c of n.correctors || [])
      for (const p of c.parameters || []) {
        if (p.name && p.name.startsWith('hdrZone.')) byName[p.name] = p.value;
      }
  for (const [zone, exp] of Object.entries(EXPECTED_EXPOSURE)) {
    const got = byName[`hdrZone.${zone}.exposure`];
    assert.ok(got !== undefined, `hdrZone.${zone}.exposure present`);
    assert.ok(Math.abs(got - exp) < 1e-3, `hdrZone.${zone}.exposure ≈ ${exp} (got ${got})`);
    assert.equal(byName[`hdrZone.${zone}.saturation`], 2, `hdrZone.${zone}.saturation = 2 (UI clamp)`);
  }
});

test('node.params.hdrZones carries all 5 named zones', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const hz = r.nodes.map((n) => n.params && n.params.hdrZones).find(Boolean);
  assert.ok(hz, 'node.params.hdrZones present');
  const names = hz.map((z) => z.name).sort();
  assert.deepEqual(names, ['Dark', 'Global', 'Highlight', 'Light', 'Shadow']);
});
