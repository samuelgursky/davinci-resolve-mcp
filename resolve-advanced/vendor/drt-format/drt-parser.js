/**
 * DRT parser — extract timeline structure from a Resolve Timeline archive.
 *
 * DRT is a zip with SeqContainer*.xml + optional MpFolder*.xml, no
 * project.xml. parseDRT walks each SeqContainer, pulls timeline-level
 * settings (Name, FrameRate, StartTC, ResolutionWidth/Height) and
 * per-track clip lists, and returns a normalized structure.
 *
 * @module drt-format/drt-parser
 */

const fs = require('node:fs/promises');
const JSZip = require('jszip');

function listSeqContainerEntries(zip) {
  const out = [];
  zip.forEach((p, e) => {
    if (e.dir) return;
    // Two on-disk conventions for SeqContainer entries:
    //   - tool-authored:  <folder>/SeqContainer<N>.xml  (e.g. Primary1/SeqContainer1.xml)
    //   - Real Resolve export: SeqContainer/<uuid>.xml       (Resolve 21 names each by its DbId)
    // Match both; never match MpFolder.xml / project.xml / Gallery.xml.
    if (/(^|\/)SeqContainer(\d*\.xml|\/[^/]+\.xml)$/.test(p)) out.push(p);
  });
  return out.sort();
}

