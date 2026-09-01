/**
 * Premiere .prproj offline reader — enumeration + normalized events, NO Premiere, NO new deps.
 *
 * A .prproj is gzip-compressed XML (Premiere CC 2013+; CS6 was plain XML). The XML is a FLAT
 * object-reference graph: every object carries an `ObjectID` and is linked from elsewhere by
 * `ObjectRef`. We gunzip (node `zlib`), parse (`fast-xml-parser`, already a dep), index every
 * object by ObjectID, then walk Sequence → Video/AudioTracks → Track → TrackItems → *ClipTrackItem.
 *
 * Time is in TICKS (254,016,000,000 per second — factors by every standard frame/sample rate).
 * We derive from tick geometry alone: cuts, source in/out, timeline position, SPEED/retime
 * (srcDur/recDur), REVERSE (in>out), transitions (VideoTransitionTrackItem span, recStart-explicit; edge spans synthesize BL fade legs), and markers.
 *
 * HONEST limits (skip-not-fake): the schema is proprietary and version-drifting (Project Version
 * 25→42+); editorial timing/structure decodes with high fidelity, but per-clip EFFECTS / Lumetri
 * COLOR are NOT translated (that's the Premiere→Resolve semantic gap present in every turnover
 * format, not a reader limit). Resolve has no native .prproj importer — this is offline READ; to
 * conform, convert the events to OTIO/EDL/DRT (see authorInterchange) and import that.
 */
import fs from 'node:fs';
import zlib from 'node:zlib';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);

export const TICKS_PER_SECOND = 254016000000;

/** Read a .prproj into its XML string, transparently handling gzip (CC) and plain XML (CS6). */
export function readPrprojXml(pathOrBuffer) {
  const buf = Buffer.isBuffer(pathOrBuffer) ? pathOrBuffer : fs.readFileSync(pathOrBuffer);
  if (buf.length >= 2 && buf[0] === 0x1f && buf[1] === 0x8b) return zlib.gunzipSync(buf).toString('utf8');
  const s = buf.toString('utf8');
  if (s.includes('<PremiereData')) return s; // CS6 / uncompressed
  throw new Error('Not a .prproj: no gzip magic and no <PremiereData> root. A .prproj is gzip-compressed XML (CC) or plain XML (CS6).');
}

const asArray = (v) => (v == null ? [] : Array.isArray(v) ? v : [v]);

/** Text of a child element, tolerating fast-xml-parser's {#text} wrapping when the node has attrs. */
function childText(node, tag) {
  if (!node) return null;
  const v = node[tag];
  if (v == null) return null;
  if (typeof v === 'object') return v['#text'] != null ? v['#text'] : null;
  return v;
}

// A real Premiere 2025 object carries its name as a direct <Name> child
// (E132); the legacy/synthetic shape keeps it under Node/Properties.
const nodeName = (node) => {
  const direct = childText(node, 'Name');
  if (direct != null && String(direct).trim() !== '') return String(direct).trim();
  return childText(node?.Node?.Properties, 'Name');
};

/** ticks → whole frames at fps. */
function ticksToFrames(ticks, fps) {
  const t = Number(ticks);
  if (!Number.isFinite(t) || !fps) return null;
  return Math.round(t / (TICKS_PER_SECOND / fps));
}

/** Sequence FrameRate is a rate (e.g. 25) OR ticks-per-frame (huge); normalize to fps. */
function deriveFps(seqNode) {
  const raw = childText(seqNode?.Node?.Properties, 'FrameRate');
  const v = Number(raw);
  if (!Number.isFinite(v) || v <= 0) return 24;
  if (v > 100000) return +(TICKS_PER_SECOND / v).toFixed(3); // stored as ticks-per-frame
  return v;
}

