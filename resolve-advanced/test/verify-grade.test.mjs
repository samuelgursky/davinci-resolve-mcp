/**
 * verify_grade (Phase-2a) — deterministic, no Resolve. Generates intended DRX grades and
 * synthesizes "applied" grades (identical / drifted / missing) to assert the verdict taxonomy.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { drxTool } from '../server/tools/drx.mjs';
import { verifyGrade } from '../server/verify-grade.mjs';

async function gen(gradeParams) {
  // These fixtures assert raw DRX-internal deltas (e.g. offset.r 0.05), so pin to space:'drx'
  // (the tool default is 'ui', which would rescale wheels/offset).
  const g = await drxTool.handler({ action: 'generate', args: { gradeParams: { space: 'drx', ...gradeParams } } });
  const content = typeof g === 'string' ? g : g.content;
  return content;
}

test('identical grades → landed', async () => {
  const c = await gen({ gain: [1.1, 1.0, 0.95, 1.0] });
  const r = await verifyGrade({ intended: { content: c }, applied: { content: c } });
  assert.equal(r.verdict, 'landed');
  assert.equal(r.counts.drifted, 0);
});

test('a changed param → drifted with the delta listed', async () => {
  const intended = await gen({ gain: [1.1, 1.0, 0.95, 1.0] });
  const applied = await gen({ gain: [1.2, 1.0, 0.95, 1.0] }); // gain.r drifted 0.1
  const r = await verifyGrade({ intended: { content: intended }, applied: { content: applied } });
  assert.equal(r.verdict, 'drifted');
  const n0 = r.nodes.find((n) => n.index === 0);
  const d = n0.deltas.find((x) => x.param === 'gain.r');
  assert.ok(d && Math.abs(d.delta - 0.1) < 1e-3, JSON.stringify(n0.deltas));
});

test('an empty applied grade → missing', async () => {
  const intended = await gen({ gain: [1.1, 1.0, 0.95, 1.0] });
  const empty = await gen({}); // no correctors of substance
  // Force the missing path: applied with zero nodes.
  const r = await verifyGrade({ intended: { content: intended }, applied: { nodes: [] } });
  assert.equal(r.verdict, 'missing');
  assert.ok(r.warnings.some((w) => /missing/.test(w)));
  void empty;
});

test('within tolerance rounding → still landed', async () => {
  const intended = await gen({ gain: [1.1, 1.0, 0.95, 1.0] });
  const applied = await gen({ gain: [1.1000004, 1.0, 0.95, 1.0] });
  const r = await verifyGrade({ intended: { content: intended }, applied: { content: applied } }, { tol: 1e-3 });
  assert.equal(r.verdict, 'landed');
});

test('offset drift is detected against the additive default', async () => {
  const intended = await gen({ gain: [1.0, 1.0, 1.0, 1.0], offset: [0.05, 0, 0, 0] });
  const applied = await gen({ gain: [1.0, 1.0, 1.0, 1.0] }); // offset.r absent → defaults to 0
  const r = await verifyGrade({ intended: { content: intended }, applied: { content: applied } });
  assert.equal(r.verdict, 'drifted');
  const d = r.nodes[0].deltas.find((x) => x.param === 'offset.r');
  assert.ok(d && Math.abs(d.delta - 0.05) < 1e-3, JSON.stringify(r.nodes[0].deltas));
});
