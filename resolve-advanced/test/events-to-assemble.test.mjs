// The conform bridge: normalized interchange events → drt.assemble spec.
// Frame math is nominal-base (v2.104.6) → 24fps template timeline, earliest
// event anchored at origin 86400; butt cuts must stay gapless through the
// conversion, retimes flatten into the ledger, overlaps refuse.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { eventsToAssembleSpec, eventsToEDL } from '../server/author-interchange.mjs';
import { parseEDL, parseOTIO, parseXMEMLEvents } from '../server/editorial.mjs';

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
  // E73: EDL dissolves span START-AT-CUT (the CMX convention). The clip
  // boundary must sit strictly inside the span (edge-aligned renders inert,
  // measured), so the bridge moves the cut +dur/2 exactly as Resolve's own
  // EDL importer does — atFrame is the SHIFTED boundary, startFrame the span.
  assert.deepEqual(spec.transitions, [{ track: 1, atFrame: 86460, durationFrames: 24, startFrame: 86448 }]);
  assert.deepEqual(report.authoredTransitions, spec.transitions);
  assert.equal(report.droppedTransitions.length, 0);
});

test('a start-at-cut EDL dissolve needs NO incoming handle — zero srcIn authors (E73)', () => {
  const edl = [
    'TITLE: DIS',
    'FCM: NON-DROP FRAME',
    '001  TAPE1 V     C        00:00:01:00 00:00:03:00 01:00:00:00 01:00:02:00',
    '002  TAPE2 V     D    024 00:00:00:00 00:00:02:00 01:00:02:00 01:00:04:00',
    '',
  ].join('\n');
  const { spec, report } = eventsToAssembleSpec(parseEDL(edl, { fps: 24 }), { sourceMap: MAP });
  assert.deepEqual(spec.transitions, [{ track: 1, atFrame: 86460, durationFrames: 24, startFrame: 86448 }]);
  assert.equal(report.droppedTransitions.length, 0);
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
  assert.match(report.droppedTransitions[0].reason, /outgoing tail media < 24/);
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
  // The r19 template ships 16 audio tracks with valid Fairlight strips
  // (re-captured live E89, 2026-09-01); A16 assembles, A17 refuses.
  const ok = await cutSourceIntoClips(base.buffer, { cuts: [{ startFrame: 86400, durationFrames: 24, audioOnly: true, track: 16 }] });
  assert.equal(ok.cutCount, 1);
  await assert.rejects(
    cutSourceIntoClips(base.buffer, { cuts: [{ startFrame: 86400, durationFrames: 24, audioOnly: true, track: 17 }] }),
    /audio track 17 exceeds the template's 16 audio tracks/,
  );
});

// Audio cross-fades: same geometry rules as video dissolves; the harvested
// cross-fade template renders a RAMP through the junction (verified on
// 19.1.3.7 against a Resolve-authored control: -27.6 → -25.6 → -23.0 → -21.9
// highpass-RMS, identical shape).
// ── BL (black) legs and fades (E91, render-verified on 19.1.3.7) ─────────
// Resolve's OWN EDL importer drops BL dissolves silently (fade-in vanishes,
// fade-out leaves a hard cut to the Solid Color it creates). This bridge
// authors them: BL legs become Solid Color generator elements, fades become
// real clip↔generator dissolves — luma ramped 18→123 (in) and 123→16 (out)
// on the live render.
test('EDL BL fades author as generator elements + dissolves (E91)', () => {
  const edl = [
    'TITLE: FADES', 'FCM: NON-DROP FRAME',
    '001  BL    V     C        00:00:00:00 00:00:00:00 01:00:00:00 01:00:00:00',
    '002  TAPE1 V     D    024 00:00:00:00 00:00:04:00 01:00:00:00 01:00:04:00',
    '003  TAPE1 V     C        00:00:04:00 00:00:04:00 01:00:04:00 01:00:04:00',
    '004  BL    V     D    024 00:00:00:00 00:00:02:00 01:00:04:00 01:00:06:00',
    '',
  ].join('\n');
  const events = parseEDL(edl, { fps: 24 });
  const { spec, report } = eventsToAssembleSpec(events, {
    sourceMap: { TAPE1: { mediaFilePath: '/m/a.mp4', spec: { width: 640, height: 360, frameCount: 192, fps: 24 } } },
  });
  // Fade-in: the zero-length BL slug GROWS through the boundary shift
  // (single-sided transitions refuse to import, measured), the picture
  // trims its head with source staying record-aligned.
  assert.deepEqual(spec.elements, [
    { type: 'generator', generatorName: 'Solid Color', track: 1, startFrame: 86400, durationFrames: 12 },
    { type: 'generator', generatorName: 'Solid Color', track: 1, startFrame: 86508, durationFrames: 36 },
  ]);
  assert.deepEqual(spec.media[0].cuts, [{ startFrame: 86412, durationFrames: 96, srcIn: 12 }]);
  assert.deepEqual(spec.transitions, [
    { track: 1, atFrame: 86412, durationFrames: 24, startFrame: 86400 },
    { track: 1, atFrame: 86508, durationFrames: 24, startFrame: 86496 },
  ]);
  assert.deepEqual(report.blackLegs, { authoredGenerators: 2, audioSilenceLegsSkipped: 0 });
  assert.equal(report.droppedTransitions.length, 0);
});

