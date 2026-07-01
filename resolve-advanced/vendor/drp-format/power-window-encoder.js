/**
 * DaVinci Resolve Power Window Encoder
 *
 * Advanced power window encoding for secondary corrections including:
 * - Circular/Oval windows
 * - Linear (gradient) windows
 * - Polygon windows
 * - Power Curve windows
 * - Gradient windows
 * - Transform controls (pan, zoom, rotation)
 * - Softness and feathering
 * - Window animation/tracking data
 *
 * Works with node-tree-encoder.js for complete grade encoding.
 *
 * @module power-window-encoder
 */

const { encodeVarint, encodeFloat, encodeTag } = require('./grade-encoder');
const { WINDOW_TYPES, WINDOW_FIELDS, CORRECTOR_TYPE } = require('./grade-parameter-decoder');

// ═══════════════════════════════════════════════════════════════════════════
// WINDOW CONSTANTS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Standard aspect ratios for oval windows
 */
const ASPECT_RATIOS = {
  SQUARE: 1.0,
  WIDE_16_9: 16 / 9,
  WIDE_2_35: 2.35,
  TALL_9_16: 9 / 16,
  PORTRAIT_4_5: 4 / 5,
  ANAMORPHIC_2_39: 2.39,
};

/**
 * Common gradient directions (in degrees)
 */
const GRADIENT_DIRECTIONS = {
  TOP_TO_BOTTOM: 0,
  BOTTOM_TO_TOP: 180,
  LEFT_TO_RIGHT: 90,
  RIGHT_TO_LEFT: 270,
  TOP_LEFT_TO_BOTTOM_RIGHT: 45,
  TOP_RIGHT_TO_BOTTOM_LEFT: 135,
  BOTTOM_LEFT_TO_TOP_RIGHT: 315,
  BOTTOM_RIGHT_TO_TOP_LEFT: 225,
};

/**
 * Pre-defined softness levels
 */
const SOFTNESS_PRESETS = {
  SHARP: 0,
  SUBTLE: 0.05,
  SOFT: 0.15,
  VERY_SOFT: 0.3,
  FEATHERED: 0.5,
  EXTREME: 0.8,
};

// ═══════════════════════════════════════════════════════════════════════════
// CIRCULAR/OVAL WINDOW BUILDERS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Create a circular power window
 *
 * @param {Object} options - Window options
 * @param {number} options.centerX - Center X position (0-1, default 0.5)
 * @param {number} options.centerY - Center Y position (0-1, default 0.5)
 * @param {number} options.radius - Window radius (0-1, default 0.25)
 * @param {number} options.softness - Edge softness (0-1, default 0.1)
 * @param {number} options.rotation - Rotation in degrees
 * @param {boolean} options.invert - Invert selection
 * @returns {Object} Window settings
 */
function createCircularWindow(options = {}) {
  const {
    centerX = 0.5,
    centerY = 0.5,
    radius = 0.25,
    softness = 0.1,
    rotation = 0,
    invert = false,
  } = options;

  return {
    type: 'CIRCLE',
    enabled: true,
    transform: {
      panX: centerX - 0.5, // Offset from center
      panY: centerY - 0.5,
      zoomX: 1.0,
      zoomY: 1.0,
      rotation,
      anchorX: 0.5,
      anchorY: 0.5,
    },
    shape: {
      radiusX: radius,
      radiusY: radius,
      softness,
      insideSoftness: 0,
      outsideSoftness: softness,
    },
    invert,
  };
}

/**
 * Create an oval power window with aspect ratio control
 *
 * @param {Object} options - Window options
 * @param {number} options.centerX - Center X position (0-1)
 * @param {number} options.centerY - Center Y position (0-1)
 * @param {number} options.radiusX - Horizontal radius (0-1)
 * @param {number} options.radiusY - Vertical radius (0-1)
 * @param {number} options.aspectRatio - Use preset aspect ratio (overrides radiusY)
 * @param {number} options.softness - Edge softness (0-1)
 * @param {number} options.rotation - Rotation in degrees
 * @param {boolean} options.invert - Invert selection
 * @returns {Object} Window settings
 */
