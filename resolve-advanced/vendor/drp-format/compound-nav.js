/**
 * compound-nav — walk INTO compound clips and nested timelines in a .drp.
 *
 * A compound clip and a nested timeline are the same shape on disk: a sequence
 * inside a sequence. Both appear in `MediaPool/Master/MpFolder.xml` as a media
 * pool element (`Sm2MpCompoundClip` / `Sm2MpTimelineClip`) carrying an inline
 * `<Sequence><Sm2Sequence DbId="X">`, and the `SeqContainer/<uuid>.xml` whose
 * tracks reference `<Sequence>X</Sequence>` holds the contents. The container's
 * own filename/DbId is referenced by NOTHING else in the package — the join is
 * on the Sm2Sequence DbId, not the container id.
 *
 * This matters because the SCRIPTING API cannot do it. MediaPoolItem.GetTimeline()
 * (Resolve 21.0.4+) resolves through the timeline handle: it returns the inner
 * Timeline for a `Type='Timeline'` item and None for a `Type='Compound'` one.
 * Compounding a Text+ therefore severs its text permanently as far as the API is
 * concerned — FusionCompCount drops 1 -> 0 and nothing reaches the tools inside.
 * Offline, the distinction does not exist: both are just a nested <Sequence>.
 *
 * Verified against a Resolve Studio 21.0.4.5 export (DbPrjVer 17) containing a
 * compound-of-media, a compound-of-Text+, and a nested timeline.
 *
 * @module drp-format/compound-nav
 */

const { loadDrpZip, splitTrackElements, splitClipElements, getItemsInner } = require('./seq-surgery');

const MP_FOLDER = 'MediaPool/Master/MpFolder.xml';

const KINDS = {
  Sm2MpCompoundClip: 'compound',
  Sm2MpTimelineClip: 'timeline',
};

const tagValue = (xml, tag) => {
  const m = xml.match(new RegExp(`<${tag}>([^<]*)</${tag}>`));
  return m ? m[1] : null;
};

/**
 * The Sm2Sequence DbId a media pool element points at.
 * Read from the element's own <Sequence> child, NOT from any later sibling.
 */
function sequenceDbIdOf(elementXml) {
  const m = elementXml.match(/<Sequence>\s*<Sm2Sequence\s+DbId="([^"]+)"/);
  return m ? m[1] : null;
}

/** Every SeqContainer entry, mapped by the Sm2Sequence DbId its tracks carry. */
async function containersBySequenceId(zip) {
  const out = new Map();
  for (const name of Object.keys(zip.files)) {
    if (!/^SeqContainer\/[^/]+\.xml$/.test(name)) continue;
    const xml = await zip.file(name).async('string');
    const seq = tagValue(xml, 'Sequence');
    if (seq) out.set(seq, { entry: name, xml });
  }
  return out;
}

/**
 * List every nested sequence in the package — compounds AND timelines.
 *
 * @param {Buffer|string} drpInput
 * @returns {Promise<Array<{kind:'compound'|'timeline', name:string,
 *   sequenceDbId:string, entry:string|null, mediaPoolItemId:string|null,
 *   videoTracks:number, itemCount:number}>>}
 */
async function listNestedSequences(drpInput) {
  const zip = await loadDrpZip(drpInput);
  const mp = await zip.file(MP_FOLDER).async('string');
  const bySeq = await containersBySequenceId(zip);

  const results = [];
  for (const [tag, kind] of Object.entries(KINDS)) {
    const re = new RegExp(`<${tag}\\b[\\s\\S]*?</${tag}>`, 'g');
    for (const m of mp.matchAll(re)) {
      const el = m[0];
      const sequenceDbId = sequenceDbIdOf(el);
      const found = sequenceDbId ? bySeq.get(sequenceDbId) : null;
      let videoTracks = 0;
      let itemCount = 0;
      if (found) {
        const vec = found.xml.match(/<VideoTrackVec>([\s\S]*?)<\/VideoTrackVec>/);
        const tracks = vec ? splitTrackElements(vec[1]) : [];
        videoTracks = tracks.length;
        itemCount = tracks.reduce(
          (n, t) => n + splitClipElements(getItemsInner(t) || '').length, 0);
      }
      results.push({
        kind,
        name: tagValue(el, 'Name'),
        sequenceDbId,
        entry: found ? found.entry : null,
        mediaPoolItemId: tagValue(el, 'UniqueMediaPoolItemId'),
        videoTracks,
        itemCount,
      });
    }
  }
  return results;
}

/**
 * Read the contents of one nested sequence by media pool name.
 *
 * @param {Buffer|string} drpInput
 * @param {object} opts
 * @param {string} opts.name - the compound / timeline name in the media pool.
 * @returns {Promise<{kind:string, name:string, entry:string,
 *   tracks:Array<{index:number, items:Array<{type:string, name:string,
 *   start:number|null, duration:number|null, dbId:string|null}>}>}>}
 */
