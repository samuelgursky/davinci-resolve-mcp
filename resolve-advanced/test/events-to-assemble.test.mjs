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

test('forward retimes author, reverse flattens; overlaps refuse; unmapped reels refuse', () => {
  const base = { track: 'V', srcIn: 0, srcOut: 48, fps: 24 };
  const retimed = [{ ...base, index: 1, source: 'TAPE1', recIn: 0, recOut: 48, speed: 50 }];
  const r1 = eventsToAssembleSpec(retimed, { sourceMap: MAP });
  assert.equal(r1.report.flattenedRetimes.length, 0);
  assert.deepEqual(r1.report.authoredRetimes, [{ index: 1, source: 'TAPE1', speed: 50 }]);
  assert.equal(r1.spec.media[0].cuts[0].speed, 0.5);
  const reversed = [{ ...base, index: 1, source: 'TAPE1', recIn: 0, recOut: 48, speed: 100, reverse: true }];
  const r2 = eventsToAssembleSpec(reversed, { sourceMap: MAP });
  assert.equal(r2.report.flattenedRetimes.length, 1);
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

// Multi-track video: parsers number video tracks (V, V2, …), cuts carry the
// track, overlap is judged PER TRACK (V2 stacking over V1 is legitimate).
import { parseOTIO } from '../server/editorial.mjs';

const rt = (value, rate = 24) => ({ OTIO_SCHEMA: 'RationalTime.1', value, rate });
const clip = (name, srcIn, dur) => ({
  OTIO_SCHEMA: 'Clip.1', name,
  source_range: { OTIO_SCHEMA: 'TimeRange.1', start_time: rt(srcIn), duration: rt(dur) },
  media_reference: { name },
});
const gap = (dur) => ({ OTIO_SCHEMA: 'Gap.1', source_range: { duration: rt(dur) } });
const vtrack = (children) => ({ OTIO_SCHEMA: 'Track.1', kind: 'Video', children });

test('two-video-track OTIO maps V2 cuts with track and passes per-track overlap', () => {
  const otio = {
    OTIO_SCHEMA: 'Timeline.1',
    tracks: { children: [
      vtrack([clip('TAPE1', 24, 96)]),
      vtrack([gap(32), clip('TAPE2', 24, 32)]),
    ] },
  };
  const events = parseOTIO(otio, { fps: 24 });
  assert.deepEqual([...new Set(events.map((e) => e.track))].sort(), ['V', 'V2']);
  const { spec, report } = eventsToAssembleSpec(events, { sourceMap: MAP });
  const t1 = spec.media.find((m) => m.mediaFilePath === '/m/a.mp4');
  const t2 = spec.media.find((m) => m.mediaFilePath === '/m/b.mp4');
  assert.deepEqual(t1.cuts, [{ startFrame: 86400, durationFrames: 96, srcIn: 24 }]);
  assert.deepEqual(t2.cuts, [{ startFrame: 86432, durationFrames: 32, srcIn: 24, track: 2 }]);
  assert.equal(report.upperTrackCutsVideoOnly, 1);
});

test('overlap on the SAME video track still refuses, naming the track', () => {
  const otio = {
    OTIO_SCHEMA: 'Timeline.1',
    tracks: { children: [
      vtrack([clip('TAPE1', 0, 48)]),
      vtrack([gap(24), clip('TAPE2', 0, 48), gap(1), clip('TAPE2', 100, 48)]),
    ] },
  };
  // Force a same-track overlap: V2 children with overlapping record ranges can't
  // come from sequential OTIO children, so collide V1 with itself via raw events.
  const events = parseOTIO(otio, { fps: 24 });
  const bad = events.concat([{ ...events[0], index: 99, recIn: 24, recOut: 72 }]);
  assert.throws(() => eventsToAssembleSpec(bad, { sourceMap: MAP }), /overlap on video track 1/);
});

// Constant-speed retime authoring: r19 keyed Sm2TimeMap (Resolve 19 silently
// IGNORES the R21 protobuf keyframe form on import — measured; the keyed form
// read back source 0..48 over 96 record frames and rendered live).
import { createRequire } from 'node:module';
const requireCjs = createRequire(import.meta.url);
const { buildConstantSpeedTimemapKeyed } = requireCjs('../vendor/drp-format/media-timemap.js');
import fs from 'node:fs';

test('the r19 keyed timemap encoder is byte-exact against the live harvest', () => {
  // Fixture: MediaTimemapBA of a 50% clip authored BY RESOLVE 19.1.3.7 itself
  // (XMEML retime import → SaveProject → ExportProject → harvest).
  const harvest = fs.readFileSync(new URL('./fixtures-r19-timemap-50pct.hex', import.meta.url), 'utf8').trim();
  const mine = buildConstantSpeedTimemapKeyed({
    speed: 0.5, sourceFrames: 192, fps: 24,
    uniqueId: 'b025dc86-ac50-4796-a222-4c8e62679164',
  });
  assert.equal(mine.toString('hex'), harvest);
});

test('OTIO LinearTimeWarp authors cut.speed; reverse flattens with the reason', () => {
  const rtv = (value) => ({ OTIO_SCHEMA: 'RationalTime.1', value, rate: 24 });
  const otio = { OTIO_SCHEMA: 'Timeline.1', tracks: { children: [
    { OTIO_SCHEMA: 'Track.1', kind: 'Video', children: [
      { OTIO_SCHEMA: 'Clip.1', name: 'TAPE1',
        source_range: { start_time: rtv(96), duration: rtv(48) },
        media_reference: { name: 'TAPE1' },
        effects: [{ OTIO_SCHEMA: 'LinearTimeWarp.1', time_scalar: 0.5 }] },
      { OTIO_SCHEMA: 'Clip.1', name: 'TAPE2',
        source_range: { start_time: rtv(120), duration: rtv(24) },
        media_reference: { name: 'TAPE2' },
        effects: [{ OTIO_SCHEMA: 'LinearTimeWarp.1', time_scalar: -1 }] },
    ] },
  ] } };
  const { spec, report } = eventsToAssembleSpec(parseOTIO(otio, { fps: 24 }), { sourceMap: MAP });
  const t1 = spec.media.find((m) => m.mediaFilePath === '/m/a.mp4');
  assert.deepEqual(t1.cuts, [{ startFrame: 86400, durationFrames: 48, srcIn: 96, speed: 0.5 }]);
  assert.deepEqual(report.authoredRetimes, [{ index: 1, source: 'TAPE1', speed: 50 }]);
  assert.equal(report.flattenedRetimes.length, 1);
  assert.match(report.flattenedRetimes[0].reason, /reverse not supported/);
});
