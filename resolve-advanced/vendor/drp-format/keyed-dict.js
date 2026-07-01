/**
 * keyed-dict — read AND write the Media Pool metadata blob format shared by
 * Geometry / Time / VideoMetadata / Proxy (the BtVideoInfo sub-blobs).
 *
 * Layout (all big-endian):
 *   [u32 hdr=1][u32 count]
 *   then `count` entries: [u32 keyLen][UTF-16BE key][value]
 *   value = [u32 valType][u8 subType][payload]
 *     valType 0x0a (STRING) : [u32 byteLen][UTF-16BE chars]
 *     valType 0x0c (BYTES)  : [u32 byteLen][raw bytes]   (e.g. Resolution, FrameRate;
 *                             also a NESTED keyed-dict — e.g. TracksBA → BtAudioTrack)
 *     valType 0x02 (INT32)  : [i32 value]                (NumChannels, IdxTrack)
 *     valType 0x03 (UINT32) : [u32 value]                (SampleRate, BitDepth)
 *     valType 0x04/0x06 (I64): [i64 value, BigInt]       (Duration, StartTime)
 *
 * Audio config (BtAudioInfo) uses the SAME format: TracksBA = { "<idx>": BYTES(inner
 * BtAudioTrack dict) }; the inner dict carries SampleRate/NumChannels/CodecName/
 * ChannelLayout/BitDepth. VirtualAudioTrackBA = { ChannelsBA: BYTES(dict), AudioType }.
 *
 * The first key is always `UniqueId` (STRING UUID); the last is `DbType` (STRING)
 * naming the concrete type (BtGeometry / BtVideoTime / BtVideoMetadata / BtVideoProxy).
 *
 * Verified by exact round-trip reconstruction against real Resolve 21 exports — encode()
 * of decode() reproduces the original blob byte-for-byte. See knowledge/blob-map.md.
 *
 * @module drp-format/keyed-dict
 */

const T_BOOL = 0x01;    // 1-byte boolean (UI view-options: ShowSubtitle, …)
const T_INT32 = 0x02;   // signed 32-bit
const T_UINT32 = 0x03;  // unsigned 32-bit (sample rate, bit depth)
const T_INT64A = 0x04;  // 64-bit int (duration, ProjectDbMigrationState)
const T_INT64C = 0x05;  // 64-bit int (ProjectFeatures)
const T_DOUBLE = 0x06;  // float64 (timemap XMax/LastValidYOffset; audio StartTime)
const T_STRING = 0x0a;
const T_BYTES = 0x0c;   // length-delimited; len 0xffffffff means null/empty
const T_DATE = 0x10;    // fixed 9-byte timestamp (CreateTime/ModTime); raw hex, round-tripped

function _utf16beDecode(buf) {
  const sw = Buffer.alloc(buf.length);
  for (let j = 0; j + 1 < buf.length; j += 2) { sw[j] = buf[j + 1]; sw[j + 1] = buf[j]; }
  return sw.toString('utf16le');
}
function _utf16beEncode(str) {
  const le = Buffer.from(str, 'utf16le');
  const be = Buffer.alloc(le.length);
  for (let j = 0; j + 1 < le.length; j += 2) { be[j] = le[j + 1]; be[j + 1] = le[j]; }
  return be;
}

/**
 * Parse a keyed-dict blob (hex string or Buffer) into typed entries.
 * Returns { hdr, count, entries: [{ key, type, subType, value }] } where value is:
 *   string  for T_STRING, hex string for T_BYTES, number for T_INT32.
 * Throws if the bytes don't parse cleanly to the end (guards against wrong format).
 */
