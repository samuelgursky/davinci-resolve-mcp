/**
 * splice-clips — in-place clip edits on a real Resolve `.drp` timeline.
 *
 * Generalizes the #74 track-targeting surgery to ANY clip type (media, title,
 * generator): a clip's track is just which <Sm2TiTrack> it sits under, so moving
 * a clip between tracks — or shifting its start — is identity-preserving string
 * surgery on the SeqContainer XML. The relocated clip keeps its DbId, MediaRef,
 * grade body, and any Fusion comp verbatim; only its track membership and (optionally)
 * Start change. No scripting API can move a clip to an arbitrary track this way.
 *
 * @module drp-format/splice-clips
 */

const {
  loadDrpZip,
  selectTargetSeq,
  splitClipElements,
  emptyTrackClone,
  getItemsInner,
  setItemsInner,
  insertClipIntoTrack,
  freshDbIds,
  getTrackVec,
  replaceTrackVec,
} = require('./seq-surgery');

function clipDbId(clipXml) {
  return (clipXml.match(/<Sm2Ti(?:Video|Audio)Clip DbId="([^"]+)"/) || [])[1] || null;
}

function clipStart(clipXml) {
  const m = clipXml.match(/<Start>(\d+)<\/Start>/);
  return m ? parseInt(m[1], 10) : null;
}
function clipDuration(clipXml) {
  const m = clipXml.match(/<Duration>(\d+)<\/Duration>/);
  return m ? parseInt(m[1], 10) : null;
}
function setClipStart(clipXml, v) {
  return clipXml.replace(/<Start>\d+<\/Start>/, `<Start>${v}</Start>`);
}
function setClipDuration(clipXml, v) {
  return clipXml.replace(/<Duration>\d+<\/Duration>/, `<Duration>${v}</Duration>`);
}
// The source IN-point lives in <In> as `<framePos>|<LE-double of framePos*0.001>`, where framePos
// is in TIMELINE frames (verified live: Resolve appended a clip with source-in 600 media-frames @29.97
// and wrote In framePos 480 = the same point in 24fps timeline frames; MediaStartTime stayed 0). So
// in-point edits go through <In>, not MediaStartTime (which is not the source in-point).
function encodeSourceIn(frame) {
  const buf = Buffer.alloc(8);
  buf.writeDoubleLE(frame * 0.001, 0);
  return `${frame}|${buf.toString('hex')}`;
}
function clipIn(clipXml) {
  const m = clipXml.match(/<In>(\d+)\|/);
  return m ? parseInt(m[1], 10) : 0; // empty <In/> ⇒ in-point 0
}
function setClipIn(clipXml, framePos) {
  const enc = `<In>${encodeSourceIn(framePos)}</In>`;
  if (/<In\s*\/>/.test(clipXml)) return clipXml.replace(/<In\s*\/>/, enc);
  if (/<In>[^<]*<\/In>/.test(clipXml)) return clipXml.replace(/<In>[^<]*<\/In>/, enc);
  return clipXml; // no In element to set
}

// Rewrite each clip on a track via fn(clipXml) -> clipXml. Clips have unique DbIds so a
// first-occurrence replace per clip is unambiguous.
function mapClipsOnTrack(trackElement, fn) {
  const inner = getItemsInner(trackElement);
  let out = inner;
  for (const c of splitClipElements(inner)) {
    const nc = fn(c);
    if (nc !== c) out = out.replace(c, nc);
  }
  return setItemsInner(trackElement, out);
}

function pickClip(clips, { clipDbId: wantId, nameContains, clipIndex = 0 }) {
  if (wantId) {
    const i = clips.findIndex((c) => clipDbId(c) === wantId);
    if (i < 0) throw new Error(`splice: no clip with DbId ${wantId} on source track`);
    return i;
  }
  if (nameContains) {
    const i = clips.findIndex((c) => {
      const m = c.match(/<Name>([\s\S]*?)<\/Name>/);
      return m && m[1].includes(nameContains);
    });
    if (i < 0) throw new Error(`splice: no clip whose Name contains "${nameContains}" on source track`);
    return i;
  }
  if (clipIndex < 0 || clipIndex >= clips.length) {
    throw new Error(`splice: clipIndex ${clipIndex} out of range (source track has ${clips.length} clip(s))`);
  }
  return clipIndex;
}