function extractScalar(xml, tag) {
  const m = xml.match(new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`));
  return m ? m[1].trim() : null;
}

function extractInt(xml, tag) {
  const v = extractScalar(xml, tag);
  if (v === null || v === '') return null;
  const n = Number.parseInt(v, 10);
  return Number.isFinite(n) ? n : null;
}

const CLIP_TAGS = ['Sm2TiVideoClip', 'Sm2VideoClip', 'Sm2TiAudioClip', 'Sm2AudioClip'];

// Resolve stores several scalars as 16-hex-char blobs (E139, measured on a
// 19.1.3.7 EXPORT_DRT): <FrameRate> / <MediaFrameRate> = one little-endian
// IEEE double + 8 pad bytes (24.0 = 0000000000003840…); <MediaExtents> = two
// little-endian doubles, start SECONDS then duration SECONDS; <Resolution> =
// two big-endian uint64, width then height.
function leDouble(hex, offset = 0) {
  const h = String(hex || '').replace(/[^0-9a-fA-F]/g, '');
  if (h.length < offset + 16) return null;
  const v = Buffer.from(h.slice(offset, offset + 16), 'hex').readDoubleLE(0);
  return Number.isFinite(v) ? v : null;
}
function beUint64(hex, offset = 0) {
  const h = String(hex || '').replace(/[^0-9a-fA-F]/g, '');
  if (h.length < offset + 16) return null;
  const v = Number(Buffer.from(h.slice(offset, offset + 16), 'hex').readBigUInt64BE(0));
  return Number.isFinite(v) ? v : null;
}
// <MediaTimemapBA> (E139/E140): tag byte 0x02 + one double = a LINEAR (100%)
// clip whose double is the media length in seconds; a keyed Sm2TimeMap
// (00000001…) is a speed map. E140 decodes it through the DRP library's
// decodeTimemap (the same reader the .drp side uses): the keyframe slope is
// the speed ratio (0.8 on all four retimed clips of a real reel — Premiere's
// 80 for the same cuts), XMax 60000 with a zero slope is the FREEZE sentinel,
// a negative slope is a reverse. A map the decoder cannot read is 'unknown',
// never a faked 100%.
const FREEZE_XMAX_SENTINEL = 60000;
function decodeTimemapField(hex) {
  const h = String(hex || '').replace(/[^0-9a-fA-F]/g, '').toLowerCase();
  if (!h) return null;
  if (h.startsWith('02')) {
    return { form: 'identity', kind: h.length === 18 ? 'linear' : 'linear-multi', speed: 1, reverse: false };
  }
  let d;
  try {
    d = require('../drp-format/media-timemap').decodeTimemap(h);
  } catch {
    return { form: 'retimed', kind: 'unknown', speed: null, reverse: false };
  }
  if (!d || d.form !== 'retimed') return { form: 'retimed', kind: 'unknown', speed: null, reverse: false };
  const slope = d.segments && d.segments.length ? d.segments[0].speed : null;
  const base = { form: 'retimed', recordDurationSec: d.recordDurationSec ?? null, sourceDurationSec: d.sourceDurationSec ?? null };
  if (d.recordDurationSec === FREEZE_XMAX_SENTINEL && slope === 0) return { ...base, kind: 'freeze', speed: 0, reverse: false };
  if (!Number.isFinite(slope) || slope === 0 || Math.abs(slope) > 100) return { ...base, kind: 'unknown', speed: null, reverse: false };
  return {
    ...base,
    kind: d.variable ? 'variable' : 'constant',
    speed: Math.abs(slope),
    reverse: slope < 0,
    ...(d.variable ? { segments: d.segments } : {}),
  };
}
// Sm2TiTransition alignment (E139, witnessed against the cut points of 11
// real dissolves): 2 = centred on the cut, 3 = ends at the cut (the
// one-sided 8-frame fade-in on a real reel is type 3 / Position 1).
const ALIGNMENT_BY_TYPE = { 1: 'start', 2: 'center', 3: 'end' };

function extractTransitionsFromTrackXml(trackXml) {
  const out = [];
  const re = /<(Sm2TiTransition)\b[^>]*?DbId="([^"]+)"[^>]*>([\s\S]*?)<\/\1>/g;
  let m;
  while ((m = re.exec(trackXml)) !== null) {
    const inner = m[3];
    const alignmentType = extractInt(inner, 'AlignmentType');
    out.push({
      transitionId: m[2],
      type: extractScalar(inner, 'PrettyType') || 'Cross Dissolve',
      start: extractInt(inner, 'Start'),
      duration: extractInt(inner, 'Duration'),
      alignmentType,
      alignment: alignmentType != null ? ALIGNMENT_BY_TYPE[alignmentType] || null : null,
      position: extractInt(inner, 'Position'),
    });
  }
  return out;
}

function extractClipsFromTrackXml(trackXml, trackType) {
  const clips = [];
  const tagAlt = CLIP_TAGS.filter((t) => t.toLowerCase().includes(trackType)).join('|');
  if (!tagAlt) return clips;
  const re = new RegExp(`<(${tagAlt})\\b([^>]*?)DbId="([^"]+)"([^>]*)>([\\s\\S]*?)</\\1>`, 'g');
  let m;
  while ((m = re.exec(trackXml)) !== null) {
    const inner = m[5];
    const mediaFilePath = extractScalar(inner, 'MediaFilePath');
    const start = extractInt(inner, 'Start');
    const duration = extractInt(inner, 'Duration');
    const bodyMatch = inner.match(/<Body>([0-9a-fA-F\s]*)<\/Body>/);
    let bodyHex = null;
    if (bodyMatch) {
      const stripped = bodyMatch[1].replace(/[^0-9a-fA-F]/g, '');
      if (stripped.length > 0) bodyHex = stripped;
    }
    const inRaw = extractScalar(inner, 'In');
    const mst = extractScalar(inner, 'MediaStartTime');
    clips.push({
      clipId: m[3],
      name: extractScalar(inner, 'Name'),
      start,
      duration,
      mediaFilePath,
      bodyHex,
      // E139: the clip's SOURCE in-point in frames (<In>); a real export writes
      // an EMPTY <In/> on audio clips and on generator tails — null, not 0.
      in: inRaw === null || inRaw === '' ? null : (Number.isFinite(Number.parseInt(inRaw, 10)) ? Number.parseInt(inRaw, 10) : null),
      mediaStartTime: mst === null || mst === '' ? null : (Number.isFinite(Number(mst)) ? Number(mst) : null),
      mediaFrameRate: leDouble(extractScalar(inner, 'MediaFrameRate')),
      timemap: decodeTimemapField(extractScalar(inner, 'MediaTimemapBA')),
      prettyType: extractScalar(inner, 'PrettyType') || null,
    });
  }
  return clips;
}

