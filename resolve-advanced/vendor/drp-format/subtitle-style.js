/**
 * DaVinci Resolve subtitle-track style codec.
 *
 * Reads and writes the caption style Resolve stores on a SUBTITLE track
 * (`Sm2TiTrack` rows with `Type = 2`). The scripting API exposes none of this:
 * subtitle TimelineItems return only the 21 transform/composite properties, and
 * `Timeline`/`Project.GetSetting()` return null for every subtitle-style key. See
 * the `Subtitle track styling and presets` entry in src/utils/api_truth.py.
 *
 * Container chain (outermost first):
 *
 *   Sm2TiTrack.FieldsBlob        keyed-dict (keyed-dict.js) — { NumLayers, EffectFiltersBA }
 *     -> EffectFiltersBA         [u32 version=2][u32 payloadLen][u8 0x80|0x81][payload]
 *          0x80 = raw protobuf, 0x81 = compressed (Resolve 21 writes ZSTD)
 *       -> protobuf              repeated f1 = effect, each:
 *                                  f1 varint  effect id (136 carries the text style)
 *                                  f9 LEN     parameter, repeated and POSITIONAL —
 *                                             empty f9 entries are placeholders and
 *                                             MUST be preserved to keep param order
 *                                    f1 varint param id
 *                                    f3 LEN    value wrapper -> f1 LEN -> one of:
 *                                                f1 varint  integer
 *                                                f3 LEN     string
 *                                                f2 fixed64 double  (LITTLE-endian)
 *                                                f7 LEN     double vector (BIG-endian)
 *
 * Note the endianness split: scalar doubles (f2) are little-endian, but the f7
 * double vector used by the position parameter is big-endian. Both were confirmed
 * against live Resolve 21 projects — reading either one with the wrong order
 * yields plausible-looking garbage (~1e-319), so this is worth not "fixing".
 *
 * Only two parameters of effect 136 are given names here, because only these two
 * are self-describing:
 *   param 18 — Qt QFont::toString() descriptor, e.g.
 *              "Helvetica,13,-1,5,50,0,0,0,0,0,Regular"
 *              (family, pointSize, pixelSize, styleHint, weight, italic,
 *               underline, strikeOut, fixedPitch, rawMode, styleName)
 *   param 17 — normalised position vector [x, y], origin top-left, e.g. [0.5, 0.109]
 *
 * Every other parameter (19, 34, 142, and effects 16/54/56) round-trips untouched
 * and is reported under `opaque`. They vary across real projects but their meaning
 * has NOT been correlated against the UI, so they are deliberately left unlabelled
 * rather than guessed at.
 *
 * @module drp-format/subtitle-style
 */

const { decodeKeyedDict, encodeKeyedDict } = require('./keyed-dict.js');

let fzstd = null;
try { fzstd = require('fzstd'); } catch (e) { /* optional; 0x81 zstd payloads need it */ }

const TEXT_STYLE_EFFECT = 136;
const PARAM_FONT = 18;
const PARAM_POSITION = 17;

const ZSTD_MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd]);

// ---------------------------------------------------------------------------
// protobuf primitives (field-preserving: we never drop unknown fields)
// ---------------------------------------------------------------------------

function readVarint(buf, off) {
  let value = 0n;
  let shift = 0n;
  let n = 0;
  while (off + n < buf.length) {
    const byte = buf[off + n];
    value |= BigInt(byte & 0x7f) << shift;
    n += 1;
    if (!(byte & 0x80)) return { value: Number(value), bytesRead: n };
    shift += 7n;
  }
  throw new Error('truncated varint');
}

