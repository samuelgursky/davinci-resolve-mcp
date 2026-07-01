/**
 * DRX Parameter Encoding/Decoding
 *
 * Handles the protobuf encoding and decoding of parameter values
 * in DaVinci Resolve's DRX format.
 *
 * @module drx-parameters/parameter-codec
 */

const { PARAM_ID_MAP } = require('./parameter-ids');
const { getRange, clamp } = require('./parameter-ranges');

// ============================================================================
// PROTOBUF PRIMITIVES
// ============================================================================

/**
 * Create a buffer with varint-encoded value
 * @param {number} value - Value to encode
 * @returns {Buffer}
 */
function encodeVarint(value) {
  const bytes = [];
  let v = value >>> 0; // Ensure unsigned

  while (v >= 0x80) {
    bytes.push((v & 0x7f) | 0x80);
    v >>>= 7;
  }
  bytes.push(v);

  return Buffer.from(bytes);
}

/**
 * Read a varint from a buffer
 * @param {Buffer} buffer - Buffer to read from
 * @param {number} offset - Starting offset
 * @returns {{ value: number, bytesRead: number }}
 */
function decodeVarint(buffer, offset) {
  let value = 0;
  let shift = 0;
  let bytesRead = 0;

  while (offset + bytesRead < buffer.length) {
    const byte = buffer[offset + bytesRead];
    bytesRead++;
    value |= (byte & 0x7f) << shift;
    if ((byte & 0x80) === 0) break;
    shift += 7;
  }

  return { value: value >>> 0, bytesRead };
}

/**
 * Encode a signed varint (zigzag encoding)
 * @param {number} value - Signed value
 * @returns {Buffer}
 */
function encodeSignedVarint(value) {
  // Zigzag encoding: (value << 1) ^ (value >> 31)
  const zigzag = (value << 1) ^ (value >> 31);
  return encodeVarint(zigzag);
}

/**
 * Decode a signed varint (zigzag encoding)
 * @param {Buffer} buffer - Buffer to read from
 * @param {number} offset - Starting offset
 * @returns {{ value: number, bytesRead: number }}
 */
function decodeSignedVarint(buffer, offset) {
  const { value, bytesRead } = decodeVarint(buffer, offset);
  // Zigzag decode: (value >>> 1) ^ -(value & 1)
  const signed = (value >>> 1) ^ -(value & 1);
  return { value: signed, bytesRead };
}

/**
 * Encode a 32-bit float (little-endian)
 * @param {number} value - Float value
 * @returns {Buffer}
 */
function encodeFloat32(value) {
  const buffer = Buffer.alloc(4);
  buffer.writeFloatLE(value, 0);
  return buffer;
}

/**
 * Decode a 32-bit float (little-endian)
 * @param {Buffer} buffer - Buffer to read from
 * @param {number} offset - Starting offset
 * @returns {number}
 */
function decodeFloat32(buffer, offset) {
  return buffer.readFloatLE(offset);
}

/**
 * Encode a 32-bit fixed value (little-endian)
 * @param {number} value - Value to encode
 * @returns {Buffer}
 */
function encodeFixed32(value) {
  const buffer = Buffer.alloc(4);
  buffer.writeUInt32LE(value >>> 0, 0);
  return buffer;
}

/**
 * Decode a 32-bit fixed value (little-endian)
 * @param {Buffer} buffer - Buffer to read from
 * @param {number} offset - Starting offset
 * @returns {number}
 */
function decodeFixed32(buffer, offset) {
  return buffer.readUInt32LE(offset);
}

/**
 * Encode a 64-bit fixed value (little-endian)
 * @param {bigint|number} value - Value to encode
 * @returns {Buffer}
 */
function encodeFixed64(value) {
  const buffer = Buffer.alloc(8);
  buffer.writeBigUInt64LE(BigInt(value), 0);
  return buffer;
}

/**
 * Decode a 64-bit fixed value (little-endian)
 * @param {Buffer} buffer - Buffer to read from
 * @param {number} offset - Starting offset
 * @returns {bigint}
 */
function decodeFixed64(buffer, offset) {
  return buffer.readBigUInt64LE(offset);
}

/**
 * Encode a length-delimited bytes field
 * @param {Buffer} data - Data to encode
 * @returns {Buffer}
 */
function encodeLengthDelimited(data) {
  const length = encodeVarint(data.length);
  return Buffer.concat([length, data]);
}

// ============================================================================
// PROTOBUF FIELD ENCODING
// ============================================================================

/**
 * Wire types for protobuf encoding
 */