function extractTracks(seqXml, trackVecTag, trackTagBase, trackType) {
  const tracks = [];
  // Match the *VideoTrackVec or *AudioTrackVec block.
  const vecMatch = seqXml.match(new RegExp(`<${trackVecTag}>([\\s\\S]*?)</${trackVecTag}>`));
  if (!vecMatch) return tracks;
  const vecXml = vecMatch[1];
  // Track element conventions, both supported:
  //   - tool-authored: <Sm2TiVideoTrack> / <Sm2TiAudioTrack>
  //   - Real Resolve 21:   <Sm2TiTrack> for BOTH, with a <Type> discriminator (0=video,1=audio).
  // The enclosing vec (VideoTrackVec/AudioTrackVec) already determines trackType, so we accept
  // any of the three tag forms and rely on a backreference for the matching close tag.
  // (trackTagBase is retained for call-site compatibility but no longer constrains the match.)
  void trackTagBase;
  const trackRe = /<(Sm2TiVideoTrack|Sm2TiAudioTrack|Sm2TiTrack)\b[^>]*?DbId="([^"]+)"[^>]*>([\s\S]*?)<\/\1>/g;
  let tm;
  while ((tm = trackRe.exec(vecXml)) !== null) {
    const trackId = tm[2];
    const trackInner = tm[3];
    tracks.push({
      trackId,
      trackType,
      clips: extractClipsFromTrackXml(trackInner, trackType),
      transitions: extractTransitionsFromTrackXml(trackInner),
    });
  }
  return tracks;
}

/**
 * The pool folder's own naming of every sequence (E127, measured against
 * Resolve 19.1.3.7's EXPORT_DRT of a compound timeline): a SeqContainer XML
 * carries NO timeline name — its first <Name> is the first CLIP's — while
 * MediaPool/Master/MpFolder.xml holds an Sm2MpTimelineClip (a timeline) or
 * Sm2MpCompoundClip (a compound) whose EMBEDDED <Sm2Sequence DbId=X> equals
 * the container's track-level <Sequence>X</Sequence>. Map X → {name, kind}.
 */
async function loadPoolSequenceNames(zip) {
  const map = new Map();
  const entries = [];
  zip.forEach((p, e) => { if (!e.dir && /(^|\/)MpFolder[^/]*\.xml$/.test(p)) entries.push(p); });
  for (const p of entries) {
    const xml = await zip.file(p).async('string');
    const re = /<(Sm2MpTimelineClip|Sm2MpCompoundClip) DbId="([^"]+)">([\s\S]*?)<\/\1>/g;
    let m;
    while ((m = re.exec(xml)) !== null) {
      const body = m[3];
      const name = extractScalar(body, 'Name');
      const seqRe = /<Sm2Sequence DbId="([^"]+)">([\s\S]*?)<\/Sm2Sequence>/g;
      let sm;
      while ((sm = seqRe.exec(body)) !== null) {
        if (map.has(sm[1])) continue;
        // E139: the embedded Sm2Sequence is also where a real export keeps the
        // timeline's frame rate, record extents and resolution — the
        // SeqContainer carries none of them.
        const sb = sm[2];
        const ext = extractScalar(sb, 'MediaExtents');
        const res = extractScalar(sb, 'Resolution');
        map.set(sm[1], {
          name,
          kind: m[1] === 'Sm2MpCompoundClip' ? 'compound' : 'timeline',
          frameRate: leDouble(extractScalar(sb, 'FrameRate')),
          startSeconds: ext ? leDouble(ext, 0) : null,
          durationSeconds: ext ? leDouble(ext, 16) : null,
          width: res ? beUint64(res, 0) : null,
          height: res ? beUint64(res, 16) : null,
        });
      }
    }
  }
  return map;
}

