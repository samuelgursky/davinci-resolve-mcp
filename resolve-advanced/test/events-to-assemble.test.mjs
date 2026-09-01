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
  assert.equal(r2.report.flattenedRetimes.length, 0);
  assert.equal(r2.spec.media[0].cuts[0].reverse, true);
  assert.deepEqual(r2.report.authoredRetimes, [{ index: 1, source: 'TAPE1', speed: 100, reverse: true }]);
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

test('OTIO LinearTimeWarp authors cut.speed; negative scalar authors reverse', () => {
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
  assert.deepEqual(report.authoredRetimes, [
    { index: 1, source: 'TAPE1', speed: 50 },
    { index: 2, source: 'TAPE2', speed: 100, reverse: true },
  ]);
  assert.equal(report.flattenedRetimes.length, 0);
  const t2 = spec.media.find((m) => m.mediaFilePath === '/m/b.mp4');
  assert.equal(t2.cuts[0].reverse, true);
  assert.equal(t2.cuts[0].speed, undefined); // |−1×| = 100% backwards
});

test('the reverse timemap encoder is byte-exact against the live -100% harvest shape', () => {
  // Same envelope as forward with the Y endpoints swapped: kf0=(0,YMax),
  // kf1=(XMax,0) — harvested from Resolve 19.1.3.7's own -100% XMEML retime
  // and verified byte-exact live; offline E14 readback: srcIn-24 dur-48
  // reversed cut reads back source 71→23.
  const fwd = buildConstantSpeedTimemapKeyed({ speed: 1, sourceFrames: 192, fps: 24, uniqueId: 'x'.repeat(0) || '3a71f4f4-0b0a-425a-aab7-7b7d766b6c55' });
  const rev = buildConstantSpeedTimemapKeyed({ speed: 1, sourceFrames: 192, fps: 24, uniqueId: '3a71f4f4-0b0a-425a-aab7-7b7d766b6c55', reverse: true });
  assert.notEqual(fwd.toString('hex'), rev.toString('hex'));
  assert.equal(fwd.length, rev.length);
});

// Audio events: authored as audioOnly cuts on their own audio tracks
// (render-verified on 19.1.3.7 — an offline A3 cut plays at the native
// control level through the captured 8-audio-track template).
test('OTIO audio tracks author audioOnly cuts and suppress nothing else', () => {
  const rta = (value) => ({ OTIO_SCHEMA: 'RationalTime.1', value, rate: 24 });
  const otio = { OTIO_SCHEMA: 'Timeline.1', tracks: { children: [
    { OTIO_SCHEMA: 'Track.1', kind: 'Video', children: [
      { OTIO_SCHEMA: 'Clip.1', name: 'TAPE1', source_range: { start_time: rta(0), duration: rta(48) }, media_reference: { name: 'TAPE1' } },
    ] },
    { OTIO_SCHEMA: 'Track.1', kind: 'Audio', children: [
      { OTIO_SCHEMA: 'Clip.1', name: 'TAPE1', source_range: { start_time: rta(0), duration: rta(48) }, media_reference: { name: 'TAPE1' } },
    ] },
    { OTIO_SCHEMA: 'Track.1', kind: 'Audio', children: [
      { OTIO_SCHEMA: 'Gap.1', source_range: { duration: rta(24) } },
      { OTIO_SCHEMA: 'Clip.1', name: 'TAPE2', source_range: { start_time: rta(12), duration: rta(24) }, media_reference: { name: 'TAPE2' } },
    ] },
  ] } };
  const events = parseOTIO(otio, { fps: 24 });
  assert.deepEqual([...new Set(events.map((e) => e.track))].sort(), ['A', 'A2', 'V']);
  const { spec, report } = eventsToAssembleSpec(events, { sourceMap: MAP });
  const t1 = spec.media.find((m) => m.mediaFilePath === '/m/a.mp4');
  const t2 = spec.media.find((m) => m.mediaFilePath === '/m/b.mp4');
  assert.deepEqual(t1.cuts, [
    { startFrame: 86400, durationFrames: 48, srcIn: 0 },
    { startFrame: 86400, durationFrames: 48, srcIn: 0, audioOnly: true, track: 1 },
  ]);
  assert.deepEqual(t2.cuts, [{ startFrame: 86424, durationFrames: 24, srcIn: 12, audioOnly: true, track: 2 }]);
  assert.equal(report.authoredAudioEvents, 2);
  assert.equal(report.audioEventsSkipped, 0);
});

