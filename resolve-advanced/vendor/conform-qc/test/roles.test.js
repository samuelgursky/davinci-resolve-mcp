'use strict';

/** P5 roles/§10 resolution + trigger model + agent toolset + geometry merge-dto. */

const test = require('node:test');
const assert = require('node:assert/strict');

const R = require('../roles');
const trigger = require('../ops/trigger');
const toolset = require('../toolset');
const { mergeGeometry } = require('../parse/merge-dto');

test('roles: editorialRole enum + a version carries a role and serializes', () => {
  assert.ok(R.EDITORIAL_ROLES.includes('finishing'));
  assert.equal(R.isValidRole('proxy'), true);
  assert.equal(R.isValidRole('bogus'), false);
  const version = { id: 'v1', width: 4096, editorialRole: 'finishing' };
  assert.equal(JSON.parse(JSON.stringify(version)).editorialRole, 'finishing');
});

test('roles: MediaRelationship (proxy↔scan, frameOffset) persists + is queryable', () => {
  const store = new R.MediaRelationshipStore();
  store.add({ fromAssetId: 'proxyA', toAssetId: 'scanA', kind: 'scan_of', frameOffset: 111, notes: 'SAMPLE proxy->scan' });
  const got = store.forAsset('proxyA');
  assert.equal(got.length, 1);
  assert.equal(got[0].kind, 'scan_of');
  assert.equal(got[0].frameOffset, 111);
  assert.throws(() => R.makeMediaRelationship({ fromAssetId: 'a', toAssetId: 'b', kind: 'nope' }), /kind must be one of/);
});

test('roles: resolution order — relationship > override > role > naming > highest-res', () => {
  const ref = {
    assetId: 'proxyA',
    versions: [
      { name: 'X 4K-2K.mov', width: 2048, path: '/proxy.mov' },
      { name: 'X 4K.mov', width: 4096, path: '/scan-named.mov', role: 'finishing' },
    ],
  };
  const relStore = new R.MediaRelationshipStore([{ fromAssetId: 'proxyA', toAssetId: 'scanAsset', kind: 'scan_of', frameOffset: 111 }]);
  const resolveAssetPath = (id) => (id === 'scanAsset' ? '/vol/scan/X.mov' : null);

  // 1. relationship wins.
  let r = R.resolveMedia(ref, { relationships: relStore, resolveAssetPath, projectOverride: { proxyA: '/override.mov' } });
  assert.equal(r.via, 'relationship');
  assert.equal(r.path, '/vol/scan/X.mov');
  assert.equal(r.frameOffset, 111);
  // 2. no relationship => project override wins.
  r = R.resolveMedia(ref, { projectOverride: { proxyA: '/override.mov' } });
  assert.equal(r.via, 'project-override');
  // 3. no override => version role (finishing).
  r = R.resolveMedia(ref, {});
  assert.equal(r.via, 'role');
  assert.equal(r.path, '/scan-named.mov');
  // 4. no role => naming (4K not 4K-2K).
  const noRole = { assetId: 'p', versions: [{ name: 'X 4K-2K.mov', width: 2048, path: '/p.mov' }, { name: 'X 4K.mov', width: 4096, path: '/s.mov' }] };
  assert.equal(R.resolveMedia(noRole, {}).via, 'naming');
  // 5. nothing distinctive => highest-res.
  const plain = { assetId: 'p', versions: [{ name: 'a', width: 1920, path: '/a' }, { name: 'b', width: 3840, path: '/b' }] };
  const top = R.resolveMedia(plain, {});
  assert.equal(top.via, 'highest-res');
  assert.equal(top.path, '/b');
});

test('roles: ingest heuristic seeds proxy role + proxy↔scan relationship', () => {
  const seeded = R.ingestHeuristic({ id: 'proxyA', name: 'Sample 4K-2K 0508.mov', width: 2048 }, { finishingAssetId: 'scanA', frameOffset: 111 });
  assert.equal(seeded.role, 'proxy');
  assert.equal(seeded.relationship.kind, 'scan_of');
  assert.equal(seeded.relationship.toAssetId, 'scanA');
  assert.equal(R.ingestHeuristic({ id: 's', name: 'Sample 4K 0821.mp4', width: 4096 }).role, 'finishing');
});

test('trigger: auto Tier-C on sidecar upload vs full conform on-demand', () => {
  const up = trigger.onSidecarUpload();
  assert.equal(up.trigger, 'auto-on-upload');
  assert.equal(up.tier, 'C');
  assert.equal(up.badge, 'math-verified');
  const conform = trigger.onConformAction({ surface: 'cloud' });
  assert.equal(conform.trigger, 'on-demand');
  assert.equal(conform.runsOn, 'render-node');
  assert.equal(trigger.onConformAction({ surface: 'local' }).runsOn, 'post-assistant');
});

test('toolset: agent-callable tool schemas validate + dispatch round-trips to verify', async () => {
  assert.ok(toolset.TOOLS.length >= 2);
  for (const t of toolset.TOOLS) {
    assert.ok(t.name && t.description && t.input_schema);
    assert.match(t.description, /deterministic|advisory/i, 'tool desc must state verdicts are deterministic / vision advisory');
  }
  // dispatch round-trips to an injected verify (no real engine needed for the binding).
  let got = null;
  await toolset.dispatch('conform_qc_verify', { model: { sequence: {}, clips: [] } }, { verify: async (m) => { got = m; return { ok: true }; } });
  assert.ok(got);
  await assert.rejects(() => toolset.dispatch('nope', {}), /unknown tool/);
});

test('parse: geometry merge-dto is additive behind a flag (base unchanged when off)', () => {
  const dto = [{ seqstart: 0, name: 'a' }, { seqstart: 48, name: 'b' }];
  const geo = [{ seqstart: 0, pproTicksIn: 123, scale_premiere: 100 }];
  // Flag off: returns the SAME array (untouched).
  assert.equal(mergeGeometry(dto, geo, { attach: false }), dto);
  // Flag on: geometry attached by seqstart; base fields intact.
  const merged = mergeGeometry(dto, geo, { attach: true });
  assert.notEqual(merged, dto);
  assert.equal(merged[0].name, 'a');
  assert.equal(merged[0].conformGeometry.pproTicksIn, 123);
  assert.equal(merged[1].conformGeometry, undefined); // no geometry for seq48
});
