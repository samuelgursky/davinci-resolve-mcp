/**
 * E139: a real Resolve 19.1.3.7 EXPORT_DRT walks into normalized events so two
 * timeline VERSIONS diff through turnover_changelist. Fixture mirrors the real
 * shape byte-for-byte where it matters: <Start>/<Duration>/<In> per clip, an
 * EMPTY <In/> on the audio clip, MediaTimemapBA tag 0x02 (linear) vs a keyed
 * curve (retime — undecoded), Sm2TiTransition AlignmentType 2 (centred) and 3
 * (ends at the cut, one-sided fade-in), and the pool Sm2Sequence carrying the
 * frame rate / MediaExtents / Resolution as little-endian doubles + BE uint64.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { drtEventsFromParsed, diffChangelist } from '../server/editorial.mjs';

const require = createRequire(import.meta.url);
const JSZip = require('jszip');
const { parseDRT } = require('../vendor/drt-format/drt-parser.js');

const LINEAR = '02409de1d555555555';
// Verbatim Sm2TimeMap blobs from a real 19.1.3.7 EXPORT_DRT (E140): an 80%
// constant retime (Premiere wrote speed 80 for the same cut), the Black Video
// generator's FREEZE (XMax 60000 sentinel, zero slope), and a truncated map
// the decoder cannot read.
const CURVE = '0000000100000007000000080059004d0069006e0000000600bff0000000000000000000080059004d006100780000000600bff0000000000000000000080058004d00610078000000060040a289eaaaaaaaab000000100055006e0069007100750065004900640000000a000000004800350064003500370063003800640063002d0061003500320037002d0034003500360030002d0061003200630035002d00330030003200320037003200310063003000350062006300000020004c00610073007400560061006c006900640059004f006600660073006500740000000600409da9800000000000000016004b00650079006600720061006d00650073004200410000000c0000000017800a000a1209abaaaaaaea89a240115655555555a99d400000000c0044006200540079007000650000000a00000000140053006d003200540069006d0065004d00610070';
const FREEZE = '0000000100000006000000080059004d0069006e0000000600bff0000000000000000000080059004d006100780000000600bff0000000000000000000080058004d00610078000000060040ed4c0000000000000000100055006e0069007100750065004900640000000a000000004800300039003100370062003600300063002d0038006600660036002d0034006600630030002d0062006200310034002d00620065003200350032003700350035006200630062006600000016004b00650079006600720061006d00650073004200410000000c000000000e800a000a090900000000004ced400000000c0044006200540079007000650000000a00000000140053006d003200540069006d0065004d00610070';
const BROKEN = '00000001000000070000000800';
const FPS24 = '00000000000038400000000000000000';
const vclip = (id, name, start, dur, inn, media, timemap = LINEAR) => `<Element><Sm2TiVideoClip DbId="${id}"><FieldsBlob/><PrettyType/><Name>${name}</Name><Start>${start}</Start><Duration>${dur}</Duration><Flags>0</Flags><EffectFiltersBA/><In>${inn}</In><MixedFrameRateAlignment>0</MixedFrameRateAlignment><MediaStartTime>0</MediaStartTime><MediaFilePath>${media}</MediaFilePath><MediaReelNumber/><MediaFrameRate>${FPS24}</MediaFrameRate><MediaTimemapBA>${timemap}</MediaTimemapBA></Sm2TiVideoClip></Element>`;
const trans = (id, start, dur, align, pos) => `<Element><Sm2TiTransition DbId="${id}"><FieldsBlob/><PrettyType>Cross Dissolve</PrettyType><Name/><Start>${start}</Start><Duration>${dur}</Duration><Flags>0</Flags><AlignmentType>${align}</AlignmentType><Position>${pos}</Position></Sm2TiTransition></Element>`;
const track = (id, type, items) => `<Element><Sm2TiTrack DbId="${id}"><FieldsBlob/><Type>${type}</Type><SubType>0</SubType><Flags>0</Flags><Sequence>seq-1</Sequence><Items>${items}</Items><FusionCompHolderItems/><UserDefinedName/><LayersVec/></Sm2TiTrack></Element>`;

function buildContainer({ bIn = 500, withDissolve = true } = {}) {
  return `<?xml version="1.0" encoding="UTF-8"?>
<!--DbAppVer="19.1.3.0007" DbPrjVer="14"-->
<Sm2SequenceContainer DbId="c1">
 <FieldsBlob/>
 <VideoTrackVec>
${track('t1', 0, [
    vclip('v1', 'Universal Counting Leader', 172608, 192, 72, ''),
    vclip('v2', 'A.mov', 172800, 164, 3159, '/Volumes/X/A.mov'),
    vclip('v3', 'B.mov', 172964, 100, bIn, '/Volumes/X/B.mov'),
    vclip('v4', 'C.mov', 173064, 48, 10, '/Volumes/X/C.mov', CURVE),
    vclip('v6', 'Black Video', 173112, 48, 86400, '', FREEZE),
    vclip('v7', 'E.mov', 173160, 24, 7, '/Volumes/X/E.mov', BROKEN),
    withDissolve ? trans('x1', 172941, 46, 2, 2) : '',
  ].join(''))}
${track('t2', 0, [vclip('v5', 'D.mov', 172700, 33, 0, '/Volumes/X/D.mov'), trans('x2', 172692, 8, 3, 1)].join(''))}
 </VideoTrackVec>
 <AudioTrackVec>
${track('t3', 1, `<Element><Sm2TiAudioClip DbId="a1"><FieldsBlob/><PrettyType/><Name>Mix.wav</Name><Start>172608</Start><Duration>600</Duration><Flags>0</Flags><In/><MediaStartTime>7184.8</MediaStartTime><MediaFilePath>/Volumes/X/Mix.wav</MediaFilePath><MediaFrameRate>0000000000003e400000000000000001</MediaFrameRate><MediaTimemapBA>02409817333333333300000000000000004098172aaaaaaaaa00000000000000004098173333333333</MediaTimemapBA></Sm2TiAudioClip></Element>`)}
 </AudioTrackVec>
 <SubtitleTrackVec/>
</Sm2SequenceContainer>`;
}
const MP_FOLDER = `<?xml version="1.0" encoding="UTF-8"?>
<Sm2MpFolder DbId="f1"><Name>Master</Name><Clips><Element><Sm2MpTimelineClip DbId="m1"><FieldsBlob/><Name>REEL_TEST</Name><Sm2Sequence DbId="seq-1"><FieldsBlob/><UniqueSequenceId>u1</UniqueSequenceId><MediaExtents>000000000018bc4000000000801d9840</MediaExtents><FrameRate>${FPS24}</FrameRate><Resolution>0000000000000e100000000000000870</Resolution><VideoTrackVec/><AudioTrackVec/></Sm2Sequence></Sm2MpTimelineClip></Element></Clips></Sm2MpFolder>`;

async function buildDrt(opts) {
  const zip = new JSZip();
  zip.file('project.xml', '<?xml version="1.0" encoding="UTF-8"?><SyProject DbId="p1"><Name>REEL_TEST</Name></SyProject>');
  zip.file('SeqContainer/86337e43-1eae-4901-a1b9-a8961094021a.xml', buildContainer(opts));
  zip.file('MediaPool/Master/MpFolder.xml', MP_FOLDER);
  return zip.generateAsync({ type: 'nodebuffer' });
}

test('parseDRT reads the real clip/transition fields and the pool sequence encodings (E139)', async () => {
  const parsed = await parseDRT(await buildDrt());
  const tl = parsed.timelines[0];
  assert.equal(tl.name, 'REEL_TEST');
  assert.equal(tl.kind, 'timeline');
  assert.equal(tl.frameRate, 24);
  assert.equal(tl.startFrame, 172608);
  assert.equal(tl.startTimecode, '01:59:52:00');
  assert.equal(tl.resolution, '3600x2160');
  const v1 = tl.videoTracks[0].clips;
  assert.deepEqual(v1.map((c) => [c.name, c.in, c.timemap.kind, c.mediaFrameRate]), [
    ['Universal Counting Leader', 72, 'linear', 24], ['A.mov', 3159, 'linear', 24], ['B.mov', 500, 'linear', 24], ['C.mov', 10, 'constant', 24],
    ['Black Video', 86400, 'freeze', 24], ['E.mov', 7, 'unknown', 24],
  ]);
  // E140: the decoded map — 0.8 ratio on the real 80% retime, the freeze sentinel, an unreadable map
  assert.equal(Math.round(v1[3].timemap.speed * 1000) / 1000, 0.8);
  assert.equal(v1[3].timemap.reverse, false);
  assert.equal(v1[4].timemap.speed, 0);
  assert.equal(v1[4].timemap.recordDurationSec, 60000);
  assert.equal(v1[5].timemap.speed, null);
  assert.deepEqual(tl.videoTracks[0].transitions.map((t) => [t.type, t.start, t.duration, t.alignmentType, t.alignment, t.position]), [['Cross Dissolve', 172941, 46, 2, 'center', 2]]);
  assert.deepEqual(tl.videoTracks[1].transitions.map((t) => [t.alignment, t.position]), [['end', 1]]);
  const a1 = tl.audioTracks[0].clips[0];
  assert.equal(a1.in, null, 'a real export writes an EMPTY <In/> on audio — null, not 0');
  assert.equal(a1.mediaStartTime, 7184.8);
  assert.equal(a1.mediaFrameRate, 30);
  assert.equal(a1.timemap.kind, 'linear-multi');
  assert.equal(a1.timemap.speed, 1);
});

test('drtEventsFromParsed walks one timeline into sequence-relative events with transitions, flags and lanes (E139)', async () => {
  const r = drtEventsFromParsed(await parseDRT(await buildDrt()));
  assert.equal(r.timeline, 'REEL_TEST');
  assert.equal(r.fps, 24);
  assert.equal(r.startFrame, 172608);
  assert.equal(r.startTimecode, '01:59:52:00');
  const rows = r.events.map((e) => [e.track, e.source, e.srcIn, e.srcOut, e.recIn, e.recOut, e.speed]);
  assert.deepEqual(rows, [
    ['V', 'Universal Counting Leader', 72, 264, 0, 192, 100],
    ['V', 'A.mov', 3159, 3323, 192, 356, 100],
    ['V', 'B.mov', 500, 600, 356, 456, 100],
    ['V', 'C.mov', 8, 46, 456, 504, 80],
    ['V', 'Black Video', 86400, 86400, 504, 552, 0],
    ['V', 'E.mov', 7, null, 552, 576, null],
    ['V2', 'D.mov', 0, 33, 92, 125, 100],
    ['V2', 'BL', 0, 0, 92, 92, 100],
    ['A', 'Mix.wav', 0, 600, 0, 600, 100],
  ]);
  const leader = r.events[0], b = r.events[2], c = r.events[3], frozen = r.events[4], broken = r.events[5], d = r.events[6], mix = r.events[8];
  assert.equal(leader.generatorName, 'Universal Counting Leader');
  assert.equal(leader.sourcePath, undefined);
  assert.equal(r.events[1].sourcePath, '/Volumes/X/A.mov');
  // the centred dissolve attaches to the INCOMING clip with its explicit span start
  assert.deepEqual(b.transition, { type: 'Cross Dissolve', duration: 46, recStart: 333, alignment: 'center' });
  assert.equal(r.events[1].transition, null);
  // E140/E143: the real 80% map decodes — <In> 10 is RECORD-domain, so the clip starts on source
  // frame round(10 × 0.8) = 8 and 48 record frames × 0.8 = 38 source frames end it at 46
  assert.equal(c.speed, 80);
  assert.equal(c.srcIn, 8);
  assert.equal(c.srcOut, 46);
  assert.equal(c.recordDomainIn, 10);
  assert.equal(c.reverse, false);
  assert.equal(c.retimeUnknown, undefined);
  assert.equal(b.recordDomainIn, undefined, 'a 100% clip has no record-domain In');
  // the freeze is the zero-speed in==out event every other parser emits
  assert.equal(frozen.speed, 0);
  assert.equal(frozen.srcOut, frozen.srcIn);
  assert.equal(frozen.generatorName, 'Black Video');
  // a map the decoder cannot read is never faked to 100%
  assert.equal(broken.speed, null);
  assert.equal(broken.srcOut, null);
  assert.equal(broken.retimeUnknown, true);
  // the one-sided fade-in (type 3, nothing outgoing) gets a zero-length BL leg
  assert.deepEqual(d.transition, { type: 'Cross Dissolve', duration: 8, recStart: 84, alignment: 'end' });
  assert.equal(mix.srcInAbsent, true);
  assert.equal(r.events.filter((e) => e.srcInAbsent).length, 1, 'only the empty <In/> is flagged');
});

test('two DRT versions diff through turnover_changelist: identical, a trim, a dropped dissolve (E139)', async () => {
  const base = drtEventsFromParsed(await parseDRT(await buildDrt())).events;
  const same = diffChangelist(base, drtEventsFromParsed(await parseDRT(await buildDrt())).events);
  assert.equal(same.shape, 'identical');
  assert.equal(same.retained, 8, 'eight cuts: the BL fade leg is a carrier, not a cut');
  const trimmed = diffChangelist(base, drtEventsFromParsed(await parseDRT(await buildDrt({ bIn: 512 }))).events);
  assert.equal(trimmed.shape, 'edit');
  assert.deepEqual(trimmed.counts, { trimmed: 1 });
  assert.deepEqual(trimmed.changes[0].deltas.src, { old: [500, 600], new: [512, 612] });
  const dropped = diffChangelist(base, drtEventsFromParsed(await parseDRT(await buildDrt({ withDissolve: false }))).events);
  assert.equal(dropped.shape, 'edit');
  assert.deepEqual(dropped.counts, { transition_dropped: 1 });
});

test('drtEventsFromParsed picks by name or index and refuses a name it cannot find (E139)', async () => {
  const parsed = await parseDRT(await buildDrt());
  assert.equal(drtEventsFromParsed(parsed, { timeline: 'REEL_TEST' }).events.length, 9);
  assert.equal(drtEventsFromParsed(parsed, { timeline: 0 }).events.length, 9);
  assert.throws(() => drtEventsFromParsed(parsed, { timeline: 'NOPE' }), /no timeline 'NOPE'/);
});

test('a retimed clip whose <In> was typed as a source frame reads as the earlier frame it really shows (E143)', async () => {
  // The bridge writes In = srcIn/speed (52682 for source 42145 at 80%); a hand conform that wrote 42145
  // straight into In shows source 33716. Same map, different In → different picture, and the reader says so.
  const zipA = await buildDrt(); const parsedA = await parseDRT(zipA);
  const cA = drtEventsFromParsed(parsedA).events.find((e) => e.source === 'C.mov');
  assert.equal(cA.srcIn, Math.round(cA.recordDomainIn * 0.8));
  const bridgeIn = Math.round(42145 / 0.8); // 52681
  assert.equal(Math.round(bridgeIn * 0.8), 42145, 'the bridge convention round-trips the source frame');
  assert.equal(Math.round(42145 * 0.8), 33716, 'the hand-typed value lands 8429 source frames early');
});
