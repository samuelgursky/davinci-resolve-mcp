/** Regression tests for the 2026-06-22 live-test findings. */

import test from 'node:test';
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import fs from 'node:fs';
import { drxTool } from '../server/tools/drx.mjs';
import { drpTool } from '../server/tools/drp.mjs';

// F3 — drx.generate primary lift/gamma/gain must round-trip (array form normalized to objects).
test('F3: drx.generate primary params survive to CDL', async () => {
  const out = path.join(os.tmpdir(), 'f3-test.drx');
  await drxTool.handler({ action: 'generate', args: { gradeParams: { space: 'drx', lift: [-0.05, -0.02, 0.03, 0], gain: [1.2, 1, 0.85, 1] }, outputPath: out } });
  const { cdl } = await drxTool.handler({ action: 'export_cdl', args: { drxPath: out } });
  assert.ok(Math.abs(cdl.slope.r - 1.2) < 1e-3, 'gain → slope.r ~1.2');
  assert.ok(Math.abs(cdl.offset.r - -0.05) < 1e-3, 'lift → offset.r ~-0.05');
  assert.notEqual(cdl.slope.b, 1, 'blue slope is not unity');
});

// F1 — drp.diff/extract must see real Resolve SeqContainer/<uuid>.xml. Uses the Desktop
// SAMPLE export when present (real-export fixture); skips in CI without it.
const SAMPLE = path.join(os.homedir(), 'Desktop', 'SAMPLE_import_test.drp');
test('F1: drp.diff finds clips in a real Resolve export', { skip: !fs.existsSync(SAMPLE) && 'no SAMPLE fixture' }, async () => {
  const d = await drpTool.handler({ action: 'diff', args: { pathA: SAMPLE, pathB: SAMPLE } });
  assert.ok(d.summary.seqContainersA > 0, 'finds SeqContainers in real export');
  assert.ok(d.summary.clipsA > 0, 'finds clips');
  assert.equal(d.summary.hasAnyChange, false, 'self-diff = no change');
});
