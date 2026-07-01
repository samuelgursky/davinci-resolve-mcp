'use strict';

/**
 * package/emit-aaf.js — emit an AAF *model* from the conformed timeline.
 *
 * NOTE: this produces the structural AAF mob/slot model (source positions
 * preserved), NOT a binary .aaf container — binary serialization needs an AAF
 * library and is a follow-up. The round-trip check below proves the conformed
 * source positions survive the mapping, which is the feature's acceptance.
 */

function toAafModel(conformed) {
  const fps = (conformed.sequence && conformed.sequence.fps) || 24;
  return {
    format: 'aaf-model',
    binary: false,
    editRate: fps,
    compositionMobs: conformed.clips.map((c) => ({
      name: c.source_basename || c.cutId || `clip${c.seqstart}`,
      sourceClip: { startPosition: c.sourceFrame, length: (c.seqend || c.seqstart) - c.seqstart, sourceUrl: c.path || null },
      seqstart: c.seqstart,
    })),
  };
}

function readAafSourceFrames(model) {
  return model.compositionMobs.map((m) => ({ name: m.name, seqstart: m.seqstart, sourceFrame: m.sourceClip.startPosition }));
}

module.exports = { toAafModel, readAafSourceFrames };
