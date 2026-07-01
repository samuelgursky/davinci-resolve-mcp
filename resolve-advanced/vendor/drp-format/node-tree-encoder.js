/**
 * DaVinci Resolve Node Tree Encoder
 *
 * Comprehensive encoder for color grading node trees including:
 * - Serial node chains
 * - Parallel node layers
 * - Layer mixers with blend modes
 * - All corrector types (wheels, curves, qualifiers, windows, LUTs)
 *
 * This is the encoding counterpart to grade-parameter-decoder.js,
 * enabling full round-trip encoding/decoding of grade data.
 *
 * Based on reverse-engineering of DaVinci Resolve 18/19 DRP protobuf format.
 *
 * @module node-tree-encoder
 */

const {
  encodeVarint,
  encodeFloat,
  encodeDouble,
  encodeTag,
} = require('./grade-encoder');

const {
  CORRECTOR_TYPE,
  PRIMARY_WHEELS,
  PRIMARY_ADJUSTMENTS,
  LOG_WHEELS,
  CURVE_TYPES,
  HSL_QUALIFIER,
  WINDOW_TYPES,
  WINDOW_FIELDS,
} = require('./grade-parameter-decoder');

// ═══════════════════════════════════════════════════════════════════════════
// NODE GRAPH ENCODING
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Connection types for node graph
 */
const CONNECTION_TYPE = {
  SERIAL: 1, // Output → Input
  PARALLEL_IN: 2, // Parallel merge input
  PARALLEL_OUT: 3, // Parallel branch output
  LAYER_INPUT: 4, // Layer node input
  KEY_INPUT: 5, // Key/alpha input
};

/**
 * Layer blend modes
 */
const BLEND_MODE = {
  NORMAL: 1,
  ADD: 2,
  SUBTRACT: 3,
  MULTIPLY: 4,
  OVERLAY: 5,
  SOFT_LIGHT: 6,
  HARD_LIGHT: 7,
  COLOR: 8,
  LUMINOSITY: 9,
  DIFFERENCE: 10,
  EXCLUSION: 11,
};

/**
 * Encode a complete node graph
 *
 * @param {Object} graph - Node graph structure
 * @param {Array} graph.nodes - Array of node definitions
 * @param {Array} graph.connections - Array of node connections
 * @param {Object} graph.metadata - Graph metadata
 * @returns {string} Hex-encoded graph data
 */
function encodeNodeGraph(graph) {
  const parts = [];

  // Field 1: Version (varint = 1)
  parts.push(encodeTag(1, 0).toString('hex'));
  parts.push(encodeVarint(1).toString('hex'));

  // Field 2: Node count (varint)
  parts.push(encodeTag(2, 0).toString('hex'));
  parts.push(encodeVarint(graph.nodes?.length || 0).toString('hex'));

  // Field 3: Nodes (repeated length-delimited)
  for (const node of graph.nodes || []) {
    const nodeData = encodeNode(node);
    parts.push(encodeTag(3, 2).toString('hex'));
    parts.push(encodeVarint(nodeData.length / 2).toString('hex'));
    parts.push(nodeData);
  }

  // Field 4: Connections (repeated length-delimited)
  for (const conn of graph.connections || []) {
    const connData = encodeConnection(conn);
    parts.push(encodeTag(4, 2).toString('hex'));
    parts.push(encodeVarint(connData.length / 2).toString('hex'));
    parts.push(connData);
  }

  // Field 5: Graph type flags
  if (graph.metadata?.isParallel) {
    parts.push(encodeTag(5, 0).toString('hex'));
    parts.push(encodeVarint(1).toString('hex'));
  }

  // Field 6: Has layer mixer
  if (graph.metadata?.hasLayerMixer) {
    parts.push(encodeTag(6, 0).toString('hex'));
    parts.push(encodeVarint(1).toString('hex'));
  }

  return parts.join('');
}

/**
 * Encode a single color node
 *
 * @param {Object} node - Node definition
 * @param {string} node.id - Unique node ID
 * @param {number} node.index - Node index in graph
 * @param {string} node.label - Node label
 * @param {number} node.posX - X position
 * @param {number} node.posY - Y position
 * @param {boolean} node.enabled - Node enabled state
 * @param {Array} node.correctors - Array of corrector data
 * @returns {string} Hex-encoded node data
 */
