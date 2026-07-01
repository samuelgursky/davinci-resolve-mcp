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
