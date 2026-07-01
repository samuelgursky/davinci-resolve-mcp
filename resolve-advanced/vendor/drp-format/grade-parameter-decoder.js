/**
 * DaVinci Resolve Grade Parameter Decoder
 *
 * Comprehensive decoder for extracting color grading parameters from DRP Body data.
 * Maps protobuf field IDs to actual color grading controls including:
 * - Primary color wheels (Lift, Gamma, Gain, Offset)
 * - Primary adjustments (Saturation, Hue, Contrast, Pivot, Luminance Mix)
 * - Log wheels (Shadow, Midtone, Highlight)
 * - Custom curves (RGB, Hue vs Sat, Lum vs Sat, etc.)
 * - Qualifiers (HSL, 3D, Luminance)
 * - Power Windows (Circle, Linear, Polygon, Curve, Gradient)
 *
 * Based on reverse-engineering of DaVinci Resolve 18/19 DRP protobuf format.
 *
 * @module grade-parameter-decoder
 */

const { parseGradeBody, parseProtobuf, initZstd } = require('./grade-node-extractor');

// ═══════════════════════════════════════════════════════════════════════════
// FIELD ID MAPPINGS - Based on Resolve Protobuf Analysis
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Corrector Type IDs (Field 9.Field 1.Field 1)
 */
const CORRECTOR_TYPE = {
  PRIMARY: 1, // Primary color wheels
  CONTRAST: 2, // Contrast adjustment
  SATURATION: 3, // Saturation adjustment
  HUE: 4, // Hue rotation
  LUM_MIX: 5, // Luminance mix
  OFFSET: 6, // Offset wheels
  LOG: 7, // Log wheels (Shadow/Mid/Highlight)
  CURVES: 18, // Custom curves
  QUALIFIER: 20, // HSL Qualifier
  WINDOW: 25, // Power window
  TRACKER: 26, // Tracking data
  OFX: 30, // OFX plugin
  LUT: 40, // LUT reference
};

/**
 * Primary Color Wheel Fields (inside corrector type 1)
 *
 * Each wheel has 4 floats: R, G, B, Master
 * Neutral values are 1.0 for master, 0.0 for RGB offsets
 */
const PRIMARY_WHEELS = {
  // Lift wheel - affects shadows
  LIFT_R: { field: 1, subfield: 1, neutral: 0.0 },
  LIFT_G: { field: 1, subfield: 2, neutral: 0.0 },
  LIFT_B: { field: 1, subfield: 3, neutral: 0.0 },
  LIFT_MASTER: { field: 1, subfield: 4, neutral: 1.0 },

  // Gamma wheel - affects midtones
  GAMMA_R: { field: 2, subfield: 1, neutral: 0.0 },
  GAMMA_G: { field: 2, subfield: 2, neutral: 0.0 },
  GAMMA_B: { field: 2, subfield: 3, neutral: 0.0 },
  GAMMA_MASTER: { field: 2, subfield: 4, neutral: 1.0 },

  // Gain wheel - affects highlights
  GAIN_R: { field: 3, subfield: 1, neutral: 0.0 },
  GAIN_G: { field: 3, subfield: 2, neutral: 0.0 },
  GAIN_B: { field: 3, subfield: 3, neutral: 0.0 },
  GAIN_MASTER: { field: 3, subfield: 4, neutral: 1.0 },

  // Offset wheel - global offset
  OFFSET_R: { field: 4, subfield: 1, neutral: 0.0 },
  OFFSET_G: { field: 4, subfield: 2, neutral: 0.0 },
  OFFSET_B: { field: 4, subfield: 3, neutral: 0.0 },
  OFFSET_MASTER: { field: 4, subfield: 4, neutral: 0.0 },
};

/**
 * Primary Adjustment Fields
 */
const PRIMARY_ADJUSTMENTS = {
  CONTRAST: { field: 5, neutral: 1.0, range: [0.0, 4.0] },
  PIVOT: { field: 6, neutral: 0.435, range: [0.0, 1.0] },
  SATURATION: { field: 7, neutral: 50.0, range: [0.0, 100.0] },
  HUE: { field: 8, neutral: 50.0, range: [0.0, 100.0] },
  LUM_MIX: { field: 9, neutral: 0.0, range: [0.0, 100.0] },
  MIDTONE_DETAIL: { field: 10, neutral: 0.0, range: [-100.0, 100.0] },
  COLOR_BOOST: { field: 11, neutral: 0.0, range: [0.0, 100.0] },
  SHADOW_SAT: { field: 12, neutral: 50.0, range: [0.0, 100.0] },
  HIGHLIGHT_SAT: { field: 13, neutral: 50.0, range: [0.0, 100.0] },
};