function encodeNode(node) {
  const parts = [];

  // Field 1: Node ID (length-delimited string)
  if (node.id) {
    const idBytes = Buffer.from(node.id, 'utf-8');
    parts.push(encodeTag(1, 2).toString('hex'));
    parts.push(encodeVarint(idBytes.length).toString('hex'));
    parts.push(idBytes.toString('hex'));
  }

  // Field 2: Node index (varint)
  parts.push(encodeTag(2, 0).toString('hex'));
  parts.push(encodeVarint(node.index || 0).toString('hex'));

  // Field 3: Label (length-delimited string)
  if (node.label) {
    const labelBytes = Buffer.from(node.label, 'utf-8');
    parts.push(encodeTag(3, 2).toString('hex'));
    parts.push(encodeVarint(labelBytes.length).toString('hex'));
    parts.push(labelBytes.toString('hex'));
  }

  // Field 4: Position X (float)
  parts.push(encodeTag(4, 5).toString('hex'));
  parts.push(encodeFloat(node.posX || 0));

  // Field 5: Position Y (float)
  parts.push(encodeTag(5, 5).toString('hex'));
  parts.push(encodeFloat(node.posY || 0));

  // Field 6: Enabled (varint boolean)
  parts.push(encodeTag(6, 0).toString('hex'));
  parts.push(encodeVarint(node.enabled !== false ? 1 : 0).toString('hex'));

  // Field 7: Timestamp (varint)
  parts.push(encodeTag(7, 0).toString('hex'));
  parts.push(encodeVarint(node.timestamp || Date.now() * 1000).toString('hex'));

  // Field 8: Correctors (repeated length-delimited)
  for (const corrector of node.correctors || []) {
    const correctorData = encodeCorrector(corrector);
    parts.push(encodeTag(8, 2).toString('hex'));
    parts.push(encodeVarint(correctorData.length / 2).toString('hex'));
    parts.push(correctorData);
  }

  return parts.join('');
}

/**
 * Encode a node connection
 *
 * @param {Object} conn - Connection definition
 * @param {number} conn.sourceNode - Source node index
 * @param {number} conn.sourceOutput - Source output index
 * @param {number} conn.targetNode - Target node index
 * @param {number} conn.targetInput - Target input index
 * @param {number} conn.type - Connection type
 * @returns {string} Hex-encoded connection data
 */
function encodeConnection(conn) {
  const parts = [];

  // Field 1: Source node (varint)
  parts.push(encodeTag(1, 0).toString('hex'));
  parts.push(encodeVarint(conn.sourceNode).toString('hex'));

  // Field 2: Source output (varint)
  parts.push(encodeTag(2, 0).toString('hex'));
  parts.push(encodeVarint(conn.sourceOutput || 0).toString('hex'));

  // Field 3: Target node (varint)
  parts.push(encodeTag(3, 0).toString('hex'));
  parts.push(encodeVarint(conn.targetNode).toString('hex'));

  // Field 4: Target input (varint)
  parts.push(encodeTag(4, 0).toString('hex'));
  parts.push(encodeVarint(conn.targetInput || 0).toString('hex'));

  // Field 5: Connection type (varint)
  if (conn.type) {
    parts.push(encodeTag(5, 0).toString('hex'));
    parts.push(encodeVarint(conn.type).toString('hex'));
  }

  return parts.join('');
}

/**
 * Create a serial node chain (standard left-to-right node layout)
 *
 * @param {Array} nodes - Array of node definitions
 * @param {Object} options - Chain options
 * @returns {Object} Complete graph with nodes and connections
 */
function encodeSerialNodes(nodes, options = {}) {
  const { startX = 0, spacing = 1.0 } = options;

  const graph = {
    nodes: [],
    connections: [],
    metadata: { isParallel: false },
  };

  // Position nodes in a row
  nodes.forEach((node, index) => {
    graph.nodes.push({
      ...node,
      index,
      posX: startX + index * spacing,
      posY: 0,
    });

    // Connect to previous node
    if (index > 0) {
      graph.connections.push({
        sourceNode: index - 1,
        sourceOutput: 0,
        targetNode: index,
        targetInput: 0,
        type: CONNECTION_TYPE.SERIAL,
      });
    }
  });

  return graph;
}

/**
 * Create parallel node layers
 *
 * @param {Array} layers - Array of node arrays (each array is a layer)
 * @param {Object} options - Layer options
 * @returns {Object} Complete graph with parallel structure
 */
function encodeParallelNodes(layers, options = {}) {
  const { startX = 0, xSpacing = 1.0, ySpacing = 0.5 } = options;

  const graph = {
    nodes: [],
    connections: [],
    metadata: { isParallel: true },
  };

  let nodeIndex = 0;
  let lastLayerEndIndices = [];

  layers.forEach((layer, layerIndex) => {
    const layerStartIndex = nodeIndex;
    const layerEndIndices = [];

    // Add nodes in this layer
    layer.forEach((node, nodeInLayer) => {
      graph.nodes.push({
        ...node,
        index: nodeIndex,
        posX: startX + layerIndex * xSpacing,
        posY: nodeInLayer * ySpacing - ((layer.length - 1) * ySpacing) / 2,
      });
      layerEndIndices.push(nodeIndex);
      nodeIndex++;
    });

    // Connect from previous layer
    if (layerIndex > 0 && lastLayerEndIndices.length > 0) {
      // Connect each node in previous layer to first node in this layer
      lastLayerEndIndices.forEach((srcIndex) => {
        graph.connections.push({
          sourceNode: srcIndex,
          sourceOutput: 0,
          targetNode: layerStartIndex,
          targetInput: graph.connections.length,
          type: CONNECTION_TYPE.PARALLEL_OUT,
        });
      });
    }

    lastLayerEndIndices = layerEndIndices;
  });

  return graph;
}

