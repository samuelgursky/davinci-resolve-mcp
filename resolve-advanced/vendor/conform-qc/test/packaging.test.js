'use strict';

/** Package builder + emitters + delivery — client-free (round-trips through own parser). */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const pkgRoot = require('../index');
const P = require('../packaging');
const { toOtio, readOtioSourceFrames } = require('../packaging/otio');
const { toFcp7Xml, fcp7TimecodeCoverage, pathToUrl, tcToFrames, framesToTc } = require('../packaging/emit-fcp7');
const { toAafModel, readAafSourceFrames } = require('../packaging/emit-aaf');
const { parseGeometry } = require('../parse');
const oracle = require('../oracle');

// The golden-answer reel is git-ignored client material (see index.js reelFixtureDir),
// so on a fresh clone it is absent and the tests that need it SKIP. Loading it at module
// scope made the whole file fail to load instead — which took the fixture-free tests
// below down with it, and those are exactly the ones that pin the importer contracts.
const GOLDEN_PATH = path.join(pkgRoot.reelFixtureDir(), 'golden_oracle.json');
const GOLDEN = fs.existsSync(GOLDEN_PATH) ? JSON.parse(fs.readFileSync(GOLDEN_PATH, 'utf8')) : null;
const needsGolden = { skip: GOLDEN ? false : 'golden reel fixture not present' };

// A conformed timeline: each clip resolved to its source frame (= expected_source_start).
const CONFORMED = GOLDEN && {
  sequence: GOLDEN.sequence,
  ticksPerFrame: GOLDEN.ticksPerFrame,
  clips: GOLDEN.clips.map((c) => ({
    cutId: `seq${c.seqstart}`,
    seqstart: c.seqstart,
    seqend: c.seqend,
    sourceFrame: c.expected_source_start,
    sampleFrame: c.expected_sample_frame != null ? c.expected_sample_frame : c.expected_source_start,
    scale: c.expected_scale_corrected,
    source_basename: c.source_basename,
    srcW: c.srcW,
    srcH: c.srcH,
    path: `/vol/online/${c.source_basename}`,
  })),
};
const CTX = GOLDEN && { ticksPerFrame: GOLDEN.ticksPerFrame, sequenceWidth: GOLDEN.sequence.width };

test('package: OTIO canonical round-trips conformed source frames (all 327)', needsGolden, () => {
  const otio = toOtio(CONFORMED);
  const back = readOtioSourceFrames(otio);
  assert.equal(back.length, 327);
  for (let i = 0; i < back.length; i++) assert.equal(back[i].sourceFrame, CONFORMED.clips[i].sourceFrame);
});

test('package: FCP7 XML emit round-trips through the parser (in+ticks consistent, all 327)', needsGolden, () => {
  const xml = toFcp7Xml(CONFORMED);
  const parsed = parseGeometry(xml);
  const bySeq = new Map(parsed.clips.map((c) => [c.seqstart, c]));
  let checked = 0;
  for (const c of CONFORMED.clips) {
    const pc = bySeq.get(c.seqstart);
    assert.ok(pc, `emitted clip @${c.seqstart} must re-parse`);
    // The non-negotiable: <in> and <pproTicksIn> are consistent, so the Oracle
    // re-derives the SAME source frame from the emitted XML.
    assert.equal(oracle.derive(pc, CTX).derivedSourceFrame, c.sourceFrame, `@${c.seqstart} round-trip`);
    checked += 1;
  }
  assert.equal(checked, 327);
});

test('package: AAF model round-trips source frames (binary serialization deferred)', needsGolden, () => {
  const back = readAafSourceFrames(toAafModel(CONFORMED));
  assert.equal(back.length, 327);
  assert.equal(back[0].sourceFrame, CONFORMED.clips[0].sourceFrame);
});

test('package: builder matrix — subset of formats + relink media mode', needsGolden, () => {
  const pkg = P.buildPackage(CONFORMED, { mediaMode: 'relink', formats: ['otio', 'fcp7Xml', 'aaf'] });
  assert.ok(pkg.files.otio && pkg.files.fcp7Xml && pkg.files.aaf);
  assert.equal(pkg.media.mode, 'relink');
  assert.equal(pkg.media.copied, false);
  assert.ok(pkg.media.references.length === 327);
});

