/**
 * place-transition — insert a cross-dissolve between two abutting clips in a real .drp,
 * offline. Transitions are the one thing the Resolve scripting API can't add (GUI only),
 * so this is the only programmatic path.
 *
 * Ground truth (captured via computer-use authoring a Cross Dissolve in Resolve 21):
 * a transition is an `<Sm2TiTransition>` element that lives in the track's `<Items>`
 * BETWEEN the two clip `<Element>`s — `<PrettyType>Cross Dissolve</PrettyType>`,
 * `<Start>`/`<Duration>`, `<AlignmentType>2` (centered on the cut), plus `FieldsBlob` +
 * `EffectFiltersBA` (the dissolve params). For a centered transition, Start = cut - Duration/2.
 *
 * The two clips must have HANDLE media across the cut (e.g. razored from continuous media),
 * or Resolve will render the dissolve edges as freeze/black.
 *
 * @module drp-format/place-transition
 */

const fs = require('node:fs');
const path = require('node:path');
const {
  loadDrpZip,
  selectTargetSeq,
  getTrackVec,
  replaceTrackVec,
  getItemsInner,
  setItemsInner,
  freshDbIds,
} = require('./seq-surgery');

// Timeline items a transition can sit between: media/title clips AND generators (Sm2TiGenerator).
function splitItems(itemsInner) {
  return itemsInner.match(/<Element>\s*<Sm2Ti(?:VideoClip|AudioClip|Generator)\b[\s\S]*?<\/Sm2Ti(?:VideoClip|AudioClip|Generator)>\s*<\/Element>/g) || [];
}

const TEMPLATE_PATH = path.join(__dirname, 'templates', 'transition-cross-dissolve.xml');

const clipStart = (c) => { const m = c.match(/<Start>(\d+)<\/Start>/); return m ? parseInt(m[1], 10) : null; };
const clipDuration = (c) => { const m = c.match(/<Duration>(\d+)<\/Duration>/); return m ? parseInt(m[1], 10) : null; };

/**
 * Insert a cross-dissolve at an abutting clip boundary.
 *
 * @param {Buffer|string} drpInput
 * @param {object} opts
 * @param {number} opts.track             - 1-based video track.
 * @param {number} opts.atFrame           - the cut frame (where one clip ends and the next begins).
 * @param {number} [opts.durationFrames=24] - transition length (even number recommended; centered).
 * @param {'video'} [opts.trackType='video'] - audio cross-fade uses a different template (not bundled).
 * @param {string} [opts.timelineUuid]
 * @returns {Promise<{buffer:Buffer, entry:string, timelineUuid:string, track:number,
 *   atFrame:number, start:number, durationFrames:number, transitionDbId:string|null}>}
 */
async function placeTransition(drpInput, opts = {}) {
  const { track, atFrame, durationFrames = 24, trackType = 'video', timelineUuid } = opts;
  if (!Number.isInteger(track) || track < 1) throw new TypeError('placeTransition: track must be a positive integer');
  if (!Number.isInteger(atFrame)) throw new TypeError('placeTransition: atFrame must be an integer');
  if (!Number.isInteger(durationFrames) || durationFrames < 2) throw new TypeError('placeTransition: durationFrames must be an integer >= 2');
  if (trackType !== 'video') throw new Error('placeTransition: only video cross-dissolve is supported (no bundled audio template)');

  const zip = await loadDrpZip(drpInput);
  const { entry, xml: seqXml, seqId } = await selectTargetSeq(zip, timelineUuid);
  const { match: vec, tracks } = getTrackVec(seqXml, trackType);
  if (track > tracks.length) throw new Error(`placeTransition: track ${track} does not exist (timeline has ${tracks.length})`);

  const items = getItemsInner(tracks[track - 1]);
  const clips = splitItems(items);
  let leftIdx = -1;
  for (let i = 0; i < clips.length - 1; i += 1) {
    const end = clipStart(clips[i]) + clipDuration(clips[i]);
    if (end === clipStart(clips[i + 1]) && end === atFrame) { leftIdx = i; break; }
  }
  if (leftIdx < 0) throw new Error(`placeTransition: no abutting clip boundary at frame ${atFrame} on track ${track}`);

  let trans = fs.readFileSync(TEMPLATE_PATH, 'utf8').trim();
  trans = freshDbIds(trans);
  const start = atFrame - Math.floor(durationFrames / 2); // centered (AlignmentType 2)
  trans = trans.replace(/<Start>\d+<\/Start>/, `<Start>${start}</Start>`);
  trans = trans.replace(/<Duration>\d+<\/Duration>/, `<Duration>${durationFrames}</Duration>`);
  const transitionDbId = (trans.match(/<Sm2TiTransition DbId="([^"]+)"/) || [])[1] || null;

  // Insert the transition <Element> immediately after the left clip's <Element> in <Items>.
  const newItems = items.replace(clips[leftIdx], `${clips[leftIdx]}${trans}`);
  tracks[track - 1] = setItemsInner(tracks[track - 1], newItems);

  const xml = replaceTrackVec(seqXml, trackType, vec, tracks);
  zip.file(entry, xml);
  const buffer = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
  return { buffer, entry, timelineUuid: seqId, track, atFrame, start, durationFrames, transitionDbId };
}

module.exports = { placeTransition, TEMPLATE_PATH };
