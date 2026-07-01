/**
 * DaVinci Resolve EffectFiltersBA Encoder/Decoder
 *
 * Encodes and decodes clip transform effects (Zoom, Pan, Rotation, Speed)
 * into DaVinci Resolve's binary EffectFiltersBA format.
 *
 * Format Overview:
 * - Header: 4-byte version (0x00000002, BE) + 4-byte payload size (BE)
 * - Payload types: 0x80 (uncompressed protobuf) or 0x81 (compressed)
 * - Parameters encoded as protobuf with IEEE 754 double values
 *
 * Resolve 21 finding (P0.3 ingest, 2026-06-19): The Resolve 21
 * DRP export no longer writes the EffectFiltersBA blob — it emits
 * <EffectFiltersBA/> empty self-closing even when cached ResolveFX
 * are present. The cached effect bag lives in the gallery-still DRX
 * route instead. This file's decoder remains correct for older
 * Resolve exports and any future re-enablement of DRP-side caching;
 * the compressed (0x81) path is implemented symmetrically per
 * Session 33.
 *
 * @module effect-encoder
 */

const zlib = require('node:zlib');

// Resolve 21 live Project.db compresses the 0x81 EffectFiltersBA payload with
// ZSTD (magic 28 B5 2F FD), not zlib — confirmed decoding a live project's
// Sm2TiItem.EffectFiltersBA. fzstd is decompress-only, which is all the
// read/diff path needs; the encoder writes uncompressed 0x80 (Resolve reads both).
let fzstd = null;
try { fzstd = require('fzstd'); } catch (e) { /* optional; zstd payloads need it */ }


/**
 * Effect parameter IDs in EffectFiltersBA
 */
const EFFECT_PARAMS = {
  ROTATION: 0x01,
  PAN_X: 0x28,      // 40
  PAN_Y: 0x29,      // 41
  ZOOM_X: 0x2a,     // 42
  ZOOM_Y: 0x2b,     // 43
  SPEED_SECTION: 0x2c,  // 44
  SPEED_FACTOR: 0x5b,   // 91
  SPEED_MODE: 0x5c,     // 92
};

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
 * Encode a varint (variable-length integer)
 * @param {number} value - Non-negative integer to encode
 * @returns {Buffer} Encoded varint bytes
 */
/**
 * Decompress an EffectFiltersBA 0x81 payload.
 *
 * The compression scheme is zlib — confirmed via byte signature
 * detection at offset 0 of the payload:
 *   0x78 = zlib (DEFLATE with zlib wrapper)
 *
 * If the magic doesn't match, falls back to raw inflate. Throws on
 * malformed input so callers see a clear failure rather than silently
 * mis-parsed protobuf garbage.
 *
 * @param {Buffer} compressed - bytes after the 0x81 marker
 * @returns {Buffer} - inflated protobuf payload (parsed by caller)
 */
function decompressEffectPayload(compressed) {
  if (!Buffer.isBuffer(compressed) || compressed.length === 0) {
    throw new Error('Compressed EffectFiltersBA payload is empty');
  }
  const firstByte = compressed[0];
  // ZSTD frame magic 28 B5 2F FD (Resolve 21 live Project.db).
  if (firstByte === 0x28 && compressed[1] === 0xb5 && compressed[2] === 0x2f && compressed[3] === 0xfd) {
    if (!fzstd) throw new Error("EffectFiltersBA 0x81 payload is zstd; install optional dep 'fzstd' to decode");
    return Buffer.from(fzstd.decompress(new Uint8Array(compressed)));
  }
  try {
    if (firstByte === 0x78) {
      // Standard zlib header
      return zlib.inflateSync(compressed);
    }
    // Fall through to raw inflate (DEFLATE without zlib wrapper).
    return zlib.inflateRawSync(compressed);
  } catch (err) {
    throw new Error(
      `Failed to decompress EffectFiltersBA 0x81 payload ` +
      `(first byte 0x${firstByte.toString(16)}): ${err.message}`,
    );
  }
}

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
 * @param {number} fieldNumber - Field number (1-536870911)
 * @param {number} wireType - Wire type (0, 1, 2, or 5)
 * @returns {Buffer} Encoded tag
 */
function encodeTag(fieldNumber, wireType) {
  const tag = (fieldNumber << 3) | wireType;
  return encodeVarint(tag);
}

/**
 * Encode an IEEE 754 double to little-endian bytes
 * @param {number} value - Double value
 * @returns {Buffer} 8-byte little-endian buffer
 */
function encodeDouble(value) {
  const buffer = Buffer.allocUnsafe(8);
  buffer.writeDoubleLE(value, 0);
  return buffer;
}

