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

const { createEmptyProject } = require('./author-project');
const { placeFusionTitle } = require('./place-fusion-title');
const { placeGenerator } = require('./place-generator');
const { placeTransition } = require('./place-transition');

async function assembleTimeline(spec = {}) {
  const { timelineName, elements = [], transitions = [] } = spec;
  if (!Array.isArray(elements)) throw new TypeError('assembleTimeline: elements must be an array');
  if (!Array.isArray(transitions)) throw new TypeError('assembleTimeline: transitions must be an array');

  const { buffer: base, timelineName: tlName, startFrame } = await createEmptyProject({ timelineName });
  let buffer = base;

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

  return { buffer, timelineName: tlName, startFrame };
}

module.exports = { assembleTimeline };
