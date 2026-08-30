/**
 * assemble-timeline — build a full, importable Resolve project from a declarative spec by
 * composing the verified primitives (createEmptyProject + placeFusionTitle / placeGenerator /
 * placeTransition). This supersedes the legacy from-spec `buildDRP`, which emits an invented
 * schema Resolve won't import.
 *
 * Spec:
 *   {
 *     timelineName?: string,
 *     elements?: [
 *       { type: 'title',     track, startFrame, durationFrames?, text?, font?, style?, size?,
 *                            color?, vJustify?, hJustify? },
 *       { type: 'generator', track, startFrame, durationFrames?, generatorName? },
 *     ],
 *     transitions?: [ { track, atFrame, durationFrames? } ],  // need two abutting clips at atFrame
 *   }
 *
 * Returns { buffer, timelineName, startFrame }. startFrame is the timeline origin (86400) — place
 * elements at >= it (clips before the origin are dropped by Resolve on import).
 *
 * @module drp-format/assemble-timeline
 */

const { createEmptyProject, addMediaClip, DEFAULT_START_FRAME } = require('./author-project');
const { loadMediaTemplate, transplantMediaElement, insertMediaElement } = require('./media-template-cache');
const JSZip = require('jszip');
const { cutSourceIntoClips } = require('./cut-media');
const { placeFusionTitle } = require('./place-fusion-title');
const { placeGenerator } = require('./place-generator');
const { placeTransition } = require('./place-transition');

