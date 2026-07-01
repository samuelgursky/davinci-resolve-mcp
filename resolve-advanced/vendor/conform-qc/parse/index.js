'use strict';

/**
 * parse/ — turnover -> captured conform geometry (spec §3.1, §4).
 *
 * XMEML (Premiere FCP7 XML) is the v1 format and is fully implemented in
 * xmeml-geometry.js. AAF and OTIO are stubbed: they MUST eventually return the
 * same captured-geometry shape so the Oracle/compare/repair layers are
 * format-agnostic. The stubs throw clearly so a caller never silently gets
 * empty data, and they document the shared contract.
 */

const { parseGeometry } = require('./xmeml-geometry');

/**
 * The captured-geometry contract every format parser must satisfy:
 *   parse(input, opts?) -> {
 *     sequence: { name, width, height, fps },
 *     clips: [{
 *       seqstart, seqend, xml_in, xml_out, pproTicksIn, pproTicksOut,
 *       is_subclip, subclip_startoffset, scale_premiere, speed,
 *       center, rotation, crop, fileId, source_basename, srcW, srcH
 *     }]
 *   }
 * Keyed by clip (seqstart) with file-ids resolved first (non-negotiable #6).
 */
const CAPTURED_CLIP_FIELDS = Object.freeze([
  'seqstart', 'seqend', 'xml_in', 'xml_out', 'pproTicksIn', 'pproTicksOut',
  'is_subclip', 'subclip_startoffset', 'scale_premiere', 'speed',
  'center', 'rotation', 'crop', 'fileId', 'source_basename', 'srcW', 'srcH',
]);

/** AAF geometry capture — stub (conforms to the parse() signature). */
function parseGeometryAAF() {
  throw new Error(
    'conform-qc parse: AAF geometry capture not implemented — XMEML is the v1 ' +
      'target; AAF must parse to the same captured-geometry shape (CAPTURED_CLIP_FIELDS).',
  );
}

/** OTIO geometry capture — stub (OTIO is the internal canonical format). */
function parseGeometryOTIO() {
  throw new Error(
    'conform-qc parse: OTIO geometry capture not implemented — OTIO is the ' +
      'internal canonical format; full capture lands later (CAPTURED_CLIP_FIELDS).',
  );
}

module.exports = {
  CAPTURED_CLIP_FIELDS,
  parseGeometry, // XMEML (implemented)
  parseGeometryAAF, // stub
  parseGeometryOTIO, // stub
};