/** Parse the XML into an ObjectID → {tag, node} index. Objects are flat children of PremiereData. */
function indexObjects(xml) {
  const { XMLParser } = require('fast-xml-parser');
  const parser = new XMLParser({ ignoreAttributes: false, attributeNamePrefix: '@_' });
  const doc = parser.parse(xml);
  const pd = doc.PremiereData;
  if (!pd) throw new Error('Not a .prproj: missing <PremiereData> root.');
  // Two id spaces (E132, measured on a real Premiere 2025 turnover): objects
  // are defined by numeric `ObjectID` (referenced by `ObjectRef`) OR by a
  // uuid `ObjectUID` (referenced by `ObjectURef`) — sequences, project items,
  // master clips, media and clip tracks are all UID-defined there, so a map
  // keyed on ObjectID alone listed ZERO sequences. Key both; the spaces do
  // not collide (integers vs uuids).
  const byId = new Map();
  for (const [tag, val] of Object.entries(pd)) {
    if (tag.startsWith('@_')) continue;
    for (const node of asArray(val)) {
      if (!node || typeof node !== 'object') continue;
      if (node['@_ObjectID'] != null) byId.set(String(node['@_ObjectID']), { tag, node });
      if (node['@_ObjectUID'] != null) byId.set(String(node['@_ObjectUID']), { tag, node });
    }
  }
  return { byId, projectVersion: firstProjectVersion(byId) };
}

function firstProjectVersion(byId) {
  for (const { tag, node } of byId.values()) {
    if (tag === 'Project' && node['@_Version'] != null) return Number(node['@_Version']);
  }
  return null;
}

/** The id a reference element names: numeric ObjectRef or uuid ObjectURef (E132). */
const refId = (r) => (r ? String(r['@_ObjectRef'] ?? r['@_ObjectURef'] ?? '') : '');
const ref = (node, tag) => {
  const r = asArray(node?.[tag])[0];
  return r ? refId(r) : null;
};

/** Best-effort source label for a clip item: media basename, else project-item name, else UNKNOWN. */
function resolveSourceName(clipNode, byId) {
  const cpiId = ref(clipNode, 'ClipProjectItem') || ref(clipNode, 'SubClip') || ref(clipNode, 'ProjectItem');
  const cpi = cpiId ? byId.get(cpiId) : null;
  if (cpi) {
    const path = findFirstText(cpi.node, ['ActualMediaFilePath', 'FilePath', 'RelativePath'], 6);
    if (path) return String(path).split(/[\\/]/).pop();
    const nm = nodeName(cpi.node);
    if (nm) return nm;
  }
  return nodeName(clipNode) || 'UNKNOWN';
}

/** Shallow recursive search for the first non-empty text under any of `tags` (depth-bounded). */
function findFirstText(node, tags, depth) {
  if (!node || typeof node !== 'object' || depth < 0) return null;
  for (const tag of tags) {
    const t = childText(node, tag);
    if (t) return t;
  }
  for (const k of Object.keys(node)) {
    if (k.startsWith('@_') || k === '#text') continue;
    for (const child of asArray(node[k])) {
      const found = findFirstText(child, tags, depth - 1);
      if (found) return found;
    }
  }
  return null;
}

/**
 * Record timing of a track item in either shape: Start/End directly on the
 * item (synthetic/legacy) or under its <ClipTrackItem>/<TransitionTrackItem>
 * <TrackItem> child (real Premiere 2025, E132).
 */
function itemTiming(node) {
  // A ZERO is written as ABSENCE (measured E132: the counting leader at
  // record 0 carries <End> and no <Start>), so a present End with no Start
  // means Start 0 — never "unknown".
  const norm = (t) => ({ start: t.start != null ? t.start : (t.end != null ? 0 : null), end: t.end });
  const direct = { start: childText(node, 'Start'), end: childText(node, 'End') };
  if (direct.end != null) return norm(direct);
  for (const k of Object.keys(node || {})) {
    if (!/TrackItem$/.test(k)) continue;
    const inner = asArray(node[k])[0];
    const ti = inner && asArray(inner.TrackItem)[0];
    if (ti && childText(ti, 'End') != null) return norm({ start: childText(ti, 'Start'), end: childText(ti, 'End') });
  }
  return norm(direct);
}

