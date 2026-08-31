// The conform bridge: normalized interchange events → drt.assemble spec.
// Frame math is nominal-base (v2.104.6) → 24fps template timeline, earliest
// event anchored at origin 86400; butt cuts must stay gapless through the
// conversion, retimes flatten into the ledger, overlaps refuse.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { eventsToAssembleSpec, eventsToEDL } from '../server/author-interchange.mjs';
import { parseEDL } from '../server/editorial.mjs';

const MAP = {
  TAPE1: { mediaFilePath: '/m/a.mp4', spec: { width: 640, height: 360, frameCount: 480, fps: 24 } },
  TAPE2: { mediaFilePath: '/m/b.mp4', spec: { width: 640, height: 360, frameCount: 480, fps: 24 } },
};

test('a 24fps EDL maps to origin-anchored gapless cuts grouped by source', () => {
  const edl = [
    'TITLE: BRIDGE',
    'FCM: NON-DROP FRAME',
    '001  TAPE1 V     C        00:00:04:00 00:00:06:00 01:00:00:00 01:00:02:00',
    '002  TAPE2 V     C        00:00:00:00 00:00:01:00 01:00:02:00 01:00:03:00',
    '003  TAPE1 V     C        00:00:07:00 00:00:08:00 01:00:03:00 01:00:04:00',
    '',
  ].join('\n');
  const events = parseEDL(edl, { fps: 24 });
  const { spec, report } = eventsToAssembleSpec(events, { sourceMap: MAP, timelineName: 'B' });
  assert.equal(spec.media.length, 2);
  const t1 = spec.media.find((m) => m.mediaFilePath === '/m/a.mp4');
  const t2 = spec.media.find((m) => m.mediaFilePath === '/m/b.mp4');
  assert.deepEqual(t1.cuts, [
    { startFrame: 86400, durationFrames: 48, srcIn: 96 },
    { startFrame: 86472, durationFrames: 24, srcIn: 168 },
  ]);
  assert.deepEqual(t2.cuts, [{ startFrame: 86448, durationFrames: 24, srcIn: 0 }]);
  assert.equal(report.videoEvents, 3);
  assert.equal(report.flattenedRetimes.length, 0);
});

test('NTSC 29.97 events convert nominal→24 and stay gapless at the joins', () => {
  const edl = [
    'TITLE: NTSC',
    'FCM: NON-DROP FRAME',
    '001  TAPE1 V     C        00:00:10:00 00:01:10:00 01:00:00:00 01:01:00:00',
    '002  TAPE2 V     C        00:00:00:00 00:00:30:00 01:01:00:00 01:01:30:00',
    '',
  ].join('\n');
  const events = parseEDL(edl, { fps: 30000 / 1001 });
  const { spec } = eventsToAssembleSpec(events, { sourceMap: MAP });
  const all = spec.media.flatMap((m) => m.cuts).sort((a, b) => a.startFrame - b.startFrame);
  // 1800 nominal frames @30 → 1440 timeline frames @24; joins butt exactly.
  assert.equal(all[0].startFrame, 86400);
  assert.equal(all[0].durationFrames, 1440);
  assert.equal(all[1].startFrame, 86400 + 1440);
  assert.equal(all[1].durationFrames, 720);
});

test('retimes flatten into the ledger; overlaps refuse; unmapped reels refuse', () => {
  const base = { track: 'V', srcIn: 0, srcOut: 48, fps: 24 };
  const retimed = [{ ...base, index: 1, source: 'TAPE1', recIn: 0, recOut: 48, speed: 50 }];
  const r1 = eventsToAssembleSpec(retimed, { sourceMap: MAP });
  assert.equal(r1.report.flattenedRetimes.length, 1);
  const overlapping = [
    { ...base, index: 1, source: 'TAPE1', recIn: 0, recOut: 48 },
    { ...base, index: 2, source: 'TAPE2', recIn: 24, recOut: 72 },
  ];
  assert.throws(() => eventsToAssembleSpec(overlapping, { sourceMap: MAP }), /overlap/);
  const unmapped = [{ ...base, index: 1, source: 'NOPE', recIn: 0, recOut: 48 }];
  assert.throws(() => eventsToAssembleSpec(unmapped, { sourceMap: MAP }), /unmapped source reel/);
});

