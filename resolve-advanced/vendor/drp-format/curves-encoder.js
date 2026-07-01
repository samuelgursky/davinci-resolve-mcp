/**
 * DaVinci Resolve Curves Encoder
 *
 * Advanced curve encoding for color grading including:
 * - RGB channel curves
 * - Hue vs Hue/Sat/Lum curves
 * - Luminance vs Saturation curves
 * - Saturation vs Saturation/Lum curves
 * - Bezier and linear interpolation
 * - S-curve and lift/gamma/gain presets
 *
 * Works with node-tree-encoder.js for complete grade encoding.
 *
 * @module curves-encoder
 */

const { encodeVarint, encodeFloat, encodeTag } = require('./grade-encoder');
const { CURVE_TYPES } = require('./grade-parameter-decoder');

// ═══════════════════════════════════════════════════════════════════════════
// CURVE POINT GENERATION
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Default bezier handle length relative to adjacent point distance
 */
const DEFAULT_HANDLE_LENGTH = 0.33;

/**
 * Create curve points from simple x,y coordinates with automatic bezier handles
 *
 * @param {Array} xyPoints - Array of [x, y] coordinate pairs
 * @param {Object} options - Handle generation options
 * @param {number} options.tension - Curve tension (0 = sharp, 1 = smooth)
 * @returns {Array} Array of complete point objects with handles
 */
function createBezierPoints(xyPoints, options = {}) {
  const { tension = 0.5 } = options;
  const points = [];

  for (let i = 0; i < xyPoints.length; i++) {
    const [x, y] = xyPoints[i];
    const prev = xyPoints[i - 1];
    const next = xyPoints[i + 1];

    // Calculate handle directions based on adjacent points
    let handleInX = x;
    let handleInY = y;
    let handleOutX = x;
    let handleOutY = y;

    if (prev && next) {
      // Interior point - smooth bezier
      const dx = next[0] - prev[0];
      const dy = next[1] - prev[1];
      const length = Math.sqrt(dx * dx + dy * dy) * DEFAULT_HANDLE_LENGTH * tension;

      const angle = Math.atan2(dy, dx);
      handleInX = x - Math.cos(angle) * length;
      handleInY = y - Math.sin(angle) * length;
      handleOutX = x + Math.cos(angle) * length;
      handleOutY = y + Math.sin(angle) * length;
    } else if (prev) {
      // End point
      const dx = x - prev[0];
      const dy = y - prev[1];
      const length = Math.sqrt(dx * dx + dy * dy) * DEFAULT_HANDLE_LENGTH * tension;
      handleInX = x - (dx / Math.sqrt(dx * dx + dy * dy || 1)) * length;
      handleInY = y - (dy / Math.sqrt(dx * dx + dy * dy || 1)) * length;
    } else if (next) {
      // Start point
      const dx = next[0] - x;
      const dy = next[1] - y;
      const length = Math.sqrt(dx * dx + dy * dy) * DEFAULT_HANDLE_LENGTH * tension;
      handleOutX = x + (dx / Math.sqrt(dx * dx + dy * dy || 1)) * length;
      handleOutY = y + (dy / Math.sqrt(dx * dx + dy * dy || 1)) * length;
    }

    points.push({
      x,
      y,
      handleInX,
      handleInY,
      handleOutX,
      handleOutY,
    });
  }

  return points;
}

/**
 * Create linear interpolation points (no bezier handles)
 *
 * @param {Array} xyPoints - Array of [x, y] coordinate pairs
 * @returns {Array} Array of point objects
 */
function createLinearPoints(xyPoints) {
  return xyPoints.map(([x, y]) => ({
    x,
    y,
    handleInX: x,
    handleInY: y,
    handleOutX: x,
    handleOutY: y,
  }));
}

// ═══════════════════════════════════════════════════════════════════════════
// PRESET CURVE GENERATORS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Create an S-curve for contrast enhancement
 *
 * @param {number} strength - Curve strength (0-1, default 0.3)
 * @param {number} pivot - Pivot point (0-1, default 0.5)
 * @returns {Array} Curve points
 */
function createSCurve(strength = 0.3, pivot = 0.5) {
  // S-curve with customizable strength and pivot
  const shadowLift = strength * 0.5;
  const highlightPush = strength * 0.5;

  const points = [
    [0, shadowLift * 0.3], // Lift shadows slightly
    [pivot * 0.5, pivot * 0.5 - shadowLift], // Shadow control point
    [pivot, pivot], // Pivot stays fixed
    [pivot + (1 - pivot) * 0.5, pivot + (1 - pivot) * 0.5 + highlightPush], // Highlight control
    [1, 1 - highlightPush * 0.3], // Pull highlights slightly
  ];

  return createBezierPoints(points, { tension: 0.6 });
}

