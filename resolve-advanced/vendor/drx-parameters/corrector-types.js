/**
 * DRX Corrector Type Definitions
 *
 * Correctors are the building blocks of DaVinci Resolve color nodes.
 * Each corrector type controls a specific aspect of the grade.
 *
 * @module drx-parameters/corrector-types
 */

/**
 * Corrector type identifiers used in DRX protobuf format
 */
const CORRECTOR_TYPES = {
  PRIMARY: 1,           // Lift/Gamma/Gain/Offset/Saturation/Temp/Tint/Curves/HDR/RGBMixer/ColorWarper
  QUALIFIER: 2,         // HSL/RGB/Luma/3D Qualifier (0x0830xxxx range) — was 'CONTRAST'
  WINDOW_SOFTNESS: 3,   // Power Window softness mask shape (0x0870xxxx) — was 'SATURATION'
  POWER_WINDOW: 4,      // Power Window position/size/type (0x0850xxxx) — was 'HUE'
  LUM_MIX: 5,           // Luma vs Saturation curves
  OFFSET: 6,            // Offset corrector
  MATTE_FINESSE: 9,     // Matte Finesse (0x0C30002x) + KEY palette (0x0C30001x) — was 'HDR_ZONE'
  MOTION_EFFECTS: 15,   // Motion Effects palette: spatial/temporal NR + motion blur (0x0C4000xx) — measured 2026-07-02
  CURVES: 18,           // RGB/Luma custom curves (legacy)

  // Backwards compatibility aliases
  CONTRAST: 2,          // @deprecated — use QUALIFIER
  SATURATION: 3,        // @deprecated — use WINDOW_SOFTNESS
  HUE: 4,               // @deprecated — use POWER_WINDOW
  HDR_ZONE: 9,          // @deprecated — use MATTE_FINESSE

  // High-bit compound types — window shape variants (discovered 2026-03-22)
  LINEAR_WINDOW: 0x10003,   // 65539 — Linear window softness shape (0x10000 + 3)
  GRADIENT_WINDOW: 0x10012, // 65554 — Gradient window shape (0x10000 + 18)

  // High-bit compound types (Magic Mask / Object Mask)
  MAGIC_MASK: 0x10001,  // 0x10000 + base type 1 (Primary)
  OBJECT_MASK: 0x20001,  // 0x20000 + base type 1 (Primary)
};

/**
 * Human-readable names for corrector types
 * CORRECTED 2026-03-22: Types 2/3/4/9 were misidentified before the March 16 calibration.
 */
const CORRECTOR_NAMES = {
  [CORRECTOR_TYPES.PRIMARY]: 'Primary',
  [CORRECTOR_TYPES.QUALIFIER]: 'Qualifier',
  [CORRECTOR_TYPES.WINDOW_SOFTNESS]: 'WindowSoftness',
  [CORRECTOR_TYPES.POWER_WINDOW]: 'PowerWindow',
  [CORRECTOR_TYPES.LUM_MIX]: 'LumMix',
  [CORRECTOR_TYPES.OFFSET]: 'Offset',
  [CORRECTOR_TYPES.MATTE_FINESSE]: 'MatteFinesse',
  [CORRECTOR_TYPES.MOTION_EFFECTS]: 'MotionEffects',
  [CORRECTOR_TYPES.CURVES]: 'Curves',
  [CORRECTOR_TYPES.LINEAR_WINDOW]: 'LinearWindow',
  [CORRECTOR_TYPES.GRADIENT_WINDOW]: 'GradientWindow',
  [CORRECTOR_TYPES.MAGIC_MASK]: 'MagicMask',
  [CORRECTOR_TYPES.OBJECT_MASK]: 'ObjectMask',
};

/**
 * Presence marker IDs required for Resolve to recognize corrector types.
 * These are written to the F2 presence list in the protobuf.
 */
const PRESENCE_MARKER_IDS = {
  [CORRECTOR_TYPES.CONTRAST]: 0x88300001,
  [CORRECTOR_TYPES.SATURATION]: 0x8870001e,
  [CORRECTOR_TYPES.HUE]: 0x88500010,
  [CORRECTOR_TYPES.LUM_MIX]: 0x88b00012,
  [CORRECTOR_TYPES.OFFSET]: 0x88d00014,
  [CORRECTOR_TYPES.CURVES]: 0x88f0000d,
};

/**
 * Get the name for a corrector type
 * @param {number} type - Corrector type ID
 * @returns {string} Human-readable name or "Type{id}" for unknown types
 */
function getCorrectorName(type) {
  return CORRECTOR_NAMES[type] || `Type${type}`;
}

/**
 * Get presence marker ID for a corrector type
 * @param {number} type - Corrector type ID
 * @returns {number|null} Presence marker ID or null if not applicable
 */
function getPresenceMarker(type) {
  return PRESENCE_MARKER_IDS[type] || null;
}

/**
 * Check if a corrector type uses full parameter blocks
 * (vs. presence marker only)
 * @param {number} type - Corrector type ID
 * @returns {boolean}
 */
function hasFullParameterBlock(type) {
  return type === CORRECTOR_TYPES.PRIMARY ||
         type === CORRECTOR_TYPES.QUALIFIER ||
         type === CORRECTOR_TYPES.POWER_WINDOW ||
         type === CORRECTOR_TYPES.WINDOW_SOFTNESS ||
         type === CORRECTOR_TYPES.MATTE_FINESSE;
}

/**
 * Get all supported corrector types
 * @returns {number[]}
 */
function getAllCorrectorTypes() {
  return Object.values(CORRECTOR_TYPES);
}

module.exports = {
  CORRECTOR_TYPES,
  CORRECTOR_NAMES,
  PRESENCE_MARKER_IDS,
  getCorrectorName,
  getPresenceMarker,
  hasFullParameterBlock,
  getAllCorrectorTypes,
};
