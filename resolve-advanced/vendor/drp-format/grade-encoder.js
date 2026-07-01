/**
 * DaVinci Resolve Grade Body Encoder
 *
 * Encodes color grade data into DaVinci Resolve's protobuf format for the <Body> element.
 * This implements the uncompressed format (800a header) based on reverse-engineered protobuf structure.
 *
 * Format Overview:
 * - Header: 0x800a (indicates uncompressed protobuf data)
 * - Length: Varint-encoded payload length
 * - Field 2: Version (varint, always 1)
 * - Field 3: Nested resolution/adjustment data (length-delimited)
 * - Field 12: Timestamp in microseconds (varint)
 * - Field 4: Secondary timestamp (varint)
 *
 * @module grade-encoder
 */

/**
 * Encodes a positive integer as a protobuf varint.
 *
 * Varint encoding uses 7 bits per byte, with the MSB indicating continuation.
 * Each byte's lower 7 bits contain data, and bit 7 is set if more bytes follow.
 *
 * @param {number} value - Positive integer to encode (0 to Number.MAX_SAFE_INTEGER)
 * @returns {Buffer} Encoded varint bytes
 *
 * @example
 * encodeVarint(1920) // Returns Buffer [0x80, 0x0f] (1920 = 0000_1111_0000_0000)
 * encodeVarint(1) // Returns Buffer [0x01]
 */
function encodeVarint(value) {
  if (value < 0) {
    throw new Error('Varint encoding only supports non-negative integers');
  }

  const bytes = [];
  let remaining = value;

  while (remaining > 0x7f) {
    // Take lower 7 bits and set continuation bit (0x80)
    bytes.push((remaining & 0x7f) | 0x80);
    remaining = Math.floor(remaining / 128);
  }

  // Last byte without continuation bit
  bytes.push(remaining & 0x7f);

  return Buffer.from(bytes);
}

/**
 * Encodes a 32-bit IEEE 754 floating point number to little-endian hex string.
 *
 * Used for primary adjustment values and unity constants in grade data.
 * Common values:
 * - 1.0 (neutral) = "0000803f"
 * - 0.9 (-10% adjustment) = "6666663f"
 * - 1.1 (+10% adjustment) ~= "cdcc8c3f"
 *
 * @param {number} value - Float value to encode
 * @returns {string} 8-character hex string (little-endian)
 *
 * @example
 * encodeFloat(1.0) // Returns "0000803f"
 * encodeFloat(0.9) // Returns "6666663f"
 */
function encodeFloat(value) {
  const buffer = Buffer.allocUnsafe(4);
  buffer.writeFloatLE(value, 0);
  return buffer.toString('hex');
}

/**
 * Encodes a 64-bit IEEE 754 double precision number to little-endian hex string.
 *
 * Used for high-precision values and timestamps in some contexts.
 *
 * @param {number} value - Double value to encode
 * @returns {string} 16-character hex string (little-endian)
 *
 * @example
 * encodeDouble(1.0) // Returns "000000000000f03f"
 */
function encodeDouble(value) {
  const buffer = Buffer.allocUnsafe(8);
  buffer.writeDoubleLE(value, 0);
  return buffer.toString('hex');
}

/**
 * Encodes a protobuf field tag and wire type.
 *
 * Tag format: (field_number << 3) | wire_type
 * Wire types:
 * - 0: Varint
 * - 1: 64-bit (fixed64, double)
 * - 2: Length-delimited (string, bytes, nested messages)
 * - 5: 32-bit (fixed32, float)
 *
 * @param {number} fieldNumber - Field identifier (1-536870911)
 * @param {number} wireType - Wire type (0, 1, 2, or 5)
 * @returns {Buffer} Encoded tag as varint
 */
function encodeTag(fieldNumber, wireType) {
  const tag = (fieldNumber << 3) | wireType;
  return encodeVarint(tag);
}

/**
 * Builds the nested Field 3 structure containing resolution and adjustment data.
 *
 * Field 3 structure (34 bytes typical):
 * - Field 1 (varint): Timeline width (e.g., 1920)
 * - Field 2 (varint): Timeline height (e.g., 1080)
 * - Field 3 (float): Unity constant (always 1.0)
 * - Field 4 (varint): Source width
 * - Field 5 (varint): Source height
 * - Field 6 (float): Primary adjustment value (1.0 = neutral)
 * - Field 7 (varint): Output width
 * - Field 8 (varint): Output height
 * - Field 9 (varint): Flags (0xFFFFFFFF for standard)
 *
 * @param {Object} options - Resolution and adjustment options
 * @param {number} options.width - Timeline width (default: 1920)
 * @param {number} options.height - Timeline height (default: 1080)
 * @param {number} options.sourceWidth - Source clip width (default: same as width)
 * @param {number} options.sourceHeight - Source clip height (default: same as height)
 * @param {number} options.primaryAdjustment - Primary correction value (default: 1.0)
 * @returns {string} Hex-encoded nested message data
 */
