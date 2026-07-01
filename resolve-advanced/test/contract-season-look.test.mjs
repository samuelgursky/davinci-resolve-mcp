/**
 * runner→apply CONTRACT (P2b) + grade_transfer season-look authoring/versioning. Deterministic.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { toApplyContract, APPLY_CONTRACT } from '../server/runner-apply-contract.mjs';
import { authorLook, carryLook } from '../server/season-look.mjs';
import { drxTool } from '../server/tools/drx.mjs';

test('apply contract maps conform → media_pool.import_timeline with source clips', () => {
  const c = toApplyContract({ stage: 'conform', config: { path_maps: [{ from: '/a', to: '/b' }], xml: '<x/>' } });
  assert.equal(c.actions[0].action, 'media_pool.import_timeline');
  assert.equal(c.actions[0].args.importSourceClips, true);
  assert.deepEqual(c.actions[0].args.pathMaps, [{ from: '/a', to: '/b' }]);
});

test('apply contract maps grade → safe_apply_drx and names the artifact source', () => {
  const c = toApplyContract({ stage: 'grade', config: { mode: 'group' } });
  assert.equal(c.actions[0].action, 'timeline_item_color.safe_apply_drx');
  assert.match(c.actions[0].args.perClipDrx, /ARTIFACT:/);
});

test('apply contract maps color_groups → create + assign', () => {
  const c = toApplyContract({ stage: 'color_groups', config: { taxonomy: ['Host'], source_map: { A: 'Host' } } });
  assert.deepEqual(
    c.actions.map((a) => a.action),
    ['color_group.create', 'color_group.assign'],
  );
});

test('every deterministic-and-resolve stage in the catalog has a contract entry', () => {
  for (const stage of ['ingest', 'conform', 'offline_ref', 'color_groups', 'grade', 'audio_sync', 'qc', 'deliver']) {
    assert.ok(APPLY_CONTRACT[stage], `contract for ${stage}`);
  }
});

async function sourceDrx() {
  const g = await drxTool.handler({ action: 'generate', args: { gradeParams: { gain: [1.1, 1.0, 0.95, 1.0] } } });
  return typeof g === 'string' ? g : g.content;
}

test('authorLook produces a versioned, hashed, apply-ready look manifest', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'sl-'));
  const content = await sourceDrx();
  const r = await authorLook({ content }, { name: 'Series host', version: 3, approvedBy: 'Sam', outPath: path.join(dir, 'look.drx') });
  assert.equal(r.manifest.name, 'Series host');
  assert.equal(r.manifest.version, 3);
  assert.equal(r.manifest.approvedBy, 'Sam');
  assert.ok(r.manifest.sourceHash && r.manifest.sourceHash.length === 16);
  assert.ok(fs.existsSync(r.manifest.drxPath));
  // Same source → same identity hash (deterministic).
  const r2 = await authorLook({ content }, { name: 'Series host', version: 3, outPath: path.join(dir, 'look2.drx') });
  assert.equal(r2.manifest.sourceHash, r.manifest.sourceHash);
});

test('carryLook plans a group apply per target with provenance', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'sl-'));
  const content = await sourceDrx();
  const { manifest } = await authorLook({ content }, { name: 'HostLook', version: 2, outPath: path.join(dir, 'l.drx') });
  const plan = carryLook(manifest, ['Host', { group: 'Guest', episode: 'E052' }]);
  assert.equal(plan.targetCount, 2);
  assert.equal(plan.plan[0].args.group, 'Host');
  assert.equal(plan.plan[1].args.episode, 'E052');
  assert.match(plan.plan[0].args.provenance, /HostLook v2/);
});

test('drx author_look + carry_look dispatch end to end', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'sl-'));
  const content = await sourceDrx();
  const manifest = await drxTool.handler({ action: 'author_look', args: { content, name: 'L', version: 1, outPath: path.join(dir, 'l.drx') } });
  const plan = await drxTool.handler({ action: 'carry_look', args: { look: manifest, targets: ['G1'] } });
  assert.equal(plan.targetCount, 1);
});
