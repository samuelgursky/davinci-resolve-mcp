/**
 * place-fusion-title — drop a Fusion Title (Text+) onto a CHOSEN video track of a
 * timeline inside a real DaVinci Resolve .drp, bypassing the Source Track Selector
 * limitation (davinci-resolve-mcp issue #74).
 *
 * The scripting API's InsertFusionTitleIntoTimeline takes no track argument — the
 * clip lands on whatever the Source Track Selector points at, and that selector is
 * not reachable from the API. The .drp file, however, encodes a clip's track purely
 * by which <Sm2TiTrack> element it sits under, so we place it directly.
 *
 * Strategy: CLONE, never synthesize. In Resolve 21 a Text+ is an <Sm2TiVideoClip>
 * with <PrettyType>Fusion Title</PrettyType> and a <CompositionTable>/<CompositionBA>
 * Fusion-comp blob — too complex to author from scratch. So we carry a real title
 * clip (bundled template, or one cloned from the target itself) verbatim, only
 * rewriting its DbId / Start / Duration / Name. Empty destination tracks are likewise
 * cloned from an existing track (preserving the shared <Sequence> uuid) with their
 * <Items> emptied — the exact surgery proven to round-trip through Resolve 21.
 *
 * See docs/design/drp-drx-drt-closeout-harness/knowledge/resolve21-schema-reconciliation.md
 *
 * @module drp-format/place-fusion-title
 */

const fs = require('node:fs');
const path = require('node:path');
// Source modules directly (not ./index) to avoid a circular require — index.js re-exports us.
const { escapeXml } = require('./xml-builder');
const { setTitleInputs } = require('./composition-text');
const {
  loadDrpZip,
  selectTargetSeq,
  splitTrackElements,
  emptyTrackClone,
  insertClipIntoTrack,
  replaceVideoTrackVec,
  freshDbIds,
} = require('./seq-surgery');

const TEMPLATE_PATH = path.join(__dirname, 'templates', 'fusion-title.xml');

/**
 * Place a Fusion Title clip onto a chosen video track of a timeline in a .drp.
 *
 * @param {Buffer|string} drpInput - .drp buffer or filesystem path.
 * @param {object} opts
 * @param {number} [opts.trackIndex=2]      - 1-based video track to place the title on. Missing
 *                                            tracks up to this index are created (empty).
 * @param {number} opts.startFrame          - timeline start frame for the clip (required).
 * @param {number} [opts.durationFrames=120]- clip duration in frames.
 * @param {string} [opts.name]              - clip Name (timeline label); independent of on-screen text.
 * @param {string} [opts.text]              - the ON-SCREEN title text (rewrites the Fusion
 *                                            comp's StyledText). No double-quotes. Omit to keep
 *                                            the template's text.
 * @param {string} [opts.timelineUuid]      - target SeqContainer DbId; default = first timeline
 *                                            that has a VideoTrackVec.
 * @param {string} [opts.titleClipXml]      - override template clip <Element> XML; default bundled.
 * @returns {Promise<{buffer: Buffer, entry: string, timelineUuid: string, trackIndex: number,
 *                     videoTrackCount: number, createdTracks: number}>}
 */
async function placeFusionTitle(drpInput, opts = {}) {
  const {
    trackIndex = 2,
    startFrame,
    durationFrames = 120,
    name,
    text,
    font,
    style,
    size,
    vJustify,
    hJustify,
    color,
    timelineUuid,
    titleClipXml,
  } = opts;

  if (!Number.isInteger(startFrame)) throw new TypeError('placeFusionTitle: startFrame (int) is required');
  if (!Number.isInteger(trackIndex) || trackIndex < 1) throw new TypeError('placeFusionTitle: trackIndex must be a positive integer');

  const zip = await loadDrpZip(drpInput);
  const { entry, xml: seqXml, seqId } = await selectTargetSeq(zip, timelineUuid);
  let xml = seqXml;

  // Prepare the title clip (clone + rewrite identity/timing).
  let clip = titleClipXml || fs.readFileSync(TEMPLATE_PATH, 'utf8');
  clip = clip.trim();
  if (!/PrettyType>\s*Fusion Title/.test(clip)) {
    throw new Error('placeFusionTitle: template is not a Fusion Title clip');
  }
  clip = freshDbIds(clip);
  clip = clip.replace(/<Start>\d+<\/Start>/, `<Start>${startFrame}</Start>`);
  clip = clip.replace(/<Duration>\d+<\/Duration>/, `<Duration>${durationFrames}</Duration>`);
  if (name) clip = clip.replace(/<Name>[\s\S]*?<\/Name>/, `<Name>${escapeXml(name)}</Name>`);
  const titleInputs = { text, font, style, size, vJustify, hJustify, color };
  if (Object.values(titleInputs).some((v) => v !== undefined && v !== null)) {
    const m = clip.match(/<CompositionBA>([0-9a-fA-F]*)<\/CompositionBA>/);
    if (!m || !m[1]) throw new Error('placeFusionTitle: template has no CompositionBA to style');
    clip = clip.replace(m[0], `<CompositionBA>${setTitleInputs(m[1], titleInputs)}</CompositionBA>`);
  }

  // Locate VideoTrackVec and split into track elements.
  const vtvInner = xml.match(/<VideoTrackVec>([\s\S]*?)<\/VideoTrackVec>/);
  const tracks = vtvInner ? splitTrackElements(vtvInner[1]) : [];
  if (tracks.length === 0) throw new Error('placeFusionTitle: no existing video track to clone from');

  // Grow to trackIndex with empty clones.
  let createdTracks = 0;
  const cloneSource = tracks[0];
  while (tracks.length < trackIndex) {
    tracks.push(emptyTrackClone(cloneSource));
    createdTracks += 1;
  }

  // Insert the clip onto the destination track.
  tracks[trackIndex - 1] = insertClipIntoTrack(tracks[trackIndex - 1], clip);

  xml = replaceVideoTrackVec(xml, tracks);
  zip.file(entry, xml);
  const outBuf = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });

  return {
    buffer: outBuf,
    entry,
    timelineUuid: seqId,
    trackIndex,
    videoTrackCount: tracks.length,
    createdTracks,
  };
}

module.exports = { placeFusionTitle, TEMPLATE_PATH };
