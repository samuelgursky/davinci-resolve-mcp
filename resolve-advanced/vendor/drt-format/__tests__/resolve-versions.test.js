/**
 * Resolve version registry + retargetDRT + capability gate.
 * Self-contained (synthetic DRTs) — no client material, no fixtures needed.
 * Run: node --test packages/drt-format/__tests__/resolve-versions.test.js
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const JSZip = require('jszip');

const drt = require('..');
const { VERSIONS, resolveVersion, readVersionStamp, retargetDRT } = require('../resolve-versions');
const { collectCapabilities, checkCapabilities } = require('../capabilities');

// Build a minimal real-schema DRT (SeqContainer/<uuid>.xml + MpFolder), stamped to a version.
async function makeDrt({ dbAppVer, dbPrjVer, body = '', uuid = 'd179c230-0000-0000-0000-fafe4faf207d' }) {
  const seq =
    `<!--DbAppVer="${dbAppVer}" DbPrjVer="${dbPrjVer}"-->\n` +
    `<Sm2SequenceContainer DbId="${uuid}"><Name>T</Name>` +
    `<VideoTrackVec><Element><Sm2TiTrack DbId="t1"><Type>0</Type><Items>${body}</Items></Sm2TiTrack></Element></VideoTrackVec>` +
    `</Sm2SequenceContainer>`;
  const mp = `<!--DbAppVer="${dbAppVer}" DbPrjVer="${dbPrjVer}"-->\n<MpFolder/>`;
  const zip = new JSZip();
  zip.file(`SeqContainer/${uuid}.xml`, seq);
  zip.file('MediaPool/Master/MpFolder.xml', mp);
  return zip.generateAsync({ type: 'nodebuffer' });
}

const MEDIA_CLIP =
  '<Element><Sm2TiVideoClip DbId="c1"><MediaRef>m1</MediaRef>' +
  '<EffectFiltersBA>00</EffectFiltersBA></Sm2TiVideoClip></Element>' +
  '<Element><Sm2TiTransition DbId="x1"><PrettyType>Cross Dissolve</PrettyType></Sm2TiTransition></Element>';

async function seqOf(buf) {
  const z = await JSZip.loadAsync(buf);
  const p = Object.keys(z.files).find((n) => /SeqContainer\/.+\.xml$/.test(n));
  return z.file(p).async('string');
}

test('registry: known versions resolve to verified stamps', () => {
  assert.equal(resolveVersion(19).dbPrjVer, '14');
  assert.equal(resolveVersion(20).dbPrjVer, '15');
  assert.equal(resolveVersion(21).dbPrjVer, '17');
  assert.equal(resolveVersion('21.0').dbAppVer, '21.0.0.0048');
});

test('registry: unknown version throws with guidance', () => {
  assert.throws(() => resolveVersion(99), /no registry entry for Resolve 99/);
});

test('readVersionStamp parses the SeqContainer header', () => {
  assert.deepEqual(
    readVersionStamp('<!--DbAppVer="20.3.2.0009" DbPrjVer="15"-->'),
    { dbAppVer: '20.3.2.0009', dbPrjVer: '15' },
  );
});

test('retargetDRT: re-stamps to each target, preserves content, adds project shell', async () => {
  const src = await makeDrt({ dbAppVer: '21.0.0.0048', dbPrjVer: '17', body: MEDIA_CLIP });
  for (const tgt of [19, 20, 21]) {
    const out = await retargetDRT(src, tgt);
    const z = await JSZip.loadAsync(out);
    const seq = await seqOf(out);
    assert.deepEqual(readVersionStamp(seq), { dbAppVer: VERSIONS[tgt].dbAppVer, dbPrjVer: VERSIONS[tgt].dbPrjVer });
    assert.ok(z.file('project.xml'), 'DRT must carry a project shell');
    assert.equal((seq.match(/<Sm2TiVideoClip\b/g) || []).length, 1, 'clip preserved');
    assert.ok(seq.includes('Cross Dissolve'), 'dissolve preserved');
    // no residual source stamp anywhere
    const all = (await Promise.all(Object.keys(z.files).filter((n) => n.endsWith('.xml')).map((n) => z.file(n).async('string')))).join('');
    if (tgt !== 21) assert.ok(!all.includes('21.0.0.0048'), 'source stamp fully replaced');
  }
});

test('retargetDRT: value-based — same-version retarget is content-stable', async () => {
  const src = await makeDrt({ dbAppVer: '19.1.3.0007', dbPrjVer: '14', body: MEDIA_CLIP });
  const out = await retargetDRT(src, 19);
  assert.deepEqual(readVersionStamp(await seqOf(out)), { dbAppVer: '19.1.3.0007', dbPrjVer: '14' });
});

test('retargetDRT: rejects a DRT with no SeqContainer', async () => {
  const zip = new JSZip();
  zip.file('nope.xml', '<x/>');
  const buf = await zip.generateAsync({ type: 'nodebuffer' });
  await assert.rejects(() => retargetDRT(buf, 19), /no SeqContainer/);
});

test('capabilities: collectCapabilities detects universal elements, no unknowns', async () => {
  const seq = await seqOf(await makeDrt({ dbAppVer: '21.0.0.0048', dbPrjVer: '17', body: MEDIA_CLIP }));
  const { used, unknownElements } = collectCapabilities(seq);
  assert.ok(used.includes('clip:media'));
  assert.ok(used.includes('transition:cross-dissolve'));
  assert.ok(used.includes('transform:basic'));
  assert.deepEqual(unknownElements, [], 'no uncatalogued Sm2Ti* elements');
});

test('capabilities: gate blocks when a capability exceeds target DbPrjVer', () => {
  // universal cap (min 14) is fine for 14, blocked for an older 13
  assert.equal(checkCapabilities(['clip:media'], [], 14).ok, true);
  assert.equal(checkCapabilities(['clip:media'], [], 13).ok, false);
  // an uncatalogued/future capability is treated as Infinity → always blocked
  const r = checkCapabilities(['feature:from-the-future'], [], 17);
  assert.equal(r.ok, false);
  assert.equal(r.blocked[0].cap, 'feature:from-the-future');
});

test('retargetDRT: downgrade allowed for universal content; force bypasses the gate', async () => {
  const src = await makeDrt({ dbAppVer: '21.0.0.0048', dbPrjVer: '17', body: MEDIA_CLIP });
  // universal content → downgrade to 19 allowed
  const ok = await retargetDRT(src, 19);
  assert.deepEqual(readVersionStamp(await seqOf(ok)), { dbAppVer: '19.1.3.0007', dbPrjVer: '14' });
  // force is accepted (no throw) even when present
  const forced = await retargetDRT(src, 19, { force: true });
  assert.ok(forced.length > 0);
});

test('index re-exports retargetDRT + capabilities surface', () => {
  assert.equal(typeof drt.retargetDRT, 'function');
  assert.equal(typeof drt.resolveVersions.resolveVersion, 'function');
  assert.equal(typeof drt.capabilities.collectCapabilities, 'function');
});