function buildNestedResolutionData(options = {}) {
  const {
    width = 1920,
    height = 1080,
    sourceWidth = width,
    sourceHeight = height,
    primaryAdjustment = 1.0
  } = options;

  const parts = [];

  // Field 1: Timeline width (wire type 0 = varint)
  parts.push(encodeTag(1, 0).toString('hex'));
  parts.push(encodeVarint(width).toString('hex'));

  // Field 2: Timeline height (wire type 0 = varint)
  parts.push(encodeTag(2, 0).toString('hex'));
  parts.push(encodeVarint(height).toString('hex'));

  // Field 3: Unity = 1.0 (wire type 5 = 32-bit float)
  parts.push(encodeTag(3, 5).toString('hex'));
  parts.push(encodeFloat(1.0));

  // Field 4: Source width (wire type 0 = varint)
  parts.push(encodeTag(4, 0).toString('hex'));
  parts.push(encodeVarint(sourceWidth).toString('hex'));

  // Field 5: Source height (wire type 0 = varint)
  parts.push(encodeTag(5, 0).toString('hex'));
  parts.push(encodeVarint(sourceHeight).toString('hex'));

  // Field 6: Primary adjustment (wire type 5 = 32-bit float)
  parts.push(encodeTag(6, 5).toString('hex'));
  parts.push(encodeFloat(primaryAdjustment));

  // Field 7: Output width (wire type 0 = varint)
  parts.push(encodeTag(7, 0).toString('hex'));
  parts.push(encodeVarint(width).toString('hex'));

  // Field 8: Output height (wire type 0 = varint)
  parts.push(encodeTag(8, 0).toString('hex'));
  parts.push(encodeVarint(height).toString('hex'));

  // Field 9: Flags = 0xFFFFFFFF (wire type 0 = varint)
  // 0xFFFFFFFF as varint: needs special handling for unsigned 32-bit
  parts.push(encodeTag(9, 0).toString('hex'));
  parts.push('ffffffff0f'); // 0xFFFFFFFF encoded as varint

  return parts.join('');
}

/**
 * Builds complete protobuf structure for grade body.
 *
 * Structure:
 * - Field 2 (varint): Version = 1
 * - Field 3 (length-delimited): Nested resolution/adjustment data
 * - Field 12 (varint): Timestamp in microseconds since epoch
 * - Field 4 (varint): Secondary timestamp (often same as field 12)
 *
 * @param {Object} options - Grade data options
 * @param {number} options.version - Format version (default: 1)
 * @param {number} options.width - Timeline width (default: 1920)
 * @param {number} options.height - Timeline height (default: 1080)
 * @param {number} options.primaryAdjustment - Primary correction (default: 1.0)
 * @param {number} options.timestamp - Microseconds since epoch (default: current time)
 * @returns {string} Hex-encoded protobuf message data (without header)
 */
function buildGradeProtobuf(options = {}) {
  const {
    version = 1,
    width = 1920,
    height = 1080,
    sourceWidth = width,
    sourceHeight = height,
    primaryAdjustment = 1.0,
    timestamp = Date.now() * 1000 // Convert milliseconds to microseconds
  } = options;

  const parts = [];

  // Field 2: Version (wire type 0 = varint)
  parts.push(encodeTag(2, 0).toString('hex'));
  parts.push(encodeVarint(version).toString('hex'));

  // Field 3: Nested resolution data (wire type 2 = length-delimited)
  const nestedData = buildNestedResolutionData({
    width,
    height,
    sourceWidth,
    sourceHeight,
    primaryAdjustment
  });
  const nestedLength = nestedData.length / 2; // Convert hex chars to byte count

  parts.push(encodeTag(3, 2).toString('hex'));
  parts.push(encodeVarint(nestedLength).toString('hex'));
  parts.push(nestedData);

  // Field 12: Timestamp (wire type 0 = varint)
  parts.push(encodeTag(12, 0).toString('hex'));
  parts.push(encodeVarint(timestamp).toString('hex'));

  // Field 2 (again): Version = 1 (appears twice in format)
  parts.push(encodeTag(2, 0).toString('hex'));
  parts.push(encodeVarint(version).toString('hex'));

  // Field 4: Secondary timestamp (wire type 0 = varint)
  parts.push(encodeTag(4, 0).toString('hex'));
  parts.push(encodeVarint(timestamp).toString('hex'));

  return parts.join('');
}

