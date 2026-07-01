/** project_read (READ tier) — query guard is self-contained; introspect uses the
 * live project when present (read-only, safe), skips otherwise. */

import test from 'node:test';
import assert from 'node:assert/strict';
import { projectReadTool } from '../server/tools/project_read.mjs';
import { findProjectDb } from '../server/db-patch.mjs';

test('query rejects non-read-only statements', async () => {
  await assert.rejects(() => projectReadTool.handler({ action: 'query', args: { projectName: 'X', sql: 'UPDATE Sm2Timeline SET Name=1' } }), /read-only/);
});

test('query rejects multiple statements', async () => {
  await assert.rejects(
    () => projectReadTool.handler({ action: 'query', args: { projectName: 'X', sql: 'SELECT 1; DROP TABLE Sm2Timeline' } }),
    /single statement/,
  );
});

test('project_read unknown action throws', async () => {
  await assert.rejects(() => projectReadTool.handler({ action: 'nope', args: {} }), /Unknown project_read action/);
});

const SAMPLE = findProjectDb('SAMPLE_import_test')[0];
const live = !SAMPLE && 'no live project';
test('introspect reads a real project', { skip: live }, async () => {
  const r = await projectReadTool.handler({ action: 'introspect', args: { projectDb: SAMPLE } });
  assert.ok(r.timelines.count > 0);
  assert.ok(Array.isArray(r.folders));
});

test('report returns per-timeline analytics', { skip: live }, async () => {
  const r = await projectReadTool.handler({ action: 'report', args: { projectDb: SAMPLE } });
  assert.ok(r.timelines > 0 && r.totalVideoClips > 0);
  assert.ok(Array.isArray(r.clipsPerTimeline));
});

test('audit returns an issues list', { skip: live }, async () => {
  const r = await projectReadTool.handler({ action: 'audit', args: { projectDb: SAMPLE } });
  assert.ok('ok' in r && Array.isArray(r.issues));
});
