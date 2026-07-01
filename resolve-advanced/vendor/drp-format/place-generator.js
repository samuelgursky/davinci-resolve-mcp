/**
 * place-generator — drop a built-in Resolve GENERATOR (Solid Color, etc.) onto a chosen
 * video track of a real .drp, the same track-targeting bypass as placeFusionTitle.
 *
 * Built-in generators are `<Sm2TiGenerator>` with a `<PrettyType>` naming the generator
 * (Solid Color, Gray Scale, …) — small, no Fusion-comp blob (unlike Text+, which is an
 * Sm2TiVideoClip). The default has an empty `<EffectFiltersBA>` (default params/color);
 * setting a custom color would populate that blob (separate ground-truth capture).
 *
 * Clone-based: carry the bundled Solid Color template and swap PrettyType/Name/Start/
 * Duration + a fresh DbId. The same Sm2TiGenerator shape serves the other simple built-in
 * generators by changing PrettyType (verify per type before relying on it).
 *
 * @module drp-format/place-generator
 */

const fs = require('node:fs');
const path = require('node:path');
const { escapeXml } = require('./xml-builder');
const {
  loadDrpZip,
  selectTargetSeq,
  emptyTrackClone,
  insertClipIntoTrack,
  replaceTrackVec,
  getTrackVec,
  freshDbIds,
} = require('./seq-surgery');

const TEMPLATE_PATH = path.join(__dirname, 'templates', 'generator-solid-color.xml');

/**
 * Place a built-in generator on a chosen video track.
 *
 * @param {Buffer|string} drpInput
 * @param {object} opts
 * @param {string} [opts.generatorName='Solid Color'] - PrettyType, e.g. "Solid Color", "Gray Scale".
 * @param {number} [opts.trackIndex=2]   - 1-based video track (created empty up to it as needed).
 * @param {number} opts.startFrame       - timeline start frame (required; must be >= timeline origin).
 * @param {number} [opts.durationFrames=120]
 * @param {string} [opts.timelineUuid]
 * @returns {Promise<{buffer:Buffer, entry:string, timelineUuid:string, trackIndex:number,
 *   generatorName:string, videoTrackCount:number, createdTracks:number}>}
 */
async function placeGenerator(drpInput, opts = {}) {
  const { generatorName = 'Solid Color', trackIndex = 2, startFrame, durationFrames = 120, timelineUuid } = opts;
  if (!Number.isInteger(startFrame)) throw new TypeError('placeGenerator: startFrame (int) is required');
  if (!Number.isInteger(trackIndex) || trackIndex < 1) throw new TypeError('placeGenerator: trackIndex must be a positive integer');
  if (/[<>]/.test(generatorName)) throw new Error('placeGenerator: generatorName must not contain < or >');

  const zip = await loadDrpZip(drpInput);
  const { entry, xml: seqXml, seqId } = await selectTargetSeq(zip, timelineUuid);

  let gen = fs.readFileSync(TEMPLATE_PATH, 'utf8').trim();
  gen = freshDbIds(gen);
  gen = gen.replace(/<PrettyType>[\s\S]*?<\/PrettyType>/, `<PrettyType>${escapeXml(generatorName)}</PrettyType>`);
  gen = gen.replace(/<Name>[\s\S]*?<\/Name>/, `<Name>${escapeXml(generatorName)}</Name>`);
  gen = gen.replace(/<Start>\d+<\/Start>/, `<Start>${startFrame}</Start>`);
  gen = gen.replace(/<Duration>\d+<\/Duration>/, `<Duration>${durationFrames}</Duration>`);

  const { match: vtv, tracks } = getTrackVec(seqXml, 'video');
  if (tracks.length === 0) throw new Error('placeGenerator: no existing video track to clone from');
  let createdTracks = 0;
  const cloneSource = tracks[0];
  while (tracks.length < trackIndex) { tracks.push(emptyTrackClone(cloneSource)); createdTracks += 1; }
  tracks[trackIndex - 1] = insertClipIntoTrack(tracks[trackIndex - 1], gen);

  const xml = replaceTrackVec(seqXml, 'video', vtv, tracks);
  zip.file(entry, xml);
  const buffer = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
  return {
    buffer, entry, timelineUuid: seqId, trackIndex, generatorName,
    videoTrackCount: tracks.length, createdTracks,
  };
}

module.exports = { placeGenerator, TEMPLATE_PATH };
