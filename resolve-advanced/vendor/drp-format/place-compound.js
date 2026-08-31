/**
 * place-compound — author a COMPOUND CLIP (nested timeline) into a .drp,
 * offline.
 *
 * Anatomy (harvested live from Studio 19.1.3.7, CreateCompoundClip +
 * ExportProject; extraction of this shape render-verified — the compound's
 * inner content plays):
 *   - pool: `Sm2MpCompoundClip` EMBEDDING a full `Sm2Sequence` (its own
 *     FrameRate/Resolution/MediaExtents + Fairlight FieldsBlob, EMPTY track
 *     vecs);
 *   - the inner tracks live in their OWN SeqContainer whose `<Sequence>`
 *     values reference the embedded Sm2Sequence DbId; the inner timeline's
 *     ORIGIN IS FRAME 0 (unlike top-level timelines at 86400);
 *   - the parent-timeline item is a plain `Sm2TiVideoClip` with `MediaRef`
 *     → the compound's pool DbId, `MediaStartTime` 0, and an identity
 *     `MediaTimemapBA` of [0x02][doubleBE((innerFrames − 0.5) / fps)].
 *
 * All three pieces ride as harvested templates (compound-pool-r19 /
 * compound-inner-r19 / compound-item-r19); this module rewires identities
 * and empties the inner Items — the caller then places content INSIDE the
 * compound with the ordinary cuts machinery, passing the returned
 * `innerContainerId` as `timelineUuid` (0-based frames).
 *
 * @module drp-format/place-compound
 */

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { escapeXml } = require('./xml-builder');
const { loadDrpZip, selectTargetSeq, getTrackVec, replaceTrackVec, getItemsInner, setItemsInner, freshDbIds } = require('./seq-surgery');

const T = (f) => path.join(__dirname, 'templates', f);

/**
 * Insert an EMPTY compound (pool object + inner container + parent item).
 *
 * @param {Buffer|string} drpInput
 * @param {object} opts
 * @param {string} opts.name              - compound name (parent item + pool).
 * @param {number} opts.startFrame        - parent placement (timeline-absolute).
 * @param {number} opts.durationFrames    - parent item duration AND the inner
 *                                          timeline's content length.
 * @param {number} [opts.track=1]         - parent video track (must exist).
 * @param {number} [opts.fps=24]
 * @param {string} [opts.timelineUuid]    - parent container DbId.
 * @returns {Promise<{buffer:Buffer, compoundId:string, innerContainerId:string, innerSequenceId:string}>}
 */