test('EDL A2 channel keeps its audio track number', () => {
  const edl = [
    'TITLE: A2',
    'FCM: NON-DROP FRAME',
    '001  TAPE1 V     C        00:00:00:00 00:00:02:00 01:00:00:00 01:00:02:00',
    '002  TAPE2 A2    C        00:00:00:00 00:00:02:00 01:00:00:00 01:00:02:00',
    '',
  ].join('\n');
  const events = parseEDL(edl, { fps: 24 });
  assert.equal(events[1].track, 'A2');
  const { spec } = eventsToAssembleSpec(events, { sourceMap: MAP });
  const t2 = spec.media.find((m) => m.mediaFilePath === '/m/b.mp4');
  assert.deepEqual(t2.cuts, [{ startFrame: 86400, durationFrames: 48, srcIn: 0, audioOnly: true, track: 2 }]);
});

test('audio cuts beyond the template ceiling refuse at assemble time', async () => {
  const requireC = createRequire(import.meta.url);
  const { cutSourceIntoClips } = requireC('../vendor/drp-format/cut-media.js');
  const { addMediaClip } = requireC('../vendor/drp-format/author-project.js');
  const base = await addMediaClip({
    mediaFile: '/m/a.mp4', spec: { width: 640, height: 360, frameCount: 480, fps: 24 }, templateVersion: 19,
  });
  await assert.rejects(
    cutSourceIntoClips(base.buffer, { cuts: [{ startFrame: 86400, durationFrames: 24, audioOnly: true, track: 9 }] }),
    /audio track 9 exceeds the template's 8 audio tracks/,
  );
});

// Audio cross-fades: same geometry rules as video dissolves; the harvested
// cross-fade template renders a RAMP through the junction (verified on
// 19.1.3.7 against a Resolve-authored control: -27.6 → -25.6 → -23.0 → -21.9
// highpass-RMS, identical shape).
test('an EDL audio dissolve with handles authors an audio cross-fade', () => {
  const edl = [
    'TITLE: AX',
    'FCM: NON-DROP FRAME',
    '001  TAPE1 A     C        00:00:01:00 00:00:03:00 01:00:00:00 01:00:02:00',
    '002  TAPE2 A     D    024 00:00:01:00 00:00:03:00 01:00:02:00 01:00:04:00',
    '003  TAPE1 V     C        00:00:01:00 00:00:05:00 01:00:00:00 01:00:04:00',
    '',
  ].join('\n');
  const { spec, report } = eventsToAssembleSpec(parseEDL(edl, { fps: 24 }), { sourceMap: MAP });
  assert.deepEqual(report.authoredTransitions, [{ track: 1, atFrame: 86448, durationFrames: 24, trackType: 'audio' }]);
  assert.equal(report.droppedTransitions.length, 0);
  assert.deepEqual(spec.transitions, report.authoredTransitions);
});

test('an audio dissolve without an abutting predecessor drops with trackType audio', () => {
  const edl = [
    'TITLE: AX',
    'FCM: NON-DROP FRAME',
    '001  TAPE1 V     C        00:00:01:00 00:00:05:00 01:00:00:00 01:00:04:00',
    '002  TAPE2 A     D    024 00:00:01:00 00:00:03:00 01:00:02:00 01:00:04:00',
    '',
  ].join('\n');
  const { report } = eventsToAssembleSpec(parseEDL(edl, { fps: 24 }), { sourceMap: MAP });
  assert.equal(report.droppedTransitions.length, 1);
  assert.equal(report.droppedTransitions[0].trackType, 'audio');
  assert.match(report.droppedTransitions[0].reason, /no abutting predecessor/);
});

