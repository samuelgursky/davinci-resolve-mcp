/**
 * DRX Parameter Value Ranges and Defaults
 *
 * Defines valid ranges, default values, and normalization rules
 * for all DRX parameters.
 *
 * @module drx-parameters/parameter-ranges
 */

/**
 * Parameter range definitions
 *
 * Each entry defines:
 * - min: Minimum valid value
 * - max: Maximum valid value
 * - default: Default/neutral value
 * - unit: Unit of measurement (optional)
 * - precision: Decimal places for display (optional)
 */
const PARAMETER_RANGES = {
  // ========================================================================
  // Color Wheels - Lift (Shadows)
  // ========================================================================
  lift: {
    r: { min: -1.0, max: 1.0, default: 0.0, precision: 3 },
    g: { min: -1.0, max: 1.0, default: 0.0, precision: 3 },
    b: { min: -1.0, max: 1.0, default: 0.0, precision: 3 },
    master: { min: -1.0, max: 1.0, default: 0.0, precision: 3 },
  },

  // ========================================================================
  // Color Wheels - Gamma (Midtones)
  // ========================================================================
  gamma: {
    r: { min: -1.0, max: 1.0, default: 0.0, precision: 3 },
    g: { min: -1.0, max: 1.0, default: 0.0, precision: 3 },
    b: { min: -1.0, max: 1.0, default: 0.0, precision: 3 },
    master: { min: -1.0, max: 1.0, default: 0.0, precision: 3 },
  },

  // ========================================================================
  // Color Wheels - Gain (Highlights)
  // ========================================================================
  gain: {
    r: { min: 0.0, max: 4.0, default: 1.0, precision: 3 },
    g: { min: 0.0, max: 4.0, default: 1.0, precision: 3 },
    b: { min: 0.0, max: 4.0, default: 1.0, precision: 3 },
    master: { min: 0.0, max: 4.0, default: 1.0, precision: 3 },
  },

  // ========================================================================
  // Color Wheels - Offset
  // ========================================================================
  offset: {
    r: { min: -1.0, max: 1.0, default: 0.0, precision: 3 },
    g: { min: -1.0, max: 1.0, default: 0.0, precision: 3 },
    b: { min: -1.0, max: 1.0, default: 0.0, precision: 3 },
  },

  // ========================================================================
  // Primary Adjustments
  // ========================================================================
  saturation: {
    master: { min: 0, max: 100, default: 50, precision: 0 },
    primary: { min: 0.0, max: 4.0, default: 1.0, precision: 3, note: 'DRX float: UI/50' },
  },

  temperature: {
    master: { min: -4000, max: 4000, default: 0, unit: 'offset', precision: 0 },
  },

  tint: {
    master: { min: -100, max: 100, default: 0, precision: 0 },
  },

  midtoneDetail: {
    master: { min: -100, max: 100, default: 0, precision: 0 },
  },

  // ========================================================================
  // Contrast Corrector
  // ========================================================================
  contrast: {
    master: { min: 0.0, max: 2.0, default: 1.0, precision: 2 },
  },

  pivot: {
    master: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
  },

  pivotFine: {
    master: { min: 0.0, max: 1.0, default: 0.435, precision: 3 },
  },

  highRange: {
    master: { min: 0.0, max: 1.0, default: 0.75, precision: 2 },
  },

  lowRange: {
    master: { min: 0.0, max: 1.0, default: 0.25, precision: 2 },
  },

  softClipHigh: {
    master: { min: 0.0, max: 1.0, default: 1.0, precision: 2 },
  },

  softClipLow: {
    master: { min: 0.0, max: 1.0, default: 0.0, precision: 2 },
  },

  // ========================================================================
  // Log Wheels Mode
  // ========================================================================
  logShadow: {
    r: { min: -1.0, max: 1.0, default: 0.0, precision: 3 },
    g: { min: -1.0, max: 1.0, default: 0.0, precision: 3 },
    b: { min: -1.0, max: 1.0, default: 0.0, precision: 3 },
    master: { min: -1.0, max: 1.0, default: 0.0, precision: 3 },
  },

  logMidtone: {
    r: { min: -1.0, max: 1.0, default: 0.0, precision: 3 },
    g: { min: -1.0, max: 1.0, default: 0.0, precision: 3 },
    b: { min: -1.0, max: 1.0, default: 0.0, precision: 3 },
  },

  logHighlight: {
    r: { min: -1.0, max: 1.0, default: 0.0, precision: 3 },
    g: { min: -1.0, max: 1.0, default: 0.0, precision: 3 },
    b: { min: -1.0, max: 1.0, default: 0.0, precision: 3 },
  },

  // ========================================================================
  // Hue Corrector (Type 4) - Ranges TBD through testing
  // ========================================================================
  hue: {
    param1: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
    param2: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
    param3: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
    param4: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
    param5: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
    param6: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
  },

  // ========================================================================
  // Luma vs Saturation (Type 5) - Ranges TBD through testing
  // ========================================================================
  lumMix: {
    param1: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
    param2: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
    param3: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
    param4: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
    param5: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
    param6: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
    param7: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
    param8: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
    param9: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
    param10: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
    param11: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
  },

  // ========================================================================
  // Saturation vs Saturation — RANGES REMOVED 2026-07-01.
  // The satVsSat.param1–7 id mapping (0x08F000xx) is VESTIGIAL: the real Sat-vs-Sat
  // curve writes the hslCurves spline 0x86000404 (see satvssat-curve-calibration),
  // and 0x08F000xx are the GRADIENT WINDOW's ids (ct65554: rotation ±, handles ±4096,
  // softness ×100). The old [0,1] guesses here made createParameterEntry clamp real
  // gradient-window writes to garbage. No ranges → clamp-free pass-through.
  // ========================================================================

  // ========================================================================
  // HDR Global Controls - TRAINED 2026-03-16
  // ========================================================================
  hdrBlackOffset: {
    master: { min: -1.0, max: 1.0, default: 0.0, precision: 3 },
  },

  // HDR Zone (Type 9) - Ranges TBD through testing
  // ========================================================================
  hdrZone: {
    param1: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
  },

  // ========================================================================
  // Curves (Type 18) - Ranges TBD through testing
  // ========================================================================
  curves: {
    param1: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
    param2: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
    param3: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
    param4: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
    param5: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
    param6: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
    param7: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
    param8: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
    param9: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
    param10: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
    param11: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
    param12: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
    param13: { min: 0.0, max: 1.0, default: 0.5, precision: 3 },
  },

  // ========================================================================
  // HDR Wheels (Zone-based grading) - TRAINED 2026-01-14, UPDATED 2026-03-16
  // Zone adjustments: Uses nested protobuf (0x86000305) with zone name strings
  // Zone definitions: Uses nested protobuf (0x86000306) with range + falloff
  // Color Balance uses X/Y (not hueAngle/hueSat as previously labeled)
  // Default falloffs are symmetric: Black/Specular=0.10, Dark/Highlight=0.20, Shadow/Light=0.22
  // ========================================================================
  hdrBlack: {
    exposure: { min: -6.0, max: 6.0, default: 0.0, unit: 'stops', precision: 2 },
    saturation: { min: 0.0, max: 4.0, default: 1.0, precision: 2 },
    colorBalanceX: { min: -1.0, max: 1.0, default: 0.0, precision: 2 },
    colorBalanceY: { min: -1.0, max: 1.0, default: 0.0, precision: 2 },
    falloff: { min: 0.0, max: 2.0, default: 0.10, precision: 2 },
  },
  hdrDark: {
    exposure: { min: -6.0, max: 6.0, default: 0.0, unit: 'stops', precision: 2 },
    saturation: { min: 0.0, max: 4.0, default: 1.0, precision: 2 },
    colorBalanceX: { min: -1.0, max: 1.0, default: 0.0, precision: 2 },
    colorBalanceY: { min: -1.0, max: 1.0, default: 0.0, precision: 2 },
    falloff: { min: 0.0, max: 2.0, default: 0.20, precision: 2 },
  },
  hdrShadow: {
    exposure: { min: -6.0, max: 6.0, default: 0.0, unit: 'stops', precision: 2 },
    saturation: { min: 0.0, max: 4.0, default: 1.0, precision: 2 },
    colorBalanceX: { min: -1.0, max: 1.0, default: 0.0, precision: 2 },
    colorBalanceY: { min: -1.0, max: 1.0, default: 0.0, precision: 2 },
    falloff: { min: 0.0, max: 2.0, default: 0.22, precision: 2 },
  },
  hdrLight: {
    exposure: { min: -6.0, max: 6.0, default: 0.0, unit: 'stops', precision: 2 },
    saturation: { min: 0.0, max: 4.0, default: 1.0, precision: 2 },
    colorBalanceX: { min: -1.0, max: 1.0, default: 0.0, precision: 2 },
    colorBalanceY: { min: -1.0, max: 1.0, default: 0.0, precision: 2 },
    falloff: { min: 0.0, max: 2.0, default: 0.22, precision: 2 },
  },
  hdrHighlight: {
    exposure: { min: -6.0, max: 6.0, default: 0.0, unit: 'stops', precision: 2 },
    saturation: { min: 0.0, max: 4.0, default: 1.0, precision: 2 },
    colorBalanceX: { min: -1.0, max: 1.0, default: 0.0, precision: 2 },
    colorBalanceY: { min: -1.0, max: 1.0, default: 0.0, precision: 2 },
    falloff: { min: 0.0, max: 2.0, default: 0.20, precision: 2 },
  },
  hdrSpecular: {
    exposure: { min: -6.0, max: 6.0, default: 0.0, unit: 'stops', precision: 2 },
    saturation: { min: 0.0, max: 4.0, default: 1.0, precision: 2 },
    colorBalanceX: { min: -1.0, max: 1.0, default: 0.0, precision: 2 },
    colorBalanceY: { min: -1.0, max: 1.0, default: 0.0, precision: 2 },
    falloff: { min: 0.0, max: 2.0, default: 0.10, precision: 2 },
  },
  hdrGlobal: {
    exposure: { min: -6.0, max: 6.0, default: 0.0, unit: 'stops', precision: 2 },
    saturation: { min: 0.0, max: 4.0, default: 1.0, precision: 2 },
    colorBalanceX: { min: -1.0, max: 1.0, default: 0.0, precision: 2 },
    colorBalanceY: { min: -1.0, max: 1.0, default: 0.0, precision: 2 },
  },

  // ========================================================================
  // HSL Qualifier - Awaiting DRX training
  // ========================================================================
  qualifier: {
    // Hue selection
    hueCenter: { min: 0, max: 360, default: 0, unit: '°', precision: 0 },
    hueWidth: { min: 0, max: 180, default: 30, unit: '°', precision: 0 },
    hueSoft: { min: 0, max: 100, default: 10, precision: 0 },

    // Saturation selection
    satLow: { min: 0, max: 100, default: 0, precision: 0 },
    satHigh: { min: 0, max: 100, default: 100, precision: 0 },
    satLowSoft: { min: 0, max: 100, default: 0, precision: 0 },
    satHighSoft: { min: 0, max: 100, default: 0, precision: 0 },

    // Luminance selection
    lumLow: { min: 0, max: 100, default: 0, precision: 0 },
    lumHigh: { min: 0, max: 100, default: 100, precision: 0 },
    lumLowSoft: { min: 0, max: 100, default: 0, precision: 0 },
    lumHighSoft: { min: 0, max: 100, default: 0, precision: 0 },

    // Additional qualifier params
    hueSymmetry: { min: 0.0, max: 1.0, default: 0.5, precision: 3, note: 'DRX = UI/100' },
    blurRadius: { min: 0.0, max: 1.0, default: 0.0, precision: 3 },

    // Matte controls
    denoise: { min: 0, max: 100, default: 0, precision: 0 },
    blur: { min: 0, max: 100, default: 0, precision: 0 },
    invert: { min: 0, max: 1, default: 0, precision: 0 },
  },

  // ========================================================================
  // Power Windows - Awaiting DRX training
  // ========================================================================
  window: {
    // Position (normalized 0-1)
    centerX: { min: 0, max: 1, default: 0.5, precision: 3 },
    centerY: { min: 0, max: 1, default: 0.5, precision: 3 },

    // Size (normalized 0-1)
    width: { min: 0, max: 2, default: 0.5, precision: 3 },
    height: { min: 0, max: 2, default: 0.5, precision: 3 },

    // Rotation
    rotation: { min: -180, max: 180, default: 0, unit: '°', precision: 1 },

    // Softness
    soft1: { min: 0, max: 100, default: 0, precision: 0 },
    soft2: { min: 0, max: 100, default: 0, precision: 0 },
    soft3: { min: 0, max: 100, default: 0, precision: 0 },
    soft4: { min: 0, max: 100, default: 0, precision: 0 },

    // Type (0=none, 1=linear, 2=circle, 3=polygon, 4=curve, 5=gradient)
    type: { min: 0, max: 5, default: 2, precision: 0 },
    invert: { min: 0, max: 1, default: 0, precision: 0 },
  },

  // ========================================================================
  // Custom Curves - Awaiting DRX training
  // ========================================================================
  customCurves: {
    // Each curve has control points (x, y pairs)
    // These are semantic representations - actual encoding TBD
    lumaCurve: { min: 0, max: 1, default: null, precision: 3, note: 'Array of control points' },
    redCurve: { min: 0, max: 1, default: null, precision: 3, note: 'Array of control points' },
    greenCurve: { min: 0, max: 1, default: null, precision: 3, note: 'Array of control points' },
    blueCurve: { min: 0, max: 1, default: null, precision: 3, note: 'Array of control points' },
  },

  // ========================================================================
  // Color Boost (already implemented)
  // ========================================================================
  colorBoost: {
    master: { min: 0, max: 100, default: 0, precision: 0 },
  },

  // ========================================================================
  // Additional Primary Controls (added for universal clamp coverage)
  // ========================================================================
  hueRotate: {
    master: { min: -1.0, max: 1.0, default: 0.0, precision: 3, note: 'DRX space: (UI-50)/50' },
  },

  highlights: {
    master: { min: -100, max: 100, default: 0, precision: 0, note: 'Direct value' },
  },

  shadows: {
    master: { min: -100, max: 100, default: 0, precision: 0, note: 'Direct value' },
  },

  lumMixSlider: {
    master: { min: 0.0, max: 1.0, default: 0.0, precision: 3 },
  },

  // ========================================================================
  // RGB Mixer (3x3 channel matrix, identity = diagonal 1.0)
  // ========================================================================
  rgbMixer: {
    rr: { min: -2.0, max: 2.0, default: 1.0, precision: 3 },
    gr: { min: -2.0, max: 2.0, default: 0.0, precision: 3 },
    br: { min: -2.0, max: 2.0, default: 0.0, precision: 3 },
    rg: { min: -2.0, max: 2.0, default: 0.0, precision: 3 },
    gg: { min: -2.0, max: 2.0, default: 1.0, precision: 3 },
    bg: { min: -2.0, max: 2.0, default: 0.0, precision: 3 },
    rb: { min: -2.0, max: 2.0, default: 0.0, precision: 3 },
    gb: { min: -2.0, max: 2.0, default: 0.0, precision: 3 },
    bb: { min: -2.0, max: 2.0, default: 1.0, precision: 3 },
    preserveLuminance: { min: 0, max: 1, default: 0, precision: 0, note: 'Boolean toggle' },
  },

  // ========================================================================
  // Matte Finesse (all DRX = UI / 100, range 0-1)
  // ========================================================================
  matteFinesse: {
    denoise: { min: 0.0, max: 1.0, default: 0.0, precision: 3 },
    blackClip: { min: 0.0, max: 1.0, default: 0.0, precision: 3 },
    whiteClip: { min: 0.0, max: 1.0, default: 0.0, precision: 3 },
    inOutRatio: { min: 0.0, max: 1.0, default: 0.0, precision: 3 },
    cleanBlack: { min: 0.0, max: 1.0, default: 0.0, precision: 3 },
    cleanWhite: { min: 0.0, max: 1.0, default: 0.0, precision: 3 },
    morphRadius: { min: 0.0, max: 1.0, default: 0.0, precision: 3 },
    preFilter: { min: 0.0, max: 1.0, default: 0.0, precision: 3 },
    postFilter: { min: 0.0, max: 1.0, default: 0.0, precision: 3 },
    shadow: { min: 0.0, max: 1.0, default: 0.0, precision: 3 },
    midtone: { min: 0.0, max: 1.0, default: 0.0, precision: 3 },
    highlight: { min: 0.0, max: 1.0, default: 0.0, precision: 3 },
  },

  // ========================================================================
  // Power Windows (spatial correction)
  // ========================================================================
  window: {
    // DRX-INTERNAL spans — calibrated 2026-06-22 (multi-point fit) and widened 2026-07-01.
    // The previous normalized guesses ([-1,1] pan/tilt, [0,1] softRef) clamped the TRUE
    // stored values (pan/tilt = (UI−50)/50 × 4096; softRef = UI × 16; size = 1+(UI−50)×0.08;
    // rotate = −UI°/180) inside createParameterEntry, which is why the generator could not
    // write Resolve-faithful window transforms.
    rotate: { min: -2.0, max: 2.0, default: 0, precision: 4, note: 'stored = −UI°/180' },
    size: { min: -3.0, max: 5.0, default: 1.0, precision: 4, note: 'stored = 1+(UI−50)×0.08' },
    softRef: { min: 0.0, max: 1600.0, default: 0.0, precision: 2, note: 'stored = UI × 16' },
    soft1: { min: 0.0, max: 1600.0, default: 0.0, precision: 2, note: 'stored = UI × 16 (ct3 mask)' },
    soft2: { min: 0.0, max: 1600.0, default: 0.0, precision: 2, note: 'stored = UI × 16 (ct3 mask)' },
    soft3: { min: 0.0, max: 1600.0, default: 0.0, precision: 2, note: 'stored = UI × 16 (ct3 mask)' },
    soft4: { min: 0.0, max: 1600.0, default: 0.0, precision: 2, note: 'stored = UI × 16 (ct3 mask)' },
    aspect: { min: -1.0, max: 1.0, default: 0.0, precision: 4, note: 'stored = (50−UI)/50' },
    pan: { min: -4096.0, max: 4096.0, default: 0.0, precision: 2, note: 'stored = (UI−50)/50 × 4096' },
    tilt: { min: -4096.0, max: 4096.0, default: 0.0, precision: 2, note: 'stored = (UI−50)/50 × 4096' },
    opacity: { min: 0.0, max: 1.0, default: 1.0, precision: 3, note: 'stored = UI/100' },
    type: { min: 0, max: 5, default: 2, precision: 0 },
    invert: { min: 0, max: 1, default: 0, precision: 0 },
  },
};