/**
 * Create a lift curve (affects shadows)
 *
 * @param {number} amount - Lift amount (-1 to 1)
 * @returns {Array} Curve points
 */
function createLiftCurve(amount = 0) {
  const liftValue = Math.max(0, Math.min(1, amount + 0));
  const points = [
    [0, liftValue], // Black point lifted
    [0.25, 0.25 + amount * 0.5], // Quarter tone
    [1, 1], // White point unchanged
  ];

  return createBezierPoints(points, { tension: 0.4 });
}

/**
 * Create a gamma curve (affects midtones)
 *
 * @param {number} amount - Gamma adjustment (0.1 to 4, 1 = neutral)
 * @returns {Array} Curve points
 */
function createGammaCurve(amount = 1) {
  // Generate gamma curve points
  const points = [];
  const numPoints = 5;

  for (let i = 0; i <= numPoints; i++) {
    const x = i / numPoints;
    const y = Math.pow(x, 1 / amount);
    points.push([x, Math.max(0, Math.min(1, y))]);
  }

  return createBezierPoints(points, { tension: 0.3 });
}

/**
 * Create a gain curve (affects highlights)
 *
 * @param {number} amount - Gain multiplier (0 to 2, 1 = neutral)
 * @returns {Array} Curve points
 */
function createGainCurve(amount = 1) {
  const points = [
    [0, 0], // Black point unchanged
    [0.75, 0.75 * amount], // Three-quarter tone
    [1, Math.min(1, amount)], // White point scaled
  ];

  return createBezierPoints(points, { tension: 0.4 });
}

/**
 * Create a clipping curve for crushing blacks or whites
 *
 * @param {Object} options - Clipping options
 * @param {number} options.blackClip - Black clipping point (0-0.5)
 * @param {number} options.whiteClip - White clipping point (0.5-1)
 * @returns {Array} Curve points
 */
function createClippingCurve(options = {}) {
  const { blackClip = 0, whiteClip = 1 } = options;

  const points = [
    [0, 0],
    [blackClip, 0], // Crush blacks
    [blackClip + 0.1, 0.1], // Transition
    [whiteClip - 0.1, 0.9], // Transition
    [whiteClip, 1], // Clip whites
    [1, 1],
  ];

  return createLinearPoints(points);
}

/**
 * Create a cross-process style curve for color channel
 *
 * @param {string} channel - 'red', 'green', or 'blue'
 * @param {number} strength - Effect strength (0-1)
 * @returns {Array} Curve points
 */
function createCrossProcessCurve(channel, strength = 0.5) {
  let points;

  switch (channel.toLowerCase()) {
    case 'red':
      // Boost shadows, compress highlights
      points = [
        [0, 0.1 * strength],
        [0.25, 0.35],
        [0.5, 0.5],
        [0.75, 0.7 - 0.05 * strength],
        [1, 0.95],
      ];
      break;

    case 'green':
      // S-curve for contrast
      points = [
        [0, 0.05 * strength],
        [0.25, 0.2],
        [0.5, 0.5],
        [0.75, 0.8],
        [1, 1 - 0.05 * strength],
      ];
      break;

    case 'blue':
      // Lift shadows significantly, compress highlights
      points = [
        [0, 0.15 * strength],
        [0.25, 0.3 + 0.05 * strength],
        [0.5, 0.55],
        [0.75, 0.75],
        [1, 0.9],
      ];
      break;

    default:
      points = [
        [0, 0],
        [1, 1],
      ];
  }

  return createBezierPoints(points, { tension: 0.5 });
}

// ═══════════════════════════════════════════════════════════════════════════
// HUE CURVE GENERATORS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Hue color reference values (in degrees)
 */
const HUE_COLORS = {
  RED: 0,
  ORANGE: 30,
  YELLOW: 60,
  YELLOW_GREEN: 90,
  GREEN: 120,
  CYAN: 180,
  BLUE: 240,
  PURPLE: 270,
  MAGENTA: 300,
  PINK: 330,
};

/**
 * Create a Hue vs Hue shift curve
 *
 * @param {Array} shifts - Array of {hue, shift} objects
 * @param {number} shifts[].hue - Source hue (0-360)
 * @param {number} shifts[].shift - Hue shift amount (-180 to 180)
 * @param {number} shifts[].width - Affected range width
 * @returns {Object} Complete curve definition
 */
