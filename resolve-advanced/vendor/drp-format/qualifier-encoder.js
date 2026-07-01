/**
 * DaVinci Resolve Qualifier Encoder
 *
 * Advanced qualifier encoding for secondary color corrections including:
 * - HSL Qualifiers (Hue, Saturation, Luminance)
 * - Luminance Qualifiers
 * - 3D Qualifiers (volumetric keying)
 * - Matte finesse controls
 * - Pre-built presets for common selections
 *
 * Works with node-tree-encoder.js for complete grade encoding.
 *
 * @module qualifier-encoder
 */

const { encodeVarint, encodeFloat, encodeTag } = require('./grade-encoder');
const { HSL_QUALIFIER, CORRECTOR_TYPE } = require('./grade-parameter-decoder');

// ═══════════════════════════════════════════════════════════════════════════
// QUALIFIER PRESETS - COMMON COLOR SELECTIONS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Pre-defined hue ranges for common color selections
 */
const HUE_PRESETS = {
  // Skin tones
  SKIN_CAUCASIAN: { center: 25, width: 25 },
  SKIN_WARM: { center: 30, width: 30 },
  SKIN_COOL: { center: 20, width: 20 },
  SKIN_DARK: { center: 28, width: 35 },

  // Sky and water
  SKY_BLUE: { center: 210, width: 40 },
  SKY_CYAN: { center: 190, width: 30 },
  WATER_DEEP: { center: 220, width: 30 },
  WATER_TROPICAL: { center: 175, width: 25 },

  // Foliage
  GRASS_GREEN: { center: 120, width: 30 },
  FOLIAGE_WARM: { center: 90, width: 40 },
  FOLIAGE_COOL: { center: 140, width: 35 },

  // Warm tones
  FIRE_ORANGE: { center: 35, width: 25 },
  SUNSET: { center: 20, width: 40 },
  GOLD: { center: 45, width: 20 },

  // Cool tones
  PURPLE: { center: 280, width: 30 },
  MAGENTA: { center: 315, width: 35 },
  PINK: { center: 340, width: 25 },

  // Neutrals (high luminance range, low saturation)
  HIGHLIGHTS: { center: 0, width: 180 }, // Full hue range
  SHADOWS: { center: 0, width: 180 },
};

/**
 * Saturation presets for common selections
 */
const SATURATION_PRESETS = {
  NEUTRAL_ONLY: { low: 0, high: 15, lowSoft: 5, highSoft: 10 },
  LOW_SAT: { low: 0, high: 40, lowSoft: 5, highSoft: 15 },
  MID_SAT: { low: 25, high: 75, lowSoft: 10, highSoft: 10 },
  HIGH_SAT: { low: 50, high: 100, lowSoft: 15, highSoft: 0 },
  FULL_SAT: { low: 0, high: 100, lowSoft: 0, highSoft: 0 },
  SKIN_SAT: { low: 15, high: 65, lowSoft: 10, highSoft: 15 },
};

/**
 * Luminance presets for tonal selections
 */
const LUMINANCE_PRESETS = {
  SHADOWS: { low: 0, high: 25, lowSoft: 0, highSoft: 15 },
  DARK_MIDS: { low: 15, high: 45, lowSoft: 10, highSoft: 10 },
  MIDTONES: { low: 25, high: 75, lowSoft: 15, highSoft: 15 },
  BRIGHT_MIDS: { low: 55, high: 85, lowSoft: 10, highSoft: 10 },
  HIGHLIGHTS: { low: 75, high: 100, lowSoft: 15, highSoft: 0 },
  FULL_RANGE: { low: 0, high: 100, lowSoft: 0, highSoft: 0 },
  SKIN_LUM: { low: 20, high: 85, lowSoft: 10, highSoft: 10 },
};

// ═══════════════════════════════════════════════════════════════════════════
// HSL QUALIFIER BUILDERS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Create a complete HSL qualifier from components
 *
 * @param {Object} options - Qualifier options
 * @param {Object} options.hue - Hue range {center, width, soft}
 * @param {Object} options.saturation - Sat range {low, high, lowSoft, highSoft}
 * @param {Object} options.luminance - Lum range {low, high, lowSoft, highSoft}
 * @param {Object} options.matte - Matte options {invert, finesse, denoise, shrinkGrow}
 * @returns {Object} Complete qualifier settings
 */