/**
 * Decode an IEEE 754 double from little-endian bytes
 * @param {Buffer} data - Buffer containing double
 * @param {number} offset - Start offset
 * @returns {number} Decoded double value
 */
function decodeDouble(data, offset = 0) {
  return data.readDoubleLE(offset);
}

/**
 * Encode an IEEE 754 float to little-endian hex string
 * @param {number} value - Float value
 * @returns {string} 8-character hex string
 */
function encodeFloat(value) {
  const buffer = Buffer.allocUnsafe(4);
  buffer.writeFloatLE(value, 0);
  return buffer.toString('hex');
}

/**
 * Common double values in hex for quick reference
 */
const DOUBLE_VALUES = {
  '1.0': '000000000000f03f',
  '1.1': '9a9999999999f13f',
  '0.9': '9a9999999999e93f',
  '2.0': '0000000000000040',
  '0.5': '000000000000e03f',
};

/**
 * Build a protobuf field with double value
 * @param {number} fieldNumber - Field number
 * @param {number} value - Double value
 * @returns {Buffer} Encoded field
 */
function buildDoubleField(fieldNumber, value) {
  // Field tag with wire type 1 (64-bit fixed)
  const tag = encodeTag(fieldNumber, WIRE_TYPES.FIXED64);
  const valueBytes = encodeDouble(value);
  return Buffer.concat([tag, valueBytes]);
}

/**
 * Build a protobuf field with varint value
 * @param {number} fieldNumber - Field number
 * @param {number} value - Integer value
 * @returns {Buffer} Encoded field
 */
function buildVarintField(fieldNumber, value) {
  const tag = encodeTag(fieldNumber, WIRE_TYPES.VARINT);
  const valueBytes = encodeVarint(value);
  return Buffer.concat([tag, valueBytes]);
}

/**
 * Build a length-delimited nested message
 * @param {number} fieldNumber - Field number
 * @param {Buffer} content - Nested content bytes
 * @returns {Buffer} Encoded field with length prefix
 */
function buildNestedField(fieldNumber, content) {
  const tag = encodeTag(fieldNumber, WIRE_TYPES.LENGTH_DELIMITED);
  const length = encodeVarint(content.length);
  return Buffer.concat([tag, length, content]);
}

/**
 * Create EffectFiltersBA blob for transform effects
 * @param {Object} transforms - Transform parameters
 * @param {number} [transforms.zoomX=1.0] - Horizontal zoom/scale (1.0 = 100%)
 * @param {number} [transforms.zoomY=1.0] - Vertical zoom/scale (1.0 = 100%)
 * @param {number} [transforms.panX=0] - Horizontal pan/position
 * @param {number} [transforms.panY=0] - Vertical pan/position
 * @param {number} [transforms.rotation=0] - Rotation in degrees
 * @returns {string} Hex-encoded EffectFiltersBA blob
 *
 * @example
 * // 110% zoom
 * encodeEffectFiltersBA({ zoomX: 1.1, zoomY: 1.1 })
 *
 * @example
 * // 10 degree rotation
 * encodeEffectFiltersBA({ rotation: 10 })
 */
function encodeEffectFiltersBA(transforms = {}) {
  const {
    zoomX = 1.0,
    zoomY = 1.0,
    panX = 0,
    panY = 0,
    rotation = 0,
  } = transforms;

  // Build inner protobuf payload
  const fields = [];

  // Always include zoom values (even if 1.0)
  fields.push(buildDoubleField(EFFECT_PARAMS.ZOOM_X, zoomX));
  fields.push(buildDoubleField(EFFECT_PARAMS.ZOOM_Y, zoomY));

  // Add pan if non-zero
  if (panX !== 0) {
    fields.push(buildDoubleField(EFFECT_PARAMS.PAN_X, panX));
  }
  if (panY !== 0) {
    fields.push(buildDoubleField(EFFECT_PARAMS.PAN_Y, panY));
  }

  // Add rotation if non-zero
  if (rotation !== 0) {
    fields.push(buildDoubleField(EFFECT_PARAMS.ROTATION, rotation));
  }

  // Combine all fields
  const payload = Buffer.concat(fields);

  // Build complete blob with header
  // Version: 0x00000002 (4 bytes BE)
  // Payload size: 4 bytes BE
  // Payload type marker: 0x80 (uncompressed)
  const version = Buffer.from([0x00, 0x00, 0x00, 0x02]);
  const payloadWithMarker = Buffer.concat([Buffer.from([0x80]), payload]);
  const size = Buffer.alloc(4);
  size.writeUInt32BE(payloadWithMarker.length, 0);

  const complete = Buffer.concat([version, size, payloadWithMarker]);
  return complete.toString('hex');
}