/**
 * Encode a layer mixer node
 *
 * @param {Array} layers - Input layer indices
 * @param {Object} options - Mixer options
 * @param {number} options.blendMode - Blend mode (BLEND_MODE enum)
 * @param {number} options.opacity - Layer opacity (0-1)
 * @returns {string} Hex-encoded layer mixer data
 */
function encodeLayerMixer(layers, options = {}) {
  const { blendMode = BLEND_MODE.NORMAL, opacity = 1.0 } = options;

  const parts = [];

  // Field 1: Type = Layer Mixer
  parts.push(encodeTag(1, 0).toString('hex'));
  parts.push(encodeVarint(100).toString('hex')); // Layer mixer type ID

  // Field 2: Blend mode (varint)
  parts.push(encodeTag(2, 0).toString('hex'));
  parts.push(encodeVarint(blendMode).toString('hex'));

  // Field 3: Opacity (float)
  parts.push(encodeTag(3, 5).toString('hex'));
  parts.push(encodeFloat(opacity));

  // Field 4: Input layer count (varint)
  parts.push(encodeTag(4, 0).toString('hex'));
  parts.push(encodeVarint(layers.length).toString('hex'));

  // Field 5: Input layer indices (repeated varint)
  for (const layerIndex of layers) {
    parts.push(encodeTag(5, 0).toString('hex'));
    parts.push(encodeVarint(layerIndex).toString('hex'));
  }

  return parts.join('');
}

// ═══════════════════════════════════════════════════════════════════════════
// CORRECTOR ENCODING
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Encode a complete corrector
 *
 * @param {Object} corrector - Corrector definition
 * @param {number} corrector.typeId - Corrector type (CORRECTOR_TYPE enum)
 * @param {boolean} corrector.enabled - Enabled state
 * @param {Object} corrector.values - Corrector values
 * @returns {string} Hex-encoded corrector data
 */
function encodeCorrector(corrector) {
  const parts = [];

  // Field 1: Type ID (varint)
  parts.push(encodeTag(1, 0).toString('hex'));
  parts.push(encodeVarint(corrector.typeId || CORRECTOR_TYPE.PRIMARY).toString('hex'));

  // Field 2: Enabled (varint boolean)
  parts.push(encodeTag(2, 0).toString('hex'));
  parts.push(encodeVarint(corrector.enabled !== false ? 1 : 0).toString('hex'));

  // Field 3: Values (type-specific nested data)
  let valuesData = '';

  switch (corrector.typeId) {
    case CORRECTOR_TYPE.PRIMARY:
      valuesData = encodeColorWheels(corrector.values?.wheels, PRIMARY_WHEELS);
      break;

    case CORRECTOR_TYPE.LOG:
      valuesData = encodeColorWheels(corrector.values?.wheels, LOG_WHEELS);
      break;

    case CORRECTOR_TYPE.CONTRAST:
    case CORRECTOR_TYPE.SATURATION:
    case CORRECTOR_TYPE.HUE:
    case CORRECTOR_TYPE.LUM_MIX:
    case CORRECTOR_TYPE.OFFSET:
      valuesData = encodePrimaryAdjustments(corrector.values);
      break;

    case CORRECTOR_TYPE.CURVES:
      valuesData = encodeCurves(corrector.values?.curves || []);
      break;

    case CORRECTOR_TYPE.QUALIFIER:
      valuesData = encodeHSLQualifier(corrector.values?.qualifier || {});
      break;

    case CORRECTOR_TYPE.WINDOW:
      valuesData = encodePowerWindow(corrector.values?.window || {});
      break;

    case CORRECTOR_TYPE.LUT:
      valuesData = encodeLUTReference(corrector.values?.lut || {});
      break;

    default:
      // Unknown type - skip values
      break;
  }

  if (valuesData) {
    parts.push(encodeTag(3, 2).toString('hex'));
    parts.push(encodeVarint(valuesData.length / 2).toString('hex'));
    parts.push(valuesData);
  }

  return parts.join('');
}

/**
 * Encode color wheels (Primary or Log)
 *
 * @param {Object} wheels - Wheel values keyed by name (e.g., LIFT_R, GAMMA_MASTER)
 * @param {Object} wheelDef - Wheel field definitions
 * @returns {string} Hex-encoded wheel data
 */