async function assembleTimeline(spec = {}) {
  const { timelineName, elements = [], transitions = [], media, templateVersion } = spec;
  if (!Array.isArray(elements)) throw new TypeError('assembleTimeline: elements must be an array');
  if (!Array.isArray(transitions)) throw new TypeError('assembleTimeline: transitions must be an array');

  let base;
  let mediaDescriptorState = 'none';
  if (media) {
    // Media authoring: cut one or MORE sources into placements. Every source
    // carries {mediaFilePath, spec, cuts}. Multi-source requires a native
    // media template CAPTURED for every source (capture-once transplant is
    // the only measured way authored media renders); single-source may fall
    // back to descriptor repoint, which imports but usually will not render.
    const sources = Array.isArray(media) ? media : [media];
    if (!sources.length) throw new TypeError('assembleTimeline: media must not be empty');
    const caches = sources.map((src) => loadMediaTemplate(src.mediaFilePath));
    if (sources.length > 1) {
      const missing = sources.filter((src, i) => !caches[i]).map((src) => src.mediaFilePath);
      if (missing.length) {
        throw new Error(
          'assembleTimeline: multi-source authoring requires a captured native media template for EVERY source — ' +
          `missing for: ${missing.join(', ')}. Run media_pool.capture_media_template(path) with Resolve open for each.`,
        );
      }
    }
    const validateCuts = (src, label) => {
      const mediaSpec = src.spec;
      (src.cuts || []).forEach((cut, i) => {
        if (cut.startFrame < DEFAULT_START_FRAME) {
          throw new RangeError(
            `assembleTimeline: ${label}.cuts[${i}].startFrame ${cut.startFrame} is before the timeline origin ${DEFAULT_START_FRAME} — Resolve silently drops it on import`,
          );
        }
        if (mediaSpec && Number.isFinite(mediaSpec.frameCount) && Number.isFinite(mediaSpec.fps)) {
          // srcIn/duration are TIMELINE frames (24fps template); the media's
          // extent converts: frameCount / mediaFps × 24.
          const maxTimelineFrames = Math.floor((mediaSpec.frameCount / mediaSpec.fps) * 24);
          if ((cut.srcIn ?? 0) + cut.durationFrames > maxTimelineFrames) {
            throw new RangeError(
              `assembleTimeline: ${label}.cuts[${i}] reads past the media's end — (srcIn ?? 0) + durationFrames exceeds ${maxTimelineFrames} timeline frames (media ${mediaSpec.frameCount} frames @ ${mediaSpec.fps} fps on the 24fps template timeline)`,
            );
          }
        }
      });
    };
    sources.forEach((src, i) => validateCuts(src, sources.length > 1 ? `media[${i}]` : 'media'));

    base = await addMediaClip({
      mediaFile: sources[0].mediaFilePath, spec: sources[0].spec, timelineName, templateVersion,
    });
    base.startFrame = DEFAULT_START_FRAME;

    // Transplant/insert native pool elements BEFORE cutting, so each cut can
    // reference its source's MediaRef.
    let zip = await JSZip.loadAsync(base.buffer);
    const mpPath = 'MediaPool/Master/MpFolder.xml';
    let mpXml = await zip.file(mpPath).async('string');
    const seqNames = Object.keys(zip.files).filter((n) => /SeqContainer\/.+\.xml$/.test(n) || /\/SeqContainer\d*\.xml$/.test(n));
    const seqXmls = [];
    for (const n of seqNames) seqXmls.push(await zip.file(n).async('string'));
    const mediaRefs = [];
    if (caches[0]) {
      const res = transplantMediaElement(mpXml, seqXmls, caches[0]);
      mpXml = res.mpXml;
      for (let i = 0; i < seqNames.length; i += 1) seqXmls[i] = res.seqXmls[i];
      mediaRefs[0] = caches[0].mediaRef;
      mediaDescriptorState = 'native-transplant';
    } else {
      mediaRefs[0] = null; // donor already points at the repointed entry
      mediaDescriptorState = 'repoint-fallback';
    }
    for (let i = 1; i < sources.length; i += 1) {
      mpXml = insertMediaElement(mpXml, caches[i].poolElement);
      mediaRefs[i] = caches[i].mediaRef;
    }
    zip.file(mpPath, mpXml);
    seqNames.forEach((n, i) => zip.file(n, seqXmls[i]));
    base.buffer = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });

    const allCuts = [];
    sources.forEach((src, i) => {
      (src.cuts || []).forEach((cut) => {
        allCuts.push(mediaRefs[i] ? { ...cut, mediaRef: mediaRefs[i] } : { ...cut });
      });
    });
    allCuts.sort((a, b) => a.startFrame - b.startFrame);
    if (allCuts.length) {
      const cutRes = await cutSourceIntoClips(base.buffer, { cuts: allCuts });
      base.buffer = cutRes.buffer;
    }
  } else {
    base = await createEmptyProject({ timelineName, templateVersion });
  }
  const { buffer: baseBuffer, timelineName: tlName, startFrame } = base;
  let buffer = baseBuffer;

  for (const [i, el] of elements.entries()) {
    if (!el || typeof el !== 'object') throw new TypeError(`assembleTimeline: elements[${i}] must be an object`);
    if (el.type === 'title') {
      ({ buffer } = await placeFusionTitle(buffer, {
        trackIndex: el.track, startFrame: el.startFrame, durationFrames: el.durationFrames,
        text: el.text, font: el.font, style: el.style, size: el.size, color: el.color,
        vJustify: el.vJustify, hJustify: el.hJustify, name: el.name,
      }));
    } else if (el.type === 'generator') {
      ({ buffer } = await placeGenerator(buffer, {
        generatorName: el.generatorName, trackIndex: el.track,
        startFrame: el.startFrame, durationFrames: el.durationFrames,
      }));
    } else {
      throw new Error(`assembleTimeline: elements[${i}] unknown type "${el.type}" (title|generator)`);
    }
  }

  for (const [i, tr] of transitions.entries()) {
    if (!tr || typeof tr !== 'object') throw new TypeError(`assembleTimeline: transitions[${i}] must be an object`);
    ({ buffer } = await placeTransition(buffer, {
      track: tr.track, atFrame: tr.atFrame, durationFrames: tr.durationFrames,
    }));
  }

  return { buffer, timelineName: tlName, startFrame, mediaDescriptor: mediaDescriptorState };
}

module.exports = { assembleTimeline };