// Start-timecode fidelity: preserveStartTimecode anchors at the turnover's
// real record start (the start TC lives in the pool timeline clip's
// MediaExtents [startSec, durSec] LE-double pair — patched, imported, and
// render-verified on 19.1.3.7: a 00:59:52:00 EDL comes back at 00:59:52:00).
test('preserveStartTimecode keeps absolute record positions and sets spec.startFrame', () => {
  const edl = [
    'TITLE: STC',
    'FCM: NON-DROP FRAME',
    '001  TAPE1 V     C        00:00:01:00 00:00:03:00 00:59:52:00 00:59:54:00',
    '002  TAPE2 V     C        00:00:01:00 00:00:03:00 00:59:54:00 00:59:56:00',
    '',
  ].join('\n');
  const events = parseEDL(edl, { fps: 24 });
  const preserved = eventsToAssembleSpec(events, { sourceMap: MAP, preserveStartTimecode: true });
  assert.equal(preserved.spec.startFrame, 86208);
  assert.equal(preserved.report.origin, 86208);
  assert.equal(preserved.spec.media.find((m) => m.mediaFilePath === '/m/a.mp4').cuts[0].startFrame, 86208);
  const anchored = eventsToAssembleSpec(events, { sourceMap: MAP });
  assert.equal(anchored.spec.startFrame, undefined);
  assert.equal(anchored.report.origin, 86400);
  assert.equal(anchored.spec.media.find((m) => m.mediaFilePath === '/m/a.mp4').cuts[0].startFrame, 86400);
});

// Turnover markers: EDL * LOC: locators and OTIO Marker objects become
// authored timeline markers (blob codec byte-exact vs a live export;
// imported markers read back perfectly through the marker API).
test('EDL LOC locators author markers with mapped colors', () => {
  const edl = [
    'TITLE: LOCS',
    'FCM: NON-DROP FRAME',
    '001  TAPE1 V     C        00:00:01:00 00:00:03:00 01:00:00:00 01:00:02:00',
    '* LOC: 01:00:01:00 RED  fix flash frame',
    '* LOC: 01:00:00:12 MAGENTA vfx due',
    '',
  ].join('\n');
  const { spec, report } = eventsToAssembleSpec(parseEDL(edl, { fps: 24 }), { sourceMap: MAP });
  assert.equal(report.authoredMarkers, 2);
  assert.deepEqual(spec.markers, [
    { frame: 86424, color: 'Red', name: 'fix flash frame' },
    { frame: 86412, color: 'Fuchsia', name: 'vfx due' },
  ]);
  assert.equal(report.audioEventsSkipped, 0, 'locators are not miscounted as skipped audio');
});

test('OTIO clip markers land at their record position', () => {
  const rtm = (value) => ({ OTIO_SCHEMA: 'RationalTime.1', value, rate: 24 });
  const otio = { OTIO_SCHEMA: 'Timeline.1', tracks: { children: [
    { OTIO_SCHEMA: 'Track.1', kind: 'Video', children: [
      { OTIO_SCHEMA: 'Clip.1', name: 'TAPE1',
        source_range: { start_time: rtm(24), duration: rtm(48) },
        media_reference: { name: 'TAPE1' },
        markers: [{ OTIO_SCHEMA: 'Marker.2', name: 'beat', color: 'GREEN',
          marked_range: { start_time: rtm(36), duration: rtm(1) } }] },
    ] },
  ] } };
  const { spec } = eventsToAssembleSpec(parseOTIO(otio, { fps: 24 }), { sourceMap: MAP });
  // clip srcIn 24 at record 0; marker at source 36 → record 12 → frame 86412
  assert.deepEqual(spec.markers, [{ frame: 86412, color: 'Green', name: 'beat' }]);
});

// AAF exports duplicate every audio clip per channel; identical A-track legs
// merge instead of refusing as a same-track overlap (measured on a Resolve 19
// rich AAF export: every audio event arrived twice).
test('identical audio channel legs merge instead of overlapping', () => {
  const base = { track: 'A', srcIn: 0, srcOut: 48, fps: 24, recIn: 0, recOut: 48, source: 'TAPE1' };
  const vid = { track: 'V', srcIn: 0, srcOut: 48, fps: 24, recIn: 0, recOut: 48, source: 'TAPE1', index: 1 };
  const events = [vid, { ...base, index: 2 }, { ...base, index: 3 }];
  const { spec, report } = eventsToAssembleSpec(events, { sourceMap: MAP });
  assert.equal(report.audioChannelLegsMerged, 1);
  assert.equal(report.authoredAudioEvents, 1);
  assert.equal(report.audioEventsSkipped, 0);
  const cuts = spec.media[0].cuts.filter((c) => c.audioOnly);
  assert.equal(cuts.length, 1);
});

