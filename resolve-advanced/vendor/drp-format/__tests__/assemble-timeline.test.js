// Unit: assemble a full timeline from a declarative spec (composes the verified primitives).
// Live Resolve round-trip is the acceptance gate.

const test = require('node:test');
const assert = require('node:assert');
const { assembleTimeline } = require('../assemble-timeline');
const { decodeTitleInputs } = require('../composition-text');
const { parseDRT } = require('../../drt-format');

async function compositionTexts(buffer) {
  const JSZip = require('jszip');
  const zip = await JSZip.loadAsync(buffer);
  const out = [];
  for (const n of Object.keys(zip.files)) {
    if (!/SeqContainer\/[^/]+\.xml$|SeqContainer\d*\.xml$/.test(n)) continue;
    const x = await zip.files[n].async('string');
    for (const tag of x.match(/<CompositionBA>[0-9a-fA-F]+<\/CompositionBA>/g) || []) {
      out.push(decodeTitleInputs(tag.replace(/<\/?CompositionBA>/g, '')));
    }
  }
  return out;
}

test('assembleTimeline composes a title (V2) + generator (V3) from a spec', async () => {
  const start = 86400;
  const { buffer, timelineName, startFrame } = await assembleTimeline({
    timelineName: 'Assembled',
    elements: [
      { type: 'generator', generatorName: 'Solid Color', track: 3, startFrame: start, durationFrames: 120 },
      { type: 'title', track: 2, startFrame: start, durationFrames: 120, text: 'HELLO', color: { r: 0.2, g: 0.8, b: 1 } },
    ],
  });
  assert.strictEqual(timelineName, 'Assembled');
  assert.strictEqual(startFrame, 86400);

  const parsed = await parseDRT(buffer);
  const tl = parsed.timelines[0];
  assert.ok(tl.videoTracks.length >= 3, 'V1/V2/V3 present');

  const titles = await compositionTexts(buffer);
  const t = titles.find((x) => x.text === 'HELLO');
  assert.ok(t, 'title text composed');
  assert.deepStrictEqual(t.color, { r: 0.2, g: 0.8, b: 1 }, 'title color composed');
});

test('assembleTimeline places two abutting generators + a transition between them', async () => {
  const s = 86400;
  const { buffer } = await assembleTimeline({
    timelineName: 'GenTrans',
    elements: [
      { type: 'generator', track: 1, startFrame: s, durationFrames: 100 },
      { type: 'generator', track: 1, startFrame: s + 100, durationFrames: 100 },
    ],
    transitions: [{ track: 1, atFrame: s + 100, durationFrames: 24 }],
  });
  const JSZip = require('jszip');
  const zip = await JSZip.loadAsync(buffer);
  let body = '';
  for (const n of Object.keys(zip.files)) {
    if (!/SeqContainer\/[^/]+\.xml$/.test(n)) continue;
    body = await zip.files[n].async('string');
  }
  assert.ok(/<Sm2TiTransition\b/.test(body), 'transition composed between the generators');
});

test('assembleTimeline rejects unknown element types', async () => {
  await assert.rejects(() => assembleTimeline({ elements: [{ type: 'bogus', track: 1, startFrame: 86400 }] }), /unknown type/);
});
