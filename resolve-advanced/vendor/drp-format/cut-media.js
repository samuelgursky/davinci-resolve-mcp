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
  emptyTrackClone,
} = require('./seq-surgery');
const { clipDbId, setClipStart, setClipDuration, setClipIn } = require('./splice-clips');

/**
 * @param {Buffer|string} drpInput
 * @param {object} opts
 * @param {Array<{startFrame:number, durationFrames:number, srcIn?:number, track?:number}>} opts.cuts
 *   Timeline placements. startFrame is timeline-absolute (origin 86400 on the
 *   bundled templates — clips before the origin are dropped by Resolve on
 *   import, silently). srcIn is the source in-point in TIMELINE frames.
 *   track is the 1-based VIDEO track (default 1); missing tracks are grown as
 *   empty clones. Cuts on track > 1 are placed VIDEO-ONLY — their audio would
 *   overlap the track-1 cuts' audio on A1 (the template has a single A1).
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
    if (cut.mediaRef !== undefined && !/^[0-9a-f-]{36}$/.test(cut.mediaRef)) {
      throw new TypeError(`cutSourceIntoClips: cuts[${i}].mediaRef must be a uuid`);
    }
    if (cut.track !== undefined && (!Number.isInteger(cut.track) || cut.track < 1)) {
      throw new TypeError(`cutSourceIntoClips: cuts[${i}].track must be a positive integer`);
    }
    if (cut.timemap !== undefined && !/^[0-9a-fA-F]+$/.test(cut.timemap)) {
      throw new TypeError(`cutSourceIntoClips: cuts[${i}].timemap must be a hex MediaTimemapBA blob`);
    }
  });

  const zip = await loadDrpZip(drpInput);
  const { entry, xml: seqXml } = await selectTargetSeq(zip, timelineUuid);
  let xml = seqXml;
  const clipDbIds = [];

  const cloneCut = (donor, cut) => {
    let c = freshDbIds(donor);
    c = setClipStart(c, cut.startFrame);
    c = setClipDuration(c, cut.durationFrames);
    c = setClipIn(c, cut.srcIn ?? 0);
    if (cut.mediaRef) {
      // Multi-source: point this cut at ITS source's transplanted pool
      // element instead of the donor's.
      c = c.replace(/<MediaRef>[0-9a-f-]{36}<\/MediaRef>/, `<MediaRef>${cut.mediaRef}</MediaRef>`);
    }
    if (cut.timemap) {
      // Constant-speed retime: swap the identity MediaTimemapBA for the
      // caller-built Sm2TimeMap (r19 keyed form render/readback-verified;
      // the clip's <In>/<Duration> are RECORD-domain, measured live).
      c = c.replace(/<MediaTimemapBA>[0-9a-fA-F]*<\/MediaTimemapBA>/, `<MediaTimemapBA>${cut.timemap}</MediaTimemapBA>`);
    }
    return c;
  };

  for (const trackType of ['video', 'audio']) {
    const { match, tracks } = getTrackVec(xml, trackType);
    if (!tracks.length) continue;
    const items = getItemsInner(tracks[0]);
    const clips = splitClipElements(items);
    if (!clips.length) continue; // audio-less media: nothing to cut on A1
    const donor = clips[0];
    if (trackType === 'audio') {
      // A1 mirrors track-1 video cuts only; higher video tracks stay video-only,
      // and so do RETIMED cuts (the audio clone would need its own timemap and
      // pitch handling — video-only is stated, not silent).
      const a1 = cuts.filter((cut) => (cut.track ?? 1) === 1 && !cut.timemap).map((cut) => cloneCut(donor, cut));
      tracks[0] = setItemsInner(tracks[0], a1.join(''));
      xml = replaceTrackVec(xml, trackType, match, tracks);
      continue;
    }
    const maxTrack = Math.max(1, ...cuts.map((cut) => cut.track ?? 1));
    const cloneSource = tracks[0];
    while (tracks.length < maxTrack) tracks.push(emptyTrackClone(cloneSource));
    for (let t = 1; t <= tracks.length; t += 1) {
      const mine = cuts.filter((cut) => (cut.track ?? 1) === t);
      if (t > 1 && !mine.length) continue; // grown-empty or untouched track keeps its items
      const clones = mine.map((cut) => cloneCut(donor, cut));
      for (const c of clones) clipDbIds.push(clipDbId(c));
      tracks[t - 1] = setItemsInner(tracks[t - 1], clones.join(''));
    }
    xml = replaceTrackVec(xml, trackType, match, tracks);
  }

  zip.file(entry, xml);
  const buffer = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
  return { buffer, cutCount: cuts.length, clipDbIds };
}

module.exports = { cutSourceIntoClips };
