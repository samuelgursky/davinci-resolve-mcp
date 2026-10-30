/** Studio 21.0.4.5 EASED speed ramps (2026-10-19): Resolve's own "Ease In and Out" speed points,
 * decoded, rebuilt byte-for-byte, and their rendered frames predicted by sourceSecAt. The offline
 * writer's render proof is recorded in buildRampTimemapR21's header. */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const fx = (n) => fs.readFileSync(path.join(here, 'fixtures', n), 'utf8').trim();
const { decodeTimemap, buildEasedTimemap, buildRampTimemapR21, predictSourceFrames } = require('../vendor/drp-format/media-timemap.js');
const close = (a, b, eps = 1e-6) => Math.abs(a - b) < eps;
const zstd = typeof zlib.zstdCompressSync === 'function';

test('a Resolve-eased point decodes: zstd KeyframesBA, Mode 2, handles on the chord slopes', () => {
  const d = decodeTimemap(fx('retimed-timemap-r21-eased.hex'));
  assert.equal(d.keyframeForm, 'protobuf-zstd');
  assert.equal(d.mode, 2);
  assert.deepEqual(d.origin, { recordSec: 0, sourceSec: 0 });
  assert.deepEqual(d.segments.map((s) => s.speed), [1, 0.5]);
  assert.equal(d.eases.length, 1);
  const [inX, inY, outX, outY, e5, e6] = d.keyframes[0].handles;
  assert.ok(close(inX, -2 / 3) && close(inY, -2 / 3) && close(outX, 2 / 3) && close(outY, 1 / 3));
  assert.equal(e5, 0); assert.equal(e6, 0);
  assert.equal(d.entries.find((e) => e.key === 'YMin'), undefined);
});

test('buildEasedTimemap rebuilds both Resolve-eased maps byte-for-byte', { skip: !zstd && 'needs zstd' }, () => {
  for (const name of ['retimed-timemap-r21-eased.hex', 'retimed-timemap-r21-eased-3seg.hex']) {
    const d = decodeTimemap(fx(name));
    const uniqueId = d.entries.find((e) => e.key === 'UniqueId').value;
    const built = buildEasedTimemap({ points: d.keyframes, sourceDurationSec: d.sourceDurationSec, recordDurationSec: d.recordDurationSec, uniqueId });
    assert.equal(built.toString('hex'), fx(name), name);
  }
});

const missesOf = (got, pred) => got.map((g, i) => [i, g, pred[i]]).filter(([, g, p]) => g !== p);

test('predictSourceFrames matches every rendered frame of both Resolve-eased ramps', () => {
  const frames = JSON.parse(fx('r21-eased-render-frames.json'));
  for (const [name, got] of [['retimed-timemap-r21-eased.hex', frames.eased], ['retimed-timemap-r21-eased-3seg.hex', frames.eased3seg]]) {
    const misses = missesOf(got, predictSourceFrames(decodeTimemap(fx(name)), got.length, 30));
    assert.deepEqual(misses, [], name);
  }
});

test('offline-written eased ramps: the render matches the predicted curve, not the linear chord', { skip: !zstd && 'needs zstd' }, () => {
  const frames = JSON.parse(fx('r21-eased-render-frames.json'));
  const cases = [
    [frames.offlineEased, [{ durationFrames: 90, speed: 1 }, { durationFrames: 100, speed: 0.25, easeFrames: 15 }, { durationFrames: 120, speed: 1.5, easeFrames: 12 }]],
    [frames.offlineAuto, [{ durationFrames: 60, speed: 1 }, { durationFrames: 200, speed: 0.5, easeFrames: 'auto' }, { durationFrames: 60, speed: 2, easeFrames: 'auto' }]],
  ];
  for (const [got, segments] of cases) {
    const b = buildRampTimemapR21({ segments, sourceFrames: 300, fps: 30, uniqueId: 'u' });
    assert.equal(b.durationFrames, got.length);
    assert.equal(b.sourceEndFrame, got[got.length - 1]);
    const d = decodeTimemap(b.timemap);
    assert.deepEqual(missesOf(got, predictSourceFrames(d, got.length, 30)), []);
    const linear = { origin: d.origin, keyframes: d.keyframes.map(({ recordSec, sourceSec }) => ({ recordSec, sourceSec })) };
    assert.ok(missesOf(got, predictSourceFrames(linear, got.length, 30)).length >= 20);
  }
});

test('buildRampTimemapR21 easeFrames writes the eased form and validates the ease widths', { skip: !zstd && 'needs zstd' }, () => {
  const b = buildRampTimemapR21({ segments: [{ durationFrames: 60, speed: 1 }, { durationFrames: 479, speed: 0.5, easeFrames: 20 }], sourceFrames: 300, fps: 30, uniqueId: 'u' });
  assert.equal(b.eased, true);
  const d = decodeTimemap(b.timemap);
  assert.equal(d.keyframeForm, 'protobuf-zstd');
  assert.ok(close(d.eases[0].easeSec, 2 / 3));
  assert.equal(predictSourceFrames(d, 61, 30)[60], 58); // Resolve's own 20-frame ease showed 58 here
  // auto = a third of the shorter neighbour
  const auto = buildRampTimemapR21({ segments: [{ durationFrames: 90, speed: 1 }, { durationFrames: 120, speed: 0.5, easeFrames: 'auto' }, { durationFrames: 70, speed: 2, easeFrames: 'auto' }], sourceFrames: 300, fps: 30, uniqueId: 'u' });
  assert.deepEqual(decodeTimemap(auto.timemap).eases.map((e) => +(e.easeSec * 30).toFixed(6)), [30, 23.333333]);
  // without eases the plain protobuf form is unchanged
  assert.equal(decodeTimemap(buildRampTimemapR21({ segments: [{ durationFrames: 60, speed: 1 }, { durationFrames: 60, speed: 0.5 }], sourceFrames: 300, fps: 30, uniqueId: 'u' }).timemap).keyframeForm, 'protobuf');
  assert.throws(() => buildRampTimemapR21({ segments: [{ durationFrames: 30, speed: 1, easeFrames: 5 }, { durationFrames: 30, speed: 0.5 }], sourceFrames: 300, fps: 30, uniqueId: 'u' }), /clip head/);
  assert.throws(() => buildRampTimemapR21({ segments: [{ durationFrames: 30, speed: 1 }, { durationFrames: 20, speed: 0.5, easeFrames: 15 }, { durationFrames: 30, speed: 1, easeFrames: 10 }], sourceFrames: 300, fps: 30, uniqueId: 'u' }), /span 25 frames/);
});
