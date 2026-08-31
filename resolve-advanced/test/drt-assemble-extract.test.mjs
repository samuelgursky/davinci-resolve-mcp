// Native-schema DRT authoring (measured live on Studio 19.1.3.7):
// drt.assemble splices real Resolve template structures into an archive
// ImportTimelineFromFile accepts; extract_from_drp keeps the importable-.drt
// recipe — project.xml + MediaPool + ORIGINAL SeqContainer path, other
// timelines' MpFolder blocks removed, Gallery dropped.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import JSZip from 'jszip';
import { drtTool } from '../server/lib.mjs';
import { createRequire } from 'node:module';

const tmp = (ext) => path.join(os.tmpdir(), `drtns-${Math.random().toString(36).slice(2)}${ext}`);

test('assemble writes a native archive with the requested version stamps', async () => {
  const out = tmp('.drt');
  const res = await drtTool.handler({ action: 'assemble', args: {
    outputPath: out, targetAppVersion: '19.1',
    spec: { timelineName: 'T', elements: [
      { type: 'title', track: 1, startFrame: 86400, durationFrames: 48, text: 'X' },
    ]},
  }});
  assert.equal(res.stamped.targetProjectVersion, 14);
  assert.ok(res.stamped.elementPatches >= 1);
  const zip = await JSZip.loadAsync(await fs.readFile(out));
  const names = Object.keys(zip.files).filter((n) => !zip.files[n].dir);
  assert.ok(names.includes('project.xml'));
  assert.ok(names.some((n) => n.startsWith('MediaPool/')));
  assert.ok(names.some((n) => /^SeqContainer\//.test(n)), 'original-path container');
  const pj = await zip.file('project.xml').async('string');
  assert.match(pj, /<ProjectVersion>14<\/ProjectVersion>/);
  assert.match(pj, /DbPrjVer="14"/);
  // native schema, not the flat template ImportTimelineFromFile refuses
  const seqName = names.find((n) => /^SeqContainer\//.test(n));
  const seq = await zip.file(seqName).async('string');
  assert.doesNotMatch(seq, /<StartFrame>/);
  await fs.unlink(out);
});

test('assemble without targetAppVersion keeps the template stamps', async () => {
  const out = tmp('.drt');
  const res = await drtTool.handler({ action: 'assemble', args: {
    outputPath: out,
    spec: { elements: [{ type: 'generator', track: 1, startFrame: 86400, durationFrames: 24 }] },
  }});
  assert.equal(res.stamped, null);
  await fs.unlink(out);
});

test('extract keeps the recipe and drops the other timeline block', async () => {
  const alpha = 'aaaaaaaa-1111-2222-3333-444444444444';
  const beta = 'bbbbbbbb-1111-2222-3333-444444444444';
  const container = (id) =>
    `<?xml version="1.0"?><Sm2SequenceContainer DbId="c"><VideoTrackVec><Element>` +
    `<Sm2TiTrack DbId="t"><Sequence>${id}</Sequence></Sm2TiTrack></Element></VideoTrackVec></Sm2SequenceContainer>`;
  const mp =
    '<Sm2MpFolder>' +
    `<Element><Sm2MpTimelineClip DbId="a"><Name>ALPHA</Name><Id>${alpha}</Id></Sm2MpTimelineClip></Element>` +
    `<Element><Sm2MpTimelineClip DbId="b"><Name>BETA</Name><Id>${beta}</Id></Sm2MpTimelineClip></Element>` +
    '</Sm2MpFolder>';
  const zip = new JSZip();
  zip.file('project.xml', '<SM_Project/>');
  zip.file('MediaPool/Master/MpFolder.xml', mp);
  zip.file('SeqContainer/aaaa.xml', container(alpha));
  zip.file('SeqContainer/bbbb.xml', container(beta));
  zip.file('Gallery.xml', '<g/>');
  const src = tmp('.drp');
  await fs.writeFile(src, await zip.generateAsync({ type: 'nodebuffer' }));
  const out = tmp('.drt');
  const res = await drtTool.handler({ action: 'extract_from_drp', args: {
    drpPath: src, outputPath: out, timelineIndex: 0 }});
  assert.equal(res.droppedTimelines, 1);
  const outZip = await JSZip.loadAsync(await fs.readFile(out));
  const names = Object.keys(outZip.files).filter((n) => !outZip.files[n].dir);
  assert.ok(names.includes('SeqContainer/aaaa.xml'), 'original path kept');
  assert.ok(!names.includes('SeqContainer/bbbb.xml'));
  assert.ok(!names.includes('Gallery.xml'));
  const folder = await outZip.file('MediaPool/Master/MpFolder.xml').async('string');
  assert.match(folder, /ALPHA/);
  assert.doesNotMatch(folder, /BETA/, 'ghost timeline block removed');
  await fs.unlink(src);
  await fs.unlink(out);
});

test('generator kind selection lands in the seq XML; title-only warning gate', async () => {
  // Kind swap render-verified on 19.1.3.7: SMPTE Color Bar YAVG 104.9,
  // Grey Scale 125.1, Solid Color 16 — plain Sm2TiGenerator, no Fusion comp,
  // so the byte-keyed comp-cache law does not apply and no warning is due.
  const out = tmp('.drt');
  const res = await drtTool.handler({ action: 'assemble', args: {
    outputPath: out, targetAppVersion: '19.1.3',
    spec: { elements: [
      { type: 'generator', generatorName: 'SMPTE Color Bar', track: 2, startFrame: 86400, durationFrames: 32 },
      { type: 'generator', generatorName: 'Grey Scale', track: 2, startFrame: 86440, durationFrames: 32 },
    ]},
  }});
  assert.equal(res.elementsWarning, undefined, 'generator-only pre-21 spec must not warn');
  const zip = await JSZip.loadAsync(await fs.readFile(out));
  const seqName = Object.keys(zip.files).find((n) => !zip.files[n].dir && /^SeqContainer\//.test(n));
  const seq = await zip.file(seqName).async('string');
  assert.match(seq, /<PrettyType>SMPTE Color Bar<\/PrettyType>/);
  assert.match(seq, /<PrettyType>Grey Scale<\/PrettyType>/);
  await fs.unlink(out);

  const out2 = tmp('.drt');
  const res2 = await drtTool.handler({ action: 'assemble', args: {
    outputPath: out2, targetAppVersion: '19.1.3',
    spec: { elements: [{ type: 'title', track: 1, startFrame: 86400, durationFrames: 24 }] },
  }});
  assert.match(res2.elementsWarning || '', /byte|cache|set_title_text/i, 'pre-21 title spec must warn');
  await fs.unlink(out2);
});

test('spec.startFrame patches MediaExtents and moves the origin guard', async () => {
  const out = tmp('.drt');
  const res = await drtTool.handler({ action: 'assemble', args: {
    outputPath: out, targetAppVersion: '19.1.3',
    spec: { timelineName: 'STC', startFrame: 86208, media: {
      mediaFilePath: '/m/a.mp4', spec: { width: 640, height: 360, frameCount: 480, fps: 24 },
      cuts: [{ startFrame: 86208, durationFrames: 48, srcIn: 0 }],
    } },
  }});
  assert.equal(res.startFrame, 86208);
  const zip = await JSZip.loadAsync(await fs.readFile(out));
  const mp = await zip.file('MediaPool/Master/MpFolder.xml').async('string');
  const tl = mp.match(/<Sm2MpTimelineClip[\s\S]*?<\/Sm2MpTimelineClip>/g).find((b) => b.includes('<Name>STC</Name>'));
  const me = Buffer.from(tl.match(/<MediaExtents>([0-9a-fA-F]*)<\/MediaExtents>/)[1], 'hex');
  assert.equal(me.readDoubleLE(0), 86208 / 24);
  assert.equal(me.readDoubleLE(8), 48 / 24);
  await fs.unlink(out);
  // a cut before the custom origin still refuses
  await assert.rejects(drtTool.handler({ action: 'assemble', args: {
    outputPath: tmp('.drt'),
    spec: { startFrame: 86208, media: { mediaFilePath: '/m/a.mp4', spec: { width: 640, height: 360, frameCount: 480, fps: 24 },
      cuts: [{ startFrame: 86000, durationFrames: 24 }] } },
  }}), /before the timeline origin 86208/);
});

test('spec.markers encode byte-exact and attach to the sequence owner', async () => {
  const requireC = createRequire(import.meta.url);
  const { encodeTimelineMarkersBlob, decodeTimelineMarkersBlob, MARKER_COLOR_BITS } =
    requireC('../vendor/drp-format/timeline-markers-blob.js');
  // Fixture: the Sm2SequenceLockableBlob FieldsBlob Resolve 19.1.3.7 itself
  // wrote for two markers (harvested via the marker API + ExportProject).
  const harvest = Buffer.from(
    (await fs.readFile(new URL('./fixtures-r19-markers-2.hex', import.meta.url), 'utf8')).trim(), 'hex');
  const dec = decodeTimelineMarkersBlob(harvest);
  assert.equal(dec.length, 2);
  assert.deepEqual(dec.map((m) => [m.frame, m.color, m.name]), [[60, 'Red', 'MK_BETA'], [24, 'Blue', 'MK_ALPHA']]);
  assert.ok(encodeTimelineMarkersBlob(dec).equals(harvest), 'byte-exact re-encode');
  assert.equal(Object.keys(MARKER_COLOR_BITS).length, 16);

  const out = tmp('.drt');
  const res = await drtTool.handler({ action: 'assemble', args: {
    outputPath: out, targetAppVersion: '19.1.3',
    spec: { timelineName: 'MRK', media: {
      mediaFilePath: '/m/a.mp4', spec: { width: 640, height: 360, frameCount: 480, fps: 24 },
      cuts: [{ startFrame: 86400, durationFrames: 96 }],
    }, markers: [{ frame: 86424, color: 'Red', name: 'A', note: 'n', duration: 12 }] },
  }});
  const zip = await JSZip.loadAsync(await fs.readFile(out));
  const pj = await zip.file('project.xml').async('string');
  const blk = pj.match(/<Sm2SequenceLockableBlob[\s\S]*?<\/Sm2SequenceLockableBlob>/);
  assert.ok(blk, 'lockable blob inserted');
  const owner = blk[0].match(/<BlobOwner>([0-9a-f-]{36})<\/BlobOwner>/)[1];
  const seqName = Object.keys(zip.files).find((n) => !zip.files[n].dir && /^SeqContainer\//.test(n));
  const seq = await zip.file(seqName).async('string');
  assert.ok(seq.includes(`<Sequence>${owner}</Sequence>`), 'owner is the Sm2Sequence id');
  const fb = Buffer.from(blk[0].match(/<FieldsBlob>([0-9a-fA-F]*)<\/FieldsBlob>/)[1], 'hex');
  const decoded = decodeTimelineMarkersBlob(fb);
  assert.deepEqual(decoded, [{ frame: 24, color: 'Red', note: 'n', duration: 12, name: 'A', customData: '' }]);
  await fs.unlink(out);
});

test('createRequire import for marker tests', () => { assert.ok(createRequire); });

test('subtitles author as plain Subtitle generators on a Type-2 track', async () => {
  // Harvested shape (19.1.3.7): Sm2TiGenerator, PrettyType Subtitle, TEXT in
  // <Name>, zero blobs — readback-verified live (3 cues at exact frames).
  const requireC2 = createRequire(import.meta.url);
  const { parseSrt } = requireC2('../vendor/drp-format/place-subtitles.js');
  const cues = parseSrt('1\n00:00:01,000 --> 00:00:02,500\nHello\n\n2\n00:00:03,000 --> 00:00:04,000\nWorld\n', 24);
  assert.deepEqual(cues, [
    { startFrame: 24, durationFrames: 36, text: 'Hello' },
    { startFrame: 72, durationFrames: 24, text: 'World' },
  ]);
  const out = tmp('.drt');
  const res = await drtTool.handler({ action: 'assemble', args: {
    outputPath: out, targetAppVersion: '19.1.3',
    spec: { timelineName: 'SUBS', media: {
      mediaFilePath: '/m/a.mp4', spec: { width: 640, height: 360, frameCount: 480, fps: 24 },
      cuts: [{ startFrame: 86400, durationFrames: 96 }],
    }, subtitlesSrt: '1\n00:00:01,000 --> 00:00:02,500\nA & B <i>styled</i>\n' },
  }});
  assert.ok(!res.error, res.error);
  const zip = await JSZip.loadAsync(await fs.readFile(out));
  const seqName = Object.keys(zip.files).find((n) => !zip.files[n].dir && /^SeqContainer\//.test(n));
  const seq = await zip.file(seqName).async('string');
  const vec = seq.match(/<SubtitleTrackVec>([\s\S]*?)<\/SubtitleTrackVec>/)[1];
  assert.match(vec, /<Type>2<\/Type>/);
  assert.match(vec, /<PrettyType>Subtitle<\/PrettyType>/);
  assert.match(vec, /<Name>A &amp; B &lt;i&gt;styled&lt;\/i&gt;<\/Name>/, 'text escaped in XML');
  assert.match(vec, /<Start>86424<\/Start>/);
  await fs.unlink(out);
  // overlapping cues refuse
  await assert.rejects(drtTool.handler({ action: 'assemble', args: {
    outputPath: tmp('.drt'),
    spec: { subtitles: [
      { startFrame: 86400, durationFrames: 48, text: 'a' },
      { startFrame: 86424, durationFrames: 24, text: 'b' },
    ], media: { mediaFilePath: '/m/a.mp4', spec: { width: 640, height: 360, frameCount: 480, fps: 24 }, cuts: [{ startFrame: 86400, durationFrames: 96 }] } },
  }}), /overlap — one subtitle track/);
});

test('extract keeps a compound clip\'s inner container, recursively', async () => {
  // A compound is a pool Sm2MpCompoundClip embedding an Sm2Sequence whose
  // tracks live in their OWN SeqContainer — the old recipe dropped it and
  // shipped a hollow compound (live-proven fix: E45/E46 render the inner
  // content on 19.1.3.7).
  const seqParent = 'aaaaaaaa-0000-0000-0000-000000000001';
  const seqInner = 'bbbbbbbb-0000-0000-0000-000000000002';
  const seqOther = 'cccccccc-0000-0000-0000-000000000003';
  const compoundId = 'dddddddd-0000-0000-0000-000000000004';
  const cont = (seqId, extra = '') =>
    `<?xml version="1.0"?><Sm2SequenceContainer DbId="c"><VideoTrackVec><Element>` +
    `<Sm2TiTrack DbId="t"><Sequence>${seqId}</Sequence><Items>${extra}</Items></Sm2TiTrack></Element></VideoTrackVec></Sm2SequenceContainer>`;
  const compoundItem = `<Element><Sm2TiVideoClip DbId="i"><Name>CMP</Name><MediaRef>${compoundId}</MediaRef></Sm2TiVideoClip></Element>`;
  const mp =
    '<Sm2MpFolder>' +
    `<Element><Sm2MpTimelineClip DbId="a"><Name>PARENT</Name><Id>${seqParent}</Id></Sm2MpTimelineClip></Element>` +
    `<Element><Sm2MpTimelineClip DbId="b"><Name>OTHER</Name><Id>${seqOther}</Id></Sm2MpTimelineClip></Element>` +
    `<Element><Sm2MpCompoundClip DbId="${compoundId}"><Name>CMP</Name><Sequence><Sm2Sequence DbId="${seqInner}"><FieldsBlob/></Sm2Sequence></Sequence></Sm2MpCompoundClip></Element>` +
    '</Sm2MpFolder>';
  const zip = new JSZip();
  zip.file('project.xml', '<SM_Project/>');
  zip.file('MediaPool/Master/MpFolder.xml', mp);
  zip.file('SeqContainer/aaaa.xml', cont(seqParent, compoundItem));
  zip.file('SeqContainer/bbbb.xml', cont(seqInner));
  zip.file('SeqContainer/cccc.xml', cont(seqOther));
  const src = tmp('.drp');
  await fs.writeFile(src, await zip.generateAsync({ type: 'nodebuffer' }));
  const out = tmp('.drt');
  const res = await drtTool.handler({ action: 'extract_from_drp', args: { drpPath: src, outputPath: out, timelineIndex: 0 } });
  const outZip = await JSZip.loadAsync(await fs.readFile(out));
  const names = Object.keys(outZip.files).filter((n) => !outZip.files[n].dir);
  assert.ok(names.includes('SeqContainer/aaaa.xml'), 'parent kept');
  assert.ok(names.includes('SeqContainer/bbbb.xml'), 'compound INNER container kept');
  assert.ok(!names.includes('SeqContainer/cccc.xml'), 'unrelated timeline still dropped');
  assert.equal(res.droppedTimelines, 1);
  await fs.unlink(src); await fs.unlink(out);
});

test('placeCompound rewires every cluster link — folder, SeqRef, Parent — and composes', async () => {
  // The three danglers that each CRASHED Resolve on import (measured E47-E50):
  // the pool element's <MpFolder>, the embedded blob's keyed SeqRef (the
  // inner container uuid), and the embedded sequence's <Parent> (the
  // compound's own id). With all three rewired, ids freshen safely and
  // MULTIPLE compounds compose (render-proven nested playback, both inner
  // edits, on 19.1.3.7).
  const requireC3 = createRequire(import.meta.url);
  const { placeCompound } = requireC3('../vendor/drp-format/place-compound.js');
  const { decodeKeyedDict } = requireC3('../vendor/drp-format/keyed-dict.js');
  const { addMediaClip } = requireC3('../vendor/drp-format/author-project.js');
  const base = await addMediaClip({
    mediaFile: '/m/a.mp4', spec: { width: 640, height: 360, frameCount: 480, fps: 24 }, templateVersion: 19,
  });
  const res = await placeCompound(base.buffer, { name: 'CMP', startFrame: 86400, durationFrames: 96 });
  const zip = await JSZip.loadAsync(res.buffer);
  const inner = await zip.file(`SeqContainer/${res.innerContainerId}.xml`).async('string');
  assert.match(inner, /<Items\/>/);
  assert.ok(inner.includes(`<Sequence>${res.innerSequenceId}</Sequence>`));
  const mp = await zip.file('MediaPool/Master/MpFolder.xml').async('string');
  const folderId = mp.match(/<Sm2MpFolder DbId="([^"]+)"/)[1];
  const cmp = mp.match(/<Sm2MpCompoundClip[\s\S]*?<\/Sm2MpCompoundClip>/)[0];
  assert.ok(cmp.includes(`<MpFolder>${folderId}</MpFolder>`), 'folder ref rewired');
  assert.ok(cmp.includes(`<Parent>${res.compoundId}</Parent>`), 'Parent rewired to the fresh compound id');
  const fb = cmp.match(/<Sm2Sequence DbId="[^"]+">\s*<FieldsBlob>([0-9a-fA-F]+)<\/FieldsBlob>/)[1];
  const seqRef = decodeKeyedDict(Buffer.from(fb, 'hex')).entries.find((e) => e.key === 'SeqRef');
  assert.equal(seqRef.value, res.innerContainerId, 'blob SeqRef patched to the fresh inner container');
  // a second compound composes with distinct identities
  const res2 = await placeCompound(res.buffer, { name: 'CMP2', startFrame: 86500, durationFrames: 24 });
  assert.notEqual(res2.compoundId, res.compoundId);
  const zip2 = await JSZip.loadAsync(res2.buffer);
  assert.ok(zip2.file(`SeqContainer/${res.innerContainerId}.xml`), 'first inner kept');
  assert.ok(zip2.file(`SeqContainer/${res2.innerContainerId}.xml`), 'second inner added');
});

test('subtitles and markers target the PINNED parent when compounds are present', async () => {
  // A compound's inner container also matches "first SeqContainer with a
  // VideoTrackVec", and entry listing is name-sorted by random uuid — so
  // pre-pin, cues (and the markers' BlobOwner) could land inside the
  // compound (measured live: the imported timeline had NO subtitle track).
  // The sort is a coin flip per assembly; several rounds pin the property.
  for (let i = 0; i < 6; i += 1) {
    const out = tmp('.drt');
    await drtTool.handler({ action: 'assemble', args: {
      outputPath: out, targetAppVersion: '19.1.3',
      spec: {
        timelineName: 'CMPSUB',
        media: { mediaFilePath: '/m/a.mp4', spec: { width: 640, height: 360, frameCount: 480, fps: 24 }, cuts: [{ startFrame: 86400, durationFrames: 96 }] },
        compounds: [{ name: 'CMP', startFrame: 86496, durationFrames: 24, cuts: [] }],
        subtitlesSrt: '1\n00:00:00,500 --> 00:00:01,500\nPinCue\n',
        markers: [{ frame: 86410, color: 'Blue', name: 'M' }],
      },
    }});
    const zip = await JSZip.loadAsync(await fs.readFile(out));
    const seqs = Object.keys(zip.files).filter((n) => !zip.files[n].dir && /^SeqContainer\//.test(n));
    assert.equal(seqs.length, 2, 'parent + compound inner');
    let parent = null;
    let inner = null;
    for (const n of seqs) {
      const xml = await zip.file(n).async('string');
      if (/<Name>CMP<\/Name>/.test(xml)) parent = xml;
      else inner = xml;
    }
    assert.ok(parent && inner, 'both containers identified');
    assert.match(parent, /<Name>PinCue<\/Name>/, 'cue in the PARENT container');
    assert.doesNotMatch(inner, /PinCue/, 'inner container has no cue');
    const pj = await zip.file('project.xml').async('string');
    // scope to the marker blob — the template carries other BlobOwner tags
    const blk = pj.match(/<Sm2SequenceLockableBlob[\s\S]*?<\/Sm2SequenceLockableBlob>/)[0];
    const owner = blk.match(/<BlobOwner>([0-9a-f-]{36})<\/BlobOwner>/)[1];
    const parentSeqId = parent.match(/<Sequence>([0-9a-f-]{36})<\/Sequence>/)[1];
    assert.equal(owner, parentSeqId, 'marker blob owned by the PARENT sequence');
    await fs.unlink(out);
  }
});

test('compound donor template carries SequenceSetup (the depth-2 render key)', async () => {
  // The historical depth-2-renders-black was ONE missing key: the embedded
  // Sm2Sequence FieldsBlob of a REAL compound (fresh 19.1.3.7 CreateCompoundClip
  // harvest, E55) carries a constant SequenceSetup blob (project format
  // descriptor) the old donor template lacked. With it, doubly nested content
  // renders (E56/E57: white 234 through two levels). Guard the template.
  const requireC4 = createRequire(import.meta.url);
  const { decodeKeyedDict } = requireC4('../vendor/drp-format/keyed-dict.js');
  const t = await fs.readFile(new URL('../vendor/drp-format/templates/compound-pool-r19.xml', import.meta.url), 'utf8');
  const fb = t.match(/<Sm2Sequence DbId="[^"]+">\s*<FieldsBlob>([0-9a-fA-F]+)/)[1];
  const keys = decodeKeyedDict(Buffer.from(fb, 'hex')).entries.map((e) => e.key);
  assert.ok(keys.includes('SequenceSetup'), `template blob keys: ${keys.join(',')}`);
  assert.ok(keys.includes('SeqRef'));
});

test('compounds nest recursively through the spec', async () => {
  const out = tmp('.drt');
  await drtTool.handler({ action: 'assemble', args: {
    outputPath: out, targetAppVersion: '19.1.3',
    spec: {
      timelineName: 'NEST',
      media: { mediaFilePath: '/m/a.mp4', spec: { width: 640, height: 360, frameCount: 480, fps: 24 }, cuts: [{ startFrame: 86400, durationFrames: 48 }] },
      compounds: [{ name: 'OUT', startFrame: 86448, durationFrames: 48, cuts: [],
        compounds: [{ name: 'INNER', startFrame: 0, durationFrames: 24, cuts: [] }] }],
    },
  }});
  const zip = await JSZip.loadAsync(await fs.readFile(out));
  const seqs = Object.keys(zip.files).filter((n) => !zip.files[n].dir && /^SeqContainer\//.test(n));
  assert.equal(seqs.length, 3, 'parent + OUT inner + INNER inner');
  let outContainer = null;
  for (const n of seqs) {
    const xml = await zip.file(n).async('string');
    if (/<Name>INNER<\/Name>/.test(xml)) outContainer = xml;
  }
  assert.ok(outContainer, 'the INNER compound item sits inside OUT\'s container');
  assert.doesNotMatch(outContainer, /<Name>OUT<\/Name>/, 'OUT\'s own item is in the PARENT, not its inner container');
  const mp = await zip.file('MediaPool/Master/MpFolder.xml').async('string');
  const compounds = mp.match(/<Sm2MpCompoundClip DbId="[^"]+">[\s\S]*?<\/Sm2MpCompoundClip>/g) || [];
  assert.equal(compounds.length, 2, 'both compounds pooled flat');
  await fs.unlink(out);
});
