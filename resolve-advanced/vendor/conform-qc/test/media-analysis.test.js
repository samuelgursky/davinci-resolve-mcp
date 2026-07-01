'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { parseFfprobe, aspectOf, bitDepth, parseRate, qualityRank } = require('../repair/media-analysis');

const PRORES_4K = JSON.stringify({
  streams: [{
    codec_type: 'video', codec_name: 'prores', profile: 'Apple ProRes 4444 XQ',
    width: 4096, height: 2612, pix_fmt: 'yuva444p10le', sample_aspect_ratio: '1:1',
    display_aspect_ratio: '1024:653', r_frame_rate: '24/1', avg_frame_rate: '24/1',
    color_primaries: 'bt709', color_transfer: 'bt709', bits_per_raw_sample: '10',
  }],
  format: { duration: '120.500' },
});

const H264_PROXY = JSON.stringify({
  streams: [{ codec_type: 'video', codec_name: 'h264', width: 2048, height: 1306, pix_fmt: 'yuv420p', r_frame_rate: '24/1' }],
  format: {},
});

test('parseFfprobe: normalizes ProRes 4444 XQ', () => {
  const i = parseFfprobe(PRORES_4K, '/hr/ProRes4444XQ/shot.mov');
  assert.equal(i.ok, true);
  assert.equal(i.width, 4096);
  assert.equal(i.height, 2612);
  assert.equal(i.aspect, 1.5681); // 4096/2612 * 1
  assert.equal(i.codec, 'prores');
  assert.equal(i.bitDepth, 10);
  assert.equal(i.fps, 24);
  assert.equal(i.durationSec, 120.5);
});

test('parseFfprobe: no video stream / bad json fail gracefully', () => {
  assert.equal(parseFfprobe('{"streams":[]}', '/x').ok, false);
  assert.equal(parseFfprobe('not json', '/x').ok, false);
});

test('aspectOf: applies SAR for anamorphic', () => {
  assert.equal(aspectOf(1920, 1080, '1:1'), 1.7778);
  assert.equal(aspectOf(1440, 1080, '4:3'), 1.7778); // anamorphic HD -> 16:9
});

test('bitDepth: from raw sample then pix_fmt fallback', () => {
  assert.equal(bitDepth({ bits_per_raw_sample: '12' }), 12);
  assert.equal(bitDepth({ pix_fmt: 'yuv422p10le' }), 10);
  assert.equal(bitDepth({ pix_fmt: 'yuv420p' }), 8);
});

test('parseRate: handles ntsc fractional', () => {
  assert.equal(parseRate('24000/1001'), 23.976024);
  assert.equal(parseRate('24/1'), 24);
});

test('qualityRank: original ProRes beats h264 proxy', () => {
  const hr = parseFfprobe(PRORES_4K, '/hr/ProRes4444XQ/shot.mov');
  const px = parseFfprobe(H264_PROXY, '/proxy/shot.mp4');
  assert.ok(qualityRank(hr) > qualityRank(px));
  // a test-tree copy ranks below the production original
  const testCopy = parseFfprobe(PRORES_4K, '/hr/Tests/shot.mov');
  assert.ok(qualityRank(hr) > qualityRank(testCopy));
});