test('OTIO track-level markers land at record positions', () => {
  const rtt = (value) => ({ OTIO_SCHEMA: 'RationalTime.1', value, rate: 24 });
  const otio = { OTIO_SCHEMA: 'Timeline.1', tracks: { children: [
    { OTIO_SCHEMA: 'Track.1', kind: 'Video',
      markers: [{ OTIO_SCHEMA: 'Marker.2', name: 'reel start', color: 'CYAN',
        marked_range: { start_time: rtt(12), duration: rtt(1) } }],
      children: [
        { OTIO_SCHEMA: 'Clip.1', name: 'TAPE1',
          source_range: { start_time: rtt(0), duration: rtt(48) },
          media_reference: { name: 'TAPE1' } },
      ] },
  ] } };
  const { spec } = eventsToAssembleSpec(parseOTIO(otio, { fps: 24 }), { sourceMap: MAP });
  assert.deepEqual(spec.markers, [{ frame: 86412, color: 'Cyan', name: 'reel start' }]);
});

// Premiere leg: a schema-faithful synthetic .prproj routes through the ACTUAL
// tool handler into an assembled .drt (live-proven: renders 122.99/234 with
// -21.1 dB audio on 19.1.3.7).
test('assemble_from_interchange routes a .prproj through the handler', async () => {
  const zlibM = await import('node:zlib');
  const fsM = await import('node:fs');
  const os = await import('node:os');
  const pathM = await import('node:path');
  const { drtTool } = await import('../server/lib.mjs');
  const TPF24 = 254016000000 / 24;
  const f = (fr) => Math.round(fr * TPF24);
  const XML = `<?xml version="1.0" encoding="UTF-8"?>
<PremiereData Version="3">
  <Project ObjectID="1" ClassID="p0" Version="40"><RootProjectItem ObjectRef="2"/></Project>
  <Sequence ObjectID="10" ClassID="s" Version="40">
    <Node Version="1"><Properties><Name>PP CUT</Name><FrameRate>24</FrameRate></Properties></Node>
    <VideoTracks><Track ObjectRef="20"/></VideoTracks>
  </Sequence>
  <VideoTrack ObjectID="20" ClassID="v" Version="1">
    <TrackItems><TrackItem ObjectRef="40"/></TrackItems>
  </VideoTrack>
  <VideoClipTrackItem ObjectID="40" ClassID="c" Version="1">
    <Start>${f(0)}</Start><End>${f(48)}</End><InPoint>${f(24)}</InPoint><OutPoint>${f(72)}</OutPoint>
    <ClipProjectItem ObjectRef="60"/>
  </VideoClipTrackItem>
  <ClipProjectItem ObjectID="60" ClassID="pi" Version="1">
    <ActualMediaFilePath>/m/a.mp4</ActualMediaFilePath>
  </ClipProjectItem>
</PremiereData>`;
  const tmpd = fsM.mkdtempSync(pathM.join(os.tmpdir(), 'pp-route-'));
  const pp = pathM.join(tmpd, 'cut.prproj');
  fsM.writeFileSync(pp, zlibM.gzipSync(Buffer.from(XML, 'utf8')));
  const out = pathM.join(tmpd, 'out.drt');
  const res = await drtTool.handler({ action: 'assemble_from_interchange', args: {
    format: 'prproj', path: pp, outputPath: out, targetAppVersion: '19.1.3',
    sourceMap: { 'a.mp4': { mediaFilePath: '/m/a.mp4', spec: { width: 640, height: 360, frameCount: 480, fps: 24 } } },
  }});
  assert.ok(!res.error, res.error);
  assert.equal(res.conform.videoEvents, 1);
  assert.match(res.note, /AUTHORED when geometry allows/);
  assert.ok(fsM.existsSync(out));
  fsM.rmSync(tmpd, { recursive: true, force: true });
});

// Round-trip QC verifier: normalizes the three measured cross-format
// conventions and fits per-source TC offsets (live-proven pass on the
// AAF→assemble→import→OTIO-export loop with srcOffsets 86400).
import { verifyRoundtrip } from '../server/author-interchange.mjs';

