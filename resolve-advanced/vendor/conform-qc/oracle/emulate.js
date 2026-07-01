'use strict';

/**
 * oracle/emulate.js — the CONFORM ENVIRONMENT EMULATOR (stage 2).
 *
 * Produces the per-clip "conform truth": what the target SHOULD show for each
 * clip, derived from the editorial XML + project settings + the analyzed target
 * media. This is the reference the diff (stage 4) compares the imported
 * Project.db against, and the source the injector (stage 5) writes from.
 *
 * The transform is computed the way Resolve actually frames a mismatched-
 * resolution clip:
 *   - the editor's displayed size = proxyW * scale/100 (Premiere scale is native-
 *     relative), and
 *   - Resolve's ZoomX-1.0 baseline = the input-scaling fit of the RELINKED HIGHRES
 *     (scaleToFit = min-fit / pillarbox; scaleToFill = max-fit / crop),
 * so   ZoomX = editorDisplayWidth / highresFitWidth.
 * When proxy and highres share an aspect this reduces to scale*srcH/seqH (the
 * fill-width fix). When they DON'T (a proxy that is a cropped view of a wider
 * highres) the dims can't determine the framing alone — we still emit the best
 * estimate but FLAG it `aspectMismatch` / confidence:low for reference resolution.
 */

const resolve = require('./resolve');
const { correctedScalePercent } = require('../packaging/surgical-relink');

const MODE = { FIT: 'scaleToFit', FILL: 'scaleToFill', STRETCH: 'stretch', CENTER: 'center' };

/** Resolve input-scaling fit factor (source px -> timeline px at ZoomX 1.0). */
function fitFactor(srcW, srcH, seqW, seqH, mode = MODE.FIT) {
  const fw = seqW / srcW;
  const fh = seqH / srcH;
  if (mode === MODE.FILL) return Math.max(fw, fh);
  if (mode === MODE.CENTER) return 1; // no resize
  if (mode === MODE.STRETCH) return fw; // non-uniform handled by caller; width here
  return Math.min(fw, fh); // scaleToFit (default)
}

const ASPECT_TOL = 0.02;

/**
 * Emulate one clip -> conform truth.
 * @param clip  parsed geometry clip (srcW/srcH = PROXY dims from the XML)
 * @param ctx   { ticksPerFrame, seqW, seqH, mode }
 * @param media analyzed HIGHRES media-info for this clip's resolved source (or null)
 */
function emulateClip(clip, ctx, media = null) {
  const hr = media && media.ok ? media : null;
  // Reverse clips end-anchor their range against the source frame count, which
  // comes from the probed media — pass it through so the oracle needs no reference.
  const tctx = { ticksPerFrame: ctx.ticksPerFrame, masterFrames: hr ? hr.frames : null };
  const proxyW = clip.srcW;
  const proxyH = clip.srcH;
  const seqW = ctx.seqW;
  const seqH = ctx.seqH;
  const mode = ctx.mode || MODE.FIT;

  // The editor framed against the PROXY (which the reference render shows), so the
  // intended ZoomX is the proxy-aspect correction (same formula the surgical relink
  // emits) — NOT a highres-fit recompute. When proxy and highres share an aspect a
  // highres-fit recompute would agree; when they DON'T (a proxy that is a
  // side-crop of a wider highres) the proxy value is the one that reproduces the
  // editor's framing, so we keep it and only FLAG aspectMismatch for a reference
  // sanity-check (the highres may simply expose more picture than the proxy did).
  let zoom = null;
  let aspectMismatch = false;
  let scaleConfidence = clip.scale_premiere == null ? 'n/a' : 'high';
  let basis = null;
  if (clip.scale_premiere != null && proxyW && proxyH) {
    zoom = +(correctedScalePercent(clip.scale_premiere, proxyW, proxyH, seqW, seqH) / 100).toFixed(5);
    basis = 'proxy';
    if (hr) {
      const pa = proxyW / proxyH;
      const ha = hr.width / hr.height;
      if (Math.abs(pa - ha) > ASPECT_TOL) {
        aspectMismatch = true;
        scaleConfidence = 'review'; // proxy↔highres aspect differs — verify vs reference
      }
    }
  }

  const dur = clip.seqend != null && clip.seqstart != null ? clip.seqend - clip.seqstart : null;
  return {
    seqstart: clip.seqstart,
    seqend: clip.seqend,
    timing: { recordIn: clip.seqstart, recordOut: clip.seqend, duration: dur },
    source: {
      basename: clip.source_basename,
      proxyW,
      proxyH,
      hrW: hr ? hr.width : null,
      hrH: hr ? hr.height : null,
      codec: hr ? hr.codec : null,
      bitDepth: hr ? hr.bitDepth : null,
      aspect: hr ? +(hr.width / hr.height).toFixed(4) : proxyH ? +(proxyW / proxyH).toFixed(4) : null,
    },
    sourceFrame: resolve.deriveSourceFrame(clip, tctx),
    sampleFrame: resolve.deriveSampleFrame(clip, tctx),
    retime: {
      speed: clip.speed != null ? clip.speed : 100,
      reverse: !!clip.reverse,
      // retimed if ticks diverge from <in> (speed ramp), OR reverse, OR speed != 100
      retimed: resolve.isRetimed(clip, tctx) || !!clip.reverse || (clip.speed != null && clip.speed !== 100),
    },
    transform: {
      zoomX: zoom,
      zoomY: zoom, // ganged (uniform); no anamorphic in this footage
      panX: clip.center ? clip.center.h : 0,
      panY: clip.center ? clip.center.v : 0,
      rotation: clip.rotation != null ? clip.rotation : 0,
      crop: clip.crop || null,
      basis,
    },
    flags: {
      aspectMismatch,
      scaleConfidence,
      reframed: !!(clip.center && (clip.center.h || clip.center.v)) || !!clip.rotation,
    },
  };
}

/**
 * Emulate a whole parsed sequence.
 * @param parsed  parseGeometry output { sequence, clips, transitions }
 * @param settings { mode?, ticksPerFrame? }
 * @param mediaBySource  basename -> analyzed highres info
 */
function emulateSequence(parsed, settings = {}, mediaBySource = {}) {
  const seq = parsed.sequence || {};
  const seqW = seq.width;
  const seqH = seq.height;
  const fps = seq.fps || 24;
  const ctx = {
    ticksPerFrame: settings.ticksPerFrame || 254016000000 / fps,
    seqW,
    seqH,
    mode: settings.mode || MODE.FIT,
  };
  const clips = (parsed.clips || []).map((c) => emulateClip(c, ctx, mediaBySource[c.source_basename] || null));
  const flagged = clips.filter((c) => c.flags.aspectMismatch);
  return {
    sequence: { width: seqW, height: seqH, fps, mode: ctx.mode },
    clips,
    transitions: parsed.transitions || [],
    summary: {
      total: clips.length,
      aspectMismatch: flagged.length,
      reframed: clips.filter((c) => c.flags.reframed).length,
      retimed: clips.filter((c) => c.retime.retimed).length,
      transitions: (parsed.transitions || []).length,
    },
  };
}

module.exports = { emulateClip, emulateSequence, fitFactor, MODE };
