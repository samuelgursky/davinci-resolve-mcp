'use strict';

/**
 * repair/strategies.js — the §9 failure-mode catalog as individual strategies.
 *
 * Each strategy is pure: { id, klass, deterministic, detect(cut,ctx)->bool,
 * propose(cut,ctx)->{ fix, diagnosis, scope?, confidence? } }. `deterministic`
 * strategies are auto-apply-eligible (subject to re-verify + the §15 gate);
 * the rest are propose-only (human approves).
 *
 * `cut` carries the captured geometry + Oracle outputs; `ctx` carries
 * { ticksPerFrame, sequenceWidth, mediaIndex? }.
 */

const TPF_24 = 10584000000;

/** Scale double-count (§9): Premiere scale bakes in seqW/srcW; normalize per source width. */
const scaleDoubleCount = {
  id: 'normalize-scale-per-source-width',
  klass: 'scale-double-count',
  deterministic: true,
  detect(cut, ctx) {
    if (cut.scale_premiere == null || !cut.srcW || !ctx.sequenceWidth) return false;
    // Signature: the raw scale is ~ the seqW/srcW fit factor (i.e. not yet normalized to ~100).
    const fit = (ctx.sequenceWidth / cut.srcW) * 100;
    return Math.abs(cut.scale_premiere - fit) > 0.5 || cut.scale_premiere > 110 || cut.scale_premiere < 90;
  },
  propose(cut, ctx) {
    const corrected = (cut.scale_premiere * cut.srcW) / ctx.sequenceWidth;
    return { fix: { scale: corrected }, diagnosis: `scale ${cut.scale_premiere} normalized per source width -> ${corrected.toFixed(3)}`, confidence: 1 };
  },
};

/** Subclip offset (§9): source = startoffset + in; never rewrite <in>. */
const subclipOffset = {
  id: 'add-subclip-startoffset',
  klass: 'subclip-offset',
  deterministic: true,
  detect(cut) {
    return !!cut.is_subclip;
  },
  propose(cut) {
    const sourceFrame = (cut.subclip_startoffset || 0) + cut.xml_in;
    return { fix: { sourceFrame }, diagnosis: `subclip: source = startoffset ${cut.subclip_startoffset} + in ${cut.xml_in} = ${sourceFrame} (<in> unchanged)`, confidence: 1 };
  },
};

/** Slow-mo / ticks != in (§9): derive the sample frame from ticks. */
const ticksRetime = {
  id: 'derive-sample-from-ticks',
  klass: 'ticks-retime',
  deterministic: true,
  detect(cut, ctx) {
    if (cut.pproTicksIn == null || cut.xml_in == null) return false;
    const tpf = ctx.ticksPerFrame || TPF_24;
    return Math.round(cut.pproTicksIn / tpf) !== cut.xml_in;
  },
  propose(cut, ctx) {
    const tpf = ctx.ticksPerFrame || TPF_24;
    const offset = cut.is_subclip ? cut.subclip_startoffset || 0 : 0;
    const sampleFrame = offset + Math.round(cut.pproTicksIn / tpf);
    return { fix: { sampleFrame }, diagnosis: `retime: sample from ticks = ${sampleFrame} (readback stays <in> ${cut.xml_in})`, confidence: 1 };
  },
};

/** Stale relink path (§9): path not found; re-resolve by exact basename via the media index. */
const staleRelink = {
  id: 'relink-by-exact-basename',
  klass: 'stale-relink',
  deterministic: true,
  detect(cut, ctx) {
    return !!cut.pathMissing && !!ctx.mediaIndex && !!cut.source_basename;
  },
  propose(cut, ctx) {
    const path = ctx.mediaIndex.byBasename ? ctx.mediaIndex.byBasename(cut.source_basename) : null;
    if (!path) return { fix: null, diagnosis: `stale relink: no exact-basename match for ${cut.source_basename}`, confidence: 0 };
    return { fix: { path }, diagnosis: `relinked ${cut.source_basename} -> ${path}`, confidence: 1 };
  },
};

/**
 * Per-file frame offset (§9): the matched frame differs from the derived frame
 * by a CONSTANT across a file's clips. Detect the constant, apply to that file.
 * Propose-only (a measured correction, not deterministic from the XML).
 */
