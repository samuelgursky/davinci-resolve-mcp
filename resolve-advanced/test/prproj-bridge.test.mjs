/**
 * Premiere .prproj offline reader (gunzip + object-graph walk) and the events→interchange conform
 * bridge (OTIO/EDL/DRT). A synthetic .prproj fixture is authored to the documented CC schema and
 * gzipped; the bridge is round-trip-verified against this repo's own parseOTIO. Offline, no Resolve,
 * no Premiere, no new deps.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';

import { parsePrproj, parsePrprojDoc, listPrprojSequences } from '../server/prproj.mjs';
import { eventsToOTIO, eventsToEDL, authorInterchange } from '../server/author-interchange.mjs';
import { parseOTIO } from '../server/editorial.mjs';
import { drt } from '../server/libs.mjs';
import { editorialTool } from '../server/tools/editorial.mjs';

const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'prproj-'));
const TPF24 = 254016000000 / 24; // ticks per frame @ 24
const f = (frames) => Math.round(frames * TPF24); // frames → ticks

// A minimal .prproj: two sequences, a 2× speed clip, an audio clip, a marker, media paths.
const PRPROJ_XML = `<?xml version="1.0" encoding="UTF-8"?>
<PremiereData Version="3">
  <Project ObjectID="1" ClassID="62ad66dd-0dcd-42da-a660-6d8fbde94876" Version="40">
    <RootProjectItem ObjectRef="2"/>
  </Project>
  <Sequence ObjectID="10" ClassID="s" Version="40">
    <Node Version="1"><Properties><Name>EP01 CUT</Name><FrameRate>24</FrameRate></Properties></Node>
    <VideoTracks><Track ObjectRef="20"/></VideoTracks>
    <AudioTracks><Track ObjectRef="30"/></AudioTracks>
  </Sequence>
  <Sequence ObjectID="11" ClassID="s" Version="40">
    <Node Version="1"><Properties><Name>EP01 BONUS</Name><FrameRate>24</FrameRate></Properties></Node>
    <VideoTracks><Track ObjectRef="21"/></VideoTracks>
  </Sequence>
  <VideoTrack ObjectID="20" ClassID="v" Version="1">
    <TrackItems><TrackItem ObjectRef="40"/><TrackItem ObjectRef="41"/></TrackItems>
  </VideoTrack>
  <AudioTrack ObjectID="30" ClassID="a" Version="1">
    <TrackItems><TrackItem ObjectRef="50"/></TrackItems>
  </AudioTrack>
  <VideoTrack ObjectID="21" ClassID="v" Version="1">
    <TrackItems><TrackItem ObjectRef="42"/></TrackItems>
  </VideoTrack>
  <VideoClipTrackItem ObjectID="40" ClassID="c" Version="1">
    <Start>${f(0)}</Start><End>${f(24)}</End><InPoint>${f(0)}</InPoint><OutPoint>${f(24)}</OutPoint>
    <ClipProjectItem ObjectRef="60"/>
  </VideoClipTrackItem>
  <VideoClipTrackItem ObjectID="41" ClassID="c" Version="1">
    <Start>${f(24)}</Start><End>${f(48)}</End><InPoint>${f(0)}</InPoint><OutPoint>${f(48)}</OutPoint>
    <ClipProjectItem ObjectRef="61"/>
  </VideoClipTrackItem>
  <AudioClipTrackItem ObjectID="50" ClassID="c" Version="1">
    <Start>${f(0)}</Start><End>${f(48)}</End><InPoint>${f(0)}</InPoint><OutPoint>${f(48)}</OutPoint>
    <ClipProjectItem ObjectRef="60"/>
  </AudioClipTrackItem>
  <VideoClipTrackItem ObjectID="42" ClassID="c" Version="1">
    <Start>${f(0)}</Start><End>${f(12)}</End><InPoint>${f(0)}</InPoint><OutPoint>${f(12)}</OutPoint>
    <ClipProjectItem ObjectRef="62"/>
  </VideoClipTrackItem>
  <ClipProjectItem ObjectID="60" ClassID="p" Version="1">
    <Node Version="1"><Properties><Name>A001</Name></Properties></Node>
    <ActualMediaFilePath>/media/A001.mov</ActualMediaFilePath>
  </ClipProjectItem>
  <ClipProjectItem ObjectID="61" ClassID="p" Version="1">
    <ActualMediaFilePath>/media/B002.mov</ActualMediaFilePath>
  </ClipProjectItem>
  <ClipProjectItem ObjectID="62" ClassID="p" Version="1">
    <ActualMediaFilePath>/media/C003.mov</ActualMediaFilePath>
  </ClipProjectItem>
  <Marker ObjectID="70" ClassID="m" Version="1">
    <Position>${f(12)}</Position><Duration>0</Duration><Name>M1</Name><Comment>flash</Comment><MarkerType>0</MarkerType><ColorIndex>1</ColorIndex>
  </Marker>
</PremiereData>`;

const PRPROJ = path.join(TMP, 'project.prproj');
fs.writeFileSync(PRPROJ, zlib.gzipSync(Buffer.from(PRPROJ_XML, 'utf8')));

// A CS6-style uncompressed .prproj to prove the plain-XML path.
const PRPROJ_PLAIN = path.join(TMP, 'cs6.prproj');
fs.writeFileSync(PRPROJ_PLAIN, PRPROJ_XML);

test('readPrproj: gunzips a CC .prproj and enumerates sequences', () => {
  const seqs = listPrprojSequences(PRPROJ);
  assert.equal(seqs.length, 2);
  assert.deepEqual(
    seqs.map((s) => [s.name, s.eventCount]),
    [
      ['EP01 CUT', 3], // 2 video + 1 audio
      ['EP01 BONUS', 1],
    ],
  );
});

test('readPrproj: also reads an uncompressed (CS6) .prproj', () => {
  const seqs = listPrprojSequences(PRPROJ_PLAIN);
  assert.equal(seqs.length, 2);
});

test('parsePrproj: normalized events with derived speed + resolved media names', () => {
  const events = parsePrproj(PRPROJ);
  assert.equal(events.length, 4);
  const b = events.find((e) => e.source === 'B002.mov');
  assert.ok(b, 'B002 present');
  assert.equal(b.recOut - b.recIn, 24); // timeline span
  assert.equal(b.srcOut - b.srcIn, 48); // source span
  assert.equal(b.speed, 200); // 2× from tick geometry
  const a = events.find((e) => e.source === 'A001.mov' && e.track === 'V');
  assert.equal(a.speed, 100);
  assert.ok(events.some((e) => e.track === 'A' && e.source === 'A001.mov'));
});

// Premiere transitions carry an explicit record span (Start/End ticks). The
// old exact-start attach silently dropped every CENTERED transition; and
// edge spans with a missing neighbor are fades, routed through the BL
// machinery (E96).
const PRPROJ_TRANS_XML = `<?xml version="1.0" encoding="UTF-8"?>
<PremiereData Version="3">
  <Project ObjectID="1" ClassID="62ad66dd-0dcd-42da-a660-6d8fbde94876" Version="40">
    <RootProjectItem ObjectRef="2"/>
  </Project>
  <Sequence ObjectID="10" ClassID="s" Version="40">
    <Node Version="1"><Properties><Name>FADES</Name><FrameRate>24</FrameRate></Properties></Node>
    <VideoTracks><Track ObjectRef="20"/></VideoTracks>
  </Sequence>
  <VideoTrack ObjectID="20" ClassID="v" Version="1">
    <TrackItems>
      <TrackItem ObjectRef="40"/><TrackItem ObjectRef="41"/>
      <TrackItem ObjectRef="80"/><TrackItem ObjectRef="81"/><TrackItem ObjectRef="82"/>
    </TrackItems>
  </VideoTrack>
  <VideoClipTrackItem ObjectID="40" ClassID="c" Version="1">
    <Start>${f(0)}</Start><End>${f(96)}</End><InPoint>${f(24)}</InPoint><OutPoint>${f(120)}</OutPoint>
    <ClipProjectItem ObjectRef="60"/>
  </VideoClipTrackItem>
  <VideoClipTrackItem ObjectID="41" ClassID="c" Version="1">
    <Start>${f(96)}</Start><End>${f(168)}</End><InPoint>${f(24)}</InPoint><OutPoint>${f(96)}</OutPoint>
    <ClipProjectItem ObjectRef="61"/>
  </VideoClipTrackItem>
  <VideoTransitionTrackItem ObjectID="80" ClassID="t" Version="1">
    <Start>${f(0)}</Start><End>${f(24)}</End>
  </VideoTransitionTrackItem>
  <VideoTransitionTrackItem ObjectID="81" ClassID="t" Version="1">
    <Start>${f(84)}</Start><End>${f(108)}</End>
  </VideoTransitionTrackItem>
  <VideoTransitionTrackItem ObjectID="82" ClassID="t" Version="1">
    <Start>${f(156)}</Start><End>${f(180)}</End>
  </VideoTransitionTrackItem>
  <ClipProjectItem ObjectID="60" ClassID="p" Version="1">
    <ActualMediaFilePath>/media/A001.mov</ActualMediaFilePath>
  </ClipProjectItem>
  <ClipProjectItem ObjectID="61" ClassID="p" Version="1">
    <ActualMediaFilePath>/media/B002.mov</ActualMediaFilePath>
  </ClipProjectItem>
</PremiereData>`;

const PRPROJ_TRANS = path.join(TMP, 'trans.prproj');
fs.writeFileSync(PRPROJ_TRANS, zlib.gzipSync(Buffer.from(PRPROJ_TRANS_XML, 'utf8')));

test('prproj transitions: centered spans attach with recStart; edge spans synthesize BL fades (E96)', async () => {
  const events = parsePrproj(PRPROJ_TRANS);
  const bls = events.filter((e) => e.source === 'BL');
  assert.equal(bls.length, 2, JSON.stringify(events, null, 1));
  // fade-in predecessor at the head, fade-out carrier at the tail
  assert.deepEqual(bls.map((e) => [e.recIn, e.recOut, !!e.transition]), [[0, 0, false], [168, 168, true]]);
  const b = events.find((e) => e.source === 'B002.mov');
  assert.deepEqual(b.transition, { type: 'dissolve', duration: 24, recStart: 84 });
  const { eventsToAssembleSpec } = await import('../server/author-interchange.mjs');
  const { spec, report } = eventsToAssembleSpec(events, {
    sourceMap: {
      'A001.mov': { mediaFilePath: '/m/a.mp4', spec: { width: 640, height: 360, frameCount: 480, fps: 24 } },
      'B002.mov': { mediaFilePath: '/m/b.mp4', spec: { width: 640, height: 360, frameCount: 480, fps: 24 } },
    },
  });
  assert.equal(report.droppedTransitions.length, 0, JSON.stringify(report.droppedTransitions));
  assert.equal(spec.transitions.length, 3); // fade-in + centered dissolve + fade-out
  assert.equal(spec.elements.length, 2); // two BL generators
  // the centered dissolve keeps its explicit span [84,108) with the junction untouched
  assert.ok(spec.transitions.some((t) => t.startFrame === 86400 + 84 && t.atFrame === 86400 + 96));
});

test('parsePrprojDoc: exposes project version, media paths, markers', () => {
  const doc = parsePrprojDoc(PRPROJ);
  assert.equal(doc.projectVersion, 40);
  assert.deepEqual(doc.mediaPaths, ['/media/A001.mov', '/media/B002.mov', '/media/C003.mov']);
  assert.ok(doc.sequences[0].markers.some((m) => m.name === 'M1' && m.frame === 12));
});

test('bridge: eventsToOTIO round-trips through parseOTIO (speed-100 exact)', () => {
  const events = [
    { track: 'V', source: 'A001.mov', srcIn: 0, srcOut: 24, recIn: 0, recOut: 24, speed: 100, reverse: false, fps: 24 },
    { track: 'V', source: 'B002.mov', srcIn: 10, srcOut: 34, recIn: 34, recOut: 58, speed: 100, reverse: false, fps: 24 }, // gap 10
  ];
  const otio = eventsToOTIO(events, { name: 'RT' });
  const back = parseOTIO(otio);
  assert.equal(back.length, 2);
  assert.equal(back[0].recIn, 0);
  assert.equal(back[1].recIn, 34); // gap preserved
  assert.equal(back[1].srcIn, 10);
  assert.equal(back[1].srcOut, 34);
});

test('bridge: OTIO carries speed via LinearTimeWarp; EDL emits M2', () => {
  const events = parsePrproj(PRPROJ);
  const otio = eventsToOTIO(events);
  const warp = JSON.stringify(otio).match(/LinearTimeWarp/g) || [];
  assert.ok(warp.length >= 1, 'a retimed clip yields a LinearTimeWarp');
  const edl = eventsToEDL(events);
  assert.match(edl, /^M2\s+B002/m);
});

test('bridge: authorInterchange drt builds a Resolve-native timeline', async () => {
  const events = parsePrproj(PRPROJ);
  const out = await authorInterchange(events, 'drt', { name: 'FromPrproj' });
  assert.ok(out.bytes > 0);
  const drtPath = path.join(TMP, 'out.drt');
  fs.writeFileSync(drtPath, out.buffer);
  const parsed = await drt().parseDRT(drtPath);
  assert.ok(parsed.timelines[0].videoTracks[0].clips.length >= 2);
});

// The DRT clip schema (vendor/drp-format/seq-container-builder.js) reads start / duration /
// in / mediaFilePath / mediaStartTime / mediaFrameRate — there is NO per-clip speed field, so
// a retime CANNOT ride into a .drt. The cluster's contract is skip-not-fake: say so, per event.
const RETIME_EVENTS = [
  { track: 'V', recIn: 0, recOut: 48, srcIn: 100, source: '/media/a.mov' },
  { track: 'V', recIn: 48, recOut: 96, srcIn: 200, source: '/media/b.mov', speed: 200 },
  { track: 'V', recIn: 96, recOut: 144, srcIn: 300, source: '/media/c.mov', reverse: true },
];

test('bridge: DRT target FLAGS flattened retimes instead of dropping them silently', async () => {
  const out = await authorInterchange(RETIME_EVENTS, 'drt', { name: 'Retimes' });
  assert.ok(Array.isArray(out.flattened), 'drt target must report a flattened list');
  assert.equal(out.flattened.length, 2, 'the 200% and the reverse are both flattened');
  const speedEv = out.flattened.find((x) => x.speed === 200);
  assert.ok(speedEv, '200% event is named');
  assert.equal(speedEv.index, 1);
  assert.equal(speedEv.recIn, 48);
  assert.match(speedEv.reason, /speed/i);
  const revEv = out.flattened.find((x) => x.reverse === true);
  assert.ok(revEv, 'reverse event is named');
  assert.equal(revEv.index, 2);
  assert.equal(revEv.recIn, 96);
  // The un-retimed event is NOT flagged.
  assert.equal(out.flattened.some((x) => x.recIn === 0), false);
});

test('bridge: a cuts-only DRT reports an EMPTY flattened list, not a missing one', async () => {
  const out = await authorInterchange([RETIME_EVENTS[0]], 'drt', { name: 'Cuts' });
  assert.deepEqual(out.flattened, []);
});

test('bridge: OTIO and EDL still CARRY speed/reverse — only DRT flattens', async () => {
  const otio = await authorInterchange(RETIME_EVENTS, 'otio', {});
  assert.equal(otio.flattened, undefined, 'otio carries retimes, so nothing is flattened');
  const scalars = JSON.stringify(otio.doc).match(/"time_scalar":\s*(-?[\d.]+)/g) || [];
  assert.equal(scalars.length, 2);
  const edl = await authorInterchange(RETIME_EVENTS, 'edl', {});
  assert.equal(edl.flattened, undefined);
  assert.equal((edl.content.match(/^M2\s/gm) || []).length, 2);
});

test('convert_to_interchange action: DRT target surfaces flattened retimes to the caller', async () => {
  const r = await editorialTool.handler({
    action: 'convert_to_interchange',
    args: { events: RETIME_EVENTS, target: 'drt', name: 'Retimes' },
  });
  assert.equal(r.target, 'drt');
  assert.equal(r.flattened.length, 2);
  assert.equal(r.flattenedCount, 2);
});

test('convert_to_interchange action: prproj source → OTIO content the parser accepts', async () => {
  const r = await editorialTool.handler({
    action: 'convert_to_interchange',
    args: { sourcePath: PRPROJ, target: 'otio', name: 'Bridged' },
  });
  assert.equal(r.target, 'otio');
  assert.equal(r.eventCount, 4);
  const back = parseOTIO(JSON.parse(r.content));
  assert.ok(back.length >= 3);
});

test('parse_interchange prproj → events + projectVersion (no more refuse)', async () => {
  const r = await editorialTool.handler({ action: 'parse_interchange', args: { format: 'prproj', content: PRPROJ } });
  assert.equal(r.format, 'prproj');
  assert.equal(r.count, 4);
  assert.equal(r.projectVersion, 40);
});

// The OTIO shape Resolve's importer actually accepts. Measured on 19.1.3 by round-tripping
// Resolve's own EXPORT_OTIO: a Resolve-authored .otio re-imports (3 items, 3 linked) while
// the shape this module used to emit produced NO TIMELINE from the same three online files.
test('otio: emits the Clip.2 / media_references shape Resolve imports', () => {
  const doc = eventsToOTIO([
    { track: 'V', recIn: 0, recOut: 48, srcIn: 0, source: '/m/src01.mov', fps: 24, mediaStartTcFrame: 86400, mediaDuration: 240 },
  ], { name: 'Shape', fps: 24, startFrame: 86400 });
  assert.equal(doc.global_start_time.value, 86400);
  const track = doc.tracks.children[0];
  assert.equal(track.name, 'Video 1');
  assert.equal(track.kind, 'Video');
  assert.equal(track.enabled, true);
  const clip = track.children[0];
  assert.equal(clip.OTIO_SCHEMA, 'Clip.2', 'Clip.1 + singular media_reference is what Resolve refuses');
  assert.equal(clip.media_reference, undefined);
  assert.equal(clip.active_media_reference_key, 'DEFAULT_MEDIA');
  assert.equal(clip.name, 'src01.mov', 'name is the basename, not the full path');
  const ref = clip.media_references.DEFAULT_MEDIA;
  assert.equal(ref.target_url, '/m/src01.mov', 'a BARE path, not a file:// URL');
  assert.equal(ref.available_range.start_time.value, 86400);
  assert.equal(ref.available_range.duration.value, 240);
});

test('otio: source frames are TIMECODE-ABSOLUTE against the media origin', () => {
  // The decisive one. 0-based source offsets sit outside the media's real range and Resolve
  // creates no timeline; the same cut with absolute frames imports 3/3.
  const [clip] = eventsToOTIO([
    { track: 'V', recIn: 0, recOut: 48, srcIn: 100, source: '/m/a.mov', fps: 24, mediaStartTcFrame: 86400, mediaDuration: 240 },
  ], { fps: 24 }).tracks.children[0].children;
  assert.equal(clip.source_range.start_time.value, 86500, 'origin 86400 + srcIn 100');
  assert.equal(clip.media_references.DEFAULT_MEDIA.available_range.start_time.value, 86400);
  // An already-absolute srcTcFrame wins and back-derives the media origin.
  const [abs] = eventsToOTIO([
    { track: 'V', recIn: 0, recOut: 48, srcIn: 100, srcTcFrame: 90000, source: '/m/a.mov', fps: 24, mediaDuration: 240 },
  ], { fps: 24 }).tracks.children[0].children;
  assert.equal(abs.source_range.start_time.value, 90000);
  assert.equal(abs.media_references.DEFAULT_MEDIA.available_range.start_time.value, 89900);
});

test('otio: an ASSUMED media timecode origin is reported, not hidden', async () => {
  const withOrigin = await authorInterchange(
    [{ track: 'V', recIn: 0, recOut: 48, srcIn: 0, source: '/m/a.mov', fps: 24, mediaStartTcFrame: 86400 }], 'otio', {});
  assert.deepEqual(withOrigin.mediaOriginAssumed, []);
  const without = await authorInterchange(
    [{ track: 'V', recIn: 0, recOut: 48, srcIn: 0, source: '/m/a.mov', fps: 24 }], 'otio', {});
  assert.equal(without.mediaOriginAssumed.length, 1);
  assert.equal(without.mediaOriginAssumed[0].index, 0);
  assert.match(without.mediaOriginAssumed[0].reason, /origin/i);
  // Assuming 0 is still what gets emitted — the point is that you are TOLD.
  assert.equal(without.doc.tracks.children[0].children[0].source_range.start_time.value, 0);
});

// E132: a REAL Premiere 2025 project (measured on a 130 MB colour turnover,
// project Version 45) defines sequences, project items, master clips, media
// and clip tracks by uuid ObjectUID (referenced by ObjectURef), lists tracks
// through TrackGroups → Video/AudioTrackGroup → TrackGroup.Tracks, and puts
// an item's record span under ClipTrackItem.TrackItem with the source chain
// SubClip → VideoClip (InPoint/OutPoint, Source) → VideoMediaSource → Media.
// A zero is written as absence (the leader at record 0 has End and no Start).
// The parser used to key ObjectID only and follow ObjectRef only: 0 of 739
// sequences listed. Now 739 list and the reel walks 335 events.
const REAL_SHAPE_XML = `<?xml version="1.0" encoding="UTF-8" ?>
<PremiereData Version="3">
  <Project ObjectRef="1"/>
  <Project ObjectID="1" ClassID="62ad66dd-0dcd-42da-a660-6d8fbde94876" Version="45"><Node Version="1"/></Project>
  <Sequence ObjectUID="06aa0210-b3c3-4858-9c56-48b6f029f8c1" ClassID="6a15d903-8739-11d5-af2d-9b7855ad8974" Version="12">
    <Node Version="1"><Properties Version="1"/></Node>
    <TrackGroups Version="1">
      <TrackGroup Version="1" Index="0"><First>228cda18-3625-4d2d-951e-348879e4ed93</First><Second ObjectRef="28140"/></TrackGroup>
      <TrackGroup Version="1" Index="1"><First>80b8e3d5-6dca-4195-aefb-cb5f407ab009</First><Second ObjectRef="28141"/></TrackGroup>
    </TrackGroups>
    <Name>REAL_REEL</Name>
  </Sequence>
  <Sequence ObjectUID="2b0665a8-e73d-4b91-82f2-d130a2cd9c32" ClassID="6a15d903-8739-11d5-af2d-9b7855ad8974" Version="12">
    <Node Version="1"><Properties Version="1"/></Node>
    <TrackGroups Version="1"><TrackGroup Version="1" Index="0"><First>228cda18-3625-4d2d-951e-348879e4ed93</First><Second ObjectRef="28150"/></TrackGroup></TrackGroups>
    <Name>NESTED_SELECTS</Name>
  </Sequence>
  <VideoTrackGroup ObjectID="28150" ClassID="v" Version="1"><TrackGroup Version="1"><Tracks Version="1"><Track Index="0" ObjectURef="5f2d4adc-1632-4dec-afaf-183607bd6650"/></Tracks><FrameRate>10584000000</FrameRate></TrackGroup></VideoTrackGroup>
  <VideoClipTrack ObjectUID="5f2d4adc-1632-4dec-afaf-183607bd6650" ClassID="vt" Version="1"><ClipTrack Version="1"><ClipItems Version="1"><TrackItems Version="1"><TrackItem Index="0" ObjectRef="50190"/><TrackItem Index="1" ObjectRef="50191"/></TrackItems></ClipItems></ClipTrack></VideoClipTrack>
  <VideoClipTrackItem ObjectID="50190" ClassID="ci" Version="1"><ClipTrackItem Version="8"><TrackItem Version="4"><End>254016000000</End></TrackItem><SubClip ObjectRef="69280"/></ClipTrackItem></VideoClipTrackItem>
  <VideoClipTrackItem ObjectID="50191" ClassID="ci" Version="1"><ClipTrackItem Version="8"><TrackItem Version="4"><Start>254016000000</Start><End>508032000000</End></TrackItem><SubClip ObjectRef="69270"/></ClipTrackItem></VideoClipTrackItem>
  <SubClip ObjectID="69280" ClassID="sc" Version="6"><Clip ObjectRef="101140"/><MasterClip ObjectURef="897fc7cf-a22c-4759-a6e2-0adeea00c0d1"/><Name>Universal Counting Leader</Name></SubClip>
  <VideoClip ObjectID="101140" ClassID="vc" Version="11"><Clip Version="18"><Source ObjectRef="5078"/><InPoint>508032000000</InPoint><OutPoint>762048000000</OutPoint></Clip></VideoClip>
  <VideoTrackGroup ObjectID="28140" ClassID="v" Version="1"><TrackGroup Version="1"><Tracks Version="1"><Track Index="0" ObjectURef="4f2d4adc-1632-4dec-afaf-183607bd663b"/></Tracks><FrameRate>10584000000</FrameRate></TrackGroup></VideoTrackGroup>
  <AudioTrackGroup ObjectID="28141" ClassID="a" Version="1"><TrackGroup Version="1"><Tracks Version="1"><Track Index="0" ObjectURef="aa2d4adc-1632-4dec-afaf-183607bd663b"/></Tracks><FrameRate>10584000000</FrameRate></TrackGroup></AudioTrackGroup>
  <VideoClipTrack ObjectUID="4f2d4adc-1632-4dec-afaf-183607bd663b" ClassID="vt" Version="1"><ClipTrack Version="1"><ClipItems Version="1"><TrackItems Version="1"><TrackItem Index="0" ObjectRef="50187"/><TrackItem Index="1" ObjectRef="50188"/><TrackItem Index="2" ObjectRef="50189"/></TrackItems></ClipItems></ClipTrack></VideoClipTrack>
  <VideoClipTrackItem ObjectID="50189" ClassID="ci" Version="1"><ClipTrackItem Version="8"><TrackItem Version="4"><Start>2540160000000</Start><End>2921184000000</End></TrackItem><SubClip ObjectRef="69290"/></ClipTrackItem></VideoClipTrackItem>
  <SubClip ObjectID="69290" ClassID="sc" Version="6"><Clip ObjectRef="101150"/><MasterClip ObjectURef="9b0363ba-2a3a-4206-ac09-20f6e5a1b399"/><Name>NESTED_SELECTS</Name></SubClip>
  <VideoClip ObjectID="101150" ClassID="vc" Version="11"><Clip Version="18"><Source ObjectRef="5090"/><InPoint>127008000000</InPoint><OutPoint>508032000000</OutPoint></Clip></VideoClip>
  <VideoSequenceSource ObjectID="5090" ClassID="ss" Version="3"><SequenceSource Version="4"><Content Version="10"/><Sequence ObjectURef="2b0665a8-e73d-4b91-82f2-d130a2cd9c32"/></SequenceSource><OriginalDuration>9420701976000000</OriginalDuration></VideoSequenceSource>
  <AudioClipTrack ObjectUID="aa2d4adc-1632-4dec-afaf-183607bd663b" ClassID="at" Version="1"><ClipTrack Version="1"><ClipItems Version="1"><TrackItems Version="1"><TrackItem Index="0" ObjectRef="50287"/></TrackItems></ClipItems></ClipTrack></AudioClipTrack>
  <VideoClipTrackItem ObjectID="50187" ClassID="ci" Version="1"><ClipTrackItem Version="8"><TrackItem Version="4"><End>2032128000000</End></TrackItem><SubClip ObjectRef="69268"/></ClipTrackItem></VideoClipTrackItem>
  <VideoClipTrackItem ObjectID="50188" ClassID="ci" Version="1"><ClipTrackItem Version="8"><TrackItem Version="4"><Start>2032128000000</Start><End>2540160000000</End></TrackItem><SubClip ObjectRef="69270"/></ClipTrackItem></VideoClipTrackItem>
  <AudioClipTrackItem ObjectID="50287" ClassID="ci" Version="1"><ClipTrackItem Version="8"><TrackItem Version="4"><Start>2032128000000</Start><End>2540160000000</End></TrackItem><SubClip ObjectRef="69270"/></ClipTrackItem></AudioClipTrackItem>
  <SubClip ObjectID="69268" ClassID="sc" Version="6"><Clip ObjectRef="101126"/><MasterClip ObjectURef="897fc7cf-a22c-4759-a6e2-0adeea00c0d1"/><Name>Universal Counting Leader</Name></SubClip>
  <SubClip ObjectID="69270" ClassID="sc" Version="6"><Clip ObjectRef="101129"/><MasterClip ObjectURef="9b0363ba-2a3a-4206-ac09-20f6e5a1b360"/><Name>BLACK_02</Name></SubClip>
  <VideoClip ObjectID="101126" ClassID="vc" Version="11"><Clip Version="18"><Source ObjectRef="5078"/><OutPoint>2032128000000</OutPoint></Clip></VideoClip>
  <VideoClip ObjectID="101129" ClassID="vc" Version="11"><Clip Version="18"><Source ObjectRef="5079"/><InPoint>2296728000000</InPoint><OutPoint>2804760000000</OutPoint></Clip></VideoClip>
  <VideoMediaSource ObjectID="5078" ClassID="ms" Version="1"><MediaSource Version="4"><Media ObjectURef="1bd72032-c2ce-49e8-833a-ecc000e12508"/></MediaSource></VideoMediaSource>
  <VideoMediaSource ObjectID="5079" ClassID="ms" Version="1"><MediaSource Version="4"><Media ObjectURef="0bd72032-c2ce-49e8-833a-ecc000e12509"/></MediaSource></VideoMediaSource>
  <Media ObjectUID="1bd72032-c2ce-49e8-833a-ecc000e12508" ClassID="m" Version="1"><FilePath>/Volumes/RAID/leader.mov</FilePath></Media>
  <Media ObjectUID="0bd72032-c2ce-49e8-833a-ecc000e12509" ClassID="m" Version="1"><ActualMediaFilePath>/Volumes/RAID/Arrow S16mm 78E 4K 0821.mp4</ActualMediaFilePath></Media>
  <MasterClip ObjectUID="897fc7cf-a22c-4759-a6e2-0adeea00c0d1" ClassID="mc" Version="1"><Name>Universal Counting Leader</Name></MasterClip>
  <MasterClip ObjectUID="9b0363ba-2a3a-4206-ac09-20f6e5a1b360" ClassID="mc" Version="1"><Name>BLACK_02</Name></MasterClip>
</PremiereData>`;
const PRPROJ_REAL = path.join(os.tmpdir(), `prproj-real-shape-${process.pid}.prproj`);
fs.writeFileSync(PRPROJ_REAL, zlib.gzipSync(Buffer.from(REAL_SHAPE_XML, 'utf8')));

test('parsePrproj walks the real Premiere 2025 shape: UID/URef graph, TrackGroups, ClipTrackItem chain, omitted zeros (E132)', () => {
  const seqs = listPrprojSequences(PRPROJ_REAL);
  assert.deepEqual(seqs.map((s) => [s.name, s.eventCount]).sort(), [['NESTED_SELECTS', 2], ['REAL_REEL', 5]]);
  const doc = parsePrprojDoc(PRPROJ_REAL);
  const ev = doc.sequences.find((s) => s.name === 'REAL_REEL').events;
  // The nested sequence (leader 0-24, then the Arrow clip 24-48 from src 217) is used from its
  // frame 12 for 36 frames at record 240: leader frames 12-24 → 240-252, Arrow → 252-276 (E133).
  assert.deepEqual(ev.map((e) => [e.track, e.source, e.srcIn, e.srcOut, e.recIn, e.recOut, e.fromCompound || null]), [
    ['V', 'leader.mov', 0, 192, 0, 192, null],
    ['V', 'Arrow S16mm 78E 4K 0821.mp4', 217, 265, 192, 240, null],
    ['V', 'leader.mov', 60, 72, 240, 252, 'NESTED_SELECTS'],
    ['V', 'Arrow S16mm 78E 4K 0821.mp4', 217, 265, 252, 276, 'NESTED_SELECTS'],
    ['A', 'Arrow S16mm 78E 4K 0821.mp4', 217, 265, 192, 240, null],
  ]);
  assert.equal(doc.sequences.find((s) => s.name === 'REAL_REEL').fps, 24);
});
