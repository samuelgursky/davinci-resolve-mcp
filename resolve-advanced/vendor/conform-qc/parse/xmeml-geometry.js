'use strict';

/**
 * parse/xmeml-geometry.js — the conform-field capture pass (spec §4).
 *
 * editorial-core's existing DTO drops every conform-critical field; this is the
 * sibling extractor (cf. parsers/xmeml-tc.js) that captures the geometry the
 * Oracle needs, keyed by clip, with FILE-IDS RESOLVED FIRST (non-negotiable #6:
 * 269 of this reel's 334 <file> references are self-closing `<file id=".."/>`
 * that only make sense once mapped back to their full definition).
 *
 * Output per clip:
 *   { seqstart, seqend, xml_in, xml_out, pproTicksIn, pproTicksOut,
 *     is_subclip, subclip_startoffset, scale_premiere, speed, reverse, fileId,
 *     source_basename, srcW, srcH, edges_resolved, transition_in, transition_out }
 *   (-1 edges from Resolve's FCP7 writer resolve to the adjacent transition's
 *   junction; transition_in/out are the windows the clip's edges sit in)
 *
 * Pure: takes an XML string, returns plain data. No IO.
 */

const { XMLParser } = require('fast-xml-parser');

const PARSER = new XMLParser({
  ignoreAttributes: false,
  attributeNamePrefix: '@_',
  parseTagValue: true,
  trimValues: true,
});

function asArray(x) {
  if (x === undefined || x === null) return [];
  return Array.isArray(x) ? x : [x];
}

function num(v) {
  if (v === undefined || v === null || v === '') return null;
  const n = Number(v);
  return Number.isNaN(n) ? null : n;
}

/** Decode a file://… pathurl (or fall back to a name) to a basename. */
function basenameFromFile(fileDef) {
  const raw = fileDef.pathurl != null ? String(fileDef.pathurl) : null;
  if (raw) {
    let p = raw;
    try {
      p = decodeURIComponent(p);
    } catch (e) {
      /* leave encoded if malformed */
    }
    const idx = p.lastIndexOf('/');
    return idx >= 0 ? p.slice(idx + 1) : p;
  }
  return fileDef.name != null ? String(fileDef.name) : null;
}

/** Extract the source W/H from a full <file> definition's video samplechars. */
function sourceDims(fileDef) {
  const sc =
    fileDef &&
    fileDef.media &&
    fileDef.media.video &&
    fileDef.media.video.samplecharacteristics;
  if (!sc) return { srcW: null, srcH: null };
  return { srcW: num(sc.width), srcH: num(sc.height) };
}

/**
 * Walk the whole tree collecting FULL <file> definitions (those carrying media
 * or a pathurl) into an id -> def map, so self-closing references resolve.
 */
function collectFileDefs(node, map) {
  if (node === null || typeof node !== 'object') return;
  if (Array.isArray(node)) {
    for (const n of node) collectFileDefs(n, map);
    return;
  }
  for (const key of Object.keys(node)) {
    if (key === 'file') {
      for (const f of asArray(node[key])) {
        if (f && typeof f === 'object' && f['@_id'] != null) {
          const id = String(f['@_id']);
          const isFullDef = f.media !== undefined || f.pathurl !== undefined;
          if (isFullDef && !map[id]) {
            const { srcW, srcH } = sourceDims(f);
            map[id] = { basename: basenameFromFile(f), srcW, srcH };
          }
        }
      }
    }
    collectFileDefs(node[key], map);
  }
}

/** Find a filter parameter object by parameterid (case-insensitive), or null. */
function findParam(clipitem, parameterid) {
  const want = String(parameterid).toLowerCase();
  for (const filter of asArray(clipitem.filter)) {
    const effect = filter && filter.effect;
    if (!effect) continue;
    for (const p of asArray(effect.parameter)) {
      if (p && String(p.parameterid).toLowerCase() === want) return p;
    }
  }
  return null;
}

/** Scalar value of a parameter, or null. */
function scalarParam(clipitem, parameterid) {
  const p = findParam(clipitem, parameterid);
  return p ? num(p.value) : null;
}

/**
 * Capture the Time-Remap speed. A clip with no Time Remap is un-retimed; we
 * report 100 (%) so downstream code has a number, and null only when truly
 * absent and we cannot assume. Premiere encodes 50% slow-mo as a non-100 speed
 * here AND as ticks/tpf != <in> in the Oracle — the two must agree.
 */
function captureSpeed(clipitem) {
  const p = findParam(clipitem, 'speed');
  if (!p) return 100; // no Time Remap => normal speed
  const v = num(p.value);
  return v == null ? 100 : v;
}