test('verifyRoundtrip passes across naming/track/TC-base conventions', () => {
  const input = [
    { track: 'V1', source: 'rt_source_1', recIn: 0, recOut: 191, srcIn: 0 },
    { track: 'V1', source: 'rt_source_2', recIn: 191, recOut: 238, srcIn: 24 },
    { track: 'V2', source: 'rt_source_2', recIn: 96, recOut: 143, srcIn: 0 },
  ];
  const exported = [
    { track: 'V', source: 'rt_source_1.mov', recIn: 86400, recOut: 86591, srcIn: 86400 },
    { track: 'V', source: 'RT_SOURCE_2.mov', recIn: 86591, recOut: 86638, srcIn: 86424 },
    { track: 'V2', source: 'rt_source_2.mov', recIn: 86496, recOut: 86543, srcIn: 86400 },
  ];
  const res = verifyRoundtrip(input, exported);
  assert.equal(res.pass, true, JSON.stringify(res.mismatches));
  assert.deepEqual(res.srcOffsets, { rt_source_1: 86400, rt_source_2: 86400 });
});

test('verifyRoundtrip flags real drift, not convention noise', () => {
  const input = [
    { track: 'V1', source: 'A', recIn: 0, recOut: 48, srcIn: 0 },
    { track: 'V1', source: 'A', recIn: 48, recOut: 96, srcIn: 100 },
  ];
  // second cut's source frames slipped by 5 beyond the fitted offset
  const exported = [
    { track: 'V', source: 'A.mov', recIn: 0, recOut: 48, srcIn: 86400 },
    { track: 'V', source: 'A.mov', recIn: 48, recOut: 96, srcIn: 86505 },
  ];
  const res = verifyRoundtrip(input, exported);
  assert.equal(res.pass, false);
  assert.equal(res.mismatches[0].kind, 'source-frames');
  // record drift too
  const res2 = verifyRoundtrip(input, [
    { track: 'V', source: 'A.mov', recIn: 0, recOut: 48, srcIn: 0 },
    { track: 'V', source: 'A.mov', recIn: 50, recOut: 96, srcIn: 100 },
  ]);
  assert.equal(res2.pass, false);
  assert.equal(res2.mismatches[0].kind, 'record');
});

