'use strict';

/** §9 propose-only strategies, media index, analysis, and P3 acceptance. */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const pkg = require('../index');
const S = require('../repair/strategies');
const { MediaIndex } = require('../repair/media-index');
const { detectDupes, proposeTimeline } = require('../repair/analysis');
const { makeRepairLadder } = require('../repair');

const GOLDEN = JSON.parse(fs.readFileSync(path.join(pkg.reelFixtureDir(), 'golden_oracle.json'), 'utf8'));
const CTX = { ticksPerFrame: GOLDEN.ticksPerFrame, sequenceWidth: GOLDEN.sequence.width, sequenceHeight: GOLDEN.sequence.height, sequenceRate: GOLDEN.sequence.fps };

test('media-index: resolves by basename, reel+TC, and proxy↔original variant', () => {
  const idx = new MediaIndex([
    { path: '/vol/scan/Sample S16mm 12R 4K 0821 CR A01-A03.mp4', basename: 'Sample S16mm 12R 4K 0821 CR A01-A03.mp4', reel: 'A001', startTc: '01:00:00:00' },
    { path: '/vol/other/Decoy.mov', basename: 'Decoy.mov' },
  ]);
  assert.equal(idx.byBasename('Decoy.mov'), '/vol/other/Decoy.mov');
  assert.equal(idx.byReelTc('A001', '01:00:00:00'), '/vol/scan/Sample S16mm 12R 4K 0821 CR A01-A03.mp4');
  // A proxy name with "4K-2K" resolves to the 4K scan (2k is variant-noise).
  const found = idx.findTrueSource('Sample S16mm 12R 4K-2K 0821 CR A01-A03.mov');
  assert.ok(found && found.basename.includes('A01-A03'), `proxy should resolve to the scan: ${JSON.stringify(found)}`);
});

test('repair: wrong-source uses identity + media index to propose the true source', () => {
  const idx = new MediaIndex([
    { path: '/vol/scan/Sample A01-A03.mp4', basename: 'Sample S16mm 12R 4K 0821 CR A01-A03.mp4' },
    { path: '/vol/scan/Other.mp4', basename: 'Totally Different Clip.mp4' },
  ]);
  const cut = { cutId: 'seq2983', verdict: 'WRONG', burnInName: 'Sample S16mm 12R 4K 0821 CR A01-A03.mp4' };
  assert.equal(S.wrongSource.detect(cut, { mediaIndex: idx }), true);
  const p = S.wrongSource.propose(cut, { mediaIndex: idx });
  assert.ok(p.fix && p.fix.source_basename.includes('A01-A03'));
  assert.ok(p.confidence > 0.5);
});

test('repair: per-file offset estimated from samples + applied to that file only', () => {
  const k = S.estimatePerFileOffset([{ derived: 100, matched: 211 }, { derived: 200, matched: 311 }, { derived: 50, matched: 161 }]);
  assert.equal(k, 111); // constant +111 (the SAMPLE-style per-file offset)
  const cut = { fileId: 'file-7' };
  assert.equal(S.perFileOffset.detect(cut, { fileOffsets: { 'file-7': 111 } }), true);
  assert.equal(S.perFileOffset.propose(cut, { fileOffsets: { 'file-7': 111 } }).fix.sourceFrameDelta, 111);
  // A noisy sample set (no majority constant) => no offset.
  assert.equal(S.estimatePerFileOffset([{ derived: 1, matched: 2 }, { derived: 1, matched: 9 }, { derived: 1, matched: 40 }]), null);
});

test('repair: measured residual patches ONLY measured clips (non-negotiable #4)', () => {
  const cut = { cutId: 'c1', measuredOffset: { dx: 4, dy: -2 } };
  assert.equal(S.measuredResidual.detect(cut), true);
  assert.deepEqual(S.measuredResidual.propose(cut).fix.positionPatch, { dx: -4, dy: 2, ds: 0 });
  // applyMeasuredPatches leaves unmeasured cuts untouched.
  const out = S.applyMeasuredPatches([{ cutId: 'a' }, { cutId: 'b' }], { a: { dx: 3, dy: 0 } });
  assert.equal(out.find((x) => x.cutId === 'a').patched, true);
  assert.equal(out.find((x) => x.cutId === 'b').patched, false);
});

