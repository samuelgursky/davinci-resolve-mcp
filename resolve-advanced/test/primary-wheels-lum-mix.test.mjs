/** Primary wheel R/G/B channels and Lum Mix (0x8600000B), render-measured on Studio 21.0.4.5
 * (2026-10-19, 30p grey-128 clip, ProRes render, mean of a plain grey band):
 *
 *   gain R=G=B 1.6, Lum Mix unset (Resolve default 100) ... 127.59 (unchanged: luma held)
 *   gain R=G=B 1.6, Lum Mix 0 ............................. 204.14 (×1.6)
 *   gain master 1.6 ....................................... 204.14
 *   gain 1.6/1.0/0.7, Lum Mix unset ....................... 190.5/114.1/76.0 (luma 127.59)
 *   gain 1.6/1.0/0.7, Lum Mix 0 (Resolve's own SetCDL) .... 204.2/127.7/89.7
 *   lift / gamma R/G/B: same pattern; offset and the masters ignore Lum Mix.
 *
 * So the ids 0x0600001D–1F were right all along; R/G/B moves need Lum Mix 0 to act per
 * channel, which is what Resolve writes for SetCDL (fixture r21-setcdl-slope-body.hex). */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { drxTool } from '../server/tools/drx.mjs';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const { parseAdjustments, parseAdjustmentsToNodes } = require('../vendor/drx-codec/drx-generator.js');

const LUM_MIX = 0x8600000b;
const GAIN_R = 0x0600001d;
const call = (action, args) => drxTool.handler({ action, args });
async function primaryParams(gradeParams) {
  const g = await call('generate', { gradeParams });
  const node = (await call('parse', { content: g.content || g })).nodes[0];
  return { params: new Map(node.correctors[0].parameters.map((p) => [p.id, p.value])), warnings: g.warnings };
}

test("Resolve's own SetCDL body carries gain R/G/B with Lum Mix 0", async () => {
  const hex = fs.readFileSync(path.join(here, 'fixtures', 'r21-setcdl-slope-body.hex'), 'utf8').trim();
  const node = (await call('parse', { content: `<Resolve_Color_Exchange><Body>${hex}</Body></Resolve_Color_Exchange>` })).nodes[0];
  const p = new Map(node.correctors[0].parameters.map((x) => [x.id, x.value]));
  assert.ok(Math.abs(p.get(GAIN_R) - 1.6) < 1e-6);
  assert.equal(p.get(LUM_MIX), 0);
});

test('per-channel gain/lift/gamma write Lum Mix 0 when it is unset', async () => {
  for (const gp of [{ gain: { r: 1.6, g: 1.6, b: 1.6 } }, { lift: { r: 0.05 } }, { gamma: { b: -0.02 } }]) {
    const { params } = await primaryParams(gp);
    assert.equal(params.get(LUM_MIX), 0, JSON.stringify(gp));
  }
});

test('masters and offset leave Lum Mix at Resolve default (not written)', async () => {
  for (const gp of [{ gain: { master: 1.6 } }, { lift: { master: 0.05 } }, { offset: { r: 0.5 } }]) {
    const { params } = await primaryParams(gp);
    assert.equal(params.has(LUM_MIX), false, JSON.stringify(gp));
  }
});

test('explicit lumMixSlider wins: ui 0-100 is stored /100, drx stays raw, 0 is no longer dropped', async () => {
  assert.ok(Math.abs((await primaryParams({ gain: { r: 1.2 }, lumMixSlider: 100 })).params.get(LUM_MIX) - 1) < 1e-6);
  assert.ok(Math.abs((await primaryParams({ lumMixSlider: 50 })).params.get(LUM_MIX) - 0.5) < 1e-6);
  assert.equal((await primaryParams({ space: 'drx', lumMixSlider: 0 })).params.get(LUM_MIX), 0);
});

test('equal R/G/B under a non-zero Lum Mix warns how much of the move Resolve cancels', async () => {
  const { warnings } = await primaryParams({ gain: { r: 1.6, g: 1.6, b: 1.6 }, lumMixSlider: 100 });
  assert.ok(warnings.some((w) => /cancels 100% of an equal R\/G\/B move/.test(w)), String(warnings));
  const half = await primaryParams({ gain: { r: 1.6, g: 1.6, b: 1.6 }, lumMixSlider: 50 });
  assert.ok(half.warnings.some((w) => /cancels 50%/.test(w)), String(half.warnings));
  const clean = await primaryParams({ gain: { r: 1.6, g: 1.6, b: 1.6 } });
  assert.ok(!(clean.warnings || []).some((w) => /cancels/.test(w)));
});

test('simple-mode shadowLift / highlightCompression / contrast node move the masters, not equal R/G/B', () => {
  const lift = parseAdjustments({ shadowLift: 0.5 });
  assert.ok(lift.lift.master > 0 && lift.lift.r === 0 && lift.lift.g === 0 && lift.lift.b === 0);
  const hc = parseAdjustments({ highlightCompression: 0.5 });
  assert.ok(hc.gain.master < 1 && hc.gain.r === 1 && hc.gain.g === 1 && hc.gain.b === 1);
  const contrast = parseAdjustmentsToNodes({ contrast: 1.4 }).find((n) => /Contrast/.test(n.label)).params;
  assert.ok(contrast.lift.master < 0 && contrast.gain.master > 1);
  assert.deepEqual([contrast.lift.r, contrast.gain.r], [0, 1]);
});