/**
 * Log Wheel Fields (inside corrector type 7)
 */
const LOG_WHEELS = {
  // Shadow wheel
  SHADOW_R: { field: 1, subfield: 1, neutral: 0.0 },
  SHADOW_G: { field: 1, subfield: 2, neutral: 0.0 },
  SHADOW_B: { field: 1, subfield: 3, neutral: 0.0 },
  SHADOW_MASTER: { field: 1, subfield: 4, neutral: 0.0 },

  // Midtone wheel
  MIDTONE_R: { field: 2, subfield: 1, neutral: 0.0 },
  MIDTONE_G: { field: 2, subfield: 2, neutral: 0.0 },
  MIDTONE_B: { field: 2, subfield: 3, neutral: 0.0 },
  MIDTONE_MASTER: { field: 2, subfield: 4, neutral: 0.0 },

  // Highlight wheel
  HIGHLIGHT_R: { field: 3, subfield: 1, neutral: 0.0 },
  HIGHLIGHT_G: { field: 3, subfield: 2, neutral: 0.0 },
  HIGHLIGHT_B: { field: 3, subfield: 3, neutral: 0.0 },
  HIGHLIGHT_MASTER: { field: 3, subfield: 4, neutral: 0.0 },

  // Log adjustments
  LOW_RANGE: { field: 4, neutral: 0.0 },
  HIGH_RANGE: { field: 5, neutral: 1.0 },
};

/**
 * Curve Types (inside corrector type 18)
 */
const CURVE_TYPES = {
  CUSTOM: 1, // Luminance/overall curve
  RED: 2, // Red channel curve
  GREEN: 3, // Green channel curve
  BLUE: 4, // Blue channel curve
  HUE_VS_HUE: 5, // Hue vs Hue
  HUE_VS_SAT: 6, // Hue vs Saturation
  HUE_VS_LUM: 7, // Hue vs Luminance
  LUM_VS_SAT: 8, // Luminance vs Saturation
  SAT_VS_SAT: 9, // Saturation vs Saturation
  SAT_VS_LUM: 10, // Saturation vs Luminance
};

/**
 * HSL Qualifier Fields (inside corrector type 20)
 */
const HSL_QUALIFIER = {
  ENABLED: { field: 1, neutral: false },

  // Hue range
  HUE_CENTER: { field: 2, neutral: 0.0, range: [0.0, 360.0] },
  HUE_WIDTH: { field: 3, neutral: 30.0, range: [0.0, 180.0] },
  HUE_SOFT: { field: 4, neutral: 0.0, range: [0.0, 100.0] },

  // Saturation range
  SAT_LOW: { field: 5, neutral: 0.0, range: [0.0, 100.0] },
  SAT_HIGH: { field: 6, neutral: 100.0, range: [0.0, 100.0] },
  SAT_LOW_SOFT: { field: 7, neutral: 0.0, range: [0.0, 100.0] },
  SAT_HIGH_SOFT: { field: 8, neutral: 0.0, range: [0.0, 100.0] },

  // Luminance range
  LUM_LOW: { field: 9, neutral: 0.0, range: [0.0, 100.0] },
  LUM_HIGH: { field: 10, neutral: 100.0, range: [0.0, 100.0] },
  LUM_LOW_SOFT: { field: 11, neutral: 0.0, range: [0.0, 100.0] },
  LUM_HIGH_SOFT: { field: 12, neutral: 0.0, range: [0.0, 100.0] },

  // Matte options
  INVERT: { field: 13, neutral: false },
  MATTE_FINESSE: { field: 14, neutral: 0.0, range: [0.0, 100.0] },
  DENOISE: { field: 15, neutral: 0.0, range: [0.0, 100.0] },
  SHRINK_GROW: { field: 16, neutral: 0.0, range: [-100.0, 100.0] },
};

/**
 * Power Window Types (inside corrector type 25)
 */
const WINDOW_TYPES = {
  CIRCLE: 1,
  LINEAR: 2,
  POLYGON: 3,
  CURVE: 4,
  GRADIENT: 5,
};

