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
 * generators by changing PrettyType — RENDER-VERIFIED on Studio 19.1.3.7 (2026-08-30):
 * Solid Color YAVG 16 over white 234, SMPTE Color Bar 104.9, Grey Scale 125.1, all from a
 * fully offline-authored .drt. Unlike Fusion titles, Sm2TiGenerator has no comp blob, so
 * the byte-keyed Fusion render-cache law does NOT apply: generators render live everywhere.
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
  getItemsInner,
  setItemsInner,
  freshDbIds,
} = require('./seq-surgery');

const TEMPLATE_PATH = path.join(__dirname, 'templates', 'generator-solid-color.xml');
const TEMPLATE_PATH_R19 = path.join(__dirname, 'templates', 'generator-solid-color-r19.xml');
// Generation-bound like every other harvested structure (R21 snippet renders
// black on 19 — measured); r19 variant harvested live from 19.1.3.7.
function snippetPathFor(templateVersion) {
  return (Number(templateVersion) || 21) >= 21 ? TEMPLATE_PATH : TEMPLATE_PATH_R19;
}

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
  const { generatorName = 'Solid Color', trackIndex = 2, startFrame, durationFrames = 120, timelineUuid, templateVersion } = opts;
  if (!Number.isInteger(startFrame)) throw new TypeError('placeGenerator: startFrame (int) is required');
  if (!Number.isInteger(trackIndex) || trackIndex < 1) throw new TypeError('placeGenerator: trackIndex must be a positive integer');
  if (/[<>]/.test(generatorName)) throw new Error('placeGenerator: generatorName must not contain < or >');

  const zip = await loadDrpZip(drpInput);
  const { entry, xml: seqXml, seqId } = await selectTargetSeq(zip, timelineUuid);

  let gen = fs.readFileSync(snippetPathFor(templateVersion), 'utf8').trim();
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
  // Insert in CHRONOLOGICAL item order, not appended: placeTransition detects
  // junctions by listed adjacency, so a generator that precedes a clip in
  // time (a fade-in's black slug, E91) must precede it in <Items> too.
  // Compound-clip elements are not scanned (their nested inner <Element>s
  // defeat the lazy regex); a generator meant to sit before one appends.
  const track = tracks[trackIndex - 1];
  const innerItems = getItemsInner(track);
  const clipRe = /<Element>\s*<Sm2Ti(?:VideoClip|AudioClip|Generator)\b[\s\S]*?<\/Sm2Ti(?:VideoClip|AudioClip|Generator)>\s*<\/Element>/g;
  let insertAt = -1;
  let m;
  while ((m = clipRe.exec(innerItems)) !== null) {
    const sm = /<Start>(\d+)<\/Start>/.exec(m[0]);
    if (sm && parseInt(sm[1], 10) > startFrame) { insertAt = m.index; break; }
  }
  tracks[trackIndex - 1] = insertAt >= 0
    ? setItemsInner(track, innerItems.slice(0, insertAt) + gen + innerItems.slice(insertAt))
    : insertClipIntoTrack(track, gen);

  const xml = replaceTrackVec(seqXml, 'video', vtv, tracks);
  zip.file(entry, xml);
  const buffer = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
  return {
    buffer, entry, timelineUuid: seqId, trackIndex, generatorName,
    videoTrackCount: tracks.length, createdTracks,
  };
}

module.exports = { placeGenerator, TEMPLATE_PATH };
