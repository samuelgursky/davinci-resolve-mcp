/**
 * Multi-format retargeting (DRT/DRP/DRX) + auto-detect + capability domains.
 * Self-contained synthetic samples. Run: node --test packages/drt-format/__tests__/multi-format.test.js
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const JSZip = require('jszip');

const drt = require('..');
const { retargetDRT, retargetDRP, retargetDRX, retarget, readVersionStamp, VERSIONS } = require('../resolve-versions');
const { fingerprintFile } = require('../schema-fingerprint');
const { capabilitiesForFormat, domainForFormat } = require('../capability-domains');

const STAMP = (a, p) => `<!--DbAppVer="${a}" DbPrjVer="${p}"-->`;

// A DRP: zip with a FULL project.xml (sentinel marks it must survive) + SeqContainer + MpFolder.
async function makeDrp(dbAppVer, dbPrjVer) {
  const zip = new JSZip();
  zip.file('project.xml', `${STAMP(dbAppVer, dbPrjVer)}\n<SM_Project><FullProjectSentinel>render-presets+color</FullProjectSentinel></SM_Project>`);
  zip.file('SeqContainer/uuid-1.xml', `${STAMP(dbAppVer, dbPrjVer)}\n<Sm2SequenceContainer><Sm2TiVideoClip><MediaRef>m</MediaRef></Sm2TiVideoClip></Sm2SequenceContainer>`);
  zip.file('MediaPool/Master/MpFolder.xml', `${STAMP(dbAppVer, dbPrjVer)}\n<MpFolder/>`);
  return zip.generateAsync({ type: 'nodebuffer' });
}

// A DRX: single XML grade/still.
function makeDrx(dbAppVer, dbPrjVer) {
  return `<?xml version="1.0" encoding="UTF-8"?>\n${STAMP(dbAppVer, dbPrjVer)}\n<Gallery::GyStill DbId="x"><HasCorrection>true</HasCorrection><Body/></Gallery::GyStill>`;
}

async function seqOfZip(buf) {
  const z = await JSZip.loadAsync(buf);
  return z.file(Object.keys(z.files).find((n) => /SeqContainer\/.+\.xml$/.test(n))).async('string');
}

test('retargetDRP re-stamps and PRESERVES the full project.xml (not a shell swap)', async () => {
  const drp = await makeDrp('21.0.0.0048', '17');
  const out = await retargetDRP(drp, 19);
  const z = await JSZip.loadAsync(out);
  const proj = await z.file('project.xml').async('string');
  assert.deepEqual(readVersionStamp(await seqOfZip(out)), { dbAppVer: '19.1.3.0007', dbPrjVer: '14' });
  assert.ok(proj.includes('FullProjectSentinel'), 'DRP project.xml must be kept, not replaced');
  assert.deepEqual(readVersionStamp(proj), { dbAppVer: '19.1.3.0007', dbPrjVer: '14' }, 'project.xml re-stamped too');
});

test('retargetDRT (no project.xml) adds a stamped shell', async () => {
  const zip = new JSZip();
  zip.file('SeqContainer/u.xml', `${STAMP('21.0.0.0048', '17')}\n<Sm2SequenceContainer/>`);
  zip.file('MediaPool/Master/MpFolder.xml', `${STAMP('21.0.0.0048', '17')}\n<MpFolder/>`);
  const out = await retargetDRT(await zip.generateAsync({ type: 'nodebuffer' }), 20);
  const z = await JSZip.loadAsync(out);
  assert.ok(z.file('project.xml'), 'shell added when source had none');
});

test('retargetDRX re-stamps a single-XML grade, keeping the gallery body', async () => {
  const out = await retargetDRX(makeDrx('19.1.3.0007', '14'), 21);
  const xml = out.toString('utf8');
  assert.ok(xml.startsWith('<?xml'), 'still valid XML');
  assert.ok(xml.includes('Gallery::GyStill'), 'grade body preserved');
  assert.deepEqual(readVersionStamp(xml), { dbAppVer: '21.0.0.0048', dbPrjVer: '17' });
});

test('retarget() auto-detects zip (DRP) vs single-XML (DRX)', async () => {
  const drpOut = await retarget(await makeDrp('21.0.0.0048', '17'), 20);
  assert.ok((await JSZip.loadAsync(drpOut)).file('project.xml'), 'zip routed to DRT/DRP handler');
  const drxOut = await retarget(makeDrx('19.1.3.0007', '14'), 20);
  assert.ok(drxOut.toString('utf8').startsWith('<?xml'), 'xml routed to DRX handler');
  assert.deepEqual(readVersionStamp(drxOut.toString('utf8')), { dbAppVer: VERSIONS[20].dbAppVer, dbPrjVer: VERSIONS[20].dbPrjVer });
});

test('fingerprintFile auto-detects format (zip vs DRX xml)', async () => {
  const drpFp = await fingerprintFile(await makeDrp('21.0.0.0048', '17'));
  assert.ok(drpFp.elements.includes('Sm2TiVideoClip'));
  const drxFp = await fingerprintFile(makeDrx('19.1.3.0007', '14'));
  assert.ok(drxFp.elements.some((e) => e.includes('Gallery')), 'DRX gallery vocabulary fingerprinted');
});

test('capability domains: format → domain selection', () => {
  assert.equal(domainForFormat('drt'), 'timeline');
  assert.equal(domainForFormat('.drp'), 'timeline');
  assert.equal(domainForFormat('DRX'), 'color');
  assert.equal(capabilitiesForFormat('drx').domain, 'color');
  assert.equal(capabilitiesForFormat('drt').domain, 'timeline');
  // color gate is structurally present but not yet populated → never blocks, says so
  assert.equal(capabilitiesForFormat('drx').checkCapabilities().ok, true);
  assert.match(capabilitiesForFormat('drx').checkCapabilities().note, /not yet mapped/);
});

test('index re-exports the multi-format surface', () => {
  for (const fn of ['retargetDRP', 'retargetDRX', 'retarget']) assert.equal(typeof drt[fn], 'function');
  assert.equal(typeof drt.capabilityDomains.capabilitiesForFormat, 'function');
  assert.equal(typeof drt.schemaFingerprint.fingerprintFile, 'function');
});
