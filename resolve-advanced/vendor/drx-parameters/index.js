/**
 * DRX Parameter Library
 *
 * Unified parameter definitions, encoding, and validation for
 * DaVinci Resolve's DRX grade format.
 *
 * This library provides a single source of truth for:
 * - Parameter IDs and mappings
 * - Value ranges and defaults
 * - Protobuf encoding/decoding
 * - Validation and correction
 *
 * Used across the The project platform for consistent DRX handling.
 *
 * @module drx-parameters
 *
 * @example
 * const drx = require('drx-parameters');
 *
 * // Get parameter info
 * const info = drx.getParamInfo(100663320); // { control: 'lift', channel: 'r' }
 *
 * // Validate parameters
 * const result = drx.validateAll({ lift: { r: 0.5 } });
 *
 * // Encode for DRX
 * const buffer = drx.encodeParameters({ [drx.LIFT.R]: 0.5 });
 */

// Import all modules
const correctorTypes = require('./corrector-types');
const parameterIds = require('./parameter-ids');
const parameterRanges = require('./parameter-ranges');
const parameterCodec = require('./parameter-codec');
const parameterValidator = require('./parameter-validator');

// Re-export everything
module.exports = {
  // ========================================================================
  // Corrector Types
  // ========================================================================
  CORRECTOR_TYPES: correctorTypes.CORRECTOR_TYPES,
  CORRECTOR_NAMES: correctorTypes.CORRECTOR_NAMES,
  PRESENCE_MARKER_IDS: correctorTypes.PRESENCE_MARKER_IDS,
  getCorrectorName: correctorTypes.getCorrectorName,
  getPresenceMarker: correctorTypes.getPresenceMarker,
  hasFullParameterBlock: correctorTypes.hasFullParameterBlock,
  getAllCorrectorTypes: correctorTypes.getAllCorrectorTypes,

  // ========================================================================
  // Parameter IDs
  // ========================================================================
  LIFT: parameterIds.LIFT,
  GAIN: parameterIds.GAIN,
  GAMMA: parameterIds.GAMMA,
  OFFSET: parameterIds.OFFSET,
  SATURATION: parameterIds.SATURATION,
  TEMP_TINT: parameterIds.TEMP_TINT,
  CONTRAST: parameterIds.CONTRAST,
  LOG_WHEELS: parameterIds.LOG_WHEELS,
  HUE: parameterIds.HUE,
  LUM_MIX: parameterIds.LUM_MIX,
  SAT_VS_SAT: parameterIds.SAT_VS_SAT,
  HDR_ZONE: parameterIds.HDR_ZONE,
  CURVES: parameterIds.CURVES,
  RGB_MIXER: parameterIds.RGB_MIXER,
  CUSTOM_CURVES: parameterIds.CUSTOM_CURVES,
  HSL_CURVES: parameterIds.HSL_CURVES,
  ADDITIONAL: parameterIds.ADDITIONAL,
  HSL_QUALIFIER: parameterIds.HSL_QUALIFIER,
  MATTE_FINESSE: parameterIds.MATTE_FINESSE,
  POWER_WINDOWS: parameterIds.POWER_WINDOWS,
  GRADIENT_WINDOW: parameterIds.GRADIENT_WINDOW,
  POLYGON_WINDOW: parameterIds.POLYGON_WINDOW,
  COLOR_WARPER: parameterIds.COLOR_WARPER,
  NODE_LUT_REF: parameterIds.NODE_LUT_REF,
  COLORSLICE: parameterIds.COLORSLICE,
  BLUR_PALETTE: parameterIds.BLUR_PALETTE,
  KEY_PALETTE: parameterIds.KEY_PALETTE,
  MOTION_EFFECTS: parameterIds.MOTION_EFFECTS,
  RESOLVEFX: parameterIds.RESOLVEFX,
  PARAM_ID_MAP: parameterIds.PARAM_ID_MAP,
  getParamInfo: parameterIds.getParamInfo,
  getParamIdsForControl: parameterIds.getParamIdsForControl,
  isKnownParam: parameterIds.isKnownParam,
  getKnownParamCount: parameterIds.getKnownParamCount,

  // ========================================================================
  // Parameter Ranges
  // ========================================================================
  PARAMETER_RANGES: parameterRanges.PARAMETER_RANGES,
  VISUAL_IMPACT_WEIGHTS: parameterRanges.VISUAL_IMPACT_WEIGHTS,
  getRange: parameterRanges.getRange,
  getDefault: parameterRanges.getDefault,
  clamp: parameterRanges.clamp,
  normalize: parameterRanges.normalize,
  denormalize: parameterRanges.denormalize,
  isDefault: parameterRanges.isDefault,
  formatValue: parameterRanges.formatValue,
  getAllDefaults: parameterRanges.getAllDefaults,
  getVisualImpactWeight: parameterRanges.getVisualImpactWeight,

  // ========================================================================
  // Parameter Codec
  // ========================================================================
  // Protobuf primitives
  encodeVarint: parameterCodec.encodeVarint,
  decodeVarint: parameterCodec.decodeVarint,
  encodeSignedVarint: parameterCodec.encodeSignedVarint,
  decodeSignedVarint: parameterCodec.decodeSignedVarint,
  encodeFloat32: parameterCodec.encodeFloat32,
  decodeFloat32: parameterCodec.decodeFloat32,
  encodeFixed32: parameterCodec.encodeFixed32,
  decodeFixed32: parameterCodec.decodeFixed32,
  encodeFixed64: parameterCodec.encodeFixed64,
  decodeFixed64: parameterCodec.decodeFixed64,
  encodeLengthDelimited: parameterCodec.encodeLengthDelimited,

  // Field encoding
  WIRE_TYPES: parameterCodec.WIRE_TYPES,
  encodeFieldTag: parameterCodec.encodeFieldTag,
  decodeFieldTag: parameterCodec.decodeFieldTag,

  // Parameter encoding
  encodeParameter: parameterCodec.encodeParameter,
  encodeParameters: parameterCodec.encodeParameters,
  semanticToRaw: parameterCodec.semanticToRaw,
  rawToSemantic: parameterCodec.rawToSemantic,

  // Merging
  MERGE_STRATEGIES: parameterCodec.MERGE_STRATEGIES,
  getMergeStrategy: parameterCodec.getMergeStrategy,
  mergeNodeParams: parameterCodec.mergeNodeParams,

  // ========================================================================
  // Parameter Validation
  // ========================================================================
  SEVERITY: parameterValidator.SEVERITY,
  PROFESSIONAL_LIMITS: parameterValidator.PROFESSIONAL_LIMITS,
  BROADCAST_LIMITS: parameterValidator.BROADCAST_LIMITS,
  ValidationResult: parameterValidator.ValidationResult,
  validateParameter: parameterValidator.validateParameter,
  validateProfessional: parameterValidator.validateProfessional,
  validateBroadcast: parameterValidator.validateBroadcast,
  validateAll: parameterValidator.validateAll,
  autoCorrect: parameterValidator.autoCorrect,
  hasActualGrade: parameterValidator.hasActualGrade,
  getAdjustmentSummary: parameterValidator.getAdjustmentSummary,
  calculateImpactScore: parameterValidator.calculateImpactScore,

  // ========================================================================
  // Convenience Constants
  // ========================================================================

  /**
   * Total count of known parameter IDs
   */
  TOTAL_KNOWN_PARAMS: parameterIds.getKnownParamCount(),

  /**
   * Version of this library
   */
  VERSION: '1.0.0',

  // ========================================================================
  // ResolveFX plugin registry (full 105-plugin universe, built 2026-07-03)
  // ========================================================================

  /**
   * The complete ResolveFX plugin universe for Resolve 19.1.3, with param/enum
   * CANDIDATES from a binary factory-block scan and EXACT `paramsObserved` decoded
   * from real project grades. Decode does NOT need this (OFX params are
   * self-describing on the wire) — it assists authoring/enum lookup.
   */
  RESOLVEFX_REGISTRY: require('./resolvefx-registry.json'),

  /**
   * Look up a ResolveFX registry entry by wire id, full plugin id, or short name
   * (case-insensitive). Returns null when unknown.
   */
  lookupResolveFX(idOrName) {
    const reg = module.exports.RESOLVEFX_REGISTRY;
    if (!idOrName) return null;
    const q = String(idOrName).toLowerCase();
    const short = q.replace('com.blackmagicdesign.resolvefx.', '');
    if (reg[short] && reg[short].wireId) return reg[short];
    for (const [k, v] of Object.entries(reg)) {
      if (k === '_meta' || !v.wireId) continue;
      if (v.wireId === q || (v.pluginId && v.pluginId.toLowerCase() === q) || k === short) return v;
    }
    return null;
  },
};