test('package: full/consolidate media modes are BLOCKED (require volumes)', needsGolden, () => {
  assert.equal(P.buildPackage(CONFORMED, { mediaMode: 'full' }).media.blocked, true);
  assert.equal(P.buildPackage(CONFORMED, { mediaMode: 'consolidate' }).media.blocked, true);
});

test('package: V2 flag track + provenance manifest + ConformPackage record', needsGolden, () => {
  const v2Flags = [{ cutId: 'seq2983', klass: 'wrong-source', note: 'flagged' }];
  const repairByCut = { seq192: { strategy: 'add-subclip-startoffset', confidence: 1 } };
  const pkg = P.buildPackage(CONFORMED, { formats: ['otio'], v2Flags, repairByCut });
  assert.equal(pkg.v2FlagTrack.length, 1);
  assert.equal(pkg.manifest.clips.length, 327);
  const m192 = pkg.manifest.clips.find((c) => c.cutId === 'seq192');
  assert.equal(m192.repairStrategy, 'add-subclip-startoffset');
  assert.equal(pkg.record.type, 'ConformPackage');
  assert.equal(pkg.record.v2FlagCount, 1);
});

test('package: gated auto-apply applies only auto-apply fixes + records undo', needsGolden, () => {
  const small = { sequence: GOLDEN.sequence, ticksPerFrame: GOLDEN.ticksPerFrame, clips: [
    { cutId: 'a', seqstart: 0, sourceFrame: 100, scale: 175 },
    { cutId: 'b', seqstart: 48, sourceFrame: 200, scale: 175 },
  ] };
  const repairResults = [
    { cutId: 'a', repair: { mode: 'auto-apply', strategy: 'normalize-scale', proposal: { fix: { scale: 100 } } } },
    { cutId: 'b', repair: { mode: 'propose-only', strategy: 'find-true-source', proposal: { fix: { scale: 999 } } } },
  ];
  const out = P.applyGatedAutoApply(small, repairResults);
  assert.equal(out.conformed.clips.find((c) => c.cutId === 'a').scale, 100); // auto-applied
  assert.equal(out.conformed.clips.find((c) => c.cutId === 'b').scale, 175); // NOT applied (propose-only)
  assert.equal(out.applied.length, 1);
  assert.equal(out.undo[0].before.scale, 175); // undo records the prior value
  assert.equal(out.deferred[0].cutId, 'b');
});