test('repair: aspect-variant, mixed-framerate, handle-shortfall, missing-media', () => {
  // Aspect: a 4:3 source in a 16:9 sequence.
  assert.equal(S.aspectVariant.detect({ srcW: 1440, srcH: 1080 }, CTX), true);
  assert.equal(S.aspectVariant.detect({ srcW: 2048, srcH: 1306 }, CTX), false); // S16mm 1.568 vs 5:3 seq — fit by scale, not a reframe
  // Mixed rate.
  const mr = S.mixedFrameRate.propose({ sourceFrame: 100, clipRate: 48 }, { sequenceRate: 24 });
  assert.equal(mr.fix.sourceFrame, 200);
  // Handle shortfall near media end.
  assert.equal(S.handleShortfall.detect({ mediaLength: 100, usedOut: 98, usedIn: 90, handles: 12 }), true);
  assert.equal(S.handleShortfall.propose({ mediaLength: 100, usedOut: 98, usedIn: 90, handles: 12 }).fix.handlesTail, 2);
  // Missing media: no index match, no burn-in.
  assert.equal(S.missingMedia.detect({ pathMissing: true, source_basename: 'Gone.mov' }, {}), true);
});

test('repair: reel-name conform resolves reel+TC', () => {
  const idx = new MediaIndex([{ path: '/vol/A001.mov', basename: 'A001.mov', reel: 'A001', startTc: '01:00:00:00' }]);
  const cut = { reel: 'A001', sourceTc: '01:00:00:00' };
  assert.equal(S.reelNameConform.detect(cut, { mediaIndex: idx }), true);
  assert.equal(S.reelNameConform.propose(cut, { mediaIndex: idx }).fix.path, '/vol/A001.mov');
});

test('check: dupes — repeated-source clusters reported, uniques not flagged', () => {
  const dupes = detectDupes(GOLDEN.clips);
  assert.ok(dupes.length > 0, 'SAMPLE reel reuses sources');
  for (const d of dupes) assert.ok(d.count > 1);
  // A reel of all-unique sources reports nothing.
  assert.deepEqual(detectDupes([{ cutId: 1, source_basename: 'a' }, { cutId: 2, source_basename: 'b' }]), []);
});

test('propose-timeline: auto-applied fixes vs V2 flag track (V1 gap per flag)', () => {
  const results = [
    { cutId: 'c1', seqstart: 0, repair: { mode: 'auto-apply', strategy: 'normalize-scale', proposal: { fix: { scale: 100 } } } },
    { cutId: 'c2', seqstart: 48, repair: { mode: 'propose-only', klass: 'wrong-source', diagnosis: 'needs review', proposal: { fix: { path: '/x' } } } },
    { cutId: 'c3', seqstart: 96, repair: { mode: 'flag-v2', klass: 'unrepairable', diagnosis: 'offline' } },
  ];
  const out = proposeTimeline(results);
  assert.equal(out.summary.autoApplied, 1);
  assert.equal(out.summary.flagged, 2);
  assert.equal(out.correctedTimeline.find((c) => c.cutId === 'c1').v1Gap, false);
  assert.equal(out.correctedTimeline.find((c) => c.cutId === 'c2').v1Gap, true);
  assert.equal(out.v2Flags.length, 2);
});

test('P3 ACCEPTANCE: broken SAMPLE variant — correct fixes proposed, only irreducible flagged', async () => {
  const ladder = makeRepairLadder({});
  // The "broken variant": all 327 clips carry un-normalized scale (the v3 scale mistake).
  const results = [];
  for (const c of GOLDEN.clips) {
    const rep = await ladder.repair({ ...c, cutId: `seq${c.seqstart}` }, CTX);
    results.push({ cutId: `seq${c.seqstart}`, seqstart: c.seqstart, expected: c.expected_scale_corrected, repair: rep });
  }
  // Every scale-broken clip auto-applies to the correct normalized scale.
  for (const r of results) {
    assert.equal(r.repair.mode, 'auto-apply', `@${r.seqstart} should auto-apply`);
    assert.ok(Math.abs(r.repair.proposal.fix.scale - r.expected) < 0.001);
  }
  // Add one genuinely-wrong, no-true-source cut: it must flag, not auto-fix.
  const wrong = await ladder.repair({ cutId: 'seqWRONG', verdict: 'WRONG', pathMissing: true, source_basename: 'Lost.mov', is_subclip: false, xml_in: 0, pproTicksIn: 0, scale_premiere: 100, srcW: CTX.sequenceWidth }, CTX);
  results.push({ cutId: 'seqWRONG', seqstart: -1, repair: wrong });
  const proposed = proposeTimeline(results);
  assert.equal(proposed.summary.autoApplied, 327);
  assert.equal(proposed.summary.flagged, 1);
  assert.equal(proposed.v2Flags[0].cutId, 'seqWRONG');
  // eslint-disable-next-line no-console
  console.log(`[P3] ACCEPTANCE: 327 auto-fixed (scale normalized) + 1 irreducible flagged to V2`);
});