/**
 * Move an existing video clip to a different track (and/or a new start), in place.
 *
 * @param {Buffer|string} drpInput
 * @param {object} opts
 * @param {number} opts.fromTrack        - 1-based video track the clip currently lives on.
 * @param {number} opts.toTrack          - 1-based destination video track (created empty if missing).
 * @param {number} [opts.clipIndex=0]    - which clip on fromTrack (0-based), if no id/name selector.
 * @param {string} [opts.clipDbId]       - select the clip by DbId.
 * @param {string} [opts.nameContains]   - select the clip by Name substring.
 * @param {number} [opts.toStart]        - new timeline Start frame (omit to keep current).
 * @param {string} [opts.timelineUuid]   - target SeqContainer DbId; default = first with a VideoTrackVec.
 * @returns {Promise<{buffer:Buffer, entry:string, timelineUuid:string, fromTrack:number, toTrack:number,
 *                     movedClipDbId:string|null, videoTrackCount:number, createdTracks:number}>}
 */
async function moveClip(drpInput, opts = {}) {
  const { fromTrack, toTrack, clipIndex = 0, clipDbId: selId, nameContains, toStart, timelineUuid, trackType = 'video' } = opts;
  if (!Number.isInteger(fromTrack) || fromTrack < 1) throw new TypeError('moveClip: fromTrack must be a positive integer');
  if (!Number.isInteger(toTrack) || toTrack < 1) throw new TypeError('moveClip: toTrack must be a positive integer');

  const zip = await loadDrpZip(drpInput);
  const { entry, xml: seqXml, seqId } = await selectTargetSeq(zip, timelineUuid);

  const { match: vtv, tracks } = getTrackVec(seqXml, trackType);
  if (fromTrack > tracks.length) throw new Error(`moveClip: fromTrack ${fromTrack} does not exist (timeline has ${tracks.length} video track(s))`);

  // Pull the clip off the source track.
  const srcItems = getItemsInner(tracks[fromTrack - 1]);
  const srcClips = splitClipElements(srcItems);
  if (srcClips.length === 0) throw new Error(`moveClip: source track ${fromTrack} has no clips`);
  const idx = pickClip(srcClips, { clipDbId: selId, nameContains, clipIndex });
  let clip = srcClips[idx];
  const movedClipDbId = clipDbId(clip);

  // Remove it from the source track (preserve the other clips' surrounding text).
  const remaining = srcItems.replace(clip, '');
  tracks[fromTrack - 1] = setItemsInner(tracks[fromTrack - 1], remaining);

  // Optionally retime.
  if (toStart !== undefined && toStart !== null) {
    if (!Number.isInteger(toStart)) throw new TypeError('moveClip: toStart must be an integer');
    clip = clip.replace(/<Start>\d+<\/Start>/, `<Start>${toStart}</Start>`);
  }

  // Grow to the destination track with empty clones, then insert.
  let createdTracks = 0;
  const cloneSource = tracks[0];
  while (tracks.length < toTrack) {
    tracks.push(emptyTrackClone(cloneSource));
    createdTracks += 1;
  }
  tracks[toTrack - 1] = insertClipIntoTrack(tracks[toTrack - 1], clip);

  const xml = replaceTrackVec(seqXml, trackType, vtv, tracks);
  zip.file(entry, xml);
  const buffer = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });

  return {
    buffer,
    entry,
    timelineUuid: seqId,
    fromTrack,
    toTrack,
    movedClipDbId,
    videoTrackCount: tracks.length,
    createdTracks,
  };
}

/**
 * Delete a clip from a video track, optionally rippling (closing the gap) the rest of THAT track.
 *
 * @param {Buffer|string} drpInput
 * @param {object} opts
 * @param {number} opts.fromTrack       - 1-based video track holding the clip.
 * @param {number} [opts.clipIndex=0]   - which clip (0-based) if no id/name selector.
 * @param {string} [opts.clipDbId]      - select by DbId.
 * @param {string} [opts.nameContains]  - select by Name substring.
 * @param {boolean} [opts.ripple=false] - shift later clips on the same track earlier by the
 *                                        deleted clip's duration (track-scoped ripple).
 * @param {string} [opts.timelineUuid]
 * @returns {Promise<{buffer:Buffer, entry:string, timelineUuid:string, track:number,
 *                     deletedClipDbId:string|null, rippled:boolean, remainingClips:number}>}
 */
