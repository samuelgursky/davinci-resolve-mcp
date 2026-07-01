'use strict';

/**
 * adapters/local-ffmpeg-sampler.js — the local FrameSampler impl (spec §3.2).
 *
 * Extracts a single SOURCE frame from a media file via local ffmpeg and decodes
 * it to the normalized-grayscale shape the comparator consumes. This is the
 * post-assistant / local-surface sampler; the render node injects its own
 * ffmpeg-over-R2 sampler with the same interface.
 */

const { spawn } = require('child_process');
const { FrameSampler } = require('./frame-sampler');
const { decodeGrayNormalized } = require('../compare/decode');

/** Run ffmpeg, capture stdout (the extracted PNG) as a Buffer. */
function runFfmpeg(args, ffmpegPath) {
  return new Promise((resolve, reject) => {
    const proc = spawn(ffmpegPath, args, { stdio: ['ignore', 'pipe', 'pipe'] });
    const out = [];
    const err = [];
    proc.stdout.on('data', (d) => out.push(d));
    proc.stderr.on('data', (d) => err.push(d));
    proc.on('error', reject);
    proc.on('close', (code) => {
      if (code === 0) resolve(Buffer.concat(out));
      else reject(new Error(`ffmpeg exited ${code}: ${Buffer.concat(err).toString().slice(-500)}`));
    });
  });
}

class LocalFfmpegFrameSampler extends FrameSampler {
  constructor({ ffmpegPath = 'ffmpeg' } = {}) {
    super();
    this.ffmpegPath = ffmpegPath;
  }

  /**
   * @param {string} mediaRef  local file path
   * @param {number} frame     0-based source frame index
   * @param {{width:number,height:number}} size
   */
  async sample(mediaRef, frame, size) {
    if (typeof mediaRef !== 'string') {
      throw new Error('LocalFfmpegFrameSampler: mediaRef must be a local file path');
    }
    // Select exactly the requested frame, emit one PNG to stdout.
    const args = [
      '-v', 'error',
      '-i', mediaRef,
      '-vf', `select=eq(n\\,${Math.round(frame)})`,
      '-vframes', '1',
      '-f', 'image2pipe',
      '-c:v', 'png',
      '-',
    ];
    const png = await runFfmpeg(args, this.ffmpegPath);
    if (!png || png.length === 0) {
      throw new Error(`LocalFfmpegFrameSampler: no frame ${frame} extracted from ${mediaRef}`);
    }
    return decodeGrayNormalized(png, size);
  }
}

module.exports = { LocalFfmpegFrameSampler };