/**
 * Source timing + name of a real Premiere clip item: ClipTrackItem.SubClip →
 * SubClip.Clip → VideoClip/AudioClip (InPoint/OutPoint, Source) →
 * VideoMediaSource.MediaSource.Media → Media (file path). Null when the item
 * is the synthetic shape (InPoint/OutPoint on the item itself).
 */
function realClipSource(clipNode, byId) {
  const cti = asArray(clipNode.ClipTrackItem)[0];
  if (!cti) return null;
  const sub = byId.get(ref(cti, 'SubClip') || '');
  if (!sub) return null;
  const clip = byId.get(ref(sub.node, 'Clip') || '');
  const inner = clip && (asArray(clip.node.Clip)[0] || clip.node);
  const outPt = inner ? childText(inner, 'OutPoint') : null;
  // Same omitted-zero law for the source in-point.
  const inPt = inner ? (childText(inner, 'InPoint') != null ? childText(inner, 'InPoint') : (outPt != null ? 0 : null)) : null;
  let name = null;
  const srcEntry = inner && byId.get(ref(inner, 'Source') || '');
  // A NESTED SEQUENCE used as a clip (E133, measured: 3607 such items in one
  // real turnover): the clip's Source is a Video/AudioSequenceSource whose
  // SequenceSource.Sequence references another Sequence object.
  if (srcEntry && /SequenceSource$/.test(srcEntry.tag)) {
    const ss = asArray(srcEntry.node.SequenceSource)[0];
    const nestedId = ss ? ref(ss, 'Sequence') : null;
    const nested = nestedId ? byId.get(nestedId) : null;
    if (nested && nested.tag === 'Sequence') {
      return { inPt, outPt, name: nodeName(nested.node) || 'NESTED', nestedSequence: nested };
    }
  }
  const ms = srcEntry && asArray(srcEntry.node.MediaSource)[0];
  const media = ms && byId.get(ref(ms, 'Media') || '');
  if (media) {
    const path = findFirstText(media.node, ['ActualMediaFilePath', 'FilePath', 'RelativePath'], 6);
    if (path) name = String(path).split(/[\\/]/).pop();
  }
  if (!name) {
    const master = byId.get(ref(sub.node, 'MasterClip') || '');
    name = (master && nodeName(master.node)) || nodeName(sub.node) || null;
  }
  return { inPt, outPt, name };
}

function clipEvent(clipNode, byId, track, fps, index) {
  const timing = itemTiming(clipNode);
  const real = realClipSource(clipNode, byId);
  const start = timing.start;
  const end = timing.end;
  const inPt = real && real.inPt != null ? real.inPt : childText(clipNode, 'InPoint');
  const outPt = real && real.outPt != null ? real.outPt : childText(clipNode, 'OutPoint');
  const recIn = ticksToFrames(start, fps);
  const recOut = ticksToFrames(end, fps);
  const srcIn = ticksToFrames(inPt, fps);
  const srcOut = ticksToFrames(outPt, fps);
  // Speed from tick geometry: |source span| / |timeline span|. Reverse when in > out.
  let speed = 100;
  let reverse = false;
  const srcSpan = Number(outPt) - Number(inPt);
  const recSpan = Number(end) - Number(start);
  if (Number.isFinite(srcSpan) && Number.isFinite(recSpan) && recSpan !== 0) {
    speed = +(Math.abs(srcSpan / recSpan) * 100).toFixed(2);
    reverse = srcSpan < 0;
  }
  return {
    index,
    track,
    source: (real && real.name) || resolveSourceName(clipNode, byId),
    ...(real && real.nestedSequence ? { __nested: real.nestedSequence } : {}),
    srcIn: reverse ? srcOut : srcIn,
    srcOut: reverse ? srcIn : srcOut,
    recIn,
    recOut,
    speed,
    reverse,
    transition: null,
    fps,
  };
}

