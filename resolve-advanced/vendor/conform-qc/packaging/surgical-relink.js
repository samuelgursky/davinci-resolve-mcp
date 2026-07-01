'use strict';

/**
 * packaging/surgical-relink.js — relink + scale-correct an XMEML turnover by
 * SURGICAL text edit, not re-emit.
 *
 * Why surgical: the round-trip emitter (emit-fcp7.js) is intentionally minimal —
 * it would drop retimes, V2+ track inserts, audio, transitions, subclips. A real
 * conform must change ONLY the two things that are wrong after a 4K relink and
 * leave every other byte of the editor's turnover untouched:
 *   1. <pathurl> — repoint each proxy to its high-res original (MediaIndex:
 *      exact basename → normalized proxy↔original key → IDF true-source).
 *   2. the Basic-Motion <scale> value — undo Premiere's seqW/srcW double-count
 *      (spec §9): corrected = round(scale * srcW / seqW, 3). Per CLIPITEM, because
 *      the same source can carry per-clip scale tweaks (179, 165.391, …).
 *
 * Generators (no camera media) and full-frame sources (srcW == seqW, e.g. 3600
 * VFX/graphics/leader) are left untouched — neither relinked nor rescaled.
 *
 * Pure-ish: takes the XML string + a MediaIndex, returns the new XML + a report.
 * No file IO (the caller reads/writes).
 */

/** Encode an absolute path into a file://localhost pathurl the way Premiere does. */
function encodePathUrl(absPath) {
  const enc = String(absPath)
    .split('/')
    .map((seg) => encodeURIComponent(seg))
    .join('/');
  return `file://localhost${enc}`;
}

/** Decode a basename out of a (possibly %-encoded) pathurl. */
function basenameOfPathUrl(pathurl) {
  let p = String(pathurl);
  try {
    p = decodeURIComponent(p);
  } catch (e) {
    /* leave encoded */
  }
  return p.slice(p.lastIndexOf('/') + 1);
}

/**
 * Collect full <file> definitions (those carrying a <pathurl>) from raw XML:
 *   id -> { pathurl, srcW, basename }
 * Self-closing <file id=".."/> refs reuse a full def by id and are not collected.
 */
function collectFileDefs(xml) {
  const defs = new Map();
  const re = /<file\s+id="([^"]+)"\s*>([\s\S]*?)<\/file>/g;
  let m;
  while ((m = re.exec(xml))) {
    const id = m[1];
    const inner = m[2];
    const pathurl = (inner.match(/<pathurl>([^<]+)<\/pathurl>/) || [])[1] || null;
    if (!pathurl) continue; // generator / no media
    // first <width>/<height> inside the def is the video samplecharacteristics size
    const w = (inner.match(/<width>(\d+)<\/width>/) || [])[1];
    const h = (inner.match(/<height>(\d+)<\/height>/) || [])[1];
    if (!defs.has(id)) {
      defs.set(id, { pathurl, srcW: w != null ? Number(w) : null, srcH: h != null ? Number(h) : null, basename: basenameOfPathUrl(pathurl) });
    }
  }
  return defs;
}

function round3(n) {
  return Math.round(n * 1000) / 1000;
}

/**
 * The corrected display scale (% ) that reproduces the editor's framing under
 * Resolve's `scaleToFit` input scaling (spec §9, aspect-aware).
 *
 * Premiere's scale is relative to the source's native pixels (scale 100 = native
 * size in the sequence), so the editor's displayed size = srcDim * scale/100.
 * Resolve's `scaleToFit` baseline (ZoomX 1.0) scales the source to FIT ENTIRELY,
 * i.e. by the BINDING dimension: width when the source is WIDER than the
 * sequence, height when it is NARROWER (a source narrower in aspect than the
 * timeline fits by height → pillarbox at 1.0). So the corrected ZoomX must
 * normalize by the SAME binding dimension Resolve fit by:
 *   narrower source (srcW/srcH < seqW/seqH): scale * srcH / seqH
 *   wider/equal source:                      scale * srcW / seqW
 * (Using srcW/seqW unconditionally — a width-only rule — pillarboxes narrow
 * footage: the editor's exact fill-width percent maps to 100% = fit, not fill,
 * leaving the image a few percent too small.)
 */
function correctedScalePercent(scale, srcW, srcH, seqW, seqH) {
  const heightBound = srcH != null && seqH != null && srcW / srcH < seqW / seqH;
  return heightBound ? (scale * srcH) / seqH : (scale * srcW) / seqW;
}

/**
 * @param {string} xml         raw XMEML turnover
 * @param {object} mediaIndex  a repair/media-index MediaIndex over the high-res tree
 * @param {object} opts        { sequenceWidth, sequenceHeight, minScore? }
 * @returns {{ xml, relink:{resolved,unresolved,skipped}, scale:{edits,untouched}, dropped }}
 */
