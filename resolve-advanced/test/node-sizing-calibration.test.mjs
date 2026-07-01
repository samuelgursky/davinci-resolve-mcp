/** Node "Input Sizing" — RE + parser extension.
 * Sizing lives outside the F9 corrector list in a transform structure; the parser now scans the
 * decompressed body for its signature (1a 0d 08 <kx> 80 c0 <kg> 01 12 05 0d <f32>) and lifts it
 * into sizing.<channel>. RE'd 2026-06-22 on the calibration SMPTE-bars compound clip:
 * Pan 71 / Tilt 72 / Zoom 1.73 / Rotate 74 / Width 1.75 / Height 1.76 / Pitch 0.77 / Yaw 0.78.
 * Scales: Zoom/Width/Height/Pitch/Yaw direct; Rotate degrees; Pan = px/1920, Tilt = px/1080. */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { drxTool } from '../server/tools/drx.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const content = fs.readFileSync(path.join(here, 'fixtures', 'node-sizing.drx'), 'utf8');

const EXPECTED = {
  width: 1.75,
  height: 1.76,
  zoom: 1.73,
  rotate: 74,
  pan: 71 / 1920, // normalized by frame width
  tilt: 72 / 1080, // normalized by frame height
  pitch: 0.77,
  yaw: 0.78,
};

test('Node Sizing surfaces all 8 transform params (pan/tilt normalized by frame dims)', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const sz = r.nodes.map((n) => n.params && n.params.sizing).find(Boolean);
  assert.ok(sz, 'node.params.sizing present');
  for (const [ch, want] of Object.entries(EXPECTED)) {
    assert.ok(Math.abs(sz[ch] - want) < 1e-3, `sizing.${ch} ≈ ${want} (got ${sz[ch]})`);
  }
});
