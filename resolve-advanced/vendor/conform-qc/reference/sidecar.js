'use strict';

/**
 * reference/sidecar.js — Tier B ground truth (spec §7): a clean review render
 * keyed by a TC sidecar (EDL / ALE / source-TC). Content is verified by frame;
 * IDENTITY comes from the sidecar (no OCR). Lower-friction than Tier A when a
 * burn-in isn't available but a sidecar is.
 *
 * Produces a referenceProvider(clip) for ops/verify — pure (takes the sidecar +
 * a frame-path resolver; no IO of its own).
 */

/**
 * @param {object[]|object} sidecar  entries { seqstart, sourceTc, sourceName, referenceFrame, derivedFrame?, label? }
 *                                    (array, or an object keyed by seqstart)
 * @param {(p:string)=>string} [resolveFramePath]  map a sidecar frame ref to a real path
 * @returns {(clip:object)=>object|null} a verify referenceProvider
 */
function tcSidecarProvider(sidecar, resolveFramePath) {
  const map = Array.isArray(sidecar)
    ? Object.fromEntries(sidecar.map((e) => [e.seqstart, e]))
    : sidecar || {};
  const resolve = resolveFramePath || ((p) => p);
  return function referenceProvider(clip) {
    const e = map[clip.seqstart];
    if (!e) return null; // no sidecar entry => Tier C for this cut
    return {
      referencePath: resolve(e.referenceFrame),
      derivedPath: e.derivedFrame ? resolve(e.derivedFrame) : null,
      tier: 'B',
      label: e.label,
      identity: { sourceTc: e.sourceTc || null, sourceName: e.sourceName || null },
    };
  };
}

module.exports = { tcSidecarProvider };