function createHSLQualifier(options = {}) {
  const {
    hue = {},
    saturation = {},
    luminance = {},
    matte = {},
  } = options;

  return {
    ENABLED: true,

    // Hue range
    HUE_CENTER: hue.center ?? 0,
    HUE_WIDTH: hue.width ?? 30,
    HUE_SOFT: hue.soft ?? 10,

    // Saturation range
    SAT_LOW: saturation.low ?? 0,
    SAT_HIGH: saturation.high ?? 100,
    SAT_LOW_SOFT: saturation.lowSoft ?? 0,
    SAT_HIGH_SOFT: saturation.highSoft ?? 0,

    // Luminance range
    LUM_LOW: luminance.low ?? 0,
    LUM_HIGH: luminance.high ?? 100,
    LUM_LOW_SOFT: luminance.lowSoft ?? 0,
    LUM_HIGH_SOFT: luminance.highSoft ?? 0,

    // Matte controls
    INVERT: matte.invert ?? false,
    MATTE_FINESSE: matte.finesse ?? 0,
    DENOISE: matte.denoise ?? 0,
    SHRINK_GROW: matte.shrinkGrow ?? 0,
  };
}

/**
 * Create a skin tone qualifier with optional customization
 *
 * @param {Object} options - Customization options
 * @param {string} options.type - Skin type preset ('caucasian', 'warm', 'cool', 'dark')
 * @param {boolean} options.strict - Use stricter selection (smaller ranges)
 * @param {number} options.denoise - Matte denoising amount (0-100)
 * @returns {Object} Skin tone qualifier settings
 */
function createSkinToneQualifier(options = {}) {
  const { type = 'caucasian', strict = false, denoise = 20 } = options;

  // Select hue preset based on skin type
  let huePreset;
  switch (type.toLowerCase()) {
    case 'warm':
      huePreset = HUE_PRESETS.SKIN_WARM;
      break;
    case 'cool':
      huePreset = HUE_PRESETS.SKIN_COOL;
      break;
    case 'dark':
      huePreset = HUE_PRESETS.SKIN_DARK;
      break;
    default:
      huePreset = HUE_PRESETS.SKIN_CAUCASIAN;
  }

  // Adjust ranges if strict mode
  const widthMultiplier = strict ? 0.7 : 1.0;
  const softMultiplier = strict ? 0.5 : 1.0;

  return createHSLQualifier({
    hue: {
      center: huePreset.center,
      width: huePreset.width * widthMultiplier,
      soft: 10 * softMultiplier,
    },
    saturation: {
      low: SATURATION_PRESETS.SKIN_SAT.low,
      high: SATURATION_PRESETS.SKIN_SAT.high,
      lowSoft: SATURATION_PRESETS.SKIN_SAT.lowSoft * softMultiplier,
      highSoft: SATURATION_PRESETS.SKIN_SAT.highSoft * softMultiplier,
    },
    luminance: {
      low: LUMINANCE_PRESETS.SKIN_LUM.low,
      high: LUMINANCE_PRESETS.SKIN_LUM.high,
      lowSoft: LUMINANCE_PRESETS.SKIN_LUM.lowSoft * softMultiplier,
      highSoft: LUMINANCE_PRESETS.SKIN_LUM.highSoft * softMultiplier,
    },
    matte: {
      denoise,
      finesse: 50,
      shrinkGrow: 0,
      invert: false,
    },
  });
}

/**
 * Create a sky/water qualifier
 *
 * @param {Object} options - Selection options
 * @param {string} options.type - Type ('sky', 'sky_cyan', 'water', 'water_tropical')
 * @param {boolean} options.excludeReflections - Add luminance floor to exclude reflections
 * @returns {Object} Sky/water qualifier settings
 */
function createSkyWaterQualifier(options = {}) {
  const { type = 'sky', excludeReflections = false } = options;

  let huePreset;
  switch (type.toLowerCase()) {
    case 'sky_cyan':
      huePreset = HUE_PRESETS.SKY_CYAN;
      break;
    case 'water':
      huePreset = HUE_PRESETS.WATER_DEEP;
      break;
    case 'water_tropical':
      huePreset = HUE_PRESETS.WATER_TROPICAL;
      break;
    default:
      huePreset = HUE_PRESETS.SKY_BLUE;
  }

  const lumPreset = excludeReflections
    ? LUMINANCE_PRESETS.BRIGHT_MIDS
    : LUMINANCE_PRESETS.FULL_RANGE;

  return createHSLQualifier({
    hue: {
      center: huePreset.center,
      width: huePreset.width,
      soft: 15,
    },
    saturation: {
      low: 15,
      high: 100,
      lowSoft: 10,
      highSoft: 0,
    },
    luminance: {
      low: lumPreset.low,
      high: lumPreset.high,
      lowSoft: lumPreset.lowSoft,
      highSoft: lumPreset.highSoft,
    },
    matte: {
      denoise: 15,
      finesse: 30,
    },
  });
}

