/**
 * P3.2 — parseDRT tests.
 *
 * Strategy: build synthetic DRTs via buildDRT, then parse them. Real-Resolve
 * fixture verification is deferred to the Resolve-batch session.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');

const drt = require('..');

const SPEC = {
  timelines: [{
    name: 'My Cut',
    frameRate: 24,
    startTimecode: '01:00:00:00',
    resolution: '1920x1080',
    videoTracks: [{
      clips: [
        { start: 0,  duration: 24, in: 0, mediaFilePath: '/m/c1.mov', grade: { body: '80aaaaaa', hasCorrection: true } },
        { start: 24, duration: 48, in: 0, mediaFilePath: '/m/c2.mov', grade: { body: '80bbbbbb', hasCorrection: true } },
      ],
    }],
    audioTracks: [{
      clips: [
        { start: 0, duration: 72, in: 0, mediaFilePath: '/m/audio.wav' },
      ],
    }],
  }],
  metadata: { source: 'drt-parse-test', operator: 'session-8' },
};

async function buildAndParse(spec = SPEC) {
  const buf = await drt.buildDRT(spec);
  return drt.parseDRT(buf);
}

test('parseDRT: accepts Buffer input', async () => {
  const parsed = await buildAndParse();
  assert.equal(parsed.timelines.length, 1);
  assert.ok(Array.isArray(parsed.seqContainers));
});

test('parseDRT: accepts filesystem path input', async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'drt-parse-'));
  try {
    const drtPath = path.join(tmp, 'out.drt');
    await fs.writeFile(drtPath, await drt.buildDRT(SPEC));
    const parsed = await drt.parseDRT(drtPath);
    assert.equal(parsed.timelines.length, 1);
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

test('parseDRT: surfaces timeline-level settings from the SeqContainer', async () => {
  const parsed = await buildAndParse();
  const tl = parsed.timelines[0];
  assert.equal(tl.name, 'My Cut');
  assert.equal(tl.startTimecode, '01:00:00:00');
  assert.equal(tl.resolution, '1920x1080');
  // FrameRate is encoded as a hex-float by the builder; just confirm it's
  // non-null and the parser surfaces it for downstream interpretation.
  assert.ok(tl.frameRate);
  assert.ok(typeof tl.startFrame === 'number');
});

test('parseDRT: reconstructs the video track and its clips', async () => {
  const parsed = await buildAndParse();
  const tl = parsed.timelines[0];
  assert.equal(tl.videoTracks.length, 1);
  const clips = tl.videoTracks[0].clips;
  assert.equal(clips.length, 2);
  // Sort by start to make order-independent.
  const sorted = clips.slice().sort((a, b) => a.start - b.start);
  assert.equal(sorted[0].mediaFilePath, '/m/c1.mov');
  assert.equal(sorted[0].duration, 24);
  assert.equal(sorted[0].bodyHex, '80aaaaaa');
  assert.equal(sorted[1].mediaFilePath, '/m/c2.mov');
  assert.equal(sorted[1].duration, 48);
  assert.equal(sorted[1].bodyHex, '80bbbbbb');
});

test('parseDRT: reconstructs the audio track separately from video', async () => {
  const parsed = await buildAndParse();
  const tl = parsed.timelines[0];
  assert.equal(tl.audioTracks.length, 1);
  assert.equal(tl.audioTracks[0].clips.length, 1);
  assert.equal(tl.audioTracks[0].clips[0].mediaFilePath, '/m/audio.wav');
});

test('parseDRT: surfaces metadata.json when present', async () => {
  const parsed = await buildAndParse();
  assert.ok(parsed.metadata);
  assert.equal(parsed.metadata.source, 'drt-parse-test');
  assert.equal(parsed.metadata.operator, 'session-8');
});

test('parseDRT: rejects non-DRT zips (no SeqContainer)', async () => {
  // Create a zip that has neither SeqContainer nor project.xml.
  const JSZip = require('jszip');
  const z = new JSZip();
  z.file('hello.txt', 'world');
  const buf = await z.generateAsync({ type: 'nodebuffer' });
  await assert.rejects(() => drt.parseDRT(buf), /no SeqContainer/);
});

test('parseDRT: rejects bad input types', async () => {
  await assert.rejects(() => drt.parseDRT(null), /string path or a Buffer/);
  await assert.rejects(() => drt.parseDRT(42), /string path or a Buffer/);
});

test('parseDRT: multi-timeline DRT parses each as its own timeline', async () => {
  const multiSpec = {
    timelines: [
      { name: 'TL One', frameRate: 24, startTimecode: '01:00:00:00', resolution: '1920x1080',
        videoTracks: [{ clips: [{ start: 0, duration: 24, in: 0, mediaFilePath: '/m/a.mov' }] }],
        audioTracks: [] },
      { name: 'TL Two', frameRate: 24, startTimecode: '02:00:00:00', resolution: '3840x2160',
        videoTracks: [{ clips: [{ start: 0, duration: 48, in: 0, mediaFilePath: '/m/b.mov' }] }],
        audioTracks: [] },
    ],
  };
  const parsed = await buildAndParse(multiSpec);
  assert.equal(parsed.timelines.length, 2);
  const names = parsed.timelines.map((t) => t.name).sort();
  assert.deepEqual(names, ['TL One', 'TL Two']);
  const resolutions = parsed.timelines.map((t) => t.resolution).sort();
  assert.deepEqual(resolutions, ['1920x1080', '3840x2160']);
});