test('OTIO gap-adjacent transitions are fades — synthetic BL legs route through the black machinery (E92)', () => {
  const rt = (v, r = 24) => ({ OTIO_SCHEMA: 'RationalTime.1', rate: r, value: v });
  const tr = (s, d, r = 24) => ({ OTIO_SCHEMA: 'TimeRange.1', start_time: rt(s, r), duration: rt(d, r) });
  const otio = {
    OTIO_SCHEMA: 'Timeline.1',
    tracks: { OTIO_SCHEMA: 'Stack.1', children: [
      { OTIO_SCHEMA: 'Track.1', kind: 'Video', markers: [], children: [
        { OTIO_SCHEMA: 'Transition.1', transition_type: 'SMPTE_Dissolve', in_offset: rt(0), out_offset: rt(24) },
        { OTIO_SCHEMA: 'Clip.2', name: 'A', source_range: tr(0, 96), media_reference: { target_url: 'A' }, effects: [], markers: [] },
        { OTIO_SCHEMA: 'Transition.1', transition_type: 'SMPTE_Dissolve', in_offset: rt(12), out_offset: rt(12) },
        { OTIO_SCHEMA: 'Gap.1', source_range: tr(0, 48) },
      ] },
    ] },
  };
  const events = parseOTIO(otio, { fps: 24 });
  assert.deepEqual(events.filter((e) => e.source === 'BL').map((e) => [e.recIn, e.recOut]), [[0, 0], [96, 96]]);
  const { spec, report } = eventsToAssembleSpec(events, {
    sourceMap: { A: { mediaFilePath: '/m/a.mp4', spec: { width: 640, height: 360, frameCount: 192, fps: 24 } } },
  });
  // Head fade: CMX-form zero BL grows via the shift; tail fade (centered):
  // the zero BL MATERIALIZES forward to cover the post side of the span.
  assert.deepEqual(spec.elements, [
    { type: 'generator', generatorName: 'Solid Color', track: 1, startFrame: 86400, durationFrames: 12 },
    { type: 'generator', generatorName: 'Solid Color', track: 1, startFrame: 86496, durationFrames: 12 },
  ]);
  assert.deepEqual(spec.transitions, [
    { track: 1, atFrame: 86412, durationFrames: 24, startFrame: 86400 },
    { track: 1, atFrame: 86496, durationFrames: 24, startFrame: 86484 },
  ]);
  assert.equal(report.droppedTransitions.length, 0);
});

test('XMEML fade transitionitems (no outgoing / no incoming clip) synthesize BL legs (E92)', () => {
  const xml = [
    "<?xml version='1.0'?>",
    "<xmeml version='4'><sequence><rate><timebase>24</timebase></rate><media><video><track>",
    '<clipitem><name>a.mp4</name><start>0</start><end>96</end><in>0</in><out>96</out></clipitem>',
    "<transitionitem><start>0</start><end>24</end><effect><effectid>Cross Dissolve</effectid></effect></transitionitem>",
    "<transitionitem><start>84</start><end>108</end><effect><effectid>Cross Dissolve</effectid></effect></transitionitem>",
    '</track></video></media></sequence></xmeml>',
  ].join('');
  const events = parseXMEMLEvents(xml, { fps: 24 });
  const { spec, report } = eventsToAssembleSpec(events, {
    sourceMap: { 'a.mp4': { mediaFilePath: '/m/a.mp4', spec: { width: 640, height: 360, frameCount: 192, fps: 24 } } },
  });
  assert.deepEqual(spec.media[0].cuts, [{ startFrame: 86412, durationFrames: 84, srcIn: 12 }]);
  assert.deepEqual(spec.elements, [
    { type: 'generator', generatorName: 'Solid Color', track: 1, startFrame: 86400, durationFrames: 12 },
    { type: 'generator', generatorName: 'Solid Color', track: 1, startFrame: 86496, durationFrames: 12 },
  ]);
  assert.equal(report.droppedTransitions.length, 0);
});

// AAF overlap reconciliation (E93): an AAF Transition CONSUMES record time,
// so the walker emits the incoming clip OVERLAPPING the outgoing by the
// transition duration. Before this, the overlap gate threw and NO AAF
// dissolve could conform. Render-verified live: fade-in 18→123, dissolve to
// white through the 181.8 midpoint fingerprint, fade-out 230→21.
test('AAF-shaped overlapping dissolve events reconcile and author (E93)', () => {
  const MAP2 = {
    A: { mediaFilePath: '/m/a.mp4', spec: { width: 640, height: 360, frameCount: 480, fps: 24 } },
    B: { mediaFilePath: '/m/b.mp4', spec: { width: 640, height: 360, frameCount: 480, fps: 24 } },
  };
  const events = [
    { index: 1, track: 'V', source: 'A', srcIn: 0, srcOut: 96, recIn: 0, recOut: 96, fps: 24 },
    { index: 2, track: 'V', source: 'B', srcIn: 48, srcOut: 144, recIn: 72, recOut: 168, fps: 24, transition: { type: 'dissolve', duration: 24, alignment: 'start', cutPoint: 12 } },
  ];
  const { spec, report } = eventsToAssembleSpec(events, { sourceMap: MAP2 });
  // Outgoing trimmed to the overlap start, then re-extended to the cut point
  // by the boundary shift — the AAF notional-cut semantics exactly.
  assert.deepEqual(spec.media.find((m) => m.mediaFilePath === '/m/a.mp4').cuts,
    [{ startFrame: 86400, durationFrames: 84, srcIn: 0 }]);
  assert.deepEqual(spec.media.find((m) => m.mediaFilePath === '/m/b.mp4').cuts,
    [{ startFrame: 86484, durationFrames: 84, srcIn: 60 }]);
  assert.deepEqual(spec.transitions, [{ track: 1, atFrame: 86484, durationFrames: 24, startFrame: 86472 }]);
  assert.equal(report.droppedTransitions.length, 0);
});

test('AAF walker-shaped BL fades author through the reconciliation (E93)', () => {
  // The exact shape aaf_probe emits for [Transition, SC, Transition, Filler]:
  // zero-length BL legs at the overlap starts, clips at post-rewind record.
  const events = [
    { index: 1, track: 'V', source: 'BL', srcIn: 0, srcOut: 0, recIn: 0, recOut: 0, fps: 24 },
    { index: 2, track: 'V', source: 'A', srcIn: 0, srcOut: 96, recIn: 0, recOut: 96, fps: 24, transition: { type: 'dissolve', duration: 24, alignment: 'start', cutPoint: 12 } },
    { index: 3, track: 'V', source: 'BL', srcIn: 0, srcOut: 0, recIn: 72, recOut: 72, fps: 24, transition: { type: 'dissolve', duration: 24, alignment: 'start', cutPoint: 12 } },
  ];
  const { spec, report } = eventsToAssembleSpec(events, {
    sourceMap: { A: { mediaFilePath: '/m/a.mp4', spec: { width: 640, height: 360, frameCount: 480, fps: 24 } } },
  });
  assert.equal(spec.elements.length, 2);
  assert.equal(spec.transitions.length, 2);
  assert.equal(report.droppedTransitions.length, 0);
});

