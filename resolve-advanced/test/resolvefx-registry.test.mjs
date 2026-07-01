/**
 * ResolveFX plugin registry — full 105-plugin universe extracted 2026-07-03 from the
 * Resolve 19.1.3 binary (plugin ids EXACT; param/enum candidates from the factory-block
 * string scan, quality-flagged; `paramsObserved` = EXACT names decoded from real
 * project grades). Decode does not depend on this registry — OFX params are
 * self-describing on the wire — so these tests pin availability + shape + the
 * ground-truth overlays, not exhaustive per-plugin content.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const drxParams = require('../vendor/drx-parameters');

test('registry: 105-plugin universe with quality flags', () => {
  const reg = drxParams.RESOLVEFX_REGISTRY;
  const plugins = Object.entries(reg).filter(([k, v]) => k !== '_meta' && v.wireId);
  assert.equal(plugins.length, 105);
  for (const [, v] of plugins) {
    assert.ok(['good', 'low', 'none'].includes(v.candidateQuality));
    assert.ok(Array.isArray(v.params) && Array.isArray(v.enums));
  }
  assert.ok(reg._meta.resolveVersion.includes('19.1.3'));
});

test('registry: lookup works by short name, wire id, and full plugin id', () => {
  const a = drxParams.lookupResolveFX('filmgrain');
  const b = drxParams.lookupResolveFX('com.blackmagicdesign.resolvefx.filmgrain');
  const c = drxParams.lookupResolveFX('com.blackmagicdesign.resolvefx.FilmGrain');
  assert.ok(a && b && c);
  assert.equal(a.wireId, b.wireId);
  assert.equal(b.wireId, c.wireId);
  assert.equal(drxParams.lookupResolveFX('not-a-plugin'), null);
});

test('registry: real-grade ground truth is overlaid (paramsObserved)', () => {
  const fg = drxParams.lookupResolveFX('filmgrain');
  assert.ok(fg.paramsObserved.includes('filmGrainPresets'));
  assert.ok(fg.params.includes('GrainStrength'), 'binary-scan candidates include the core params');
  assert.ok(fg.enums.some((e) => e.startsWith('GRAIN_PRE_')), 'preset enum values captured');
  const cst = drxParams.lookupResolveFX('colorspacetransformv2');
  assert.ok(cst.paramsObserved.includes('inputColorSpace'));
  assert.ok(cst.paramsObserved.includes('inputGamma'));
});
