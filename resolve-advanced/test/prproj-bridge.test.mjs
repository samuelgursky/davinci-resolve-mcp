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
