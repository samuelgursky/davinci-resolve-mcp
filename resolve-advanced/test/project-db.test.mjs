/** project_db (DB-patch tier) safety-gate tests — self-contained (no live DB needed:
 * the project-closed gate fires before any DB is opened). */

import test from 'node:test';
import assert from 'node:assert/strict';
import { projectDbTool } from '../server/tools/project_db.mjs';

test('rename_folder refuses without iConfirmProjectClosed', async () => {
  await assert.rejects(() => projectDbTool.handler({ action: 'rename_folder', args: { projectName: 'X', folder: 'a', newName: 'b' } }), /close the project/);
});

test('set_clip_marks refuses without iConfirmProjectClosed', async () => {
  await assert.rejects(() => projectDbTool.handler({ action: 'set_clip_marks', args: { projectName: 'X', clip: 'c', markIn: 0 } }), /close the project/);
});

test('set_folder_color refuses without iConfirmProjectClosed', async () => {
  await assert.rejects(
    () => projectDbTool.handler({ action: 'set_folder_color', args: { projectName: 'X', folder: 'a', color: 'FOLDER_COLOR_BLUE' } }),
    /close the project/,
  );
});

test('project_db unknown action throws', async () => {
  await assert.rejects(() => projectDbTool.handler({ action: 'nope', args: {} }), /Unknown project_db action/);
});