// E139: a real export's record start lives ONLY in the pool sequence's
// MediaExtents (seconds) — frames = round(seconds × fps); the timecode is
// derived at that rate (non-drop; the export writes no drop flag here).
function poolStartFrame(pool) {
  if (!pool || pool.startSeconds == null || !pool.frameRate) return null;
  return Math.round(pool.startSeconds * pool.frameRate);
}
function poolStartTimecode(pool) {
  const f = poolStartFrame(pool);
  if (f == null) return null;
  const fps = Math.round(pool.frameRate);
  const ff = f % fps, totalS = Math.floor(f / fps);
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(Math.floor(totalS / 3600))}:${pad(Math.floor(totalS / 60) % 60)}:${pad(totalS % 60)}:${pad(ff)}`;
}

function parseSeqContainer(seqXml, sequenceName, poolNames = new Map()) {
  const seqId = extractScalar(seqXml, 'Sequence');
  const pool = seqId ? poolNames.get(seqId) : null;
  const compoundNames = new Set([...poolNames.values()].filter((v) => v.kind === 'compound' && v.name).map((v) => v.name));
  const parsed = {
    // The pool's name for this sequence when the export carries one; the
    // first <Name> in the container is a CLIP name and only a fallback.
    name: (pool && pool.name) || extractScalar(seqXml, 'Name') || sequenceName,
    kind: pool ? pool.kind : null,
    sequence: sequenceName,
    frameRate: extractScalar(seqXml, 'FrameRate') ?? (pool && pool.frameRate != null ? pool.frameRate : null),
    startTimecode: extractScalar(seqXml, 'StartTC') ?? poolStartTimecode(pool),
    startFrame: extractInt(seqXml, 'StartFrame') ?? poolStartFrame(pool),
    resolution: (() => {
      const w = extractInt(seqXml, 'ResolutionWidth');
      const h = extractInt(seqXml, 'ResolutionHeight');
      if (w === null || h === null) return pool && pool.width && pool.height ? `${pool.width}x${pool.height}` : null;
      return `${w}x${h}`;
    })(),
    videoTracks: extractTracks(seqXml, 'VideoTrackVec', 'Sm2TiVideoTrack', 'video').map((t) => ({
      ...t,
      // A media-less clip named after a compound in the pool IS that compound
      // placed on this track (E127) — tag it so consumers do not read it as a
      // missing source.
      clips: (t.clips || []).map((c) => (c.mediaFilePath == null && c.name && compoundNames.has(c.name) ? { ...c, compound: c.name } : c)),
    })),
    audioTracks: extractTracks(seqXml, 'AudioTrackVec', 'Sm2TiAudioTrack', 'audio'),
  };
  return parsed;
}

async function loadMetadata(zip) {
  const entry = zip.file('metadata.json');
  if (!entry) return null;
  try {
    return JSON.parse(await entry.async('string'));
  } catch {
    return null;
  }
}

/**
 * Parse a DRT archive.
 *
 * @param {string|Buffer} drtPathOrBuffer - filesystem path or in-memory buffer
 * @param {object} [options]
 * @returns {Promise<{timelines: Array, metadata: object|null, seqContainers: string[]}>}
 */
async function parseDRT(drtPathOrBuffer, options = {}) {
  void options;
  let buf;
  if (Buffer.isBuffer(drtPathOrBuffer)) {
    buf = drtPathOrBuffer;
  } else if (typeof drtPathOrBuffer === 'string') {
    buf = await fs.readFile(drtPathOrBuffer);
  } else {
    throw new TypeError('parseDRT: first arg must be a string path or a Buffer');
  }

  const zip = await JSZip.loadAsync(buf);
  const seqEntries = listSeqContainerEntries(zip);
  if (seqEntries.length === 0) {
    throw new Error('parseDRT: no SeqContainer*.xml entries found — is this a DRT/DRP?');
  }

  const poolNames = await loadPoolSequenceNames(zip);
  const timelines = [];
  for (const p of seqEntries) {
    const xml = await zip.file(p).async('string');
    timelines.push(parseSeqContainer(xml, p, poolNames));
  }

  const metadata = await loadMetadata(zip);

  return {
    timelines,
    metadata,
    seqContainers: seqEntries,
  };
}

module.exports = { parseDRT, listSeqContainerEntries, loadPoolSequenceNames };
