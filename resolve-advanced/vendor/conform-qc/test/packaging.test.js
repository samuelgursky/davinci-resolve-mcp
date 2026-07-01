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
const { toFcp7Xml } = require('../packaging/emit-fcp7');
const { toAafModel, readAafSourceFrames } = require('../packaging/emit-aaf');
const { parseGeometry } = require('../parse');
const oracle = require('../oracle');

const GOLDEN = JSON.parse(fs.readFileSync(path.join(pkgRoot.reelFixtureDir(), 'golden_oracle.json'), 'utf8'));

// A conformed timeline: each clip resolved to its source frame (= expected_source_start).
const CONFORMED = {
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
const CTX = { ticksPerFrame: GOLDEN.ticksPerFrame, sequenceWidth: GOLDEN.sequence.width };

test('package: OTIO canonical round-trips conformed source frames (all 327)', () => {
  const otio = toOtio(CONFORMED);
  const back = readOtioSourceFrames(otio);
  assert.equal(back.length, 327);
  for (let i = 0; i < back.length; i++) assert.equal(back[i].sourceFrame, CONFORMED.clips[i].sourceFrame);
});

test('package: FCP7 XML emit round-trips through the parser (in+ticks consistent, all 327)', () => {
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

test('package: AAF model round-trips source frames (binary serialization deferred)', () => {
  const back = readAafSourceFrames(toAafModel(CONFORMED));
  assert.equal(back.length, 327);
  assert.equal(back[0].sourceFrame, CONFORMED.clips[0].sourceFrame);
});

test('package: builder matrix — subset of formats + relink media mode', () => {
  const pkg = P.buildPackage(CONFORMED, { mediaMode: 'relink', formats: ['otio', 'fcp7Xml', 'aaf'] });
  assert.ok(pkg.files.otio && pkg.files.fcp7Xml && pkg.files.aaf);
  assert.equal(pkg.media.mode, 'relink');
  assert.equal(pkg.media.copied, false);
  assert.ok(pkg.media.references.length === 327);
});

test('package: full/consolidate media modes are BLOCKED (require volumes)', () => {
  assert.equal(P.buildPackage(CONFORMED, { mediaMode: 'full' }).media.blocked, true);
  assert.equal(P.buildPackage(CONFORMED, { mediaMode: 'consolidate' }).media.blocked, true);
});

test('package: V2 flag track + provenance manifest + ConformPackage record', () => {
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

test('package: gated auto-apply applies only auto-apply fixes + records undo', () => {
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

test('package: delivery to a local folder writes the files', () => {
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

test('package: delivery to Download Center enqueues keys via injected sink (mock R2)', async () => {
  const uploaded = {};
  const enqueue = async (key, content) => { uploaded[key] = content; };
  const pkg = P.buildPackage(CONFORMED, { formats: ['otio'] });
  const keys = await P.deliverToDownloadCenter(pkg, { enqueue });
  assert.ok(keys.includes('conform/otio'));
  assert.ok(keys.includes('conform/manifest.json'));
  assert.equal(Object.keys(uploaded).length, keys.length);
});
