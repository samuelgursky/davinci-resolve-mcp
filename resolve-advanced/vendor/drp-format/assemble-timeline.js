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
const { loadMediaTemplate, transplantMediaElement } = require('./media-template-cache');
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
  if (media) {
    // Media authoring: ONE source file, cut into N placements — the template
    // media pool holds one media entry, so multi-source is refused honestly
    // rather than half-built.
    if (Array.isArray(media)) {
      throw new TypeError('assembleTimeline: media must be a single {mediaFilePath, spec, cuts} object — multi-source authoring is not supported yet');
    }
    const { mediaFilePath, spec: mediaSpec, cuts } = media;
    base = await addMediaClip({ mediaFile: mediaFilePath, spec: mediaSpec, timelineName, templateVersion });
    base.startFrame = DEFAULT_START_FRAME;
    if (Array.isArray(cuts) && cuts.length) {
      // Placement guards, loudly: clips before the timeline origin are
      // DROPPED by Resolve on import with no error, and a source range past
      // the media's end reads back as a truncated clip.
      cuts.forEach((cut, i) => {
        if (cut.startFrame < DEFAULT_START_FRAME) {
          throw new RangeError(
            `assembleTimeline: media.cuts[${i}].startFrame ${cut.startFrame} is before the timeline origin ${DEFAULT_START_FRAME} — Resolve silently drops it on import`,
          );
        }
        if (mediaSpec && Number.isFinite(mediaSpec.frameCount) && Number.isFinite(mediaSpec.fps)) {
          // srcIn/duration are TIMELINE frames (24fps template); the media's
          // extent converts: frameCount / mediaFps × 24.
          const maxTimelineFrames = Math.floor((mediaSpec.frameCount / mediaSpec.fps) * 24);
          if ((cut.srcIn ?? 0) + cut.durationFrames > maxTimelineFrames) {
            throw new RangeError(
              `assembleTimeline: media.cuts[${i}] reads past the media's end — (srcIn ?? 0) + durationFrames exceeds ${maxTimelineFrames} timeline frames (media ${mediaSpec.frameCount} frames @ ${mediaSpec.fps} fps on the 24fps template timeline)`,
            );
          }
        }
      });
      const cutRes = await cutSourceIntoClips(base.buffer, { cuts });
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

  // Native-descriptor transplant: when a live-captured media template exists
  // for this file, swap the pool media element and rewire MediaRefs — the
  // only measured way an authored timeline's media actually RENDERS (the
  // repoint fallback imports and reads back fine but the render engine
  // refuses or paints black; see media-template-cache).
  let mediaDescriptor = 'none';
  if (media && media.mediaFilePath) {
    const cached = loadMediaTemplate(media.mediaFilePath);
    if (cached) {
      const zip = await JSZip.loadAsync(buffer);
      const mpPath = 'MediaPool/Master/MpFolder.xml';
      const seqNames = Object.keys(zip.files).filter((n) => /SeqContainer\/.+\.xml$/.test(n) || /\/SeqContainer\d*\.xml$/.test(n));
      const mpXml = await zip.file(mpPath).async('string');
      const seqXmls = [];
      for (const n of seqNames) seqXmls.push(await zip.file(n).async('string'));
      const res = transplantMediaElement(mpXml, seqXmls, cached);
      zip.file(mpPath, res.mpXml);
      seqNames.forEach((n, i) => zip.file(n, res.seqXmls[i]));
      buffer = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
      mediaDescriptor = 'native-transplant';
    } else {
      mediaDescriptor = 'repoint-fallback';
    }
  }

  return { buffer, timelineName: tlName, startFrame, mediaDescriptor };
}

module.exports = { assembleTimeline };