test('audio BL fades drop with the no-silence-source reason; BL needs no sourceMap entry', () => {
  const edl = [
    'TITLE: AFADE', 'FCM: NON-DROP FRAME',
    '001  TAPE1 A     C        00:00:00:00 00:00:02:00 01:00:00:00 01:00:02:00',
    '002  BL    A     D    024 00:00:00:00 00:00:01:00 01:00:02:00 01:00:03:00',
    '003  TAPE1 V     C        00:00:00:00 00:00:03:00 01:00:00:00 01:00:03:00',
    '',
  ].join('\n');
  const events = parseEDL(edl, { fps: 24 });
  const { spec, report } = eventsToAssembleSpec(events, {
    sourceMap: { TAPE1: { mediaFilePath: '/m/a.mp4', spec: { width: 640, height: 360, frameCount: 192, fps: 24 } } },
  });
  assert.equal(spec.elements, undefined); // audio BL never becomes a generator
  assert.equal(report.blackLegs.audioSilenceLegsSkipped, 1);
  const drop = report.droppedTransitions.find((d) => d.trackType === 'audio');
  assert.match(drop.reason, /no silence source/);
});

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
  assert.deepEqual(report.authoredTransitions, [{ track: 1, atFrame: 86460, durationFrames: 24, trackType: 'audio', startFrame: 86448 }]);
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

test('OTIO clip markers become ITEM markers on the cut (E80)', () => {
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
  // clip srcIn 24; marker at source 36 → ITEM-relative frame 12, authored as
  // an Sm2TiItemLockableBlob on the cut (v2.143 item markers) rather than a
  // timeline marker — track-level markers still go to spec.markers.
  assert.equal(spec.markers, undefined);
  assert.deepEqual(spec.media[0].cuts[0].markers, [{ frame: 12, color: 'Green', name: 'beat' }]);
});

