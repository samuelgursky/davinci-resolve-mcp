/**
 * seq-surgery — shared primitives for editing a DaVinci Resolve timeline's
 * VideoTrackVec inside a real `.drp`/.drt SeqContainer, in place.
 *
 * A clip's track is encoded purely by which <Sm2TiTrack> it sits under, so all
 * track-targeting / move operations are string surgery on the SeqContainer XML.
 * Everything here is clone-based and identity-preserving: we never synthesize the
 * complex clip/track elements (Fusion comp blobs, media refs, grade bodies), we
 * relocate or clone real ones and only rewrite DbId / Start / Duration.
 *
 * Used by place-fusion-title.js (#74 title placement) and splice-clips.js
 * (general in-place clip moves). See
 * docs/design/drp-drx-drt-closeout-harness/knowledge/resolve21-schema-reconciliation.md
 *
 * @module drp-format/seq-surgery
 */

const fs = require('node:fs');
const JSZip = require('jszip');
const { generateUUID } = require('./xml-builder');

// SeqContainer entry, both conventions: SeqContainer/<uuid>.xml and <folder>/SeqContainer<N>.xml.
const SEQ_ENTRY_RE = /(^|\/)SeqContainer(\d*\.xml|\/[^/]+\.xml)$/;

function listSeqEntries(zip) {
  const out = [];
  zip.forEach((p, e) => {
    if (e.dir) return;
    if (SEQ_ENTRY_RE.test(p)) out.push(p);
  });
  return out.sort();
}

async function loadDrpZip(drpInput) {
  const buf = Buffer.isBuffer(drpInput) ? drpInput : await fs.promises.readFile(drpInput);
  return JSZip.loadAsync(buf);
}

/**
 * Pick the target SeqContainer entry + xml. By DbId if timelineUuid is given,
 * else the first entry that has a VideoTrackVec.
 * @returns {Promise<{entry:string, xml:string, seqId:string|null}>}
 */
async function selectTargetSeq(zip, timelineUuid) {
  const entries = listSeqEntries(zip);
  if (entries.length === 0) throw new Error('seq-surgery: no SeqContainer entries — not a .drp/.drt?');
  for (const e of entries) {
    const xml = await zip.file(e).async('string');
    const id = (xml.match(/<Sm2SequenceContainer DbId="([^"]+)"/) || [])[1] || null;
    if (timelineUuid) {
      if (id === timelineUuid) return { entry: e, xml, seqId: id };
    } else if (/<VideoTrackVec>/.test(xml)) {
      return { entry: e, xml, seqId: id };
    }
  }
  throw new Error(
    timelineUuid
      ? `seq-surgery: timeline ${timelineUuid} not found`
      : 'seq-surgery: no timeline with a VideoTrackVec found',
  );
}

// Top-level track <Element> blocks within a VideoTrackVec/AudioTrackVec body.
// Sm2TiTrack never nests another Sm2TiTrack, so a non-greedy match per track is safe.
function splitTrackElements(vecInner) {
  return vecInner.match(/<Element>\s*<Sm2TiTrack\b[\s\S]*?<\/Sm2TiTrack>\s*<\/Element>/g) || [];
}

// Clip <Element> blocks within a track's <Items>. A clip element never nests another
// clip element of the same tag, so non-greedy per clip is safe.
function splitClipElements(itemsInner) {
  return itemsInner.match(/<Element>\s*<Sm2Ti(?:Video|Audio)Clip\b[\s\S]*?<\/Sm2Ti(?:Video|Audio)Clip>\s*<\/Element>/g) || [];
}

function freshDbIds(xml) {
  return xml.replace(/DbId="[0-9a-fA-F-]+"/g, () => `DbId="${generateUUID()}"`);
}

function emptyTrackClone(trackElement) {
  return freshDbIds(trackElement).replace(/<Items>[\s\S]*?<\/Items>/, '<Items/>');
}

function getItemsInner(trackElement) {
  if (/<Items\s*\/>/.test(trackElement)) return '';
  const m = trackElement.match(/<Items>([\s\S]*?)<\/Items>/);
  return m ? m[1] : '';
}

function setItemsInner(trackElement, inner) {
  const body = inner && inner.trim() ? inner : null;
  if (/<Items\s*\/>/.test(trackElement)) {
    return body ? trackElement.replace(/<Items\s*\/>/, `<Items>${body}</Items>`) : trackElement;
  }
  return trackElement.replace(/<Items>[\s\S]*?<\/Items>/, body ? `<Items>${body}</Items>` : '<Items/>');
}

function insertClipIntoTrack(trackElement, clipElement) {
  const inner = getItemsInner(trackElement);
  return setItemsInner(trackElement, `${inner}${clipElement}`);
}

// Replace the VideoTrackVec body in a SeqContainer xml with a new ordered set of track elements.
function replaceVideoTrackVec(xml, trackElements) {
  const vtv = xml.match(/<VideoTrackVec>([\s\S]*?)<\/VideoTrackVec>/);
  if (!vtv) throw new Error('seq-surgery: target timeline has no VideoTrackVec');
  const body = `<VideoTrackVec>\n  ${trackElements.join('\n  ')}\n </VideoTrackVec>`;
  return xml.slice(0, vtv.index) + body + xml.slice(vtv.index + vtv[0].length);
}

function getVideoTracks(xml) {
  const vtv = xml.match(/<VideoTrackVec>([\s\S]*?)<\/VideoTrackVec>/);
  if (!vtv) throw new Error('seq-surgery: target timeline has no VideoTrackVec');
  return splitTrackElements(vtv[1]);
}

// Generic over track type. Audio tracks are also <Sm2TiTrack> (Type 1) inside <AudioTrackVec>.
const TRACK_VEC_TAG = { video: 'VideoTrackVec', audio: 'AudioTrackVec' };

function vecTagFor(trackType) {
  const tag = TRACK_VEC_TAG[trackType || 'video'];
  if (!tag) throw new Error(`seq-surgery: unknown trackType "${trackType}"`);
  return tag;
}

// Returns { match, inner, tracks } for the requested vec, or throws if absent.
function getTrackVec(xml, trackType) {
  const tag = vecTagFor(trackType);
  const m = xml.match(new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`));
  if (!m) throw new Error(`seq-surgery: target timeline has no ${tag}`);
  return { match: m, inner: m[1], tracks: splitTrackElements(m[1]) };
}

function replaceTrackVec(xml, trackType, vecMatch, trackElements) {
  const tag = vecTagFor(trackType);
  const body = `<${tag}>\n  ${trackElements.join('\n  ')}\n </${tag}>`;
  return xml.slice(0, vecMatch.index) + body + xml.slice(vecMatch.index + vecMatch[0].length);
}

module.exports = {
  SEQ_ENTRY_RE,
  listSeqEntries,
  loadDrpZip,
  selectTargetSeq,
  splitTrackElements,
  splitClipElements,
  freshDbIds,
  emptyTrackClone,
  getItemsInner,
  setItemsInner,
  insertClipIntoTrack,
  replaceVideoTrackVec,
  getVideoTracks,
  getTrackVec,
  replaceTrackVec,
};