/**
 * Power Window Fields
 */
const WINDOW_FIELDS = {
  TYPE: { field: 1 },
  ENABLED: { field: 2, neutral: true },

  // Transform
  PAN_X: { field: 3, neutral: 0.0 },
  PAN_Y: { field: 4, neutral: 0.0 },
  ZOOM_X: { field: 5, neutral: 1.0 },
  ZOOM_Y: { field: 6, neutral: 1.0 },
  ROTATION: { field: 7, neutral: 0.0 },
  ANCHOR_X: { field: 8, neutral: 0.5 },
  ANCHOR_Y: { field: 9, neutral: 0.5 },

  // Circle/Linear specific
  RADIUS_X: { field: 10, neutral: 0.25 },
  RADIUS_Y: { field: 11, neutral: 0.25 },
  SOFTNESS: { field: 12, neutral: 0.0 },
  INSIDE_SOFTNESS: { field: 13, neutral: 0.0 },
  OUTSIDE_SOFTNESS: { field: 14, neutral: 0.0 },

  // Linear specific
  ANGLE: { field: 15, neutral: 0.0 },
  POSITION: { field: 16, neutral: 0.5 },

  // Polygon/Curve specific
  POINTS: { field: 20 }, // Nested array of points

  // Common
  INVERT: { field: 30, neutral: false },
};

// ═══════════════════════════════════════════════════════════════════════════
// DECODER FUNCTIONS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Decode color wheels from corrector parameters
 *
 * @param {Array} fields - Parsed protobuf fields from corrector
 * @param {Object} wheelDef - Wheel field definitions (PRIMARY_WHEELS or LOG_WHEELS)
 * @returns {Object} Decoded wheel values
 */
function decodeColorWheels(fields, wheelDef) {
  const wheels = {};

  // Group fields by wheel number
  const wheelFields = {};
  for (const field of fields) {
    if (!wheelFields[field.fieldNum]) {
      wheelFields[field.fieldNum] = [];
    }
    wheelFields[field.fieldNum].push(field);
  }

  // Extract each wheel's values
  for (const [name, def] of Object.entries(wheelDef)) {
    const wheelField = wheelFields[def.field];
    if (wheelField && wheelField[0]?.nested) {
      const subFields = wheelField[0].nested;
      for (const sf of subFields) {
        if (sf.fieldNum === def.subfield && (sf.type === 'float' || sf.type === 'double')) {
          wheels[name] = sf.value;
        }
      }
    }

    // Default to neutral if not found
    if (wheels[name] === undefined) {
      wheels[name] = def.neutral;
    }
  }

  return wheels;
}

/**
 * Decode primary adjustments from corrector parameters
 *
 * @param {Array} fields - Parsed protobuf fields
 * @returns {Object} Decoded adjustment values
 */
function decodePrimaryAdjustments(fields) {
  const adjustments = {};

  for (const [name, def] of Object.entries(PRIMARY_ADJUSTMENTS)) {
    const field = fields.find((f) => f.fieldNum === def.field);
    if (field && (field.type === 'float' || field.type === 'double')) {
      adjustments[name] = field.value;
    } else {
      adjustments[name] = def.neutral;
    }
  }

  return adjustments;
}

/**
 * Decode HSL qualifier settings
 *
 * @param {Array} fields - Parsed protobuf fields from qualifier corrector
 * @returns {Object} Decoded qualifier settings
 */
function decodeHSLQualifier(fields) {
  const qualifier = {};

  for (const [name, def] of Object.entries(HSL_QUALIFIER)) {
    const field = fields.find((f) => f.fieldNum === def.field);

    if (field) {
      if (def.neutral === false || def.neutral === true) {
        qualifier[name] = field.value === 1;
      } else if (field.type === 'float' || field.type === 'double') {
        qualifier[name] = field.value;
      } else if (field.type === 'varint') {
        qualifier[name] = field.value;
      }
    } else {
      qualifier[name] = def.neutral;
    }
  }

  return qualifier;
}

/**
 * Decode power window settings
 *
 * @param {Array} fields - Parsed protobuf fields from window corrector
 * @returns {Object} Decoded window settings
 */
