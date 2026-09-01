// Unit: place a built-in generator (Sm2TiGenerator) on a chosen track. Live Resolve
// round-trip is the acceptance gate (see resolve21-schema-reconciliation.md).

const test = require('node:test');
const assert = require('node:assert');
const { placeGenerator } = require('../place-generator');
const { createEmptyProject } = require('../author-project');

async function genOnTrack(buffer, trackIdx) {
  const JSZip = require('jszip');
  const zip = await JSZip.loadAsync(buffer);
  for (const n of Object.keys(zip.files)) {
    if (!/SeqContainer\/[^/]+\.xml$|SeqContainer\d*\.xml$/.test(n)) continue;
    const x = await zip.files[n].async('string');
    const vtv = (x.match(/<VideoTrackVec>([\s\S]*?)<\/VideoTrackVec>/) || [null, ''])[1];
    const tracks = vtv.match(/<Element>\s*<Sm2TiTrack\b[\s\S]*?<\/Sm2TiTrack>\s*<\/Element>/g) || [];
    return tracks[trackIdx - 1] || '';
  }
  return '';
}

test('placeGenerator drops a Solid Color generator on V2 from scratch', async () => {
  const { buffer, startFrame } = await createEmptyProject({ timelineName: 'Gen' });
  const res = await placeGenerator(buffer, { trackIndex: 2, startFrame, durationFrames: 90 });
  assert.strictEqual(res.generatorName, 'Solid Color');
  assert.strictEqual(res.createdTracks, 1);
  const v2 = await genOnTrack(res.buffer, 2);
  assert.ok(/<Sm2TiGenerator\b/.test(v2), 'V2 holds an Sm2TiGenerator');
  assert.ok(/<PrettyType>Solid Color<\/PrettyType>/.test(v2), 'PrettyType set');
  assert.ok(new RegExp(`<Start>${startFrame}</Start>`).test(v2), 'start set');
  assert.ok(/<Duration>90<\/Duration>/.test(v2), 'duration set');
});

test('placeGenerator honors generatorName + requires startFrame', async () => {
  const { buffer, startFrame } = await createEmptyProject();
  const res = await placeGenerator(buffer, { generatorName: 'Gray Scale', trackIndex: 1, startFrame });
  const v1 = await genOnTrack(res.buffer, 1);
  assert.ok(/<PrettyType>Gray Scale<\/PrettyType>/.test(v1));
  await assert.rejects(() => placeGenerator(buffer, { trackIndex: 1 }), /startFrame/);
});

// E110: Solid Color fill colour. Ground truth is Resolve 19.1.3.7's OWN writer:
// FCP7 generatoritem fillcolor red / blue imported, rendered Y81 U90 V240 and
// Y41 U240 V110 (BT.601 limited-range exact), and EXPORT_DRT wrote these two
// 55-byte EffectFiltersBA blobs — only the ARGB words differ.
const { solidColorEffectBlob, decodeSolidColorEffectBlob } = require('../place-generator');
const RED_BLOB = '000000020000002f800a2c080a18004a004a2408061a0f0a0d320b01ffffffff000000000000220f0a0d320b00ffff0000000000000000';
const BLUE_BLOB = '000000020000002f800a2c080a18004a004a2408061a0f0a0d320b01ffff00000000ffff0000220f0a0d320b00ffff0000000000000000';

test('solidColorEffectBlob reproduces Resolve-written red and blue byte-for-byte (E110)', () => {
  assert.equal(solidColorEffectBlob({ r: 1, g: 0, b: 0 }), RED_BLOB);
  assert.equal(solidColorEffectBlob({ r: 0, g: 0, b: 255 }), BLUE_BLOB); // 0..255 ints accepted
  assert.deepEqual(decodeSolidColorEffectBlob(RED_BLOB), { a: 1, r: 1, g: 0, b: 0 });
  assert.deepEqual(decodeSolidColorEffectBlob(BLUE_BLOB), { a: 1, r: 0, g: 0, b: 1 });
  const mid = decodeSolidColorEffectBlob(solidColorEffectBlob({ r: 0.5, g: 0.25, b: 0.75 }));
  assert.ok(Math.abs(mid.r - 0.5) < 1e-4 && Math.abs(mid.g - 0.25) < 1e-4 && Math.abs(mid.b - 0.75) < 1e-4);
  // Null controls: not-that-shape decodes to null; out-of-range refuses.
  assert.equal(decodeSolidColorEffectBlob(''), null);
  assert.equal(decodeSolidColorEffectBlob('00' + RED_BLOB), null);
  assert.throws(() => solidColorEffectBlob({ r: 300, g: 0, b: 0 }), /exceeds range|0\.\.255/);
  assert.throws(() => solidColorEffectBlob({ r: -1, g: 0, b: 0 }), />= 0/);
});

test('placeGenerator writes the colour blob only when a colour is given (E110)', async () => {
  const { buffer, startFrame } = await createEmptyProject({ timelineName: 'GenColour' });
  const withColour = await placeGenerator(buffer, { startFrame, durationFrames: 48, trackIndex: 2, color: { r: 1, g: 1, b: 1 } });
  const v2 = await genOnTrack(withColour.buffer, 2);
  assert.ok(v2.includes(`<EffectFiltersBA>${solidColorEffectBlob({ r: 1, g: 1, b: 1 })}</EffectFiltersBA>`), 'white blob authored');
  assert.deepEqual(withColour.color, { r: 1, g: 1, b: 1, a: 1 });
  const plain = await placeGenerator(buffer, { startFrame, durationFrames: 48, trackIndex: 2 });
  const v2plain = await genOnTrack(plain.buffer, 2);
  assert.ok(/<EffectFiltersBA\s*\/>|<EffectFiltersBA>\s*<\/EffectFiltersBA>/.test(v2plain), 'default stays the empty blob');
  assert.equal(plain.color, null);
});