function encodeColorWheels(wheels, wheelDef) {
  const parts = [];

  // Group by field number (wheel type)
  const wheelGroups = {};

  for (const [name, def] of Object.entries(wheelDef)) {
    if (!wheelGroups[def.field]) {
      wheelGroups[def.field] = [];
    }
    wheelGroups[def.field].push({ name, def });
  }

  // Encode each wheel group
  for (const [fieldNum, entries] of Object.entries(wheelGroups)) {
    const wheelData = [];

    for (const { name, def } of entries) {
      const value = wheels?.[name] ?? def.neutral;

      // Encode subfield
      wheelData.push(encodeTag(def.subfield, 5).toString('hex'));
      wheelData.push(encodeFloat(value));
    }

    if (wheelData.length > 0) {
      const wheelDataStr = wheelData.join('');
      parts.push(encodeTag(parseInt(fieldNum), 2).toString('hex'));
      parts.push(encodeVarint(wheelDataStr.length / 2).toString('hex'));
      parts.push(wheelDataStr);
    }
  }

  return parts.join('');
}

/**
 * Encode primary adjustments
 *
 * @param {Object} adjustments - Adjustment values keyed by name
 * @returns {string} Hex-encoded adjustment data
 */
function encodePrimaryAdjustments(adjustments) {
  const parts = [];

  for (const [name, def] of Object.entries(PRIMARY_ADJUSTMENTS)) {
    const value = adjustments?.[name] ?? def.neutral;

    // Only encode non-neutral values
    if (Math.abs(value - def.neutral) > 0.0001) {
      parts.push(encodeTag(def.field, 5).toString('hex'));
      parts.push(encodeFloat(value));
    }
  }

  return parts.join('');
}

// ═══════════════════════════════════════════════════════════════════════════
// CURVES ENCODING
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Encode multiple curves
 *
 * @param {Array} curves - Array of curve definitions
 * @returns {string} Hex-encoded curves data
 */
function encodeCurves(curves) {
  const parts = [];

  for (const curve of curves) {
    const curveData = encodeSingleCurve(curve);
    parts.push(encodeTag(1, 2).toString('hex')); // Repeated field 1
    parts.push(encodeVarint(curveData.length / 2).toString('hex'));
    parts.push(curveData);
  }

  return parts.join('');
}

/**
 * Encode a single curve
 *
 * @param {Object} curve - Curve definition
 * @param {string} curve.type - Curve type (from CURVE_TYPES keys)
 * @param {boolean} curve.enabled - Curve enabled state
 * @param {Array} curve.points - Array of control points
 * @param {string} curve.interpolation - 'linear' or 'bezier'
 * @returns {string} Hex-encoded curve data
 */
function encodeSingleCurve(curve) {
  const parts = [];

  // Field 1: Type (varint)
  const typeId = CURVE_TYPES[curve.type] || CURVE_TYPES.CUSTOM;
  parts.push(encodeTag(1, 0).toString('hex'));
  parts.push(encodeVarint(typeId).toString('hex'));

  // Field 2: Enabled (varint)
  parts.push(encodeTag(2, 0).toString('hex'));
  parts.push(encodeVarint(curve.enabled !== false ? 1 : 0).toString('hex'));

  // Field 3: Points (repeated nested)
  if (curve.points && curve.points.length > 0) {
    const pointsData = encodeCurvePoints(curve.points);
    parts.push(encodeTag(3, 2).toString('hex'));
    parts.push(encodeVarint(pointsData.length / 2).toString('hex'));
    parts.push(pointsData);
  }

  // Field 4: Interpolation (varint)
  parts.push(encodeTag(4, 0).toString('hex'));
  parts.push(encodeVarint(curve.interpolation === 'linear' ? 1 : 0).toString('hex'));

  return parts.join('');
}

/**
 * Encode curve control points with handles
 *
 * @param {Array} points - Array of point objects
 * @returns {string} Hex-encoded points data
 */
function encodeCurvePoints(points) {
  const parts = [];

  for (const point of points) {
    const pointData = encodeSinglePoint(point);
    parts.push(encodeTag(1, 2).toString('hex')); // Repeated field 1
    parts.push(encodeVarint(pointData.length / 2).toString('hex'));
    parts.push(pointData);
  }

  return parts.join('');
}

/**
 * Encode a single curve control point
 *
 * @param {Object} point - Point with x, y and optional handles
 * @returns {string} Hex-encoded point data
 */
