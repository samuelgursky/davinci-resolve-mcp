/** Color Warper (Chroma Warp) — pin-list structure RE'd + registry claim CORRECTED. Net-new value tool. Dragged 2 chroma-warp pins on the the calibration rig 2026-06-22 and set pin 0's
 * five numeric Pin controls to unique values (Chroma Range 0.12 / Exposure 0.20 / Tonal Low 0.34 /
 * Tonal High 0.56 / Tonal Pivot 0.25), Cmd+S, decoded the BARS grade.
 *
 * KEY FINDINGS:
 * - The registry's "COLOR_WARPER DECODED 2026-03-23" mesh-vertex model (0x86000121: F1=ver / F2=config /
 * F3=N×12B float32 triplets, "5 vertices per moved point") is WRONG for Resolve 21 — a live chroma-warp
 * move emits NONE of 0x86000121/126/129/12C/12D/130. Same failure class as the polygon 0x08B0/ct5 claim.
 * - R21 stores the Color Warper as a PIN LIST under the Primary corrector (ct1): the warp lives in
 * 0x86000138 = value envelope { F27: { F1: [ <pin>, … ] } }. Two config varints (0x86000136/137) and a
 * mode varint (0x86000133) accompany it.
 * - Each pin = { F1=id, F2/F3=source chroma XY, F4/F5=dest chroma XY, F6=chromaRange, F7=exposure
 * (omitted when 0), F8=tonalLow, F9=tonalHigh, F10=tonalPivot }. The five labeled scalars are
 * identity-scale against the UI Pin controls (validated below). F2–F5 are normalized chroma-plane coords. */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { drxTool } from '../server/tools/drx.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const content = fs.readFileSync(path.join(here, 'fixtures', 'color-warper.drx'), 'utf8');

test('Color Warper chroma-warp pins decode into node.params.colorWarper', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const node = r.nodes.find((n) => n.params?.colorWarper);
  assert.ok(node, 'a node exposes params.colorWarper');
  const pins = node.params.colorWarper;
  assert.equal(pins.length, 2, 'two chroma-warp pins captured');
});

test('Pin 0 labeled scalars are identity-scale vs the UI Pin controls', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const [pin0] = r.nodes.find((n) => n.params?.colorWarper).params.colorWarper;
  const close = (a, b) => Math.abs(a - b) < 1e-4;
  assert.ok(close(pin0.chromaRange, 0.12), `chromaRange 0.12 (got ${pin0.chromaRange})`);
  assert.ok(close(pin0.exposure, 0.2), `exposure 0.20 (got ${pin0.exposure})`);
  assert.ok(close(pin0.tonalLow, 0.34), `tonalLow 0.34 (got ${pin0.tonalLow})`);
  assert.ok(close(pin0.tonalHigh, 0.56), `tonalHigh 0.56 (got ${pin0.tonalHigh})`);
  assert.ok(close(pin0.tonalPivot, 0.25), `tonalPivot 0.25 (got ${pin0.tonalPivot})`);
  // Source/dest chroma coords are normalized [0,1].
  for (const k of ['srcX', 'srcY', 'dstX', 'dstY']) {
    assert.ok(pin0[k] >= 0 && pin0[k] <= 1, `${k} normalized (got ${pin0[k]})`);
  }
});

test('Pin 1 carries Color Warper defaults (Exposure 0 omitted from the wire)', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const pin1 = r.nodes.find((n) => n.params?.colorWarper).params.colorWarper[1];
  const close = (a, b) => Math.abs(a - b) < 1e-4;
  assert.ok(close(pin1.chromaRange, 0.04), `default chromaRange 0.04 (got ${pin1.chromaRange})`);
  assert.equal(pin1.exposure, 0, 'exposure defaults to 0 (field omitted on the wire)');
  assert.ok(close(pin1.tonalLow, 1) && close(pin1.tonalHigh, 1) && close(pin1.tonalPivot, 0.5), 'default tonal range 1/1/0.5');
});

test('Pins also surface as named colorWarper.pinN.* params on the ct1 corrector', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const node = r.nodes.find((n) => n.params?.colorWarper);
  const names = node.correctors.flatMap((c) => c.parameters.map((p) => p.name));
  assert.ok(names.includes('colorWarper.pin0.chromaRange'), 'pin0.chromaRange named');
  assert.ok(names.includes('colorWarper.pin1.tonalPivot'), 'pin1.tonalPivot named');
});