/**
 * Create a foliage/greenery qualifier
 *
 * @param {Object} options - Selection options
 * @param {string} options.type - Type ('grass', 'warm', 'cool')
 * @param {boolean} options.includeYellows - Include yellow-green tones
 * @returns {Object} Foliage qualifier settings
 */
function createFoliageQualifier(options = {}) {
  const { type = 'grass', includeYellows = false } = options;

  let huePreset;
  switch (type.toLowerCase()) {
    case 'warm':
      huePreset = HUE_PRESETS.FOLIAGE_WARM;
      break;
    case 'cool':
      huePreset = HUE_PRESETS.FOLIAGE_COOL;
      break;
    default:
      huePreset = HUE_PRESETS.GRASS_GREEN;
  }

  // Expand width if including yellows
  const width = includeYellows ? huePreset.width + 20 : huePreset.width;
  const center = includeYellows ? huePreset.center - 10 : huePreset.center;

  return createHSLQualifier({
    hue: {
      center,
      width,
      soft: 15,
    },
    saturation: {
      low: 20,
      high: 100,
      lowSoft: 10,
      highSoft: 0,
    },
    luminance: LUMINANCE_PRESETS.FULL_RANGE,
    matte: {
      denoise: 10,
      finesse: 25,
    },
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// LUMINANCE QUALIFIER BUILDERS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Create a luminance-only qualifier (ignores hue/saturation)
 *
 * @param {Object} options - Luminance range options
 * @param {number} options.low - Low threshold (0-100)
 * @param {number} options.high - High threshold (0-100)
 * @param {number} options.softness - Edge softness (0-100)
 * @param {boolean} options.invert - Invert selection
 * @returns {Object} Luminance qualifier settings
 */
function createLuminanceQualifier(options = {}) {
  const { low = 0, high = 100, softness = 10, invert = false } = options;

  return createHSLQualifier({
    hue: {
      center: 0,
      width: 180, // Full hue range
      soft: 0,
    },
    saturation: SATURATION_PRESETS.FULL_SAT,
    luminance: {
      low,
      high,
      lowSoft: softness,
      highSoft: softness,
    },
    matte: {
      invert,
      denoise: 0,
      finesse: 0,
    },
  });
}

/**
 * Create a shadow qualifier
 *
 * @param {Object} options - Shadow range options
 * @param {number} options.threshold - Shadow threshold (default 25)
 * @param {number} options.softness - Edge softness (default 15)
 * @returns {Object} Shadow qualifier settings
 */
function createShadowQualifier(options = {}) {
  const { threshold = 25, softness = 15 } = options;

  return createLuminanceQualifier({
    low: 0,
    high: threshold,
    softness,
    invert: false,
  });
}

/**
 * Create a highlight qualifier
 *
 * @param {Object} options - Highlight range options
 * @param {number} options.threshold - Highlight threshold (default 75)
 * @param {number} options.softness - Edge softness (default 15)
 * @returns {Object} Highlight qualifier settings
 */
function createHighlightQualifier(options = {}) {
  const { threshold = 75, softness = 15 } = options;

  return createLuminanceQualifier({
    low: threshold,
    high: 100,
    softness,
    invert: false,
  });
}

/**
 * Create a midtone qualifier
 *
 * @param {Object} options - Midtone range options
 * @param {number} options.low - Low threshold (default 25)
 * @param {number} options.high - High threshold (default 75)
 * @param {number} options.softness - Edge softness (default 15)
 * @returns {Object} Midtone qualifier settings
 */
function createMidtoneQualifier(options = {}) {
  const { low = 25, high = 75, softness = 15 } = options;

  return createLuminanceQualifier({
    low,
    high,
    softness,
    invert: false,
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// 3D QUALIFIER (VOLUMETRIC KEYING)
// ═══════════════════════════════════════════════════════════════════════════

/**
 * 3D Qualifier type identifiers
 */
const QUALIFIER_3D_TYPE = {
  HSL_CUBE: 1, // Standard HSL cube
  LGG_CUBE: 2, // Lift/Gamma/Gain cube
  CUSTOM: 3, // Custom 3D LUT-based
};

/**
 * Create a 3D qualifier configuration
 *
 * This is used for advanced volumetric keying where you need
 * to select a specific region of color space that can't be
 * easily defined with HSL ranges.
 *
 * @param {Object} options - 3D qualifier options
 * @param {number} options.type - Qualifier type (QUALIFIER_3D_TYPE enum)
 * @param {Array} options.centerColor - Center color [h, s, l] or [r, g, b]
 * @param {Array} options.radius - Selection radius [h, s, l] or [r, g, b]
 * @param {number} options.softness - Edge softness (0-1)
 * @param {boolean} options.invert - Invert selection
 * @returns {Object} 3D qualifier configuration
 */
function create3DQualifier(options = {}) {
  const {
    type = QUALIFIER_3D_TYPE.HSL_CUBE,
    centerColor = [0, 50, 50],
    radius = [30, 30, 30],
    softness = 0.2,
    invert = false,
  } = options;

  return {
    type,
    centerColor,
    radius,
    softness,
    invert,
    // 3D qualifiers require additional encoding - these are stored
    // as look-up cube data in a separate field
    cubeSize: 17, // Default LUT size
  };
}

/**
 * Encode a 3D qualifier to protobuf format
 *
 * @param {Object} qualifier - 3D qualifier configuration
 * @returns {string} Hex-encoded 3D qualifier data
 */
function encode3DQualifier(qualifier) {
  const parts = [];

  // Field 1: Type (varint)
  parts.push(encodeTag(1, 0).toString('hex'));
  parts.push(encodeVarint(qualifier.type).toString('hex'));

  // Field 2: Center color (nested floats)
  const centerParts = [];
  for (const value of qualifier.centerColor) {
    centerParts.push(encodeTag(1, 5).toString('hex'));
    centerParts.push(encodeFloat(value));
  }
  const centerData = centerParts.join('');
  parts.push(encodeTag(2, 2).toString('hex'));
  parts.push(encodeVarint(centerData.length / 2).toString('hex'));
  parts.push(centerData);

  // Field 3: Radius (nested floats)
  const radiusParts = [];
  for (const value of qualifier.radius) {
    radiusParts.push(encodeTag(1, 5).toString('hex'));
    radiusParts.push(encodeFloat(value));
  }
  const radiusData = radiusParts.join('');
  parts.push(encodeTag(3, 2).toString('hex'));
  parts.push(encodeVarint(radiusData.length / 2).toString('hex'));
  parts.push(radiusData);

  // Field 4: Softness (float)
  parts.push(encodeTag(4, 5).toString('hex'));
  parts.push(encodeFloat(qualifier.softness));

  // Field 5: Invert (varint boolean)
  parts.push(encodeTag(5, 0).toString('hex'));
  parts.push(encodeVarint(qualifier.invert ? 1 : 0).toString('hex'));

  // Field 6: Cube size (varint)
  parts.push(encodeTag(6, 0).toString('hex'));
  parts.push(encodeVarint(qualifier.cubeSize || 17).toString('hex'));

  return parts.join('');
}

// ═══════════════════════════════════════════════════════════════════════════
// MATTE FINESSE HELPERS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Apply matte finesse adjustments to a qualifier
 *
 * @param {Object} qualifier - Existing qualifier settings
 * @param {Object} finesse - Finesse adjustments
 * @param {number} finesse.denoise - Reduce noise in matte (0-100)
 * @param {number} finesse.clean - Clean black/white levels (0-100)
 * @param {number} finesse.blur - Blur matte edges (0-100)
 * @param {number} finesse.shrink - Shrink matte (-100 to 0)
 * @param {number} finesse.grow - Grow matte (0 to 100)
 * @returns {Object} Updated qualifier with finesse
 */
function applyMatteFinesse(qualifier, finesse = {}) {
  const { denoise = 0, clean = 0, blur = 0, shrink = 0, grow = 0 } = finesse;

  return {
    ...qualifier,
    DENOISE: denoise,
    MATTE_FINESSE: clean + blur, // Combined into single value
    SHRINK_GROW: shrink + grow, // Negative = shrink, positive = grow
  };
}

/**
 * Create a refined qualifier with clean edges
 *
 * @param {Object} baseQualifier - Base qualifier settings
 * @param {string} refinementLevel - 'light', 'medium', 'heavy'
 * @returns {Object} Refined qualifier
 */
function refineQualifier(baseQualifier, refinementLevel = 'medium') {
  const refinements = {
    light: { denoise: 10, clean: 20, blur: 5, shrink: 0, grow: 0 },
    medium: { denoise: 25, clean: 40, blur: 15, shrink: -5, grow: 0 },
    heavy: { denoise: 50, clean: 60, blur: 30, shrink: -10, grow: 0 },
  };

  const finesse = refinements[refinementLevel] || refinements.medium;
  return applyMatteFinesse(baseQualifier, finesse);
}

// ═══════════════════════════════════════════════════════════════════════════
// QUALIFIER CORRECTOR BUILDER
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Create a complete qualifier corrector ready for encoding
 *
 * @param {Object} qualifier - Qualifier settings from any builder
 * @returns {Object} Corrector object for node-tree-encoder
 */
function createQualifierCorrector(qualifier) {
  return {
    typeId: CORRECTOR_TYPE.QUALIFIER,
    enabled: true,
    values: {
      qualifier,
    },
  };
}

/**
 * Create a qualified correction node (qualifier + primary correction)
 *
 * @param {Object} qualifier - Qualifier settings
 * @param {Object} correction - Primary correction to apply
 * @returns {Object} Node definition with both correctors
 */
function createQualifiedCorrectionNode(qualifier, correction) {
  return {
    id: `qualified_node_${Date.now()}`,
    label: 'Qualified Correction',
    enabled: true,
    correctors: [
      createQualifierCorrector(qualifier),
      {
        typeId: CORRECTOR_TYPE.PRIMARY,
        enabled: true,
        values: correction,
      },
    ],
  };
}

// ═══════════════════════════════════════════════════════════════════════════
// COLOR SPACE HELPERS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Convert RGB color to HSL for qualifier input
 *
 * @param {number} r - Red (0-255)
 * @param {number} g - Green (0-255)
 * @param {number} b - Blue (0-255)
 * @returns {Object} HSL values {h: 0-360, s: 0-100, l: 0-100}
 */
function rgbToHsl(r, g, b) {
  r /= 255;
  g /= 255;
  b /= 255;

  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;

  let h = 0;
  let s = 0;

  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);

    switch (max) {
      case r:
        h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
        break;
      case g:
        h = ((b - r) / d + 2) / 6;
        break;
      case b:
        h = ((r - g) / d + 4) / 6;
        break;
    }
  }

  return {
    h: Math.round(h * 360),
    s: Math.round(s * 100),
    l: Math.round(l * 100),
  };
}

/**
 * Create a qualifier from a sampled color
 *
 * @param {number} r - Red (0-255)
 * @param {number} g - Green (0-255)
 * @param {number} b - Blue (0-255)
 * @param {Object} options - Selection options
 * @param {number} options.hueWidth - Hue selection width
 * @param {number} options.satWidth - Saturation selection width
 * @param {number} options.lumWidth - Luminance selection width
 * @returns {Object} Qualifier settings
 */
function createQualifierFromColor(r, g, b, options = {}) {
  const { hueWidth = 20, satWidth = 30, lumWidth = 30 } = options;

  const hsl = rgbToHsl(r, g, b);

  return createHSLQualifier({
    hue: {
      center: hsl.h,
      width: hueWidth,
      soft: hueWidth * 0.3,
    },
    saturation: {
      low: Math.max(0, hsl.s - satWidth),
      high: Math.min(100, hsl.s + satWidth),
      lowSoft: satWidth * 0.3,
      highSoft: satWidth * 0.3,
    },
    luminance: {
      low: Math.max(0, hsl.l - lumWidth),
      high: Math.min(100, hsl.l + lumWidth),
      lowSoft: lumWidth * 0.3,
      highSoft: lumWidth * 0.3,
    },
    matte: {
      denoise: 15,
      finesse: 30,
    },
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// EXPORTS
// ═══════════════════════════════════════════════════════════════════════════

module.exports = {
  // HSL qualifier builders
  createHSLQualifier,
  createSkinToneQualifier,
  createSkyWaterQualifier,
  createFoliageQualifier,

  // Luminance qualifiers
  createLuminanceQualifier,
  createShadowQualifier,
  createHighlightQualifier,
  createMidtoneQualifier,

  // 3D qualifiers
  create3DQualifier,
  encode3DQualifier,

  // Matte finesse
  applyMatteFinesse,
  refineQualifier,

  // Corrector builders
  createQualifierCorrector,
  createQualifiedCorrectionNode,

  // Color space helpers
  rgbToHsl,
  createQualifierFromColor,

  // Presets/Constants
  HUE_PRESETS,
  SATURATION_PRESETS,
  LUMINANCE_PRESETS,
  QUALIFIER_3D_TYPE,
};