/**
 * Decode EffectFiltersBA blob to extract transform parameters
 * @param {string|Buffer} blob - Hex string or buffer of EffectFiltersBA data
 * @returns {Object} Decoded transform parameters
 *
 * @example
 * const transforms = decodeEffectFiltersBA(hexString);
 * console.log(transforms.zoomX, transforms.rotation);
 */
/** Walk a protobuf message into flat fields [{field, wire, value|bytes}]. */
function readProtoFields(buf) {
  const fields = [];
  let o = 0;
  while (o < buf.length) {
    const { value: tag, bytesRead } = decodeVarint(buf, o);
    o += bytesRead;
    const field = tag >> 3;
    const wire = tag & 0x7;
    if (wire === 0) {
      const v = decodeVarint(buf, o);
      o += v.bytesRead;
      fields.push({ field, wire, value: v.value });
    } else if (wire === 1) {
      fields.push({ field, wire, bytes: buf.slice(o, o + 8) });
      o += 8;
    } else if (wire === 2) {
      const l = decodeVarint(buf, o);
      o += l.bytesRead;
      fields.push({ field, wire, bytes: buf.slice(o, o + l.value) });
      o += l.value;
    } else if (wire === 5) {
      fields.push({ field, wire, bytes: buf.slice(o, o + 4) });
      o += 4;
    } else break;
  }
  return fields;
}

/**
 * Decode the Resolve 21 NESTED EffectFiltersBA layout:
 *   field1 (container) -> repeated field9 (param) -> { field1 varint = paramId,
 *   field3 (curve) -> field1 (keyframe) -> field2 fixed64 = value }.
 * Even static transforms are stored as a single-keyframe curve; a param with no
 * curve keeps its default (zoom 1.0, pan/rot 0). Returns null if this isn't the
 * nested layout (caller falls back to the legacy flat parse).
 */
function decodeTransformNested(payload) {
  const top = readProtoFields(payload);
  const container = top.find((f) => f.field === 1 && f.wire === 2);
  if (!container) return null;
  const t = { zoomX: 1.0, zoomY: 1.0, panX: 0, panY: 0, rotation: 0 };
  let sawParam = false;
  for (const p of readProtoFields(container.bytes).filter((f) => f.field === 9 && f.wire === 2)) {
    const pf = readProtoFields(p.bytes);
    const idF = pf.find((f) => f.field === 1 && f.wire === 0);
    if (!idF) continue;
    const curve = pf.find((f) => f.field === 3 && f.wire === 2);
    if (!curve) continue; // no curve -> default value
    const kf = readProtoFields(curve.bytes).find((f) => f.field === 1 && f.wire === 2);
    if (!kf) continue;
    const vF = readProtoFields(kf.bytes).find((f) => f.field === 2 && f.wire === 1);
    if (!vF) continue;
    const val = vF.bytes.readDoubleLE(0);
    sawParam = true;
    switch (idF.value) {
      case EFFECT_PARAMS.ZOOM_X: t.zoomX = val; break;
      case EFFECT_PARAMS.ZOOM_Y: t.zoomY = val; break;
      case EFFECT_PARAMS.PAN_X: t.panX = val; break;
      case EFFECT_PARAMS.PAN_Y: t.panY = val; break;
      case EFFECT_PARAMS.ROTATION: t.rotation = val; break;
      default: break;
    }
  }
  return sawParam || top.some((f) => f.field === 1) ? t : null;
}

/** Walk a protobuf message yielding fields with the ABSOLUTE offset of their value. */
function* walkProtoFields(buf, base = 0) {
  let o = 0;
  while (o < buf.length) {
    const { value: tag, bytesRead } = decodeVarint(buf, o);
    o += bytesRead;
    const field = tag >> 3;
    const wire = tag & 0x7;
    if (wire === 0) {
      const v = decodeVarint(buf, o);
      yield { field, wire, value: v.value, valOffset: base + o };
      o += v.bytesRead;
    } else if (wire === 1) {
      yield { field, wire, valOffset: base + o, bytes: buf.slice(o, o + 8) };
      o += 8;
    } else if (wire === 2) {
      const l = decodeVarint(buf, o);
      o += l.bytesRead;
      yield { field, wire, valOffset: base + o, bytes: buf.slice(o, o + l.value) };
      o += l.value;
    } else if (wire === 5) {
      yield { field, wire, valOffset: base + o, bytes: buf.slice(o, o + 4) };
      o += 4;
    } else return;
  }
}

