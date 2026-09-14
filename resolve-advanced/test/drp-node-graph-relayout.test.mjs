/** Whole-.drp "Cleanup Node Graph" (drp.relayout_node_graphs) — inventory of every node
 * graph a project export carries (every LOCAL version per clip, remote versions, group
 * pre/post, timeline-level), the scope matrix, and the write + read-back contract.
 *
 * Fixture shapes are the ones measured on Resolve 19.1.3 exports (DbPrjVer 14): tags,
 * nesting, `<pActive>`, `<LinkedGroup>`, the 0x80 STORED default body. Grade bodies are
 * authored through the drx tool so losslessness can be asserted on real parameters. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import JSZip from 'jszip';
import { drxTool } from '../server/tools/drx.mjs';
import { drpTool } from '../server/tools/drp.mjs';

const require = createRequire(import.meta.url);
const layout = require('../vendor/drx-codec/node-layout.js');

const drx = (action, args) => drxTool.handler({ action, args });
const drp = (action, args) => drpTool.handler({ action, args });
const bodyHex = (xml) => xml.match(/<Body>([0-9a-fA-F]+)<\/Body>/)[1];

/** Resolve's 53-byte default body from a real export: 0x80 STORED, no node message. */
const EMPTY_BODY = '800a2a1a2208800f10b8081d0000803f20800f28b808350000803f38800f40b80848ffffffff0f60c4b8a1dd12100120c4b8a1dd12';

async function scattered(labels, positions) {
  const base = (await drx('generate', { gradeParams: { saturation: 60, label: labels[0] } })).content;
  const merged =
    labels.length > 1
      ? (await drx('merge', { baseContent: base, newNodes: labels.slice(1).map((label, i) => ({ label, params: i === 0 ? { contrast: 1.2 } : { hueRotate: 0.1 } })) })).content
      : base;
  return bodyHex((await drx('relayout', { content: merged, positions })).content);
}

/** Same protobuf, re-wrapped STORED (0x80) — how Resolve serialises small graphs. */
async function stored(hex) {
  const { proto } = await layout.unwrapBody(Buffer.from(hex, 'hex'));
  return (await layout.wrapBody(0x80, proto)).toString('hex');
}

const version = (id, name, corrected, body, verType = 0) =>
  `<Element><ListMgt::LmVersion DbId="${id}"><FieldsBlob/><Name>${name}</Name><HasCorrection>${corrected}</HasCorrection><VerType>${verType}</VerType><ImplVersion>1</ImplVersion><Body>${body}</Body></ListMgt::LmVersion></Element>`;
const table = (id, active, versions, extra = '') =>
  `<pLmVerTable><ListMgt::LmVersionTable DbId="${id}"><FieldsBlob/><VerType>0</VerType>${active ? `<pActive>${active}</pActive>` : ''}<Locals>${versions.join('')}</Locals>${extra}</ListMgt::LmVersionTable></pLmVerTable>`;
const clip = (id, o) =>
  `<Element><Sm2TiVideoClip DbId="${id}"><FieldsBlob/><Name>${o.name}</Name><Start>${o.start}</Start><Duration>${o.duration}</Duration><In>0</In><MediaRef>mp-${id}</MediaRef><MediaFilePath>${o.path}</MediaFilePath>${table(`vt-${id}`, o.active, o.versions, o.group ? `<LinkedGroup>${o.group}</LinkedGroup>` : '')}</Sm2TiVideoClip></Element>`;
const track = (id, type, seq, items) =>
  `<Element><Sm2TiTrack DbId="${id}"><FieldsBlob/><Type>${type}</Type><Sequence>${seq}</Sequence><Items>${items}</Items></Sm2TiTrack></Element>`;

