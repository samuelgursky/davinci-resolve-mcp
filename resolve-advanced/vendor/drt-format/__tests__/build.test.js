/**
 * P3.3 — buildDRT tests.
 *
 * Round-trip strategy without a parser (P3.2 ships parseDRT later):
 *   - buildDRT produces a zip with SeqContainer*.xml inside but NO
 *     project.xml. Verify the zip contents directly via jszip.
 *   - Use drp-format diff internals to walk the SeqContainer and
 *     confirm clips are encoded as expected.
 *
 * Run: node --test packages/drt-format/__tests__/build.test.js
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const JSZip = require('jszip');

const drt = require('..');
const drp = require('../../drp-format');

const SPEC = {
  timelines: [{
    name: 'T1',
    frameRate: 24,
    startTimecode: '01:00:00:00',
    resolution: '1920x1080',
    videoTracks: [{
      clips: [
        { start: 0, duration: 24, in: 0, mediaFilePath: '/m/c1.mov', grade: { body: '80aaaaaa', hasCorrection: true } },
        { start: 24, duration: 24, in: 0, mediaFilePath: '/m/c2.mov', grade: { body: '80bbbbbb', hasCorrection: true } },
      ],
    }],
    audioTracks: [],
  }],
  metadata: { source: 'drt-format-test' },
};

test('buildDRT: produces a zip with SeqContainer but no project.xml', async () => {
  const buf = await drt.buildDRT(SPEC);
  assert.ok(Buffer.isBuffer(buf), 'should return a Buffer');
  assert.ok(buf.length > 0, 'buffer should not be empty');

  const zip = await JSZip.loadAsync(buf);
  const entries = [];
  zip.forEach((p, e) => { if (!e.dir) entries.push(p); });

  const hasProjectXml = entries.some((p) => /(^|\/)project\.xml$/.test(p));
  assert.equal(hasProjectXml, false, 'DRT must NOT include project.xml');

  const seqEntries = entries.filter((p) => /(^|\/)SeqContainer\d*\.xml$/.test(p));
  assert.ok(seqEntries.length >= 1, 'DRT must include at least one SeqContainer XML');
});

test('buildDRT: clips from the spec land in the SeqContainer with correct media refs', async () => {
  const buf = await drt.buildDRT(SPEC);
  const zip = await JSZip.loadAsync(buf);
  let seqXml = null;
  const ps = [];
  zip.forEach((p, e) => {
    if (!e.dir && /(^|\/)SeqContainer\d*\.xml$/.test(p)) {
      ps.push(zip.file(p).async('string').then((s) => { seqXml = s; }));
    }
  });
  await Promise.all(ps);

  assert.ok(seqXml.includes('/m/c1.mov'), 'clip 1 mediaFilePath should be embedded');
  assert.ok(seqXml.includes('/m/c2.mov'), 'clip 2 mediaFilePath should be embedded');
  // Each clip's body blob (uncompressed marker + hex) should appear.
  assert.ok(seqXml.includes('80aaaaaa'), 'clip 1 body hex should be present');
  assert.ok(seqXml.includes('80bbbbbb'), 'clip 2 body hex should be present');
});

test('buildDRT: roundtrips through drp-format.diffInternals.indexDrp', async () => {
  const buf = await drt.buildDRT(SPEC);
  // Write to disk because indexDrp expects a path.
  const fs = require('node:fs/promises');
  const path = require('node:path');
  const os = require('node:os');
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'drt-build-'));
  try {
    const drtPath = path.join(tmp, 'out.drt');
    await fs.writeFile(drtPath, buf);

    const index = await drp.diffInternals.indexDrp(drtPath);
    assert.equal(index.clipsById.size, 2, 'should walk 2 clips');
    assert.equal(index.seqContainers.length, 1, 'should find 1 SeqContainer');

    // Project settings should be EMPTY — no project.xml in a DRT.
    assert.equal(index.projectXml, null);
    assert.deepEqual(index.projectSettings, {});

    // Verify each clip's body hex is reachable.
    const bodies = [...index.clipsById.values()].map((c) => c.bodyHex).sort();
    assert.deepEqual(bodies, ['80aaaaaa', '80bbbbbb']);
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

test('buildDRT: rejects empty/invalid spec', async () => {
  await assert.rejects(() => drt.buildDRT(null), /spec must be an object/);
  await assert.rejects(() => drt.buildDRT({}), /at least one timeline/i);
  await assert.rejects(() => drt.buildDRT({ timelines: [] }), /at least one timeline/i);
});

test('buildDRT: includes metadata in the archive when supplied', async () => {
  const buf = await drt.buildDRT(SPEC);
  const zip = await JSZip.loadAsync(buf);
  const metaEntry = zip.file('metadata.json');
  assert.ok(metaEntry, 'metadata.json should be present');
  const metaJson = JSON.parse(await metaEntry.async('string'));
  assert.equal(metaJson.source, 'drt-format-test');
  assert.ok(metaJson.exportedAt, 'exportedAt should be auto-stamped');
});