/** A reversed clip carries a Time Remap with parameter `reverse` = TRUE. */
function captureReverse(clipitem) {
  const p = findParam(clipitem, 'reverse');
  if (!p) return false;
  return String(p.value).toUpperCase() === 'TRUE';
}

/** Capture Basic-Motion center/rotation/crop (reframes + online/offline Y residual). */
function captureTransform(clipitem) {
  const center = findParam(clipitem, 'center');
  const c = center && center.value ? center.value : null;
  return {
    center: c ? { h: num(c.horiz), v: num(c.vert) } : null,
    rotation: scalarParam(clipitem, 'rotation'),
    crop: {
      left: scalarParam(clipitem, 'leftcrop'),
      top: scalarParam(clipitem, 'topcrop'),
      right: scalarParam(clipitem, 'rightcrop'),
      bottom: scalarParam(clipitem, 'bottomcrop'),
    },
  };
}


/**
 * A track's transitionitems as junctions: the frame a `-1` clip edge resolves
 * to (alignment-dependent) plus the span. Alignment vocabulary per Resolve's
 * writer: start/start-black → span start, end/end-black → span end, center
 * (or absent) → span center.
 */
function trackJunctions(track) {
  const out = [];
  for (const tr of asArray(track && track.transitionitem)) {
    if (!tr) continue;
    const s0 = num(tr.start);
    const e0 = num(tr.end);
    if (s0 == null || e0 == null) continue;
    const al = String(tr.alignment || 'center').toLowerCase();
    const frame = al === 'start-black' || al === 'start' ? s0 : al === 'end-black' || al === 'end' ? e0 : Math.round((s0 + e0) / 2);
    const effect = tr.effect || {};
    out.push({ frame, start: s0, end: e0, alignment: al, effectid: effect.effectid != null ? String(effect.effectid) : null });
  }
  return out;
}

/** Capture video transitions (dissolves/wipes) across the sequence's video tracks. */
function videoTransitions(sequence) {
  const tracks = asArray(
    sequence && sequence.media && sequence.media.video && sequence.media.video.track,
  );
  const out = [];
  tracks.forEach((track, ti) => {
    for (const tr of asArray(track.transitionitem)) {
      if (!tr) continue;
      const effect = tr.effect || {};
      out.push({
        track: ti + 1,
        start: num(tr.start),
        end: num(tr.end),
        duration: num(tr.end) != null && num(tr.start) != null ? num(tr.end) - num(tr.start) : null,
        alignment: tr.alignment != null ? String(tr.alignment) : null,
        effectid: effect.effectid != null ? String(effect.effectid) : null,
        category: effect.effectcategory != null ? String(effect.effectcategory) : null,
        mediatype: effect.mediatype != null ? String(effect.mediatype) : null,
        reverse: effect.reverse != null ? String(effect.reverse).toUpperCase() === 'TRUE' : false,
      });
    }
  });
  return out;
}

function sequenceInfo(sequence) {
  const sc =
    sequence &&
    sequence.media &&
    sequence.media.video &&
    sequence.media.video.format &&
    sequence.media.video.format.samplecharacteristics;
  const rate = sc && sc.rate;
  return {
    name: sequence && sequence.name != null ? String(sequence.name) : null,
    width: sc ? num(sc.width) : null,
    height: sc ? num(sc.height) : null,
    fps: rate ? num(rate.timebase) : null,
  };
}

/**
 * Parse an XMEML string into captured conform geometry.
 * @param {string} xml
 * @returns {{ sequence: object, fileDefs: object, clips: object[] }}
 */