async function deleteClip(drpInput, opts = {}) {
  const { fromTrack, clipIndex = 0, clipDbId: selId, nameContains, ripple = false, timelineUuid, trackType = 'video' } = opts;
  if (!Number.isInteger(fromTrack) || fromTrack < 1) throw new TypeError('deleteClip: fromTrack must be a positive integer');

  const zip = await loadDrpZip(drpInput);
  const { entry, xml: seqXml, seqId } = await selectTargetSeq(zip, timelineUuid);
  const { match: vtv, tracks } = getTrackVec(seqXml, trackType);
  if (fromTrack > tracks.length) throw new Error(`deleteClip: fromTrack ${fromTrack} does not exist (timeline has ${tracks.length} video track(s))`);

  const items = getItemsInner(tracks[fromTrack - 1]);
  const clips = splitClipElements(items);
  if (clips.length === 0) throw new Error(`deleteClip: track ${fromTrack} has no clips`);
  const idx = pickClip(clips, { clipDbId: selId, nameContains, clipIndex });
  const target = clips[idx];
  const tStart = clipStart(target);
  const tDur = clipDuration(target);
  const deletedClipDbId = clipDbId(target);

  let track = setItemsInner(tracks[fromTrack - 1], items.replace(target, ''));
  if (ripple && tStart !== null && tDur !== null) {
    track = mapClipsOnTrack(track, (c) => {
      const s = clipStart(c);
      return s !== null && s > tStart ? setClipStart(c, s - tDur) : c;
    });
  }
  tracks[fromTrack - 1] = track;

  const xml = replaceTrackVec(seqXml, trackType, vtv, tracks);
  zip.file(entry, xml);
  const buffer = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
  return {
    buffer,
    entry,
    timelineUuid: seqId,
    track: fromTrack,
    deletedClipDbId,
    rippled: Boolean(ripple),
    remainingClips: clips.length - 1,
  };
}

/**
 * Trim a clip's Duration (tail trim), optionally rippling later clips on THAT track.
 * Note: tail trim only (changes <Duration>); head/in-point trims aren't handled here.
 *
 * @param {Buffer|string} drpInput
 * @param {object} opts
 * @param {number} opts.track            - 1-based video track holding the clip.
 * @param {number} opts.newDuration      - new clip duration in frames (>0).
 * @param {number} [opts.clipIndex=0]    - which clip (0-based) if no id/name selector.
 * @param {string} [opts.clipDbId]
 * @param {string} [opts.nameContains]
 * @param {boolean} [opts.ripple=false]  - shift clips after this one by (newDuration - oldDuration).
 * @param {string} [opts.timelineUuid]
 * @returns {Promise<{buffer:Buffer, entry:string, timelineUuid:string, track:number,
 *                     trimmedClipDbId:string|null, oldDuration:number, newDuration:number,
 *                     rippled:boolean}>}
 */
async function trimClip(drpInput, opts = {}) {
  const { track: trackIdx, newDuration, clipIndex = 0, clipDbId: selId, nameContains, ripple = false, timelineUuid, trackType = 'video' } = opts;
  if (!Number.isInteger(trackIdx) || trackIdx < 1) throw new TypeError('trimClip: track must be a positive integer');
  if (!Number.isInteger(newDuration) || newDuration < 1) throw new TypeError('trimClip: newDuration must be a positive integer');

  const zip = await loadDrpZip(drpInput);
  const { entry, xml: seqXml, seqId } = await selectTargetSeq(zip, timelineUuid);
  const { match: vtv, tracks } = getTrackVec(seqXml, trackType);
  if (trackIdx > tracks.length) throw new Error(`trimClip: track ${trackIdx} does not exist (timeline has ${tracks.length} video track(s))`);

  const items = getItemsInner(tracks[trackIdx - 1]);
  const clips = splitClipElements(items);
  if (clips.length === 0) throw new Error(`trimClip: track ${trackIdx} has no clips`);
  const idx = pickClip(clips, { clipDbId: selId, nameContains, clipIndex });
  const target = clips[idx];
  const oldDuration = clipDuration(target);
  const tStart = clipStart(target);
  const trimmedClipDbId = clipDbId(target);

  let track = setItemsInner(tracks[trackIdx - 1], items.replace(target, setClipDuration(target, newDuration)));
  if (ripple && oldDuration !== null && tStart !== null) {
    const delta = newDuration - oldDuration;
    const tEnd = tStart + oldDuration;
    track = mapClipsOnTrack(track, (c) => {
      const s = clipStart(c);
      return s !== null && s >= tEnd ? setClipStart(c, s + delta) : c;
    });
  }
  tracks[trackIdx - 1] = track;

  const xml = replaceTrackVec(seqXml, trackType, vtv, tracks);
  zip.file(entry, xml);
  const buffer = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
  return {
    buffer,
    entry,
    timelineUuid: seqId,
    track: trackIdx,
    trimmedClipDbId,
    oldDuration,
    newDuration,
    rippled: Boolean(ripple),
  };
}

