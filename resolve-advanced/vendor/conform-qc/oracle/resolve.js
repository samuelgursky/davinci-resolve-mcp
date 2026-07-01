'use strict';

/**
 * oracle/resolve.js — the Resolve target ruleset.
 *
 * Given a clip's captured conform fields + a sequence context, derive the
 * source frame Resolve actually reports (clip_where `source_start`). This is the
 * heart of the engine: a filename match is NOT a conform (spec §2) — the Oracle
 * models the target's conform math so we can prove a cut by frame.
 *
 * THE TICKS vs <in> RECONCILIATION (verified against golden_oracle.json):
 *   Resolve READS `pproTicksIn` on import (non-negotiable #5), and for an
 *   un-retimed clip ticks/tpf == <in>, so source_start == ticks/tpf == in.
 *   For a RETIMED clip the two diverge: a 50% slow-mo has ticks/tpf ≈ 2*in,
 *   but Resolve applies the speed and clip_where reports the speed-adjusted
 *   media-in, which equals the captured <in> (e.g. ticks/tpf=35819, in=17910 →
 *   source_start=17910). So the authoritative readback is `startoffset + in`,
 *   and ticks/tpf is how we
 *   DETECT the retime (and, later, recover the speed for content sampling).
 *
 * ctx: { ticksPerFrame } (from the sequence model; @24 = 254016000000/24 =
 * 10584000000). Taking tpf from ctx keeps non-24 sequences on the same path.
 *
 * Clip fields consumed (as captured into golden_oracle.json):
 *  - xml_in              : the media in-frame (<in>); the speed-adjusted source.
 *  - pproTicksIn         : authoritative tick position; used to detect retime.
 *  - is_subclip          : pickups are subclips (source = startoffset + in).
 *  - subclip_startoffset : the subclip's offset into its parent media.
 */

function requireNumber(v, name) {
  if (typeof v !== 'number' || Number.isNaN(v)) {
    throw new Error(`oracle/resolve: clip.${name} is required (number)`);
  }
  return v;
}

/** The tick-derived source frame (pre-speed). Used to detect retimes. */
function ticksSourceFrame(clip, ctx) {
  const tpf = ctx.ticksPerFrame;
  if (!tpf || typeof tpf !== 'number') {
    throw new Error('oracle/resolve: ctx.ticksPerFrame is required');
  }
  return Math.round(requireNumber(clip.pproTicksIn, 'pproTicksIn') / tpf);
}

/**
 * The source frame a clip's range BEGINS at, measured in the source media.
 *
 * Forward clip: the in-frame, plus the subclip's startoffset into its parent
 * media (subclips only) — i.e. the range is anchored at the START of the
 * available media and grows downward by <in>.
 *
 * Reversed clip: a reversed subclip anchors at the END of its available range,
 * not the start, and mirrors the in/out about that end. With 0-based frame
 * indices, the LAST usable source frame is:
 *   lastAvail = masterFrames - 1 - endoffset
 * Reversed playback shows that end first, so Resolve's source_start readback (the
 * first DISPLAYED frame) is the HIGH end, lastAvail - in; source_end is the low
 * end, lastAvail - out (in < out, so source_start > source_end — the reversed
 * order Resolve reports):
 *   source_start = lastAvail - in   (this function's return — matches clip_where)
 *   source_end   = lastAvail - out
 * Fully derivable from the XML (<in>/<out>, endoffset) plus the source media's
 * frame count (master*Frames, from the media probe) — no reference render needed.
 * Mirror of the forward case: the start-anchor (startoffset, growing UP by <in>)
 * becomes the end-anchor (lastAvail, growing DOWN by <in>).
 *
 * (Verified live: nb_frames 47849, endoffset 11832, in 589 → 35427; out 604 →
 * 35412 — exactly Resolve's get_source_start/end_frame. The -1 and anchoring on
 * <in> both matter: anchoring on <out> or dropping the -1 mislands the frame.)
 *
 * masterFrames is read from ctx.masterFrames (sequence-level default) or
 * clip.master_frames (per-source override). Reverse without a frame count fails
 * loudly rather than silently emitting the forward (wrong) frame.
 */
function deriveSourceFrame(clip, ctx) {
  const inFrame = requireNumber(clip.xml_in, 'xml_in');
  // Touch ticks so a missing/garbage pproTicksIn still fails loudly here
  // (Resolve reads ticks; we never silently ignore them).
  ticksSourceFrame(clip, ctx);
  if (clip.reverse) {
    return reverseLastAvail(clip, ctx) - inFrame;
  }
  const offset = clip.is_subclip ? clip.subclip_startoffset || 0 : 0;
  return offset + inFrame;
}

