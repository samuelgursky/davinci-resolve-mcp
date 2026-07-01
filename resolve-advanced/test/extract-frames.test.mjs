/**
 * extract_frames (Phase-1a) — the display-referred front door with a HARD log-refuse.
 * Pure unit tests for the colorspace gate + position math (no media), plus real-media
 * extraction/refuse tests gated on ffmpeg being on PATH.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { assessColorspace, resolvePosition, extractFrames } from '../server/extract-frames.mjs';
import { hasFfmpeg, hasFfprobe } from '../server/capabilities.mjs';

const FF = hasFfmpeg() && hasFfprobe();

// ── pure gate + position math (always run) ────────────────────────────
test('assessColorspace accepts display transfers, refuses log', () => {
  assert.equal(assessColorspace({ colorTransfer: 'bt709' }).ok, true);
  assert.equal(assessColorspace({ colorTransfer: 'iec61966-2-1' }).ok, true);
  const log = assessColorspace({ colorTransfer: 'log316' });
  assert.equal(log.ok, false);
  assert.match(log.reason, /LOG\/scene-referred/);
  // A camera-log name substring anywhere → refuse.
  assert.equal(assessColorspace({ colorTransfer: 'arri-logc' }).ok, false);
});

test('assessColorspace refuses unknown unless the caller asserts display-referred', () => {
  assert.equal(assessColorspace({ colorTransfer: 'unknown' }).ok, false);
  assert.equal(assessColorspace({ colorTransfer: 'unknown' }, { displayReferred: true }).ok, true);
});

test('resolvePosition handles frame index, midpoint, and TC', () => {
  const probe = { frameCount: 100, fps: 25 };
  assert.equal(resolvePosition(42, probe), 42);
  assert.equal(resolvePosition('midpoint', probe), 50);
  assert.equal(resolvePosition(undefined, probe), 50);
  assert.equal(resolvePosition('00:00:02:00', probe), 50); // 2s @ 25fps
});

// ── real media (gated) ────────────────────────────────────────────────
// Display clip: tag the Rec.709 matrix (survives muxing; the transfer tag often doesn't).
function makeDisplayClip(file) {
  const r = spawnSync(
    'ffmpeg',
    [
      '-v',
      'error',
      '-f',
      'lavfi',
      '-i',
      'testsrc=duration=1:size=64x48:rate=10',
      '-frames:v',
      '10',
      '-colorspace',
      'bt709',
      '-color_primaries',
      'bt709',
      '-pix_fmt',
      'yuv420p',
      '-y',
      file,
    ],
    { encoding: 'utf8' },
  );
  if (r.status !== 0) throw new Error(`ffmpeg gen failed: ${r.stderr}`);
}
// Untagged clip: no color metadata → probes as unknown (the camera-log-lookalike case).
function makeUntaggedClip(file) {
  const r = spawnSync(
    'ffmpeg',
    ['-v', 'error', '-f', 'lavfi', '-i', 'testsrc=duration=1:size=64x48:rate=10', '-frames:v', '10', '-pix_fmt', 'yuv420p', '-y', file],
    { encoding: 'utf8' },
  );
  if (r.status !== 0) throw new Error(`ffmpeg gen failed: ${r.stderr}`);
}

test('extractFrames writes a PNG from a display-referred source', { skip: !FF }, async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ef-'));
  const src = path.join(dir, 'disp.mp4');
  makeDisplayClip(src);
  const r = await extractFrames([{ id: 'A', source: src, at: 'midpoint' }], { outDir: path.join(dir, 'out') });
  assert.ok(r.frames.A, `expected a frame, got ${JSON.stringify(r.skipped)}`);
  assert.ok(fs.statSync(r.frames.A).size > 0, 'PNG has bytes');
});

test('extractFrames refuses an untagged (unknown-space) source, then extracts when asserted', { skip: !FF }, async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ef-'));
  const src = path.join(dir, 'unknown.mp4');
  makeUntaggedClip(src);
  // Refused by default (skip-not-fake — could be camera log).
  const refused = await extractFrames([{ id: 'U', source: src, at: 'midpoint' }], { outDir: path.join(dir, 'out') });
  assert.ok(!refused.frames.U, 'no frame faked for an unknown source');
  assert.ok(refused.skipped.some((s) => s.id === 'U' && /UNKNOWN/.test(s.reason)));
  // Extracts only when the caller explicitly asserts display-referred.
  const ok = await extractFrames([{ id: 'U', source: src, at: 'midpoint', displayReferred: true }], { outDir: path.join(dir, 'out2') });
  assert.ok(ok.frames.U, `expected a frame with assertion, got ${JSON.stringify(ok.skipped)}`);
});
