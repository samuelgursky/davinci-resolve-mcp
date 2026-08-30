// Issue #167: the hand-typed FRAME_RATE_ENCODINGS table stored 30000/1001 for
// 23.976, 29.9739 for 29.97, and 0.9367 for 59.94, while validate stayed
// green. Issue #168: fractional StartFrame at NTSC rates, startFrame ignored.
const { test } = require('node:test');
const assert = require('node:assert');
const { encodeFrameRate, snapFrameRate } = require('../xml-builder');
const { buildSeqContainerFile } = require('../seq-container-builder');

function decode(hex) {
  return Buffer.from(hex, 'hex').readDoubleLE(0);
}

test('rounded NTSC decimals snap to their exact rationals', () => {
  assert.ok(Math.abs(decode(encodeFrameRate(23.976)) - 24000 / 1001) < 1e-9);
  assert.ok(Math.abs(decode(encodeFrameRate(29.97)) - 30000 / 1001) < 1e-9);
  assert.ok(Math.abs(decode(encodeFrameRate(59.94)) - 60000 / 1001) < 1e-9);
  assert.ok(Math.abs(decode(encodeFrameRate(23.98)) - 24000 / 1001) < 1e-9);
});

test('exact rationals and integers round-trip untouched', () => {
  for (const fps of [24, 25, 30, 48, 50, 60, 30000 / 1001, 24000 / 1001, 60000 / 1001]) {
    assert.ok(Math.abs(decode(encodeFrameRate(fps)) - snapFrameRate(fps)) < 1e-12);
    if (Number.isInteger(fps)) {
      assert.strictEqual(snapFrameRate(fps), fps, `integer ${fps} must not snap`);
    }
  }
});

test('the three formerly-wrong table rates never reappear', () => {
  // The old table's values, byte for byte. None may ever be produced again
  // for the inputs that used to hit them.
  assert.notStrictEqual(encodeFrameRate(23.976), '286b55e253f83d40');
  assert.notStrictEqual(encodeFrameRate(29.97), '286b55e253f93d40');
  assert.notStrictEqual(encodeFrameRate(59.94), '286b55e253f9ed3f');
});

test('StartFrame counts NOMINAL frames and startFrame wins', async () => {
  // Measured against Resolve itself (Studio 19.1.3.7): 01:00:00:00 at 29.97
  // reads GetStartFrame 108000 = 3600 x 30, and 23.976 reads 86400 = 3600 x
  // 24 — SMPTE NDF counts by the integer base, not the exact rate. Both the
  // pre-#168 fractional product and its first rounded fix (107892) were wrong.
  const tl = { name: 'T', videoTracks: [], audioTracks: [] };
  const ntsc30 = await buildSeqContainerFile(tl, {
    frameRate: 30000 / 1001, startTimecode: '01:00:00:00',
  });
  assert.match(ntsc30, /<StartFrame>108000<\/StartFrame>/);
  const ntsc24 = await buildSeqContainerFile(tl, {
    frameRate: 24000 / 1001, startTimecode: '01:00:00:00',
  });
  assert.match(ntsc24, /<StartFrame>86400<\/StartFrame>/);
  const explicit = await buildSeqContainerFile(tl, {
    frameRate: 30000 / 1001, startTimecode: '01:00:00:00', startFrame: 99999,
  });
  assert.match(explicit, /<StartFrame>99999<\/StartFrame>/);
});

test('drop-frame start timecode subtracts the dropped numbers', async () => {
  // 00:01:00;02 DF at 29.97: minute 1 drops 2 numbers -> 1800 + 2 - 2 = 1800.
  const tl = { name: 'T', videoTracks: [], audioTracks: [] };
  const df = await buildSeqContainerFile(tl, {
    frameRate: 30000 / 1001, startTimecode: '00:01:00;02',
  });
  assert.match(df, /<StartFrame>1800<\/StartFrame>/);
});
