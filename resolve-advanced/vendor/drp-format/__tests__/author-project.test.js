// Unit: create a fresh importable project from scratch, then populate it.
// Live Resolve round-trip is the acceptance gate (proven manually — see
// resolve21-schema-reconciliation.md).

const test = require('node:test');
const assert = require('node:assert');
const { createEmptyProject } = require('../author-project');
const { placeFusionTitle } = require('../place-fusion-title');
const { decodeTitleText } = require('../composition-text');
const { parseDRT } = require('../../drt-format');

test('createEmptyProject returns an importable empty timeline', async () => {
  const { buffer, timelineName } = await createEmptyProject();
  assert.strictEqual(timelineName, 'Timeline 1');
  const parsed = await parseDRT(buffer);
  assert.strictEqual(parsed.timelines.length, 1, 'one timeline');
  const tl = parsed.timelines[0];
  assert.ok((tl.videoTracks || []).length >= 1, 'has a video track');
  assert.strictEqual((tl.videoTracks[0].clips || []).length, 0, 'timeline is empty');
});

test('createEmptyProject renames the timeline', async () => {
  const { buffer } = await createEmptyProject({ timelineName: 'My Fresh Cut' });
  const JSZip = require('jszip');
  const zip = await JSZip.loadAsync(buffer);
  const mp = await zip.file('MediaPool/Master/MpFolder.xml').async('string');
  assert.ok(mp.includes('<Name>My Fresh Cut</Name>'), 'renamed in media pool');
  assert.ok(!mp.includes('<Name>Timeline 1</Name>'), 'default name gone');
});

test('createEmptyProject rejects angle brackets in the name', async () => {
  await assert.rejects(() => createEmptyProject({ timelineName: 'bad<name>' }), /< or >/);
});

test('from scratch: createEmptyProject -> placeFusionTitle on V2 with text', async () => {
  const { buffer, startFrame } = await createEmptyProject({ timelineName: 'Scratch' });
  assert.strictEqual(startFrame, 86400, 'timeline origin exposed for correct clip placement');
  const res = await placeFusionTitle(buffer, { trackIndex: 2, startFrame, durationFrames: 120, text: 'FROM SCRATCH' });
  // The placed title is on V2 with the requested text.
  const JSZip = require('jszip');
  const zip = await JSZip.loadAsync(res.buffer);
  let text = null;
  for (const n of Object.keys(zip.files)) {
    if (!/SeqContainer\/[^/]+\.xml$|SeqContainer\d*\.xml$/.test(n)) continue;
    const xml = await zip.files[n].async('string');
    for (const tag of xml.match(/<CompositionBA>[0-9a-fA-F]+<\/CompositionBA>/g) || []) {
      const t = decodeTitleText(tag.replace(/<\/?CompositionBA>/g, ''));
      if (t === 'FROM SCRATCH') text = t;
    }
  }
  assert.strictEqual(text, 'FROM SCRATCH', 'title text present');

  const parsed = await parseDRT(res.buffer);
  const tl = parsed.timelines.find((t2) => (t2.videoTracks || []).length >= 2);
  assert.ok(tl, 'V2 exists');
  assert.strictEqual(tl.videoTracks[1].clips.length, 1, 'title on V2');
});
