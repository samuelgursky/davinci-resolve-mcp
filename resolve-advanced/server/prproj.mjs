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
 * (srcDur/recDur), REVERSE (in>out), transitions (VideoTransitionTrackItem span), and markers.
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

const nodeName = (node) => childText(node?.Node?.Properties, 'Name');

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
  const byId = new Map();
  for (const [tag, val] of Object.entries(pd)) {
    if (tag.startsWith('@_')) continue;
    for (const node of asArray(val)) {
      if (node && typeof node === 'object' && node['@_ObjectID'] != null) byId.set(String(node['@_ObjectID']), { tag, node });
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

const ref = (node, tag) => {
  const r = asArray(node?.[tag])[0];
  return r ? String(r['@_ObjectRef'] ?? '') : null;
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

function clipEvent(clipNode, byId, track, fps, index) {
  const start = childText(clipNode, 'Start');
  const end = childText(clipNode, 'End');
  const inPt = childText(clipNode, 'InPoint');
  const outPt = childText(clipNode, 'OutPoint');
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
    source: resolveSourceName(clipNode, byId),
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

function walkSequence(seqEntry, byId) {
  const fps = deriveFps(seqEntry.node);
  const events = [];
  let idx = 1;
  for (const [container, trackKind] of [
    ['VideoTracks', 'V'],
    ['AudioTracks', 'A'],
  ]) {
    const trackRefs = asArray(seqEntry.node[container]?.Track);
    for (const tref of trackRefs) {
      const tEntry = byId.get(String(tref['@_ObjectRef'] ?? ''));
      if (!tEntry) continue;
      const itemRefs = asArray(tEntry.node.TrackItems?.TrackItem);
      const transitions = [];
      const clipEvents = [];
      for (const iref of itemRefs) {
        const cEntry = byId.get(String(iref['@_ObjectRef'] ?? ''));
        if (!cEntry) continue;
        if (/ClipTrackItem$/.test(cEntry.tag)) {
          clipEvents.push(clipEvent(cEntry.node, byId, trackKind, fps, idx++));
        } else if (/Transition/.test(cEntry.tag)) {
          const dur = ticksToFrames(Number(childText(cEntry.node, 'End')) - Number(childText(cEntry.node, 'Start')), fps);
          transitions.push({ recIn: ticksToFrames(childText(cEntry.node, 'Start'), fps), duration: dur || 0 });
        }
      }
      // Attach each transition to the clip that begins at its record position (best-effort).
      for (const tr of transitions) {
        const hit = clipEvents.find((e) => e.recIn === tr.recIn);
        if (hit) hit.transition = { type: 'dissolve', duration: tr.duration };
      }
      events.push(...clipEvents);
    }
  }
  return events;
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
      id: String(entry.node['@_ObjectID']),
      name: nodeName(entry.node) || `Sequence ${entry.node['@_ObjectID']}`,
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
