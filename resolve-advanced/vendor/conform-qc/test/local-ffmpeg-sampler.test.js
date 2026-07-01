'use strict';

/**
 * Local ffmpeg FrameSampler test. Generates a tiny LOSSLESS test video where
 * frame n has a known uniform luma (28*n), then samples specific frames and
 * asserts both the level AND that the correct frame was selected (frame 5 is
 * brighter than frame 2 — proving it doesn't just grab frame 0).
 *
 * Skips if ffmpeg is unavailable. No committed binaries — the video is built in
 * a temp dir at test time.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync, spawnSync } = require('node:child_process');

const { LocalFfmpegFrameSampler } = require('../adapters/local-ffmpeg-sampler');

const FFMPEG = 'ffmpeg';
const haveFfmpeg = spawnSync(FFMPEG, ['-version'], { stdio: 'ignore' }).status === 0;
const SKIP = haveFfmpeg ? false : 'ffmpeg not available — skipping';

function meanOf(frameObj) {
  let s = 0;
  for (let i = 0; i < frameObj.data.length; i++) s += frameObj.data[i];
  return s / frameObj.data.length;
}

test('LocalFfmpegFrameSampler: samples the requested source frame (level + selection)', { skip: SKIP }, async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'conformqc-ffmpeg-'));
  const video = path.join(dir, 'ramp.mkv');
  try {
    // 8 frames, frame n uniform luma = 28*n, lossless ffv1 so levels survive.
    execFileSync(
      FFMPEG,
      [
        '-v', 'error', '-y',
        '-f', 'lavfi', '-i', 'color=c=black:s=64x48:r=10:d=1',
        '-vf', "geq=lum='clip(28*N,0,255)':cb=128:cr=128,format=gray",
        '-frames:v', '8', '-c:v', 'ffv1', video,
      ],
      { stdio: 'ignore' },
    );

    const sampler = new LocalFfmpegFrameSampler();
    const size = { width: 32, height: 24 };
    const f2 = await sampler.sample(video, 2, size);
    const f5 = await sampler.sample(video, 5, size);

    assert.equal(f2.width, 32);
    assert.equal(f2.height, 24);
    // Expected normalized luma ~28*n/255 (loose: TV/full-range + build variance).
    assert.ok(Math.abs(meanOf(f2) - (28 * 2) / 255) < 0.07, `frame 2 mean ${meanOf(f2).toFixed(3)} ~ ${(56 / 255).toFixed(3)}`);
    assert.ok(Math.abs(meanOf(f5) - (28 * 5) / 255) < 0.07, `frame 5 mean ${meanOf(f5).toFixed(3)} ~ ${(140 / 255).toFixed(3)}`);
    // Selection correctness (the core check): frame 5 is clearly brighter than
    // frame 2 — proves it samples the REQUESTED frame, not always frame 0.
    assert.ok(meanOf(f5) > meanOf(f2) + 0.1, 'frame 5 must be brighter than frame 2');
    // eslint-disable-next-line no-console
    console.log(`[ffmpeg-sampler] frame2 mean ${meanOf(f2).toFixed(3)}, frame5 mean ${meanOf(f5).toFixed(3)} (selection verified)`);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
