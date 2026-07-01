const test = require('node:test');
const assert = require('node:assert');
const mb = require('../media-blobs');

// Samples captured from real Resolve 21 exports (canary).
test('decodeResolutionBlob matches a real sample (1920x1080)', () => {
  assert.deepStrictEqual(mb.decodeResolutionBlob('00000000000007800000000000000438'), { width: 1920, height: 1080 });
});
test('decodeRateBlob: FrameRate=24, MediaFrameRate=29.97', () => {
  assert.strictEqual(mb.decodeRateBlob('00000000000038400000000000000000'), 24);
  assert.ok(Math.abs(mb.decodeRateBlob('286b55e253f83d400000000000000000') - 30000 / 1001) < 1e-9);
});
test('decodeMediaExtentsBlob: start 3600s, ~152.67s', () => {
  const e = mb.decodeMediaExtentsBlob('000000000020ac405055555555156340');
  assert.strictEqual(e.startSeconds, 3600);
  assert.ok(Math.abs(e.durationSeconds - 152.666) < 0.01);
});
test('round-trips', () => {
  assert.deepStrictEqual(mb.decodeResolutionBlob(mb.encodeResolutionBlob({ width: 3840, height: 2160 })), { width: 3840, height: 2160 });
  assert.strictEqual(mb.decodeRateBlob(mb.encodeRateBlob(23.976)), 23.976);
  const ex = { startSeconds: 3600, durationSeconds: 10.5 };
  assert.deepStrictEqual(mb.decodeMediaExtentsBlob(mb.encodeMediaExtentsBlob(ex)), ex);
  // encodeResolutionBlob reproduces the real 1080p sample exactly
  assert.strictEqual(mb.encodeResolutionBlob({ width: 1920, height: 1080 }), '00000000000007800000000000000438');
});