const PARAM_FOR = { zoomX: EFFECT_PARAMS.ZOOM_X, zoomY: EFFECT_PARAMS.ZOOM_Y, panX: EFFECT_PARAMS.PAN_X, panY: EFFECT_PARAMS.PAN_Y, rotation: EFFECT_PARAMS.ROTATION };

/**
 * Surgically set transform values in an R21 NESTED EffectFiltersBA, preserving the
 * protobuf STRUCTURE byte-for-byte and only overwriting the targeted param curve's
 * fixed64 double(s). The result is re-wrapped UNCOMPRESSED (0x80) so Resolve reads
 * it without needing a zstd compressor. Only params that already have a curve are
 * patchable; ones without (identity, no keyframe) are returned in `skipped` (adding
 * a curve from scratch would require a full re-encode).
 *
 * @returns {{ blob: Buffer, patched: string[], skipped: string[] }}
 */
function patchTransformBlob(blob, values) {
  const data = typeof blob === 'string' ? Buffer.from(blob, 'hex') : blob;
  const version = data.readUInt32BE(0);
  if (version !== 2) throw new Error(`Unknown EffectFiltersBA version: ${version}`);
  const marker = data[8];
  let payload;
  if (marker === 0x81) payload = Buffer.from(decompressEffectPayload(data.slice(9)));
  else if (marker === 0x80) payload = Buffer.from(data.slice(9));
  else throw new Error(`Unknown payload type: 0x${marker.toString(16)}`);

  // locate each param's curve fixed64 offset
  const offsetByParam = new Map();
  const container = [...walkProtoFields(payload)].find((f) => f.field === 1 && f.wire === 2);
  if (container) {
    for (const p of walkProtoFields(container.bytes, container.valOffset)) {
      if (p.field !== 9 || p.wire !== 2) continue;
      const pf = [...walkProtoFields(p.bytes, p.valOffset)];
      const idF = pf.find((f) => f.field === 1 && f.wire === 0);
      const curve = pf.find((f) => f.field === 3 && f.wire === 2);
      if (!idF || !curve) continue;
      const kf = [...walkProtoFields(curve.bytes, curve.valOffset)].find((f) => f.field === 1 && f.wire === 2);
      if (!kf) continue;
      const vF = [...walkProtoFields(kf.bytes, kf.valOffset)].find((f) => f.field === 2 && f.wire === 1);
      if (vF) offsetByParam.set(idF.value, vF.valOffset);
    }
  }

  const patched = [];
  const skipped = [];
  for (const [key, val] of Object.entries(values)) {
    if (val == null) continue;
    const pid = PARAM_FOR[key];
    if (pid == null) continue;
    const off = offsetByParam.get(pid);
    if (off == null) { skipped.push(key); continue; }
    payload.writeDoubleLE(val, off);
    patched.push(key);
  }

  const header = Buffer.alloc(9);
  header.writeUInt32BE(2, 0);
  header.writeUInt32BE(payload.length, 4);
  header[8] = 0x80; // uncompressed (Resolve reads 0x80 and 0x81)
  return { blob: Buffer.concat([header, payload]), patched, skipped };
}