function createOvalWindow(options = {}) {
  const {
    centerX = 0.5,
    centerY = 0.5,
    radiusX = 0.3,
    radiusY = 0.2,
    aspectRatio = null,
    softness = 0.1,
    rotation = 0,
    invert = false,
  } = options;

  // Calculate radiusY from aspect ratio if provided
  let finalRadiusY = radiusY;
  if (aspectRatio) {
    finalRadiusY = radiusX / aspectRatio;
  }

  return {
    type: 'CIRCLE',
    enabled: true,
    transform: {
      panX: centerX - 0.5,
      panY: centerY - 0.5,
      zoomX: 1.0,
      zoomY: 1.0,
      rotation,
      anchorX: 0.5,
      anchorY: 0.5,
    },
    shape: {
      radiusX,
      radiusY: finalRadiusY,
      softness,
      insideSoftness: 0,
      outsideSoftness: softness,
    },
    invert,
  };
}

/**
 * Create a vignette effect (large inverted oval)
 *
 * @param {Object} options - Vignette options
 * @param {number} options.strength - Vignette strength (0-1, affects size and softness)
 * @param {number} options.roundness - Vignette roundness (1 = circle, <1 = oval)
 * @param {number} options.offsetX - Horizontal center offset (-0.5 to 0.5)
 * @param {number} options.offsetY - Vertical center offset (-0.5 to 0.5)
 * @returns {Object} Window settings for vignette
 */
