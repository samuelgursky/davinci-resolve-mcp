/**
 * DRT builder — package a timeline-only Resolve archive.
 *
 * DRT and DRP share the SeqContainer/MpFolder schema; the only on-disk
 * difference is that DRT has no project.xml. This module reuses
 * drp-format's packageFullDRP with includeProjectXml: false.
 *
 * Spec shape — same as buildDRP minus the project shell:
 *   {
 *     timelines: [{
 *       name, frameRate, startTimecode, resolution,
 *       videoTracks, audioTracks, markers
 *     }],
 *     mediaPool: object | null,
 *     metadata: object,
 *   }
 *
 * Returns a Buffer ready to write as a .drt file.
 *
 * @module drt-format/drt-builder
 */

const drpFormat = require('../drp-format');

async function buildDRT(spec = {}) {
  if (!spec || typeof spec !== 'object') {
    throw new TypeError('buildDRT: spec must be an object');
  }
  if (!Array.isArray(spec.timelines) || spec.timelines.length === 0) {
    throw new TypeError('buildDRT: spec.timelines must contain at least one timeline');
  }

  return drpFormat.packager.packageFullDRP({
    // projectXml omitted; includeProjectXml: false skips its zip entry.
    includeProjectXml: false,
    timelines: spec.timelines,
    mediaPool: spec.mediaPool || null,
    metadata: spec.metadata || {},
  });
}

module.exports = { buildDRT };