const WIRE_TYPES = {
  VARINT: 0,
  FIXED64: 1,
  LENGTH_DELIMITED: 2,
  FIXED32: 5,
};

/**
 * Encode a protobuf field tag
 * @param {number} fieldNumber - Field number
 * @param {number} wireType - Wire type
 * @returns {Buffer}
 */
function encodeFieldTag(fieldNumber, wireType) {
  return encodeVarint((fieldNumber << 3) | wireType);
}

/**
 * Decode a protobuf field tag
 * @param {Buffer} buffer - Buffer to read from
 * @param {number} offset - Starting offset
 * @returns {{ fieldNumber: number, wireType: number, bytesRead: number }}
 */
function decodeFieldTag(buffer, offset) {
  const { value, bytesRead } = decodeVarint(buffer, offset);
  return {
    fieldNumber: value >>> 3,
    wireType: value & 0x07,
    bytesRead,
  };
}

// ============================================================================
// DRX PARAMETER ENCODING
// ============================================================================

/**
 * Encode a single DRX parameter
 * @param {number} paramId - Parameter ID
 * @param {number} value - Parameter value
 * @returns {Buffer} Encoded parameter bytes
 */
function encodeParameter(paramId, value) {
  // DRX parameter structure:
  // F3 (nested message) {
  //   F1: parameter ID (varint)
  //   F2: nested { F2: value (float32 as fixed32) }
  // }
  const parts = [];

  // F1: parameter ID
  parts.push(encodeFieldTag(1, WIRE_TYPES.VARINT));
  parts.push(encodeVarint(paramId));

  // F2: nested message with value
  const valueBytes = Buffer.concat([
    encodeFieldTag(2, WIRE_TYPES.FIXED32),
    encodeFloat32(value),
  ]);
  parts.push(encodeFieldTag(2, WIRE_TYPES.LENGTH_DELIMITED));
  parts.push(encodeLengthDelimited(valueBytes));

  // Wrap in F3
  const innerBytes = Buffer.concat(parts);
  return Buffer.concat([
    encodeFieldTag(3, WIRE_TYPES.LENGTH_DELIMITED),
    encodeLengthDelimited(innerBytes),
  ]);
}

/**
 * Encode multiple DRX parameters
 * @param {object} params - Object mapping param IDs to values
 * @returns {Buffer} Encoded parameters bytes
 */
function encodeParameters(params) {
  const buffers = [];

  for (const [paramId, value] of Object.entries(params)) {
    buffers.push(encodeParameter(Number(paramId), value));
  }

  return Buffer.concat(buffers);
}

/**
 * Convert semantic parameters to raw parameter IDs
 * @param {object} semanticParams - Parameters keyed by control.channel
 * @returns {object} Parameters keyed by parameter ID
 */
function semanticToRaw(semanticParams) {
  const rawParams = {};
  const { LIFT, GAIN, GAMMA, OFFSET, SATURATION, TEMP_TINT, CONTRAST, LOG_WHEELS } = require('./parameter-ids');

  // Map semantic names to parameter ID groups
  const controlMaps = {
    lift: LIFT,
    gain: GAIN,
    gamma: GAMMA,
    offset: OFFSET,
    saturation: { master: SATURATION.PRIMARY },
    temperature: { master: TEMP_TINT.TEMPERATURE },
    tint: { master: TEMP_TINT.TINT },
    midtoneDetail: { master: TEMP_TINT.MIDTONE_DETAIL },
    contrast: { master: CONTRAST.CONTRAST },
    pivot: { master: CONTRAST.PIVOT },
    highRange: { master: CONTRAST.HIGH_RANGE },
    lowRange: { master: CONTRAST.LOW_RANGE },
    // Log Wheels (R/G/B only - no master channel per 2026-01-14 DRX analysis)
    logShadow: {
      r: LOG_WHEELS.SHADOW_R,
      g: LOG_WHEELS.SHADOW_G,
      b: LOG_WHEELS.SHADOW_B,
    },
    logMidtone: {
      r: LOG_WHEELS.MIDTONE_R,
      g: LOG_WHEELS.MIDTONE_G,
      b: LOG_WHEELS.MIDTONE_B,
    },
    logHighlight: {
      r: LOG_WHEELS.HIGHLIGHT_R,
      g: LOG_WHEELS.HIGHLIGHT_G,
      b: LOG_WHEELS.HIGHLIGHT_B,
    },
  };

  for (const [control, channels] of Object.entries(semanticParams)) {
    const controlMap = controlMaps[control];
    if (!controlMap) continue;

    for (const [channel, value] of Object.entries(channels)) {
      // Map channel name to constant key
      const channelKey = channel.toUpperCase();
      const paramId = controlMap[channelKey] || controlMap[channel];

      if (paramId !== undefined) {
        // Validate and clamp value
        const clampedValue = clamp(control, channel, value);
        rawParams[paramId] = clampedValue;
      }
    }
  }

  return rawParams;
}

