/**
 * Schema fingerprint + diff. Self-contained (synthetic XML), no fixtures.
 * Run: node --test packages/drt-format/__tests__/schema-fingerprint.test.js
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const JSZip = require('jszip');

const drt = require('..');
const { schemaFingerprint, diffFingerprints, fingerprintDrt } = require('../schema-fingerprint');

const SEQ_19 =
  '<Sm2SequenceContainer><VideoTrackVec><Element><Sm2TiTrack><Type>0</Type><Items>' +
  '<Element><Sm2TiVideoClip><MediaRef>m</MediaRef></Sm2TiVideoClip></Element>' +
  '<Element><Sm2TiTransition><PrettyType>Cross Dissolve</PrettyType></Sm2TiTransition></Element>' +
  '</Items></Sm2TiTrack></Element></VideoTrackVec></Sm2SequenceContainer>';

// same content + one new element/prettyType, as a "newer version" would add
const SEQ_21 = SEQ_19.replace(
  '</Items></Sm2TiTrack>',
  '<Element><Sm2TiAudioClip><PrettyType>Smooth Cut</PrettyType></Sm2TiAudioClip></Element></Items><GeometryTrackVec/></Sm2TiTrack>',
);

test('schemaFingerprint extracts distinct element tags + prettyTypes, sorted', () => {
  const fp = schemaFingerprint(SEQ_19);
  assert.ok(fp.elements.includes('Sm2TiVideoClip'));
  assert.ok(fp.elements.includes('Sm2TiTransition'));
  assert.ok(fp.elements.includes('VideoTrackVec'));
  assert.deepEqual(fp.prettyTypes, ['Cross Dissolve']);
  // sorted + de-duplicated
  assert.deepEqual(fp.elements, [...new Set(fp.elements)].sort());
});

test('diffFingerprints isolates added/removed (older -> newer)', () => {
  const d = diffFingerprints(schemaFingerprint(SEQ_19), schemaFingerprint(SEQ_21));
  assert.deepEqual(d.elements.added.sort(), ['GeometryTrackVec', 'Sm2TiAudioClip']);
  assert.deepEqual(d.elements.removed, []);
  assert.deepEqual(d.prettyTypes.added, ['Smooth Cut']);
});

test('diff of identical fingerprints is empty', () => {
  const fp = schemaFingerprint(SEQ_19);
  const d = diffFingerprints(fp, fp);
  assert.deepEqual(d.elements, { added: [], removed: [] });
  assert.deepEqual(d.prettyTypes, { added: [], removed: [] });
});

test('fingerprintDrt reads the first SeqContainer of a real-schema DRT', async () => {
  const zip = new JSZip();
  zip.file('SeqContainer/abc-uuid.xml', SEQ_21);
  const buf = await zip.generateAsync({ type: 'nodebuffer' });
  const fp = await fingerprintDrt(buf);
  assert.ok(fp.elements.includes('Sm2TiAudioClip'));
  assert.ok(fp.prettyTypes.includes('Smooth Cut'));
});

test('index re-exports the fingerprint surface', () => {
  assert.equal(typeof drt.schemaFingerprint.schemaFingerprint, 'function');
  assert.equal(typeof drt.schemaFingerprint.diffFingerprints, 'function');
  assert.equal(typeof drt.schemaFingerprint.fingerprintDrt, 'function');
});