function decodeKeyedDict(input) {
  const b = Buffer.isBuffer(input) ? input : Buffer.from(input, 'hex');
  if (b.length < 8) throw new Error('keyed-dict too short');
  const hdr = b.readUInt32BE(0);
  const count = b.readUInt32BE(4);
  let o = 8;
  const entries = [];
  while (o < b.length - 4) {
    const kl = b.readUInt32BE(o);
    if (!(kl >= 2 && kl <= 200 && kl % 2 === 0 && o + 4 + kl <= b.length)) break;
    const key = _utf16beDecode(b.slice(o + 4, o + 4 + kl));
    o += 4 + kl;
    const valType = b.readUInt32BE(o); o += 4;
    const subType = b[o]; o += 1;
    let value;
    if (valType === T_STRING) {
      const ln = b.readUInt32BE(o); o += 4;
      value = _utf16beDecode(b.slice(o, o + ln)); o += ln;
    } else if (valType === T_BYTES) {
      const ln = b.readUInt32BE(o); o += 4;
      if (ln === 0xffffffff) { value = null; } // null/empty marker — no payload
      else { value = b.slice(o, o + ln).toString('hex'); o += ln; }
    } else if (valType === T_BOOL) {
      value = b[o] !== 0; o += 1;
    } else if (valType === T_INT32) {
      value = b.readInt32BE(o); o += 4;
    } else if (valType === T_UINT32) {
      value = b.readUInt32BE(o); o += 4;
    } else if (valType === T_INT64A || valType === T_INT64C) {
      value = b.readBigInt64BE(o); o += 8;
    } else if (valType === T_DOUBLE) {
      value = b.readDoubleBE(o); o += 8;
    } else if (valType === T_DATE) {
      value = b.slice(o, o + 9).toString('hex'); o += 9;
    } else {
      throw new Error(`keyed-dict unknown valType 0x${valType.toString(16)} at ${o - 5} (key=${key})`);
    }
    entries.push({ key, type: valType, subType, value });
  }
  return { hdr, count, entries };
}

/** Re-encode a parsed keyed-dict ({ hdr, count, entries }) to a Buffer (round-trips exactly). */
function encodeKeyedDict({ hdr = 1, entries }) {
  const parts = [];
  const head = Buffer.alloc(8);
  head.writeUInt32BE(hdr, 0);
  head.writeUInt32BE(entries.length, 4);
  parts.push(head);
  for (const e of entries) {
    const keyBuf = _utf16beEncode(e.key);
    const kh = Buffer.alloc(4); kh.writeUInt32BE(keyBuf.length, 0);
    parts.push(kh, keyBuf);
    const vh = Buffer.alloc(5);
    vh.writeUInt32BE(e.type, 0); vh.writeUInt8(e.subType || 0, 4);
    parts.push(vh);
    if (e.type === T_STRING) {
      const sb = _utf16beEncode(e.value);
      const lh = Buffer.alloc(4); lh.writeUInt32BE(sb.length, 0);
      parts.push(lh, sb);
    } else if (e.type === T_BYTES) {
      if (e.value === null) {
        const lh = Buffer.alloc(4); lh.writeUInt32BE(0xffffffff, 0);
        parts.push(lh);
      } else {
        const raw = Buffer.from(e.value, 'hex');
        const lh = Buffer.alloc(4); lh.writeUInt32BE(raw.length, 0);
        parts.push(lh, raw);
      }
    } else if (e.type === T_BOOL) {
      parts.push(Buffer.from([e.value ? 1 : 0]));
    } else if (e.type === T_INT32) {
      const ib = Buffer.alloc(4); ib.writeInt32BE(e.value | 0, 0);
      parts.push(ib);
    } else if (e.type === T_UINT32) {
      const ib = Buffer.alloc(4); ib.writeUInt32BE(e.value >>> 0, 0);
      parts.push(ib);
    } else if (e.type === T_INT64A || e.type === T_INT64C) {
      const ib = Buffer.alloc(8); ib.writeBigInt64BE(BigInt(e.value), 0);
      parts.push(ib);
    } else if (e.type === T_DOUBLE) {
      const db = Buffer.alloc(8); db.writeDoubleBE(e.value, 0);
      parts.push(db);
    } else if (e.type === T_DATE) {
      parts.push(Buffer.from(e.value, 'hex'));
    } else {
      throw new Error(`keyed-dict cannot encode valType 0x${e.type.toString(16)}`);
    }
  }
  return Buffer.concat(parts);
}