async function readNestedSequence(drpInput, opts = {}) {
  const { name } = opts;
  if (!name) throw new TypeError('readNestedSequence: name is required');
  const zip = await loadDrpZip(drpInput);
  const list = await listNestedSequences(drpInput);
  const hit = list.find((e) => e.name === name);
  if (!hit) throw new Error(`readNestedSequence: no compound or timeline named ${JSON.stringify(name)}`);
  if (!hit.entry) throw new Error(`readNestedSequence: ${name} has no SeqContainer (sequence ${hit.sequenceDbId})`);

  const xml = await zip.file(hit.entry).async('string');
  const vec = xml.match(/<VideoTrackVec>([\s\S]*?)<\/VideoTrackVec>/);
  const tracks = (vec ? splitTrackElements(vec[1]) : []).map((t, i) => ({
    index: i + 1,
    items: splitClipElements(getItemsInner(t) || '').map((c) => {
      const typeMatch = c.match(/<(Sm2Ti[A-Za-z]+)\b/);
      const idMatch = c.match(/<Sm2Ti[A-Za-z]+\s+DbId="([^"]+)"/);
      const num = (tag) => {
        const v = tagValue(c, tag);
        return v == null ? null : parseInt(v, 10);
      };
      return {
        type: typeMatch ? typeMatch[1] : 'unknown',
        name: tagValue(c, 'Name'),
        start: num('Start'),
        duration: num('Duration'),
        dbId: idMatch ? idMatch[1] : null,
      };
    }),
  }));
  return { kind: hit.kind, name: hit.name, entry: hit.entry, tracks };
}

/** Locate the nested sequence's container entry + xml, or throw. */
async function resolveEntry(zip, drpInput, name) {
  const list = await listNestedSequences(drpInput);
  const hit = list.find((e) => e.name === name);
  if (!hit) throw new Error(`no compound or timeline named ${JSON.stringify(name)}`);
  if (!hit.entry) throw new Error(`${name} has no SeqContainer (sequence ${hit.sequenceDbId})`);
  return { hit, xml: await zip.file(hit.entry).async('string') };
}

const COMPOSITION_BA = /<CompositionBA>([^<]*)<\/CompositionBA>/g;

/**
 * Read the title inputs of every Fusion title inside a nested sequence.
 *
 * This is the operation the scripting API cannot perform on a compound at all:
 * MediaPoolItem.GetTimeline() is None for Type='Compound', and the compounded
 * item reports GetFusionCompCount()==0, so there is no route to the text.
 *
 * @param {Buffer|string} drpInput
 * @param {object} opts
 * @param {string} opts.name
 * @returns {Promise<Array<{index:number, text:string, font:string, style:string,
 *   size:number, vJustify:number, hJustify:number}>>}
 */
async function readNestedTitles(drpInput, opts = {}) {
  const { name } = opts;
  if (!name) throw new TypeError('readNestedTitles: name is required');
  const zip = await loadDrpZip(drpInput);
  const { xml } = await resolveEntry(zip, drpInput, name);
  const { decodeTitleInputs } = require('./composition-text');
  const out = [];
  let i = 0;
  for (const m of xml.matchAll(COMPOSITION_BA)) {
    out.push({ index: i++, ...decodeTitleInputs(m[1]) });
  }
  return out;
}

/**
 * Rewrite the text (and optionally font/style/size/justification) of a Fusion
 * title INSIDE a compound or nested timeline.
 *
 * @param {Buffer|string} drpInput
 * @param {object} opts
 * @param {string} opts.name              - compound / timeline name.
 * @param {number} [opts.titleIndex=0]    - which title inside, if several.
 * @param {string} [opts.text]            - new on-screen text (no double quotes).
 * @param {string} [opts.font] @param {string} [opts.style] @param {number} [opts.size]
 * @returns {Promise<{buffer:Buffer, entry:string, name:string, titleIndex:number,
 *   before:object, after:object}>}
 */
async function setNestedTitleText(drpInput, opts = {}) {
  const { name, titleIndex = 0, ...inputs } = opts;
  if (!name) throw new TypeError('setNestedTitleText: name is required');
  if (typeof inputs.text === 'string' && inputs.text.includes('"')) {
    throw new Error('setNestedTitleText: text must not contain double quotes');
  }
  const zip = await loadDrpZip(drpInput);
  const { hit, xml } = await resolveEntry(zip, drpInput, name);
  const { decodeTitleInputs, setTitleInputs } = require('./composition-text');

  const blobs = [...xml.matchAll(COMPOSITION_BA)];
  if (!blobs[titleIndex]) {
    throw new Error(`setNestedTitleText: ${name} has ${blobs.length} title(s); no index ${titleIndex}`);
  }
  const target = blobs[titleIndex];
  const before = decodeTitleInputs(target[1]);
  const rewritten = setTitleInputs(target[1], inputs);
  const after = decodeTitleInputs(rewritten);

  // Splice by offset — the same hex can legitimately appear more than once.
  const start = target.index;
  const patched = xml.slice(0, start)
    + `<CompositionBA>${rewritten}</CompositionBA>`
    + xml.slice(start + target[0].length);

  zip.file(hit.entry, patched);
  const buffer = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
  return { buffer, entry: hit.entry, name, titleIndex, before, after };
}

module.exports = {
  listNestedSequences,
  readNestedSequence,
  readNestedTitles,
  setNestedTitleText,
  sequenceDbIdOf,
};