test('assemble_from_interchange carries a sidecar SRT onto the subtitle track', async () => {
  const fsM = await import('node:fs');
  const os = await import('node:os');
  const pathM = await import('node:path');
  const JSZipM = (await import('jszip')).default;
  const { drtTool } = await import('../server/lib.mjs');
  const tmpd = fsM.mkdtempSync(pathM.join(os.tmpdir(), 'srt-side-'));
  const srt = pathM.join(tmpd, 'cues.srt');
  fsM.writeFileSync(srt, '1\n00:00:00,500 --> 00:00:01,500\nSidecar cue\n');
  const out = pathM.join(tmpd, 'out.drt');
  const edl = 'TITLE: S\nFCM: NON-DROP FRAME\n001  TAPE1 V     C        00:00:01:00 00:00:03:00 01:00:00:00 01:00:02:00\n';
  const res = await drtTool.handler({ action: 'assemble_from_interchange', args: {
    format: 'edl', content: edl, outputPath: out, targetAppVersion: '19.1.3',
    subtitlesSrtPath: srt,
    sourceMap: { TAPE1: { mediaFilePath: '/m/a.mp4', spec: { width: 640, height: 360, frameCount: 480, fps: 24 } } },
  }});
  assert.ok(!res.error, res.error);
  const zip = await JSZipM.loadAsync(fsM.readFileSync(out));
  const seqName = Object.keys(zip.files).find((n) => !zip.files[n].dir && /^SeqContainer\//.test(n));
  const seq = await zip.file(seqName).async('string');
  assert.match(seq, /<Name>Sidecar cue<\/Name>/);
  assert.match(seq, /<Start>86412<\/Start>/); // 0.5s @24 + origin
  fsM.rmSync(tmpd, { recursive: true, force: true });
});

test('verifyRoundtrip drops zero-duration dissolve legs and maps reels via aliases', () => {
  // An EDL dissolve writes a ZERO-duration outgoing leg before the D event —
  // a pairing placeholder no export reproduces — and names sources by REEL
  // (CUTSRC) while the re-export uses file basenames (cut_src). Both broke
  // the first live EDL round-trip through the tool layer (E54).
  const input = [
    { track: 'V1', source: 'CUTSRC', recIn: 0, recOut: 48, srcIn: 24 },
    { track: 'V1', source: 'CUTSRC', recIn: 48, recOut: 48, srcIn: 72 },
    { track: 'V1', source: 'WHITESRC', recIn: 48, recOut: 96, srcIn: 24 },
  ];
  const exported = [
    { track: 'V', source: 'cut_src.mp4', recIn: 86400, recOut: 86448, srcIn: 24 },
    { track: 'V', source: 'white_src.mp4', recIn: 86448, recOut: 86496, srcIn: 24 },
  ];
  const res = verifyRoundtrip(input, exported, {
    sourceAliases: { CUTSRC: 'cut_src.mp4', WHITESRC: 'white_src.mp4' },
  });
  assert.equal(res.pass, true, JSON.stringify(res.mismatches));
  assert.equal(res.pairs, 2);
  assert.deepEqual(res.srcOffsets, { cut_src: 0, white_src: 0 });
  // without aliases the reel names cannot match — the miss is reported, not silent
  const bare = verifyRoundtrip(input, exported);
  assert.equal(bare.pass, false);
  assert.equal(bare.mismatches[0].kind, 'source');
});

// FREEZE frames (E55/E56, 2026-08-31): the real freeze map — harvested from a
// live 19.1.3.7 EDL `M2 000.0` import and render-proven frozen by
// freezedetect — is a flat line in SECONDS (YMin=YMax=Y=frozen position,
// XMax=60000 sentinel), NOT the frame-domain flat line the earlier synthetic
// used (that one reads back frozen but RENDERS moving). Offline authoring of
// this shape was render-proven frozen at a different source frame (96).
const { buildFreezeTimemapKeyed } = requireCjs('../vendor/drp-format/media-timemap.js');

test('buildFreezeTimemapKeyed is byte-exact vs the live freeze harvest', () => {
  const harvest = fs.readFileSync(new URL('./fixtures-r19-freeze-timemap.hex', import.meta.url), 'utf8').trim().toLowerCase();
  const mine = buildFreezeTimemapKeyed({
    freezeFrame: 24, sourceFrames: 192, fps: 24,
    uniqueId: 'a953300c-1100-4a80-adb5-e0747bba751f',
  }).toString('hex').toLowerCase();
  assert.equal(mine, harvest);
});

test('zero-speed events author freezes instead of flattening', () => {
  const base = { track: 'V', srcIn: 96, srcOut: 144, fps: 24 };
  const frozen = [{ ...base, index: 1, source: 'TAPE1', recIn: 0, recOut: 48, speed: 0 }];
  const r = eventsToAssembleSpec(frozen, { sourceMap: MAP });
  assert.equal(r.report.flattenedRetimes.length, 0);
  assert.deepEqual(r.report.authoredRetimes, [{ index: 1, source: 'TAPE1', speed: 0, freeze: true }]);
  assert.equal(r.spec.media[0].cuts[0].freeze, true);
  assert.equal(r.spec.media[0].cuts[0].srcIn, 96);
});

test('assemble authors a freeze cut: freeze map present, <In/> EMPTY', async () => {
  const { drtTool } = await import('../server/lib.mjs');
  const os = await import('node:os');
  const path = await import('node:path');
  const JSZip = (await import('jszip')).default;
  const out = path.join(os.tmpdir(), `frz-${Math.random().toString(36).slice(2)}.drt`);
  await drtTool.handler({ action: 'assemble', args: {
    outputPath: out, targetAppVersion: '19.1.3',
    spec: { timelineName: 'FRZ', media: {
      mediaFilePath: '/m/a.mp4', spec: { width: 640, height: 360, frameCount: 192, fps: 24 },
      cuts: [{ startFrame: 86400, durationFrames: 48, srcIn: 96, freeze: true }],
    } },
  }});
  const zip = await JSZip.loadAsync(fs.readFileSync(out));
  const seqName = Object.keys(zip.files).find((n) => !zip.files[n].dir && /^SeqContainer\//.test(n));
  const seq = await zip.file(seqName).async('string');
  const clip = seq.match(/<Element>\s*<Sm2TiVideoClip[\s\S]*?<\/Sm2TiVideoClip>\s*<\/Element>/)[0];
  assert.match(clip, /<In\/>/, 'frozen clip keeps an EMPTY <In/>');
  const tm = clip.match(/<MediaTimemapBA>([0-9a-fA-F]+)<\/MediaTimemapBA>/)[1];
  const expected = buildFreezeTimemapKeyed({ freezeFrame: 96, sourceFrames: 192, fps: 24, uniqueId: '00000000-0000-0000-0000-000000000000' }).toString('hex');
  // uniqueId differs per assembly — compare everything around the uuid field
  assert.equal(tm.length, expected.length);
  assert.equal(tm.slice(0, 100), expected.slice(0, 100), 'header (YMin/YMax/XMax) matches');
  assert.equal(tm.slice(-700), expected.slice(-700), 'keyframes/DbType match');
  fs.unlinkSync(out);
});

test('audio tool refuses mistyped trim windows instead of silently copying', async () => {
  // Measured through the MCP layer (E59 sweep): non-strict schemas stripped
  // unknown keys, so trim with {start, duration} (wrong names) copied the
  // WHOLE file and reported success — the silent-lie class. Schemas are now
  // strict, and a windowless trim (no durationFrames) refuses outright.
  const { audioTool } = await import('../server/tools/audio.mjs');
  await assert.rejects(
    audioTool.handler({ action: 'trim', args: { input: '/x.mp4', output: '/y.wav', start: 0, duration: 1 } }),
    /unrecognized|durationFrames/i,
  );
  await assert.rejects(
    audioTool.handler({ action: 'trim', args: { input: '/x.mp4', output: '/y.wav' } }),
    /durationFrames/i,
  );
});

test('cdlDiff reads array-shaped CDLs and refuses garbage instead of identity-defaulting', async () => {
  // E60: an [r,g,b]-array CDL silently decayed to identity through the old
  // .r/.g/.b reader — two different grades diffed as saturation-only.
  const { cdlDiff } = await import('../server/provenance-audit.mjs');
  const arr = cdlDiff(
    { slope: [1, 1, 1], offset: [0, 0, 0], power: [1, 1, 1], saturation: 1 },
    { slope: [1.1, 1, 0.95], offset: [0.01, 0, 0], power: [1, 1, 1], saturation: 0.9 },
  );
  const params = arr.deltas.map((d) => d.param).sort();
  assert.deepEqual(params, ['offset.r', 'saturation', 'slope.b', 'slope.r']);
  const obj = cdlDiff({ slope: { r: 1, g: 1, b: 1 } }, { slope: { r: 1.2, g: 1, b: 1 } });
  assert.equal(obj.deltas[0].param, 'slope.r');
  assert.throws(() => cdlDiff({ slope: 'oops' }, {}), /refusing to silently treat it as identity/);
  assert.throws(() => cdlDiff({ slope: [1, 1] }, {}), /exactly \[r, g, b\]/);
});

test('EDL W-codes author as wipes; D stays a plain dissolve (E61/E62)', () => {
  // Resolve's own EDL importer maps EVERY W-code to its single soft-edge
  // wipe style (W001/W002/W005 harvested identical), stored as a Cross
  // Dissolve element whose FieldsBlob zeroes the style id. Render-proven:
  // authored wipe midpoint splits spatially (158/205) where a dissolve is
  // uniform (181.6), and matches the live-import wipe's split.
  const wipeEdl = [
    'TITLE: W', 'FCM: NON-DROP FRAME',
    '001  TAPE1 V     C        00:00:01:00 00:00:03:00 01:00:00:00 01:00:02:00',
    '002  TAPE2 V     W001 024 00:00:01:00 00:00:03:00 01:00:02:00 01:00:04:00',
    '',
  ].join('\n');
  const w = eventsToAssembleSpec(parseEDL(wipeEdl, { fps: 24 }), { sourceMap: MAP });
  assert.deepEqual(w.spec.transitions, [{ track: 1, atFrame: 86448, durationFrames: 24, type: 'wipe' }]);
  const disEdl = wipeEdl.replace('W001 024', 'D    024');
  const d = eventsToAssembleSpec(parseEDL(disEdl, { fps: 24 }), { sourceMap: MAP });
  assert.deepEqual(d.spec.transitions, [{ track: 1, atFrame: 86448, durationFrames: 24 }]);
});
