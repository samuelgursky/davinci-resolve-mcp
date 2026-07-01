'use strict';

/**
 * compare/locate.js — find a clip's true SOURCE FRAME from a reference render
 * WITHOUT relying on a burn-in timecode.
 *
 * The fast path (when the reference carries a filename/source-TC burn-in) is to
 * OCR the timecode and read the frame directly. When the reference has NO burn-in,
 * the reference frame's *content* is still the ground truth: we search the source
 * for the frame whose conformed picture best matches the reference, by structure
 * (brightness/contrast-invariant SSIM, so a temped grade still matches). This is
 * the automated form of eyeballing an offline-reference wipe.
 *
 * IO is injected — this module stays pure-ish (no ffmpeg/decode of its own):
 *   conformAt(frame)  -> Promise<Float64Array>  the SOURCE conformed (scaled/
 *                        cropped the way the timeline frames it) and decoded to a
 *                        DW×DH grayscale buffer, for candidate source `frame`.
 *   refGray           -> Float64Array           the reference frame at the clip's
 *                        record position, same DW×DH grayscale.
 *
 * Returns { frame, score, evals, confidence, margin } where confidence is
 * 'high' | 'review' | 'low' from the peak score and its margin over the
 * surrounding scores — low-confidence locates should be routed to a human wipe
 * rather than trusted silently.
 */

const { ssimStructure, coarseToFinePeak } = require('./metrics');

const DEFAULTS = Object.freeze({
  coarseStep: 8,
  // Peak-score gates (structure SSIM over the unmasked region).
  highScore: 0.75,
  reviewScore: 0.55,
  // How much the peak must beat its neighbours (avoids flat/ambiguous matches).
  minMargin: 0.04,
});

/**
 * Locate the best-matching source frame in [lo, hi] by content.
 * @param {Float64Array} refGray  reference frame (grayscale, DW×DH)
 * @param {(frame:number)=>Promise<Float64Array>} conformAt  injected decoder
 * @param {number} lo  inclusive low source frame
 * @param {number} hi  inclusive high source frame
 * @param {object} [opts]  { mask, coarseStep, highScore, reviewScore, minMargin }
 */
async function locateByContent(refGray, conformAt, lo, hi, opts = {}) {
  const o = { ...DEFAULTS, ...opts };
  const mask = opts.mask || null;
  const scoreAt = async (frame) => {
    const g = await conformAt(frame);
    if (!g) return -Infinity;
    return ssimStructure(refGray, g, mask);
  };
  const peak = await coarseToFinePeak(scoreAt, lo, hi, o.coarseStep);
  // Margin: how much the peak beats a neighbour a coarse-step away (ambiguity guard).
  const near = await Promise.all([
    scoreAt(Math.max(lo, peak.x - o.coarseStep)),
    scoreAt(Math.min(hi, peak.x + o.coarseStep)),
  ]);
  const neighbour = Math.max(...near.filter((s) => Number.isFinite(s)), -Infinity);
  const margin = Number.isFinite(neighbour) ? peak.score - neighbour : Infinity;

  let confidence = 'low';
  if (peak.score >= o.highScore && margin >= o.minMargin) confidence = 'high';
  else if (peak.score >= o.reviewScore) confidence = 'review';

  return { frame: peak.x, score: peak.score, evals: peak.evals, margin, confidence };
}

module.exports = { locateByContent, DEFAULTS };
