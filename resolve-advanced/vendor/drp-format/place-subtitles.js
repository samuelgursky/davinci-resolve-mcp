/**
 * place-subtitles — author SUBTITLE items into a timeline inside a real .drp,
 * offline.
 *
 * Ground truth (harvested live from Studio 19.1.3.7, an SRT appended via the
 * scripting API and re-exported): a subtitle is the SIMPLEST timeline item in
 * the schema — a plain `<Sm2TiGenerator>` with `<PrettyType>Subtitle` and the
 * CUE TEXT in `<Name>`, all blob fields empty, sitting in a `<Sm2TiTrack>` of
 * `<Type>2</Type>` inside `<SubtitleTrackVec>`. No Fusion comp, so the
 * byte-keyed comp-cache law does not apply; the text is API-visible after
 * import (readback IS meaningful here — the payload is the Name).
 *
 * The r19 template ships `<SubtitleTrackVec/>` self-closed; this module
 * synthesizes the vec + track from the harvested shape (track FieldsBlob is
 * the same keyed NumLayers=0 dict every track carries) and reuses the
 * timeline's shared <Sequence> uuid.
 *
 * Caveat (measured): Resolve treats angle-bracket runs in cue text as SRT
 * formatting markup — an unknown tag like <escaped> is STRIPPED from the
 * displayed/readback name. That is standard subtitle semantics, not a loss
 * in this writer (the XML itself carries the text escaped and intact).
 *
 * @module drp-format/place-subtitles
 */

const crypto = require('node:crypto');
const { escapeXml } = require('./xml-builder');
const { loadDrpZip, selectTargetSeq } = require('./seq-surgery');

// Harvested track FieldsBlob: keyed dict { NumLayers: int32 0 } — identical
// across video/audio/subtitle tracks.
const TRACK_FIELDS_BLOB = '000000010000000100000012004e0075006d004c00610079006500720073000000020000000000';

function subtitleElement({ startFrame, durationFrames, text }) {
  return (
    `<Element>\n      <Sm2TiGenerator DbId="${crypto.randomUUID()}">\n` +
    '       <FieldsBlob/>\n' +
    '       <PrettyType>Subtitle</PrettyType>\n' +
    `       <Name>${escapeXml(text)}</Name>\n` +
    `       <Start>${startFrame}</Start>\n` +
    `       <Duration>${durationFrames}</Duration>\n` +
    '       <LinkedItemSync/>\n' +
    '       <WasDisbanded>false</WasDisbanded>\n' +
    '       <MarkersBA/>\n' +
    '       <UiMemento>0</UiMemento>\n' +
    '       <Flags>0</Flags>\n' +
    '       <PriorityIndex>0</PriorityIndex>\n' +
    '       <EffectFiltersBA/>\n' +
    '       <ImportExportMetadataBA/>\n' +
    '       <RenderTextEnabled>true</RenderTextEnabled>\n' +
    '       <RenderTextGanged>true</RenderTextGanged>\n' +
    '       <RenderTextPrefixed>true</RenderTextPrefixed>\n' +
    '       <In/>\n' +
    '      </Sm2TiGenerator>\n     </Element>'
  );
}

/**
 * Place subtitle cues on the (single) subtitle track of a timeline in a .drp.
 * Overlapping cues are refused — one track cannot hold both.
 *
 * @param {Buffer|string} drpInput
 * @param {object} opts
 * @param {Array<{startFrame:number,durationFrames:number,text:string}>} opts.subtitles
 *   startFrame is timeline-ABSOLUTE (origin 86400 on the bundled templates).
 * @param {string} [opts.timelineUuid]
 * @returns {Promise<{buffer:Buffer, entry:string, timelineUuid:string, count:number}>}
 */
async function placeSubtitles(drpInput, opts = {}) {
  const { subtitles, timelineUuid } = opts;
  if (!Array.isArray(subtitles) || !subtitles.length) throw new TypeError('placeSubtitles: subtitles must be a non-empty array');
  const sorted = [...subtitles].sort((a, b) => a.startFrame - b.startFrame);
  sorted.forEach((sub, i) => {
    if (!Number.isInteger(sub.startFrame) || !Number.isInteger(sub.durationFrames) || sub.durationFrames <= 0) {
      throw new TypeError(`placeSubtitles: subtitles[${i}] needs integer startFrame and positive durationFrames`);
    }
    if (typeof sub.text !== 'string' || !sub.text.length) throw new TypeError(`placeSubtitles: subtitles[${i}].text must be a non-empty string`);
    if (i > 0 && sub.startFrame < sorted[i - 1].startFrame + sorted[i - 1].durationFrames) {
      throw new RangeError(`placeSubtitles: cues ${i - 1} and ${i} overlap — one subtitle track cannot hold both`);
    }
  });

  const zip = await loadDrpZip(drpInput);
  const { entry, xml: seqXml, seqId } = await selectTargetSeq(zip, timelineUuid);
  const seqUuidM = seqXml.match(/<Sequence>([0-9a-f-]{36})<\/Sequence>/);
  if (!seqUuidM) throw new Error('placeSubtitles: cannot find the shared <Sequence> uuid');
  const items = sorted.map(subtitleElement).join('\n     ');
  const track =
    `\n  <Element>\n   <Sm2TiTrack DbId="${crypto.randomUUID()}">\n` +
    `    <FieldsBlob>${TRACK_FIELDS_BLOB}</FieldsBlob>\n` +
    '    <Type>2</Type>\n    <SubType>0</SubType>\n    <Flags>0</Flags>\n' +
    `    <Sequence>${seqUuidM[1]}</Sequence>\n` +
    `    <Items>\n     ${items}\n    </Items>\n` +
    '    <UserDefinedName/>\n    <LayersVec/>\n   </Sm2TiTrack>\n  </Element>\n ';
  let xml;
  if (/<SubtitleTrackVec\/>/.test(seqXml)) {
    xml = seqXml.replace('<SubtitleTrackVec/>', `<SubtitleTrackVec>${track}</SubtitleTrackVec>`);
  } else if (/<SubtitleTrackVec>/.test(seqXml)) {
    xml = seqXml.replace('</SubtitleTrackVec>', `${track}</SubtitleTrackVec>`);
  } else {
    throw new Error('placeSubtitles: timeline has no SubtitleTrackVec');
  }
  zip.file(entry, xml);
  const buffer = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
  return { buffer, entry, timelineUuid: seqId, count: sorted.length };
}

/** Parse an SRT string → cues in frames at fps (timeline-RELATIVE, add the origin). */
function parseSrt(srt, fps = 24) {
  const cues = [];
  const tc = (s) => {
    const m = /(\d{2}):(\d{2}):(\d{2})[,.](\d{3})/.exec(s);
    return Math.round(((+m[1] * 3600 + +m[2] * 60 + +m[3]) + +m[4] / 1000) * fps);
  };
  for (const block of String(srt).replace(/\r/g, '').split(/\n\n+/)) {
    const lines = block.split('\n').filter((l) => l.trim().length);
    const ti = lines.findIndex((l) => /-->/.test(l));
    if (ti < 0) continue;
    const [a, b] = lines[ti].split('-->');
    const text = lines.slice(ti + 1).join('\n').trim();
    if (!text) continue;
    const start = tc(a), end = tc(b);
    if (end > start) cues.push({ startFrame: start, durationFrames: end - start, text });
  }
  return cues;
}

module.exports = { placeSubtitles, parseSrt };
