/**
 * Matcher additions — match_to_reference, saturation_match, black_balance, skin_match v2
 * (chroma metric). Deterministic synthetic frames with known deltas; no Resolve.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { computeMatchToReference, measureMeanStd } from '../server/match-to-reference.mjs';
import { computeSaturationMatch, measureSaturation } from '../server/saturation-match.mjs';
import { computeBlackBalance, measureBlackPoint } from '../server/black-balance.mjs';
import { computeSkinMatch } from '../server/skin-match.mjs';
import { drxTool } from '../server/tools/drx.mjs';

const require = createRequire(import.meta.url);
const sharp = require('sharp');

async function solid(file, { r, g, b }, w = 64, h = 64) {
  const buf = Buffer.alloc(w * h * 3);
  for (let i = 0; i < buf.length; i += 3) {
    buf[i] = r;
    buf[i + 1] = g;
    buf[i + 2] = b;
  }
  await sharp(buf, { raw: { width: w, height: h, channels: 3 } })
    .png()
    .toFile(file);
}
// Two-tone frame for non-zero std + a black point.
async function twoTone(file, a, b, w = 64, h = 64) {
  const buf = Buffer.alloc(w * h * 3);
  for (let y = 0; y < h; y++) {
    const c = y < h / 2 ? a : b;
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

test('match_to_reference moves a target toward a warmer reference', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'mtr-'));
  const tgt = path.join(dir, 't.png');
  const ref = path.join(dir, 'r.png');
  await twoTone(tgt, { r: 100, g: 100, b: 100 }, { r: 140, g: 140, b: 140 }); // neutral
  await twoTone(ref, { r: 150, g: 110, b: 80 }, { r: 180, g: 140, b: 100 }); // warm
  const r = await computeMatchToReference([{ id: 't', png: tgt, reference: ref }], { outDir: path.join(dir, 'out'), skinGate: false });
  assert.equal(r.grades.length, 1);
  const g = r.grades[0];
  // Warm ref → red gain up relative to blue.
  assert.ok(fs.existsSync(g.drxPath));
  const back = await drxTool.handler({ action: 'parse', args: { content: fs.readFileSync(g.drxPath, 'utf8') } });
  const params = back.nodes.flatMap((n) => n.correctors.flatMap((c) => c.parameters));
  assert.ok(
    params.some((p) => /gain\.r/.test(p.name)),
    'has a red gain',
  );
});

test('match_to_reference skips an unreadable reference (skip-not-fake)', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'mtr-'));
  const tgt = path.join(dir, 't.png');
  await solid(tgt, { r: 100, g: 100, b: 100 });
  const r = await computeMatchToReference([{ id: 't', png: tgt, reference: path.join(dir, 'nope.png') }], { outDir: path.join(dir, 'out') });
  assert.equal(r.grades.length, 0);
  assert.ok(r.skipped.some((s) => s.id === 't'));
});

test('match_to_reference lumaPreserve keeps the target luma', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'mtr-'));
  const tgt = path.join(dir, 't.png');
  const ref = path.join(dir, 'r.png');
  await twoTone(tgt, { r: 60, g: 60, b: 60 }, { r: 90, g: 90, b: 90 }); // dark
  await twoTone(ref, { r: 180, g: 150, b: 120 }, { r: 210, g: 180, b: 150 }); // bright + warm
  const r = await computeMatchToReference([{ id: 't', png: tgt, reference: ref }], { outDir: path.join(dir, 'out'), skinGate: false, lumaPreserve: true });
  const g = r.grades[0];
  // With luma preserved, the mean offset shouldn't push the whole frame bright — corrections stay bounded.
  assert.ok(g.lumaPreserve === true);
});

test('saturation_match pulls a flat clip toward a saturated hero', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'sat-'));
  const hero = path.join(dir, 'hero.png');
  const flat = path.join(dir, 'flat.png');
  await solid(hero, { r: 200, g: 60, b: 60 }); // saturated red
  await solid(flat, { r: 150, g: 120, b: 120 }); // low sat
  const heroSat = (await measureSaturation(hero)).sat;
  const flatSat = (await measureSaturation(flat)).sat;
  assert.ok(heroSat > flatSat);
  const r = await computeSaturationMatch(
    [
      { id: 'hero', png: hero },
      { id: 'flat', png: flat },
    ],
    { outDir: path.join(dir, 'out') },
  );
  const fg = r.grades.find((g) => g.id === 'flat');
  assert.ok(fg.satScale > 1, `expected sat scale up, got ${fg.satScale}`);
  assert.ok(fs.existsSync(fg.drxPath));
});

test('black_balance neutralizes a shadow cast and skips neutral shadows', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bb-'));
  const cast = path.join(dir, 'cast.png');
  const neutral = path.join(dir, 'neutral.png');
  // Shadows carry a blue cast (blue black point lifted), highlights neutral.
  await twoTone(cast, { r: 8, g: 12, b: 40 }, { r: 200, g: 200, b: 200 });
  await twoTone(neutral, { r: 10, g: 10, b: 10 }, { r: 200, g: 200, b: 200 });
  const bp = await measureBlackPoint(cast);
  assert.ok(bp.b > bp.r, 'blue black is lifted');
  const r = await computeBlackBalance(
    [
      { id: 'cast', png: cast },
      { id: 'neutral', png: neutral },
    ],
    { outDir: path.join(dir, 'out') },
  );
  const cg = r.grades.find((g) => g.id === 'cast');
  assert.ok(cg, 'cast clip graded');
  assert.ok(cg.offset.b < 0, 'blue pulled down to neutralize the cast');
  assert.ok(
    r.skipped.some((s) => s.id === 'neutral'),
    'neutral shadows skipped',
  );
});

test('skin_match v2 chroma metric preserves luma (darker face not dragged bright)', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'sk2-'));
  const hero = path.join(dir, 'hero.png');
  const dark = path.join(dir, 'dark.png');
  // Same skin HUE, different luma (dark face). Chroma metric should NOT apply a big uniform gain up.
  const skin = (mul) => ({ r: Math.round(200 * mul), g: Math.round(140 * mul), b: Math.round(110 * mul) });
  await solid(hero, skin(1.0));
  await solid(dark, skin(0.7));
  const mean = await computeSkinMatch(
    [
      { id: 'hero', png: hero, group: 'G' },
      { id: 'dark', png: dark, group: 'G' },
    ],
    { outDir: path.join(dir, 'mean'), metric: 'mean' },
  );
  const chroma = await computeSkinMatch(
    [
      { id: 'hero', png: hero, group: 'G' },
      { id: 'dark', png: dark, group: 'G' },
    ],
    { outDir: path.join(dir, 'chroma'), metric: 'chroma' },
  );
  const meanDark = mean.grades.find((g) => g.id === 'dark');
  const chromaDark = chroma.grades.find((g) => g.id === 'dark');
  // Mean metric drags every channel up ~1/0.7≈1.43; chroma metric leaves gains ~unity (same hue).
  assert.ok(meanDark.gain.g > 1.3, `mean g gain ${meanDark.gain.g}`);
  assert.ok(Math.abs(chromaDark.gain.g - 1) < 0.05, `chroma g gain ${chromaDark.gain.g}`);
});