function walkSequence(seqEntry, byId, depth = 0, seen = new Set()) {
  const fps = deriveFps(seqEntry.node);
  const events = [];
  let idx = 1;
  const seqKey = String(seqEntry.node['@_ObjectUID'] ?? seqEntry.node['@_ObjectID'] ?? '');
  const seenHere = new Set(seen);
  if (seqKey) seenHere.add(seqKey);
  // Two sequence shapes (E132): the synthetic/legacy one lists tracks under
  // <VideoTracks>/<AudioTracks>; a real Premiere 2025 project lists
  // <TrackGroups> whose <Second> references a VideoTrackGroup /
  // AudioTrackGroup carrying <TrackGroup><Tracks><Track ObjectURef>.
  const trackLists = [];
  for (const [container, trackKind] of [['VideoTracks', 'V'], ['AudioTracks', 'A']]) {
    const refs = asArray(seqEntry.node[container]?.Track);
    if (refs.length) trackLists.push({ trackKind, refs });
  }
  for (const tg of asArray(seqEntry.node.TrackGroups?.TrackGroup)) {
    const grp = byId.get(refId(asArray(tg.Second)[0]));
    if (!grp) continue;
    const trackKind = /^Audio/.test(grp.tag) ? 'A' : /^Video/.test(grp.tag) ? 'V' : null;
    if (!trackKind) continue;
    const refs = asArray(grp.node.TrackGroup?.Tracks?.Track);
    if (refs.length) trackLists.push({ trackKind, refs });
  }
  // Lanes number per kind in track order — V, V2, V3 … / A, A2 … — like
  // every other parser (E109/E135): labelling every track 'V'/'A' stacked
  // 687 of 741 real sequences' cuts onto one lane (4631 overlapping pairs).
  const laneCount = { V: 0, A: 0 };
  for (const { trackKind, refs: trackRefs } of trackLists) {
    for (const tref of trackRefs) {
      const tEntry = byId.get(refId(tref));
      if (!tEntry) continue;
      laneCount[trackKind] += 1;
      const laneNum = laneCount[trackKind];
      const trackLabel = laneNum === 1 ? trackKind : `${trackKind}${laneNum}`;
      // Real Premiere 2025 keeps a track's TRANSITIONS in a separate list,
      // ClipTrack.TransitionItems (E134, measured: 2 video + 1 audio on the
      // reel — none reached the parser from ClipItems alone).
      const itemRefs = asArray(tEntry.node.TrackItems?.TrackItem).concat(
        asArray(tEntry.node.ClipTrack?.ClipItems?.TrackItems?.TrackItem),
        asArray(tEntry.node.ClipItems?.TrackItems?.TrackItem),
        asArray(tEntry.node.ClipTrack?.TransitionItems?.TrackItems?.TrackItem),
        asArray(tEntry.node.TransitionItems?.TrackItems?.TrackItem),
      );
      const transitions = [];
      const clipEvents = [];
      for (const iref of itemRefs) {
        const cEntry = byId.get(refId(iref));
        if (!cEntry) continue;
        if (/ClipTrackItem$/.test(cEntry.tag)) {
          const ev = clipEvent(cEntry.node, byId, trackLabel, fps, idx++);
          const nested = ev.__nested;
          delete ev.__nested;
          const nestedKey = nested ? String(nested.node['@_ObjectUID'] ?? nested.node['@_ObjectID'] ?? '') : '';
          if (nested && depth < 8 && !seenHere.has(nestedKey)) {
            // Defer the FLATTEN (E133/E135): expanded after every parent lane
            // is known, so a nested block's inner lanes can first-fit above
            // whatever the parent already stacks there — two nested
            // sequences on different parent lanes each bring their own inner
            // lanes, and a fixed offset collides (measured: 7615 overlapping
            // pairs on the reels project).
            ev.__nestedExpand = { nested, laneNum, trackKind, seenHere };
            clipEvents.push(ev);
            continue;
          }
          if (nested) ev.compound = ev.source; // cycle/depth guard: keep it as a named compound hole
          clipEvents.push(ev);
        } else if (/Transition/.test(cEntry.tag)) {
          const ti = itemTiming(cEntry.node);
          const dur = ticksToFrames(Number(ti.end) - Number(ti.start), fps);
          // Real shape carries the type and the fade semantics on the item
          // (E134): DisplayName/MatchName name the effect; HasOutgoingClip
          // false = a fade-IN from black/silence, HasIncomingClip false = a
          // fade-OUT — the BL synthesis below keys on the missing neighbour.
          const tti = asArray(cEntry.node.TransitionTrackItem)[0] || {};
          const type = childText(tti, 'DisplayName') || childText(tti, 'MatchName') || childText(cEntry.node, 'DisplayName') || null;
          transitions.push({ recIn: ticksToFrames(ti.start, fps), duration: dur || 0, type });
        }
      }
      // Attach each transition to the INCOMING clip whose record-in falls
      // inside its span — Premiere stores the explicit record span, so
      // recStart carries it and the bridge reproduces the editor's actual
      // alignment (the old exact-start match silently dropped every
      // centered transition). A span with no outgoing clip is a fade-IN,
      // one with no incoming a fade-OUT — both synthesize BL legs for the
      // bridge's black machinery (E91-E96).
      for (const tr of transitions) {
        const end = tr.recIn + tr.duration;
        const trans = { type: tr.type || 'dissolve', duration: tr.duration, recStart: tr.recIn };
        const incoming = clipEvents.find((e) => e.recIn > tr.recIn - 1 && e.recIn <= end);
        if (incoming) {
          incoming.transition = trans;
          const outgoing = clipEvents.find((e) => e !== incoming && e.recOut > tr.recIn - 1 && e.recOut <= end);
          if (!outgoing) {
            clipEvents.push({ index: idx++, track: trackLabel, source: 'BL', srcIn: 0, srcOut: 0, recIn: incoming.recIn, recOut: incoming.recIn, speed: 100, reverse: false, transition: null, fps });
          }
        } else {
          const outgoing = clipEvents.find((e) => e.recOut > tr.recIn - 1 && e.recOut <= end);
          if (outgoing) {
            clipEvents.push({ index: idx++, track: trackLabel, source: 'BL', srcIn: 0, srcOut: 0, recIn: outgoing.recOut, recOut: outgoing.recOut, speed: 100, reverse: false, transition: trans, fps });
          }
        }
      }
      events.push(...clipEvents);
    }
  }
  return expandNestedPlaceholders(events, byId, fps, depth);
}