async function placeCompound(drpInput, opts = {}) {
  const { name, startFrame, durationFrames, track = 1, fps = 24, timelineUuid } = opts;
  if (typeof name !== 'string' || !name.length) throw new TypeError('placeCompound: name is required');
  if (!Number.isInteger(startFrame) || !Number.isInteger(durationFrames) || durationFrames <= 0) {
    throw new TypeError('placeCompound: integer startFrame and positive durationFrames are required');
  }

  const zip = await loadDrpZip(drpInput);
  const { entry, xml: parentXml } = await selectTargetSeq(zip, timelineUuid);

  // The harvested compound cluster keeps its ORIGINAL GUIDs verbatim: the
  // embedded Sm2Sequence FieldsBlob almost certainly encodes cluster
  // identities, and freshening the XML ids around an unchanged blob CRASHED
  // Resolve on import (measured, E47/E47c — the app died, twice). The
  // harvest GUIDs cannot collide with an assembled archive's fresh ids, so
  // verbatim is safe — but it limits authoring to ONE compound per archive.
  const pool0 = fs.readFileSync(T('compound-pool-r19.xml'), 'utf8');
  const compoundId = pool0.match(/<Sm2MpCompoundClip DbId="([^"]+)"/)[1];
  const innerSequenceId = pool0.match(/<Sm2Sequence DbId="([^"]+)"/)[1];
  const inner0 = fs.readFileSync(T('compound-inner-r19.xml'), 'utf8');
  const innerContainerId = inner0.match(/<Sm2SequenceContainer DbId="([^"]+)"/)[1];
  if (zip.file(`SeqContainer/${innerContainerId}.xml`)) {
    throw new Error('placeCompound: only one compound per archive is supported (the harvested donor identities are kept verbatim)');
  }

  // 1) Inner container: template verbatim, Items emptied (content added by
  //    the caller via the cuts machinery, 0-based frames).
  const inner = inner0.replace(/<Items>[\s\S]*?<\/Items>/g, '<Items/>');
  zip.file(`SeqContainer/${innerContainerId}.xml`, inner);

  // 2) Pool compound element: verbatim identities; only name + extents change.
  let pool = pool0;
  pool = pool.replace(/<Name>[^<]*<\/Name>/, `<Name>${escapeXml(name)}</Name>`);
  // MediaExtents = [startSec, durationSec] LE doubles; inner starts at 0.
  const me = Buffer.alloc(16);
  me.writeDoubleLE(0, 0);
  me.writeDoubleLE(durationFrames / fps, 8);
  pool = pool.replace(/<MediaExtents>[0-9a-fA-F]*<\/MediaExtents>/, `<MediaExtents>${me.toString('hex')}</MediaExtents>`);
  // Attach to the primary MediaPool folder — and point the element's
  // <MpFolder> at THAT folder's DbId (the template's value references the
  // harvest project's folder; a dangling folder ref CRASHES Resolve on
  // import, measured E47).
  const mpPath = 'MediaPool/Master/MpFolder.xml';
  let mpXml = await zip.file(mpPath).async('string');
  const folderId = (mpXml.match(/<Sm2MpFolder DbId="([^"]+)"/) || [])[1];
  if (!folderId) throw new Error('placeCompound: target MpFolder has no Sm2MpFolder DbId');
  pool = pool.replace(/<MpFolder>[0-9a-f-]{36}<\/MpFolder>/, `<MpFolder>${folderId}</MpFolder>`);
  mpXml = mpXml.replace('</MediaVec>', `${pool}\n  </MediaVec>`);
  zip.file(mpPath, mpXml);

  // 3) Parent item: template clone → fresh id, name, placement, MediaRef,
  //    identity timemap over the inner content ((frames − 0.5)/fps, measured).
  let item = fs.readFileSync(T('compound-item-r19.xml'), 'utf8').trim();
  item = freshDbIds(item);
  item = item.replace(/<Name>[^<]*<\/Name>/, `<Name>${escapeXml(name)}</Name>`);
  item = item.replace(/<Start>\d+<\/Start>/, `<Start>${startFrame}</Start>`);
  item = item.replace(/<Duration>\d+<\/Duration>/, `<Duration>${durationFrames}</Duration>`);
  item = item.replace(/<MediaRef>[0-9a-f-]{36}<\/MediaRef>/, `<MediaRef>${compoundId}</MediaRef>`);
  const tm = Buffer.alloc(9);
  tm.writeUInt8(0x02, 0);
  tm.writeDoubleBE((durationFrames - 0.5) / fps, 1);
  item = item.replace(/<MediaTimemapBA>[0-9a-fA-F]*<\/MediaTimemapBA>/, `<MediaTimemapBA>${tm.toString('hex')}</MediaTimemapBA>`);

  const { match: vec, tracks } = getTrackVec(parentXml, 'video');
  if (track > tracks.length) throw new Error(`placeCompound: parent video track ${track} does not exist (${tracks.length})`);
  const items = getItemsInner(tracks[track - 1]);
  tracks[track - 1] = setItemsInner(tracks[track - 1], items + item);
  const newParent = replaceTrackVec(parentXml, 'video', vec, tracks);
  zip.file(entry, newParent);

  const buffer = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
  return { buffer, compoundId, innerContainerId, innerSequenceId };
}

module.exports = { placeCompound };