function decodePowerWindow(fields) {
  const window = {
    type: 'unknown',
    enabled: true,
    transform: {},
    shape: {},
    invert: false,
  };

  for (const field of fields) {
    switch (field.fieldNum) {
      case WINDOW_FIELDS.TYPE.field:
        window.type = Object.keys(WINDOW_TYPES).find(
          (k) => WINDOW_TYPES[k] === field.value
        ) || 'unknown';
        break;
      case WINDOW_FIELDS.ENABLED.field:
        window.enabled = field.value === 1;
        break;
      case WINDOW_FIELDS.PAN_X.field:
        window.transform.panX = field.value;
        break;
      case WINDOW_FIELDS.PAN_Y.field:
        window.transform.panY = field.value;
        break;
      case WINDOW_FIELDS.ZOOM_X.field:
        window.transform.zoomX = field.value;
        break;
      case WINDOW_FIELDS.ZOOM_Y.field:
        window.transform.zoomY = field.value;
        break;
      case WINDOW_FIELDS.ROTATION.field:
        window.transform.rotation = field.value;
        break;
      case WINDOW_FIELDS.RADIUS_X.field:
        window.shape.radiusX = field.value;
        break;
      case WINDOW_FIELDS.RADIUS_Y.field:
        window.shape.radiusY = field.value;
        break;
      case WINDOW_FIELDS.SOFTNESS.field:
        window.shape.softness = field.value;
        break;
      case WINDOW_FIELDS.INSIDE_SOFTNESS.field:
        window.shape.insideSoftness = field.value;
        break;
      case WINDOW_FIELDS.OUTSIDE_SOFTNESS.field:
        window.shape.outsideSoftness = field.value;
        break;
      case WINDOW_FIELDS.ANGLE.field:
        window.shape.angle = field.value;
        break;
      case WINDOW_FIELDS.POSITION.field:
        window.shape.position = field.value;
        break;
      case WINDOW_FIELDS.POINTS.field:
        if (field.nested) {
          window.shape.points = decodeWindowPoints(field.nested);
        }
        break;
      case WINDOW_FIELDS.INVERT.field:
        window.invert = field.value === 1;
        break;
    }
  }

  return window;
}

/**
 * Decode window polygon/curve points
 *
 * @param {Array} fields - Nested point data
 * @returns {Array} Array of {x, y} points
 */
function decodeWindowPoints(fields) {
  const points = [];

  for (const field of fields) {
    if (field.nested) {
      const point = { x: 0, y: 0 };
      for (const pf of field.nested) {
        if (pf.fieldNum === 1) point.x = pf.value;
        if (pf.fieldNum === 2) point.y = pf.value;
      }
      points.push(point);
    }
  }

  return points;
}

/**
 * Decode curve control points
 *
 * @param {Array} fields - Curve data fields
 * @returns {Object} Curve definition with type and points
 */
function decodeCurve(fields) {
  const curve = {
    type: 'CUSTOM',
    enabled: true,
    points: [],
    interpolation: 'bezier',
  };

  for (const field of fields) {
    switch (field.fieldNum) {
      case 1:
        curve.type = Object.keys(CURVE_TYPES).find(
          (k) => CURVE_TYPES[k] === field.value
        ) || 'CUSTOM';
        break;
      case 2:
        curve.enabled = field.value === 1;
        break;
      case 3:
        if (field.nested) {
          curve.points = decodeCurvePoints(field.nested);
        }
        break;
      case 4:
        curve.interpolation = field.value === 1 ? 'linear' : 'bezier';
        break;
    }
  }

  return curve;
}

/**
 * Decode curve control points with handles
 *
 * @param {Array} fields - Point data
 * @returns {Array} Array of curve points with handles
 */
function decodeCurvePoints(fields) {
  const points = [];

  for (const field of fields) {
    if (field.nested) {
      const point = {
        x: 0,
        y: 0,
        handleInX: 0,
        handleInY: 0,
        handleOutX: 0,
        handleOutY: 0,
      };

      for (const pf of field.nested) {
        switch (pf.fieldNum) {
          case 1: point.x = pf.value; break;
          case 2: point.y = pf.value; break;
          case 3: point.handleInX = pf.value; break;
          case 4: point.handleInY = pf.value; break;
          case 5: point.handleOutX = pf.value; break;
          case 6: point.handleOutY = pf.value; break;
        }
      }

      points.push(point);
    }
  }

  return points;
}

/**
 * Decode a complete color corrector node
 *
 * @param {Object} corrector - Corrector data from grade-node-extractor
 * @returns {Object} Fully decoded corrector with all parameters
 */