/**
 * Flatten every deferred nested-sequence placeholder into the parent record
 * time (E133/E135). Inner lanes land on the parent's lane and the lanes above
 * it, shifted up by the smallest offset at which none of the block's cuts
 * overlap what the parent (or an earlier block) already holds on those lanes.
 */
function expandNestedPlaceholders(events, byId, fps, depth) {
  const laneOf = (t) => parseInt(String(t).replace(/\D/g, '') || '1', 10);
  const label = (kind, n) => (n === 1 ? kind : `${kind}${n}`);
  const occupancy = new Map(); // lane label → [[recIn, recOut], …]
  const occupy = (e) => { if (e.recIn == null || e.recOut == null) return; (occupancy.get(e.track) || occupancy.set(e.track, []).get(e.track)).push([e.recIn, e.recOut]); };
  const free = (lane, a, b) => !(occupancy.get(lane) || []).some(([x, y]) => a < y && b > x);
  for (const e of events) if (!e.__nestedExpand) occupy(e);
  const out = [];
  let idx = 1;
  for (const ev of events) {
    const ph = ev.__nestedExpand;
    if (!ph) { out.push({ ...ev, index: idx++ }); continue; }
    delete ev.__nestedExpand;
    const { nested, laneNum, trackKind, seenHere } = ph;
    const inner = walkSequence(nested, byId, depth + 1, seenHere).filter((e) => e.track.charAt(0) === trackKind && e.recIn != null && e.recOut != null);
    const winStart = ev.srcIn ?? 0;
    const winLen = (ev.recOut ?? 0) - (ev.recIn ?? 0);
    const block = [];
    for (const e of inner) {
      const a = e.recIn - winStart, b = e.recOut - winStart;
      const a2 = Math.max(0, a), b2 = Math.min(winLen, b);
      if (b2 <= a2) continue;
      const k = ((e.speed ?? 100) / 100) * (e.reverse ? -1 : 1);
      block.push({ ...e, recIn: ev.recIn + a2, recOut: ev.recIn + b2, srcIn: e.srcIn != null ? Math.round(e.srcIn + (a2 - a) * k) : e.srcIn, srcOut: e.srcOut != null ? Math.round(e.srcOut - (b - b2) * k) : e.srcOut, fromCompound: ev.source, __innerLane: laneOf(e.track) });
    }
    // First-fit: the smallest upward shift at which every cut of the block finds its lane free.
    let shift = 0;
    for (; shift < 64; shift += 1) {
      if (block.every((e) => free(label(trackKind, laneNum + e.__innerLane - 1 + shift), e.recIn, e.recOut))) break;
    }
    let first = true;
    for (const e of block) {
      const placed = { ...e, index: idx++, track: label(trackKind, laneNum + e.__innerLane - 1 + shift) };
      delete placed.__innerLane;
      if (shift) placed.laneShift = shift;
      if (first && ev.transition && !placed.transition) placed.transition = ev.transition;
      first = false;
      occupy(placed);
      out.push(placed);
    }
    if (!block.length) out.push({ ...ev, index: idx++, compound: ev.source });
  }
  return out;
}

