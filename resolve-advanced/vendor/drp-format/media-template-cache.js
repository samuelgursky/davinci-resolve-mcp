/**
 * media-template-cache — native per-media descriptors, captured live once.
 *
 * Offline authoring cannot synthesize Resolve's media-identity descriptors:
 * repointing a template's pool entry at a different file imports and reads
 * back perfectly but the render engine refuses ("Full resolution media not
 * found") or paints black — the entry's deep blobs (Radiometry, keyed-dict
 * FieldsBlobs, stream descriptors) still describe the template's file.
 * Measured fix (2026-08-30, Studio 19.1.3.7): TRANSPLANT the entire native
 * media <Element> captured from a scratch project built around the target
 * file, and rewire the timeline clips' <MediaRef> to the native id —
 * rendered luma then matches the native control exactly.
 *
 * The Python server's media_pool.capture_media_template action writes these
 * caches (one JSON per media file, keyed by sha1 of the absolute path) while
 * Resolve is running; this module consumes them offline.
 *
 * @module drp-format/media-template-cache
 */

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');

const CACHE_DIR = process.env.DRP_MEDIA_TEMPLATE_DIR
  || path.join(os.homedir(), '.config', 'davinci-resolve-mcp', 'media-templates');

function cachePathFor(mediaFilePath) {
  const key = crypto.createHash('sha1').update(path.resolve(mediaFilePath)).digest('hex');
  return path.join(CACHE_DIR, `${key}.json`);
}

/** Load the cached native descriptor for a media file, or null. */
function loadMediaTemplate(mediaFilePath) {
  try {
    const raw = fs.readFileSync(cachePathFor(mediaFilePath), 'utf8');
    const data = JSON.parse(raw);
    if (!data.poolElement || !data.mediaRef) return null;
    return data;
  } catch (e) {
    return null;
  }
}

/** Replace the pool media <Element> holding `marker` and rewire MediaRefs. */
function transplantMediaElement(mpXml, seqXmls, { poolElement, mediaRef }) {
  const idx = mpXml.indexOf('<Sm2MpVideoClip');
  if (idx < 0) throw new Error('transplant: no Sm2MpVideoClip element in MpFolder');
  const start = mpXml.lastIndexOf('<Element>', idx);
  let depth = 0; let end = -1; let m;
  const re = /<\/?Element>/g;
  re.lastIndex = start;
  while ((m = re.exec(mpXml))) {
    if (m[0] === '<Element>') depth += 1; else depth -= 1;
    if (depth === 0) { end = m.index + m[0].length; break; }
  }
  if (end < 0) throw new Error('transplant: unbalanced Element nesting');
  const folderId = (mpXml.slice(start, end).match(/<MpFolder>([0-9a-f-]{36})<\/MpFolder>/) || [])[1];
  let element = poolElement;
  if (folderId) {
    element = element.replace(/<MpFolder>[0-9a-f-]{36}<\/MpFolder>/, `<MpFolder>${folderId}</MpFolder>`);
  }
  const outMp = mpXml.slice(0, start) + element + mpXml.slice(end);
  const outSeqs = seqXmls.map((seq) =>
    seq.replace(/<MediaRef>[0-9a-f-]{36}<\/MediaRef>/g, `<MediaRef>${mediaRef}</MediaRef>`),
  );
  return { mpXml: outMp, seqXmls: outSeqs };
}

module.exports = { CACHE_DIR, cachePathFor, loadMediaTemplate, transplantMediaElement };