async function buildFixture(dir) {
  const s3 = await scattered(['Node A', 'Node B', 'Node C'], [[500, 300], [770, 40], [1040, 460]]);
  const s2 = await scattered(['Base', 'Skin'], [[10, 10], [900, 900]]);
  const one = await scattered(['Solo'], [[190, 180]]);
  const clean3 = bodyHex((await drx('relayout', { content: (await drx('merge', { baseContent: (await drx('generate', { gradeParams: { saturation: 60, label: 'X' } })).content, newNodes: [{ label: 'Y', params: { contrast: 1.2 } }, { label: 'Z', params: { hueRotate: 0.1 } }] })).content })).content);
  const s2stored = await stored(s2);

  const project = `<?xml version="1.0"?><Sm2Project DbId="p1"><FieldsBlob/><ProjectName>FIX</ProjectName><GroupListObj><Sm2GroupList DbId="gl"><GroupList>
<Element><Sm2Group DbId="g1"><FieldsBlob/><Name>Wide</Name>${table('vt-g1', null, [version('g1-pre', 'Pre Clip Grade', 'false', EMPTY_BODY), version('g1-post', 'Post Clip Grade', 'true', s3)])}</Sm2Group></Element>
<Element><Sm2Group DbId="g2"><FieldsBlob/><Name>B-Roll</Name>${table('vt-g2', null, [version('g2-pre', 'Pre Clip Grade', 'false', EMPTY_BODY), version('g2-post', 'Post Clip Grade', 'false', EMPTY_BODY)])}</Sm2Group></Element>
</GroupList></Sm2GroupList></GroupListObj></Sm2Project>`;

  const mp = `<MpFolder><Sm2MpFolder DbId="f1"><Name>Master</Name>
<Sm2Timeline DbId="tl-1"><FieldsBlob/><Name>REEL_01</Name><Sequence><Sm2Sequence DbId="seq-1"><FieldsBlob/><Parent>tl-1</Parent>${table('vt-seq1', 'seq1-v1', [version('seq1-v1', 'Version 1', 'false', EMPTY_BODY, 1)])}</Sm2Sequence></Sequence></Sm2Timeline>
<Sm2Timeline DbId="tl-2"><FieldsBlob/><Name>REEL_02</Name><Sequence><Sm2Sequence DbId="seq-2"><FieldsBlob/><Parent>tl-2</Parent></Sm2Sequence></Sequence></Sm2Timeline>
<Sm2MpVideoClip DbId="mp-a"><FieldsBlob/><Name>A001.mov</Name><MediaFilePath>/x/A001.mov</MediaFilePath>${table('vt-mp-a', 'r1', [version('r1', 'Remote 1', 'true', s2, 1)])}</Sm2MpVideoClip>
<Sm2MpVideoClip DbId="mp-b"><FieldsBlob/><Name>B.mov</Name><MediaFilePath>/x/B.mov</MediaFilePath></Sm2MpVideoClip>
</Sm2MpFolder></MpFolder>`;

  const container = `<Sm2SequenceContainer DbId="c1"><FieldsBlob/><VideoTrackVec>
${track('v1', 0, 'seq-1', [
  clip('a', { name: 'A001.mov', start: 100, duration: 50, path: '/x/A001.mov', group: 'g1', active: 'a2', versions: [version('a1', 'Version 1', 'true', s3), version('a2', 'Version 2', 'true', s2stored)] }),
  clip('b', { name: 'B.mov', start: 150, duration: 50, path: '/x/B.mov', group: 'g2', active: 'b1', versions: [version('b1', 'Version 1', 'false', one)] }),
  clip('c', { name: 'C.mov', start: 200, duration: 10, path: '/x/C.mov', active: 'c1', versions: [version('c1', 'Version 1', 'true', 'deadbeef')] }),
  clip('d', { name: 'D_0001.MP4', start: 300, duration: 10, path: '/x/D_0001.MP4', active: 'd1', versions: [version('d1', 'Version 1', 'true', clean3)] }),
].join(''))}
${track('v2', 0, 'seq-1', clip('e', { name: 'E.mov', start: 100, duration: 20, path: '/x/E.mov', active: 'e1', versions: [version('e1', 'Version 1', 'true', s3)] }))}
${track('v3', 0, 'seq-2', clip('f', { name: 'F.mov', start: 5, duration: 5, path: '/x/F.mov', active: 'f1', versions: [version('f1', 'Version 1', 'true', s3)] }))}
</VideoTrackVec><AudioTrackVec>${track('au1', 1, 'seq-1', '<Element><Sm2TiAudioClip DbId="au"><Name>AU</Name><Start>100</Start><Duration>50</Duration></Sm2TiAudioClip></Element>')}</AudioTrackVec></Sm2SequenceContainer>`;

  const zip = new JSZip();
  zip.file('project.xml', project);
  zip.file('MediaPool/Master/MpFolder.xml', mp);
  zip.file('SeqContainer/c1.xml', container);
  const drpPath = path.join(dir, 'FIX.drp');
  fs.writeFileSync(drpPath, await zip.generateAsync({ type: 'nodebuffer' }));
  return { drpPath, bodies: { s3, s2, one, clean3, s2stored } };
}

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'drp-relayout-'));
const fixture = await buildFixture(dir);
const keysOf = (r) => r.items.map((i) => i.key).sort();

