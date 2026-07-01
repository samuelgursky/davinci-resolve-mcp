/** Matte Finesse + Blur Radius — VALIDATE-WIRE pass.
 * Live-measured 2026-06-22 on the calibration SMPTE-bars compound clip. Two results:
 * 1. The 6 swept Matte Finesse sliders (corrector type 9, 0x0c30002x/31) decode with correct
 * names + the /100 scale (UI 41–86 → 0.41–0.86). Confirms the 2026-03-22 CleanBlack/CleanWhite
 * name-swap correction is right (UI "Clean Black"=42 → 0x0c300024 cleanBlack=0.42).
 * 2. BUG FOUND + FIXED — Blur Radius (0x86000051) had registry value 2248146001 (typo vs its own
 * hex comment; 0x86000051 = 2248147025, off by 0x400) so it decoded as unknown_. Live: UI 46 →
 * 0.46. Same typo class as the Lum Mix bug. Now wired as qualifier.blurRadius (scale /100). */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { drxTool } from '../server/tools/drx.mjs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const params = require('../vendor/drx-parameters/parameter-ids.js');
const here = path.dirname(fileURLToPath(import.meta.url));
const content = fs.readFileSync(path.join(here, 'fixtures', 'matte-finesse-grid.drx'), 'utf8');

const EXPECTED = {
  0x0c300021: ['matteFinesse.blackClip', 0.44],
  0x0c300022: ['matteFinesse.whiteClip', 0.86],
  0x0c300023: ['matteFinesse.inOutRatio', 0.47],
  0x0c300024: ['matteFinesse.cleanBlack', 0.42],
  0x0c300025: ['matteFinesse.cleanWhite', 0.43],
  0x0c300031: ['matteFinesse.preFilter', 0.41],
  0x86000051: ['qualifier.blurRadius', 0.46],
};

test('Matte Finesse + Blur Radius decode to live-measured values (/100 scale, no unknown_)', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const got = {};
  for (const n of r.nodes)
    for (const c of n.correctors || [])
      for (const p of c.parameters || []) {
        got[p.id >>> 0] = { name: p.name, value: p.value };
      }
  for (const [id, [name, want]] of Object.entries(EXPECTED)) {
    const p = got[Number(id) >>> 0];
    assert.ok(p, `0x${Number(id).toString(16)} (${name}) must be present`);
    assert.equal(p.name, name, `0x${Number(id).toString(16)} names ${name}`);
    assert.ok(Math.abs(p.value - want) < 1e-3, `${name} ≈ ${want} (got ${p.value})`);
  }
});

test('Blur Radius registry constant matches its 0x86000051 hex (typo fix)', () => {
  assert.equal(params.HSL_QUALIFIER.BLUR_RADIUS, 0x86000051);
});
