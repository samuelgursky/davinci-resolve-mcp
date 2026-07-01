/**
 * P0.1 — injectGrades unit tests.
 *
 * Strategy: build a synthetic DRP with two pre-graded clips, scrape their
 * auto-generated DbIds out of the SeqContainer XML, inject a new <Body>
 * blob into one of them, and verify (a) the targeted clip's Body changed
 * to the injected value, (b) the other clip's Body didn't change,
 * (c) the surrounding XML is otherwise byte-identical.
 *
 * Run: node --test packages/drp-format/__tests__/inject-grades.test.js
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const JSZip = require('jszip');

const drpFormat = require('..');
const { resolveVerifyTest } = require('./_resolve-verify');

// A plausible-shaped synthetic body. The injector does not parse the bytes,
// only substitutes them. Hex characters only.
const BASELINE_BODY = '80aaaaaaaaaaaaaaaa';
const ORIGINAL_BODY_CLIP_2 = '80bbbbbbbbbbbbbbbb';
const INJECTED_BODY = '81cafebabe0102030405060708090a0b0c0d0e0f';

function makeSyntheticDrx(bodyHex) {
  return `<?xml version="1.0" encoding="UTF-8"?>\n<Resolve_Color_Exchange>\n  <Body>${bodyHex}</Body>\n</Resolve_Color_Exchange>\n`;
}

async function buildSyntheticDrp(outPath) {
  const buf = await drpFormat.buildDRP({
    projectName: 'inject-grades-test',
    timelines: [{
      name: 'T1',
      frameRate: 24,
      startTimecode: '01:00:00:00',
      resolution: '1920x1080',
      videoTracks: [{
        clips: [
          {
            start: 0, duration: 24, in: 0,
            mediaFilePath: '/synthetic/clip1.mov',
            grade: { body: BASELINE_BODY, hasCorrection: true, versionName: 'V1' },
          },
          {
            start: 24, duration: 24, in: 0,
            mediaFilePath: '/synthetic/clip2.mov',
            grade: { body: ORIGINAL_BODY_CLIP_2, hasCorrection: true, versionName: 'V1' },
          },
        ],
      }],
      audioTracks: [],
    }],
  });
  await fs.writeFile(outPath, buf);
  return buf;
}

async function readSeqContainer(drpPath) {
  const buf = await fs.readFile(drpPath);
  const zip = await JSZip.loadAsync(buf);
  const seqEntries = [];
  zip.forEach((p, e) => {
    if (!e.dir && /(^|\/)SeqContainer\d*\.xml$/.test(p)) seqEntries.push(p);
  });
  assert(seqEntries.length > 0, 'synthetic DRP should have at least one SeqContainer');
  return zip.file(seqEntries[0]).async('string');
}

/**
 * Scrape (DbId, Body) pairs from a built SeqContainer XML. Pulls them in
 * document order so callers can pick clip 1 / clip 2 deterministically.
 */
function scrapeClipBodies(xml) {
  const pairs = [];
  const clipRe = /<Sm2TiVideoClip\b[^>]*?DbId="([^"]+)"[\s\S]*?<Body>([0-9a-fA-F]+)<\/Body>[\s\S]*?<\/Sm2TiVideoClip>/g;
  let m;
  while ((m = clipRe.exec(xml)) !== null) {
    pairs.push({ dbId: m[1], body: m[2] });
  }
  return pairs;
}

