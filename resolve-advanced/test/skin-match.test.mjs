/**
 * skin_match (C2) — deterministic, no Resolve. Synthesizes frames with known skin /
 * non-skin pixels and asserts the gate, the masked mean, the cross-clip gain match,
 * and the two silent-lie guards (skip low-skin clips; throw on no-skin-anywhere).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { isSkin, measureSkinMeanRGB, computeSkinMatch } from '../server/skin-match.mjs';

const require = createRequire(import.meta.url);
const sharp = require('sharp');

const SKIN = { r: 200, g: 140, b: 110 }; // clears the Kovac rule
const SKIN_DARK = { r: 150, g: 100, b: 80 };
const BLUE = { r: 20, g: 40, b: 160 }; // background, never skin

/** Write a WxH PNG: top `skinRows` of pixels are `skin`, rest are `bg`. */
async function frame(file, { w = 64, h = 64, skinRows = 32, skin = SKIN, bg = BLUE }) {
  const buf = Buffer.alloc(w * h * 3);
  for (let y = 0; y < h; y++) {
    const c = y < skinRows ? skin : bg;
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

test('isSkin gate accepts skin tones, rejects background', () => {
  assert.ok(isSkin(SKIN.r, SKIN.g, SKIN.b));
  assert.ok(isSkin(SKIN_DARK.r, SKIN_DARK.g, SKIN_DARK.b));
  assert.ok(!isSkin(BLUE.r, BLUE.g, BLUE.b));
  assert.ok(!isSkin(10, 10, 10)); // black
  assert.ok(!isSkin(250, 250, 250)); // white (no spread)
});

test('measureSkinMeanRGB masks to skin pixels only, ignoring background', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'skin-'));
  const f = path.join(dir, 'half.png');
  await frame(f, { skinRows: 32 }); // half skin, half blue
  const m = await measureSkinMeanRGB(f);
  assert.ok(m.mean, 'should find skin');
  // Mean is the SKIN color, not the frame average (blue is excluded entirely).
  assert.ok(Math.abs(m.mean.r - SKIN.r) < 2, `r=${m.mean.r}`);
  assert.ok(Math.abs(m.mean.g - SKIN.g) < 2, `g=${m.mean.g}`);
  assert.ok(Math.abs(m.mean.b - SKIN.b) < 2, `b=${m.mean.b}`);
  assert.ok(Math.abs(m.skinFrac - 0.5) < 0.05, `skinFrac=${m.skinFrac}`);
});

test('computeSkinMatch pulls a darker-skinned clip toward the hero', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'skin-'));
  const hero = path.join(dir, 'hero.png');
  const dark = path.join(dir, 'dark.png');
  await frame(hero, { skin: SKIN });
  await frame(dark, { skin: SKIN_DARK });
  const out = path.join(dir, 'out');
  const r = await computeSkinMatch(
    [
      { id: 'hero', png: hero, group: 'Guest' },
      { id: 'dark', png: dark, group: 'Guest' },
    ],
    { outDir: out },
  );
  assert.equal(r.gradeCount ?? r.grades.length, 2);
  const dg = r.grades.find((g) => g.id === 'dark');
  const hg = r.grades.find((g) => g.id === 'hero');
  // Hero matches itself → ~unity. Dark clip needs gain UP toward hero on every channel.
  assert.ok(hg.correctionPct < 1, `hero corr ${hg.correctionPct}`);
  assert.ok(dg.gain.r > 1 && dg.gain.g > 1 && dg.gain.b > 1, `gains ${JSON.stringify(dg.gain)}`);
  assert.ok(Math.abs(dg.gain.r - SKIN.r / SKIN_DARK.r) < 0.02, `r gain ${dg.gain.r}`);
  assert.ok(fs.existsSync(dg.drxPath), 'DRX written');
});

test('GUARD: clip below the skin floor is skipped, not faked', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'skin-'));
  const hero = path.join(dir, 'hero.png');
  const tiny = path.join(dir, 'tiny.png');
  await frame(hero, { skin: SKIN });
  await frame(tiny, { skinRows: 1 }); // ~1.5% skin on 64 rows
  const r = await computeSkinMatch(
    [
      { id: 'hero', png: hero, group: 'Guest' },
      { id: 'tiny', png: tiny, group: 'Guest' },
    ],
    { outDir: path.join(dir, 'out'), minSkinFrac: 0.1 }, // floor above tiny's fraction
  );
  assert.ok(
    r.skipped.some((s) => s.id === 'tiny'),
    'tiny skipped',
  );
  assert.ok(!r.grades.some((g) => g.id === 'tiny'), 'no DRX faked for tiny');
});

test('GUARD: zero skin anywhere throws (wrong-space frames)', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'skin-'));
  const blue = path.join(dir, 'blue.png');
  await frame(blue, { skinRows: 0 }); // all background
  await assert.rejects(() => computeSkinMatch([{ id: 'b', png: blue, group: 'Guest' }], { outDir: path.join(dir, 'out') }), /NO skin-tone pixels/);
});
