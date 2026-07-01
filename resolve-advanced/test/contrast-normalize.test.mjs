/**
 * contrast_normalize (C3) — deterministic, no Resolve. Builds a hero with a wide tonal
 * range and a low-contrast clip, and asserts the affine fit expands the clip toward the
 * hero's black/white points (gain > 1) and the grade round-trips non-empty.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { measureBWPoints, computeContrastNormalize } from '../server/contrast-normalize.mjs';

const require = createRequire(import.meta.url);
const sharp = require('sharp');

/** A vertical gradient between lo and hi (gray), so black/white points are lo/hi. */
async function gradient(file, lo, hi, { w = 64, h = 64 } = {}) {
  const buf = Buffer.alloc(w * h * 3);
  for (let y = 0; y < h; y++) {
    const v = Math.round(lo + (hi - lo) * (y / (h - 1)));
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 3;
      buf[i] = v;
      buf[i + 1] = v;
      buf[i + 2] = v;
    }
  }
  await sharp(buf, { raw: { width: w, height: h, channels: 3 } })
    .png()
    .toFile(file);
}

test('measureBWPoints recovers black/white points (normalized)', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cn-'));
  const f = path.join(dir, 'g.png');
  await gradient(f, 40, 200);
  const bw = await measureBWPoints(f, { lowPct: 2, highPct: 98 });
  assert.ok(Math.abs(bw.r.black - 40 / 255) < 0.03, `black ${bw.r.black}`);
  assert.ok(Math.abs(bw.r.white - 200 / 255) < 0.03, `white ${bw.r.white}`);
});

test('a low-contrast clip is expanded toward the hero range (gain > 1)', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cn-'));
  const hero = path.join(dir, 'hero.png');
  const flat = path.join(dir, 'flat.png');
  await gradient(hero, 16, 235); // full range
  await gradient(flat, 80, 160); // compressed
  const r = await computeContrastNormalize(
    [
      { id: 'hero', png: hero, group: 'G' },
      { id: 'flat', png: flat, group: 'G' },
    ],
    { outDir: path.join(dir, 'out') },
  );
  const fg = r.grades.find((g) => g.id === 'flat');
  const hg = r.grades.find((g) => g.id === 'hero');
  // hero maps to itself ≈ identity; flat needs to STRETCH → gain > 1.
  assert.ok(hg.correctionPct < 2, `hero corr ${hg.correctionPct}`);
  assert.ok(fg.gain.r > 1.2, `flat gain ${fg.gain.r}`);
  assert.ok(fs.existsSync(fg.drxPath), 'DRX written');
});
