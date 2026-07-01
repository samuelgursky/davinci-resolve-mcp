/**
 * author-project — create a NEW, importable Resolve project from scratch.
 *
 * Resolve's project.xml + MpFolder.xml are large and undocumented, so rather than
 * synthesize every byte we scaffold from a bundled real empty-project export
 * (templates/empty-project.drp — one empty timeline, correct Sm2TiTrack schema,
 * captured from Resolve Studio 21). Compose with placeFusionTitle / moveClip to
 * populate the empty timeline — a complete from-scratch authoring path that imports.
 *
 * The timeline name lives in the Media Pool (MpFolder.xml), not the SeqContainer,
 * so renaming is a targeted string replace there.
 *
 * @module drp-format/author-project
 */

const fs = require('node:fs');
const path = require('node:path');
const JSZip = require('jszip');
const { escapeXml } = require('./xml-builder');
const { repointMedia } = require('./relink-media');
const { trimClip } = require('./splice-clips');

const TEMPLATE_DRP = path.join(__dirname, 'templates', 'empty-project.drp');
const DEFAULT_TIMELINE_NAME = 'Timeline 1';

// Bundled single-clip h264 media template (captured from Resolve 21) + its known specs — the
// "from" side for repointMedia when authoring a media clip from scratch.
const MEDIA_TEMPLATE_DRP = path.join(__dirname, 'templates', 'media-clip-h264.drp');
const MEDIA_TEMPLATE_SPEC = { width: 352, height: 262, frameCount: 4576, fps: 30000 / 1001 };
const MEDIA_TEMPLATE_TL_NAME = 'MediaTemplate';
// The template timeline begins at 01:00:00:00 (24fps) — clips placed BEFORE this frame are
// dropped by Resolve on import. Callers should place at >= startFrame.
const DEFAULT_START_FRAME = 86400;

/**
 * Build a fresh, importable .drp containing one empty timeline.
 *
 * @param {object} [opts]
 * @param {string} [opts.timelineName] - rename the single timeline (default "Timeline 1").
 * @returns {Promise<{buffer: Buffer, timelineName: string, startFrame: number}>}
 *   startFrame is the timeline origin (86400 = 01:00:00:00 @ 24fps); place clips at >= this.
 */
async function createEmptyProject(opts = {}) {
  const { timelineName } = opts;
  const tmpl = await fs.promises.readFile(TEMPLATE_DRP);

  if (!timelineName || timelineName === DEFAULT_TIMELINE_NAME) {
    return { buffer: tmpl, timelineName: DEFAULT_TIMELINE_NAME, startFrame: DEFAULT_START_FRAME };
  }
  if (/[<>]/.test(timelineName)) throw new Error('createEmptyProject: timelineName must not contain < or >');

  const zip = await JSZip.loadAsync(tmpl);
  const mpPath = 'MediaPool/Master/MpFolder.xml';
  const mp = await zip.file(mpPath).async('string');
  const renamed = mp.split(`<Name>${DEFAULT_TIMELINE_NAME}</Name>`).join(`<Name>${escapeXml(timelineName)}</Name>`);
  zip.file(mpPath, renamed);

  const buffer = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
  return { buffer, timelineName, startFrame: DEFAULT_START_FRAME };
}

/**
 * Author a project containing ONE media clip referencing an arbitrary (h264) file, from scratch.
 * Scaffolds from the bundled single-clip template and repoints it to the target file + specs
 * (Resolve doesn't reconform, so the cached specs must match). Same codec family (h264) as the
 * template; cross-codec needs a per-codec template.
 *
 * @param {object} opts
 * @param {string} opts.mediaFile        - absolute path to the target media file.
 * @param {{width:number,height:number,frameCount:number,fps:number}} opts.spec - target specs (ffprobe).
 * @param {string} [opts.timelineName]   - rename the timeline.
 * @param {number} [opts.durationFrames] - trim the timeline clip to this length (else keeps template's;
 *                                         a shorter target will over-run into freeze/black without it).
 * @returns {Promise<{buffer:Buffer, timelineName:string, mediaFile:string}>}
 */
async function addMediaClip(opts = {}) {
  const { mediaFile, spec, timelineName, durationFrames } = opts;
  if (!mediaFile || !path.isAbsolute(mediaFile)) throw new Error('addMediaClip: mediaFile must be an absolute path');
  if (!spec || ['width', 'height', 'frameCount', 'fps'].some((k) => typeof spec[k] !== 'number')) {
    throw new Error('addMediaClip: spec must be { width, height, frameCount, fps } (numbers)');
  }

  const tmpl = await fs.promises.readFile(MEDIA_TEMPLATE_DRP);
  // Discover the template's current media path (the "from" for repoint).
  const zip0 = await JSZip.loadAsync(tmpl);
  let fromPath = null;
  for (const n of Object.keys(zip0.files)) {
    if (!/SeqContainer\/[^/]+\.xml$/.test(n)) continue;
    const m = (await zip0.file(n).async('string')).match(/<MediaFilePath>([^<]+)<\/MediaFilePath>/);
    if (m) { fromPath = m[1]; break; }
  }
  if (!fromPath) throw new Error('addMediaClip: could not read template media path');

  let { buffer } = await repointMedia(tmpl, {
    from: fromPath, to: mediaFile, fromSpec: MEDIA_TEMPLATE_SPEC, toSpec: spec,
  });

  // Rename the timeline (lives in the Media Pool).
  if (timelineName && timelineName !== MEDIA_TEMPLATE_TL_NAME) {
    if (/[<>]/.test(timelineName)) throw new Error('addMediaClip: timelineName must not contain < or >');
    const zip = await JSZip.loadAsync(buffer);
    const mpPath = 'MediaPool/Master/MpFolder.xml';
    const mp = await zip.file(mpPath).async('string');
    zip.file(mpPath, mp.split(`<Name>${MEDIA_TEMPLATE_TL_NAME}</Name>`).join(`<Name>${escapeXml(timelineName)}</Name>`));
    buffer = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
  }

  // Optionally trim the clip (video; linked audio left at template length).
  if (Number.isInteger(durationFrames) && durationFrames > 0) {
    ({ buffer } = await trimClip(buffer, { track: 1, clipIndex: 0, newDuration: durationFrames }));
  }

  return { buffer, timelineName: timelineName || MEDIA_TEMPLATE_TL_NAME, mediaFile };
}

module.exports = {
  createEmptyProject, addMediaClip, TEMPLATE_DRP, MEDIA_TEMPLATE_DRP, DEFAULT_TIMELINE_NAME, DEFAULT_START_FRAME,
};