test('package: delivery to a local folder writes the files', needsGolden, () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cqc-pkg-'));
  try {
    const pkg = P.buildPackage(CONFORMED, { formats: ['otio', 'fcp7Xml'], v2Flags: [{ cutId: 'x' }] });
    const written = P.deliverToFolder(pkg, dir);
    assert.ok(written.some((p) => p.endsWith('conform.otio.json')));
    assert.ok(written.some((p) => p.endsWith('conform.xml')));
    assert.ok(written.some((p) => p.endsWith('manifest.json')));
    assert.ok(fs.existsSync(path.join(dir, 'v2-flags.json')));
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('package: delivery to Download Center enqueues keys via injected sink (mock R2)', needsGolden, async () => {
  const uploaded = {};
  const enqueue = async (key, content) => { uploaded[key] = content; };
  const pkg = P.buildPackage(CONFORMED, { formats: ['otio'] });
  const keys = await P.deliverToDownloadCenter(pkg, { enqueue });
  assert.ok(keys.includes('conform/otio'));
  assert.ok(keys.includes('conform/manifest.json'));
  assert.equal(Object.keys(uploaded).length, keys.length);
});

// ---------------------------------------------------------------------------
// Resolve 19.1.3 importer contracts. Both failures are SILENT — a clean-looking
// XML and a Resolve that does nothing — so they are pinned here rather than left
// to be rediscovered. Fixture-free on purpose: these must run on a fresh clone.
// ---------------------------------------------------------------------------

// One clip whose media path has a space in two different segments, carrying an
// embedded start timecode of 01:00:00:00 @ 24.
const TC_CONFORMED = {
  sequence: { name: 'tc', width: 1920, height: 1080, fps: 24 },
  ticksPerFrame: 10584000000,
  clips: [{
    cutId: 'a',
    seqstart: 0,
    seqend: 48,
    sourceFrame: 86400,
    source_basename: 'take 01.mov',
    path: '/Volumes/Media Drive/A Roll/take 01.mov',
    startTc: '01:00:00:00',
    startTcFps: 24,
  }],
};

test('U7: pathurl is percent-encoded PER SEGMENT — %20 for spaces, / separators intact', () => {
  // Measured on 19.1.3: a raw space survives, but a raw '%' is an invalid escape and
  // kills THE WHOLE IMPORT. Encode everything rather than betting on the tolerated set.
  assert.equal(
    pathToUrl('/Volumes/Media Drive/A Roll/take 01.mov'),
    'file://localhost/Volumes/Media%20Drive/A%20Roll/take%2001.mov',
  );
  // Encoding the path in ONE pass would have produced %2F separators — the bug that
  // makes "just percent-encode it" fail differently instead of working.
  assert.equal(pathToUrl('/a b/c d').includes('%2F'), false);
  // The fatal one: a literal '%' must become %25, or the URL carries an invalid escape
  // and Resolve creates no timeline at all.
  assert.equal(pathToUrl('/vol/take%03.mov'), 'file://localhost/vol/take%2503.mov');

  const xml = toFcp7Xml(TC_CONFORMED);
  const url = xml.match(/<pathurl>([^<]*)<\/pathurl>/)[1];
  assert.equal(url, 'file://localhost/Volumes/Media%20Drive/A%20Roll/take%2001.mov');
  assert.equal(/<pathurl>[^<]* /.test(xml), false, 'no raw space survives inside a pathurl');
});

test('U8: every file def carries a <timecode> block MATCHING the media embedded TC', () => {
  // Absent, zero, and wrong all silently reject THE ENTIRE IMPORT (measured, 19.1.3).
  const xml = toFcp7Xml(TC_CONFORMED);
  const block = xml.match(/<timecode>[\s\S]*?<\/timecode>/);
  assert.ok(block, 'a file def with known media TC emits a <timecode> block');
  assert.match(block[0], /<string>01:00:00:00<\/string>/);
  assert.match(block[0], /<frame>86400<\/frame>/);   // 01:00:00:00 @ 24
  assert.match(block[0], /<displayformat>NDF<\/displayformat>/);
  assert.match(block[0], /<timebase>24<\/timebase>/);
  // It lives INSIDE the <file> def, not at sequence level.
  assert.match(xml, /<file id="file-1">[\s\S]*?<timecode>[\s\S]*?<\/timecode>[\s\S]*?<\/file>/);
  // Not the zero block that reads as present and imports as nothing.
  assert.equal(/<string>00:00:00:00<\/string>/.test(xml), false);
});

test('U8: startTcFrame and startTc agree; the frame wins and the string is re-derived', () => {
  const byFrame = toFcp7Xml({ ...TC_CONFORMED, clips: [{ ...TC_CONFORMED.clips[0], startTc: undefined, startTcFrame: 86400 }] });
  assert.match(byFrame, /<string>01:00:00:00<\/string>/);
  assert.match(byFrame, /<frame>86400<\/frame>/);
  // A disagreeing pair cannot emit a half-right block: the frame is authoritative.
  const both = toFcp7Xml({ ...TC_CONFORMED, clips: [{ ...TC_CONFORMED.clips[0], startTc: '05:00:00:00', startTcFrame: 86400 }] });
  assert.match(both, /<string>01:00:00:00<\/string>/);
});

test('U8: drop-frame media emits a DF block with the drop-frame frame count', () => {
  const df = toFcp7Xml({
    ...TC_CONFORMED,
    clips: [{ ...TC_CONFORMED.clips[0], startTc: '01:00:00;00', startTcFps: 29.97, startTcDrop: true }],
  });
  assert.match(df, /<string>01:00:00;00<\/string>/);
  assert.match(df, /<frame>107892<\/frame>/); // DF, not the 108000 an NDF count would give
  assert.match(df, /<displayformat>DF<\/displayformat>/);
  assert.match(df, /<ntsc>TRUE<\/ntsc>/);
});

test('U8: a clip with NO media timecode emits no block and is REPORTED, not guessed', () => {
  // A wrong block is exactly as fatal as no block, so the emitter never invents one —
  // it says which clips it could not write, and that the XML will import nothing.
  const noTc = { ...TC_CONFORMED, clips: [{ ...TC_CONFORMED.clips[0], startTc: undefined, startTcFps: undefined }] };
  const xml = toFcp7Xml(noTc);
  assert.equal(/<timecode>/.test(xml), false);
  const cov = fcp7TimecodeCoverage(noTc);
  assert.equal(cov.total, 1);
  assert.equal(cov.withTimecode, 0);
  assert.equal(cov.importable, false);
  assert.equal(cov.missing[0].name, 'take 01.mov');

  const ok = fcp7TimecodeCoverage(TC_CONFORMED);
  assert.equal(ok.withTimecode, 1);
  assert.equal(ok.importable, true);
  assert.deepEqual(ok.missing, []);
});

test('U8: buildPackage carries the timecode coverage alongside the fcp7 XML', () => {
  const pkg = P.buildPackage(TC_CONFORMED, { formats: ['fcp7Xml'] });
  assert.equal(pkg.fcp7Timecode.importable, true);
  assert.equal(pkg.fcp7Timecode.withTimecode, 1);
  // Not attached when no fcp7 XML was asked for.
  assert.equal(P.buildPackage(TC_CONFORMED, { formats: ['otio'] }).fcp7Timecode, undefined);
});

test('U8: timecode <-> frame conversion is exact, non-drop and drop', () => {
  for (const [tc, fps] of [['01:00:00:00', 24], ['00:59:50:00', 24], ['10:00:00:00', 25], ['23:59:59:23', 24]]) {
    assert.equal(framesToTc(tcToFrames(tc, fps, false), fps, false), tc, `${tc} @${fps}`);
  }
  assert.equal(tcToFrames('01:00:00;00', 29.97, true), 107892);
  assert.equal(tcToFrames('00:10:00;00', 29.97, true), 17982);
  assert.equal(tcToFrames('00:01:00;02', 29.97, true), 1800);
  for (const f of [0, 1800, 17981, 17982, 107892]) {
    assert.equal(tcToFrames(framesToTc(f, 29.97, true), 29.97, true), f, `DF frame ${f}`);
  }
});

test('emit: the SEQUENCE carries its own <rate> — without it Resolve creates no timeline', () => {
  // Bisected against Resolve's own FCP7 export on 19.1.3: the sequence <rate> was the
  // single element that flipped this emitter's output from "no timeline" to 2 items /
  // 2 linked. <duration> alone did not, and the clipitem/file <duration>/<rate>/<enabled>
  // that Resolve's exporter writes were not required.
  const xml = toFcp7Xml(TC_CONFORMED);
  const head = xml.slice(0, xml.indexOf('<media>'));
  assert.match(head, /<rate><timebase>24<\/timebase><ntsc>FALSE<\/ntsc><\/rate>/);
  assert.match(head, /<duration>48<\/duration>/);
  // A sequence start timecode rides at sequence level when the caller supplies one.
  const withTc = toFcp7Xml({ ...TC_CONFORMED, sequence: { ...TC_CONFORMED.sequence, startTc: '00:59:50:00' } });
  assert.match(withTc.slice(0, withTc.indexOf('<media>')), /<string>00:59:50:00<\/string>/);
  // 23.976 is the fractional case: NTSC must read TRUE, timebase must round to 24.
  const ntsc = toFcp7Xml({ ...TC_CONFORMED, sequence: { ...TC_CONFORMED.sequence, fps: 23.976 } });
  assert.match(ntsc.slice(0, ntsc.indexOf('<media>')), /<timebase>24<\/timebase><ntsc>TRUE<\/ntsc>/);
});
