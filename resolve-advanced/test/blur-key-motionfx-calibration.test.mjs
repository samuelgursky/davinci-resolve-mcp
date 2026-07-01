/** Blur / Key / Motion Effects palettes — the last unswept NATIVE palettes, swept live
 * 2026-07-02 on the 19.1.3 bars rig (distinctive values per field, gallery-grabbed).
 *
 * KEY FINDINGS:
 * - The registry's old "Curves corrector (Type 18)" grouping for the 0x0C30001x/0x0C4000xx
 *   ids was an unvalidated legacy claim (same class as the Color Warper mesh / polygon
 *   0x08B0 claims). Live data: 0x0C30001x = KEY palette under ct9 (beside Matte Finesse's
 *   0x0C30002x), and 0x0C4000xx = MOTION EFFECTS under a NEW corrector type 15.
 * - Blur palette (ct1): radius/hvRatio stored = (UI−0.5)×2 (0.5-neutral sliders → 0);
 *   scaling identity (single-point fits).
 * - Key palette: all identity. 0x0C30001D (Key Output Gain) is the param the June
 *   keyframe sweep animated.
 * - Motion Effects: thresholds/blends identity; framesFlag varint ({F2:4} @ UI frames 2);
 *   temporalMotion (UI 35 → 11.8) and motionBlur (UI 0.4 → 0.0044) scales unconfirmed
 *   (single points) — named, values locked as observed.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { drxTool } from '../server/tools/drx.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const content = fs.readFileSync(path.join(here, 'fixtures', 'blur-key-motionfx.drx'), 'utf8');

const close = (a, b, eps = 1e-3) => Math.abs(a - b) < eps;

test('Blur/Key/Motion-Effects palettes decode with measured names and scales', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const byName = {};
  const cts = new Set();
  for (const n of r.nodes) {
    for (const c of n.correctors || []) {
      cts.add(c.type);
      for (const p of c.parameters || []) byName[p.name] = { ct: c.type, value: p.value };
    }
  }

  // Blur palette (ct1): radius/hvRatio = (UI−0.5)×2; scaling identity.
  assert.ok(close(byName['blur.radiusR'].value, (0.73 - 0.5) * 2), 'radius (0.73−0.5)×2 = 0.46');
  assert.ok(close(byName['blur.hvRatioG'].value, (0.62 - 0.5) * 2), 'hvRatio (0.62−0.5)×2 = 0.24');
  assert.ok(close(byName['blur.scalingB'].value, 0.31), 'scaling identity 0.31');
  assert.equal(byName['blur.radiusR'].ct, 1, 'blur lives in ct1');

  // Key palette (ct9, identity).
  for (const [k, v] of [['key.inputGain', 0.85], ['key.inputOffset', 0.12], ['key.outputGain', 0.65], ['key.outputOffset', 0.08]]) {
    assert.equal(byName[k].ct, 9, `${k} lives in ct9`);
    assert.ok(close(byName[k].value, v), `${k} identity ${v}`);
  }

  // Motion Effects (NEW corrector type 15).
  assert.ok(cts.has(15), 'corrector type 15 present');
  for (const [k, v] of [
    ['motionEffects.spatialLuma', 27], ['motionEffects.spatialChroma', 27], ['motionEffects.spatialBlend', 0.15],
    ['motionEffects.temporalLuma', 21], ['motionEffects.temporalChroma', 21], ['motionEffects.temporalBlend', 0.25],
  ]) {
    assert.equal(byName[k].ct, 15, `${k} lives in ct15`);
    assert.ok(close(byName[k].value, v), `${k} identity ${v}`);
  }
  // Unconfirmed-scale params: names locked, observed values locked.
  assert.ok(close(byName['motionEffects.temporalMotion'].value, 11.8, 0.05), 'temporalMotion observed 11.8 @ UI 35');
  assert.ok(close(byName['motionEffects.motionBlur'].value, 0.0044, 5e-4), 'motionBlur observed 0.0044 @ UI 0.4');
  assert.equal(byName['motionEffects.framesFlag'].value?.F2 ?? byName['motionEffects.framesFlag'].value, 4, 'framesFlag varint 4 @ UI frames 2');

  // Nothing in this grade decodes as unknown_ anymore.
  assert.ok(!Object.keys(byName).some((k) => k && k.startsWith('unknown_')), 'zero unknown_ params');
});
