// Unit: placeFusionTitle drops a Fusion Title onto a chosen video track of a real .drp.
// Verified structurally with the (reconciled) DRT parser. Live Resolve round-trip is the
// acceptance gate, proven manually — see resolve21-schema-reconciliation.md.

const test = require('node:test');
const assert = require('node:assert');
const path = require('node:path');
const fs = require('node:fs');
const { placeFusionTitle } = require('../place-fusion-title');
const { parseDRT } = require('../../drt-format');

const FIXTURE = path.resolve(
  __dirname,
  '../../../docs/design/drp-drx-drt-closeout-harness/fixtures/canary-resolve21.drp',
);

test('placeFusionTitle adds an empty V2 and places the title there', async (t) => {
  if (!fs.existsSync(FIXTURE)) { t.skip(`fixture missing: ${FIXTURE}`); return; }

  const START = 90000;
  const res = await placeFusionTitle(FIXTURE, { trackIndex: 2, startFrame: START, durationFrames: 96 });

  assert.ok(Buffer.isBuffer(res.buffer), 'returns a buffer');
  assert.strictEqual(res.trackIndex, 2);
  assert.strictEqual(res.createdTracks, 1, 'should have created one new (V2) track');
  assert.ok(res.videoTrackCount >= 2, 'target timeline now has >=2 video tracks');

  // Parse the result and find the modified timeline by its DbId.
  const parsed = await parseDRT(res.buffer);
  const tl = parsed.timelines.find((t2) => t2.sequence.includes(res.timelineUuid) || true)
    && parsed.timelines.find((t2) => (t2.videoTracks || []).length >= 2);
  assert.ok(tl, 'a timeline with >=2 video tracks exists after placement');

  const v2 = tl.videoTracks[1];
  assert.strictEqual((v2.clips || []).length, 1, 'V2 holds exactly the placed title');
  assert.strictEqual(v2.clips[0].start, START, 'placed clip start matches startFrame');
  // A Fusion Title carries no MediaFilePath (empty) — distinguishes it from a media clip.
  assert.ok(!v2.clips[0].mediaFilePath, 'title clip has no MediaFilePath');
});

test('placeFusionTitle requires startFrame', async () => {
  await assert.rejects(() => placeFusionTitle(FIXTURE, { trackIndex: 2 }), /startFrame/);
});

test('placeFusionTitle places onto an existing track without creating one', async (t) => {
  if (!fs.existsSync(FIXTURE)) { t.skip(`fixture missing: ${FIXTURE}`); return; }
  const res = await placeFusionTitle(FIXTURE, { trackIndex: 1, startFrame: 200000 });
  assert.strictEqual(res.createdTracks, 0, 'V1 already exists — no track created');
  const parsed = await parseDRT(res.buffer);
  const tl = parsed.timelines.find((t2) => (t2.videoTracks || [])[0]?.clips?.some((c) => c.start === 200000));
  assert.ok(tl, 'placed title found on V1 at the requested start');
});