function decodeCorrector(corrector) {
  const decoded = {
    type: corrector.type,
    typeId: corrector.typeId,
    enabled: corrector.enabled,
    values: {},
  };

  switch (corrector.typeId) {
    case CORRECTOR_TYPE.PRIMARY:
      decoded.values.wheels = decodeColorWheels(corrector.values || [], PRIMARY_WHEELS);
      break;

    case CORRECTOR_TYPE.LOG:
      decoded.values.wheels = decodeColorWheels(corrector.values || [], LOG_WHEELS);
      break;

    case CORRECTOR_TYPE.CONTRAST:
    case CORRECTOR_TYPE.SATURATION:
    case CORRECTOR_TYPE.HUE:
    case CORRECTOR_TYPE.LUM_MIX:
    case CORRECTOR_TYPE.OFFSET:
      decoded.values = decodePrimaryAdjustments(corrector.values || []);
      break;

    case CORRECTOR_TYPE.CURVES:
      decoded.values.curves = [];
      for (const field of corrector.values || []) {
        if (field.nested) {
          decoded.values.curves.push(decodeCurve(field.nested));
        }
      }
      break;

    case CORRECTOR_TYPE.QUALIFIER:
      decoded.values.qualifier = decodeHSLQualifier(corrector.values || []);
      break;

    case CORRECTOR_TYPE.WINDOW:
      decoded.values.window = decodePowerWindow(corrector.values || []);
      break;

    case CORRECTOR_TYPE.LUT:
      decoded.values.lut = decodeLUTReference(corrector.values || []);
      break;

    default:
      // Keep raw values for unknown types
      decoded.values.raw = corrector.values;
  }

  return decoded;
}

/**
 * Decode LUT reference
 *
 * @param {Array} fields - LUT corrector fields
 * @returns {Object} LUT reference with path and strength
 */
function decodeLUTReference(fields) {
  const lut = {
    path: null,
    strength: 1.0,
    inputColorSpace: null,
    outputColorSpace: null,
  };

  for (const field of fields) {
    switch (field.fieldNum) {
      case 1:
        if (field.raw) {
          lut.path = field.raw.toString('utf-8').replace(/\x00/g, '');
        }
        break;
      case 2:
        lut.strength = field.value;
        break;
      case 3:
        if (field.raw) {
          lut.inputColorSpace = field.raw.toString('utf-8').replace(/\x00/g, '');
        }
        break;
      case 4:
        if (field.raw) {
          lut.outputColorSpace = field.raw.toString('utf-8').replace(/\x00/g, '');
        }
        break;
    }
  }

  return lut;
}

/**
 * Decode all parameters from a grade body
 *
 * @param {string} hexData - Hex-encoded Body data from DRP
 * @returns {Promise<Object>} Complete decoded grade data
 */
async function decodeGradeParameters(hexData) {
  const gradeData = await parseGradeBody(hexData);

  const decoded = {
    nodes: [],
    connections: gradeData.connections || [],
    metadata: {
      nodeCount: gradeData.nodes?.length || 0,
      hasCorrections: false,
    },
  };

  for (const node of gradeData.nodes || []) {
    const decodedNode = {
      id: node.id,
      index: node.index,
      label: node.label,
      posX: node.posX,
      posY: node.posY,
      enabled: node.enabled,
      timestamp: node.timestamp,
      correctors: [],
    };

    for (const param of node.parameters || []) {
      const decodedCorrector = decodeCorrector(param);
      decodedNode.correctors.push(decodedCorrector);

      // Check if any correction is non-neutral
      if (decodedCorrector.enabled && hasNonNeutralValues(decodedCorrector)) {
        decoded.metadata.hasCorrections = true;
      }
    }

    decoded.nodes.push(decodedNode);
  }

  return decoded;
}

/**
 * Check if a corrector has non-neutral values
 *
 * @param {Object} corrector - Decoded corrector
 * @returns {boolean} True if corrector has adjustments
 */