/**
 * Get range info for a parameter
 * @param {string} control - Control name (e.g., 'lift', 'gain')
 * @param {string} channel - Channel name (e.g., 'r', 'master')
 * @returns {object|null} Range object or null if not found
 */
function getRange(control, channel) {
  const controlRanges = PARAMETER_RANGES[control];
  if (!controlRanges) return null;
  return controlRanges[channel] || null;
}

/**
 * Get the default value for a parameter
 * @param {string} control - Control name
 * @param {string} channel - Channel name
 * @returns {number|null} Default value or null if not found
 */
function getDefault(control, channel) {
  const range = getRange(control, channel);
  return range ? range.default : null;
}

/**
 * Clamp a value to the valid range for a parameter
 * @param {string} control - Control name
 * @param {string} channel - Channel name
 * @param {number} value - Value to clamp
 * @returns {number} Clamped value
 */
function clamp(control, channel, value) {
  const range = getRange(control, channel);
  if (!range) return value;
  return Math.max(range.min, Math.min(range.max, value));
}

/**
 * Normalize a value to 0-1 range
 * @param {string} control - Control name
 * @param {string} channel - Channel name
 * @param {number} value - Raw value
 * @returns {number} Normalized 0-1 value
 */
function normalize(control, channel, value) {
  const range = getRange(control, channel);
  if (!range) return value;
  return (value - range.min) / (range.max - range.min);
}