function createHueVsHueCurve(shifts) {
  const points = [];

  // Start and end at neutral (no shift)
  points.push([0, 0.5]); // Normalized: 0.5 = no shift

  for (const { hue, shift, width = 30 } of shifts) {
    const normalizedHue = hue / 360;
    const normalizedShift = 0.5 + shift / 360;

    // Add transition points
    const widthNorm = width / 360;
    const startHue = (normalizedHue - widthNorm + 1) % 1;
    const endHue = (normalizedHue + widthNorm) % 1;

    if (startHue < normalizedHue) {
      points.push([startHue, 0.5]);
    }
    points.push([normalizedHue, normalizedShift]);
    if (endHue > normalizedHue) {
      points.push([endHue, 0.5]);
    }
  }

  points.push([1, 0.5]);

  // Sort by x and remove duplicates
  const sortedPoints = points
    .sort((a, b) => a[0] - b[0])
    .filter((p, i, arr) => i === 0 || p[0] !== arr[i - 1][0]);

  return {
    type: 'HUE_VS_HUE',
    enabled: true,
    points: createBezierPoints(sortedPoints, { tension: 0.3 }),
    interpolation: 'bezier',
  };
}

/**
 * Create a Hue vs Saturation curve
 *
 * @param {Array} adjustments - Array of {hue, saturation} objects
 * @param {number} adjustments[].hue - Target hue (0-360)
 * @param {number} adjustments[].saturation - Saturation multiplier (0-2, 1 = neutral)
 * @param {number} adjustments[].width - Affected range width
 * @returns {Object} Complete curve definition
 */
function createHueVsSatCurve(adjustments) {
  const points = [];

  // Neutral baseline
  points.push([0, 0.5]); // 0.5 = 1x saturation (neutral)

  for (const { hue, saturation, width = 30 } of adjustments) {
    const normalizedHue = hue / 360;
    const normalizedSat = saturation / 2; // 0-1 range for 0-2x

    // Add transition points
    const widthNorm = width / 360;

    points.push([(normalizedHue - widthNorm + 1) % 1, 0.5]);
    points.push([normalizedHue, normalizedSat]);
    points.push([(normalizedHue + widthNorm) % 1, 0.5]);
  }

  points.push([1, 0.5]);

  const sortedPoints = points
    .sort((a, b) => a[0] - b[0])
    .filter((p, i, arr) => i === 0 || p[0] !== arr[i - 1][0]);

  return {
    type: 'HUE_VS_SAT',
    enabled: true,
    points: createBezierPoints(sortedPoints, { tension: 0.4 }),
    interpolation: 'bezier',
  };
}

/**
 * Create a Hue vs Luminance curve
 *
 * @param {Array} adjustments - Array of {hue, luminance} objects
 * @param {number} adjustments[].hue - Target hue (0-360)
 * @param {number} adjustments[].luminance - Luminance adjustment (-1 to 1, 0 = neutral)
 * @param {number} adjustments[].width - Affected range width
 * @returns {Object} Complete curve definition
 */
function createHueVsLumCurve(adjustments) {
  const points = [];

  points.push([0, 0.5]); // Neutral

  for (const { hue, luminance, width = 30 } of adjustments) {
    const normalizedHue = hue / 360;
    const normalizedLum = 0.5 + luminance / 2;

    const widthNorm = width / 360;

    points.push([(normalizedHue - widthNorm + 1) % 1, 0.5]);
    points.push([normalizedHue, normalizedLum]);
    points.push([(normalizedHue + widthNorm) % 1, 0.5]);
  }

  points.push([1, 0.5]);

  const sortedPoints = points
    .sort((a, b) => a[0] - b[0])
    .filter((p, i, arr) => i === 0 || p[0] !== arr[i - 1][0]);

  return {
    type: 'HUE_VS_LUM',
    enabled: true,
    points: createBezierPoints(sortedPoints, { tension: 0.4 }),
    interpolation: 'bezier',
  };
}

// ═══════════════════════════════════════════════════════════════════════════
// LUMINANCE/SATURATION CURVE GENERATORS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Create a Luminance vs Saturation curve
 *
 * @param {Object} options - Curve options
 * @param {number} options.shadowSat - Shadow saturation (0-2, 1 = neutral)
 * @param {number} options.midtoneSat - Midtone saturation (0-2, 1 = neutral)
 * @param {number} options.highlightSat - Highlight saturation (0-2, 1 = neutral)
 * @returns {Object} Complete curve definition
 */
