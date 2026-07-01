/**
 * ffmpeg sampler adapter for frame-QC (Phase 9 wiring). Builds the two injected
 * samplers qcSnapshot expects, from real media:
 * sampleReference(cut) — the reference render at the cut's record position (burn-in
 * masked, brightness-robust).
 * sampleConform(cut) — the highres source at oracle_source_frame, scaled by the
 * corrected zoom and centre-cropped to the sequence frame (the picture Resolve
 * shows). Residual pan is left to classify's findOffset → OFFSET (still flagged).
 *
 * Needs system ffmpeg on PATH + the optional `sharp` dep (decodeGrayNormalized). Pure
 * IO — the comparison/orchestration lives in qc-frame.mjs.
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const metrics = require('../vendor/conform-qc/compare/metrics.js');

function grab(src, sec, out, vf, ffmpegPath) {
  const a = ['-v', 'error', '-y', '-ss', sec.toFixed(3), '-i', src, '-frames:v', '1'];
  if (vf) a.push('-vf', vf);
  a.push(out);
  return spawnSync(ffmpegPath || 'ffmpeg', a, { timeout: 60000 }).status === 0 && fs.existsSync(out);
}

/**
 * opts: { referenceMovie, mediaMap?:{basename:path}, refOffset=0, fps=24, seqW, seqH,
 * hrW, hrH, decodeW=1200, decodeH=720, ffmpegPath?, tmpDir?, burnInRegions? }
 * Returns { sampleConform, sampleReference, mask, width, height }.
 */
export function makeSamplers(opts = {}) {
  const { decodeGrayNormalized } = require('../vendor/conform-qc/compare/decode.js'); // lazy → sharp
  const DW = opts.decodeW || 1200;
  const DH = opts.decodeH || 720;
  const fps = opts.fps || 24;
  const tmp = opts.tmpDir || fs.mkdtempSync(path.join(os.tmpdir(), 'qc-sample-'));
  const mask = metrics.buildBurnInMask(DW, DH, opts.burnInRegions);
  let n = 0;

  const sampleReference = async (cut) => {
    if (cut.record_start == null) return null;
    const frame = cut.record_start + (opts.refOffset || 0);
    const p = path.join(tmp, `ref-${n}.png`);
    if (!grab(opts.referenceMovie, frame / fps, p, `scale=${DW}:${DH}`, opts.ffmpegPath)) return null;
    // classify()/referenceIsBlank() consume a raw Float64Array — unwrap the decode result.
    return (await decodeGrayNormalized(p, { width: DW, height: DH })).data;
  };

  const sampleConform = async (cut) => {
    const src = (opts.mediaMap && opts.mediaMap[cut.source_basename]) || cut.source_path;
    if (!src || cut.oracle_source_frame == null) return null;
    const zoom = cut.scale_corrected != null ? cut.scale_corrected / 100 : 1;
    const H = Math.round(opts.seqH * zoom);
    const W = Math.round(H * (opts.hrW / opts.hrH));
    const vf = `scale=${W}:${H},crop=${opts.seqW}:${opts.seqH}:(iw-${opts.seqW})/2:(ih-${opts.seqH})/2,scale=${DW}:${DH}`;
    const p = path.join(tmp, `conf-${n++}.png`);
    if (!grab(src, cut.oracle_source_frame / fps, p, vf, opts.ffmpegPath)) return null;
    // classify() consumes a raw Float64Array — unwrap the decode result.
    return (await decodeGrayNormalized(p, { width: DW, height: DH })).data;
  };

  return { sampleConform, sampleReference, mask, width: DW, height: DH, tmpDir: tmp };
}
