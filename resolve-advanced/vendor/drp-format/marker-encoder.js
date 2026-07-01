/**
 * DaVinci Resolve Timeline Marker Encoder/Decoder
 *
 * Encodes and decodes timeline markers into DaVinci Resolve's
 * compressed protobuf format stored in Sm2SequenceLockableBlob.FieldsBlob.
 *
 * Format Overview:
 * - FieldsBlob header (Big-Endian): version, field count, "BlobData" field
 * - ZSTD compressed protobuf (magic: 0x28b52ffd)
 * - Nested protobuf with frame, color, name, ref_id, description
 *
 * @module marker-encoder
 */

const zlib = require('zlib');

/**
 * DaVinci Resolve marker color codes
 * Colors are represented as bit positions, not sequential values
 */
const MARKER_COLORS = {
  BLUE: 2,           // 0x00002 - Default marker color
  YELLOW: 8,         // 0x00008
  RED: 32,           // 0x00020
  PURPLE: 131072,    // 0x20000 (Lavender)
  // Additional colors to be reverse-engineered
};

/**
 * Encode a positive integer as a protobuf varint
 * @param {number} value - Non-negative integer to encode
 * @returns {Buffer} Encoded varint bytes
 */
function encodeVarint(value) {
  const bytes = [];
  let remaining = value;

  while (remaining > 0x7f) {
    bytes.push((remaining & 0x7f) | 0x80);
    remaining = Math.floor(remaining / 128);
  }
  bytes.push(remaining & 0x7f);

  return Buffer.from(bytes);
}

/**
 * Decode a varint from buffer
 * @param {Buffer} data - Buffer containing varint
 * @param {number} offset - Start offset
 * @returns {{value: number, bytesRead: number}} Decoded value and bytes consumed
 */