function createLumVsSatCurve(options = {}) {
  const { shadowSat = 1, midtoneSat = 1, highlightSat = 1 } = options;

  const points = [
    [0, shadowSat / 2],
    [0.25, (shadowSat + midtoneSat) / 4],
    [0.5, midtoneSat / 2],
    [0.75, (midtoneSat + highlightSat) / 4],
    [1, highlightSat / 2],
  ];

  return {
    type: 'LUM_VS_SAT',
    enabled: true,
    points: createBezierPoints(points, { tension: 0.5 }),
    interpolation: 'bezier',
  };
}

/**
 * Create a Saturation vs Saturation curve (affects saturated vs unsaturated areas)
 *
 * @param {Object} options - Curve options
 * @param {number} options.lowSatBoost - Boost for low saturation areas
 * @param {number} options.highSatCompress - Compression for high saturation
 * @returns {Object} Complete curve definition
 */
function createSatVsSatCurve(options = {}) {
  const { lowSatBoost = 0, highSatCompress = 0 } = options;

  const points = [
    [0, 0],
    [0.25, 0.25 + lowSatBoost * 0.1],
    [0.5, 0.5],
    [0.75, 0.75 - highSatCompress * 0.05],
    [1, 1 - highSatCompress * 0.1],
  ];

  return {
    type: 'SAT_VS_SAT',
    enabled: true,
    points: createBezierPoints(points, { tension: 0.4 }),
    interpolation: 'bezier',
  };
}

/**
 * Create a Saturation vs Luminance curve
 *
 * @param {Object} options - Curve options
 * @param {number} options.lowSatLum - Luminance adjustment for low saturation
 * @param {number} options.highSatLum - Luminance adjustment for high saturation
 * @returns {Object} Complete curve definition
 */
function createSatVsLumCurve(options = {}) {
  const { lowSatLum = 0, highSatLum = 0 } = options;

  const points = [
    [0, 0.5 + lowSatLum / 2],
    [0.5, 0.5],
    [1, 0.5 + highSatLum / 2],
  ];

  return {
    type: 'SAT_VS_LUM',
    enabled: true,
    points: createBezierPoints(points, { tension: 0.5 }),
    interpolation: 'bezier',
  };
}

// ═══════════════════════════════════════════════════════════════════════════
// FILM EMULATION PRESETS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Create curves that emulate classic film stocks
 *
 * @param {string} filmStock - Film stock name
 * @returns {Object} Object containing R, G, B, and Lum curves
 */