/**
 * Convert raw parameter IDs to semantic parameters
 * @param {object} rawParams - Parameters keyed by parameter ID
 * @returns {object} Parameters keyed by control.channel
 */
function rawToSemantic(rawParams) {
  const semanticParams = {};

  for (const [paramId, value] of Object.entries(rawParams)) {
    const info = PARAM_ID_MAP[Number(paramId)];
    if (!info) continue;

    const { control, channel } = info;

    if (!semanticParams[control]) {
      semanticParams[control] = {};
    }
    semanticParams[control][channel] = value;
  }

  return semanticParams;
}

// ============================================================================
// PARAMETER MERGING
// ============================================================================

/**
 * Merge strategies for different parameter types
 */
const MERGE_STRATEGIES = {
  // Additive: sum values across nodes
  ADDITIVE: 'additive',
  // Multiplicative: multiply values
  MULTIPLICATIVE: 'multiplicative',
  // Replace: use last value
  REPLACE: 'replace',
};

/**
 * Get merge strategy for a control type
 * @param {string} control - Control name
 * @returns {string} Merge strategy
 */
function getMergeStrategy(control) {
  const strategies = {
    // Additive controls
    lift: MERGE_STRATEGIES.ADDITIVE,
    gamma: MERGE_STRATEGIES.ADDITIVE,
    offset: MERGE_STRATEGIES.ADDITIVE,
    temperature: MERGE_STRATEGIES.ADDITIVE,
    tint: MERGE_STRATEGIES.ADDITIVE,
    logShadow: MERGE_STRATEGIES.ADDITIVE,
    logMidtone: MERGE_STRATEGIES.ADDITIVE,
    logHighlight: MERGE_STRATEGIES.ADDITIVE,

    // Multiplicative controls
    gain: MERGE_STRATEGIES.MULTIPLICATIVE,
    saturation: MERGE_STRATEGIES.MULTIPLICATIVE,
    contrast: MERGE_STRATEGIES.MULTIPLICATIVE,

    // Replace controls
    pivot: MERGE_STRATEGIES.REPLACE,
    pivotFine: MERGE_STRATEGIES.REPLACE,
    highRange: MERGE_STRATEGIES.REPLACE,
    lowRange: MERGE_STRATEGIES.REPLACE,
    softClipHigh: MERGE_STRATEGIES.REPLACE,
    softClipLow: MERGE_STRATEGIES.REPLACE,
  };

  return strategies[control] || MERGE_STRATEGIES.REPLACE;
}

/**
 * Merge parameters from multiple nodes into cumulative state
 * @param {object[]} nodeParams - Array of parameter objects from each node
 * @returns {object} Merged semantic parameters
 */
function mergeNodeParams(nodeParams) {
  const { getAllDefaults, getRange } = require('./parameter-ranges');
  const result = getAllDefaults();

  for (const params of nodeParams) {
    for (const [control, channels] of Object.entries(params)) {
      if (!result[control]) {
        result[control] = {};
      }

      for (const [channel, value] of Object.entries(channels)) {
        const strategy = getMergeStrategy(control);
        const range = getRange(control, channel);
        const defaultVal = range ? range.default : 0;

        if (result[control][channel] === undefined) {
          result[control][channel] = defaultVal;
        }

        switch (strategy) {
          case MERGE_STRATEGIES.ADDITIVE:
            result[control][channel] += value;
            break;
          case MERGE_STRATEGIES.MULTIPLICATIVE:
            result[control][channel] *= value;
            break;
          case MERGE_STRATEGIES.REPLACE:
            result[control][channel] = value;
            break;
        }
      }
    }
  }

  return result;
}

module.exports = {
  // Protobuf primitives
  encodeVarint,
  decodeVarint,
  encodeSignedVarint,
  decodeSignedVarint,
  encodeFloat32,
  decodeFloat32,
  encodeFixed32,
  decodeFixed32,
  encodeFixed64,
  decodeFixed64,
  encodeLengthDelimited,

  // Field encoding
  WIRE_TYPES,
  encodeFieldTag,
  decodeFieldTag,

  // Parameter encoding
  encodeParameter,
  encodeParameters,
  semanticToRaw,
  rawToSemantic,

  // Merging
  MERGE_STRATEGIES,
  getMergeStrategy,
  mergeNodeParams,
};