/**
 * Denormalize a 0-1 value to parameter range
 * @param {string} control - Control name
 * @param {string} channel - Channel name
 * @param {number} normalized - Normalized 0-1 value
 * @returns {number} Denormalized value
 */
function denormalize(control, channel, normalized) {
  const range = getRange(control, channel);
  if (!range) return normalized;
  return range.min + normalized * (range.max - range.min);
}

/**
 * Check if a value is at the default/neutral
 * @param {string} control - Control name
 * @param {string} channel - Channel name
 * @param {number} value - Value to check
 * @param {number} tolerance - Tolerance for floating point comparison
 * @returns {boolean}
 */
function isDefault(control, channel, value, tolerance = 0.001) {
  const defaultVal = getDefault(control, channel);
  if (defaultVal === null) return false;
  return Math.abs(value - defaultVal) < tolerance;
}

/**
 * Format a value for display
 * @param {string} control - Control name
 * @param {string} channel - Channel name
 * @param {number} value - Value to format
 * @returns {string} Formatted string
 */
function formatValue(control, channel, value) {
  const range = getRange(control, channel);
  if (!range) return String(value);

  const precision = range.precision || 2;
  let formatted = value.toFixed(precision);

  // Add unit if present
  if (range.unit) {
    formatted += ` ${range.unit}`;
  }

  // Add sign for positive values on signed ranges
  if (range.min < 0 && value > 0) {
    formatted = '+' + formatted;
  }

  return formatted;
}

