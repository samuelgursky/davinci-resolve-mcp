/** Smoke for the M6/M2 additive tools: fusion, audio_plan, drp.extract_lut_refs. */

import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { fusionTool } from '../server/tools/fusion.mjs';
import { audioPlanTool } from '../server/tools/audio_plan.mjs';
import { drpTool } from '../server/tools/drp.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const tpl = path.resolve(__dirname, '..', 'vendor', 'drp-format', 'templates', 'media-clip-h264.drp');

test('fusion.list_templates returns templates', async () => {
  const r = await fusionTool.handler({ action: 'list_templates', args: {} });
  assert.ok(Array.isArray(r.templates) && r.templates.length > 0);
});

test('audio_plan select + track_plan', async () => {
  const sel = await audioPlanTool.handler({ action: 'select_template', args: { contentType: 'documentary' } });
  assert.ok(sel.template);
  const plan = await audioPlanTool.handler({ action: 'track_plan', args: { contentType: 'documentary' } });
  assert.ok(plan.plan);
});

test('drp.extract_lut_refs returns recognized slots', async () => {
  const r = await drpTool.handler({ action: 'extract_lut_refs', args: { drpPath: tpl } });
  assert.ok(Array.isArray(r.recognizedSlots) && !r.error);
});

test('fusion + audio_plan unknown action throws', async () => {
  await assert.rejects(() => fusionTool.handler({ action: 'x', args: {} }), /Unknown fusion action/);
  await assert.rejects(() => audioPlanTool.handler({ action: 'x', args: {} }), /Unknown audio_plan action/);
});