function encodeSinglePoint(point) {
  const parts = [];

  // Field 1: X position (float)
  parts.push(encodeTag(1, 5).toString('hex'));
  parts.push(encodeFloat(point.x));

  // Field 2: Y position (float)
  parts.push(encodeTag(2, 5).toString('hex'));
  parts.push(encodeFloat(point.y));

  // Field 3-6: Handle positions (optional)
  if (point.handleInX !== undefined) {
    parts.push(encodeTag(3, 5).toString('hex'));
    parts.push(encodeFloat(point.handleInX));
  }
  if (point.handleInY !== undefined) {
    parts.push(encodeTag(4, 5).toString('hex'));
    parts.push(encodeFloat(point.handleInY));
  }
  if (point.handleOutX !== undefined) {
    parts.push(encodeTag(5, 5).toString('hex'));
    parts.push(encodeFloat(point.handleOutX));
  }
  if (point.handleOutY !== undefined) {
    parts.push(encodeTag(6, 5).toString('hex'));
    parts.push(encodeFloat(point.handleOutY));
  }

  return parts.join('');
}

/**
 * Create standard RGB curves (commonly used in color grading)
 *
 * @param {Object} curves - RGB curve data
 * @param {Array} curves.red - Red channel curve points
 * @param {Array} curves.green - Green channel curve points
 * @param {Array} curves.blue - Blue channel curve points
 * @param {Array} curves.lum - Luminance curve points (optional)
 * @returns {Array} Array of curve objects ready for encoding
 */
function createRGBCurves(curves) {
  const result = [];

  // Default diagonal curve points
  const defaultPoints = [
    { x: 0, y: 0, handleInX: 0, handleInY: 0, handleOutX: 0.1, handleOutY: 0.1 },
    { x: 1, y: 1, handleInX: 0.9, handleInY: 0.9, handleOutX: 1, handleOutY: 1 },
  ];

  if (curves.lum) {
    result.push({
      type: 'CUSTOM',
      enabled: true,
      points: curves.lum || defaultPoints,
      interpolation: 'bezier',
    });
  }

  if (curves.red) {
    result.push({
      type: 'RED',
      enabled: true,
      points: curves.red || defaultPoints,
      interpolation: 'bezier',
    });
  }

  if (curves.green) {
    result.push({
      type: 'GREEN',
      enabled: true,
      points: curves.green || defaultPoints,
      interpolation: 'bezier',
    });
  }

  if (curves.blue) {
    result.push({
      type: 'BLUE',
      enabled: true,
      points: curves.blue || defaultPoints,
      interpolation: 'bezier',
    });
  }

  return result;
}

/**
 * Create hue vs saturation curve
 *
 * @param {Array} points - Curve control points (x = hue 0-360, y = sat multiplier)
 * @returns {Object} Curve object ready for encoding
 */
function createHueVsSatCurve(points) {
  return {
    type: 'HUE_VS_SAT',
    enabled: true,
    points: points.map((p) => ({
      x: p.x / 360, // Normalize hue to 0-1
      y: p.y,
      handleInX: p.handleInX,
      handleInY: p.handleInY,
      handleOutX: p.handleOutX,
      handleOutY: p.handleOutY,
    })),
    interpolation: 'bezier',
  };
}

// ═══════════════════════════════════════════════════════════════════════════
// QUALIFIER ENCODING
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Encode HSL qualifier settings
 *
 * @param {Object} qualifier - Qualifier settings
 * @returns {string} Hex-encoded qualifier data
 */
function encodeHSLQualifier(qualifier) {
  const parts = [];

  for (const [name, def] of Object.entries(HSL_QUALIFIER)) {
    const value = qualifier[name] ?? def.neutral;

    // Encode based on type
    if (def.neutral === false || def.neutral === true) {
      // Boolean field
      parts.push(encodeTag(def.field, 0).toString('hex'));
      parts.push(encodeVarint(value ? 1 : 0).toString('hex'));
    } else if (typeof def.neutral === 'number') {
      // Float field
      parts.push(encodeTag(def.field, 5).toString('hex'));
      parts.push(encodeFloat(value));
    }
  }

  return parts.join('');
}

/**
 * Create a common HSL qualifier for skin tones
 *
 * @param {Object} options - Customization options
 * @returns {Object} Qualifier settings for skin tone selection
 */
function createSkinToneQualifier(options = {}) {
  const { hueCenter = 25, softness = 10 } = options;

  return {
    ENABLED: true,
    HUE_CENTER: hueCenter, // Orange-yellow range
    HUE_WIDTH: 30,
    HUE_SOFT: softness,
    SAT_LOW: 20,
    SAT_HIGH: 100,
    SAT_LOW_SOFT: 10,
    SAT_HIGH_SOFT: 0,
    LUM_LOW: 10,
    LUM_HIGH: 90,
    LUM_LOW_SOFT: 5,
    LUM_HIGH_SOFT: 5,
    INVERT: false,
    MATTE_FINESSE: 50,
    DENOISE: 20,
    SHRINK_GROW: 0,
  };
}

/**
 * Create a luminance qualifier for highlight/shadow isolation
 *
 * @param {Object} options - Range options
 * @param {number} options.low - Low luminance threshold (0-100)
 * @param {number} options.high - High luminance threshold (0-100)
 * @param {number} options.softness - Edge softness
 * @returns {Object} Qualifier settings
 */