function hasNonNeutralValues(corrector) {
  const values = corrector.values;

  // Check wheels
  if (values.wheels) {
    for (const [key, value] of Object.entries(values.wheels)) {
      const def = PRIMARY_WHEELS[key] || LOG_WHEELS[key];
      if (def && Math.abs(value - def.neutral) > 0.001) {
        return true;
      }
    }
  }

  // Check adjustments
  for (const [key, def] of Object.entries(PRIMARY_ADJUSTMENTS)) {
    if (values[key] !== undefined && Math.abs(values[key] - def.neutral) > 0.001) {
      return true;
    }
  }

  // Check curves
  if (values.curves?.length > 0) {
    for (const curve of values.curves) {
      if (curve.points?.length > 2) return true;
    }
  }

  // Check qualifier
  if (values.qualifier?.ENABLED) {
    return true;
  }

  // Check window
  if (values.window?.enabled) {
    return true;
  }

  // Check LUT
  if (values.lut?.path) {
    return true;
  }

  return false;
}

/**
 * Format decoded parameters for display
 *
 * @param {Object} decoded - Decoded grade data
 * @returns {string} Human-readable format
 */
function formatDecodedGrade(decoded) {
  const lines = [];

  lines.push(`Grade Data (${decoded.nodes.length} nodes)`);
  lines.push(`Has Corrections: ${decoded.metadata.hasCorrections}`);
  lines.push('');

  for (const node of decoded.nodes) {
    lines.push(`═══ Node ${node.id} (${node.label || 'Unlabeled'}) ═══`);
    lines.push(`  Enabled: ${node.enabled}`);
    lines.push(`  Position: (${node.posX}, ${node.posY})`);

    for (const corrector of node.correctors) {
      lines.push(`  ─── ${corrector.type} (${corrector.enabled ? 'ON' : 'OFF'}) ───`);

      if (corrector.values.wheels) {
        lines.push('    Wheels:');
        for (const [name, value] of Object.entries(corrector.values.wheels)) {
          if (typeof value === 'number' && Math.abs(value) > 0.001) {
            lines.push(`      ${name}: ${value.toFixed(4)}`);
          }
        }
      }

      if (corrector.values.qualifier) {
        lines.push('    HSL Qualifier:');
        const q = corrector.values.qualifier;
        lines.push(`      Hue: ${q.HUE_CENTER}° ± ${q.HUE_WIDTH}°`);
        lines.push(`      Sat: ${q.SAT_LOW}-${q.SAT_HIGH}`);
        lines.push(`      Lum: ${q.LUM_LOW}-${q.LUM_HIGH}`);
      }

      if (corrector.values.window) {
        const w = corrector.values.window;
        lines.push(`    Window: ${w.type}`);
        lines.push(`      Pan: (${w.transform.panX?.toFixed(3)}, ${w.transform.panY?.toFixed(3)})`);
        lines.push(`      Zoom: (${w.transform.zoomX?.toFixed(3)}, ${w.transform.zoomY?.toFixed(3)})`);
        lines.push(`      Rotation: ${w.transform.rotation?.toFixed(1)}°`);
      }

      if (corrector.values.curves?.length > 0) {
        lines.push(`    Curves: ${corrector.values.curves.length}`);
        for (const curve of corrector.values.curves) {
          lines.push(`      ${curve.type}: ${curve.points.length} points`);
        }
      }

      if (corrector.values.lut?.path) {
        lines.push(`    LUT: ${corrector.values.lut.path}`);
        lines.push(`      Strength: ${corrector.values.lut.strength}`);
      }
    }

    lines.push('');
  }

  if (decoded.connections.length > 0) {
    lines.push('Connections:');
    for (const conn of decoded.connections) {
      lines.push(`  Node ${conn.sourceNode} → Node ${conn.targetNode}`);
    }
  }

  return lines.join('\n');
}

// ═══════════════════════════════════════════════════════════════════════════
// EXPORTS
// ═══════════════════════════════════════════════════════════════════════════

module.exports = {
  // Main decoder
  decodeGradeParameters,

  // Sub-decoders
  decodeColorWheels,
  decodePrimaryAdjustments,
  decodeHSLQualifier,
  decodePowerWindow,
  decodeCurve,
  decodeLUTReference,
  decodeCorrector,

  // Utilities
  hasNonNeutralValues,
  formatDecodedGrade,

  // Constants
  CORRECTOR_TYPE,
  PRIMARY_WHEELS,
  PRIMARY_ADJUSTMENTS,
  LOG_WHEELS,
  CURVE_TYPES,
  HSL_QUALIFIER,
  WINDOW_TYPES,
  WINDOW_FIELDS,
};