/** Enumerate marker objects (project- or sequence-level) with tick→frame positions. */
function collectMarkers(byId, fps) {
  const markers = [];
  for (const { tag, node } of byId.values()) {
    if (tag !== 'Marker') continue;
    markers.push({
      frame: ticksToFrames(childText(node, 'Position'), fps),
      duration: ticksToFrames(childText(node, 'Duration'), fps) || 0,
      name: childText(node, 'Name') || '',
      note: childText(node, 'Comment') || '',
      type: Number(childText(node, 'MarkerType')) || 0,
      colorIndex: Number(childText(node, 'ColorIndex')) || 0,
    });
  }
  return markers;
}

function sequenceEntries(byId) {
  const seqs = [];
  for (const entry of byId.values()) if (entry.tag === 'Sequence') seqs.push(entry);
  return seqs;
}

/**
 * Parse a .prproj into per-sequence structure.
 * @returns {{projectVersion:number|null, sequences:Array<{id,name,fps,eventCount,events,markers}>, mediaPaths:string[]}}
 */
export function parsePrprojDoc(pathOrBuffer) {
  const xml = readPrprojXml(pathOrBuffer);
  const { byId, projectVersion } = indexObjects(xml);
  const sequences = sequenceEntries(byId).map((entry) => {
    const fps = deriveFps(entry.node);
    const events = walkSequence(entry, byId);
    return {
      id: String(entry.node['@_ObjectID'] ?? entry.node['@_ObjectUID']),
      name: nodeName(entry.node) || `Sequence ${entry.node['@_ObjectID'] ?? entry.node['@_ObjectUID']}`,
      fps,
      eventCount: events.length,
      events,
      markers: collectMarkers(byId, fps),
    };
  });
  const mediaPaths = [...new Set(collectMediaPaths(byId))].sort();
  return { projectVersion, sequences, mediaPaths };
}

function collectMediaPaths(byId) {
  const paths = [];
  for (const { node } of byId.values()) {
    for (const tag of ['ActualMediaFilePath', 'FilePath']) {
      const t = childText(node, tag);
      if (t) paths.push(String(t));
    }
  }
  return paths;
}

/** FLAT normalized-event list across every sequence (mirrors parseEDL/parseOTIO output). */
export function parsePrproj(pathOrBuffer) {
  const { sequences } = parsePrprojDoc(pathOrBuffer);
  const events = [];
  for (const s of sequences) for (const e of s.events) events.push(e);
  return events;
}

/** Enumerate sequences for the picker. */
export function listPrprojSequences(pathOrBuffer) {
  const { sequences } = parsePrprojDoc(pathOrBuffer);
  return sequences.map((s, index) => ({ id: s.id, name: s.name, eventCount: s.eventCount, index }));
}