const perFileOffset = {
  id: 'apply-per-file-frame-offset',
  klass: 'per-file-offset',
  deterministic: false,
  detect(cut, ctx) {
    return ctx.fileOffsets != null && cut.fileId != null && ctx.fileOffsets[cut.fileId] != null && ctx.fileOffsets[cut.fileId] !== 0;
  },
  propose(cut, ctx) {
    const k = ctx.fileOffsets[cut.fileId];
    return { fix: { sourceFrameDelta: k }, scope: cut.fileId, diagnosis: `per-file offset ${k > 0 ? '+' : ''}${k} applied to file ${cut.fileId}`, confidence: 0.8 };
  },
};

/** Estimate a constant per-file offset from verified (derived, matched) samples. */
function estimatePerFileOffset(samples) {
  if (!samples || !samples.length) return null;
  const deltas = samples.map((s) => s.matched - s.derived);
  const counts = {};
  for (const d of deltas) counts[d] = (counts[d] || 0) + 1;
  const best = Object.keys(counts).sort((a, b) => counts[b] - counts[a])[0];
  const k = Number(best);
  // Only a confident constant offset (majority agree) counts.
  return counts[best] / deltas.length >= 0.6 ? k : null;
}

/** Aspect variant (§9): source aspect != reference/sequence aspect → reframe. Propose-only. */
const aspectVariant = {
  id: 'reframe-aspect-variant',
  klass: 'aspect-variant',
  deterministic: false,
  detect(cut, ctx) {
    if (!cut.srcW || !cut.srcH || !ctx.sequenceWidth || !ctx.sequenceHeight) return false;
    const srcAspect = cut.srcW / cut.srcH;
    const seqAspect = ctx.sequenceWidth / ctx.sequenceHeight;
    // Only a LARGE aspect mismatch (e.g. 4:3 vs 16:9) needs a per-clip reframe;
    // a minor fit difference (e.g. 1.568 source in a 5:3 sequence) is handled by scale.
    return Math.abs(srcAspect - seqAspect) / seqAspect > 0.1;
  },
  propose(cut, ctx) {
    // Fit-to-fill the differing dimension; carry a reframe scale/center.
    const fillScale = Math.max(ctx.sequenceWidth / cut.srcW, ctx.sequenceHeight / cut.srcH) / (ctx.sequenceWidth / cut.srcW);
    return { fix: { reframe: { scale: fillScale, center: { h: 0, v: 0 } } }, diagnosis: `aspect ${cut.srcW}x${cut.srcH} != sequence; proposed reframe scale ${fillScale.toFixed(3)}`, confidence: 0.6 };
  },
};

/**
 * Online/offline framing residual (§9): a measured X/Y(/scale) offset on SOME
 * clips. Apply a per-clip position patch ONLY where measured (non-negotiable #4).
 * Propose-only.
 */
const measuredResidual = {
  id: 'per-clip-measured-position-patch',
  klass: 'online-offline-residual',
  deterministic: false,
  detect(cut) {
    return !!cut.measuredOffset && (cut.measuredOffset.dx !== 0 || cut.measuredOffset.dy !== 0 || (cut.measuredOffset.ds || 0) !== 0);
  },
  propose(cut) {
    const o = cut.measuredOffset;
    return { fix: { positionPatch: { dx: -o.dx, dy: -o.dy, ds: o.ds ? -o.ds : 0 } }, scope: cut.cutId, diagnosis: `measured residual (${o.dx},${o.dy}) -> per-clip patch (${-o.dx},${-o.dy})`, confidence: 0.7 };
  },
};

/** Apply measured patches ONLY to the cuts that have a measurement (measured-only). */
function applyMeasuredPatches(cuts, measurements) {
  return cuts.map((c) => {
    const m = measurements[c.cutId];
    if (!m) return { cutId: c.cutId, patched: false };
    return { cutId: c.cutId, patched: true, positionPatch: { dx: -m.dx, dy: -m.dy, ds: m.ds ? -m.ds : 0 } };
  });
}

