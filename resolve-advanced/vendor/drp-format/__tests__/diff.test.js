/**
 * P0.2 — diff(drpA, drpB) unit tests.
 *
 * Strategy: build synthetic DRPs via buildDRP with controlled deltas
 * between them, then assert the resulting DTO captures each delta in
 * the right bucket without false positives.
 *
 * Run: node --test packages/drp-format/__tests__/diff.test.js
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const JSZip = require('jszip');

const drpFormat = require('..');

const BODY_A = '80aaaaaaaaaaaaaaaa';
const BODY_B = '80bbbbbbbbbbbbbbbb';
const BODY_C = '80cccccccccccccccc';

async function buildTwoClipDrp(outPath, clipSpecs) {
  const buf = await drpFormat.buildDRP({
    projectName: 'diff-test',
    timelines: [{
      name: 'T1',
      frameRate: 24,
      startTimecode: '01:00:00:00',
      resolution: '1920x1080',
      videoTracks: [{
        clips: clipSpecs,
      }],
      audioTracks: [],
    }],
  });
  await fs.writeFile(outPath, buf);
}

async function readClipIds(drpPath) {
  // Use the diff module's indexer to discover the auto-generated DbIds.
  const idx = await drpFormat.diff && (await drpFormat._diffInternals.indexDrp(drpPath));
  return [...idx.clipsById.keys()];
}

// Expose internals for the tests without polluting the public API.
drpFormat._diffInternals = require('../diff')._internals;

test('diff: identical DRPs report no changes', async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'drp-diff-'));
  try {
    const drpA = path.join(tmp, 'a.drp');
    const drpB = path.join(tmp, 'b.drp');
    const specs = [
      { start: 0,  duration: 24, in: 0, mediaFilePath: '/m/clip1.mov', grade: { body: BODY_A, hasCorrection: true } },
      { start: 24, duration: 24, in: 0, mediaFilePath: '/m/clip2.mov', grade: { body: BODY_B, hasCorrection: true } },
    ];
    await buildTwoClipDrp(drpA, specs);
    // Build B from the same spec object (separate buildDRP run = different
    // auto-generated UUIDs — so identical CONTENT will produce
    // added/removed pairs). Cheat the test: copy A bytes-for-bytes to get
    // identical DbIds. That's how a real "compare X against itself" call
    // would look anyway.
    await fs.copyFile(drpA, drpB);

    const result = await drpFormat.diff(drpA, drpB);
    assert.equal(result.summary.hasAnyChange, false);
    assert.equal(result.addedClips.length, 0);
    assert.equal(result.removedClips.length, 0);
    assert.equal(result.movedClips.length, 0);
    assert.equal(result.gradeChanges.length, 0);
    assert.equal(result.timelineSettingDeltas.length, 0);
    assert.equal(result.mediaPoolDeltas.added.length, 0);
    assert.equal(result.mediaPoolDeltas.removed.length, 0);
    assert.equal(result.summary.sameClipCount, 2);
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

test('diff: grade change on one clip is detected, other clip unchanged', async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'drp-diff-'));
  try {
    const drpA = path.join(tmp, 'a.drp');
    const drpB = path.join(tmp, 'b.drp');
    const specs = [
      { start: 0,  duration: 24, in: 0, mediaFilePath: '/m/clip1.mov', grade: { body: BODY_A, hasCorrection: true } },
      { start: 24, duration: 24, in: 0, mediaFilePath: '/m/clip2.mov', grade: { body: BODY_B, hasCorrection: true } },
    ];
    await buildTwoClipDrp(drpA, specs);
    await fs.copyFile(drpA, drpB);

    // Mutate clip 1 in B via injectGrades to BODY_C — preserves DbIds.
    const idsB = await readClipIds(drpB);
    const drxFor = (hex) => `<x><Body>${hex}</Body></x>`;
    await drpFormat.injectGrades(drpB, [
      { clipId: idsB[0], drxContent: drxFor(BODY_C) },
    ]);

    const result = await drpFormat.diff(drpA, drpB);
    assert.equal(result.summary.hasAnyChange, true);
    assert.equal(result.addedClips.length, 0);
    assert.equal(result.removedClips.length, 0);
    assert.equal(result.movedClips.length, 0);
    assert.equal(result.gradeChanges.length, 1);
    const g = result.gradeChanges[0];
    assert.equal(g.clipId, idsB[0]);
    assert.equal(g.hadGrade, true);
    assert.equal(g.hasGrade, true);
    assert.notEqual(g.beforeBodyHash, g.afterBodyHash);
    assert.ok(g.beforeBodyHash && /^[0-9a-f]{64}$/.test(g.beforeBodyHash));
    assert.ok(g.afterBodyHash && /^[0-9a-f]{64}$/.test(g.afterBodyHash));
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

test('diff: clip added in B surfaces in addedClips with no grade-change false positive', async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'drp-diff-'));
  try {
    const drpA = path.join(tmp, 'a.drp');
    const drpB = path.join(tmp, 'b.drp');
    await buildTwoClipDrp(drpA, [
      { start: 0, duration: 24, in: 0, mediaFilePath: '/m/clip1.mov', grade: { body: BODY_A, hasCorrection: true } },
    ]);
    await buildTwoClipDrp(drpB, [
      { start: 0,  duration: 24, in: 0, mediaFilePath: '/m/clip1.mov', grade: { body: BODY_A, hasCorrection: true } },
      { start: 24, duration: 24, in: 0, mediaFilePath: '/m/clip2.mov', grade: { body: BODY_B, hasCorrection: true } },
    ]);

    const result = await drpFormat.diff(drpA, drpB);
    // Because A and B were built independently, every DbId differs — A's
    // clip 1 is "removed", B's both clips are "added". That's correct per
    // the schema: identity is DbId, not media path. A more sophisticated
    // similarity layer is future work.
    assert.equal(result.summary.hasAnyChange, true);
    assert.equal(result.removedClips.length, 1);
    assert.equal(result.addedClips.length, 2);
    assert.equal(result.gradeChanges.length, 0);
    // Media-pool diff catches the new file.
    assert.ok(result.mediaPoolDeltas.added.includes('/m/clip2.mov'));
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

test('diff: same DbIds, clip 1 moved in B → movedClips, gradeChanges empty', async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'drp-diff-'));
  try {
    const drpA = path.join(tmp, 'a.drp');
    const drpB = path.join(tmp, 'b.drp');
    const specs = [
      { start: 0,  duration: 24, in: 0, mediaFilePath: '/m/clip1.mov', grade: { body: BODY_A, hasCorrection: true } },
      { start: 24, duration: 24, in: 0, mediaFilePath: '/m/clip2.mov', grade: { body: BODY_B, hasCorrection: true } },
    ];
    await buildTwoClipDrp(drpA, specs);
    await fs.copyFile(drpA, drpB);

    // Mutate the START frame of clip 1 in B's SeqContainer XML directly
    // (the only way to simulate "moved" while preserving DbIds —
    // injectGrades only touches <Body>).
    await mutateClipStart(drpB, /* clipIndex */ 0, /* newStart */ 100);

    const result = await drpFormat.diff(drpA, drpB);
    assert.equal(result.movedClips.length, 1);
    const move = result.movedClips[0];
    assert.equal(move.before.start, 0);
    assert.equal(move.after.start, 100);
    assert.equal(result.gradeChanges.length, 0,
      'a pure move should not falsely report a grade change');
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