function decodeVarint(data, offset = 0) {
  let value = 0;
  let shift = 0;
  let bytesRead = 0;

  while (offset + bytesRead < data.length) {
    const byte = data[offset + bytesRead];
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
 * Encode a protobuf field tag
 * @param {number} fieldNumber - Field number
 * @param {number} wireType - Wire type (0=varint, 2=length-delimited)
 * @returns {Buffer} Encoded tag
 */
function encodeTag(fieldNumber, wireType) {
  const tag = (fieldNumber << 3) | wireType;
  return encodeVarint(tag);
}

/**
 * Encode a string as a length-delimited protobuf field
 * @param {number} fieldNumber - Field number
 * @param {string} value - String value
 * @returns {Buffer} Encoded field
 */
function encodeString(fieldNumber, value) {
  const tag = encodeTag(fieldNumber, 2);
  const strBytes = Buffer.from(value, 'utf-8');
  const length = encodeVarint(strBytes.length);
  return Buffer.concat([tag, length, strBytes]);
}

/**
 * Encode a varint field
 * @param {number} fieldNumber - Field number
 * @param {number} value - Integer value
 * @returns {Buffer} Encoded field
 */
function encodeVarintField(fieldNumber, value) {
  const tag = encodeTag(fieldNumber, 0);
  const valueBytes = encodeVarint(value);
  return Buffer.concat([tag, valueBytes]);
}

/**
 * Encode a length-delimited bytes field
 * @param {number} fieldNumber - Field number
 * @param {Buffer} value - Bytes value
 * @returns {Buffer} Encoded field
 */
function encodeBytesField(fieldNumber, value) {
  const tag = encodeTag(fieldNumber, 2);
  const length = encodeVarint(value.length);
  return Buffer.concat([tag, length, value]);
}

/**
 * Encode the innermost marker content
 * @param {Object} marker - Marker data
 * @param {number} marker.color - Color code
 * @param {string} [marker.name=''] - Marker name
 * @param {string} marker.refId - Reference ID
 * @param {string} marker.note - Marker description/note
 * @returns {Buffer} Encoded content
 */
function encodeMarkerContent(marker) {
  const parts = [];

  // Field 1 (varint): color code
  parts.push(encodeVarintField(1, marker.color || MARKER_COLORS.BLUE));

  // Field 3 (string): name (usually empty)
  parts.push(encodeString(3, marker.name || ''));

  // Field 3 (string): reference ID
  parts.push(encodeString(3, marker.refId || ''));

  // Field 3 (string): description/note
  parts.push(encodeString(3, marker.note || ''));

  return Buffer.concat(parts);
}

/**
 * Encode inner protobuf wrapper for marker data
 * @param {Object} marker - Marker data
 * @returns {Buffer} Encoded inner protobuf
 */
function encodeMarkerInner(marker) {
  const content = encodeMarkerContent(marker);
  // Wrap content in Field 1 (nested message)
  return encodeBytesField(1, content);
}

/**
 * Encode complete marker data with 8-byte header
 * @param {Object} marker - Marker data
 * @returns {Buffer} Encoded marker data
 */
function encodeMarkerData(marker) {
  const inner = encodeMarkerInner(marker);

  // 8-byte header (Big-Endian):
  // - 4 bytes: Type = 2
  // - 4 bytes: Inner protobuf length
  const header = Buffer.alloc(8);
  header.writeUInt32BE(2, 0);
  header.writeUInt32BE(inner.length, 4);

  return Buffer.concat([header, inner]);
}

/**
 * Encode a complete marker entry
 * @param {Object} marker - Marker data
 * @param {number} marker.frame - Frame number
 * @param {number} marker.color - Color code
 * @param {string} marker.refId - Reference ID
 * @param {string} marker.note - Description
 * @returns {Buffer} Encoded marker entry
 */
function encodeMarkerEntry(marker) {
  const parts = [];

  // Field 1 (varint): frame number
  parts.push(encodeVarintField(1, marker.frame));

  // Field 2 (bytes): marker data
  const markerData = encodeMarkerData(marker);
  parts.push(encodeBytesField(2, markerData));

  return Buffer.concat(parts);
}

/**
 * Encode all markers into container
 * @param {Object[]} markers - Array of marker objects
 * @returns {Buffer} Encoded container
 */
function encodeMarkerContainer(markers) {
  const parts = [];

  for (const marker of markers) {
    const entry = encodeMarkerEntry(marker);
    // Each entry wrapped in Field 1 (repeated)
    parts.push(encodeBytesField(1, entry));
  }

  return Buffer.concat(parts);
}

/**
 * Encode markers to complete protobuf
 * @param {Object[]} markers - Array of marker objects
 * @returns {Buffer} Encoded protobuf
 */
function encodeMarkersProtobuf(markers) {
  const container = encodeMarkerContainer(markers);
  // Wrap in Field 2
  return encodeBytesField(2, container);
}

/**
 * Compress markers protobuf with ZSTD
 * Note: Node.js doesn't have native ZSTD, uses zlib deflate as fallback
 * For production, use 'zstd-codec' or 'node-zstandard' npm package
 *
 * @param {Object[]} markers - Array of marker objects
 * @returns {Buffer} Compressed data
 */
function compressMarkers(markers) {
  const protobuf = encodeMarkersProtobuf(markers);

  // For full DRP compatibility, use ZSTD compression
  // This requires installing: npm install @pxtrn/zstd or similar
  // For now, return uncompressed with a note
  console.warn('Note: For full DRP compatibility, use ZSTD compression');

  // Return protobuf as-is (would need ZSTD for actual DRP files)
  return protobuf;
}

/**
 * Decode markers from compressed protobuf
 * @param {Buffer} compressed - ZSTD compressed data
 * @returns {Object[]} Array of decoded markers
 */
function decodeMarkers(compressed) {
  // For ZSTD decompression, use 'zstd-codec' npm package
  // This is a simplified implementation assuming uncompressed data
  const protobuf = compressed;

  const markers = [];
  let offset = 0;

  // Skip Field 2 container tag
  const { bytesRead: tagBytes } = decodeVarint(protobuf, 0);
  offset = tagBytes;
  const { value: containerLen, bytesRead: lenBytes } = decodeVarint(protobuf, offset);
  offset += lenBytes;

  const container = protobuf.slice(offset, offset + containerLen);

  // Parse each marker entry
  let containerOffset = 0;
  while (containerOffset < container.length) {
    const tag = container[containerOffset];
    if ((tag & 0x7) !== 2) break;

    const { value: entryLen, bytesRead } = decodeVarint(container, containerOffset + 1);
    containerOffset += 1 + bytesRead;

    const entry = container.slice(containerOffset, containerOffset + entryLen);
    containerOffset += entryLen;

    const marker = parseMarkerEntry(entry);
    markers.push(marker);
  }

  return markers;
}

/**
 * Parse a single marker entry
 * @param {Buffer} entry - Marker entry bytes
 * @returns {Object} Parsed marker
 */
function parseMarkerEntry(entry) {
  const marker = {
    frame: 0,
    color: MARKER_COLORS.BLUE,
    name: '',
    refId: '',
    note: '',
  };

  let offset = 0;
  while (offset < entry.length) {
    const tag = entry[offset];
    const fieldNum = tag >> 3;
    const wireType = tag & 0x7;
    offset++;

    if (wireType === 0) {
      // Varint
      const { value, bytesRead } = decodeVarint(entry, offset);
      offset += bytesRead;
      if (fieldNum === 1) {
        marker.frame = value;
      }
    } else if (wireType === 2) {
      // Length-delimited
      const { value: len, bytesRead } = decodeVarint(entry, offset);
      offset += bytesRead;
      const data = entry.slice(offset, offset + len);
      offset += len;

      if (fieldNum === 2 && data.length > 8) {
        // Skip 8-byte header, parse inner protobuf
        const inner = data.slice(8);
        parseMarkerInner(inner, marker);
      }
    }
  }

  return marker;
}

/**
 * Parse inner marker protobuf
 * @param {Buffer} inner - Inner protobuf bytes
 * @param {Object} marker - Marker object to populate
 */
function parseMarkerInner(inner, marker) {
  let offset = 0;
  while (offset < inner.length) {
    const tag = inner[offset];
    const fieldNum = tag >> 3;
    const wireType = tag & 0x7;
    offset++;

    if (wireType === 2) {
      const { value: len, bytesRead } = decodeVarint(inner, offset);
      offset += bytesRead;
      const content = inner.slice(offset, offset + len);
      offset += len;

      // Parse content
      parseMarkerContent(content, marker);
    }
  }
}

/**
 * Parse marker content fields
 * @param {Buffer} content - Content bytes
 * @param {Object} marker - Marker object to populate
 */
function parseMarkerContent(content, marker) {
  let offset = 0;
  let stringIndex = 0;

  while (offset < content.length) {
    const tag = content[offset];
    const fieldNum = tag >> 3;
    const wireType = tag & 0x7;
    offset++;

    if (wireType === 0) {
      // Varint
      const { value, bytesRead } = decodeVarint(content, offset);
      offset += bytesRead;
      marker.color = value;
    } else if (wireType === 2) {
      // String
      const { value: len, bytesRead } = decodeVarint(content, offset);
      offset += bytesRead;
      const str = content.slice(offset, offset + len).toString('utf-8');
      offset += len;

      if (stringIndex === 0) {
        marker.name = str;
      } else if (stringIndex === 1) {
        marker.refId = str;
      } else if (stringIndex === 2) {
        marker.note = str;
      }
      stringIndex++;
    }
  }
}

/**
 * Create FieldsBlob header for markers
 * @param {Buffer} compressedData - ZSTD compressed protobuf
 * @returns {Buffer} Complete FieldsBlob with header
 */
function createFieldsBlob(compressedData) {
  const parts = [];

  // Version (4 bytes BE)
  const version = Buffer.alloc(4);
  version.writeUInt32BE(1, 0);
  parts.push(version);

  // Field count (4 bytes BE)
  const fieldCount = Buffer.alloc(4);
  fieldCount.writeUInt32BE(1, 0);
  parts.push(fieldCount);

  // Field name: "BlobData" (UTF-16BE)
  const fieldName = Buffer.from('BlobData', 'utf16le').swap16();
  const nameLen = Buffer.alloc(4);
  nameLen.writeUInt32BE(fieldName.length, 0);
  parts.push(nameLen);
  parts.push(fieldName);

  // Data length (12 bytes for BlobData metadata)
  const dataLen = Buffer.alloc(4);
  dataLen.writeUInt32BE(12, 0);
  parts.push(dataLen);

  // BlobData value (12 bytes metadata)
  const blobDataValue = Buffer.alloc(12);
  blobDataValue.writeUInt32BE(2, 0); // Type
  // Remaining bytes can be calculated based on compressed size
  parts.push(blobDataValue);

  // Magic prefix before ZSTD
  parts.push(Buffer.from([0xad, 0x81]));

  // Compressed data
  parts.push(compressedData);

  return Buffer.concat(parts);
}

/**
 * Convert timecode string to frame number
 * @param {string} timecode - Timecode in HH:MM:SS:FF format
 * @param {number} frameRate - Frame rate (default 23.976)
 * @returns {number} Frame number
 */
function timecodeToFrame(timecode, frameRate = 23.976) {
  const parts = timecode.split(':').map(Number);
  if (parts.length !== 4) {
    throw new Error('Invalid timecode format. Use HH:MM:SS:FF');
  }

  const [hours, minutes, seconds, frames] = parts;
  const totalSeconds = hours * 3600 + minutes * 60 + seconds;
  return Math.round(totalSeconds * frameRate) + frames;
}

/**
 * Convert frame number to timecode string
 * @param {number} frame - Frame number
 * @param {number} frameRate - Frame rate (default 23.976)
 * @returns {string} Timecode in HH:MM:SS:FF format
 */
function frameToTimecode(frame, frameRate = 23.976) {
  const totalSeconds = frame / frameRate;
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = Math.floor(totalSeconds % 60);
  const frames = Math.round((totalSeconds % 1) * frameRate);

  return [hours, minutes, seconds, frames]
    .map((v) => v.toString().padStart(2, '0'))
    .join(':');
}

/**
 * Create a marker object with default values
 * @param {Object} options - Marker options
 * @param {number|string} options.position - Frame number or timecode string
 * @param {string} [options.note=''] - Marker description
 * @param {string} [options.refId=''] - Reference ID
 * @param {number|string} [options.color='blue'] - Color code or name
 * @param {string} [options.name=''] - Marker name
 * @param {number} [options.frameRate=23.976] - Frame rate for timecode conversion
 * @returns {Object} Marker object ready for encoding
 */
function createMarker(options) {
  let frame = options.position;
  if (typeof frame === 'string') {
    frame = timecodeToFrame(frame, options.frameRate || 23.976);
  }

  let color = options.color || MARKER_COLORS.BLUE;
  if (typeof color === 'string') {
    const colorName = color.toUpperCase();
    color = MARKER_COLORS[colorName] || MARKER_COLORS.BLUE;
  }

  return {
    frame,
    color,
    name: options.name || '',
    refId: options.refId || '',
    note: options.note || '',
  };
}

module.exports = {
  // Main encoding/decoding functions
  encodeMarkersProtobuf,
  decodeMarkers,
  compressMarkers,
  createFieldsBlob,

  // Marker creation helpers
  createMarker,
  timecodeToFrame,
  frameToTimecode,

  // Low-level utilities
  encodeVarint,
  decodeVarint,
  encodeTag,
  encodeString,
  encodeVarintField,
  encodeBytesField,
  encodeMarkerEntry,
  parseMarkerEntry,

  // Constants
  MARKER_COLORS,
};
