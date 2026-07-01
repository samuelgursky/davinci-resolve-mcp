// Regression: parse a REAL DaVinci Resolve 21 export.
//
// Resolve's on-disk schema differs from the tool-authored convention in two
// ways that previously made parseDRT blind to real exports:
//   1. SeqContainer entries are named `SeqContainer/<uuid>.xml`, not `<folder>/SeqContainer<N>.xml`.
//   2. Tracks are `<Sm2TiTrack>` with a `<Type>` discriminator, not `<Sm2TiVideoTrack>`/`<Sm2TiAudioTrack>`.
//
// Ground-truth fixture captured from Resolve Studio 21.0.0.48 via
// project_manager.export_project (see docs/.../resolve-verifications.md, P3.2).

const test = require('node:test');
const assert = require('node:assert');
const path = require('node:path');
const fs = require('node:fs');
const { parseDRT } = require('../index');

const FIXTURE = path.resolve(
  __dirname,
  '../../../docs/design/drp-drx-drt-closeout-harness/fixtures/canary-resolve21.drp',
);

test('parseDRT reads a real Resolve 21 export (SeqContainer/<uuid>.xml + Sm2TiTrack)', async (t) => {
  if (!fs.existsSync(FIXTURE)) {
    t.skip(`fixture missing: ${FIXTURE}`);
    return;
  }
  const parsed = await parseDRT(FIXTURE);

  // SeqContainer/<uuid>.xml entries must be discovered (regression: previously threw
  // "no SeqContainer*.xml entries found").
  assert.ok(parsed.timelines.length >= 2, `expected >=2 timelines, got ${parsed.timelines.length}`);

  // At least one timeline must surface video + audio tracks parsed from real <Sm2TiTrack> elements
  // (regression: previously every track count was 0 because only Sm2TiVideoTrack was matched).
  const withClips = parsed.timelines.filter((tl) =>
    (tl.videoTracks || []).some((v) => (v.clips || []).length > 0),
  );
  assert.ok(withClips.length >= 1, 'expected at least one timeline with video clips');

  const tl = withClips[0];
  assert.ok((tl.videoTracks || []).length >= 1, 'expected at least one video track');
  assert.ok((tl.audioTracks || []).length >= 1, 'expected at least one audio track');

  const clip = tl.videoTracks[0].clips[0];
  assert.ok(clip.clipId, 'clip should have a DbId');
  assert.strictEqual(typeof clip.start, 'number', 'clip start should parse to a number');
  assert.strictEqual(typeof clip.duration, 'number', 'clip duration should parse to a number');
  assert.ok(clip.mediaFilePath && clip.mediaFilePath.length > 0, 'real media clip should have a MediaFilePath');
  // Real Resolve clips carry a grade Body blob (ListMgt::LmVersion) — parser should surface it.
  assert.ok(clip.bodyHex && clip.bodyHex.length > 0, 'real clip should expose a grade bodyHex');
});