/**
 * Main grade body encoder. Generates complete hex-encoded body data.
 *
 * Creates the full <Body> element content including:
 * - 800a header (uncompressed format indicator)
 * - Length varint
 * - Complete protobuf payload
 *
 * @param {Object} gradeData - Grade configuration
 * @param {boolean} gradeData.hasCorrection - Whether grade has any corrections (default: true)
 * @param {number} gradeData.primaryAdjustment - Primary adjustment value, 1.0 = neutral (default: 1.0)
 * @param {number} gradeData.width - Timeline resolution width (default: 1920)
 * @param {number} gradeData.height - Timeline resolution height (default: 1080)
 * @param {number} gradeData.sourceWidth - Source media width (default: same as width)
 * @param {number} gradeData.sourceHeight - Source media height (default: same as height)
 * @param {number} gradeData.timestamp - Custom timestamp in microseconds (default: current time)
 * @returns {string} Complete hex string for <Body> element
 *
 * @example
 * // Neutral grade at 1920x1080
 * encodeGradeBody({ hasCorrection: false })
 * // Returns: "800a2d10011a2208800f10b8081d0000803f..."
 *
 * @example
 * // Grade with -10% primary adjustment
 * encodeGradeBody({
 *   hasCorrection: true,
 *   primaryAdjustment: 0.9,
 *   width: 1920,
 *   height: 1080
 * })
 */
function encodeGradeBody(gradeData = {}) {
  const {
    hasCorrection = true,
    primaryAdjustment = 1.0,
    width = 1920,
    height = 1080,
    sourceWidth = width,
    sourceHeight = height,
    timestamp = Date.now() * 1000
  } = gradeData;

  // Build the protobuf payload
  const protobufData = buildGradeProtobuf({
    version: 1,
    width,
    height,
    sourceWidth,
    sourceHeight,
    primaryAdjustment,
    timestamp
  });

  // Calculate payload length in bytes
  const payloadLength = protobufData.length / 2;

  // Build complete body: header + length + payload
  const parts = [];
  parts.push('800a'); // Uncompressed format header
  parts.push(encodeVarint(payloadLength).toString('hex'));
  parts.push(protobufData);

  return parts.join('');
}

/**
 * Creates a neutral grade body (no corrections applied).
 *
 * A neutral grade has all adjustment values at 1.0, indicating no color correction.
 * This is the default state for clips without grading.
 *
 * @param {Object} options - Resolution options
 * @param {number} options.width - Timeline width (default: 1920)
 * @param {number} options.height - Timeline height (default: 1080)
 * @returns {string} Hex-encoded neutral grade body
 *
 * @example
 * encodeNeutralGrade({ width: 1920, height: 1080 })
 * // Returns: "800a2d10011a2208800f10b8081d0000803f20800f28b808350000803f38800f40b80848ffffffff0f60..."
 */
function encodeNeutralGrade(options = {}) {
  const { width = 1920, height = 1080 } = options;

  return encodeGradeBody({
    hasCorrection: false,
    primaryAdjustment: 1.0,
    width,
    height,
    sourceWidth: width,
    sourceHeight: height
  });
}

/**
 * Decodes a varint from hex string for debugging/verification.
 *
 * Useful for testing and verifying encoded values.
 *
 * @param {string} hex - Hex string containing varint
 * @param {number} offset - Starting position in hex string (default: 0)
 * @returns {Object} Object with value and bytes consumed
 * @returns {number} return.value - Decoded integer value
 * @returns {number} return.bytesRead - Number of bytes consumed
 *
 * @example
 * decodeVarint('800f', 0) // Returns { value: 1920, bytesRead: 2 }
 */
function decodeVarint(hex, offset = 0) {
  let value = 0;
  let shift = 0;
  let bytesRead = 0;

  while (true) {
    const byteHex = hex.substr(offset + bytesRead * 2, 2);
    const byte = parseInt(byteHex, 16);

    value |= (byte & 0x7f) << shift;
    bytesRead++;

    if ((byte & 0x80) === 0) {
      break;
    }

    shift += 7;
  }

  return { value, bytesRead };
}

/**
 * Decodes a float from hex string for debugging/verification.
 *
 * @param {string} hex - 8-character hex string (little-endian float)
 * @returns {number} Decoded float value
 *
 * @example
 * decodeFloat('0000803f') // Returns 1.0
 */
function decodeFloat(hex) {
  const buffer = Buffer.from(hex, 'hex');
  return buffer.readFloatLE(0);
}

module.exports = {
  encodeGradeBody,
  encodeVarint,
  encodeFloat,
  encodeDouble,
  buildGradeProtobuf,
  encodeNeutralGrade,
  // Export utility functions for testing
  encodeTag,
  buildNestedResolutionData,
  decodeVarint,
  decodeFloat
};
