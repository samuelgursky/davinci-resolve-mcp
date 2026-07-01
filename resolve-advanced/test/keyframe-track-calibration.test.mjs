/** Keyframe interpolation track decode — FULLY CRACKED.
 * Sam hand-placed 3 keyframes on one Matte-Finesse param (param 0x0c30001d) at frames 0 / 60 / 119 with
 * values 0.40 / 1.10 / 1.70, Cmd+S; decoded from the live calibration BARS grade.
 *
 * ENCODING (validated): a keyframed corrector's F6 is a REPEATED field — one block per keyframe. Each block
 * = { F1: timeUnits, F2: {F3:[param values]} } where timeUnits = frame × 2 (half-frame/field units; F1 is
 * ABSENT on block 0 = frame 0). The clip is 120 frames → last frame 119 → F1 238 = 119×2; the middle
 * keyframe frame 60 → F1 120 = 60×2 confirmed the unit beyond doubt. The parser surfaces this as
 * node.keyframes = [{ correctorType, tracks: { <paramName>: [{frame, value}, …] } }]. */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { drxTool } from '../server/tools/drx.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const content = fs.readFileSync(path.join(here, 'fixtures', 'keyframe-track.drx'), 'utf8');

test('keyframe tracks decode to per-param {frame, value} points (time = frame × 2)', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const node = r.nodes.find((n) => n.keyframes);
  assert.ok(node, 'a node exposes node.keyframes');
  const track = node.keyframes.flatMap((k) => Object.values(k.tracks))[0];
  assert.ok(Array.isArray(track) && track.length === 3, `3 keyframes (got ${track?.length})`);
  const close = (a, b) => Math.abs(a - b) < 1e-4;
  assert.equal(track[0].frame, 0);
  assert.ok(close(track[0].value, 0.4), `kf0 0.40 (got ${track[0].value})`);
  assert.equal(track[1].frame, 60);
  assert.ok(close(track[1].value, 1.1), `kf1@60 1.10 (got ${track[1].value})`);
  assert.equal(track[2].frame, 119);
  assert.ok(close(track[2].value, 1.7), `kf2@119 1.70 (got ${track[2].value})`);
});

test('keyframed node is still flagged and recovers its base (frame-0) param snapshot', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const node = r.nodes.find((n) => n.keyframed);
  assert.ok(node, 'node flagged keyframed');
  assert.equal(r.valueFidelity.keyframed, true);
  // The static param path returns the base (frame-0) values, not empty.
  const total = node.correctors.reduce((s, c) => s + c.parameters.length, 0);
  assert.ok(total >= 1, 'base params recovered');
});