function createVignetteWindow(options = {}) {
  const {
    strength = 0.5,
    roundness = 0.8,
    offsetX = 0,
    offsetY = 0,
  } = options;

  // Calculate size based on strength (stronger = smaller/more visible)
  const baseRadius = 1.2 - strength * 0.7;
  const softness = 0.2 + strength * 0.4;

  return createOvalWindow({
    centerX: 0.5 + offsetX,
    centerY: 0.5 + offsetY,
    radiusX: baseRadius,
    radiusY: baseRadius * roundness,
    softness,
    invert: true, // Vignettes are inverted to darken edges
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// LINEAR/GRADIENT WINDOW BUILDERS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Create a linear (gradient) power window
 *
 * @param {Object} options - Window options
 * @param {number} options.angle - Gradient angle in degrees (0 = top to bottom)
 * @param {number} options.position - Position of gradient center (0-1)
 * @param {number} options.softness - Gradient softness (0-1)
 * @param {boolean} options.invert - Invert selection
 * @returns {Object} Window settings
 */
function createLinearWindow(options = {}) {
  const {
    angle = 0,
    position = 0.5,
    softness = 0.2,
    invert = false,
  } = options;

  return {
    type: 'LINEAR',
    enabled: true,
    transform: {
      panX: 0,
      panY: 0,
      zoomX: 1.0,
      zoomY: 1.0,
      rotation: 0,
      anchorX: 0.5,
      anchorY: 0.5,
    },
    shape: {
      angle,
      position,
      softness,
    },
    invert,
  };
}

/**
 * Create a gradient window from preset direction
 *
 * @param {string} direction - Direction name from GRADIENT_DIRECTIONS
 * @param {Object} options - Additional options
 * @param {number} options.position - Gradient position (0-1)
 * @param {number} options.softness - Gradient softness (0-1)
 * @param {boolean} options.invert - Invert selection
 * @returns {Object} Window settings
 */
function createGradientWindow(direction, options = {}) {
  const angle = GRADIENT_DIRECTIONS[direction.toUpperCase()] ?? 0;
  return createLinearWindow({ ...options, angle });
}

/**
 * Create a horizontal split window (left/right)
 *
 * @param {Object} options - Split options
 * @param {number} options.position - Split position (0-1, 0.5 = center)
 * @param {number} options.softness - Edge softness (0-1)
 * @param {boolean} options.selectRight - Select right side (default left)
 * @returns {Object} Window settings
 */
function createHorizontalSplit(options = {}) {
  const { position = 0.5, softness = 0.05, selectRight = false } = options;

  return createLinearWindow({
    angle: 90,
    position,
    softness,
    invert: selectRight,
  });
}

/**
 * Create a vertical split window (top/bottom)
 *
 * @param {Object} options - Split options
 * @param {number} options.position - Split position (0-1, 0.5 = center)
 * @param {number} options.softness - Edge softness (0-1)
 * @param {boolean} options.selectBottom - Select bottom side (default top)
 * @returns {Object} Window settings
 */
function createVerticalSplit(options = {}) {
  const { position = 0.5, softness = 0.05, selectBottom = false } = options;

  return createLinearWindow({
    angle: 0,
    position,
    softness,
    invert: selectBottom,
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// POLYGON WINDOW BUILDERS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Create a polygon power window
 *
 * @param {Array} points - Array of {x, y} points (0-1 normalized)
 * @param {Object} options - Window options
 * @param {number} options.softness - Edge softness (0-1)
 * @param {boolean} options.invert - Invert selection
 * @returns {Object} Window settings
 */
function createPolygonWindow(points, options = {}) {
  const { softness = 0.05, invert = false } = options;

  return {
    type: 'POLYGON',
    enabled: true,
    transform: {
      panX: 0,
      panY: 0,
      zoomX: 1.0,
      zoomY: 1.0,
      rotation: 0,
      anchorX: 0.5,
      anchorY: 0.5,
    },
    shape: {
      points: points.map((p) => ({ x: p.x, y: p.y })),
      softness,
    },
    invert,
  };
}

/**
 * Create a rectangular polygon window
 *
 * @param {Object} options - Rectangle options
 * @param {number} options.left - Left edge (0-1)
 * @param {number} options.top - Top edge (0-1)
 * @param {number} options.right - Right edge (0-1)
 * @param {number} options.bottom - Bottom edge (0-1)
 * @param {number} options.softness - Edge softness (0-1)
 * @param {boolean} options.invert - Invert selection
 * @returns {Object} Window settings
 */
function createRectangleWindow(options = {}) {
  const {
    left = 0.25,
    top = 0.25,
    right = 0.75,
    bottom = 0.75,
    softness = 0.05,
    invert = false,
  } = options;

  const points = [
    { x: left, y: top },
    { x: right, y: top },
    { x: right, y: bottom },
    { x: left, y: bottom },
  ];

  return createPolygonWindow(points, { softness, invert });
}

/**
 * Create a triangular polygon window
 *
 * @param {Object} options - Triangle options
 * @param {Object} options.point1 - First point {x, y}
 * @param {Object} options.point2 - Second point {x, y}
 * @param {Object} options.point3 - Third point {x, y}
 * @param {number} options.softness - Edge softness (0-1)
 * @param {boolean} options.invert - Invert selection
 * @returns {Object} Window settings
 */
function createTriangleWindow(options = {}) {
  const {
    point1 = { x: 0.5, y: 0.2 },
    point2 = { x: 0.2, y: 0.8 },
    point3 = { x: 0.8, y: 0.8 },
    softness = 0.05,
    invert = false,
  } = options;

  return createPolygonWindow([point1, point2, point3], { softness, invert });
}

/**
 * Create a regular polygon window (pentagon, hexagon, etc.)
 *
 * @param {Object} options - Polygon options
 * @param {number} options.sides - Number of sides (3-12)
 * @param {number} options.centerX - Center X position (0-1)
 * @param {number} options.centerY - Center Y position (0-1)
 * @param {number} options.radius - Polygon radius (0-0.5)
 * @param {number} options.rotation - Rotation in degrees
 * @param {number} options.softness - Edge softness (0-1)
 * @param {boolean} options.invert - Invert selection
 * @returns {Object} Window settings
 */
function createRegularPolygonWindow(options = {}) {
  const {
    sides = 6,
    centerX = 0.5,
    centerY = 0.5,
    radius = 0.25,
    rotation = 0,
    softness = 0.05,
    invert = false,
  } = options;

  const points = [];
  const angleStep = (2 * Math.PI) / sides;
  const rotationRad = (rotation * Math.PI) / 180;

  for (let i = 0; i < sides; i++) {
    const angle = angleStep * i - Math.PI / 2 + rotationRad;
    points.push({
      x: centerX + radius * Math.cos(angle),
      y: centerY + radius * Math.sin(angle),
    });
  }

  return createPolygonWindow(points, { softness, invert });
}

// ═══════════════════════════════════════════════════════════════════════════
// POWER CURVE WINDOW BUILDERS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Create a power curve window (bezier-edged shape)
 *
 * @param {Array} controlPoints - Array of {x, y, handleX, handleY} points
 * @param {Object} options - Window options
 * @param {number} options.softness - Edge softness (0-1)
 * @param {boolean} options.invert - Invert selection
 * @returns {Object} Window settings
 */
function createPowerCurveWindow(controlPoints, options = {}) {
  const { softness = 0.1, invert = false } = options;

  return {
    type: 'CURVE',
    enabled: true,
    transform: {
      panX: 0,
      panY: 0,
      zoomX: 1.0,
      zoomY: 1.0,
      rotation: 0,
      anchorX: 0.5,
      anchorY: 0.5,
    },
    shape: {
      points: controlPoints.map((p) => ({
        x: p.x,
        y: p.y,
        handleX: p.handleX ?? p.x,
        handleY: p.handleY ?? p.y,
      })),
      softness,
      feather: softness,
    },
    invert,
  };
}

/**
 * Create a curved rectangle (rounded corners)
 *
 * @param {Object} options - Rectangle options
 * @param {number} options.left - Left edge (0-1)
 * @param {number} options.top - Top edge (0-1)
 * @param {number} options.right - Right edge (0-1)
 * @param {number} options.bottom - Bottom edge (0-1)
 * @param {number} options.cornerRadius - Corner radius (0-0.5)
 * @param {number} options.softness - Edge softness (0-1)
 * @param {boolean} options.invert - Invert selection
 * @returns {Object} Window settings
 */
function createRoundedRectangleWindow(options = {}) {
  const {
    left = 0.2,
    top = 0.2,
    right = 0.8,
    bottom = 0.8,
    cornerRadius = 0.1,
    softness = 0.05,
    invert = false,
  } = options;

  // Generate points with bezier handles for rounded corners
  const r = cornerRadius;
  const controlPoints = [
    // Top edge
    { x: left + r, y: top, handleX: left, handleY: top },
    { x: right - r, y: top, handleX: right, handleY: top },
    // Right edge
    { x: right, y: top + r, handleX: right, handleY: top },
    { x: right, y: bottom - r, handleX: right, handleY: bottom },
    // Bottom edge
    { x: right - r, y: bottom, handleX: right, handleY: bottom },
    { x: left + r, y: bottom, handleX: left, handleY: bottom },
    // Left edge
    { x: left, y: bottom - r, handleX: left, handleY: bottom },
    { x: left, y: top + r, handleX: left, handleY: top },
  ];

  return createPowerCurveWindow(controlPoints, { softness, invert });
}

// ═══════════════════════════════════════════════════════════════════════════
// WINDOW TRANSFORM UTILITIES
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Apply transform to an existing window
 *
 * @param {Object} window - Existing window settings
 * @param {Object} transform - Transform to apply
 * @param {number} transform.panX - X offset (-1 to 1)
 * @param {number} transform.panY - Y offset (-1 to 1)
 * @param {number} transform.zoomX - X scale (0.1 to 10)
 * @param {number} transform.zoomY - Y scale (0.1 to 10)
 * @param {number} transform.rotation - Rotation in degrees
 * @returns {Object} Transformed window
 */
function applyWindowTransform(window, transform) {
  return {
    ...window,
    transform: {
      ...window.transform,
      panX: (window.transform?.panX ?? 0) + (transform.panX ?? 0),
      panY: (window.transform?.panY ?? 0) + (transform.panY ?? 0),
      zoomX: (window.transform?.zoomX ?? 1) * (transform.zoomX ?? 1),
      zoomY: (window.transform?.zoomY ?? 1) * (transform.zoomY ?? 1),
      rotation: (window.transform?.rotation ?? 0) + (transform.rotation ?? 0),
    },
  };
}

/**
 * Scale a window uniformly
 *
 * @param {Object} window - Existing window settings
 * @param {number} scale - Scale factor (1 = no change)
 * @returns {Object} Scaled window
 */
function scaleWindow(window, scale) {
  return applyWindowTransform(window, {
    zoomX: scale,
    zoomY: scale,
  });
}

/**
 * Move a window
 *
 * @param {Object} window - Existing window settings
 * @param {number} offsetX - X offset (-1 to 1)
 * @param {number} offsetY - Y offset (-1 to 1)
 * @returns {Object} Moved window
 */
function moveWindow(window, offsetX, offsetY) {
  return applyWindowTransform(window, {
    panX: offsetX,
    panY: offsetY,
  });
}

/**
 * Rotate a window
 *
 * @param {Object} window - Existing window settings
 * @param {number} degrees - Rotation in degrees
 * @returns {Object} Rotated window
 */
function rotateWindow(window, degrees) {
  return applyWindowTransform(window, {
    rotation: degrees,
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// WINDOW SOFTNESS UTILITIES
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Apply softness settings to a window
 *
 * @param {Object} window - Existing window settings
 * @param {Object} softness - Softness settings
 * @param {number} softness.overall - Overall softness (0-1)
 * @param {number} softness.inside - Inside edge softness (0-1)
 * @param {number} softness.outside - Outside edge softness (0-1)
 * @returns {Object} Window with updated softness
 */
function applyWindowSoftness(window, softness = {}) {
  const { overall, inside = 0, outside = softness.overall } = softness;

  return {
    ...window,
    shape: {
      ...window.shape,
      softness: overall ?? window.shape?.softness,
      insideSoftness: inside,
      outsideSoftness: outside ?? overall ?? window.shape?.outsideSoftness,
    },
  };
}

/**
 * Apply preset softness to a window
 *
 * @param {Object} window - Existing window settings
 * @param {string} preset - Preset name from SOFTNESS_PRESETS
 * @returns {Object} Window with preset softness
 */
function applyPresetSoftness(window, preset) {
  const softness = SOFTNESS_PRESETS[preset.toUpperCase()] ?? SOFTNESS_PRESETS.SOFT;
  return applyWindowSoftness(window, { overall: softness });
}

// ═══════════════════════════════════════════════════════════════════════════
// WINDOW CORRECTOR BUILDER
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Create a complete window corrector ready for encoding
 *
 * @param {Object} window - Window settings from any builder
 * @returns {Object} Corrector object for node-tree-encoder
 */
function createWindowCorrector(window) {
  return {
    typeId: CORRECTOR_TYPE.WINDOW,
    enabled: true,
    values: {
      window,
    },
  };
}

/**
 * Create a windowed correction node (window + primary correction)
 *
 * @param {Object} window - Window settings
 * @param {Object} correction - Primary correction to apply
 * @returns {Object} Node definition with both correctors
 */
function createWindowedCorrectionNode(window, correction) {
  return {
    id: `windowed_node_${Date.now()}`,
    label: 'Windowed Correction',
    enabled: true,
    correctors: [
      createWindowCorrector(window),
      {
        typeId: CORRECTOR_TYPE.PRIMARY,
        enabled: true,
        values: correction,
      },
    ],
  };
}

/**
 * Combine multiple windows (intersect/union)
 *
 * Note: DaVinci Resolve handles multiple windows per node
 * through multiple window correctors. This creates a node
 * with multiple windows.
 *
 * @param {Array} windows - Array of window settings
 * @param {Object} correction - Primary correction to apply
 * @returns {Object} Node with multiple windows
 */
function createMultiWindowNode(windows, correction) {
  const correctors = windows.map((w) => createWindowCorrector(w));

  if (correction) {
    correctors.push({
      typeId: CORRECTOR_TYPE.PRIMARY,
      enabled: true,
      values: correction,
    });
  }

  return {
    id: `multi_window_node_${Date.now()}`,
    label: 'Multi-Window',
    enabled: true,
    correctors,
  };
}

// ═══════════════════════════════════════════════════════════════════════════
// TRACKING DATA (PLACEHOLDER)
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Window tracking data structure (read-only reference)
 *
 * Note: Tracking data is typically generated by Resolve's tracker,
 * not encoded manually. This structure documents the format for
 * potential future use in reading/modifying existing tracking data.
 */
const TRACKING_DATA_STRUCTURE = {
  // Frame-by-frame transform data
  frames: [
    {
      frame: 0,
      panX: 0,
      panY: 0,
      zoomX: 1,
      zoomY: 1,
      rotation: 0,
    },
  ],
  // Tracking type
  type: 'point', // 'point', 'object', 'surface'
  // Source clip reference
  clipId: null,
  // Tracking region
  searchRegion: { x: 0, y: 0, width: 0.2, height: 0.2 },
};

// ═══════════════════════════════════════════════════════════════════════════
// EXPORTS
// ═══════════════════════════════════════════════════════════════════════════

module.exports = {
  // Circular/Oval windows
  createCircularWindow,
  createOvalWindow,
  createVignetteWindow,

  // Linear/Gradient windows
  createLinearWindow,
  createGradientWindow,
  createHorizontalSplit,
  createVerticalSplit,

  // Polygon windows
  createPolygonWindow,
  createRectangleWindow,
  createTriangleWindow,
  createRegularPolygonWindow,

  // Power curve windows
  createPowerCurveWindow,
  createRoundedRectangleWindow,

  // Transform utilities
  applyWindowTransform,
  scaleWindow,
  moveWindow,
  rotateWindow,

  // Softness utilities
  applyWindowSoftness,
  applyPresetSoftness,

  // Corrector builders
  createWindowCorrector,
  createWindowedCorrectionNode,
  createMultiWindowNode,

  // Constants
  ASPECT_RATIOS,
  GRADIENT_DIRECTIONS,
  SOFTNESS_PRESETS,
  TRACKING_DATA_STRUCTURE,
};
