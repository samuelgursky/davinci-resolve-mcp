const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const { addMediaClip } = require('../author-project');
const { parseDRT } = require('../../drt-format');

test('addMediaClip authors a project with the target media + patched specs', async () => {
  const { buffer, timelineName, mediaFile } = await addMediaClip({
    mediaFile: '/media/Sample Montage.mp4',
    spec: { width: 1280, height: 960, frameCount: 3094, fps: 30000 / 1001 },
    timelineName: 'Authored Cut', durationFrames: 240,
  });
  assert.strictEqual(timelineName, 'Authored Cut');
  const parsed = await parseDRT(buffer);
  const clip = parsed.timelines[0].videoTracks[0].clips[0];
  assert.ok(clip.mediaFilePath.includes('Sample Montage.mp4'), 'clip points at target file');
  assert.strictEqual(clip.duration, 240, 'clip trimmed to durationFrames');
  const JSZip = require('jszip');
  const zip = await JSZip.loadAsync(buffer);
  const mp = await zip.file('MediaPool/Master/MpFolder.xml').async('string');
  assert.ok(mp.includes('<Name>Authored Cut</Name>'), 'timeline renamed');
  assert.ok(mp.includes('<Name>Sample Montage.mp4</Name>'), 'media entry renamed');
  const geo = Buffer.from(mp.match(/<Geometry>([0-9a-fA-F]+)<\/Geometry>/)[1], 'hex');
  assert.ok(geo.includes(Buffer.from([0, 0, 5, 0])), 'width 1280 patched');  // 1280 = 0x500
});

test('addMediaClip validates inputs', async () => {
  await assert.rejects(() => addMediaClip({ mediaFile: 'rel.mov', spec: { width: 1, height: 1, frameCount: 1, fps: 24 } }), /absolute/);
  await assert.rejects(() => addMediaClip({ mediaFile: '/a/b.mov', spec: { width: 1 } }), /spec must/);
});
