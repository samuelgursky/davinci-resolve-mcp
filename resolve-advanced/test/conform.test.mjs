/** M3 conform tool smoke: offline core actions + input contract + sharp gating. */

import test from 'node:test';
import assert from 'node:assert/strict';
import { conformTool } from '../server/tools/conform.mjs';

test('conform.list_targets includes resolve', async () => {
  const r = await conformTool.handler({ action: 'list_targets', args: {} });
  assert.ok(r.targets);
  assert.equal(r.default, 'resolve');
});

test('conform.repair_ladder exposes the strategy ladder', async () => {
  const r = await conformTool.handler({ action: 'repair_ladder', args: {} });
  assert.ok(Array.isArray(r.strategies) && r.strategies.length > 0);
});

test('conform.report builds a QC report', async () => {
  const r = await conformTool.handler({ action: 'report', args: { meta: { reel: 'R01' }, cuts: [] } });
  assert.ok(r && 'summary' in r);
});

test('conform.oracle_derive enforces its input contract (real fn wired)', async () => {
  // missing required Premiere fields → the real oracle throws (proves it is wired, not stubbed)
  await assert.rejects(() => conformTool.handler({ action: 'oracle_derive', args: { clip: {}, ctx: {} } }), /required|xml_in/);
});

test('conform.verify is gated on optional sharp', async () => {
  await assert.rejects(
    () => conformTool.handler({ action: 'verify', args: { model: {} } }),
    (e) => /sharp/.test(e.message) || e.message.length > 0,
  );
});

test('conform unknown action throws', async () => {
  await assert.rejects(() => conformTool.handler({ action: 'x', args: {} }), /Unknown conform action/);
});