/** Wrong source entirely (§9): content mismatch → use burn-in identity + media index to find the true source. Propose-only. */
const wrongSource = {
  id: 'find-true-source-by-identity',
  klass: 'wrong-source',
  deterministic: false,
  detect(cut, ctx) {
    return cut.verdict === 'WRONG' && !!ctx.mediaIndex && (!!cut.burnInName || !!cut.source_basename);
  },
  propose(cut, ctx) {
    const name = cut.burnInName || cut.source_basename;
    const found = ctx.mediaIndex.findTrueSource(name, { minScore: 0.5 });
    if (!found) return { fix: null, diagnosis: `wrong source: no true-source match for "${name}"`, confidence: 0 };
    return { fix: { path: found.path, source_basename: found.basename }, diagnosis: `true source for "${name}" -> ${found.basename} (score ${found.score.toFixed(2)})`, confidence: Math.min(0.9, found.score) };
  },
};

/** Reel-name conform (§9): EDL/AAF reel only → reel+TC match via the media index. */
const reelNameConform = {
  id: 'reel-tc-match',
  klass: 'reel-name-conform',
  deterministic: true,
  detect(cut, ctx) {
    return !!cut.reel && !!ctx.mediaIndex;
  },
  propose(cut, ctx) {
    const path = ctx.mediaIndex.byReelTc(cut.reel, cut.sourceTc);
    if (!path) return { fix: null, diagnosis: `reel ${cut.reel} not found`, confidence: 0 };
    return { fix: { path }, diagnosis: `reel ${cut.reel} @ ${cut.sourceTc} -> ${path}`, confidence: 1 };
  },
};

/** Mixed frame rates (§9): clip rate != sequence rate → rate-aware source-frame mapping. Propose-only. */
const mixedFrameRate = {
  id: 'rate-aware-frame-map',
  klass: 'mixed-framerate',
  deterministic: false,
  detect(cut, ctx) {
    return cut.clipRate != null && ctx.sequenceRate != null && cut.clipRate !== ctx.sequenceRate;
  },
  propose(cut, ctx) {
    const mapped = Math.round((cut.sourceFrame || cut.xml_in) * (cut.clipRate / ctx.sequenceRate));
    return { fix: { sourceFrame: mapped }, diagnosis: `rate ${cut.clipRate} != seq ${ctx.sequenceRate}; mapped source frame -> ${mapped}`, confidence: 0.7 };
  },
};

/** Handle shortfall (§9): used range + handles near media bounds → warn + clamp. */
const handleShortfall = {
  id: 'clamp-handles',
  klass: 'handle-shortfall',
  deterministic: true,
  detect(cut) {
    if (cut.mediaLength == null || cut.usedOut == null) return false;
    const want = cut.handles || 0;
    return cut.usedOut + want > cut.mediaLength || (cut.usedIn || 0) - want < 0;
  },
  propose(cut) {
    const want = cut.handles || 0;
    const head = Math.min(want, cut.usedIn || 0);
    const tail = Math.min(want, cut.mediaLength - cut.usedOut);
    return { fix: { handlesHead: head, handlesTail: tail }, diagnosis: `handle shortfall: clamped to head ${head}/tail ${tail} (wanted ${want})`, confidence: 1, warn: true };
  },
};

/** Missing/offline media (§9): no match anywhere → flag to V2 with diagnosis. */
const missingMedia = {
  id: 'flag-missing-media',
  klass: 'missing-media',
  deterministic: false,
  detect(cut, ctx) {
    return !!cut.pathMissing && (!ctx.mediaIndex || !ctx.mediaIndex.byBasename(cut.source_basename)) && !cut.burnInName;
  },
  propose(cut) {
    return { fix: null, diagnosis: `missing/offline media: ${cut.source_basename || cut.cutId} — flag to V2`, confidence: 0 };
  },
};

module.exports = {
  scaleDoubleCount,
  subclipOffset,
  ticksRetime,
  staleRelink,
  perFileOffset,
  aspectVariant,
  measuredResidual,
  wrongSource,
  reelNameConform,
  mixedFrameRate,
  handleShortfall,
  missingMedia,
  estimatePerFileOffset,
  applyMeasuredPatches,
  TPF_24,
};
