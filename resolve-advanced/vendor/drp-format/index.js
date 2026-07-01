/**
 * DaVinci Resolve Project (DRP) Generator
 *
 * This module provides utilities for generating DaVinci Resolve Project files (.drp)
 * with support for timelines, media pools, color grades, effects, markers, and project settings.
 *
 * Includes comprehensive encoding/decoding for:
 * - Grade parameters (color wheels, adjustments)
 * - Node trees (serial, parallel, layer mixers)
 * - Custom curves (RGB, Hue vs Sat/Lum, etc.)
 * - Qualifiers (HSL, luminance, 3D)
 * - Power windows (circle, linear, polygon, curve)
 *
 * @module drp-generator
 */

const xmlBuilder = require('./xml-builder');
const gradeEncoder = require('./grade-encoder');
const drpPackager = require('./drp-packager');
const effectEncoder = require('./effect-encoder');
const markerEncoder = require('./marker-encoder');
const injectGradesModule = require('./inject-grades');
const diffModule = require('./diff');
const extractLutRefsModule = require('./extract-lut-refs');

/**
 * High-level convenience: build a full DRP buffer from a spec.
 *
 * Spec shape:
 *   {
 *     projectName: string,
 *     projectSettings: object,  // → buildProjectXml input
 *     timelines: [{ name, frameRate, startTimecode, resolution,
 *                   videoTracks, audioTracks, markers }],
 *     mediaPool: object | null,
 *     metadata: object,
 *   }
 *
 * Returns a Buffer ready to write to disk as a .drp file.
 */
async function buildDRP(spec = {}) {
  const projectSettings = {
    projectName: spec.projectName || 'Untitled Project',
    ...(spec.projectSettings || {}),
  };
  const projectXml = xmlBuilder.buildProjectXml(projectSettings);
  return drpPackager.packageFullDRP({
    projectXml,
    timelines: spec.timelines || [],
    mediaPool: spec.mediaPool || null,
    metadata: {
      projectName: projectSettings.projectName,
      ...(spec.metadata || {}),
    },
  });
}

// Advanced grade encoding/decoding modules
const gradeParameterDecoder = require('./grade-parameter-decoder');
const nodeTreeEncoder = require('./node-tree-encoder');
const curvesEncoder = require('./curves-encoder');
const qualifierEncoder = require('./qualifier-encoder');
const powerWindowEncoder = require('./power-window-encoder');

module.exports = {
  // XML Builder functions
  ...xmlBuilder,

  // Grade Encoder functions
  ...gradeEncoder,

  // DRP Packager functions
  ...drpPackager,

  // Effect Encoder functions
  ...effectEncoder,

  // Marker Encoder functions
  ...markerEncoder,

  // Grade Parameter Decoder functions
  ...gradeParameterDecoder,

  // Node Tree Encoder functions
  ...nodeTreeEncoder,

  // Curves Encoder functions
  ...curvesEncoder,

  // Qualifier Encoder functions
  ...qualifierEncoder,

  // Power Window Encoder functions
  ...powerWindowEncoder,

  // High-level convenience entry point
  buildDRP,

  // Grade injection into an existing DRP (P0.1)
  injectGrades: injectGradesModule.injectGrades,

  // Structural diff of two DRPs (P0.2)
  diff: diffModule.diff,

  // Diff module internals — exposed so the MCP extract_node_graphs
  // action can walk the clip index without duplicating the SeqContainer
  // walker. Not part of the supported public API; subject to change.
  diffInternals: diffModule._internals,

  // Project-level LUT reference extraction (P5.2 — clf-lut-bridge)
  extractProjectLUTRefs: extractLutRefsModule.extractProjectLUTRefs,
  LUT_RECOGNIZED_SLOTS: extractLutRefsModule.RECOGNIZED_SLOTS,

  // Place a Fusion Title (Text+) on a chosen video track — the #74 track-targeting
  // bypass (clone-based; carries a real CompositionBA verbatim).
  placeFusionTitle: require('./place-fusion-title').placeFusionTitle,

  // Place a built-in generator (Solid Color, etc.) on a chosen video track.
  placeGenerator: require('./place-generator').placeGenerator,

  // Insert a cross-dissolve between two abutting clips (the one op the Resolve API can't do).
  placeTransition: require('./place-transition').placeTransition,

  // Read/replace a Fusion Title's text + style (font/size/justify) inside a CompositionBA blob.
  decodeTitleText: require('./composition-text').decodeTitleText,

  // Fixed-size Media Pool/timeline metadata blobs (Resolution/FrameRate/MediaFrameRate/MediaExtents).
  mediaBlobs: require('./media-blobs'),
  // Reader for the Media Pool keyed-dict metadata blobs (Geometry/Time/VideoMetadata/Proxy).
  keyedDict: require('./keyed-dict'),
  // Per-clip retime/speed map (MediaTimemapBA) — [u8 type][BE float64 seconds].
  mediaTimemap: require('./media-timemap'),
  // Generic protobuf wire codec for Radiometry / EffectFiltersBA / protobuf FieldsBlob.
  protobufWire: require('./protobuf-wire'),
  setTitleText: require('./composition-text').setTitleText,
  setTitleInputs: require('./composition-text').setTitleInputs,
  decodeTitleInputs: require('./composition-text').decodeTitleInputs,

  // In-place clip edits (move/delete/trim, optional track-scoped ripple) — generalizes #74.
  moveClip: require('./splice-clips').moveClip,
  deleteClip: require('./splice-clips').deleteClip,
  trimClip: require('./splice-clips').trimClip,
  trimClipHead: require('./splice-clips').trimClipHead,
  splitClip: require('./splice-clips').splitClip,
  rippleTimeline: require('./splice-clips').rippleTimeline,

  // Create a fresh, importable Resolve project (one empty timeline) from a bundled template.
  createEmptyProject: require('./author-project').createEmptyProject,

  // Build a full importable timeline from a declarative spec (titles/generators/transitions).
  assembleTimeline: require('./assemble-timeline').assembleTimeline,

  // Author a project with one media clip referencing an arbitrary h264 file, from scratch [P8].
  addMediaClip: require('./author-project').addMediaClip,

  // Offline media relink — repoint media to new paths in the Media Pool blobs (no Resolve).
  relinkMedia: require('./relink-media').relinkMedia,
  // Relink + fix cached specs (resolution/frames/fps) for a differently-formatted file [P8].
  repointMedia: require('./relink-media').repointMedia,

  // Convenience re-exports for common operations
  xml: xmlBuilder,
  grade: gradeEncoder,
  packager: drpPackager,
  effect: effectEncoder,
  marker: markerEncoder,

  // Advanced encoding/decoding modules
  gradeDecoder: gradeParameterDecoder,
  nodeTree: nodeTreeEncoder,
  curves: curvesEncoder,
  qualifier: qualifierEncoder,
  window: powerWindowEncoder,
};