/** The last usable (0-based) source frame of a reversed clip's available range. */
function reverseLastAvail(clip, ctx) {
  const masterFrames = masterFrameCount(clip, ctx);
  const endoffset = clip.is_subclip ? clip.subclip_endoffset || 0 : 0;
  return masterFrames - 1 - endoffset;
}

/** Source-media frame count, for reverse-clip end-anchoring. */
function masterFrameCount(clip, ctx) {
  const n = (typeof clip.master_frames === 'number' && clip.master_frames) ||
    (ctx && typeof ctx.masterFrames === 'number' && ctx.masterFrames);
  if (!n || typeof n !== 'number') {
    throw new Error(
      'oracle/resolve: reversed clip needs a source frame count ' +
      '(clip.master_frames or ctx.masterFrames) to end-anchor its range'
    );
  }
  return n;
}

/** Is this clip retimed? ticks/tpf diverges from <in> when speed != 100%. */
function isRetimed(clip, ctx) {
  return ticksSourceFrame(clip, ctx) !== requireNumber(clip.xml_in, 'xml_in');
}

/**
 * The frame to SAMPLE from the media for content verification — the ticks path,
 * pre-speed (= ~2*in for a 50% slow-mo). For un-retimed clips this equals
 * derivedSourceFrame; for retimes it is the ticks value the comparator's derived
 * frame was rendered at (golden_compare.derived_source_frame). Distinct from the
 * Resolve readback (derivedSourceFrame), which is the speed-adjusted media-in.
 */
function deriveSampleFrame(clip, ctx) {
  if (clip.reverse) {
    // The first DISPLAYED frame (= the readback source_start) is what a reference
    // at the clip's record-start shows, so sample there. No extra speed offset.
    return reverseLastAvail(clip, ctx) - requireNumber(clip.xml_in, 'xml_in');
  }
  const offset = clip.is_subclip ? clip.subclip_startoffset || 0 : 0;
  return offset + ticksSourceFrame(clip, ctx);
}

/**
 * Derive the corrected display scale (the "double-count" fix, spec §9) — ASPECT
 * AWARE, to reproduce the editor's framing under Resolve's `scaleToFit` input
 * scaling. Resolve's ZoomX-1.0 baseline fits the source ENTIRELY, i.e. by the
 * BINDING dimension: width when the source is wider than the sequence, height
 * when it is narrower. So the correction normalizes by the same dimension:
 *   narrower source (srcW/srcH < seqW/seqH): scale * srcH / seqH
 *   wider/equal source:                      scale * srcW / seqW
 *
 * (A width-only rule pillarboxes footage narrower than the timeline: a source
 * narrower in aspect than the sequence, scaled to exact fill-width, reads back as
 * fit-not-fill and lands a few percent too small. Height-normalizing for narrower
 * sources is the fix.) srcH/seqH fall back to the width rule when heights are
 * unavailable.
 */
function deriveScaleCorrected(clip, ctx) {
  const seqW = ctx.sequenceWidth;
  if (!seqW || typeof seqW !== 'number') {
    throw new Error('oracle/resolve: ctx.sequenceWidth is required for scale');
  }
  const scale = requireNumber(clip.scale_premiere, 'scale_premiere');
  const srcW = requireNumber(clip.srcW, 'srcW');
  const seqH = ctx.sequenceHeight;
  const srcH = clip.srcH;
  if (typeof seqH === 'number' && seqH > 0 && typeof srcH === 'number' && srcH > 0 && srcW / srcH < seqW / seqH) {
    return (scale * srcH) / seqH; // narrower source — Resolve fits by height
  }
  return (scale * srcW) / seqW;
}

/**
 * Derive the transform the target applies at the sequence resolution: the
 * corrected (per-source-width normalized) scale, with center/crop/rotation
 * carried through from the captured geometry. Fields absent on a clip (e.g. the
 * golden_oracle entries carry no reframe) pass through as null.
 */
function deriveTransform(clip, ctx) {
  return {
    scale: deriveScaleCorrected(clip, ctx),
    center: clip.center || null,
    crop: clip.crop || null,
    rotation: clip.rotation != null ? clip.rotation : null,
  };
}

/** Derive everything the target needs for a clip. */
function derive(clip, ctx) {
  return {
    derivedSourceFrame: deriveSourceFrame(clip, ctx),
    derivedSampleFrame: deriveSampleFrame(clip, ctx),
    derivedScaleCorrected: deriveScaleCorrected(clip, ctx),
    derivedTransform: deriveTransform(clip, ctx),
    retimed: isRetimed(clip, ctx),
  };
}

module.exports = {
  id: 'resolve',
  derive,
  deriveSourceFrame,
  deriveSampleFrame,
  deriveScaleCorrected,
  deriveTransform,
  ticksSourceFrame,
  isRetimed,
};
