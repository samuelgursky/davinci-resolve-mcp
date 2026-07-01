/**
 * Resolve wire semantics for the affine emitters — LIVE-CALIBRATED 2026-07-03 on
 * DaVinci Resolve Studio 19.1.3 (DaVinci YRGB / Rec709 render, synthetic test project):
 *
 *  1. Resolve renders the RGB gain wheels as COLOR BALANCE only (luma-renormalized).
 *     A uniform per-channel gain with master=1 is a render NO-OP. The achromatic level
 *     must ride gain.master — the emitters set master = luma-weighted gain so Resolve's
 *     renormalization yields exactly the intended per-channel multipliers.
 *  2. Wire offset shifts output by wire×0.2 normalized (wire −0.1 → −5/255 exactly),
 *     and the wire range is ±1: the emitter scales normalized intent ×5, clamps, warns.
 *
 * These tests pin the emitter output so a codec/emitter change can't silently regress
 * the render-calibrated behavior. (ACEScct offset scale is a separate real-footage check.)
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { generateAssertedGainDRX } from '../server/exposure-level.mjs';
import { generateAssertedAffineDRX, OFFSET_WIRE_PER_NORM } from '../server/contrast-normalize.mjs';
import { drxTool } from '../server/tools/drx.mjs';

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'wire-semantics-'));
const parseParams = async (p) => {
  const back = await drxTool.handler({ action: 'parse', args: { content: fs.readFileSync(p, 'utf8') } });
  return back.nodes[0].params;
};
const LUMA = (g) => 0.2126 * g.r + 0.7152 * g.g + 0.0722 * g.b;

test('gain emitter: master carries the luma-weighted level (uniform gain is not chroma-only)', async () => {
  const gain = { r: 1.31, g: 1.31, b: 1.31 };
  const out = path.join(tmp, 'uniform-gain.drx');
  await generateAssertedGainDRX(gain, 'test uniform', out);
  const p = await parseParams(out);
  assert.ok(Math.abs(p.gain.master - 1.31) < 1e-3, `master must carry the level, got ${p.gain.master}`);
  assert.ok(Math.abs(p.gain.r - 1.31) < 1e-3);
});

test('gain emitter: unequal gains keep absolute channels + luma-weighted master', async () => {
  const gain = { r: 0.871, g: 1.004, b: 1.169 };
  const out = path.join(tmp, 'unequal-gain.drx');
  await generateAssertedGainDRX(gain, 'test unequal', out);
  const p = await parseParams(out);
  assert.ok(Math.abs(p.gain.master - LUMA(gain)) < 1e-3, `master should be luma(gain)=${LUMA(gain)}, got ${p.gain.master}`);
  assert.ok(Math.abs(p.gain.b - 1.169) < 1e-3);
});

test('affine emitter: normalized offset intent is wire-scaled ×5', async () => {
  const out = path.join(tmp, 'offset-scale.drx');
  const warnings = [];
  await generateAssertedAffineDRX({ r: 1, g: 1, b: 1 }, { r: -0.02, g: -0.02, b: -0.02 }, 'test offset', out, warnings);
  const p = await parseParams(out);
  assert.equal(OFFSET_WIRE_PER_NORM, 5);
  assert.ok(Math.abs(p.offset.r - -0.1) < 1e-4, `wire should be −0.1 for −0.02 norm, got ${p.offset.r}`);
  assert.equal(warnings.length, 0);
});

test('affine emitter: offset beyond ±0.2 norm clamps to wire ±1 and WARNS (no silent divergence)', async () => {
  const out = path.join(tmp, 'offset-clamp.drx');
  const warnings = [];
  await generateAssertedAffineDRX({ r: 1, g: 1, b: 1 }, { r: -0.2445, g: 0.05, b: 0.3 }, 'test clamp', out, warnings);
  const p = await parseParams(out);
  assert.ok(Math.abs(p.offset.r - -1) < 1e-4, `r should clamp to −1, got ${p.offset.r}`);
  assert.ok(Math.abs(p.offset.g - 0.25) < 1e-4, `g in-range should scale, got ${p.offset.g}`);
  assert.ok(Math.abs(p.offset.b - 1) < 1e-4, `b should clamp to +1, got ${p.offset.b}`);
  assert.equal(warnings.filter((w) => w.includes('exceeds the wire range')).length, 2, 'one warning per clamped channel');
});

test('skin_match guard: orange non-skin content warns off the skin line; skin tones do not', async () => {
  const { computeSkinMatch } = await import('../server/skin-match.mjs');
  const sharp = (await import('sharp')).default;
  const os = await import('node:os');
  const path = await import('node:path');
  const fs = await import('node:fs');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'skinline-'));
  // fire-like YELLOW-orange (Kovac-passing, ~+21° off the 123° line — matches the
  // live-measured car-fire frame at +13.5°; deep red-orange can brush the skin line,
  // which is exactly why this is a warning and not a skip)
  await sharp({ create: { width: 64, height: 64, channels: 3, background: { r: 230, g: 140, b: 25 } } }).png().toFile(path.join(tmp, 'orange.png'));
  await sharp({ create: { width: 64, height: 64, channels: 3, background: { r: 200, g: 150, b: 125 } } }).png().toFile(path.join(tmp, 'skin.png'));
  const r = await computeSkinMatch(
    [{ id: 'orange', png: path.join(tmp, 'orange.png'), group: 'g' }, { id: 'skin', png: path.join(tmp, 'skin.png'), group: 'g' }],
    { outDir: tmp, heroId: 'skin' },
  );
  assert.ok(r.warnings.some((w) => w.startsWith('orange:') && w.includes('off the vectorscope skin line')), 'orange content warns');
  assert.ok(!r.warnings.some((w) => w.startsWith('skin:') && w.includes('off the vectorscope skin line')), 'skin tone stays clean');
});
