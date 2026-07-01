// Unit: offline media relink — rewrite the media path in the Media Pool blobs + plain text.
// Live Resolve acceptance proven manually (lint: 0 offline; re-export blob shows the new path)
// — see resolve21-schema-reconciliation.md.

const test = require('node:test');
const assert = require('node:assert');
const path = require('node:path');
const fs = require('node:fs');
const { relinkMedia } = require('../relink-media');

const FIXTURE = path.resolve(
  __dirname,
  '../../../docs/design/drp-drx-drt-closeout-harness/fixtures/canary-resolve21.drp',
);
const FROM = '/media/Sample Clip.mp4';

async function videoClipBlob(buffer) {
  const JSZip = require('jszip');
  const zip = await JSZip.loadAsync(buffer);
  const mp = await zip.file('MediaPool/Master/MpFolder.xml').async('string');
  const m = mp.match(/<Video>\s*<BtVideoInfo\b[\s\S]*?<Clip>([0-9a-fA-F]*)<\/Clip>/);
  return Buffer.from(m[1], 'hex');
}
async function timelineMediaPaths(buffer) {
  const JSZip = require('jszip');
  const zip = await JSZip.loadAsync(buffer);
  const out = [];
  for (const n of Object.keys(zip.files)) {
    if (!/SeqContainer\/[^/]+\.xml$/.test(n)) continue;
    const x = await zip.files[n].async('string');
    for (const p of x.match(/<MediaFilePath>([^<]+)<\/MediaFilePath>/g) || []) out.push(p);
  }
  return out;
}

test('relinkMedia repoints the blob path AND the plain-text MediaFilePath', async (t) => {
  if (!fs.existsSync(FIXTURE)) { t.skip(`fixture missing: ${FIXTURE}`); return; }
  const TO = '/Volumes/ARCHIVE/relinked/My Cut Final.mov'; // different dir + name + length

  const res = await relinkMedia(FIXTURE, { from: FROM, to: TO });
  assert.strictEqual(res.relinked.length, 1);
  assert.ok(res.relinked[0].blobsEdited >= 1, 'at least the video blob edited');
  assert.ok(res.relinked[0].textRefs >= 1, 'plain-text refs edited');

  const blob = await videoClipBlob(res.buffer);
  assert.ok(blob.includes(Buffer.from('/Volumes/ARCHIVE/relinked', 'utf8')), 'new dir in blob');
  assert.ok(blob.includes(Buffer.from('My Cut Final.mov', 'utf8')), 'new filename in blob');
  assert.ok(!blob.includes(Buffer.from('Sample Clip.mp4', 'utf8')), 'old filename gone from blob');

  // The 4-byte BE payload-length header must stay consistent (len = blob.length - 8).
  assert.strictEqual(blob.readUInt32BE(4), blob.length - 8, 'blob payload-length header updated');

  const paths = await timelineMediaPaths(res.buffer);
  assert.ok(paths.every((p) => p.includes(TO)), 'timeline MediaFilePath repointed');
});

test('relinkMedia supports multiple mappings', async (t) => {
  if (!fs.existsSync(FIXTURE)) { t.skip(`fixture missing: ${FIXTURE}`); return; }
  const res = await relinkMedia(FIXTURE, {
    mappings: [{ from: FROM, to: '/new/loc/clip-a.mov' }, { from: '/never/here.mov', to: '/x/y.mov' }],
  });
  assert.strictEqual(res.relinked.length, 2);
  assert.ok(res.relinked[0].blobsEdited >= 1);
  assert.strictEqual(res.relinked[1].blobsEdited, 0, 'absent source maps to nothing');
});

test('relinkMedia requires absolute paths', async () => {
  await assert.rejects(() => relinkMedia(FIXTURE, { from: 'rel/a.mov', to: '/abs/b.mov' }), /absolute/);
});

test('relinkMedia requires a mapping', async () => {
  await assert.rejects(() => relinkMedia(FIXTURE, {}), /from.*to|mappings/);
});

const { repointMedia } = require('../relink-media');

test('repointMedia relinks the path AND patches resolution/frames/fps in the matching entry', async (t) => {
  if (!fs.existsSync(FIXTURE)) { t.skip(`fixture missing: ${FIXTURE}`); return; }
  const TO = '/Volumes/ARCHIVE/new clip.mov';
  const res = await repointMedia(FIXTURE, {
    from: FROM, to: TO,
    fromSpec: { width: 352, height: 262, frameCount: 4576, fps: 30000 / 1001 },
    toSpec: { width: 1920, height: 1080, frameCount: 240, fps: 24 },
  });
  assert.strictEqual(res.specPatched[0].patched, true);

  const JSZip = require('jszip');
  const zip = await JSZip.loadAsync(res.buffer);
  const mp = await zip.file('MediaPool/Master/MpFolder.xml').async('string');
  // entry renamed + geometry/time patched to target values
  const entry = mp.match(/<Sm2MpVideoClip\b[\s\S]*?<\/Sm2MpVideoClip>/)[0];
  assert.ok(entry.includes('<Name>new clip.mov</Name>'), 'entry renamed');
  const geo = Buffer.from(entry.match(/<Geometry>([0-9a-fA-F]+)<\/Geometry>/)[1], 'hex');
  assert.ok(geo.includes(Buffer.from([0, 0, 7, 128])), 'width 1920 (0x780) patched');
  assert.ok(geo.includes(Buffer.from([0, 0, 4, 56])), 'height 1080 (0x438) patched');
  assert.ok(!geo.includes(Buffer.from([0, 0, 1, 96])), 'old width 352 gone');
  const time = Buffer.from(entry.match(/<Time>([0-9a-fA-F]+)<\/Time>/)[1], 'hex');
  assert.ok(time.includes(Buffer.from([0, 0, 0, 240])), 'frame count 240 patched');
});

test('repointMedia without specs just relinks (no patch)', async (t) => {
  if (!fs.existsSync(FIXTURE)) { t.skip(`fixture missing: ${FIXTURE}`); return; }
  const res = await repointMedia(FIXTURE, { from: FROM, to: '/x/y.mov' });
  assert.strictEqual(res.specPatched[0].patched, false);
  assert.ok(res.relinked[0].blobsEdited >= 1);
});
