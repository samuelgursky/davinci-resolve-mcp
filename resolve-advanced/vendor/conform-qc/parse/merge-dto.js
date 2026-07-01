'use strict';

/**
 * parse/merge-dto.js — merge captured geometry onto editorial-core's normalized
 * DTO clips ADDITIVELY, behind a flag (spec §13 P0). A wrapper (per the feature:
 * "editorial-core parse OR a wrapper") so editorial-core stays untouched and
 * un-regressed: with the flag off the DTO is returned byte-identical; with it on,
 * a `conformGeometry` field is attached per clip, keyed by seqstart.
 */

/**
 * @param {object[]} dtoClips        editorial-core DTO clips (must carry a start/seqstart key)
 * @param {object[]} geometryClips   captured geometry (parse/xmeml-geometry output)
 * @param {object} opts { attach (bool, default false), keyOf }
 * @returns {object[]} the DTO clips (unchanged when !attach; geometry attached when attach)
 */
function mergeGeometry(dtoClips, geometryClips, opts = {}) {
  if (!opts.attach) return dtoClips; // flag off: base DTO untouched (no regressions)
  const keyOf = opts.keyOf || ((c) => (c.seqstart != null ? c.seqstart : c.start));
  const geoBy = new Map(geometryClips.map((g) => [keyOf(g), g]));
  return dtoClips.map((c) => {
    const g = geoBy.get(keyOf(c));
    return g ? { ...c, conformGeometry: g } : { ...c };
  });
}

module.exports = { mergeGeometry };