/**
 * Head-trim a clip: move its source in-point later by `frames` (the left edge in).
 * MediaStartTime += frames, Duration -= frames. Non-ripple keeps the OUT point fixed
 * (Start += frames, a gap opens before the clip). Ripple keeps Start and shifts later
 * clips on the track left by `frames` (closes the gap).
 *
 * @param {Buffer|string} drpInput
 * @param {object} opts
 * @param {number} opts.track          - 1-based video track.
 * @param {number} opts.frames         - frames to trim off the head (>0, < clip duration).
 * @param {number} [opts.clipIndex=0]
 * @param {string} [opts.clipDbId]
 * @param {string} [opts.nameContains]
 * @param {boolean} [opts.ripple=false]
 * @param {string} [opts.timelineUuid]
 * @returns {Promise<{buffer:Buffer, entry:string, timelineUuid:string, track:number,
 *   clipDbId:string|null, framesTrimmed:number, newMediaStart:number, newStart:number, newDuration:number, rippled:boolean}>}
 */
async function trimClipHead(drpInput, opts = {}) {
  const { track: trackIdx, frames, clipIndex = 0, clipDbId: selId, nameContains, ripple = false, timelineUuid, trackType = 'video' } = opts;
  if (!Number.isInteger(trackIdx) || trackIdx < 1) throw new TypeError('trimClipHead: track must be a positive integer');
  if (!Number.isInteger(frames) || frames < 1) throw new TypeError('trimClipHead: frames must be a positive integer');

  const zip = await loadDrpZip(drpInput);
  const { entry, xml: seqXml, seqId } = await selectTargetSeq(zip, timelineUuid);
  const { match: vtv, tracks } = getTrackVec(seqXml, trackType);
  if (trackIdx > tracks.length) throw new Error(`trimClipHead: track ${trackIdx} does not exist (timeline has ${tracks.length})`);

  const items = getItemsInner(tracks[trackIdx - 1]);
  const clips = splitClipElements(items);
  if (clips.length === 0) throw new Error(`trimClipHead: track ${trackIdx} has no clips`);
  const idx = pickClip(clips, { clipDbId: selId, nameContains, clipIndex });
  const target = clips[idx];
  const oldStart = clipStart(target);
  const oldDur = clipDuration(target);
  const oldIn = clipIn(target);
  if (frames >= oldDur) throw new Error(`trimClipHead: frames ${frames} >= clip duration ${oldDur}`);

  const newIn = oldIn + frames; // advance the source in-point (timeline frames)
  const newDur = oldDur - frames;
  const newStart = ripple ? oldStart : oldStart + frames;

  let edited = setClipIn(target, newIn);
  edited = setClipDuration(edited, newDur);
  edited = setClipStart(edited, newStart);

  let track = setItemsInner(tracks[trackIdx - 1], items.replace(target, edited));
  if (ripple) {
    track = mapClipsOnTrack(track, (c) => {
      const s = clipStart(c);
      return s !== null && s > oldStart ? setClipStart(c, s - frames) : c;
    });
  }
  tracks[trackIdx - 1] = track;

  const xml = replaceTrackVec(seqXml, trackType, vtv, tracks);
  zip.file(entry, xml);
  const buffer = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
  return {
    buffer, entry, timelineUuid: seqId, track: trackIdx, clipDbId: clipDbId(target),
    framesTrimmed: frames, newIn, newStart, newDuration: newDur, rippled: Boolean(ripple),
  };
}

/**
 * Split (razor) the clip that spans timeline frame `at` into two abutting clips.
 * Left keeps Start + in-point, shortened to `at`. Right is a fresh-DbId clone starting at
 * `at` with its in-point advanced by (at - start), filling the remainder. No gap, no ripple.
 *
 * @param {Buffer|string} drpInput
 * @param {object} opts
 * @param {number} opts.track          - 1-based video track.
 * @param {number} opts.at             - timeline frame to cut at (must be strictly inside a clip).
 * @param {string} [opts.timelineUuid]
 * @returns {Promise<{buffer:Buffer, entry:string, timelineUuid:string, track:number,
 *   leftDbId:string|null, rightDbId:string|null, at:number, leftDuration:number, rightDuration:number}>}
 */
