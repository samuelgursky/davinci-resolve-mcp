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
 *   audioOnly:true makes a cut an AUDIO clip placement instead (track then
 *   indexes AUDIO tracks, grown as needed) — and the presence of ANY
 *   audioOnly cut suppresses the implicit A1 mirror of track-1 video cuts
 *   (explicit audio wins over the convenience mirror).
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

  const cloneCut = (donor, cut, kind) => {
    // Prefer the source's own CAPTURED clip of the matching kind — the A1
    // mirror clones AUDIO even for plain video cuts, so the donor must be
    // chosen per track type, never per cut flavor (a video element in an
    // audio track aborts the whole import, measured E31e).
    // NATIVE-DONOR PATH — RENDER-VERIFIED on 19.1.3.7 (E36): a TC-bearing
    // .mov source (embedded 01:00:00:00) renders picture AND audio through a
    // cloned native clip, and the full AAF route (two sources, V2 stacking,
    // merged audio legs) renders every window frame-accurately. Only caches
    // that carry videoClipElement/audioClipElement reach this; ordinary
    // captures keep the proven donor path. Donor clones from
    // splitClipElements come <Element>-wrapped and Items concatenation
    // depends on the wrapper.
    const native = kind === 'audio' ? cut.donorClipAudio : cut.donorClipVideo;
    let c = freshDbIds(native ? native.trim() : donor);
    c = setClipStart(c, cut.startFrame);
    c = setClipDuration(c, cut.durationFrames);
    c = setClipIn(c, cut.srcIn ?? 0);
    if (cut.mediaRef) {
      // Multi-source: point this cut at ITS source's transplanted pool
      // element instead of the donor's.
      c = c.replace(/<MediaRef>[0-9a-f-]{36}<\/MediaRef>/, `<MediaRef>${cut.mediaRef}</MediaRef>`);
    }
    if (cut.srcMeta && !native && cut.audioOnly) {
      // Every clone must carry ITS OWN source identity — a donor clone
      // keeping stale Name/MediaFilePath/MediaFrameRate (the template
      // donor's was 29.97!) or the donor's identity-timemap extent imports
      // and reads back fine but fails at render: audio renders SILENT off
      // A1 (measured, E15), and a TC-bearing video source fails the whole
      // render with "Full resolution media not found" (measured, E31).
      const { name, mediaFilePath, fps, frameCount } = cut.srcMeta;
      c = c.replace(/<Name>[\s\S]*?<\/Name>/, `<Name>${name}</Name>`);
      c = c.replace(/<MediaFilePath>[\s\S]*?<\/MediaFilePath>/, `<MediaFilePath>${mediaFilePath}</MediaFilePath>`);
      const rate = Buffer.alloc(16);
      rate.writeDoubleLE(fps, 0);
      c = c.replace(/<MediaFrameRate>[0-9a-fA-F]*<\/MediaFrameRate>/, `<MediaFrameRate>${rate.toString('hex')}</MediaFrameRate>`);
      const idm = Buffer.alloc(9);
      idm.writeUInt8(0x02, 0);
      idm.writeDoubleBE((frameCount - 1) / fps, 1);
      c = c.replace(/<MediaTimemapBA>[0-9a-fA-F]*<\/MediaTimemapBA>/, `<MediaTimemapBA>${idm.toString('hex')}</MediaTimemapBA>`);
      if (cut.audioOnly) {
        // Generic audio-clip FieldsBlob, verbatim from the live A2 harvest.
        // (Video clones keep their blob — repointClipBlobsInXml owns it.)
        c = c.replace(/<FieldsBlob>[0-9a-fA-F]*<\/FieldsBlob>/, '<FieldsBlob>0000000200000005800a022001</FieldsBlob>');
      }
    }
    if (cut.mediaStartTime !== undefined && cut.mediaStartTime !== null && !native) {
      // Embedded source timecode base, in SECONDS (harvested with the media
      // template). Donor default 0 makes Resolve seek the wrong TC and fail
      // the render with "Full resolution media not found at <TC>".
      c = c.replace(/<MediaStartTime>[\s\S]*?<\/MediaStartTime>/, `<MediaStartTime>${cut.mediaStartTime}</MediaStartTime>`);
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
      const audioCuts = cuts.filter((cut) => cut.audioOnly);
      if (audioCuts.length) {
        // Explicit audio placements: grow audio tracks and place per track;
        // the implicit A1 mirror is suppressed (explicit audio wins).
        const maxA = Math.max(1, ...audioCuts.map((cut) => cut.track ?? 1));
        if (maxA > tracks.length) {
          // Audio tracks CANNOT be grown by cloning: the per-timeline
          // Fairlight model (FLStudioModelBA inside the pool's
          // Sm2Sequence.FieldsBlob) holds one strip per track, and a cloned
          // track without a strip imports fine, reads back fine, and renders
          // SILENT (measured). The r19 media template is captured with 8
          // audio tracks (valid strips included); beyond that, refuse.
          throw new Error(
            `cutSourceIntoClips: audio track ${maxA} exceeds the template's ${tracks.length} ` +
            'audio tracks — audio tracks cannot be grown offline (no Fairlight strip = silent). ' +
            'Re-capture a template with more audio tracks to raise the ceiling.');
        }
        for (let t = 1; t <= tracks.length; t += 1) {
          const mine = audioCuts.filter((cut) => (cut.track ?? 1) === t);
          if (t > 1 && !mine.length) continue;
          tracks[t - 1] = setItemsInner(tracks[t - 1], mine.map((cut) => cloneCut(donor, cut, 'audio')).join(''));
        }
      } else {
        // A1 mirrors track-1 video cuts only; higher video tracks stay
        // video-only, and so do RETIMED cuts (the audio clone would need its
        // own timemap and pitch handling — video-only is stated, not silent).
        const a1 = cuts.filter((cut) => (cut.track ?? 1) === 1 && !cut.timemap).map((cut) => cloneCut(donor, cut, 'audio'));
        tracks[0] = setItemsInner(tracks[0], a1.join(''));
      }
      xml = replaceTrackVec(xml, trackType, match, tracks);
      continue;
    }
    const vCuts = cuts.filter((cut) => !cut.audioOnly);
    const maxTrack = Math.max(1, ...vCuts.map((cut) => cut.track ?? 1));
    const cloneSource = tracks[0];
    while (tracks.length < maxTrack) tracks.push(emptyTrackClone(cloneSource));
    for (let t = 1; t <= tracks.length; t += 1) {
      const mine = vCuts.filter((cut) => (cut.track ?? 1) === t);
      if (t > 1 && !mine.length) continue; // grown-empty or untouched track keeps its items
      const clones = mine.map((cut) => cloneCut(donor, cut, 'video'));
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
