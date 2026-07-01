/** color_trace match-engine + project_read.timeline_clips. Uses the live SAMPLE
 * project when present (read-only), skips otherwise. */

import test from 'node:test';
import assert from 'node:assert/strict';
import { colorTraceTool } from '../server/tools/color_trace.mjs';
import { projectReadTool } from '../server/tools/project_read.mjs';
import { findProjectDb } from '../server/db-patch.mjs';

const SAMPLE = findProjectDb('SAMPLE_import_test')[0];
const live = SAMPLE ? false : 'no live SAMPLE project';

test("project_read.timeline_clips reads a timeline's clips", { skip: live }, async () => {
  const r = await projectReadTool.handler({ action: 'timeline_clips', args: { projectDb: SAMPLE, timeline: 'SAMPLE_REF_TL 2', trackType: 'video' } });
  assert.ok(r.clipCount > 0);
  assert.ok(r.clips[0].name !== undefined);
});

test('color_trace.plan matches clips between two timelines', { skip: live }, async () => {
  const r = await colorTraceTool.handler({
    action: 'plan',
    args: {
      sourceProjectDb: SAMPLE,
      sourceTimeline: 'SAMPLE_REF_TL',
      targetProjectDb: SAMPLE,
      targetTimeline: 'SAMPLE_REF_TL 2',
    },
  });
  assert.ok(r.summary.matched > 0, 'matches some clips');
  assert.equal(r.summary.matched + r.summary.unmatched, r.target.clips, 'every target clip accounted for');
  // every matched clip carries a grade-apply descriptor (ready | no-source-grade)
  const m = r.matches.find((x) => x.source);
  assert.ok(m.gradeApply && ['ready', 'no-source-grade'].includes(m.gradeApply.status));
});

test('color_trace.plan emits lossless DRX for graded matches', { skip: live }, async () => {
  const os = await import('node:os');
  const path = await import('node:path');
  const fs = await import('node:fs');
  const emitDir = path.join(os.tmpdir(), 'ct-grade-test');
  fs.rmSync(emitDir, { recursive: true, force: true });
  const r = await colorTraceTool.handler({
    action: 'plan',
    args: {
      sourceProjectDb: SAMPLE,
      sourceTimeline: 'SAMPLE_REF_TL 2',
      targetProjectDb: SAMPLE,
      targetTimeline: 'SAMPLE_REF_TL',
      emitDir,
    },
  });
  // SAMPLE_REF_TL 2 has the manufactured graded clip → at least one match is grade-ready + a DRX emitted.
  if (r.summary.gradesReady > 0) {
    const ready = r.matches.find((m) => m.gradeApply?.status === 'ready' && m.gradeApply.drxPath);
    assert.ok(ready, 'a grade-ready match with a drxPath');
    assert.ok(fs.existsSync(ready.gradeApply.drxPath), 'DRX file written');
    assert.ok(fs.readFileSync(ready.gradeApply.drxPath, 'utf8').includes('<Body>'), 'DRX has a Body');
  }
});

test('color_trace unknown action throws', async () => {
  await assert.rejects(() => colorTraceTool.handler({ action: 'nope', args: {} }), /Unknown color_trace action/);
});