async function splitClip(drpInput, opts = {}) {
  const { track: trackIdx, at, timelineUuid, trackType = 'video' } = opts;
  if (!Number.isInteger(trackIdx) || trackIdx < 1) throw new TypeError('splitClip: track must be a positive integer');
  if (!Number.isInteger(at)) throw new TypeError('splitClip: at (frame) must be an integer');

  const zip = await loadDrpZip(drpInput);
  const { entry, xml: seqXml, seqId } = await selectTargetSeq(zip, timelineUuid);
  const { match: vtv, tracks } = getTrackVec(seqXml, trackType);
  if (trackIdx > tracks.length) throw new Error(`splitClip: track ${trackIdx} does not exist (timeline has ${tracks.length})`);

  const items = getItemsInner(tracks[trackIdx - 1]);
  const clips = splitClipElements(items);
  const idx = clips.findIndex((c) => {
    const s = clipStart(c);
    const d = clipDuration(c);
    return s !== null && d !== null && at > s && at < s + d;
  });
  if (idx < 0) throw new Error(`splitClip: no clip on track ${trackIdx} spans frame ${at}`);

  const target = clips[idx];
  const start = clipStart(target);
  const dur = clipDuration(target);
  const leftIn = clipIn(target);

  const leftDur = at - start;
  const rightDur = start + dur - at;

  const left = setClipDuration(target, leftDur); // In unchanged
  let right = freshDbIds(target);
  right = setClipStart(right, at);
  right = setClipDuration(right, rightDur);
  right = setClipIn(right, leftIn + leftDur); // source continues where left ended

  const track = setItemsInner(tracks[trackIdx - 1], items.replace(target, `${left}${right}`));
  tracks[trackIdx - 1] = track;

  const xml = replaceTrackVec(seqXml, trackType, vtv, tracks);
  zip.file(entry, xml);
  const buffer = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
  return {
    buffer, entry, timelineUuid: seqId, track: trackIdx,
    leftDbId: clipDbId(left), rightDbId: clipDbId(right), at, leftDuration: leftDur, rightDuration: rightDur,
  };
}

/**
 * Cross-track ripple: shift EVERY clip whose Start >= `at` by `delta`, on BOTH the video
 * and audio vecs — so linked video + audio move together and stay in sync. Use to close or
 * open a gap across the whole timeline (true ripple), vs. the track-scoped ripple in
 * delete/trim which only touches one track.
 *
 * @param {Buffer|string} drpInput
 * @param {object} opts
 * @param {number} opts.at            - timeline frame; clips starting at/after this shift.
 * @param {number} opts.delta         - frames to shift by (negative closes a gap).
 * @param {string} [opts.timelineUuid]
 * @returns {Promise<{buffer:Buffer, entry:string, timelineUuid:string, at:number, delta:number, shifted:number}>}
 */
async function rippleTimeline(drpInput, opts = {}) {
  const { at, delta, timelineUuid } = opts;
  if (!Number.isInteger(at)) throw new TypeError('rippleTimeline: at must be an integer');
  if (!Number.isInteger(delta)) throw new TypeError('rippleTimeline: delta must be an integer');

  const zip = await loadDrpZip(drpInput);
  const { entry, xml: seqXml, seqId } = await selectTargetSeq(zip, timelineUuid);

  let xml = seqXml;
  let shifted = 0;
  for (const trackType of ['video', 'audio']) {
    let vec;
    try { vec = getTrackVec(xml, trackType); } catch { continue; } // vec may be absent
    const tracks = vec.tracks.map((track) => mapClipsOnTrack(track, (c) => {
      const s = clipStart(c);
      if (s !== null && s >= at) { shifted += 1; return setClipStart(c, s + delta); }
      return c;
    }));
    if (tracks.length) xml = replaceTrackVec(xml, trackType, vec.match, tracks);
  }

  zip.file(entry, xml);
  const buffer = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
  return { buffer, entry, timelineUuid: seqId, at, delta, shifted };
}

module.exports = { moveClip, deleteClip, trimClip, trimClipHead, splitClip, rippleTimeline };