function createLuminanceQualifier(options = {}) {
  const { low = 0, high = 100, softness = 10 } = options;

  return {
    ENABLED: true,
    HUE_CENTER: 0,
    HUE_WIDTH: 180, // Full hue range
    HUE_SOFT: 0,
    SAT_LOW: 0,
    SAT_HIGH: 100,
    SAT_LOW_SOFT: 0,
    SAT_HIGH_SOFT: 0,
    LUM_LOW: low,
    LUM_HIGH: high,
    LUM_LOW_SOFT: softness,
    LUM_HIGH_SOFT: softness,
    INVERT: false,
    MATTE_FINESSE: 0,
    DENOISE: 0,
    SHRINK_GROW: 0,
  };
}

// ═══════════════════════════════════════════════════════════════════════════
// POWER WINDOW ENCODING
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Encode power window settings
 *
 * @param {Object} window - Window settings
 * @returns {string} Hex-encoded window data
 */
function encodePowerWindow(window) {
  const parts = [];

  // Field 1: Type
  const typeId = WINDOW_TYPES[window.type] || WINDOW_TYPES.CIRCLE;
  parts.push(encodeTag(1, 0).toString('hex'));
  parts.push(encodeVarint(typeId).toString('hex'));

  // Field 2: Enabled
  parts.push(encodeTag(2, 0).toString('hex'));
  parts.push(encodeVarint(window.enabled !== false ? 1 : 0).toString('hex'));

  // Transform fields
  const transform = window.transform || {};
  if (transform.panX !== undefined) {
    parts.push(encodeTag(3, 5).toString('hex'));
    parts.push(encodeFloat(transform.panX));
  }
  if (transform.panY !== undefined) {
    parts.push(encodeTag(4, 5).toString('hex'));
    parts.push(encodeFloat(transform.panY));
  }
  if (transform.zoomX !== undefined) {
    parts.push(encodeTag(5, 5).toString('hex'));
    parts.push(encodeFloat(transform.zoomX));
  }
  if (transform.zoomY !== undefined) {
    parts.push(encodeTag(6, 5).toString('hex'));
    parts.push(encodeFloat(transform.zoomY));
  }
  if (transform.rotation !== undefined) {
    parts.push(encodeTag(7, 5).toString('hex'));
    parts.push(encodeFloat(transform.rotation));
  }

  // Shape fields
  const shape = window.shape || {};
  if (shape.radiusX !== undefined) {
    parts.push(encodeTag(10, 5).toString('hex'));
    parts.push(encodeFloat(shape.radiusX));
  }
  if (shape.radiusY !== undefined) {
    parts.push(encodeTag(11, 5).toString('hex'));
    parts.push(encodeFloat(shape.radiusY));
  }
  if (shape.softness !== undefined) {
    parts.push(encodeTag(12, 5).toString('hex'));
    parts.push(encodeFloat(shape.softness));
  }
  if (shape.insideSoftness !== undefined) {
    parts.push(encodeTag(13, 5).toString('hex'));
    parts.push(encodeFloat(shape.insideSoftness));
  }
  if (shape.outsideSoftness !== undefined) {
    parts.push(encodeTag(14, 5).toString('hex'));
    parts.push(encodeFloat(shape.outsideSoftness));
  }

  // Linear window specific
  if (shape.angle !== undefined) {
    parts.push(encodeTag(15, 5).toString('hex'));
    parts.push(encodeFloat(shape.angle));
  }
  if (shape.position !== undefined) {
    parts.push(encodeTag(16, 5).toString('hex'));
    parts.push(encodeFloat(shape.position));
  }

  // Polygon/curve points
  if (shape.points && shape.points.length > 0) {
    const pointsData = encodeWindowPoints(shape.points);
    parts.push(encodeTag(20, 2).toString('hex'));
    parts.push(encodeVarint(pointsData.length / 2).toString('hex'));
    parts.push(pointsData);
  }

  // Invert
  if (window.invert) {
    parts.push(encodeTag(30, 0).toString('hex'));
    parts.push(encodeVarint(1).toString('hex'));
  }

  return parts.join('');
}

/**
 * Encode window polygon/curve points
 *
 * @param {Array} points - Array of {x, y} points
 * @returns {string} Hex-encoded points data
 */
function encodeWindowPoints(points) {
  const parts = [];

  for (const point of points) {
    const pointParts = [];
    pointParts.push(encodeTag(1, 5).toString('hex'));
    pointParts.push(encodeFloat(point.x));
    pointParts.push(encodeTag(2, 5).toString('hex'));
    pointParts.push(encodeFloat(point.y));

    const pointData = pointParts.join('');
    parts.push(encodeTag(1, 2).toString('hex'));
    parts.push(encodeVarint(pointData.length / 2).toString('hex'));
    parts.push(pointData);
  }

  return parts.join('');
}

