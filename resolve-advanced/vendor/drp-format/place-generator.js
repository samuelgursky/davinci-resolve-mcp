/**
 * place-generator — drop a built-in Resolve GENERATOR (Solid Color, etc.) onto a chosen
 * video track of a real .drp, the same track-targeting bypass as placeFusionTitle.
 *
 * Built-in generators are `<Sm2TiGenerator>` with a `<PrettyType>` naming the generator
 * (Solid Color, Gray Scale, …) — small, no Fusion-comp blob (unlike Text+, which is an
 * Sm2TiVideoClip). The default has an empty `<EffectFiltersBA>` (default params/color).
 *
 * COLOR (E110, ground truth from Resolve's OWN writer, Studio 19.1.3.7): a Solid Color
 * with a non-default color carries a 55-byte `<EffectFiltersBA>`. Resolve's FCP7 XML
 * importer honours a generatoritem `fillcolor` (red rendered Y81 U90 V240, blue
 * Y41 U240 V110 — exact BT.601 limited-range), EXPORT_DRT then wrote:
 *   00000002 0000002f                      version 2, payload length 47
 *   80 0a 2c 08 0a 18 00 4a 00 4a 24 08 06 1a 0f 0a 0d 32 0b   fixed prefix
 *   01  AAAA RRRR GGGG BBBB 0000           flag + big-endian uint16 ARGB (+ pad)
 *   22 0f 0a 0d 32 0b 00 ffff 0000 0000 0000 0000              second colour, black
 * Only the ARGB words differed between the red and blue captures. `opts.color`
 * ({r,g,b} in 0..1, or 0..255 ints) populates that blob; omitted = the empty default.
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
 * @param {{r:number,g:number,b:number,a?:number}} [opts.color] - Solid Color fill (0..1 floats, or 0..255 ints).
 * @returns {Promise<{buffer:Buffer, entry:string, timelineUuid:string, trackIndex:number,
 *   generatorName:string, videoTrackCount:number, createdTracks:number, color:object|null}>}
 */
async function placeGenerator(drpInput, opts = {}) {
  const { generatorName = 'Solid Color', trackIndex = 2, startFrame, durationFrames = 120, timelineUuid, templateVersion, color } = opts;
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
  const colorNorm = color != null ? normalizeColor(color) : null;
  if (colorNorm) {
    const blob = solidColorEffectBlob(colorNorm);
    if (!/<EffectFiltersBA\s*\/>|<EffectFiltersBA>\s*<\/EffectFiltersBA>/.test(gen)) {
      throw new Error('placeGenerator: template carries no empty <EffectFiltersBA/> to populate with the colour');
    }
    gen = gen.replace(/<EffectFiltersBA\s*\/>|<EffectFiltersBA>\s*<\/EffectFiltersBA>/, `<EffectFiltersBA>${blob}</EffectFiltersBA>`);
  }

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
    videoTrackCount: tracks.length, createdTracks, color: colorNorm,
  };
}

// ── Solid Color effect blob (E110) ─────────────────────────────────────
const BLOB_PREFIX = '000000020000002f800a2c080a18004a004a2408061a0f0a0d320b01';
const BLOB_SUFFIX = '0000220f0a0d320b00ffff0000000000000000';

/** {r,g,b[,a]} in 0..1 floats or 0..255 ints → 0..1 floats. Refuses NaN/out-of-range. */
function normalizeColor(c) {
  if (!c || typeof c !== 'object') throw new TypeError('placeGenerator: color must be {r,g,b[,a]}');
  const vals = ['r', 'g', 'b'].map((k) => Number(c[k]));
  if (vals.some((v) => !Number.isFinite(v) || v < 0)) throw new RangeError('placeGenerator: color r/g/b must be finite numbers >= 0');
  const a = c.a == null ? null : Number(c.a);
  if (a != null && (!Number.isFinite(a) || a < 0)) throw new RangeError('placeGenerator: color a must be a finite number >= 0');
  const all = a == null ? vals : [...vals, a];
  const eightBit = all.some((v) => v > 1);
  const norm = (v) => (eightBit ? v / 255 : v);
  const out = { r: norm(vals[0]), g: norm(vals[1]), b: norm(vals[2]), a: a == null ? 1 : norm(a) };
  for (const k of ['r', 'g', 'b', 'a']) if (out[k] > 1) throw new RangeError(`placeGenerator: color ${k} exceeds range (0..1 floats or 0..255 ints)`);
  return out;
}

/** Encode a normalized {r,g,b,a} (0..1) as the 55-byte Solid Color EffectFiltersBA hex. */
function solidColorEffectBlob(color) {
  const c = normalizeColor(color);
  const w = (v) => Math.round(v * 65535).toString(16).padStart(4, '0');
  return `${BLOB_PREFIX}${w(c.a)}${w(c.r)}${w(c.g)}${w(c.b)}${BLOB_SUFFIX}`;
}

/** Decode a Solid Color EffectFiltersBA hex → {r,g,b,a} in 0..1, or null when it is not that shape. */
function decodeSolidColorEffectBlob(hex) {
  const h = String(hex || '').toLowerCase();
  if (h.length !== 110 || !h.startsWith(BLOB_PREFIX) || !h.endsWith(BLOB_SUFFIX)) return null;
  const words = h.slice(BLOB_PREFIX.length, BLOB_PREFIX.length + 16);
  const v = (i) => parseInt(words.slice(i * 4, i * 4 + 4), 16) / 65535;
  return { a: v(0), r: v(1), g: v(2), b: v(3) };
}

module.exports = { placeGenerator, TEMPLATE_PATH, solidColorEffectBlob, decodeSolidColorEffectBlob, normalizeColor };