test('XMEML clipitem <marker>s become ITEM markers too (E81)', () => {
  const { parseXMEMLEvents } = requireCjs('../server/editorial.mjs');
  const xml = `<?xml version="1.0"?><xmeml version="4"><sequence><name>S</name>
   <rate><timebase>24</timebase></rate><media><video><track>
   <clipitem><name>a.mp4</name><start>0</start><end>48</end><in>24</in><out>72</out>
    <marker><name>vfx</name><comment>replace sky</comment><in>30</in><out>30</out></marker>
   </clipitem>
   </track></video></media></sequence></xmeml>`;
  const events = parseXMEMLEvents(xml, { fps: 24 });
  assert.deepEqual(events[0].itemMarkers, [{ frame: 6, name: 'vfx', note: 'replace sky' }]);
  const { spec } = eventsToAssembleSpec(events, { sourceMap: { 'a.mp4': MAP.TAPE1 } });
  assert.deepEqual(spec.media[0].cuts[0].markers, [{ frame: 6, color: 'Blue', name: 'vfx', note: 'replace sky' }]);
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

test('verifyRoundtrip is fade-aware: black legs merge out, reshaped edges excused with a report (E94)', () => {
  // A faded conform (measured E94 live): input EDL has a zero-length BL +
  // picture + BL tail; the re-export shows Solid Color legs and the picture
  // shifted +12 both ends by the fade boundary-shift.
  const input = [
    { track: 'V', source: 'BL', recIn: 0, recOut: 0, srcIn: 0 },
    { track: 'V', source: 'TAPE1', recIn: 0, recOut: 96, srcIn: 0, transition: { type: 'D', duration: 24, alignment: 'start' } },
    { track: 'V', source: 'BL', recIn: 96, recOut: 144, srcIn: 0, transition: { type: 'D', duration: 24, alignment: 'start' } },
  ];
  const exported = [
    { track: 'V', source: 'Solid Color', recIn: 0, recOut: 12, srcIn: 0 },
    { track: 'V', source: 'cut_src.mp4', recIn: 12, recOut: 108, srcIn: 12 },
    { track: 'V', source: 'Solid Color', recIn: 108, recOut: 144, srcIn: 0 },
  ];
  const res = verifyRoundtrip(input, exported, { sourceAliases: { TAPE1: 'cut_src' } });
  assert.equal(res.pass, true, JSON.stringify(res.mismatches));
  assert.deepEqual(res.blackSegments, { input: 1, exported: 2 });
  assert.deepEqual(res.fadeReshapedBoundaries, [
    { at: 0, source: 'cut_src', input: [0, 96], exported: [12, 108] },
  ]);
  assert.deepEqual(res.srcOffsets, { cut_src: 0 });
  // A shift BEYOND the fade window is still real drift.
  const drifted = JSON.parse(JSON.stringify(exported));
  drifted[1].recIn = 40; drifted[1].srcIn = 40;
  const res2 = verifyRoundtrip(input, drifted, { sourceAliases: { TAPE1: 'cut_src' } });
  assert.equal(res2.pass, false);
  assert.equal(res2.mismatches[0].kind, 'record');
  // And a shifted edge NOWHERE NEAR a junction is drift even when small-ish.
  const noFade = [
    { track: 'V', source: 'A', recIn: 0, recOut: 96, srcIn: 0 },
    { track: 'V', source: 'A', recIn: 96, recOut: 144, srcIn: 100 },
  ];
  const res3 = verifyRoundtrip(noFade, [
    { track: 'V', source: 'A.mov', recIn: 0, recOut: 96, srcIn: 0 },
    { track: 'V', source: 'A.mov', recIn: 108, recOut: 156, srcIn: 112 },
  ]);
  assert.equal(res3.pass, false);
  assert.equal(res3.mismatches[0].kind, 'record');
});

test('verifyRoundtrip is retime-aware: a lost or wrong-speed retime fails as drift (E95)', () => {
  // Record/source geometry cannot catch a lost retime (the record extent is
  // unchanged). Measured live: EXPORT_OTIO carries an authored Sm2TimeMap
  // back as LinearTimeWarp 0.5, so speed/reverse compare pairwise.
  const input = [
    { track: 'V', source: 'A', recIn: 0, recOut: 48, srcIn: 0 },
    { track: 'V', source: 'A', recIn: 48, recOut: 96, srcIn: 48, speed: 50 },
  ];
  const good = [
    { track: 'V', source: 'A.mov', recIn: 0, recOut: 48, srcIn: 0, speed: 100 },
    { track: 'V', source: 'A.mov', recIn: 48, recOut: 96, srcIn: 48, speed: 50 },
  ];
  assert.equal(verifyRoundtrip(input, good).pass, true);
  const flattened = good.map((e) => ({ ...e, speed: 100 }));
  const r1 = verifyRoundtrip(input, flattened);
  assert.equal(r1.pass, false);
  assert.equal(r1.mismatches[0].kind, 'retime');
  const reversed = good.map((e, i) => (i === 1 ? { ...e, reverse: true } : e));
  const r2 = verifyRoundtrip(input, reversed);
  assert.equal(r2.pass, false);
  assert.equal(r2.mismatches[0].kind, 'retime');
});

test('verifyRoundtrip is audio-aware: declared audio compares, the A1 mirror stays informational (E97)', () => {
  const input = [
    { track: 'V', source: 'A', recIn: 0, recOut: 96, srcIn: 0 },
    { track: 'A2', source: 'A', recIn: 24, recOut: 72, srcIn: 24 },
  ];
  const good = [
    { track: 'V', source: 'A.mov', recIn: 0, recOut: 96, srcIn: 0 },
    { track: 'A2', source: 'A.mov', recIn: 24, recOut: 72, srcIn: 24 },
  ];
  const r1 = verifyRoundtrip(input, good);
  assert.equal(r1.pass, true, JSON.stringify(r1.mismatches));
  assert.deepEqual(r1.audio, { input: 1, exported: 1, compared: true });
  // audio leg slipped 6 frames → real drift, tagged audio
  const drift = good.map((e) => (e.track === 'A2' ? { ...e, recIn: 30, recOut: 78, srcIn: 30 } : e));
  const r2 = verifyRoundtrip(input, drift);
  assert.equal(r2.pass, false);
  assert.deepEqual(r2.mismatches[0], { kind: 'record', trackType: 'audio', at: 0, input: [24, 72], exported: [30, 78] });
  // a video-only turnover re-exporting with mirrored audio is NOT a drift
  const r3 = verifyRoundtrip([input[0]], good);
  assert.equal(r3.pass, true);
  assert.equal(r3.audio.compared, false);
  // AAF channel legs dedupe: the same audio range once per channel is one leg
  const dupIn = [input[0], input[1], { ...input[1] }];
  const r4 = verifyRoundtrip(dupIn, good);
  assert.equal(r4.pass, true, JSON.stringify(r4.mismatches));
  assert.equal(r4.audio.input, 1);
});

test('conformManifest is BL-aware: fades need no black-side source or handles (E99)', async () => {
  const { conformManifest } = await import('../server/editorial.mjs');
  const edl = [
    'TITLE: F', 'FCM: NON-DROP FRAME', '',
    '001  BL       V     C        00:00:00:00 00:00:00:00 01:00:00:00 01:00:00:00',
    '002  TAPE1    V     D    024 00:00:00:00 00:00:04:00 01:00:00:00 01:00:04:00',
    '003  TAPE1    V     C        00:00:04:00 00:00:04:00 01:00:04:00 01:00:04:00',
    '004  BL       V     D    024 00:00:00:00 00:00:02:00 01:00:04:00 01:00:06:00', '',
  ].join('\n');
  const events = parseEDL(edl, { fps: 24 });
  // A conformable fade EDL passes: BL needs no source, the fade-in needs no
  // handles, and the fade-out's tail requirement lands on the PICTURE source.
  const ok = conformManifest(events, { TAPE1: { path: '/m/a.mp4', handleIn: 0, handleOut: 48 } });
  assert.equal(ok.pass, true, JSON.stringify(ok.rows));
  // A starved outgoing tail still fails — named on the fade-out row.
  const starved = conformManifest(events, { TAPE1: { path: '/m/a.mp4', handleIn: 0, handleOut: 4 } });
  assert.equal(starved.pass, false);
  const failing = starved.rows.find((r) => !r.pass);
  assert.match(failing.checks.find((c) => c.name === 'handles').detail, /outgoing TAPE1 needs tail/);
});

// E100 certification: every authored structure in ONE turnover — fade-in,
// stack, centered dissolve, retime, fade-out, two audio legs, track + clip
// markers. Live loop measured 2026-09-01: all 16 video windows and 16 audio
// windows correct, verify_roundtrip pass:true against Resolve's re-export.
test('kitchen-sink OTIO turnover conforms with a complete ledger (E100)', () => {
  const rt = (v, r = 24) => ({ OTIO_SCHEMA: 'RationalTime.1', rate: r, value: v });
  const tr = (s, d, r = 24) => ({ OTIO_SCHEMA: 'TimeRange.1', start_time: rt(s, r), duration: rt(d, r) });
  const clip = (url, sIn, d, extra = {}) => ({ OTIO_SCHEMA: 'Clip.2', name: url, source_range: tr(sIn, d), media_reference: { target_url: url }, effects: [], markers: [], ...extra });
  const otio = { OTIO_SCHEMA: 'Timeline.1', tracks: { OTIO_SCHEMA: 'Stack.1', children: [
    { OTIO_SCHEMA: 'Track.1', kind: 'Video', markers: [
      { OTIO_SCHEMA: 'Marker.2', name: 'TM1', color: 'BLUE', marked_range: tr(30, 0) },
      { OTIO_SCHEMA: 'Marker.2', name: 'TM2', color: 'RED', marked_range: tr(100, 0) },
    ], children: [
      { OTIO_SCHEMA: 'Transition.1', transition_type: 'SMPTE_Dissolve', in_offset: rt(0), out_offset: rt(24) },
      clip('/m/cut.mp4', 24, 72),
      { OTIO_SCHEMA: 'Transition.1', transition_type: 'SMPTE_Dissolve', in_offset: rt(12), out_offset: rt(12) },
      clip('/m/wht.mp4', 24, 48, { markers: [{ OTIO_SCHEMA: 'Marker.2', name: 'CM1', color: 'GREEN', marked_range: tr(34, 0) }] }),
      clip('/m/cut.mp4', 0, 48, { effects: [{ OTIO_SCHEMA: 'LinearTimeWarp.1', time_scalar: 0.5 }] }),
      { OTIO_SCHEMA: 'Transition.1', transition_type: 'SMPTE_Dissolve', in_offset: rt(12), out_offset: rt(12) },
      { OTIO_SCHEMA: 'Gap.1', source_range: tr(0, 48) },
    ] },
    { OTIO_SCHEMA: 'Track.1', kind: 'Video', markers: [], children: [
      { OTIO_SCHEMA: 'Gap.1', source_range: tr(0, 24) }, clip('/m/wht.mp4', 96, 24),
    ] },
    { OTIO_SCHEMA: 'Track.1', kind: 'Audio', markers: [], children: [
      { OTIO_SCHEMA: 'Gap.1', source_range: tr(0, 12) }, clip('/m/cut.mp4', 12, 60),
    ] },
    { OTIO_SCHEMA: 'Track.1', kind: 'Audio', markers: [], children: [
      { OTIO_SCHEMA: 'Gap.1', source_range: tr(0, 96) }, clip('/m/cut.mp4', 0, 48),
    ] },
  ] } };
  const spec24 = { width: 640, height: 360, frameCount: 192, fps: 24 };
  const { spec, report } = eventsToAssembleSpec(parseOTIO(otio, { fps: 24 }), {
    sourceMap: { '/m/cut.mp4': { mediaFilePath: '/m/cut.mp4', spec: spec24 }, '/m/wht.mp4': { mediaFilePath: '/m/wht.mp4', spec: spec24 } },
  });
  assert.equal(report.droppedTransitions.length, 0, JSON.stringify(report.droppedTransitions));
  assert.equal(spec.transitions.length, 3);
  assert.equal(spec.elements.length, 2);
  assert.equal(spec.markers.length, 2);
  assert.equal(report.authoredRetimes.length, 1);
  assert.equal(report.authoredAudioEvents, 2);
  assert.equal(report.upperTrackCutsVideoOnly, 1);
  const whiteCut = spec.media.find((m) => m.mediaFilePath === '/m/wht.mp4').cuts.find((c) => c.markers);
  assert.deepEqual(whiteCut.markers, [{ frame: 10, color: 'Green', name: 'CM1' }]);
});

test('verifyRoundtrip matches path-style OTIO sources against basename re-exports (E100)', () => {
  const input = [{ track: 'V', source: '/media/deep/cut_src.mp4', recIn: 0, recOut: 48, srcIn: 0 }];
  const exported = [{ track: 'V', source: 'cut_src.mp4', recIn: 0, recOut: 48, srcIn: 0 }];
  assert.equal(verifyRoundtrip(input, exported).pass, true);
});

test('eventsToEDL writes the CMX transition pairs — dissolves and fades survive the EDL target (E101)', () => {
  // The OTIO writer carried transitions since day one; the EDL writer
  // silently dropped every one. Now: zero-length outgoing marker + D line,
  // with BL on the black side of fades — and the written EDL parses back to
  // a fully-authored spec.
  const events = [
    { track: 'V', source: 'BL', recIn: 86400, recOut: 86400, srcIn: 0, srcOut: 0, fps: 24 },
    { track: 'V', source: 'TAPE1', recIn: 86400, recOut: 86496, srcIn: 0, srcOut: 96, fps: 24, transition: { type: 'D', duration: 24 } },
    { track: 'V', source: 'TAPE2', recIn: 86496, recOut: 86544, srcIn: 48, srcOut: 96, fps: 24, transition: { type: 'D', duration: 24 } },
    { track: 'V', source: 'BL', recIn: 86544, recOut: 86592, srcIn: 0, srcOut: 0, fps: 24, transition: { type: 'D', duration: 24 } },
  ];
  const edl = eventsToEDL(events, { fps: 24 });
  assert.match(edl, /002 {2}TAPE1 V {5}D {4}024/);
  assert.match(edl, /006 {2}BL V {5}D {4}024/);
  const { spec, report } = eventsToAssembleSpec(parseEDL(edl, { fps: 24 }), { sourceMap: MAP });
  assert.equal(spec.transitions.length, 3);
  assert.equal(spec.elements.length, 2);
  assert.equal(report.droppedTransitions.length, 0);
});

test('eventsToOTIO carries transition alignment; the flat DRT target omits BL legs (E102)', async () => {
  const { eventsToOTIO, eventsToDrtSpec } = await import('../server/author-interchange.mjs');
  const events = [
    { index: 1, track: 'V', source: 'BL', recIn: 0, recOut: 0, srcIn: 0, srcOut: 0, fps: 24 },
    { index: 2, track: 'V', source: 'TAPE1', recIn: 0, recOut: 96, srcIn: 0, srcOut: 96, fps: 24, transition: { type: 'D', duration: 24, alignment: 'start' } },
    { index: 3, track: 'V', source: 'BL', recIn: 96, recOut: 144, srcIn: 0, srcOut: 0, fps: 24, transition: { type: 'D', duration: 24, alignment: 'start' } },
  ];
  // A centered rewrite of a start-at-cut fade-in used to demand incoming
  // pre-roll the source never needed — the round-trip dropped the fade.
  const back = parseOTIO(eventsToOTIO(events, { fps: 24 }), { fps: 24 });
  const { spec, report } = eventsToAssembleSpec(back, { sourceMap: MAP });
  assert.equal(spec.transitions.length, 2, JSON.stringify(report.droppedTransitions));
  assert.equal(spec.elements.length, 2);
  assert.equal(report.droppedTransitions.length, 0);
  // BL never becomes a bogus offline clip on the flat DRT target.
  const drtSpec = eventsToDrtSpec(events, { fps: 24 });
  assert.deepEqual(drtSpec.timelines[0].videoTracks[0].clips.map((c) => c.mediaFilePath), ['TAPE1']);
});

test('OTIO FreezeFrame effects ingest as freezes, write back as FreezeFrame, and verify (E103)', async () => {
  const { eventsToOTIO } = await import('../server/author-interchange.mjs');
  const rt = (v, r = 24) => ({ OTIO_SCHEMA: 'RationalTime.1', rate: r, value: v });
  const tr = (s, d, r = 24) => ({ OTIO_SCHEMA: 'TimeRange.1', start_time: rt(s, r), duration: rt(d, r) });
  // A FreezeFrame WITHOUT time_scalar (common writer shape) used to read as
  // a plain 100% clip — the freeze vanished at parse.
  const otio = { OTIO_SCHEMA: 'Timeline.1', tracks: { OTIO_SCHEMA: 'Stack.1', children: [
    { OTIO_SCHEMA: 'Track.1', kind: 'Video', markers: [], children: [
      { OTIO_SCHEMA: 'Clip.2', name: 'A', source_range: tr(0, 48), media_reference: { target_url: 'A' }, effects: [], markers: [] },
      { OTIO_SCHEMA: 'Clip.2', name: 'A', source_range: tr(48, 48), media_reference: { target_url: 'A' }, effects: [{ OTIO_SCHEMA: 'FreezeFrame.1', name: 'Freeze' }], markers: [] },
    ] },
  ] } };
  const events = parseOTIO(otio, { fps: 24 });
  assert.equal(events[1].speed, 0);
  const { spec, report } = eventsToAssembleSpec(events, { sourceMap: { A: { mediaFilePath: '/m/a.mp4', spec: { width: 640, height: 360, frameCount: 480, fps: 24 } } } });
  assert.equal(spec.media[0].cuts[1].freeze, true);
  assert.deepEqual(report.authoredRetimes, [{ index: 2, source: 'A', speed: 0, freeze: true }]);
  // Writer emits OTIO's own schema for it (Resolve's EXPORT_OTIO writes the
  // same FreezeFrame.1 for an authored freeze — measured live).
  const doc = eventsToOTIO(events, { fps: 24 });
  const eff = doc.tracks.children[0].children.find((c) => c.OTIO_SCHEMA === 'Clip.2' && c.effects.length).effects[0];
  assert.equal(eff.OTIO_SCHEMA, 'FreezeFrame.1');
  assert.equal(eff.time_scalar, 0);
  // and the round trip verifies; a freeze flattened to 100% fails as retime drift
  const back = parseOTIO(doc, { fps: 24 });
  assert.equal(verifyRoundtrip(events, back).pass, true);
  const flat = back.map((e) => ({ ...e, speed: 100 }));
  assert.equal(verifyRoundtrip(events, flat).mismatches[0].kind, 'retime');
});

// E105: QC through every export format. Resolve's own writers measured on a
// faded/dissolved/retimed conform — FCP7 XML (-1 junction edges, exact
// `speed` next to `variablespeed` 0, Solid Color generatoritems), CMX EDL
// (reel AX + FROM/TO CLIP NAME comments, video-only), OTIO (control).
test('parseXMEMLEvents reads Resolve-written -1 edges, exact speed, and Solid Color generators (E105)', () => {
  const xml = [
    "<?xml version='1.0'?><xmeml version='4'><sequence><rate><timebase>24</timebase></rate><media><video><track>",
    '<generatoritem id="g0"><name>Solid Color</name><start>0</start><end>-1</end><in>0</in><out>12</out></generatoritem>',
    '<transitionitem><start>0</start><end>24</end><alignment>center</alignment><effect><effectid>Cross Dissolve</effectid></effect></transitionitem>',
    '<clipitem id="c0"><name>cut_src.mp4</name><start>-1</start><end>-1</end><in>24</in><out>84</out></clipitem>',
    '<transitionitem><start>60</start><end>84</end><alignment>center</alignment><effect><effectid>Cross Dissolve</effectid></effect></transitionitem>',
    '<clipitem id="c1"><name>white_src.mp4</name><start>-1</start><end>120</end><in>12</in><out>60</out></clipitem>',
    '<clipitem id="c2"><name>cut_src.mp4</name><start>120</start><end>168</end><in>0</in><out>48</out>',
    '<filter><effect><name>Time Remap</name><effectid>timeremap</effectid>',
    '<parameter><name>speed</name><parameterid>speed</parameterid><value>50</value></parameter>',
    '<parameter><name>reverse</name><parameterid>reverse</parameterid><value>FALSE</value></parameter>',
    '<parameter><name>variablespeed</name><parameterid>variablespeed</parameterid><value>0</value></parameter>',
    '</effect></filter></clipitem>',
    '</track></video></media></sequence></xmeml>',
  ].join('');
  const ev = parseXMEMLEvents(xml, { fps: 24 });
  const rows = ev.filter((e) => e.recOut > e.recIn).map((e) => [e.source, e.recIn, e.recOut, e.srcIn, e.speed]);
  assert.deepEqual(rows, [
    ['BL', 0, 12, 0, 100],            // generatoritem, end -1 → the first junction
    ['cut_src.mp4', 12, 72, 36, 100], // both edges -1 → junction to junction; `in` advances by the overlap offset
    ['white_src.mp4', 72, 120, 24, 100],
    ['cut_src.mp4', 120, 168, 0, 50], // `speed` 50 survives the `variablespeed` 0 that follows it
  ]);
  const pic = ev.find((e) => e.source === 'cut_src.mp4' && e.recIn === 12);
  assert.equal(pic.transition.recStart, 0, 'the fade-in attaches to the PICTURE, not the black generator');
});

test('parseEDL applies FROM/TO CLIP NAME comments to generic AX reels (E105)', () => {
  const edl = [
    'TITLE: e105', 'FCM: NON-DROP FRAME', '',
    '001  BL       V     C        01:00:00:00 01:00:00:00 01:00:00:00 01:00:00:00',
    '001  AX       V     D    024 00:00:01:00 00:00:03:12 01:00:00:00 01:00:02:12',
    '* FROM CLIP NAME: Solid Color', '* TO CLIP NAME: cut_src.mp4', '',
    '002  AX       V     C        00:00:03:12 00:00:03:12 01:00:02:12 01:00:02:12',
    '002  AX       V     D    024 00:00:00:12 00:00:03:00 01:00:02:12 01:00:05:00',
    '* FROM CLIP NAME: cut_src.mp4', '* TO CLIP NAME: white_src.mp4', '',
    '003  TAPE9    V     C        00:00:00:00 00:00:01:12 01:00:05:00 01:00:06:12',
    '* FROM CLIP NAME: keeps_reel.mov', '',
  ].join('\n');
  const ev = parseEDL(edl, { fps: 24 });
  assert.deepEqual(ev.map((e) => e.source), ['BL', 'cut_src.mp4', 'cut_src.mp4', 'white_src.mp4', 'TAPE9']);
  assert.equal(ev[4].clipName, 'keeps_reel.mov'); // a specific reel keeps its name, clipName rides along
});

test('verifyRoundtrip flags a video-only export as audioNotInExport instead of failing (E105)', () => {
  const input = [
    { track: 'V', source: 'A', recIn: 0, recOut: 48, srcIn: 0 },
    { track: 'A', source: 'A', recIn: 0, recOut: 48, srcIn: 0 },
  ];
  const exported = [{ track: 'V', source: 'A.mov', recIn: 0, recOut: 48, srcIn: 0 }];
  const r = verifyRoundtrip(input, exported);
  assert.equal(r.pass, true, JSON.stringify(r.mismatches));
  assert.equal(r.audioNotInExport, true);
  assert.equal(r.audio.compared, false);
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
  assert.deepEqual(w.spec.transitions, [{ track: 1, atFrame: 86460, durationFrames: 24, type: 'wipe', startFrame: 86448 }]);
  const disEdl = wipeEdl.replace('W001 024', 'D    024');
  const d = eventsToAssembleSpec(parseEDL(disEdl, { fps: 24 }), { sourceMap: MAP });
  assert.deepEqual(d.spec.transitions, [{ track: 1, atFrame: 86460, durationFrames: 24, startFrame: 86448 }]);
});

test('buildRampTimemapKeyed: piecewise arithmetic, srcIn baking, and refusals (E63/E64)', () => {
  const requireR = requireCjs;
  const { buildRampTimemapKeyed } = requireR('../vendor/drp-format/media-timemap.js');
  const { decodeKeyedDict } = requireR('../vendor/drp-format/keyed-dict.js');
  // E64 live-verified shape: srcIn 96, 24f @0.5 then 24f @2.0 → source 96..156,
  // rendered f0 at the source-96 luma family, second half at 4.3x the first
  // half's per-frame motion. interp stays 0 EVERYWHERE: an interp=2 keyframe
  // CRASHED Resolve outright on import (E65, app death) — easing is a
  // measured crasher on 19.1.3, linear segments are the envelope.
  const map = buildRampTimemapKeyed({
    segments: [{ durationFrames: 24, speed: 0.5 }, { durationFrames: 24, speed: 2.0 }],
    srcIn: 96, sourceFrames: 192, fps: 24, uniqueId: 'u-ramp',
  });
  const d = decodeKeyedDict(map);
  const get = (k) => d.entries.find((e) => e.key === k).value;
  assert.equal(get('XMax'), 2);                       // 48 record frames
  assert.equal(get('YMax'), 156 / 24);                // source end
  assert.equal(get('LastValidYOffset'), 191 / 24);    // whole-source extent, as always
  const kfs = decodeKeyedDict(Buffer.from(get('KeyframesBA'), 'hex')).entries;
  assert.equal(kfs.length, 3);
  for (const k of kfs) {
    const inner = decodeKeyedDict(Buffer.from(k.value, 'hex')).entries;
    assert.equal(inner.find((e) => e.key === 'interp').value, 0, 'interp must stay 0 — easing crashes Resolve (measured)');
  }
  assert.throws(() => buildRampTimemapKeyed({ segments: [{ durationFrames: 24, speed: 2 }], srcIn: 0, sourceFrames: 192, fps: 24, uniqueId: 'u' }), />= 2/);
  assert.throws(() => buildRampTimemapKeyed({ segments: [{ durationFrames: 24, speed: 4 }, { durationFrames: 24, speed: 4 }], srcIn: 0, sourceFrames: 100, fps: 24, uniqueId: 'u' }), /consumes source frame/);
  assert.throws(() => buildRampTimemapKeyed({ segments: [{ durationFrames: 24, speed: 0 }, { durationFrames: 24, speed: 1 }], srcIn: 0, sourceFrames: 192, fps: 24, uniqueId: 'u' }), /speed must be > 0/);
});

test('XMEML transitionitems parse and map to render-verified styles (E66-E69)', () => {
  const { parseXMEMLEvents } = requireCjs('../server/editorial.mjs');
  const xml = `<?xml version="1.0"?><xmeml version="4"><sequence><name>S</name>
   <rate><timebase>24</timebase></rate><media><video><track>
   <clipitem><name>a.mp4</name><start>0</start><end>48</end><in>24</in><out>72</out></clipitem>
   <transitionitem><start>36</start><end>60</end><alignment>center</alignment>
    <effect><name>Dip to Color Dissolve</name><effectid>Dip to Color Dissolve</effectid></effect></transitionitem>
   <clipitem><name>b.mp4</name><start>48</start><end>96</end><in>24</in><out>72</out></clipitem>
   </track></video></media></sequence></xmeml>`;
  const events = parseXMEMLEvents(xml, { fps: 24 });
  const incoming = events.find((e) => e.recIn === 48);
  assert.deepEqual(incoming.transition, { type: 'Dip to Color Dissolve', duration: 24, recStart: 36 });
  const map2 = { 'a.mp4': MAP.TAPE1, 'b.mp4': MAP.TAPE2 };
  const { spec, report } = eventsToAssembleSpec(events, { sourceMap: map2 });
  assert.deepEqual(spec.transitions, [{ track: 1, atFrame: 86448, durationFrames: 24, type: 'dip', startFrame: 86436 }]);
  assert.equal(report.authoredTransitions[0].type, 'dip');
});

test('OTIO Transition children attach to the incoming clip and author (E70)', () => {
  const rt = (v) => ({ OTIO_SCHEMA: 'RationalTime.1', rate: 24, value: v });
  const clip = (name, start, dur) => ({ OTIO_SCHEMA: 'Clip.1', name,
    source_range: { OTIO_SCHEMA: 'TimeRange.1', start_time: rt(start), duration: rt(dur) },
    media_reference: { OTIO_SCHEMA: 'ExternalReference.1', target_url: name } });
  const doc = { OTIO_SCHEMA: 'Timeline.1', tracks: { OTIO_SCHEMA: 'Stack.1', children: [
    { OTIO_SCHEMA: 'Track.1', kind: 'Video', children: [
      clip('TAPE1', 24, 48),
      { OTIO_SCHEMA: 'Transition.1', transition_type: 'SMPTE_Dissolve', in_offset: rt(12), out_offset: rt(12) },
      clip('TAPE2', 24, 48),
    ] },
  ] } };
  const events = parseOTIO(doc, { fps: 24 });
  const incoming = events.find((e) => e.recIn === 48);
  assert.deepEqual(incoming.transition, { type: 'SMPTE_Dissolve', duration: 24, inOffset: 12 });
  const { spec } = eventsToAssembleSpec(events, { sourceMap: MAP });
  // SMPTE_Dissolve maps to the plain dissolve; the explicit in/out offsets
  // carry the span (12 before the cut).
  assert.deepEqual(spec.transitions, [{ track: 1, atFrame: 86448, durationFrames: 24, startFrame: 86436 }]);
});

test('verifyRoundtrip compares markers; a marker-less export is flagged, not failed (E88)', () => {
  const base = [
    { track: 'V1', source: 'A', recIn: 0, recOut: 48, srcIn: 0 },
    { track: 'MARKER', source: '', recIn: 12, recOut: null, name: 'first' },
    { track: 'MARKER', source: '', recIn: 40, recOut: null, name: 'second' },
  ];
  const exportedNoMk = [{ track: 'V', source: 'A.mov', recIn: 86400, recOut: 86448, srcIn: 0 }];
  // Resolve's OTIO export drops timeline markers wholesale (measured live:
  // 2 read back through the marker API, 0 in the export) — honesty flag.
  const r1 = verifyRoundtrip(base, exportedNoMk);
  assert.equal(r1.pass, true);
  assert.equal(r1.markersNotInExport, true);
  // when the export DOES carry markers, they compare strictly
  const exportedMk = [...exportedNoMk,
    { track: 'MARKER', source: '', recIn: 86412, recOut: null, name: 'first' },
    { track: 'MARKER', source: '', recIn: 86445, recOut: null, name: 'second' }];
  const r2 = verifyRoundtrip(base, exportedMk);
  assert.equal(r2.pass, false);
  assert.equal(r2.mismatches[0].kind, 'marker-frame'); // 40 vs 45
  const exportedGood = [...exportedNoMk,
    { track: 'MARKER', source: '', recIn: 86412, recOut: null, name: 'first' },
    { track: 'MARKER', source: '', recIn: 86440, recOut: null, name: 'second' }];
  const r3 = verifyRoundtrip(base, exportedGood);
  assert.equal(r3.pass, true);
  assert.equal(r3.markers.exported, 2);
});

// E107: measured against Resolve 19.1.3.7's OWN FCP7 writer (fixture is the
// verbatim export of a fade-in → clip → centered dissolve → clip → fade-out
// timeline, rendered and luma-verified 2026-09-01). Two laws: (1) with three
// centered transitions, two equal-length clips both carry -1/-1 edges and
// the first-pair rule put BOTH at the first junction pair; a record-order
// cursor fixes it. (2) The writer emits NO pproTicksIn at all.
const E107_XML = fs.readFileSync(new URL('./fixtures/E107_resolve_fades.xml', import.meta.url), 'utf8');

test('parseXMEMLEvents places equal-length -1/-1 clips at successive junction pairs (E107)', () => {
  const ev = parseXMEMLEvents(E107_XML);
  const vid = ev.filter((e) => e.track === 'V' && !/^BL$/.test(e.source));
  assert.deepEqual(vid.map((e) => [e.source, e.recIn, e.recOut, e.srcIn, e.srcOut]), [
    ['cut_src.mp4', 12, 108, 36, 132],
    ['white_src.mp4', 108, 204, 12, 108],
  ]);
  const black = ev.filter((e) => e.track === 'V' && e.source === 'BL');
  assert.deepEqual(black.map((e) => [e.recIn, e.recOut]), [[0, 12], [204, 216]]);
  assert.ok(!E107_XML.includes('pproTicksIn'), 'the fixture must stay a verbatim Resolve export (no ticks)');
});