function writeVarint(value) {
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
 * Parse a protobuf message into a flat list of {field, wire, ...} records.
 * Length-delimited payloads are kept as raw Buffers so unknown structure
 * survives a re-encode byte-for-byte.
 */
function parseMessage(buf) {
  const out = [];
  let off = 0;
  while (off < buf.length) {
    const tag = readVarint(buf, off);
    off += tag.bytesRead;
    const field = tag.value >> 3;
    const wire = tag.value & 7;
    if (wire === 0) {
      const v = readVarint(buf, off);
      off += v.bytesRead;
      out.push({ field, wire, value: v.value });
    } else if (wire === 1) {
      out.push({ field, wire, bytes: buf.slice(off, off + 8) });
      off += 8;
    } else if (wire === 2) {
      const len = readVarint(buf, off);
      off += len.bytesRead;
      out.push({ field, wire, bytes: buf.slice(off, off + len.value) });
      off += len.value;
    } else if (wire === 5) {
      out.push({ field, wire, bytes: buf.slice(off, off + 4) });
      off += 4;
    } else {
      throw new Error(`unsupported protobuf wire type ${wire} at offset ${off}`);
    }
  }
  return out;
}

function serializeMessage(records) {
  const parts = [];
  for (const rec of records) {
    parts.push(writeVarint((rec.field << 3) | rec.wire));
    if (rec.wire === 0) {
      parts.push(writeVarint(rec.value));
    } else if (rec.wire === 2) {
      parts.push(writeVarint(rec.bytes.length));
      parts.push(rec.bytes);
    } else {
      parts.push(rec.bytes);
    }
  }
  return Buffer.concat(parts);
}

// ---------------------------------------------------------------------------
// EffectFiltersBA envelope
// ---------------------------------------------------------------------------

function unwrapEffectFilters(raw) {
  if (raw.length < 9) throw new Error('EffectFiltersBA too short');
  const version = raw.readUInt32BE(0);
  const declared = raw.readUInt32BE(4);
  const marker = raw[8];
  const payload = raw.slice(9);
  if (declared !== payload.length + 1) {
    throw new Error(`EffectFiltersBA length mismatch: declared ${declared}, payload ${payload.length + 1}`);
  }
  if (marker === 0x80) return { version, marker, protobuf: payload };
  if (marker === 0x81) {
    if (!payload.slice(0, 4).equals(ZSTD_MAGIC)) {
      throw new Error('EffectFiltersBA 0x81 payload is not a zstd frame');
    }
    if (!fzstd) throw new Error("EffectFiltersBA 0x81 payload is zstd; optional dep 'fzstd' is required to decode");
    return { version, marker, protobuf: Buffer.from(fzstd.decompress(new Uint8Array(payload))) };
  }
  throw new Error(`unknown EffectFiltersBA payload marker 0x${marker.toString(16)}`);
}

/**
 * Re-wrap a protobuf payload as EffectFiltersBA.
 *
 * Always emits the UNCOMPRESSED 0x80 form. This avoids depending on a zstd
 * *compressor* (the bundled fzstd is decompress-only); the cost is a larger
 * blob, which does not matter here.
 *
 * Confirmed live against Resolve 21 (2026-08-06): a subtitle track patched with
 * a 0x80 payload opens without error, and once Resolve next re-serialises that
 * track it writes the style back out as 0x81 zstd with the font descriptor and
 * position preserved exactly — i.e. Resolve genuinely parses the 0x80 form into
 * its in-memory model rather than passing the bytes through untouched.
 */
function wrapEffectFilters(protobuf, version = 2) {
  const head = Buffer.alloc(9);
  head.writeUInt32BE(version, 0);
  head.writeUInt32BE(protobuf.length + 1, 4);
  head[8] = 0x80;
  return Buffer.concat([head, protobuf]);
}

// ---------------------------------------------------------------------------
// parameter access
// ---------------------------------------------------------------------------

/** Split one effect into { idRecord, params: [{record, id, wrapper}] , others } */
function readEffect(effectBytes) {
  const records = parseMessage(effectBytes);
  const params = [];
  for (const rec of records) {
    if (rec.field !== 9 || rec.wire !== 2 || rec.bytes.length === 0) continue;
    const inner = parseMessage(rec.bytes);
    const idRec = inner.find((r) => r.field === 1 && r.wire === 0);
    if (!idRec) continue;
    params.push({ record: rec, id: idRec.value, inner });
  }
  const idRec = records.find((r) => r.field === 1 && r.wire === 0);
  return { records, effectId: idRec ? idRec.value : null, params };
}

/** Decode the value wrapper (f3 -> f1 -> typed leaf) into a JS value. */
function readParamValue(wrapperBytes) {
  const outer = parseMessage(wrapperBytes).find((r) => r.field === 1 && r.wire === 2);
  if (!outer) return null;
  const leaves = parseMessage(outer.bytes);
  const result = {};
  for (const leaf of leaves) {
    if (leaf.field === 1 && leaf.wire === 0) result.int = leaf.value;
    else if (leaf.field === 3 && leaf.wire === 2) result.string = leaf.bytes.toString('utf8');
    else if (leaf.field === 2 && leaf.wire === 1) result.double = leaf.bytes.readDoubleLE(0);
    else if (leaf.field === 7 && leaf.wire === 2) {
      // BIG-endian double vector — see module note on the endianness split.
      const vec = [];
      for (let i = 0; i + 8 <= leaf.bytes.length; i += 8) vec.push(leaf.bytes.readDoubleBE(i));
      result.vector = vec;
    }
  }
  return Object.keys(result).length ? result : null;
}

/** Rebuild a value wrapper, replacing the string leaf. */
function writeStringParam(wrapperBytes, text) {
  const outerRecords = parseMessage(wrapperBytes);
  const outer = outerRecords.find((r) => r.field === 1 && r.wire === 2);
  if (!outer) throw new Error('parameter wrapper has no inner message');
  const leaves = parseMessage(outer.bytes);
  const target = leaves.find((l) => l.field === 3 && l.wire === 2);
  if (!target) throw new Error('parameter has no string leaf to replace');
  target.bytes = Buffer.from(text, 'utf8');
  outer.bytes = serializeMessage(leaves);
  return serializeMessage(outerRecords);
}

/** Rebuild a value wrapper, replacing the big-endian double vector. */
function writeVectorParam(wrapperBytes, values) {
  const outerRecords = parseMessage(wrapperBytes);
  const outer = outerRecords.find((r) => r.field === 1 && r.wire === 2);
  if (!outer) throw new Error('parameter wrapper has no inner message');
  const leaves = parseMessage(outer.bytes);
  const target = leaves.find((l) => l.field === 7 && l.wire === 2);
  if (!target) throw new Error('parameter has no vector leaf to replace');
  if (values.length * 8 !== target.bytes.length) {
    throw new Error(`vector arity mismatch: existing ${target.bytes.length / 8} values, given ${values.length}`);
  }
  const buf = Buffer.alloc(values.length * 8);
  values.forEach((v, i) => buf.writeDoubleBE(v, i * 8));
  target.bytes = buf;
  outer.bytes = serializeMessage(leaves);
  return serializeMessage(outerRecords);
}

// ---------------------------------------------------------------------------
// QFont descriptor
// ---------------------------------------------------------------------------

/**
 * Parse a Qt QFont::toString() descriptor.
 * Fields after the family are positional; unknown trailing fields are kept
 * verbatim so a re-serialise is lossless.
 */
function parseFontDescriptor(descriptor) {
  const parts = String(descriptor).split(',');
  return {
    family: parts[0],
    pointSize: parts.length > 1 ? Number(parts[1]) : null,
    pixelSize: parts.length > 2 ? Number(parts[2]) : null,
    styleHint: parts.length > 3 ? Number(parts[3]) : null,
    weight: parts.length > 4 ? Number(parts[4]) : null,
    italic: parts.length > 5 ? parts[5] === '1' : null,
    styleName: parts.length > 10 ? parts[10] : null,
    raw: descriptor,
    _parts: parts,
  };
}

function buildFontDescriptor(parsed, changes) {
  const parts = parsed._parts.slice();
  if (changes.family != null) parts[0] = String(changes.family);
  if (changes.pointSize != null && parts.length > 1) parts[1] = String(changes.pointSize);
  if (changes.weight != null && parts.length > 4) parts[4] = String(changes.weight);
  if (changes.italic != null && parts.length > 5) parts[5] = changes.italic ? '1' : '0';
  if (changes.styleName != null && parts.length > 10) parts[10] = String(changes.styleName);
  return parts.join(',');
}

// ---------------------------------------------------------------------------
// public API
// ---------------------------------------------------------------------------

/**
 * Decode the caption style from an Sm2TiTrack.FieldsBlob.
 *
 * @param {Buffer|string} fieldsBlob - raw blob or hex string
 * @returns {{styled: boolean, font: object|null, position: {x: number, y: number}|null,
 *            opaque: Array, effects: Array}}
 *   `styled: false` means the track carries no EffectFiltersBA at all (Resolve
 *   writes a ~39-byte NumLayers-only stub for an unstyled subtitle track).
 */
function decodeSubtitleStyle(fieldsBlob) {
  const buf = Buffer.isBuffer(fieldsBlob) ? fieldsBlob : Buffer.from(fieldsBlob, 'hex');
  const dict = decodeKeyedDict(buf);
  const entry = dict.entries.find((e) => e.key === 'EffectFiltersBA');
  if (!entry || !entry.value) {
    return { styled: false, font: null, position: null, opaque: [], effects: [] };
  }
  const { protobuf } = unwrapEffectFilters(Buffer.from(entry.value, 'hex'));
  const effects = parseMessage(protobuf).filter((r) => r.field === 1 && r.wire === 2);

  let font = null;
  let position = null;
  const opaque = [];
  const summary = [];

  for (const effectRec of effects) {
    const effect = readEffect(effectRec.bytes);
    const paramSummary = [];
    for (const param of effect.params) {
      const wrapper = param.inner.find((r) => r.field === 3 && r.wire === 2);
      const value = wrapper ? readParamValue(wrapper.bytes) : null;
      paramSummary.push({ id: param.id, value });
      if (effect.effectId === TEXT_STYLE_EFFECT && param.id === PARAM_FONT && value && value.string) {
        font = parseFontDescriptor(value.string);
      } else if (effect.effectId === TEXT_STYLE_EFFECT && param.id === PARAM_POSITION && value && value.vector) {
        position = { x: value.vector[0], y: value.vector[1] };
      } else if (value) {
        opaque.push({ effect: effect.effectId, param: param.id, value });
      }
    }
    summary.push({ effect: effect.effectId, params: paramSummary });
  }
  return { styled: true, font, position, opaque, effects: summary };
}

/**
 * Return a new FieldsBlob with the caption style modified.
 *
 * Only the font descriptor and position are writable; every other parameter and
 * effect is re-emitted untouched. Throws rather than silently no-op'ing when the
 * track has no style blob to patch, or when a requested change has no target
 * parameter — a silent no-op here would read as success.
 *
 * @param {Buffer|string} fieldsBlob
 * @param {{family?: string, pointSize?: number, weight?: number, italic?: boolean,
 *          styleName?: string, position?: {x: number, y: number}}} changes
 * @returns {Buffer} new FieldsBlob
 */
function encodeSubtitleStyle(fieldsBlob, changes = {}) {
  const buf = Buffer.isBuffer(fieldsBlob) ? fieldsBlob : Buffer.from(fieldsBlob, 'hex');
  const dict = decodeKeyedDict(buf);
  const entry = dict.entries.find((e) => e.key === 'EffectFiltersBA');
  if (!entry || !entry.value) {
    throw new Error(
      'track has no EffectFiltersBA — it is an unstyled subtitle track; ' +
      'style it once in the Resolve UI so a style blob exists to patch',
    );
  }
  const envelope = unwrapEffectFilters(Buffer.from(entry.value, 'hex'));
  const records = parseMessage(envelope.protobuf);

  const wantsFont = changes.family != null || changes.pointSize != null ||
    changes.weight != null || changes.italic != null || changes.styleName != null;
  const wantsPosition = changes.position != null;
  let fontDone = false;
  let positionDone = false;

  for (const effectRec of records) {
    if (effectRec.field !== 1 || effectRec.wire !== 2) continue;
    const effect = readEffect(effectRec.bytes);
    if (effect.effectId !== TEXT_STYLE_EFFECT) continue;
    let touched = false;
    for (const param of effect.params) {
      const wrapper = param.inner.find((r) => r.field === 3 && r.wire === 2);
      if (!wrapper) continue;
      if (wantsFont && param.id === PARAM_FONT) {
        const current = readParamValue(wrapper.bytes);
        if (!current || !current.string) continue;
        const next = buildFontDescriptor(parseFontDescriptor(current.string), changes);
        wrapper.bytes = writeStringParam(wrapper.bytes, next);
        param.record.bytes = serializeMessage(param.inner);
        fontDone = true;
        touched = true;
      } else if (wantsPosition && param.id === PARAM_POSITION) {
        const current = readParamValue(wrapper.bytes);
        if (!current || !current.vector) continue;
        wrapper.bytes = writeVectorParam(wrapper.bytes, [changes.position.x, changes.position.y]);
        param.record.bytes = serializeMessage(param.inner);
        positionDone = true;
        touched = true;
      }
    }
    if (touched) effectRec.bytes = serializeMessage(effect.records);
  }

  if (wantsFont && !fontDone) throw new Error(`no font parameter (${PARAM_FONT}) found on effect ${TEXT_STYLE_EFFECT}`);
  if (wantsPosition && !positionDone) throw new Error(`no position parameter (${PARAM_POSITION}) found on effect ${TEXT_STYLE_EFFECT}`);

  entry.value = wrapEffectFilters(serializeMessage(records), envelope.version).toString('hex');
  return encodeKeyedDict(dict);
}

module.exports = {
  decodeSubtitleStyle,
  encodeSubtitleStyle,
  // exposed for tests and for callers needing the lower layers
  parseMessage,
  serializeMessage,
  unwrapEffectFilters,
  wrapEffectFilters,
  parseFontDescriptor,
  buildFontDescriptor,
  TEXT_STYLE_EFFECT,
  PARAM_FONT,
  PARAM_POSITION,
};