function createFilmEmulationCurves(filmStock) {
  switch (filmStock.toLowerCase()) {
    case 'kodak_portra':
      return {
        lum: {
          type: 'CUSTOM',
          enabled: true,
          points: createBezierPoints([
            [0, 0.02],
            [0.25, 0.27],
            [0.5, 0.52],
            [0.75, 0.78],
            [1, 0.98],
          ]),
          interpolation: 'bezier',
        },
        red: {
          type: 'RED',
          enabled: true,
          points: createBezierPoints([
            [0, 0.03],
            [0.25, 0.28],
            [0.5, 0.52],
            [0.75, 0.76],
            [1, 0.97],
          ]),
          interpolation: 'bezier',
        },
        green: {
          type: 'GREEN',
          enabled: true,
          points: createBezierPoints([
            [0, 0.02],
            [0.25, 0.26],
            [0.5, 0.51],
            [0.75, 0.77],
            [1, 0.98],
          ]),
          interpolation: 'bezier',
        },
        blue: {
          type: 'BLUE',
          enabled: true,
          points: createBezierPoints([
            [0, 0.05],
            [0.25, 0.29],
            [0.5, 0.53],
            [0.75, 0.78],
            [1, 0.96],
          ]),
          interpolation: 'bezier',
        },
      };

    case 'fuji_velvia':
      return {
        lum: {
          type: 'CUSTOM',
          enabled: true,
          points: createSCurve(0.4, 0.5),
          interpolation: 'bezier',
        },
        red: {
          type: 'RED',
          enabled: true,
          points: createBezierPoints([
            [0, 0],
            [0.2, 0.18],
            [0.5, 0.55],
            [0.8, 0.85],
            [1, 1],
          ]),
          interpolation: 'bezier',
        },
        green: {
          type: 'GREEN',
          enabled: true,
          points: createBezierPoints([
            [0, 0],
            [0.2, 0.22],
            [0.5, 0.52],
            [0.8, 0.82],
            [1, 1],
          ]),
          interpolation: 'bezier',
        },
        blue: {
          type: 'BLUE',
          enabled: true,
          points: createBezierPoints([
            [0, 0.02],
            [0.2, 0.24],
            [0.5, 0.54],
            [0.8, 0.84],
            [1, 1],
          ]),
          interpolation: 'bezier',
        },
      };

    case 'cinestill_800t':
      return {
        lum: {
          type: 'CUSTOM',
          enabled: true,
          points: createBezierPoints([
            [0, 0.05],
            [0.3, 0.32],
            [0.5, 0.52],
            [0.7, 0.72],
            [1, 0.95],
          ]),
          interpolation: 'bezier',
        },
        red: {
          type: 'RED',
          enabled: true,
          points: createBezierPoints([
            [0, 0.02],
            [0.3, 0.28],
            [0.5, 0.48],
            [0.7, 0.7],
            [1, 0.95],
          ]),
          interpolation: 'bezier',
        },
        green: {
          type: 'GREEN',
          enabled: true,
          points: createBezierPoints([
            [0, 0.04],
            [0.3, 0.32],
            [0.5, 0.52],
            [0.7, 0.72],
            [1, 0.96],
          ]),
          interpolation: 'bezier',
        },
        blue: {
          type: 'BLUE',
          enabled: true,
          points: createBezierPoints([
            [0, 0.08],
            [0.3, 0.36],
            [0.5, 0.56],
            [0.7, 0.74],
            [1, 0.94],
          ]),
          interpolation: 'bezier',
        },
      };

    default:
      // Neutral curves
      return {
        lum: {
          type: 'CUSTOM',
          enabled: true,
          points: createLinearPoints([
            [0, 0],
            [1, 1],
          ]),
          interpolation: 'linear',
        },
        red: { type: 'RED', enabled: false, points: [], interpolation: 'linear' },
        green: { type: 'GREEN', enabled: false, points: [], interpolation: 'linear' },
        blue: { type: 'BLUE', enabled: false, points: [], interpolation: 'linear' },
      };
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// CURVE ENCODING HELPERS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Encode a complete curve set for a corrector
 *
 * @param {Object} curveSet - Object with multiple curves
 * @returns {Array} Array of curve objects ready for node-tree-encoder
 */
function encodeCurveSet(curveSet) {
  const curves = [];

  if (curveSet.lum) curves.push(curveSet.lum);
  if (curveSet.red) curves.push(curveSet.red);
  if (curveSet.green) curves.push(curveSet.green);
  if (curveSet.blue) curves.push(curveSet.blue);
  if (curveSet.hueVsHue) curves.push(curveSet.hueVsHue);
  if (curveSet.hueVsSat) curves.push(curveSet.hueVsSat);
  if (curveSet.hueVsLum) curves.push(curveSet.hueVsLum);
  if (curveSet.lumVsSat) curves.push(curveSet.lumVsSat);
  if (curveSet.satVsSat) curves.push(curveSet.satVsSat);
  if (curveSet.satVsLum) curves.push(curveSet.satVsLum);

  return curves;
}

/**
 * Create a corrector node with curves
 *
 * @param {Object|Array} curves - Curve set or array of curves
 * @returns {Object} Corrector object ready for encoding
 */
function createCurvesCorrector(curves) {
  const { CORRECTOR_TYPE } = require('./grade-parameter-decoder');

  const curveArray = Array.isArray(curves) ? curves : encodeCurveSet(curves);

  return {
    typeId: CORRECTOR_TYPE.CURVES,
    enabled: true,
    values: {
      curves: curveArray,
    },
  };
}

// ═══════════════════════════════════════════════════════════════════════════
// EXPORTS
// ═══════════════════════════════════════════════════════════════════════════

module.exports = {
  // Point generation
  createBezierPoints,
  createLinearPoints,

  // Preset curves
  createSCurve,
  createLiftCurve,
  createGammaCurve,
  createGainCurve,
  createClippingCurve,
  createCrossProcessCurve,

  // Hue curves
  createHueVsHueCurve,
  createHueVsSatCurve,
  createHueVsLumCurve,

  // Lum/Sat curves
  createLumVsSatCurve,
  createSatVsSatCurve,
  createSatVsLumCurve,

  // Film emulation
  createFilmEmulationCurves,

  // Encoding helpers
  encodeCurveSet,
  createCurvesCorrector,

  // Constants
  HUE_COLORS,
  DEFAULT_HANDLE_LENGTH,
};
