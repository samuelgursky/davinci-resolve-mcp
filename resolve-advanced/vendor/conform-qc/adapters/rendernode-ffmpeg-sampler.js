'use strict';

/**
 * adapters/rendernode-ffmpeg-sampler.js — the render-node FrameSampler (spec
 * §3.2, P0) over volume/R2 media. Unlike the local sampler's decode-from-start
 * (select=eq(n,N)), this SEEKS by timestamp (-ss before -i), which is fast on
 * multi-GB sources and frame-accurate on all-intra codecs (ProRes/DNxHR). A
 * MediaResolver maps a turnover path to the real media path.
 */

const { spawnSync } = require('child_process');
const { FrameSampler } = require('./frame-sampler');
const { decodeGrayNormalized } = require('../compare/decode');

/** Simple prefix-remap MediaResolver (e.g. /Volumes/TURNOVER/PROJECT → /Volumes/ONLINE/PROJECT). */
class PrefixRemapMediaResolver {
  constructor(from, to) {
    this.from = from;
    this.to = to;
  }

  resolve(p) {
    return this.from && p.startsWith(this.from) ? this.to + p.slice(this.from.length) : p;
  }
}

class RenderNodeFrameSampler extends FrameSampler {
  constructor({ frameRate = 24, mediaResolver = null, ffmpegPath = 'ffmpeg' } = {}) {
    super();
    this.frameRate = frameRate;
    this.mediaResolver = mediaResolver;
    this.ffmpegPath = ffmpegPath;
  }

  async sample(mediaRef, frame, size) {
    const realPath = this.mediaResolver ? this.mediaResolver.resolve(String(mediaRef)) : String(mediaRef);
    const ts = (Math.max(0, frame) / this.frameRate).toFixed(6);
    const r = spawnSync(
      this.ffmpegPath,
      ['-v', 'error', '-ss', ts, '-i', realPath, '-frames:v', '1', '-f', 'image2pipe', '-c:v', 'png', '-'],
      { encoding: 'buffer', maxBuffer: 256 * 1024 * 1024, timeout: 120000 },
    );
    if (r.status !== 0 || !r.stdout || r.stdout.length === 0) {
      throw new Error(`RenderNodeFrameSampler: ffmpeg failed for ${realPath}@${frame}: ${(r.stderr || '').toString().slice(-300)}`);
    }
    return decodeGrayNormalized(r.stdout, size);
  }
}

module.exports = { RenderNodeFrameSampler, PrefixRemapMediaResolver };
