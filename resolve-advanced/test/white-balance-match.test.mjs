/**
 * white_balance_match (C3) — deterministic, no Resolve. Builds frames where a CORNER
 * patch is a known colour over a different-coloured field, and asserts that WB is
 * computed from the PATCH (not the field) — the distinction from gray-world shot_match.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { measurePatchMeanRGB, computeWhiteBalanceMatch } from '../server/white-balance-match.mjs';

const require = createRequire(import.meta.url);
const sharp = require('sharp');

/** WxH PNG: a `patch` colour fills the top-left quarter; rest is `field`. */
async function withPatch(file, patch, field, { w = 64, h = 64 } = {}) {
  const buf = Buffer.alloc(w * h * 3);
  for (let y = 0; y < h; y++)
    for (let x = 0; x < w; x++) {
      const c = x < w / 2 && y < h / 2 ? patch : field;
      const i = (y * w + x) * 3;
      buf[i] = c.r;
      buf[i + 1] = c.g;
      buf[i + 2] = c.b;
    }
  await sharp(buf, { raw: { width: w, height: h, channels: 3 } })
    .png()
    .toFile(file);
}

const TL = { x: 0, y: 0, w: 0.5, h: 0.5 }; // top-left patch

test('measurePatchMeanRGB reads only the rect, ignoring the field', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'wb-'));
  const f = path.join(dir, 'a.png');
  await withPatch(f, { r: 150, g: 120, b: 90 }, { r: 10, g: 200, b: 10 }); // warm patch, green field
  const m = await measurePatchMeanRGB(f, TL);
  assert.ok(Math.abs(m.r - 150) < 2 && Math.abs(m.g - 120) < 2 && Math.abs(m.b - 90) < 2, JSON.stringify(m));
});

test('neutralize computes WB from the warm patch (not the green field)', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'wb-'));
  const f = path.join(dir, 'warm.png');
  await withPatch(f, { r: 150, g: 120, b: 90 }, { r: 10, g: 200, b: 10 });
  const r = await computeWhiteBalanceMatch([{ id: 'a', png: f, rect: TL }], { outDir: path.join(dir, 'out') });
  const g = r.grades[0].gain;
  // patch luma 120 → gain.r=120/150, gain.b=120/90; green field would have given totally different gains.
  assert.ok(Math.abs(g.r - 120 / 150) < 0.02, `r ${g.r}`);
  assert.ok(Math.abs(g.b - 120 / 90) < 0.02, `b ${g.b}`);
});

test('hero mode matches each patch to the hero patch', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'wb-'));
  const hero = path.join(dir, 'hero.png');
  const cool = path.join(dir, 'cool.png');
  await withPatch(hero, { r: 130, g: 120, b: 110 }, { r: 0, g: 0, b: 0 });
  await withPatch(cool, { r: 100, g: 120, b: 150 }, { r: 0, g: 0, b: 0 });
  const r = await computeWhiteBalanceMatch(
    [
      { id: 'hero', png: hero, rect: TL },
      { id: 'cool', png: cool, rect: TL },
    ],
    { outDir: path.join(dir, 'out'), mode: 'hero', heroId: 'hero' },
  );
  const cg = r.grades.find((x) => x.id === 'cool').gain;
  assert.ok(Math.abs(cg.r - 130 / 100) < 0.02 && Math.abs(cg.b - 110 / 150) < 0.02, JSON.stringify(cg));
});

test('GUARD: hero without heroId throws', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'wb-'));
  const f = path.join(dir, 'a.png');
  await withPatch(f, { r: 120, g: 120, b: 120 }, { r: 0, g: 0, b: 0 });
  await assert.rejects(
    () => computeWhiteBalanceMatch([{ id: 'a', png: f, rect: TL }], { outDir: path.join(dir, 'out'), mode: 'hero' }),
    /requires opts\.heroId/,
  );
});