function parseGeometry(xml) {
  const doc = PARSER.parse(xml);
  const sequence = doc && doc.xmeml && doc.xmeml.sequence;
  if (!sequence) throw new Error('xmeml-geometry: no <xmeml><sequence> found');

  // Pass 1 — resolve file-ids (non-negotiable #6) BEFORE reading clip fields.
  const fileDefs = {};
  collectFileDefs(doc, fileDefs);

  // Pass 2 — capture per-clip geometry, track by track so each clip can be
  // resolved against ITS track's transitionitems.
  //
  // Resolve's FCP7 writer (measured, E105/E107): a clipitem edge that sits
  // under a transitionitem is written as `-1` and means "this edge is the
  // adjacent transition's JUNCTION" — the span center for alignment center,
  // the span start/end for start(-black)/end(-black). `out - in` is the
  // RECORD duration even under a retime, which anchors the missing edge. A
  // -1 START edge's <in> is the source at the OVERLAP start (the material
  // begins under the transition), so <in>/<out> advance by (junction -
  // span start) to stay record-aligned. Left raw, a -1 record position poisons
  // every consumer downstream (oracle null, reference sampled at frame 0).
  const clips = [];
  const tracks = asArray(sequence && sequence.media && sequence.media.video && sequence.media.video.track);
  for (const track of tracks) {
    const junctions = trackJunctions(track);
    const js = junctions.map((j) => j.frame).sort((a, b) => a - b);
    // Clips are written in record order, so a clip whose BOTH edges are -1
    // can only pair junctions at or after the previous clip's end. Without
    // the cursor, two equal-length clips under three centered transitions
    // both resolve to the FIRST pair (measured, E107).
    let cursor = 0;
    for (const ci of asArray(track.clipitem)) {
      // A real clip has a record position + a source in-point.
      if (!(ci && ci.start !== undefined && ci.in !== undefined)) continue;
      const fileNode = ci.file;
      const fileId = fileNode && fileNode['@_id'] != null ? String(fileNode['@_id']) : null;
      const def = fileId ? fileDefs[fileId] : null;
      // Resolve's FCP7 writer flattens a COMPOUND CLIP to a clipitem whose
      // <file> carries an explicitly EMPTY <pathurl> and no inner content
      // (measured E120/E121). It has no flat source to sample.
      const isCompound = !!(fileNode && typeof fileNode.pathurl === 'string' && fileNode.pathurl.trim() === '');
      const sub = ci.subclipinfo;
      const startoffset = sub ? num(sub.startoffset) : null;
      const endoffset = sub ? num(sub.endoffset) : null;
      const transform = captureTransform(ci);
      const start0 = num(ci.start);
      const end0 = num(ci.end);
      const inF = num(ci.in);
      const outF = num(ci.out);
      const dur = inF != null && outF != null ? outF - inF : null;
      let start = start0;
      let end = end0;
      let inAdj = 0;
      if (start === -1 && end !== -1 && end != null && dur != null) start = end - dur;
      else if (end === -1 && start !== -1 && start != null && dur != null) end = start + dur;
      else if (start === -1 && end === -1 && dur != null && js.length) {
        const pair = js.find((a) => a >= cursor && js.includes(a + dur));
        if (pair != null) {
          start = pair;
          end = pair + dur;
        }
      }
      if (end != null && end >= 0) cursor = Math.max(cursor, end);
      if (start0 === -1 && start != null && start >= 0) {
        const j = junctions.find((jj) => jj.frame === start);
        if (j) inAdj = start - j.start;
      }
      const edgesResolved = start0 === -1 || end0 === -1;
      const unresolved = (start0 === -1 && (start == null || start < 0)) || (end0 === -1 && (end == null || end < 0));
      // The transition windows this clip's edges sit in: the incoming window
      // contains the record start, the outgoing window contains the record
      // end. Downstream frame-QC must sample CLEAR of both (the reference is
      // a blend — or black, for a fade — inside them).
      const win = (j) => (j ? { start: j.start, end: j.end, junction: j.frame, alignment: j.alignment, effectid: j.effectid } : null);
      const inWin = start != null && start >= 0 ? junctions.find((j) => start >= j.start && start <= j.end) : null;
      const outWin = end != null && end >= 0 ? junctions.find((j) => end >= j.start && end <= j.end) : null;
      clips.push({
        seqstart: start,
        seqend: end,
        xml_in: inF != null ? inF + inAdj : inF,
        xml_out: outF != null ? outF + inAdj : outF,
        pproTicksIn: num(ci.pproTicksIn),
        pproTicksOut: num(ci.pproTicksOut),
        is_subclip: startoffset != null,
        subclip_startoffset: startoffset != null ? startoffset : 0,
        subclip_endoffset: endoffset != null ? endoffset : 0,
        scale_premiere: scalarParam(ci, 'scale'),
        speed: captureSpeed(ci),
        reverse: captureReverse(ci),
        center: transform.center,
        rotation: transform.rotation,
        crop: transform.crop,
        fileId,
        source_basename: def ? def.basename : null,
        srcW: def ? def.srcW : null,
        srcH: def ? def.srcH : null,
        edges_resolved: edgesResolved,
        edges_unresolved: unresolved,
        is_compound: isCompound,
        transition_in: win(inWin),
        transition_out: win(outWin),
      });
    }
  }

  return { sequence: sequenceInfo(sequence), fileDefs, clips, transitions: videoTransitions(sequence) };
}

module.exports = { parseGeometry, basenameFromFile };