test('diff: timeline settings delta surfaces project-level differences', async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'drp-diff-'));
  try {
    const drpA = path.join(tmp, 'a.drp');
    const drpB = path.join(tmp, 'b.drp');
    await buildTwoClipDrp(drpA, [
      { start: 0, duration: 24, in: 0, mediaFilePath: '/m/c.mov', grade: { body: BODY_A } },
    ]);
    // Mutate B's project.xml to change ProjectName.
    await fs.copyFile(drpA, drpB);
    await mutateProjectName(drpB, 'diff-test-renamed');

    const result = await drpFormat.diff(drpA, drpB);
    const nameDelta = result.timelineSettingDeltas.find((d) => d.key === 'projectName');
    assert.ok(nameDelta, 'projectName delta should be reported');
    assert.equal(nameDelta.before, 'diff-test');
    assert.equal(nameDelta.after, 'diff-test-renamed');
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

test('diff: internals.extractClips finds clips even when body absent', () => {
  const xml = `
    <Sm2TiVideoTrack DbId="t">
      <Sm2TiVideoClip DbId="clip-1">
        <Start>0</Start>
        <Duration>24</Duration>
        <MediaFilePath>/m/a.mov</MediaFilePath>
      </Sm2TiVideoClip>
      <Sm2TiVideoClip DbId="clip-2">
        <Start>24</Start>
        <Duration>24</Duration>
        <MediaFilePath>/m/b.mov</MediaFilePath>
        <Body>80aabb</Body>
      </Sm2TiVideoClip>
    </Sm2TiVideoTrack>
  `;
  const clips = drpFormat._diffInternals.extractClips(xml);
  assert.equal(clips.length, 2);
  assert.equal(clips[0].clipId, 'clip-1');
  assert.equal(clips[0].bodyHex, null);
  assert.equal(clips[0].start, 0);
  assert.equal(clips[1].clipId, 'clip-2');
  assert.equal(clips[1].bodyHex, '80aabb');
});

test('diff: rejects non-string arguments', async () => {
  await assert.rejects(() => drpFormat.diff(123, '/tmp/x'), /must be strings/);
  await assert.rejects(() => drpFormat.diff('/tmp/x', null), /must be strings/);
});

// ─── helpers that mutate a DRP zip in-place ─────────────────────────────

async function mutateClipStart(drpPath, clipIndex, newStart) {
  const buf = await fs.readFile(drpPath);
  const zip = await JSZip.loadAsync(buf);
  let seqEntry = null;
  zip.forEach((p, e) => { if (!e.dir && /(^|\/)SeqContainer\d*\.xml$/.test(p)) seqEntry = p; });
  let xml = await zip.file(seqEntry).async('string');
  // Replace the Nth Sm2TiVideoClip's <Start> value.
  const clipRe = /<Sm2TiVideoClip\b([\s\S]*?)<\/Sm2TiVideoClip>/g;
  let m, i = 0, replaced = false;
  while ((m = clipRe.exec(xml)) !== null) {
    if (i === clipIndex) {
      const clipBlock = m[0];
      const newClipBlock = clipBlock.replace(/<Start>[^<]*<\/Start>/, `<Start>${newStart}</Start>`);
      xml = xml.slice(0, m.index) + newClipBlock + xml.slice(m.index + clipBlock.length);
      replaced = true;
      break;
    }
    i += 1;
  }
  if (!replaced) throw new Error('mutateClipStart: no matching clip');
  zip.file(seqEntry, xml);
  const outBuf = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
  await fs.writeFile(drpPath, outBuf);
}

async function mutateProjectName(drpPath, newName) {
  const buf = await fs.readFile(drpPath);
  const zip = await JSZip.loadAsync(buf);
  let projEntry = null;
  zip.forEach((p, e) => { if (!e.dir && /(^|\/)project\.xml$/.test(p)) projEntry = p; });
  let xml = await zip.file(projEntry).async('string');
  // tool-authored DRPs use <Name>; Resolve-exported variants may
  // use <ProjectName>. Match either.
  const before = xml;
  xml = xml
    .replace(/<ProjectName>[^<]*<\/ProjectName>/, `<ProjectName>${newName}</ProjectName>`)
    .replace(/<Name>[^<]*<\/Name>/, `<Name>${newName}</Name>`);
  if (xml === before) throw new Error('mutateProjectName: no project-name tag found to mutate');
  zip.file(projEntry, xml);
  const outBuf = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
  await fs.writeFile(drpPath, outBuf);
}