test('node-layout: STORED (0x80) bodies decode and re-wrap in kind', async () => {
  const pos = await layout.readNodePositions(Buffer.from(fixture.bodies.s2stored, 'hex'));
  assert.deepEqual(pos, [[10, 10], [900, 900]]);
  const r = await layout.relayoutBody(Buffer.from(fixture.bodies.s2stored, 'hex'));
  assert.equal(r.body[0], 0x80, 'container kind preserved');
  assert.deepEqual(await layout.readNodePositions(r.body), layout.cleanRowPositions(2));
  assert.deepEqual(await layout.readNodePositions(Buffer.from(EMPTY_BODY, 'hex')), [], 'default body has no node message');
  await assert.rejects(() => layout.relayoutBody(Buffer.from('7f00', 'hex')), /magic/);
});

test('inventory: every graph kind, every local version, with timeline/track/position/group attribution', async () => {
  const r = await drp('relayout_node_graphs', { drpPath: fixture.drpPath, scope: { gradedOnly: false }, includeLabels: true });
  assert.equal(r.dryRun, true);
  assert.equal(r.totals.graphs, 13);
  assert.deepEqual(r.context.kinds, { local: 7, remote: 1, group: 4, sequence: 1 });
  assert.equal(r.totals.empty, 4, 'default bodies are empty, not skipped');
  assert.equal(r.totals.skipped, 1);
  assert.equal(r.skipped[0].key, 'c1');
  assert.equal(r.totals.matched, 8);
  assert.equal(r.totals.alreadyClean, 1);
  assert.equal(r.totals.wouldRelayout, 7);
  assert.equal(r.context.project, 'FIX');
  assert.equal(r.context.multiVersionClips, 1);
  assert.deepEqual(r.context.timelines.map((t) => [t.name, t.tracks, t.clips]), [['REEL_01', 2, 5], ['REEL_02', 1, 1]]);
  assert.deepEqual(r.context.groups, [{ name: 'Wide', clips: 1 }, { name: 'B-Roll', clips: 1 }]);
  const a2 = r.items.find((i) => i.key === 'a2');
  assert.deepEqual(
    { ...a2, before: undefined, after: undefined },
    { key: 'a2', kind: 'local', label: 'REEL_01 V1 #1 A001.mov · Version 2', timeline: 'REEL_01', track: 1, clipIndex: 1, clipId: 'a', clipName: 'A001.mov', start: 100, end: 149, mediaName: 'A001.mov', group: 'Wide', versionId: 'a2', versionName: 'Version 2', active: true, hasCorrection: true, nodes: 2, nodeLabels: ['AI Generated Grade', 'Skin'], status: 'would-relayout', before: undefined, after: undefined },
  );
  assert.equal(r.items.find((i) => i.key === 'a1').active, false, 'the non-active local version is its own graph');
  assert.equal(r.items.find((i) => i.key === 'r1').kind, 'remote');
  assert.equal(r.items.find((i) => i.key === 'g1-post').group, 'Wide');
  assert.equal(r.items.find((i) => i.key === 'd1').status, 'clean');
});

