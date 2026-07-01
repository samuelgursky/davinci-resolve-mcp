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
    clips.push({
      clipId: m[3],
      start,
      duration,
      mediaFilePath,
      bodyHex,
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
    });
  }
  return tracks;
}

function parseSeqContainer(seqXml, sequenceName) {
  return {
    name: extractScalar(seqXml, 'Name') || sequenceName,
    sequence: sequenceName,
    frameRate: extractScalar(seqXml, 'FrameRate'),
    startTimecode: extractScalar(seqXml, 'StartTC'),
    startFrame: extractInt(seqXml, 'StartFrame'),
    resolution: (() => {
      const w = extractInt(seqXml, 'ResolutionWidth');
      const h = extractInt(seqXml, 'ResolutionHeight');
      if (w === null || h === null) return null;
      return `${w}x${h}`;
    })(),
    videoTracks: extractTracks(seqXml, 'VideoTrackVec', 'Sm2TiVideoTrack', 'video'),
    audioTracks: extractTracks(seqXml, 'AudioTrackVec', 'Sm2TiAudioTrack', 'audio'),
  };
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

  const timelines = [];
  for (const p of seqEntries) {
    const xml = await zip.file(p).async('string');
    timelines.push(parseSeqContainer(xml, p));
  }

  const metadata = await loadMetadata(zip);

  return {
    timelines,
    metadata,
    seqContainers: seqEntries,
  };
}

module.exports = { parseDRT, listSeqContainerEntries };
