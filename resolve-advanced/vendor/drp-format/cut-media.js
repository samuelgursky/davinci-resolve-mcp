/**
 * cut-media — replace a timeline's single source clip with N cuts of it.
 *
 * The composable half of media authoring: addMediaClip yields a project whose
 * timeline holds ONE clip of the (repointed) source on V1/A1; this clones that
 * donor clip into a cut list — fresh DbIds, per-cut Start / Duration / source
 * In — on both the video and audio tracks, so a real editorial cut of one
 * source becomes an importable timeline. Source-IN semantics per splice-clips:
 * <In> framePos is in TIMELINE frames (verified live), encoded as
 * `frames|LE-double(frames*0.001)`.
 *
 * Single-source by design (the template media pool holds one media entry);
 * multi-source needs media-pool entry synthesis and is refused honestly.
 *
 * @module drp-format/cut-media
 */

const {
  loadDrpZip,
  selectTargetSeq,
  splitClipElements,
  getItemsInner,
  setItemsInner,
  freshDbIds,
  getTrackVec,
  replaceTrackVec,
} = require('./seq-surgery');
const { clipDbId, setClipStart, setClipDuration, setClipIn } = require('./splice-clips');

/**
 * @param {Buffer|string} drpInput
 * @param {object} opts
 * @param {Array<{startFrame:number, durationFrames:number, srcIn?:number}>} opts.cuts
 *   Timeline placements. startFrame is timeline-absolute (origin 86400 on the
 *   bundled templates — clips before the origin are dropped by Resolve on
 *   import, silently). srcIn is the source in-point in TIMELINE frames.
 * @param {string} [opts.timelineUuid]
 * @returns {Promise<{buffer: Buffer, cutCount: number, clipDbIds: string[]}>}
 */
async function cutSourceIntoClips(drpInput, opts = {}) {
  const { cuts, timelineUuid } = opts;
  if (!Array.isArray(cuts) || cuts.length === 0) {
    throw new TypeError('cutSourceIntoClips: cuts must be a non-empty array');
  }
  cuts.forEach((cut, i) => {
    if (!cut || !Number.isInteger(cut.startFrame) || !Number.isInteger(cut.durationFrames) || cut.durationFrames <= 0) {
      throw new TypeError(`cutSourceIntoClips: cuts[${i}] needs integer startFrame and positive integer durationFrames`);
    }
    if (cut.srcIn !== undefined && (!Number.isInteger(cut.srcIn) || cut.srcIn < 0)) {
      throw new TypeError(`cutSourceIntoClips: cuts[${i}].srcIn must be a non-negative integer`);
    }
  });

  const zip = await loadDrpZip(drpInput);
  const { entry, xml: seqXml } = await selectTargetSeq(zip, timelineUuid);
  let xml = seqXml;
  const clipDbIds = [];

  for (const trackType of ['video', 'audio']) {
    const { match, tracks } = getTrackVec(xml, trackType);
    if (!tracks.length) continue;
    const items = getItemsInner(tracks[0]);
    const clips = splitClipElements(items);
    if (!clips.length) continue; // audio-less media: nothing to cut on A1
    const donor = clips[0];
    const clones = cuts.map((cut) => {
      let c = freshDbIds(donor);
      c = setClipStart(c, cut.startFrame);
      c = setClipDuration(c, cut.durationFrames);
      c = setClipIn(c, cut.srcIn ?? 0);
      return c;
    });
    if (trackType === 'video') {
      for (const c of clones) clipDbIds.push(clipDbId(c));
    }
    tracks[0] = setItemsInner(tracks[0], clones.join(''));
    xml = replaceTrackVec(xml, trackType, match, tracks);
  }

  zip.file(entry, xml);
  const buffer = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
  return { buffer, cutCount: cuts.length, clipDbIds };
}

module.exports = { cutSourceIntoClips };
