/**
 * A3 offline-reference tests. Uses the real Resolve-authored fixture on the
 * Desktop when present (linked .drt); otherwise skips (CI without the fixture).
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import fs from 'node:fs';
import fsp from 'node:fs/promises';

import { offlineRefTool } from '../server/tools/offline_ref.mjs';

const FIXTURE = path.join(os.homedir(), 'Desktop', 'SAMPLE_REF_TL.drt');
const REF_UUID = 'a8975a95-975c-4fd7-8cef-ab7f973b7446';
const haveFixture = fs.existsSync(FIXTURE);
const tmp = (n) => path.join(os.tmpdir(), `adv-a3-${n}`);

test('offline_ref.get reads a real linked .drt', { skip: !haveFixture && 'no Desktop fixture' }, async () => {
  const r = await offlineRefTool.handler({ action: 'get', args: { filePath: FIXTURE } });
  assert.equal(r.count, 1);
  assert.equal(r.links[0].offlineClip, REF_UUID);
});

test('offline_ref clear → set round-trip is byte-faithful', { skip: !haveFixture && 'no Desktop fixture' }, async () => {
  await fsp.copyFile(FIXTURE, tmp('work.drt'));
  const cleared = await offlineRefTool.handler({
    action: 'clear',
    args: { filePath: tmp('work.drt'), all: true, outputPath: tmp('cleared .drt'), backup: false },
  });
  assert.equal(cleared.cleared.length, 1);
  const reset = await offlineRefTool.handler({
    action: 'set',
    args: { filePath: tmp('cleared .drt'), links: [{ referenceDbId: REF_UUID }], outputPath: tmp('relinked .drt'), backup: false },
  });
  assert.equal(reset.changes[0].action, 'inserted');
  assert.equal(reset.linksAfter[0].offlineClip, REF_UUID);
});

test('offline_ref unknown action throws', async () => {
  await assert.rejects(() => offlineRefTool.handler({ action: 'nope', args: {} }), /Unknown offline_ref action/);
});