/**
 * Create a circular power window
 *
 * @param {Object} options - Window options
 * @returns {Object} Window settings for encoding
 */
function createCircularWindow(options = {}) {
  const {
    centerX = 0.5,
    centerY = 0.5,
    radiusX = 0.25,
    radiusY = 0.25,
    softness = 0.1,
    rotation = 0,
    invert = false,
  } = options;

  return {
    type: 'CIRCLE',
    enabled: true,
    transform: {
      panX: centerX - 0.5,
      panY: centerY - 0.5,
      zoomX: 1.0,
      zoomY: 1.0,
      rotation,
    },
    shape: {
      radiusX,
      radiusY,
      softness,
      insideSoftness: 0,
      outsideSoftness: softness,
    },
    invert,
  };
}

/**
 * Create a linear (gradient) power window
 *
 * @param {Object} options - Window options
 * @returns {Object} Window settings for encoding
 */
function createLinearWindow(options = {}) {
  const { angle = 0, position = 0.5, softness = 0.2, invert = false } = options;

  return {
    type: 'LINEAR',
    enabled: true,
    transform: {
      panX: 0,
      panY: 0,
      zoomX: 1.0,
      zoomY: 1.0,
      rotation: 0,
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
 * Create a polygon power window
 *
 * @param {Array} points - Array of {x, y} points (0-1 normalized)
 * @param {Object} options - Window options
 * @returns {Object} Window settings for encoding
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
    },
    shape: {
      points,
      softness,
    },
    invert,
  };
}

// ═══════════════════════════════════════════════════════════════════════════
// LUT ENCODING
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Encode LUT reference
 *
 * @param {Object} lut - LUT settings
 * @param {string} lut.path - Path to LUT file
 * @param {number} lut.strength - LUT strength (0-1)
 * @param {string} lut.inputColorSpace - Input color space
 * @param {string} lut.outputColorSpace - Output color space
 * @returns {string} Hex-encoded LUT reference data
 */
function encodeLUTReference(lut) {
  const parts = [];

  // Field 1: Path (length-delimited string)
  if (lut.path) {
    const pathBytes = Buffer.from(lut.path, 'utf-8');
    parts.push(encodeTag(1, 2).toString('hex'));
    parts.push(encodeVarint(pathBytes.length).toString('hex'));
    parts.push(pathBytes.toString('hex'));
  }

  // Field 2: Strength (float)
  parts.push(encodeTag(2, 5).toString('hex'));
  parts.push(encodeFloat(lut.strength ?? 1.0));

  // Field 3: Input color space (optional)
  if (lut.inputColorSpace) {
    const icsBytes = Buffer.from(lut.inputColorSpace, 'utf-8');
    parts.push(encodeTag(3, 2).toString('hex'));
    parts.push(encodeVarint(icsBytes.length).toString('hex'));
    parts.push(icsBytes.toString('hex'));
  }

  // Field 4: Output color space (optional)
  if (lut.outputColorSpace) {
    const ocsBytes = Buffer.from(lut.outputColorSpace, 'utf-8');
    parts.push(encodeTag(4, 2).toString('hex'));
    parts.push(encodeVarint(ocsBytes.length).toString('hex'));
    parts.push(ocsBytes.toString('hex'));
  }

  return parts.join('');
}

/**
 * Encode ASC CDL values as inline LUT equivalent
 *
 * @param {Object} cdl - CDL values
 * @param {Array} cdl.slope - [r, g, b] slope values
 * @param {Array} cdl.offset - [r, g, b] offset values
 * @param {Array} cdl.power - [r, g, b] power values
 * @param {number} cdl.saturation - Saturation value
 * @returns {Object} Corrector object with CDL as primary adjustments
 */
function createCDLCorrector(cdl) {
  const { slope = [1, 1, 1], offset = [0, 0, 0], power = [1, 1, 1], saturation = 1 } = cdl;

  return {
    typeId: CORRECTOR_TYPE.PRIMARY,
    enabled: true,
    values: {
      wheels: {
        // Map CDL to primary wheels
        // Slope → Gain
        GAIN_R: slope[0] - 1,
        GAIN_G: slope[1] - 1,
        GAIN_B: slope[2] - 1,
        GAIN_MASTER: 1.0,
        // Offset → Offset
        OFFSET_R: offset[0],
        OFFSET_G: offset[1],
        OFFSET_B: offset[2],
        OFFSET_MASTER: 0,
        // Power → Gamma (inverted)
        GAMMA_R: 1 / power[0] - 1,
        GAMMA_G: 1 / power[1] - 1,
        GAMMA_B: 1 / power[2] - 1,
        GAMMA_MASTER: 1.0,
        // Lift at neutral
        LIFT_R: 0,
        LIFT_G: 0,
        LIFT_B: 0,
        LIFT_MASTER: 1.0,
      },
      SATURATION: saturation * 50, // Convert to 0-100 scale
    },
  };
}