test('round trip: events → EDL → events → spec is stable', () => {
  const events = [
    { index: 1, track: 'V', source: 'TAPE1', srcIn: 96, srcOut: 144, recIn: 86400, recOut: 86448, fps: 24 },
    { index: 2, track: 'V', source: 'TAPE2', srcIn: 0, srcOut: 24, recIn: 86448, recOut: 86472, fps: 24 },
  ];
  const text = eventsToEDL(events, { fps: 24 });
  const back = parseEDL(text, { fps: 24 });
  const { spec } = eventsToAssembleSpec(back, { sourceMap: MAP });
  const all = spec.media.flatMap((m) => m.cuts).sort((a, b) => a.startFrame - b.startFrame);
  assert.deepEqual(all.map((c) => [c.startFrame, c.durationFrames, c.srcIn]),
    [[86400, 48, 96], [86448, 24, 0]]);
});

// Cross-dissolve authoring (render-verified on 19.1.3.7: offline
// Sm2TiTransition over transplanted media blends 124→181.6→234 at the cut).
// Authored only when a predecessor abuts the cut AND both sides have handle
// media for the centered span; otherwise dropped WITH the reason.
test('an EDL dissolve with handles both sides is authored as a transition', () => {
  const edl = [
    'TITLE: DIS',
    'FCM: NON-DROP FRAME',
    '001  TAPE1 V     C        00:00:01:00 00:00:03:00 01:00:00:00 01:00:02:00',
    '002  TAPE2 V     D    024 00:00:01:00 00:00:03:00 01:00:02:00 01:00:04:00',
    '',
  ].join('\n');
  const { spec, report } = eventsToAssembleSpec(parseEDL(edl, { fps: 24 }), { sourceMap: MAP });
  assert.deepEqual(spec.transitions, [{ track: 1, atFrame: 86448, durationFrames: 24 }]);
  assert.deepEqual(report.authoredTransitions, spec.transitions);
  assert.equal(report.droppedTransitions.length, 0);
});

test('a dissolve with no handle on the incoming side drops with the reason', () => {
  const edl = [
    'TITLE: DIS',
    'FCM: NON-DROP FRAME',
    '001  TAPE1 V     C        00:00:01:00 00:00:03:00 01:00:00:00 01:00:02:00',
    '002  TAPE2 V     D    024 00:00:00:00 00:00:02:00 01:00:02:00 01:00:04:00',
    '',
  ].join('\n');
  const { spec, report } = eventsToAssembleSpec(parseEDL(edl, { fps: 24 }), { sourceMap: MAP });
  assert.equal(spec.transitions, undefined);
  assert.equal(report.authoredTransitions.length, 0);
  assert.equal(report.droppedTransitions.length, 1);
  assert.match(report.droppedTransitions[0].reason, /incoming srcIn < half/);
});

test('a dissolve whose outgoing tail runs off the media drops with the reason', () => {
  const edl = [
    'TITLE: DIS',
    'FCM: NON-DROP FRAME',
    // TAPE1 is 480 frames; this cut ends at source frame 480 — zero tail handle.
    '001  TAPE1 V     C        00:00:18:00 00:00:20:00 01:00:00:00 01:00:02:00',
    '002  TAPE2 V     D    024 00:00:01:00 00:00:03:00 01:00:02:00 01:00:04:00',
    '',
  ].join('\n');
  const { spec, report } = eventsToAssembleSpec(parseEDL(edl, { fps: 24 }), { sourceMap: MAP });
  assert.equal(spec.transitions, undefined);
  assert.match(report.droppedTransitions[0].reason, /outgoing tail media < half/);
});

test('a dissolve with a record gap before it drops as no-abutting-predecessor', () => {
  const edl = [
    'TITLE: DIS',
    'FCM: NON-DROP FRAME',
    '001  TAPE1 V     C        00:00:01:00 00:00:03:00 01:00:00:00 01:00:02:00',
    '002  TAPE2 V     D    024 00:00:01:00 00:00:03:00 01:00:03:00 01:00:05:00',
    '',
  ].join('\n');
  const { spec, report } = eventsToAssembleSpec(parseEDL(edl, { fps: 24 }), { sourceMap: MAP });
  assert.equal(spec.transitions, undefined);
  assert.match(report.droppedTransitions[0].reason, /no abutting predecessor/);
});
