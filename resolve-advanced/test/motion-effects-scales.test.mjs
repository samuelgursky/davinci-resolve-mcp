/**
 * Motion Effects ct15 — temporalMotion/motionBlur write scales, CONFIRMED by
 * three-point live panel capture 2026-07-03 (Resolve 19.1.3, gallery still + .drx):
 *   temporalMotion: stored = 0.28×UI + 2.0  (UI 35→11.8, 60→18.8, 80→24.4 exact)
 *   motionBlur:     stored = 0.0099×UI      (UI 50→0.495, 25→0.2475 exact)
 * Generator takes UI panel values and applies the mapping; parse returns stored.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { drxTool } from '../server/tools/drx.mjs';

const storedME = async (content) => {
  const p = await drxTool.handler({ action: 'parse', args: { content } });
  const out = {};
  for (const c of p.nodes[0].correctors || [])
    for (const prm of c.parameters || [])
      if (prm.name.startsWith('motionEffects.')) out[prm.name.split('.')[1]] = prm.value;
  return out;
};

test('ct15: temporalMotion UI value writes stored = 0.28×UI + 2.0', async () => {
  const r = await drxTool.handler({ action: 'generate', args: { gradeParams: { motionEffects: { frames: 2, temporalMotion: 60 } }, metadata: { label: 'me tm' } } });
  const me = await storedME(r.content);
  assert.ok(Math.abs(me.temporalMotion - 18.8) < 1e-4, `expected 18.8, got ${me.temporalMotion}`);
});

test('ct15: motionBlur UI value writes stored = 0.0099×UI', async () => {
  const r = await drxTool.handler({ action: 'generate', args: { gradeParams: { motionEffects: { motionBlur: 50 } }, metadata: { label: 'me mb' } } });
  const me = await storedME(r.content);
  assert.ok(Math.abs(me.motionBlur - 0.495) < 1e-6, `expected 0.495, got ${me.motionBlur}`);
});

test('ct15: panel-captured fixture points all satisfy the affine fits', () => {
  const tm = (ui) => 0.28 * ui + 2.0;
  for (const [ui, stored] of [[35, 11.8], [60, 18.8], [80, 24.4]])
    assert.ok(Math.abs(tm(ui) - stored) < 1e-6, `temporalMotion ${ui}→${stored}`);
  for (const [ui, stored] of [[50, 0.495], [25, 0.2475]])
    assert.ok(Math.abs(0.0099 * ui - stored) < 1e-6, `motionBlur ${ui}→${stored}`);
});
