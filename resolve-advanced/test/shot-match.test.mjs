/**
 * shot_match (C1) — deterministic, no Resolve. Asserts per-channel median tone, the
 * gray-world neutralize mode, the hero-match mode, median robustness to a coloured
 * object, and the mode guards.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { measureToneRGB, computeShotMatch } from '../server/shot-match.mjs';

const require = createRequire(import.meta.url);
const sharp = require('sharp');

/** Solid WxH PNG of one colour, optionally with a `blob` of another colour over `blobFrac` of rows. */
async function flat(file, color, { w = 64, h = 64, blob = null, blobFrac = 0 } = {}) {
  const buf = Buffer.alloc(w * h * 3);
  const blobRows = Math.round(h * blobFrac);
  for (let y = 0; y < h; y++) {
    const c = blob && y < blobRows ? blob : color;
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 3;
      buf[i] = c.r;
      buf[i + 1] = c.g;
      buf[i + 2] = c.b;
    }
  }
  await sharp(buf, { raw: { width: w, height: h, channels: 3 } })
    .png()
    .toFile(file);
}

test('measureToneRGB median tracks dominant tone, ignores a minority colour blob', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'shot-'));
  const f = path.join(dir, 'warm.png');
  // 70% warm gray, 30% saturated red blob — the MEDIAN should stay on the warm gray.
  await flat(f, { r: 120, g: 110, b: 90 }, { blob: { r: 240, g: 10, b: 10 }, blobFrac: 0.3 });
  const t = await measureToneRGB(f);
  assert.ok(Math.abs(t.median.r - 120) <= 2, `r=${t.median.r}`);
  assert.ok(Math.abs(t.median.g - 110) <= 2, `g=${t.median.g}`);
  assert.ok(Math.abs(t.median.b - 90) <= 2, `b=${t.median.b}`);
});

test('neutralize: gray-world pulls a warm shot toward neutral, preserving luma', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'shot-'));
  const warm = path.join(dir, 'warm.png');
  await flat(warm, { r: 150, g: 120, b: 90 }); // luma 120
  const r = await computeShotMatch([{ id: 'w', png: warm }], { outDir: path.join(dir, 'out') });
  const g = r.grades[0].gain;
  // gain.c = 120 / channel → r down, b up, g ~unity. Applied → all channels ~120 (neutral).
  assert.ok(Math.abs(g.r - 120 / 150) < 0.02, `r ${g.r}`);
  assert.ok(Math.abs(g.b - 120 / 90) < 0.02, `b ${g.b}`);
  assert.ok(Math.abs(g.g - 1) < 0.02, `g ${g.g}`);
  assert.equal(r.grades[0].mode, 'neutralize');
});

test('hero: each shot matches the hero plate median', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'shot-'));
  const hero = path.join(dir, 'hero.png');
  const cool = path.join(dir, 'cool.png');
  await flat(hero, { r: 130, g: 120, b: 110 });
  await flat(cool, { r: 100, g: 120, b: 150 });
  const r = await computeShotMatch(
    [
      { id: 'hero', png: hero, scene: 's1' },
      { id: 'cool', png: cool, scene: 's1' },
    ],
    { outDir: path.join(dir, 'out'), mode: 'hero', heroId: 'hero' },
  );
  const cg = r.grades.find((x) => x.id === 'cool').gain;
  assert.ok(Math.abs(cg.r - 130 / 100) < 0.02, `r ${cg.r}`); // pull warm
  assert.ok(Math.abs(cg.b - 110 / 150) < 0.02, `b ${cg.b}`); // pull down blue
  const hg = r.grades.find((x) => x.id === 'hero');
  assert.ok(hg.correctionPct < 1, 'hero ~unity');
});

test('GUARD: hero mode without heroId throws', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'shot-'));
  const f = path.join(dir, 'a.png');
  await flat(f, { r: 120, g: 120, b: 120 });
  await assert.rejects(() => computeShotMatch([{ id: 'a', png: f }], { outDir: path.join(dir, 'out'), mode: 'hero' }), /requires opts\.heroId/);
});