test('scope matrix — each selector narrows the way the operator expects', async () => {
  const run = async (scope) => keysOf(await drp('relayout_node_graphs', { drpPath: fixture.drpPath, scope }));
  assert.deepEqual(await run({}), ['a1', 'a2', 'd1', 'e1', 'f1', 'g1-post', 'r1'], 'default = every graded graph');
  assert.deepEqual(await run({ gradedOnly: false }), ['a1', 'a2', 'b1', 'd1', 'e1', 'f1', 'g1-post', 'r1']);
  assert.deepEqual(await run({ timelines: 'REEL_01' }), ['a1', 'a2', 'd1', 'e1'], 'timeline selector never sweeps group/remote graphs along');
  assert.deepEqual(await run({ timelines: ['REEL_0*'] }), ['a1', 'a2', 'd1', 'e1', 'f1']);
  assert.deepEqual(await run({ timelines: 'REEL_01', tracks: [2] }), ['e1']);
  assert.deepEqual(await run({ frames: [120, 160] }), ['a1', 'a2'], 'overlap, not containment');
  assert.deepEqual(await run({ frames: [120, 160], gradedOnly: false }), ['a1', 'a2', 'b1']);
  assert.deepEqual(await run({ tracks: [1], clipRange: [3, 4] }), ['d1']);
  assert.deepEqual(await run({ clipIds: ['a'] }), ['a1', 'a2'], 'a clip id selects EVERY version of the clip');
  assert.deepEqual(await run({ clipIds: ['a'], versions: 'active' }), ['a2']);
  assert.deepEqual(await run({ excludeClipIds: ['a', 'd'] }), ['e1', 'f1', 'g1-post', 'r1']);
  assert.deepEqual(await run({ names: 'D_*' }), ['d1']);
  assert.deepEqual(await run({ media: '*.mov' }), ['a1', 'a2', 'e1', 'f1', 'r1'], 'media matches clip AND remote graphs');
  assert.deepEqual(await run({ media: '/x/A001*' }), ['a1', 'a2', 'r1'], 'full-path globs too');
  assert.deepEqual(await run({ groups: ['Wide'] }), ['a1', 'a2', 'g1-post'], 'a group = its clips + its own graphs');
  assert.deepEqual(await run({ excludeGroups: ['Wide'] }), ['d1', 'e1', 'f1', 'r1']);
  assert.deepEqual(await run({ versions: 'active' }), ['a2', 'd1', 'e1', 'f1', 'g1-post', 'r1']);
  assert.deepEqual(await run({ versionNames: 'Version 2' }), ['a2']);
  assert.deepEqual(await run({ versionNames: ['Remote*', 'Post*'] }), ['g1-post', 'r1']);
  assert.deepEqual(await run({ kinds: ['group'] }), ['g1-post']);
  assert.deepEqual(await run({ kinds: ['remote', 'sequence'] }), ['r1'], 'the sequence graph is empty');
  assert.deepEqual(await run({ minNodes: 3 }), ['a1', 'd1', 'e1', 'f1', 'g1-post']);
  assert.deepEqual(await run({ maxNodes: 2 }), ['a2', 'r1']);
  assert.deepEqual(await run({ nodeLabels: 'Skin' }), ['a2', 'r1'], 'the remote version shares the 2-node body');
  assert.deepEqual(await run({ nodeLabels: ['node b'] }), ['a1', 'e1', 'f1', 'g1-post'], 'labels match case-insensitively');
  assert.deepEqual(await run([{ names: 'D_*' }, { tracks: [2] }]), ['d1', 'e1'], 'several scopes union');
  assert.deepEqual(await run({ names: 'NOPE*' }), [], 'null control: a scope that matches nothing matches nothing');
  await assert.rejects(() => drp('relayout_node_graphs', { drpPath: fixture.drpPath, scope: { timeline: 'REEL_01' } }), /unrecognized|Unrecognized/i, 'typos in selectors are refused, not ignored');
});

