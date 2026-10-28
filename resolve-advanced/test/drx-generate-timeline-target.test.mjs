// Issue #318: `drx generate` can write a grade a TIMELINE apply loads.
//
// A timeline ApplyGradeFromDRX loads <pTrackVer> (VerType 1). The direct
// generate path wrote no <pTrackVer>, so a timeline apply loaded nothing and
// replaced the timeline graph with an empty one. target:'timeline' writes the
// grade there and marks the clip part uncorrected, the shape the reporter
// applied successfully on Studio 21.1.1.10.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { drxTool } from '../server/tools/drx.mjs';

const GRADE = { contrast: 1.12, pivot: 0.435, gain: [1.03, 1.0, 0.96, 1.0] };

function block(xml, tag) {
  const match = xml.match(new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`));
  return match && match[1];
}

const field = (section, name) => section.match(new RegExp(`<${name}>([^<]*)</${name}>`))[1];

test('the default stays a clip grade with no timeline block', async () => {
  const { content } = await drxTool.handler({ action: 'generate', args: { gradeParams: GRADE } });
  assert.equal(block(content, 'pTrackVer'), null);
  assert.equal(field(block(content, 'pClipFullVer'), 'HasCorrection'), 'true');
});

test("target:'timeline' carries the grade in <pTrackVer>", async () => {
  const { content } = await drxTool.handler({ action: 'generate', args: { gradeParams: GRADE, target: 'timeline' } });
  const track = block(content, 'pTrackVer');
  const clip = block(content, 'pClipFullVer');
  assert.ok(track, 'a timeline-target file must have <pTrackVer>');
  assert.equal(field(track, 'HasCorrection'), 'true');
  assert.equal(field(track, 'VerType'), '1');
  assert.equal(field(clip, 'HasCorrection'), 'false');
  assert.equal(field(track, 'Body'), field(clip, 'Body'), 'the timeline block carries the same grade body');
});

test('the generated timeline grade parses back to the same grade', async () => {
  const clipFile = await drxTool.handler({ action: 'generate', args: { gradeParams: GRADE } });
  const tlFile = await drxTool.handler({ action: 'generate', args: { gradeParams: GRADE, target: 'timeline' } });
  const a = await drxTool.handler({ action: 'parse', args: { content: clipFile.content } });
  const b = await drxTool.handler({ action: 'parse', args: { content: tlFile.content } });
  assert.equal(b.nodes.length, a.nodes.length);
});

test('an unknown target is refused', async () => {
  await assert.rejects(drxTool.handler({ action: 'generate', args: { gradeParams: GRADE, target: 'track' } }));
});