/**
 * Get all default parameter values as a flat object
 * @returns {object} Object with control.channel keys and default values
 */
function getAllDefaults() {
  const defaults = {};

  for (const [control, channels] of Object.entries(PARAMETER_RANGES)) {
    defaults[control] = {};
    for (const [channel, range] of Object.entries(channels)) {
      defaults[control][channel] = range.default;
    }
  }

  return defaults;
}

/**
 * Visual impact weights for change detection
 * Higher values = more visually impactful changes
 */
const VISUAL_IMPACT_WEIGHTS = {
  saturation: 2.0,   // Saturation changes are very noticeable
  contrast: 1.8,     // Contrast is highly visible
  temperature: 1.5,  // Color temperature shifts are obvious
  gamma: 1.2,        // Midtone changes are visible
  lift: 1.0,         // Shadow changes
  gain: 1.0,         // Highlight changes
  tint: 1.0,         // Tint is noticeable
  offset: 0.8,       // Offset is subtle
  pivot: 0.5,        // Pivot changes are less obvious
};

/**
 * Get visual impact weight for a control
 * @param {string} control - Control name
 * @returns {number} Impact weight (default 1.0)
 */
function getVisualImpactWeight(control) {
  return VISUAL_IMPACT_WEIGHTS[control] || 1.0;
}

module.exports = {
  PARAMETER_RANGES,
  VISUAL_IMPACT_WEIGHTS,
  getRange,
  getDefault,
  clamp,
  normalize,
  denormalize,
  isDefault,
  formatValue,
  getAllDefaults,
  getVisualImpactWeight,
};