function decodeEffectFiltersBA(blob) {
  const data = typeof blob === 'string' ? Buffer.from(blob, 'hex') : blob;

  if (data.length < 8) {
    throw new Error('EffectFiltersBA too short');
  }

  // Read header
  const version = data.readUInt32BE(0);
  const payloadSize = data.readUInt32BE(4);

  if (version !== 2) {
    throw new Error(`Unknown EffectFiltersBA version: ${version}`);
  }

  const payloadType = data[8];

  // 2026-06-19 (Session 33, P0.3 ingest): Resolve 21 finding from
  // Session 30 capture — the DRP export writes <EffectFiltersBA/> as
  // empty self-closing in modern projects; the cached ResolveFX blob
  // lives in the gallery-still DRX route instead. The compressed
  // (0x81) payload is still expected to surface in older Resolve
  // exports + future versions that re-enable DRP-side caching, so we
  // implement the decoder symmetrically with the uncompressed path.
  //
  // Compression scheme: zlib raw or deflate (depending on Resolve
  // version). We attempt zlib (with header) first, fall back to raw
  // inflate. The decompressed bytes are then parsed as the same
  // protobuf payload the uncompressed path handles.
  let payload;
  if (payloadType === 0x81) {
    const compressed = data.slice(9);
    payload = decompressEffectPayload(compressed);
  } else if (payloadType === 0x80) {
    payload = data.slice(9);
  } else {
    throw new Error(`Unknown payload type: 0x${payloadType.toString(16)}`);
  }
  // Resolve 21 nested layout (field1 container -> params -> curve) first; the
  // legacy flat parse below handles older top-level fixed64 layouts.
  const nested = decodeTransformNested(payload);
  if (nested) return nested;

  const transforms = {
    zoomX: 1.0,
    zoomY: 1.0,
    panX: 0,
    panY: 0,
    rotation: 0,
  };

  let offset = 0;
  while (offset < payload.length) {
    const { value: tag, bytesRead: tagBytes } = decodeVarint(payload, offset);
    offset += tagBytes;

    const fieldNumber = tag >> 3;
    const wireType = tag & 0x7;

    if (wireType === WIRE_TYPES.FIXED64) {
      // 64-bit value (double)
      if (offset + 8 > payload.length) break;
      const value = decodeDouble(payload, offset);
      offset += 8;

      switch (fieldNumber) {
        case EFFECT_PARAMS.ZOOM_X:
          transforms.zoomX = value;
          break;
        case EFFECT_PARAMS.ZOOM_Y:
          transforms.zoomY = value;
          break;
        case EFFECT_PARAMS.PAN_X:
          transforms.panX = value;
          break;
        case EFFECT_PARAMS.PAN_Y:
          transforms.panY = value;
          break;
        case EFFECT_PARAMS.ROTATION:
          transforms.rotation = value;
          break;
      }
    } else if (wireType === WIRE_TYPES.VARINT) {
      const { value, bytesRead } = decodeVarint(payload, offset);
      offset += bytesRead;
    } else if (wireType === WIRE_TYPES.LENGTH_DELIMITED) {
      const { value: length, bytesRead } = decodeVarint(payload, offset);
      offset += bytesRead + length;
    } else if (wireType === WIRE_TYPES.FIXED32) {
      offset += 4;
    } else {
      throw new Error(`Unknown wire type: ${wireType}`);
    }
  }

  return transforms;
}

/**
 * Modify an existing EffectFiltersBA blob with new transform values
 * @param {string|Buffer} blob - Original blob
 * @param {Object} newValues - New transform values to apply
 * @returns {string} Modified hex-encoded blob
 *
 * @example
 * const modified = modifyEffectFiltersBA(original, { zoomX: 1.2 });
 */
function modifyEffectFiltersBA(blob, newValues) {
  // Decode existing values
  const current = decodeEffectFiltersBA(blob);

  // Merge with new values
  const merged = { ...current, ...newValues };

  // Re-encode
  return encodeEffectFiltersBA(merged);
}

/**
 * Create speed/retime effect data
 * @param {number} speedFactor - Speed multiplier (1.0 = normal, 2.0 = 2x speed)
 * @param {number} [speedMode=0] - Speed mode (0 = default)
 * @returns {string} Hex-encoded speed effect data
 */
function encodeSpeedEffect(speedFactor, speedMode = 0) {
  const fields = [];

  // Speed section container
  const speedSection = Buffer.concat([
    buildDoubleField(EFFECT_PARAMS.SPEED_FACTOR, speedFactor),
    buildVarintField(EFFECT_PARAMS.SPEED_MODE, speedMode),
  ]);

  fields.push(buildNestedField(EFFECT_PARAMS.SPEED_SECTION, speedSection));

  const payload = Buffer.concat(fields);

  // Build complete blob
  const version = Buffer.from([0x00, 0x00, 0x00, 0x02]);
  const payloadWithMarker = Buffer.concat([Buffer.from([0x80]), payload]);
  const size = Buffer.alloc(4);
  size.writeUInt32BE(payloadWithMarker.length, 0);

  return Buffer.concat([version, size, payloadWithMarker]).toString('hex');
}

/**
 * Create a neutral/empty EffectFiltersBA (no transforms applied)
 * @returns {string} Hex-encoded neutral effect blob
 */
function createNeutralEffectFiltersBA() {
  return encodeEffectFiltersBA({
    zoomX: 1.0,
    zoomY: 1.0,
    panX: 0,
    panY: 0,
    rotation: 0,
  });
}

module.exports = {
  // Main encoding/decoding functions
  encodeEffectFiltersBA,
  decodeEffectFiltersBA,
  decodeTransformNested,
  patchTransformBlob,
  modifyEffectFiltersBA,
  createNeutralEffectFiltersBA,
  encodeSpeedEffect,

  // Low-level utilities
  encodeVarint,
  decodeVarint,
  encodeDouble,
  decodeDouble,
  encodeFloat,
  encodeTag,
  buildDoubleField,
  buildVarintField,
  buildNestedField,

  // Constants
  EFFECT_PARAMS,
  WIRE_TYPES,
  DOUBLE_VALUES,
};
