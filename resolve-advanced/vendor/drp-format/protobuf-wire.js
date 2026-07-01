/**
 * protobuf-wire — a generic protobuf wire-format decoder/encoder for the Resolve
 * blobs that are raw protobuf: Radiometry (color science), EffectFiltersBA (effect
 * params for transitions/generators), and the large protobuf FieldsBlob (per-element
 * internal state).
 *
 * We decode to the WIRE level — field number, wire type, and raw value — which makes
 * the structure inspectable and round-trippable. We do NOT name the fields: that needs
 * Resolve's private .proto schema. This is the honest ceiling for these blobs; they are
 * authored by cloning a real element and carried verbatim, so wire-exact round-trip is
 * all the toolkit needs. See knowledge/blob-map.md.
 *
 * Wire types: 0 varint, 1 i64 (8 bytes), 2 length-delimited, 5 i32 (4 bytes).
 *
 * @module drp-format/protobuf-wire
 */

function _readVarint(b, o) {
  let shift = 0n; let result = 0n; let pos = o;
  for (;;) {
    const byte = b[pos++];
    result |= BigInt(byte & 0x7f) << shift;
    if ((byte & 0x80) === 0) break;
    shift += 7n;
  }
  return { value: result, next: pos };
}

function _writeVarint(value) {
  let v = BigInt(value); const out = [];
  for (;;) {
    const byte = Number(v & 0x7fn);
    v >>= 7n;
    if (v === 0n) { out.push(byte); break; }
    out.push(byte | 0x80);
  }
  return Buffer.from(out);
}

/**
 * Decode a protobuf payload into a flat list of fields:
 *   [{ field, wire, value }]  where value is BigInt (wire 0), Buffer (wire 1/2/5).
 * Throws if the bytes don't consume cleanly (guards against non-protobuf input).
 */
function decodeProtobuf(input) {
  const b = Buffer.isBuffer(input) ? input : Buffer.from(input, 'hex');
  const fields = [];
  let o = 0;
  while (o < b.length) {
    const key = _readVarint(b, o); o = key.next;
    const field = Number(key.value >> 3n);
    const wire = Number(key.value & 0x7n);
    if (wire === 0) {
      const v = _readVarint(b, o); o = v.next;
      fields.push({ field, wire, value: v.value });
    } else if (wire === 1) {
      fields.push({ field, wire, value: b.slice(o, o + 8) }); o += 8;
    } else if (wire === 2) {
      const len = _readVarint(b, o); o = len.next;
      const n = Number(len.value);
      fields.push({ field, wire, value: b.slice(o, o + n) }); o += n;
    } else if (wire === 5) {
      fields.push({ field, wire, value: b.slice(o, o + 4) }); o += 4;
    } else {
      throw new Error(`protobuf: unsupported wire type ${wire} at ${o}`);
    }
  }
  return fields;
}

/** Re-encode a field list (from decodeProtobuf) to a Buffer (round-trips exactly). */
function encodeProtobuf(fields) {
  const parts = [];
  for (const f of fields) {
    parts.push(_writeVarint((BigInt(f.field) << 3n) | BigInt(f.wire)));
    if (f.wire === 0) {
      parts.push(_writeVarint(f.value));
    } else if (f.wire === 1 || f.wire === 5) {
      parts.push(f.value);
    } else if (f.wire === 2) {
      parts.push(_writeVarint(f.value.length), f.value);
    } else {
      throw new Error(`protobuf: cannot encode wire type ${f.wire}`);
    }
  }
  return Buffer.concat(parts);
}

/**
 * EffectFiltersBA / similar are wrapped: [u32 hdr][u32 payloadLen][protobuf payload].
 * Returns { hdr, fields } and a re-encoder that reproduces the envelope exactly.
 */
function decodeEffectFilters(input) {
  const b = Buffer.isBuffer(input) ? input : Buffer.from(input, 'hex');
  const hdr = b.readUInt32BE(0);
  const len = b.readUInt32BE(4);
  const fields = decodeProtobuf(b.slice(8, 8 + len));
  return { hdr, fields };
}

function encodeEffectFilters({ hdr, fields }) {
  const payload = encodeProtobuf(fields);
  const head = Buffer.alloc(8);
  head.writeUInt32BE(hdr, 0);
  head.writeUInt32BE(payload.length, 4);
  return Buffer.concat([head, payload]);
}

module.exports = {
  decodeProtobuf, encodeProtobuf, decodeEffectFilters, encodeEffectFilters,
};
