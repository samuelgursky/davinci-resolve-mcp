/**
 * P5.2 — extractProjectLUTRefs unit tests.
 *
 * Strategy: build synthetic DRPs via buildDRP with optional LUT slots
 * populated. Verify the extractor surfaces each slot when set, and
 * returns empty array when none are.
 *
 * Real Resolve-fixture verification is deferred to the Resolve-batch
 * session (queued in knowledge/resolve-verifications.md).
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');

const drpFormat = require('..');

const BASE_SPEC = {
  projectName: 'lut-test',
  timelines: [{
    name: 'T1', frameRate: 24, startTimecode: '01:00:00:00', resolution: '1920x1080',
    videoTracks: [{ clips: [{ start: 0, duration: 24, in: 0, mediaFilePath: '/m/c.mov' }] }],
    audioTracks: [],
  }],
};

async function buildDrpWithLuts(luts) {
  return drpFormat.buildDRP({
    ...BASE_SPEC,
    projectSettings: { ...luts },
  });
}

test('extractProjectLUTRefs: returns empty when no LUTs in project.xml', async () => {
  const buf = await drpFormat.buildDRP(BASE_SPEC);
  const refs = await drpFormat.extractProjectLUTRefs(buf);
  assert.deepEqual(refs, []);
});

test('extractProjectLUTRefs: surfaces a TimelineLUT path', async () => {
  const buf = await buildDrpWithLuts({ timelineLUT: '/lut/look.cube' });
  const refs = await drpFormat.extractProjectLUTRefs(buf);
  assert.equal(refs.length, 1);
  assert.equal(refs[0].slot, 'TimelineLUT');
  assert.equal(refs[0].path, '/lut/look.cube');
});

test('extractProjectLUTRefs: surfaces all four standard slots', async () => {
  const buf = await buildDrpWithLuts({
    inputLUT: '/lut/idt.clf',
    outputLUT: '/lut/odt.clf',
    timelineLUT: '/lut/look.cube',
    monitorLUT: '/lut/monitor.cube',
  });
  const refs = await drpFormat.extractProjectLUTRefs(buf);
  const slots = refs.map((r) => r.slot).sort();
  assert.deepEqual(slots, ['InputLUT', 'MonitorLUT', 'OutputLUT', 'TimelineLUT']);
  const byTag = Object.fromEntries(refs.map((r) => [r.slot, r.path]));
  assert.equal(byTag.InputLUT, '/lut/idt.clf');
  assert.equal(byTag.OutputLUT, '/lut/odt.clf');
  assert.equal(byTag.TimelineLUT, '/lut/look.cube');
  assert.equal(byTag.MonitorLUT, '/lut/monitor.cube');
});

test('extractProjectLUTRefs: surfaces claimed color spaces alongside each LUT', async () => {
  const buf = await buildDrpWithLuts({ timelineLUT: '/lut/look.cube' });
  const refs = await drpFormat.extractProjectLUTRefs(buf);
  const spaces = refs[0].claimedSpaces;
  // buildDRP defaults populate the color-space fields.
  assert.ok(spaces.InputColorSpace);
  assert.ok(spaces.TimelineColorSpace);
  assert.ok(spaces.OutputColorSpace);
});

test('extractProjectLUTRefs: accepts a filesystem path', async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'lut-refs-'));
  try {
    const drpPath = path.join(tmp, 'with-lut.drp');
    await fs.writeFile(drpPath, await buildDrpWithLuts({ timelineLUT: '/lut/x.cube' }));
    const refs = await drpFormat.extractProjectLUTRefs(drpPath);
    assert.equal(refs.length, 1);
    assert.equal(refs[0].path, '/lut/x.cube');
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

test('extractProjectLUTRefs: rejects bad input types', async () => {
  await assert.rejects(() => drpFormat.extractProjectLUTRefs(null), /string path or a Buffer/);
  await assert.rejects(() => drpFormat.extractProjectLUTRefs(42), /string path or a Buffer/);
});

test('extractProjectLUTRefs: returns [] when archive has no project.xml (DRT-like)', async () => {
  // Build a minimal zip with no project.xml — mimics DRT layout.
  const JSZip = require('jszip');
  const z = new JSZip();
  z.folder('Primary1').file('SeqContainer1.xml', '<Sm2SequenceContainer><Name>x</Name><FrameRate>0</FrameRate></Sm2SequenceContainer>');
  const buf = await z.generateAsync({ type: 'nodebuffer' });
  const refs = await drpFormat.extractProjectLUTRefs(buf);
  assert.deepEqual(refs, []);
});

test('extractProjectLUTRefs: ignores empty-string LUT slots', async () => {
  // If someone manually constructed a DRP with empty LUT tags, those
  // shouldn't count as references.
  const buf = await buildDrpWithLuts({ timelineLUT: '' });
  const refs = await drpFormat.extractProjectLUTRefs(buf);
  assert.deepEqual(refs, []);
});

test('LUT_RECOGNIZED_SLOTS: exposes the slot whitelist', () => {
  assert.ok(Array.isArray(drpFormat.LUT_RECOGNIZED_SLOTS));
  assert.ok(drpFormat.LUT_RECOGNIZED_SLOTS.includes('TimelineLUT'));
  assert.ok(drpFormat.LUT_RECOGNIZED_SLOTS.includes('InputLUT'));
  assert.ok(drpFormat.LUT_RECOGNIZED_SLOTS.includes('OutputLUT'));
  assert.ok(drpFormat.LUT_RECOGNIZED_SLOTS.includes('MonitorLUT'));
});
