'use strict';

/**
 * packaging/media-ops.js — the volume-tier media operations (spec §12, P4):
 * consolidate (trim used range + handles, transcode) and full (complete copy).
 * Require mounted media; the render node / post-assistant runs these. ffmpeg/fs.
 */

const { spawnSync } = require('child_process');
const fs = require('fs');

/**
 * Consolidate a clip: trim [usedIn-handles, usedOut+handles] and transcode.
 * Seek-based (fast, frame-accurate on intra codecs). Returns the trimmed path +
 * the frame window it covers.
 */
function consolidateClip(srcPath, opts) {
  const { usedIn, usedOut, handles = 0, frameRate = 24, outPath, codec = 'prores', ffmpegPath = 'ffmpeg' } = opts;
  const inFrame = Math.max(0, usedIn - handles);
  const outFrame = usedOut + handles;
  const ss = (inFrame / frameRate).toFixed(6);
  const dur = ((outFrame - inFrame) / frameRate).toFixed(6);
  const codecArgs = codec === 'prores'
    ? ['-c:v', 'prores_ks', '-profile:v', '0']
    : ['-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p'];
  const r = spawnSync(ffmpegPath, ['-v', 'error', '-ss', ss, '-i', srcPath, '-t', dur, ...codecArgs, '-an', '-y', outPath], { encoding: 'utf8', timeout: 600000 });
  if (r.status !== 0) throw new Error(`consolidateClip: ffmpeg failed: ${(r.stderr || '').slice(-300)}`);
  return { path: outPath, inFrame, outFrame, frames: outFrame - inFrame, handles };
}

/** Probe the frame count of a media file. */
function probeFrameCount(p, ffprobePath = 'ffprobe') {
  const r = spawnSync(ffprobePath, ['-v', 'error', '-select_streams', 'v:0', '-count_frames', '-show_entries', 'stream=nb_read_frames', '-of', 'default=nokey=1:noprint_wrappers=1', p], { encoding: 'utf8', timeout: 120000 });
  return r.status === 0 ? parseInt((r.stdout || '').trim(), 10) : null;
}

/** Full media mode: copy the complete source into the package (byte-identical). */
function copyFull(srcPath, outPath) {
  fs.copyFileSync(srcPath, outPath);
  return { path: outPath, bytes: fs.statSync(outPath).size, sourceBytes: fs.statSync(srcPath).size };
}

/**
 * Extract a single source frame to an image — for frame-verification of a relink.
 * Input-seek is frame-accurate for all-intra codecs (ProRes scans are intra-only),
 * and fast (no decode from the head). Returns the output path.
 */
function extractFrame(srcPath, frame, outPath, opts = {}) {
  const { frameRate = 24, ffmpegPath = 'ffmpeg' } = opts;
  const ss = (Math.max(0, frame) / frameRate).toFixed(6);
  const r = spawnSync(ffmpegPath, ['-v', 'error', '-ss', ss, '-i', srcPath, '-frames:v', '1', '-y', outPath], { encoding: 'utf8', timeout: 600000 });
  if (r.status !== 0) throw new Error(`extractFrame: ffmpeg failed: ${(r.stderr || '').slice(-300)}`);
  return outPath;
}

module.exports = { consolidateClip, probeFrameCount, copyFull, extractFrame };