/** Tolerant reader: [{ key, value }] (value = decoded string/number/hex). Back-compat. */
function readKeyedDict(input) {
  return decodeKeyedDict(input).entries.map((e) => ({ key: e.key, value: e.value }));
}

/** The concrete DbType name (BtGeometry / BtVideoTime / …) declared in the blob. */
function keyedDictType(input) {
  const e = decodeKeyedDict(input).entries.find((x) => x.key === 'DbType');
  return e ? e.value : null;
}

/** Get a single entry's value by key (typed). */
function getKeyedValue(input, key) {
  const e = decodeKeyedDict(input).entries.find((x) => x.key === key);
  return e ? e.value : undefined;
}

/** Set a single entry's value by key, returning a re-encoded hex string. Preserves order/type. */
function setKeyedValue(input, key, value) {
  const parsed = decodeKeyedDict(input);
  const e = parsed.entries.find((x) => x.key === key);
  if (!e) throw new Error(`keyed-dict has no key ${key}`);
  e.value = value;
  return encodeKeyedDict(parsed).toString('hex');
}

/**
 * Read audio config from a TracksBA blob: returns an array of per-track objects
 * { idx, sampleRate, numChannels, codecName, channelLayout, bitDepth, … } by
 * recursively decoding each track's nested BYTES dict.
 */
function readAudioTracks(input) {
  const outer = decodeKeyedDict(input);
  const tracks = [];
  for (const e of outer.entries) {
    if (e.type !== T_BYTES) continue; // skip non-track scalar entries
    let inner;
    try { inner = decodeKeyedDict(Buffer.from(e.value, 'hex')); } catch { continue; }
    const m = Object.fromEntries(inner.entries.map((x) => [x.key, x.value]));
    if (m.DbType !== 'BtAudioTrack') continue;
    tracks.push({
      idx: e.key,
      sampleRate: m.SampleRate,
      numChannels: m.NumChannels,
      codecName: m.CodecName,
      channelLayout: m.ChannelLayout,
      bitDepth: m.BitDepth,
      startTime: m.StartTime,
      duration: m.Duration,
    });
  }
  return tracks;
}

/**
 * Classify any Resolve metadata blob by its leading bytes — useful for the
 * heterogeneous FieldsBlob (which is a keyed-dict for small element state but a
 * zstd-compressed protobuf for large internal/UI/cache state).
 *   'keyed-dict'  : [u32 hdr=1][u32 count] …            (decode with decodeKeyedDict)
 *   'protobuf'    : [u32 hdr=2][u32 len][protobuf]       (decode with decodeEffectFilters)
 *   'zstd'        : protobuf envelope wrapping a zstd frame (magic 28 b5 2f fd) —
 *                   internal state, carried verbatim (Node lacks built-in zstd)
 *   'unknown'     : none of the above
 */
function classifyBlob(input) {
  const b = Buffer.isBuffer(input) ? input : Buffer.from(input, 'hex');
  if (b.length >= 8 && b.indexOf(Buffer.from('28b52ffd', 'hex')) >= 0) return 'zstd';
  const hdr = b.length >= 4 ? b.readUInt32BE(0) : -1;
  if (hdr === 1) return 'keyed-dict';
  if (hdr === 2) return 'protobuf';
  return 'unknown';
}

module.exports = {
  decodeKeyedDict, encodeKeyedDict,
  readKeyedDict, keyedDictType, getKeyedValue, setKeyedValue, readAudioTracks,
  classifyBlob,
  T_BOOL, T_INT32, T_UINT32, T_INT64A, T_INT64C, T_DOUBLE, T_STRING, T_BYTES, T_DATE,
};
