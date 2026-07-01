'use strict';

/**
 * adapters/frame-sampler.js — the FrameSampler adapter interface (spec §3.2).
 *
 * Extract a frame from a media reference at a given SOURCE frame and resolution.
 * The core never touches ffmpeg/Resolve directly — a surface injects a concrete
 * sampler (render-node ffmpeg in the cloud, local ffmpeg in the post-assistant).
 * Output matches the comparator's decoded-frame shape ({data,width,height},
 * grayscale, 0..1) so a sampled frame flows straight into compare/.
 */

class FrameSampler {
  /**
   * @param {string|object} mediaRef  resolved media (path / asset+version / stream)
   * @param {number} frame            SOURCE frame to extract (the Oracle's derivedSampleFrame)
   * @param {{width:number,height:number}} size
   * @returns {Promise<{data:Float64Array,width:number,height:number}>}
   */
  // eslint-disable-next-line class-methods-use-this, no-unused-vars
  async sample(mediaRef, frame, size) {
    throw new Error('FrameSampler.sample must be implemented by an adapter');
  }
}

/** Duck-typed check that an object satisfies the FrameSampler interface. */
function isFrameSampler(obj) {
  return !!obj && typeof obj.sample === 'function';
}

/**
 * A deterministic in-memory sampler for tests — no media, no ffmpeg. The frame
 * content is a stable hash of (mediaRef, frame), so the same request always
 * yields the same pixels and different requests differ.
 */
class FakeFrameSampler extends FrameSampler {
  // eslint-disable-next-line class-methods-use-this
  async sample(mediaRef, frame, { width, height }) {
    const n = width * height;
    const data = new Float64Array(n);
    let h = 2166136261 >>> 0;
    const key = `${typeof mediaRef === 'object' ? JSON.stringify(mediaRef) : mediaRef}:${frame}`;
    for (let i = 0; i < key.length; i++) {
      h ^= key.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    for (let i = 0; i < n; i++) {
      h ^= i;
      h = Math.imul(h, 16777619);
      data[i] = ((h >>> 8) & 0xff) / 255;
    }
    return { data, width, height };
  }
}

module.exports = { FrameSampler, FakeFrameSampler, isFrameSampler };
