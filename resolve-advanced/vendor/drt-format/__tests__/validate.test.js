/**
 * P3.4 — validateDRT tests.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const JSZip = require('jszip');

const drt = require('..');

const SPEC = {
  timelines: [{
    name: 'V', frameRate: 24, startTimecode: '01:00:00:00', resolution: '1920x1080',
    videoTracks: [{ clips: [{ start: 0, duration: 24, in: 0, mediaFilePath: '/m/c1.mov' }] }],
    audioTracks: [],
  }],
};

test('validateDRT: well-formed buildDRT output is valid', async () => {
  const buf = await drt.buildDRT(SPEC);
  const v = await drt.validateDRT(buf);
  assert.equal(v.valid, true, JSON.stringify(v.errors));
  assert.deepEqual(v.errors, []);
});

test('validateDRT: empty buffer reports zip-open', async () => {
  const v = await drt.validateDRT(Buffer.from([0x00, 0x00, 0x00]));
  assert.equal(v.valid, false);
  assert.ok(v.errors.some((e) => e.code === 'zip-open'));
});

test('validateDRT: zip with no SeqContainer reports no-seq', async () => {
  const z = new JSZip();
  z.file('hello.txt', 'world');
  const buf = await z.generateAsync({ type: 'nodebuffer' });
  const v = await drt.validateDRT(buf);
  assert.equal(v.valid, false);
  assert.ok(v.errors.some((e) => e.code === 'no-seq'));
});

test('validateDRT: zip with project.xml reports has-project (DRP not DRT)', async () => {
  const z = new JSZip();
  z.file('project.xml', '<Sm2Project><Name>x</Name></Sm2Project>');
  z.folder('Primary1').file('SeqContainer1.xml', '<Sm2SequenceContainer><Name>x</Name><FrameRate>0</FrameRate></Sm2SequenceContainer>');
  const buf = await z.generateAsync({ type: 'nodebuffer' });
  const v = await drt.validateDRT(buf);
  assert.equal(v.valid, false);
  assert.ok(v.errors.some((e) => e.code === 'has-project'));
});

test('validateDRT: SeqContainer missing required fields reports seq-schema', async () => {
  const z = new JSZip();
  z.folder('Primary1').file('SeqContainer1.xml', '<Sm2SequenceContainer></Sm2SequenceContainer>');
  const buf = await z.generateAsync({ type: 'nodebuffer' });
  const v = await drt.validateDRT(buf);
  assert.equal(v.valid, false);
  const seqErrs = v.errors.filter((e) => e.code === 'seq-schema');
  assert.ok(seqErrs.length >= 2, 'expected multiple seq-schema entries');
  const messages = seqErrs.map((e) => e.message);
  assert.ok(messages.some((m) => m.includes('<Name>')));
  assert.ok(messages.some((m) => m.includes('<FrameRate>')));
});

test('validateDRT: empty MediaFilePath reports orphan-media', async () => {
  const z = new JSZip();
  z.folder('Primary1').file('SeqContainer1.xml',
    '<Sm2SequenceContainer>' +
    '<Name>x</Name>' +
    '<FrameRate>0</FrameRate>' +
    '<VideoTrackVec><Sm2TiVideoTrack DbId="t">' +
    '<LayersVec><Items>' +
    '<Sm2TiVideoClip DbId="c1"><MediaFilePath></MediaFilePath></Sm2TiVideoClip>' +
    '</Items></LayersVec>' +
    '</Sm2TiVideoTrack></VideoTrackVec>' +
    '</Sm2SequenceContainer>');
  const buf = await z.generateAsync({ type: 'nodebuffer' });
  const v = await drt.validateDRT(buf);
  assert.equal(v.valid, false);
  const orphan = v.errors.find((e) => e.code === 'orphan-media');
  assert.ok(orphan);
  assert.ok(orphan.message.includes('1 clip'));
});

test('validateDRT: filesystem path input also works', async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'drt-validate-'));
  try {
    const drtPath = path.join(tmp, 'out.drt');
    await fs.writeFile(drtPath, await drt.buildDRT(SPEC));
    const v = await drt.validateDRT(drtPath);
    assert.equal(v.valid, true);
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

test('validateDRT: missing path reports read-failed without throwing', async () => {
  const v = await drt.validateDRT('/tmp/does-not-exist-' + Math.random().toString(36).slice(2) + '.drt');
  assert.equal(v.valid, false);
  assert.ok(v.errors.some((e) => e.code === 'read-failed'));
});

test('validateDRT: bad input type reports bad-input', async () => {
  const v = await drt.validateDRT(null);
  assert.equal(v.valid, false);
  assert.ok(v.errors.some((e) => e.code === 'bad-input'));
});
