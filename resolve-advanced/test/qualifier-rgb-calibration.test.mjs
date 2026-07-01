/** RGB-mode qualifier — field layout CORRECTED + validated live.
 * Switched the qualifier to RGB mode on the the calibration rig 2026-06-22 and set per-channel ranges
 * (Red Low 12 / High 88 / L.Soft 5 / H.Soft 7, Green Low 22 / High 78, Blue Low 32 / High 68), Cmd+S,
 * decoded the BARS grade.
 *
 * KEY FINDINGS:
 * - RGB-mode range params DO serialize once the qualifier is actively keying (a restricted range counts) —
 * so the alt-mode set is reachable, not a hard limit.
 * - The registry's "TRAINED 2026-03-16" per-channel layout [Low, High, LowSoft, HighSoft] is WRONG. Live
 * data proves the layout is [High, HighSoft, Low, LowSoft] from the base id (Red: 0x02=High 0.88,
 * 0x03=HighSoft 0.07, 0x04=Low 0.12, 0x05=LowSoft 0.05). Const id VALUES re-pointed so the generator's
 * q.rLow/rHigh API and the decoder both name the right field. Scale = UI/100. Corrector type 2. */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { drxTool } from '../server/tools/drx.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const content = fs.readFileSync(path.join(here, 'fixtures', 'qualifier-rgb.drx'), 'utf8');

function qualParams(nodes) {
  const out = {};
  for (const n of nodes) {
    for (const c of n.correctors || []) {
      if (c.type !== 2) continue;
      for (const p of c.parameters || []) out[p.name] = p.value;
    }
  }
  return out;
}

test('RGB-mode qualifier ranges decode named with the correct field layout (UI/100)', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  const q = qualParams(r.nodes);
  const close = (a, b) => Math.abs(a - b) < 1e-4;
  assert.ok(close(q['qualifier.rgbRHigh'], 0.88), `R High 0.88 (got ${q['qualifier.rgbRHigh']})`);
  assert.ok(close(q['qualifier.rgbRHighSoft'], 0.07), `R HighSoft 0.07 (got ${q['qualifier.rgbRHighSoft']})`);
  assert.ok(close(q['qualifier.rgbRLow'], 0.12), `R Low 0.12 (got ${q['qualifier.rgbRLow']})`);
  assert.ok(close(q['qualifier.rgbRLowSoft'], 0.05), `R LowSoft 0.05 (got ${q['qualifier.rgbRLowSoft']})`);
  assert.ok(close(q['qualifier.rgbGHigh'], 0.78), `G High 0.78`);
  assert.ok(close(q['qualifier.rgbGLow'], 0.22), `G Low 0.22`);
  assert.ok(close(q['qualifier.rgbBHigh'], 0.68), `B High 0.68`);
  assert.ok(close(q['qualifier.rgbBLow'], 0.32), `B Low 0.32`);
});