// ═══════════════════════════════════════════════════════════════════════════
// HIGH-LEVEL BUILDERS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Create a complete grade body with nodes
 *
 * @param {Object} config - Grade configuration
 * @param {Array} config.nodes - Node definitions
 * @param {Object} config.resolution - Resolution settings
 * @returns {string} Complete hex-encoded grade body
 */
function buildCompleteGradeBody(config) {
  const { nodes = [], resolution = { width: 1920, height: 1080 } } = config;

  // Create serial node chain from provided nodes
  const graph = encodeSerialNodes(nodes);
  const graphData = encodeNodeGraph(graph);

  // Build header + resolution data + graph
  const parts = [];

  // Header: 800a (uncompressed format)
  parts.push('800a');

  // Build inner protobuf
  const innerParts = [];

  // Field 2: Version
  innerParts.push(encodeTag(2, 0).toString('hex'));
  innerParts.push(encodeVarint(1).toString('hex'));

  // Field 3: Resolution data
  const resData = buildResolutionData(resolution);
  innerParts.push(encodeTag(3, 2).toString('hex'));
  innerParts.push(encodeVarint(resData.length / 2).toString('hex'));
  innerParts.push(resData);

  // Field 9: Node graph
  innerParts.push(encodeTag(9, 2).toString('hex'));
  innerParts.push(encodeVarint(graphData.length / 2).toString('hex'));
  innerParts.push(graphData);

  // Field 12: Timestamp
  innerParts.push(encodeTag(12, 0).toString('hex'));
  innerParts.push(encodeVarint(Date.now() * 1000).toString('hex'));

  const innerData = innerParts.join('');
  parts.push(encodeVarint(innerData.length / 2).toString('hex'));
  parts.push(innerData);

  return parts.join('');
}

/**
 * Build resolution data block
 */
function buildResolutionData(resolution) {
  const { width = 1920, height = 1080 } = resolution;
  const parts = [];

  parts.push(encodeTag(1, 0).toString('hex'));
  parts.push(encodeVarint(width).toString('hex'));
  parts.push(encodeTag(2, 0).toString('hex'));
  parts.push(encodeVarint(height).toString('hex'));
  parts.push(encodeTag(3, 5).toString('hex'));
  parts.push(encodeFloat(1.0));
  parts.push(encodeTag(4, 0).toString('hex'));
  parts.push(encodeVarint(width).toString('hex'));
  parts.push(encodeTag(5, 0).toString('hex'));
  parts.push(encodeVarint(height).toString('hex'));
  parts.push(encodeTag(6, 5).toString('hex'));
  parts.push(encodeFloat(1.0));

  return parts.join('');
}

/**
 * Create a simple single-node grade
 *
 * @param {Object} adjustments - Primary adjustment values
 * @returns {string} Complete hex-encoded grade body
 */
function createSimpleGrade(adjustments) {
  const node = {
    id: 'node1',
    label: 'Primary',
    correctors: [
      {
        typeId: CORRECTOR_TYPE.PRIMARY,
        enabled: true,
        values: {
          wheels: {
            ...Object.fromEntries(
              Object.entries(PRIMARY_WHEELS).map(([k, v]) => [k, adjustments[k] ?? v.neutral])
            ),
          },
          ...adjustments,
        },
      },
    ],
  };

  return buildCompleteGradeBody({ nodes: [node] });
}

// ═══════════════════════════════════════════════════════════════════════════
// EXPORTS
// ═══════════════════════════════════════════════════════════════════════════

module.exports = {
  // Node graph encoding
  encodeNodeGraph,
  encodeNode,
  encodeConnection,
  encodeSerialNodes,
  encodeParallelNodes,
  encodeLayerMixer,

  // Corrector encoding
  encodeCorrector,
  encodeColorWheels,
  encodePrimaryAdjustments,

  // Curves encoding
  encodeCurves,
  encodeSingleCurve,
  encodeCurvePoints,
  encodeSinglePoint,
  createRGBCurves,
  createHueVsSatCurve,

  // Qualifier encoding
  encodeHSLQualifier,
  createSkinToneQualifier,
  createLuminanceQualifier,

  // Window encoding
  encodePowerWindow,
  encodeWindowPoints,
  createCircularWindow,
  createLinearWindow,
  createPolygonWindow,

  // LUT encoding
  encodeLUTReference,
  createCDLCorrector,

  // High-level builders
  buildCompleteGradeBody,
  buildResolutionData,
  createSimpleGrade,

  // Constants
  CONNECTION_TYPE,
  BLEND_MODE,
};