test('write: every matched graph relaid (both local versions, remote, group), everything else byte-identical, read-back verified, idempotent', async () => {
  const outputPath = path.join(dir, 'FIX_CLEANED.drp');
  await assert.rejects(() => drp('relayout_node_graphs', { drpPath: fixture.drpPath, outputPath: fixture.drpPath }), /refusing to overwrite/);
  await assert.rejects(() => drp('relayout_node_graphs', { drpPath: fixture.drpPath, dryRun: false }), /outputPath is required/);

  const w = await drp('relayout_node_graphs', { drpPath: fixture.drpPath, outputPath });
  assert.equal(w.dryRun, false);
  assert.equal(w.totals.relaid, 6);
  assert.equal(w.totals.alreadyClean, 1);
  assert.equal(w.totals.skipped, 1, 'the garbage body is reported, never rewritten');
  assert.equal(w.verify.ok, true);
  assert.equal(w.verify.rewritten, 6);
  assert.equal(w.verify.checked, 13);
  assert.ok(fs.existsSync(outputPath));

  // A second index of the WRITTEN file, from scratch.
  const again = await drp('relayout_node_graphs', { drpPath: outputPath, scope: { gradedOnly: false }, includeLabels: true });
  assert.equal(again.totals.graphs, 13, 'no graph gained or lost');
  assert.equal(again.totals.wouldRelayout, 1, 'only the ungraded single node (b1) is still off the row — it was out of scope');
  assert.equal(again.totals.alreadyClean, 7);
  assert.equal(again.totals.skipped, 1);
  for (const k of ['a1', 'a2', 'd1', 'e1', 'f1', 'g1-post', 'r1']) {
    const it = again.items.find((i) => i.key === k);
    assert.equal(it.status, 'clean', k);
    assert.deepEqual(it.before, layout.cleanRowPositions(it.nodes), k);
  }
  assert.deepEqual(again.items.find((i) => i.key === 'a1').nodeLabels, ['AI Generated Grade', 'Node B', 'Node C'], 'labels (grade content) survive');

  // Raw XML: HasCorrection untouched, untouched bodies byte-identical, container kinds preserved.
  const zip = await JSZip.loadAsync(fs.readFileSync(outputPath));
  const seq = await zip.file('SeqContainer/c1.xml').async('string');
  const mp = await zip.file('MediaPool/Master/MpFolder.xml').async('string');
  const proj = await zip.file('project.xml').async('string');
  const bodyOf = (xml, id) => xml.match(new RegExp(`<ListMgt::LmVersion DbId="${id}">[\\s\\S]*?<Body>([0-9a-fA-F]*)</Body>`))[1];
  assert.equal(bodyOf(seq, 'b1'), fixture.bodies.one, 'out-of-scope body untouched');
  assert.equal(bodyOf(seq, 'c1'), 'deadbeef', 'undecodable body untouched');
  assert.equal(bodyOf(seq, 'd1'), fixture.bodies.clean3, 'already-clean body untouched');
  assert.equal(bodyOf(proj, 'g1-pre'), EMPTY_BODY);
  assert.equal(bodyOf(mp, 'seq1-v1'), EMPTY_BODY);
  assert.equal(bodyOf(seq, 'a2').slice(0, 2), '80', 'STORED container kind preserved on the rewritten version 2');
  assert.equal(bodyOf(seq, 'a1').slice(0, 2), '81');
  assert.notEqual(bodyOf(seq, 'a1'), fixture.bodies.s3);
  assert.equal((seq.match(/<HasCorrection>false<\/HasCorrection>/g) || []).length, 1, 'only b1 was false and still is');
  assert.equal((proj.match(/<HasCorrection>true<\/HasCorrection>/g) || []).length, 1);

  // Idempotence: relaying the clean file writes nothing new.
  const out2 = path.join(dir, 'FIX_CLEANED_2.drp');
  const w2 = await drp('relayout_node_graphs', { drpPath: outputPath, outputPath: out2 });
  assert.equal(w2.totals.relaid, 0);
  assert.equal(w2.totals.alreadyClean, 7);
  assert.equal(w2.verify.ok, true);

  // Null control on write: a scope matching nothing rewrites nothing.
  const out3 = path.join(dir, 'FIX_NONE.drp');
  const w3 = await drp('relayout_node_graphs', { drpPath: fixture.drpPath, outputPath: out3, scope: { names: 'NOPE*' } });
  assert.equal(w3.totals.matched, 0);
  assert.equal(w3.totals.relaid, 0);
  const z3 = await JSZip.loadAsync(fs.readFileSync(out3));
  assert.equal(await z3.file('SeqContainer/c1.xml').async('string'), await (await JSZip.loadAsync(fs.readFileSync(fixture.drpPath))).file('SeqContainer/c1.xml').async('string'));
});

test('write: explicit layout tuning reaches every rewritten graph', async () => {
  const outputPath = path.join(dir, 'FIX_TUNED.drp');
  const w = await drp('relayout_node_graphs', { drpPath: fixture.drpPath, outputPath, scope: { clipIds: ['a'] }, layout: { originX: 100, originY: 50, spacingX: 200 } });
  assert.equal(w.totals.relaid, 2);
  const a1 = w.items.find((i) => i.key === 'a1');
  assert.deepEqual(a1.after, [[100, 50], [300, 50], [500, 50]]);
  const again = await drp('relayout_node_graphs', { drpPath: outputPath, scope: { clipIds: ['a'] }, layout: { originX: 100, originY: 50, spacingX: 200 } });
  assert.equal(again.totals.alreadyClean, 2);
});
