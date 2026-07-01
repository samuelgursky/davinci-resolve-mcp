/** ColorSlice global params — calibrated 2026-06-22 via the automated harness
 *: each UI field was set to a known value on the Color page and
 * the encoded value read back from Project.db. These 6 IDs (0x86000600–605) were
 * previously absent from the registry and decoded as `unknown_<id>`. This test
 * locks in the names + the Hue negation finding so they can't silently regress. */

import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const params = require('../vendor/drx-parameters/parameter-ids.js');

const EXPECTED = {
  0x86000600: 'density',
  0x86000601: 'densityDepth',
  0x86000602: 'sat',
  0x86000603: 'satBalance',
  0x86000604: 'satDepth',
  0x86000605: 'hue',
};

test('ColorSlice global params are in the registry (no longer unknown_)', () => {
  for (const [id, channel] of Object.entries(EXPECTED)) {
    const info = params.getParamInfo(Number(id));
    assert.ok(info, `0x${Number(id).toString(16)} must be a known param`);
    assert.equal(info.control, 'colorSlice');
    assert.equal(info.channel, channel);
  }
});

test('ColorSlice Hue carries the negated-scale marker', () => {
  assert.equal(params.getParamInfo(0x86000605).scale, 'negated');
});

test('the ColorSlice block starts at 0x86000600, not 0x86000606', () => {
  // the global controls sit just below the documented per-vector VECTOR_DATA blob
  assert.equal(params.COLORSLICE.DENSITY, 0x86000600);
  assert.equal(params.COLORSLICE.VECTOR_DATA, 0x86000606);
});

test('Primary Lum Mix id is 0x8600000b', () => {
  // was 0x8600008b (=2248147083) — a transcription typo vs its own comment that
  // made Lum Mix decode as unknown_. Live-measured: UI 80 → stored 0.8 at 0x8600000b.
  assert.equal(params.ADDITIONAL.LUM_MIX_SLIDER, 0x8600000b);
  assert.equal(params.getParamInfo(0x8600000b).control, 'lumMixSlider');
});
