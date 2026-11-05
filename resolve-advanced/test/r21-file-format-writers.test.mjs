/** Studio 21.0.4.5 file-format writers (2026-10-19): variable-speed ramps, keyframed grade
 * params and Magic Mask 2 click placement. Offline round-trips here; the render proofs that
 * back each writer are recorded in the module headers (frame-coded / per-frame metric renders). */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const fx = (n) => fs.readFileSync(path.join(here, 'fixtures', n), 'utf8');
const { decodeTimemap, buildRampTimemapR21 } = require('../vendor/drp-format/media-timemap.js');
const { keyframeCorrector } = require('../vendor/drx-codec/grade-keyframes.js');
const { placeMagicMaskClick, readMagicMaskClicks } = require('../vendor/drx-codec/magic-mask-author.js');
const { bodyHexOf } = require('../vendor/drx-codec/grade-body-wire.js');
const { generateDRX } = require('../vendor/drx-codec/drx-generator.js');
const { parseDRXContent } = require('../vendor/drx-codec/drx-parser.js');
const xmlOf = (g) => (typeof g === 'string' ? g : g.content || g.drxContent);
const close = (a, b, eps = 1e-6) => Math.abs(a - b) < eps;

test('a hand-made Studio 21 ramp decodes as protobuf points (100% then 50%)', () => {
  const d = decodeTimemap(fx('retimed-timemap-r21-hand-ramp.hex').trim());
  assert.equal(d.keyframeForm, 'protobuf');
  assert.equal(d.variable, true);
  assert.deepEqual(d.segments.map((s) => s.speed), [1, 0.5]);
  assert.ok(close(d.keyframes[0].recordSec, 2) && close(d.keyframes[0].sourceSec, 2));
});

test('buildRampTimemapR21 reproduces the hand ramp byte-for-byte (same uniqueId)', () => {
  const hand = decodeTimemap(fx('retimed-timemap-r21-hand-ramp.hex').trim());
  const uniqueId = hand.entries.find((e) => e.key === 'UniqueId').value;
  const built = buildRampTimemapR21({ segments: [{ durationFrames: 60, speed: 1 }, { durationFrames: 479, speed: 0.5 }], sourceFrames: 300, fps: 30, uniqueId });
  assert.equal(built.timemap.toString('hex'), fx('retimed-timemap-r21-hand-ramp.hex').trim());
  assert.equal(built.sourceEndFrame, 299);
});

test('buildRampTimemapR21: the render-proven 100/25/200 ramp and its source bound', () => {
  const b = buildRampTimemapR21({ segments: [{ durationFrames: 30, speed: 1 }, { durationFrames: 90, speed: 0.25 }, { durationFrames: 120, speed: 2 }], sourceFrames: 300, fps: 30, uniqueId: 'u' });
  assert.equal(b.durationFrames, 240);
  assert.equal(b.sourceEndFrame, 290); // the render's last decoded frame was source 290
  assert.deepEqual(decodeTimemap(b.timemap).segments.map((s) => s.speed), [1, 0.25, 2]);
  assert.throws(() => buildRampTimemapR21({ segments: [{ durationFrames: 400, speed: 1 }], sourceFrames: 300, fps: 30, uniqueId: 'u' }), /media ends/);
});

test('keyframeCorrector writes dynamic Midtone Detail keyframes the parser reads back', async () => {
  const base = xmlOf(await generateDRX({ midtoneDetail: 100 }, { label: 'kf' }));
  const out = keyframeCorrector(base, { keyframes: [{ frame: 0, values: { 0x86000113: 0 } }, { frame: 100, values: { 0x86000113: 100 } }] });
  const r = await parseDRXContent(out);
  const node = r.nodes.find((n) => n.keyframed);
  assert.ok(node, 'keyframed node');
  const track = node.keyframes.flatMap((k) => Object.values(k.tracks))[0];
  assert.deepEqual(track.map((p) => p.frame), [0, 100]);
  assert.deepEqual(track.map((p) => p.value), [0, 100]);
});

test('keyframeCorrector refuses params missing from the base corrector and re-keyframing', async () => {
  const base = xmlOf(await generateDRX({ midtoneDetail: 50 }, { label: 'kf' }));
  assert.throws(() => keyframeCorrector(base, { keyframes: [{ frame: 0, values: { 0x0600001d: 1 } }, { frame: 9, values: { 0x0600001d: 2 } }] }), /not in the base corrector/);
  const once = keyframeCorrector(base, { kind: 'static', keyframes: [{ frame: 0, values: { 0x86000113: 0 } }, { frame: 9, values: { 0x86000113: 50 } }] });
  assert.throws(() => keyframeCorrector(once, { keyframes: [{ frame: 0, values: {} }, { frame: 1, values: {} }] }), /already keyframed/);
});

test('Magic Mask 2 capture stores the subject click (source frame, centred x/y)', () => {
  const clicks = readMagicMaskClicks(bodyHexOf(fx('magic-mask2-click.drx')));
  assert.equal(clicks.length, 1);
  assert.equal(clicks[0].frame, 929);
  assert.equal(clicks[0].op, 6);
  assert.ok(close(clicks[0].x, -0.0156, 1e-3) && close(clicks[0].y, 0.1286, 1e-3));
});

test('placeMagicMaskClick moves the click and can add a Primary inside the mask', async () => {
  const sat0 = xmlOf(await generateDRX({ saturation: 0 }, { label: 'sat0' }));
  const out = placeMagicMaskClick(fx('magic-mask2-click.drx'), { frame: 10, x: 0.15, y: 0.05 }, { primaryFromDrx: sat0 });
  const [c] = readMagicMaskClicks(bodyHexOf(out));
  assert.equal(c.frame, 10);
  assert.ok(close(c.x, 0.15) && close(c.y, 0.05));
  const r = await parseDRXContent(out);
  const types = r.nodes[0].correctors.map((k) => k.type);
  assert.deepEqual(types.slice(0, 2), [1, 2], 'Primary added before the mask corrector');
  assert.throws(() => placeMagicMaskClick(fx('magic-mask2-click.drx'), { frame: 1, x: 0.7, y: 0 }), /centred image fractions/);
});