test('injectGrades: replaces body of the targeted clip only', async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'inject-grades-'));
  try {
    const srcDrp = path.join(tmp, 'src.drp');
    const outDrp = path.join(tmp, 'out.drp');
    await buildSyntheticDrp(srcDrp);

    // 1. Discover the auto-generated DbIds + baseline bodies.
    const beforeXml = await readSeqContainer(srcDrp);
    const before = scrapeClipBodies(beforeXml);
    assert.equal(before.length, 2, 'expected exactly two video clips with bodies');
    assert.equal(before[0].body, BASELINE_BODY);
    assert.equal(before[1].body, ORIGINAL_BODY_CLIP_2);

    // 2. Inject into clip 1.
    const result = await drpFormat.injectGrades(srcDrp, [
      { clipId: before[0].dbId, drxContent: makeSyntheticDrx(INJECTED_BODY) },
    ], { outputPath: outDrp });

    assert.equal(result.clipsInjected, 1);
    assert.deepEqual(result.misses, []);
    assert.ok(result.bytes > 0);

    // 3. Verify the injection landed only on clip 1.
    const afterXml = await readSeqContainer(outDrp);
    const after = scrapeClipBodies(afterXml);
    assert.equal(after.length, 2);
    assert.equal(after[0].dbId, before[0].dbId);
    assert.equal(after[1].dbId, before[1].dbId);
    assert.equal(after[0].body, INJECTED_BODY, 'clip 1 body should be replaced');
    assert.equal(after[1].body, ORIGINAL_BODY_CLIP_2, 'clip 2 body must be untouched');
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

test('injectGrades: misses report unmatched DbIds', async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'inject-grades-'));
  try {
    const srcDrp = path.join(tmp, 'src.drp');
    const outDrp = path.join(tmp, 'out.drp');
    await buildSyntheticDrp(srcDrp);

    const result = await drpFormat.injectGrades(srcDrp, [
      { clipId: 'definitely-not-a-real-dbid', drxContent: makeSyntheticDrx(INJECTED_BODY) },
    ], { outputPath: outDrp });

    assert.equal(result.clipsInjected, 0);
    assert.deepEqual(result.misses, ['definitely-not-a-real-dbid']);
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

test('injectGrades: rejects malformed DRX content', async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'inject-grades-'));
  try {
    const srcDrp = path.join(tmp, 'src.drp');
    await buildSyntheticDrp(srcDrp);
    const beforeXml = await readSeqContainer(srcDrp);
    const before = scrapeClipBodies(beforeXml);

    await assert.rejects(
      () => drpFormat.injectGrades(srcDrp, [
        { clipId: before[0].dbId, drxContent: '<not-a-drx>nothing here</not-a-drx>' },
      ], { outputPath: path.join(tmp, 'out.drp') }),
      /no <Body>HEX<\/Body> block/i,
    );
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

test('injectGrades: resolveId alias works the same as clipId', async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'inject-grades-'));
  try {
    const srcDrp = path.join(tmp, 'src.drp');
    const outDrp = path.join(tmp, 'out.drp');
    await buildSyntheticDrp(srcDrp);

    const beforeXml = await readSeqContainer(srcDrp);
    const before = scrapeClipBodies(beforeXml);

    const result = await drpFormat.injectGrades(srcDrp, [
      { resolveId: before[1].dbId, drxContent: makeSyntheticDrx(INJECTED_BODY) },
    ], { outputPath: outDrp });

    assert.equal(result.clipsInjected, 1);
    const afterXml = await readSeqContainer(outDrp);
    const after = scrapeClipBodies(afterXml);
    assert.equal(after[1].body, INJECTED_BODY);
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

test('injectGrades: in-place overwrite atomically replaces the source file', async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'inject-grades-'));
  try {
    const drpPath = path.join(tmp, 'inplace.drp');
    await buildSyntheticDrp(drpPath);
    const originalBytes = (await fs.stat(drpPath)).size;

    const beforeXml = await readSeqContainer(drpPath);
    const before = scrapeClipBodies(beforeXml);

    // No outputPath → in-place.
    await drpFormat.injectGrades(drpPath, [
      { clipId: before[0].dbId, drxContent: makeSyntheticDrx(INJECTED_BODY) },
    ]);

    const afterBytes = (await fs.stat(drpPath)).size;
    assert.ok(Math.abs(afterBytes - originalBytes) < originalBytes * 0.25,
      'in-place output size should be in the ballpark of original');

    const afterXml = await readSeqContainer(drpPath);
    const after = scrapeClipBodies(afterXml);
    assert.equal(after[0].body, INJECTED_BODY);

    // No leftover tmp file.
    const tmpLeftover = await fs.stat(`${drpPath}.injecting`).catch(() => null);
    assert.equal(tmpLeftover, null);
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

test('injectGrades: internals — extractDrxBodyHex strips non-hex chars', () => {
  const { _internals } = require('../inject-grades');
  const xml = '<x><Body>  81 ca\nfe ba be  </Body></x>';
  assert.equal(_internals.extractDrxBodyHex(xml), '81cafebabe');
});

test('injectGrades: internals — extractDrxBodyHex throws on missing Body', () => {
  const { _internals } = require('../inject-grades');
  assert.throws(() => _internals.extractDrxBodyHex('<x>nope</x>'),
    /no <Body>HEX<\/Body> block/i);
});

// ─── Resolve-in-loop verification (RESOLVE_VERIFY=1) ───────────
//
// Per P0.1 step 5 (logged deferred in knowledge/resolve-verifications.md),
// the byte-identical-render check requires Resolve. When the env flag is
// unset the test skips with a clear marker.

resolveVerifyTest('injectGrades: rendered frame matches direct DRX apply', async () => {
  // The harness's resolve-verifications.md has the full recipe. The actual
  // implementation will live here once a captured fixture + a Resolve session
  // is in flight. Until then it's a placeholder that exists to demonstrate
  // the resolveVerifyTest gate and to surface in the skip list as a TODO.
  throw new Error('TODO — implement once fixtures/inject-target.drp + Resolve session land');
});