function surgicalRelink(xml, mediaIndex, opts = {}) {
  const seqW = opts.sequenceWidth;
  const seqH = opts.sequenceHeight;
  if (!seqW || !seqH) throw new Error('surgical-relink: opts.sequenceWidth and sequenceHeight are required');
  const minScore = opts.minScore != null ? opts.minScore : 0.55;

  const defs = collectFileDefs(xml);
  const idDims = new Map(); // fileId -> {srcW, srcH, basename} (for the scale + reframe passes)
  for (const [id, d] of defs) idDims.set(id, { srcW: d.srcW, srcH: d.srcH, basename: d.basename });
  // Optional per-source vertical reframe (rescan-framing lift): basename -> center
  // vert (FCP7 normalized; Resolve maps to Tilt). The rescans were scanned at a
  // different vertical framing than the proxies the editor cut with, so they need a
  // measured lift that the base XML (center=0) doesn't carry.
  const reframeY = opts.reframeY || {};

  // ── Pass A: build the per-file relink map (camera sources only) ─────────────
  const resolved = [];
  const unresolved = [];
  const skipped = []; // full-frame (srcW==seqW) or otherwise intentionally left
  const pathReplacements = []; // { oldPathurl, newPathurl, oldBase, newBase }
  for (const [id, d] of defs) {
    if (d.srcW != null && d.srcW >= seqW) {
      skipped.push({ id, basename: d.basename, srcW: d.srcW, reason: 'full-frame (srcW >= seqW)' });
      continue;
    }
    const exact = mediaIndex.byBasename(d.basename);
    const norm = exact ? null : mediaIndex.byNormalized(d.basename);
    const hit = exact
      ? { path: exact, score: 1 }
      : norm
        ? { path: norm, score: 1 }
        : mediaIndex.findTrueSource(d.basename, { minScore });
    if (!hit) {
      unresolved.push({ id, basename: d.basename, srcW: d.srcW });
      continue;
    }
    const newBase = hit.path.slice(hit.path.lastIndexOf('/') + 1);
    resolved.push({ id, oldBase: d.basename, newBase, score: round3(hit.score), path: hit.path });
    pathReplacements.push({
      oldPathurl: d.pathurl,
      newPathurl: encodePathUrl(hit.path),
      oldBase: d.basename,
      newBase,
    });
  }

  // ── Pass B: apply pathurl + basename text replacements (global, exact) ──────
  let out = xml;
  for (const r of pathReplacements) {
    out = out.split(r.oldPathurl).join(r.newPathurl);
    if (r.oldBase !== r.newBase) out = out.split(`<name>${r.oldBase}</name>`).join(`<name>${r.newBase}</name>`);
  }

  // ── Pass C: per-clipitem scale correction + optional rescan reframe-Y ────────
  let edits = 0;
  let reframeEdits = 0;
  const untouched = [];
  const fileIdRe = /<file\s+id="([^"]+)"/;
  const scaleRe = /(<parameterid>scale<\/parameterid>[\s\S]*?<value>)([^<]*)(<\/value>)/;
  // center param's vert (NOT centerOffset/anchor, which follows): first <vert> after
  // the exact `center` parameterid.
  const centerVertRe = /(<parameterid>center<\/parameterid>[\s\S]*?<vert>)(-?[\d.]+)(<\/vert>)/;
  out = out.replace(/<clipitem\b[\s\S]*?<\/clipitem>/g, (block) => {
    const idm = block.match(fileIdRe);
    if (!idm) return block;
    const dims = idDims.get(idm[1]) || {};
    const srcW = dims.srcW;
    const srcH = dims.srcH;
    let b = block;
    // reframe-Y: apply a measured per-source vertical lift to the center vert
    const lift = dims.basename != null ? reframeY[dims.basename] : undefined;
    if (lift != null && centerVertRe.test(b)) {
      b = b.replace(centerVertRe, (whole, pre, _v, post) => { reframeEdits += 1; return `${pre}${lift}${post}`; });
    }
    if (srcW == null || srcW >= seqW) {
      if (scaleRe.test(b)) untouched.push({ fileId: idm[1], srcW, reason: srcW == null ? 'no srcW' : 'full-frame' });
      return b; // generator / full-frame — leave scale alone (reframe already applied if mapped)
    }
    return b.replace(scaleRe, (whole, pre, val, post) => {
      const scale = Number(val);
      if (!Number.isFinite(scale)) return whole;
      edits += 1;
      return `${pre}${round3(correctedScalePercent(scale, srcW, srcH, seqW, seqH))}${post}`;
    });
  });

  return {
    xml: out,
    relink: { resolved, unresolved, skipped },
    scale: { edits, untouched },
    reframe: { edits: reframeEdits },
    dropped: [],
  };
}

module.exports = { surgicalRelink, correctedScalePercent, encodePathUrl, basenameOfPathUrl, collectFileDefs };
