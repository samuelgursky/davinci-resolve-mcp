/**
 * DRX Parser - Extract node structures from DaVinci Resolve DRX files
 *
 * Parses DRX files to extract:
 * - Node definitions (id, position, label, enabled, parameters)
 * - Connections between nodes
 * - Metadata (resolution, timestamps)
 *
 * Uses shared DRX parameter library for consistent parameter handling
 * across the the pipeline platform.
 *
 * @module drx/drx-parser
 */

const fs = require('fs');
const crypto = require('crypto');
// zstd-codec (WASM) with fzstd (pure JS) fallback for Electron asar bundles
let ZstdCodec;
try {
  ZstdCodec = require('zstd-codec').ZstdCodec;
} catch {
  ZstdCodec = null;
}

// Import shared DRX parameter library
const drxParams = require('../drx-parameters');

// Build PARAM_IDS from shared library for backwards compatibility
// This maps parameter IDs to their semantic meaning
const PARAM_IDS = {};
for (const [paramId, info] of Object.entries(drxParams.PARAM_ID_MAP)) {
  PARAM_IDS[paramId] = {
    name: `${info.control}.${info.channel}`,
    control: info.control,
    channel: info.channel,
  };
}

// Re-export corrector types from shared library for backwards compatibility
const CORRECTOR_TYPES = drxParams.CORRECTOR_NAMES;

// ZSTD decoder — prefer Node's built-in zstd (Node 22+, available on Vercel)
// over zstd-codec (WASM) over fzstd (pure JS). See drx-generator.js for the
// reason: zstd-codec produced truncated frames on Vercel's runtime, and we
// want parser + generator to agree on which backend is authoritative.
const _nodeZlib = require('zlib');
const _HAS_NATIVE_ZSTD = typeof _nodeZlib.zstdDecompressSync === 'function';

let zstdCodec = null;

async function getZstdCodec() {
  if (zstdCodec) return zstdCodec;

  if (_HAS_NATIVE_ZSTD) {
    zstdCodec = {
      decompress(data, _size) {
        const buf = data instanceof Buffer
          ? data
          : Buffer.from(data instanceof Uint8Array ? data : new Uint8Array(data));
        return _nodeZlib.zstdDecompressSync(buf);
      },
    };
    return zstdCodec;
  }

  if (ZstdCodec) {
    return new Promise((resolve) => {
      ZstdCodec.run((zstd) => {
        zstdCodec = new zstd.Streaming();
        resolve(zstdCodec);
      });
    });
  }

  const fzstd = require('fzstd');
  zstdCodec = {
    decompress(data, _size) {
      return fzstd.decompress(data instanceof Uint8Array ? data : new Uint8Array(data));
    },
  };
  return zstdCodec;
}

// P4A: LRU cache for parsed DRX content (keyed by SHA-256 hash of input)
// Avoids re-decompression + re-parsing for identical DRX data
const DRX_PARSE_CACHE_MAX = 50;
const drxParseCache = new Map();

function drxCacheGet(key) {
  const entry = drxParseCache.get(key);
  if (!entry) return undefined;
  // Move to end (most recently used)
  drxParseCache.delete(key);
  drxParseCache.set(key, entry);
  return entry;
}

function drxCacheSet(key, value) {
  if (drxParseCache.size >= DRX_PARSE_CACHE_MAX) {
    // Evict oldest (first) entry
    const firstKey = drxParseCache.keys().next().value;
    drxParseCache.delete(firstKey);
  }
  drxParseCache.set(key, value);
}

/**
 * Protobuf parser for DRX body content
 */
class ProtobufParser {
  constructor(buffer) {
    this.buffer = buffer;
    this.pos = 0;
  }

  readVarint() {
    let result = 0;
    let shift = 0;
    while (this.pos < this.buffer.length) {
      const byte = this.buffer[this.pos++];
      result |= (byte & 0x7f) << shift;
      if ((byte & 0x80) === 0) break;
      shift += 7;
      if (shift > 35) throw new Error('Varint too long');
    }
    return result >>> 0;
  }

  readFixed32() {
    const val = this.buffer.readUInt32LE(this.pos);
    this.pos += 4;
    return val;
  }

  readFloat32() {
    const val = this.buffer.readFloatLE(this.pos);
    this.pos += 4;
    return val;
  }

  readFixed64() {
    const low = this.buffer.readUInt32LE(this.pos);
    const high = this.buffer.readUInt32LE(this.pos + 4);
    this.pos += 8;
    return { low, high };
  }

  readBytes(length) {
    const bytes = this.buffer.slice(this.pos, this.pos + length);
    this.pos += length;
    return bytes;
  }

  parse(maxDepth = 10) {
    const result = { _fields: [] };

    while (this.pos < this.buffer.length && maxDepth > 0) {
      const startPos = this.pos;
      let tag;
      try {
        tag = this.readVarint();
      } catch {
        break;
      }

      if (tag === 0) break;

      const fieldNum = tag >>> 3;
      const wireType = tag & 0x7;

      let value;
      let rawValue;

      try {
        switch (wireType) {
          case 0: // Varint
            rawValue = this.readVarint();
            value = rawValue;
            break;
          case 1: // 64-bit
            rawValue = this.readFixed64();
            value = rawValue;
            break;
          case 2: // Length-delimited
            const length = this.readVarint();
            rawValue = this.readBytes(length);
            // Try to parse as nested protobuf
            try {
              const nestedParser = new ProtobufParser(rawValue);
              value = nestedParser.parse(maxDepth - 1);
              if (!value._fields || value._fields.length === 0) {
                value = rawValue;
              }
            } catch {
              value = rawValue;
            }
            break;
          case 5: // 32-bit (fixed32/float)
            rawValue = this.readFixed32();
            const floatBuf = Buffer.alloc(4);
            floatBuf.writeUInt32LE(rawValue);
            value = floatBuf.readFloatLE(0);
            break;
          default:
            break;
        }
      } catch (e) {
        break;
      }

      const field = {
        fieldNum,
        wireType,
        value,
        rawValue,
        pos: startPos,
      };

      result._fields.push(field);

      const key = `F${fieldNum}`;
      if (result[key] !== undefined) {
        if (!Array.isArray(result[key])) {
          result[key] = [result[key]];
        }
        result[key].push(value);
      } else {
        result[key] = value;
      }
    }

    return result;
  }
}

/**
 * Extract string from a field that may have been incorrectly parsed as nested protobuf
 * @param {Object} parentObj - The parent object containing the field
 * @param {number} fieldNum - The field number to extract
 * @returns {string} - The extracted string or empty string
 */
function extractStringField(parentObj, fieldNum) {
  const fieldKey = `F${fieldNum}`;
  const fieldValue = parentObj[fieldKey];

  // If it's already a Buffer, convert to string
  if (Buffer.isBuffer(fieldValue)) {
    return fieldValue.toString('utf8');
  }

  // If it's already a string, use it directly
  if (typeof fieldValue === 'string') {
    return fieldValue;
  }

  // If it's an object (incorrectly parsed as nested protobuf), extract rawValue from _fields
  if (fieldValue && typeof fieldValue === 'object' && parentObj._fields) {
    const field = parentObj._fields.find(f => f.fieldNum === fieldNum);
    if (field && Buffer.isBuffer(field.rawValue)) {
      return field.rawValue.toString('utf8');
    }
  }

  return '';
}

// ColorSlice per-vector grid (Tier-2, RE'd 2026-06-22 — design note §16a). The grid
// param 0x86000606 (COLORSLICE.VECTOR_DATA) carries 7 repeated sub-messages at F24.F1,
// one per color vector, each: F1=enabled(varint), F3=sat(float32, default 1.0),
// F4=hue(float32, stored NEGATED of the UI value). Previously surfaced as an opaque
// NaN scalar; this lifts it into named per-vector params. (The per-vector "Center"
// values live in the sibling GRID_DATA_2 0x86000607 as a packed binary blob — not
// clean protobuf — so they are NOT decoded here; see §16a follow-up.)
const COLORSLICE_VECTOR_DATA_ID = 2248148486; // 0x86000606
const COLORSLICE_GRID2_ID = 2248148487;       // 0x86000607 — per-vector "Center" values
const COLORSLICE_VECTORS = ['red', 'skin', 'yellow', 'green', 'cyan', 'blue', 'magenta'];

// Tier-2: HDR Zone adjustments (0x86000305). F16 → F1[] repeated zone sub-messages, each a
// raw buffer: 0a<len><name>  15<f32 exposure>  1d<f32 cbalY>  25<f32 cbalX>  3d<f32 saturation>.
// Zones differentiate by embedded name string, not param ID (RE'd 2026-06-22 on DRX_CALIB bars).
const HDR_ZONE_ADJUSTMENTS_ID = 2248147717;   // 0x86000305

// Corrector-type-aware naming for the GRADIENT_WINDOW ↔ SAT_VS_SAT id collision (both 0x08F000xx,
// distinguished only by corrector type: gradient = 65554, sat-vs-sat = 3). The flat PARAM_IDS map
// resolves these to satVsSat.*; when the corrector is a gradient window, override to gradientWindow.*.
const GRADIENT_CORRECTOR_TYPE = 65554;
const GRADIENT_NAME_BY_ID = {
  149946369: 'gradientWindow.type',       // 0x08F00001
  149946371: 'gradientWindow.rotation',   // 0x08F00003
  149946373: 'gradientWindow.handle1Pos', // 0x08F00005
  149946374: 'gradientWindow.handle2Pos', // 0x08F00006
  149946377: 'gradientWindow.offsetX',    // 0x08F00009
  149946378: 'gradientWindow.offsetY',    // 0x08F0000A
  149946379: 'gradientWindow.softness',   // 0x08F0000B
};

// ct-aware relabel for the polygon window (corrector type 6). The 0x08D000xx param ids are registered
// in PARAM_ID_MAP under LUM_MIX.PARAM_1–11 (control 'lumMix', correctorType 5) — but live R21 data
// (Session 4, §16a) shows they are the POLYGON-WINDOW geometry, appearing on a ct6 corrector. Rather
// than a sweeping LUM_MIX symbol rename (the LUM_MIX/ct5 pathway is woven through the generator +
// drp-format and the ct5↔ct6 id reuse was NOT measured to be safe), relabel ONLY when the id appears
// under ct6 — exactly the collision-fix pattern used for GRADIENT_NAME_BY_ID. The actual shape geometry
// is still surfaced structurally via node.params.polygonVertices/polygonMatrix regardless of this label.
const POLYGON_CORRECTOR_TYPE = 6;
const POLYGON_NAME_BY_ID = {
  147849218: 'polygonWindow.param1', // 0x08D00002
  147849220: 'polygonWindow.param2', // 0x08D00004
  147849222: 'polygonWindow.param3', // 0x08D00006 (shape vertex ring — see node.params.polygonVertices)
  147849223: 'polygonWindow.param4', // 0x08D00007 (soft-edge vertex ring)
  147849224: 'polygonWindow.param5', // 0x08D00008 (soft-edge vertex ring)
  147849225: 'polygonWindow.param6', // 0x08D00009
  147849226: 'polygonWindow.param7', // 0x08D0000A
  147849227: 'polygonWindow.param8', // 0x08D0000B
  147849228: 'polygonWindow.param9', // 0x08D0000C
  147849232: 'polygonWindow.param10', // 0x08D00010
  147849233: 'polygonWindow.param11', // 0x08D00011
};

// The per-vector "Center" values live in GRID_DATA_2 (0x86000607) as a PACKED float32
// array — structure F12{F1{<packed 7×float32>}} — which is NOT valid nested protobuf
// (the generic parser misreads the packed bytes), so read it from the raw F2 bytes.
// (RE'd 2026-06-22 — design note §16a, C.) Returns the 7 center floats (identity scale).
function decodeColorSliceCenters(f2Bytes) {
  if (!Buffer.isBuffer(f2Bytes) && !(f2Bytes instanceof Uint8Array)) return null;
  const buf = Buffer.from(f2Bytes);
  // Walk length-delimited fields to descend F12 → F1, then read the packed float32s.
  const findField = (start, end, target) => {
    let p = start;
    while (p < end) {
      const tag = buf[p++]; const fnum = tag >>> 3; const wt = tag & 7;
      if (wt === 2) {
        let len = 0, s = 0, b;
        do { b = buf[p++]; len |= (b & 0x7f) << s; s += 7; } while (b & 0x80);
        const cs = p; p += len;
        if (fnum === target) return [cs, cs + len];
      } else if (wt === 0) { while (buf[p] & 0x80) p++; p++; }
      else if (wt === 5) { p += 4; } else if (wt === 1) { p += 8; } else return null;
    }
    return null;
  };
  const f12 = findField(0, buf.length, 12); if (!f12) return null;
  const f1 = findField(f12[0], f12[1], 1); if (!f1) return null;
  const [s, e] = f1; const n = Math.floor((e - s) / 4); const out = [];
  for (let i = 0; i < n; i++) out.push(buf.readFloatLE(s + i * 4));
  return out;
}

// The grid sits ~11 levels deep but the generic parser stops at maxDepth=10, so the
// per-vector sub-messages arrive as raw Buffers — re-parse them on demand here.
function ensureParsed(x) {
  if (Buffer.isBuffer(x) || x instanceof Uint8Array) {
    try {
      const p = new ProtobufParser(Buffer.from(x)).parse(40);
      return p && p._fields && p._fields.length ? p : null;
    } catch { return null; }
  }
  return x && typeof x === 'object' ? x : null;
}

function decodeColorSliceGrid(gridMsg) {
  const msg = ensureParsed(gridMsg);
  if (!msg) return null;
  const f24 = ensureParsed(msg.F24);
  if (!f24 || f24.F1 === undefined) return null;
  const vecs = Array.isArray(f24.F1) ? f24.F1 : [f24.F1];
  return vecs.map((raw, i) => {
    const v = ensureParsed(raw) || {};
    return {
      vector: COLORSLICE_VECTORS[i] || `vec${i}`,
      enabled: v.F1 !== undefined ? v.F1 === 1 : true,
      sat: typeof v.F3 === 'number' ? v.F3 : 1,   // F3 = saturation (default 1.0)
      hue: typeof v.F4 === 'number' ? -v.F4 : 0,  // F4 = hue, stored negated → report UI value
    };
  });
}

// Byte-walk one HDR zone sub-message buffer → {name, exposure, saturation, colorBalanceX/Y}.
// Fields: F1(0x0a)=name str, F2(0x15)=exposure f32, F3(0x1d)=cbalY f32, F4(0x25)=cbalX f32,
// F7(0x3d)=saturation f32. Default exposure 0, saturation 1.
function parseHdrZone(raw) {
  if (!Buffer.isBuffer(raw) && !(raw instanceof Uint8Array)) return null;
  const buf = Buffer.from(raw);
  const z = { name: null, exposure: 0, saturation: 1, colorBalanceX: 0, colorBalanceY: 0 };
  let p = 0;
  while (p < buf.length) {
    const tag = buf[p++]; const fnum = tag >>> 3; const wt = tag & 7;
    if (wt === 2) {
      let len = 0, s = 0, b; do { b = buf[p++]; len |= (b & 0x7f) << s; s += 7; } while (b & 0x80);
      if (fnum === 1) z.name = buf.toString('utf8', p, p + len);
      p += len;
    } else if (wt === 5) {
      const f = buf.readFloatLE(p); p += 4;
      if (fnum === 2) z.exposure = f;
      else if (fnum === 3) z.colorBalanceY = f;
      else if (fnum === 4) z.colorBalanceX = f;
      else if (fnum === 7) z.saturation = f;
    } else if (wt === 0) { while (buf[p] & 0x80) p++; p++; }
    else if (wt === 1) { p += 8; }
    else break;
  }
  return z.name ? z : null;
}

// Tier-2: 3D-qualifier selection volume (0x0830002A) — byte-level RE'd 2026-07-02 off the
// qualifier-3d fixture (key stroke across the bars, 8 samples). Layout: value envelope
// { F5: <packed buffer> } where the buffer = 9 × uint64 BIG-endian header (fields 0-7
// semantics unconfirmed — observed [2,1,1,0x88,7,0,0x40,0xBA]; field 8 = SAMPLE COUNT)
// followed by count × 3 float32 LITTLE-endian samples (x, y, radius) — the keyer's
// sampled chroma-plane point cloud (stroke path; radius observed constant 0.015).
const QUALIFIER_3D_VOLUME_ID = 0x0830002a;  // 137363498
function decodeQualifier3dVolume(env) {
  const m = ensureParsed(env);
  if (!m || !Buffer.isBuffer(m.F5)) return null;
  const buf = m.F5;
  if (buf.length < 72) return null;
  const header = [];
  for (let i = 0; i < 9; i++) header.push(Number(buf.readBigUInt64BE(i * 8)));
  const count = header[8];
  const samples = [];
  for (let i = 0; i < count && 72 + (i + 1) * 12 <= buf.length; i++) {
    const off = 72 + i * 12;
    samples.push({ x: buf.readFloatLE(off), y: buf.readFloatLE(off + 4), radius: buf.readFloatLE(off + 8) });
  }
  return samples.length ? { header, count, samples } : null;
}

// Tier-2: decode the HDR ZONE_ADJUSTMENTS blob (0x86000305) into per-zone named params.
function decodeHdrZones(adjMsg) {
  const msg = ensureParsed(adjMsg);
  if (!msg) return null;
  const f16 = ensureParsed(msg.F16);
  if (!f16 || f16.F1 === undefined) return null;
  const zones = Array.isArray(f16.F1) ? f16.F1 : [f16.F1];
  return zones.map((raw) => parseHdrZone(raw)).filter(Boolean);
}

// Node "Input Sizing" (RE'd 2026-06-22, harness §16a). Stored outside the F9 corrector list in a
// transform structure whose param entries have a fixed signature in the decompressed body:
//   1a 0d  08 <kx> 80 c0 <kg> 01  12 05 0d <f32>
// where <kg>=group (0x81=A pan/tilt/zoom/rotate/width/height, 0x85=B pitch/yaw) and <kx>=param index.
// Pan/Tilt are normalized (UI px / frame dim); Zoom/Width/Height = direct mult; Rotate = degrees.
const SIZING_MAP = {
  '81:81': { channel: 'width',  id: 0x10310001 },
  '82:81': { channel: 'height', id: 0x10310002 },
  '83:81': { channel: 'zoom',   id: 0x10310003 },
  '84:81': { channel: 'rotate', id: 0x10310004 },
  '85:81': { channel: 'pan',    id: 0x10310005, normalized: 'width' },
  '86:81': { channel: 'tilt',   id: 0x10310006, normalized: 'height' },
  '81:85': { channel: 'pitch',  id: 0x10B10001 },
  '82:85': { channel: 'yaw',    id: 0x10B10002 },
};
function decodeNodeSizing(buf) {
  if (!Buffer.isBuffer(buf)) return null;
  const out = [];
  for (let i = 0; i + 15 <= buf.length; i++) {
    // 1a 0d 08 <kx> 80 c0 <kg> 01 12 05 0d <f32>
    if (buf[i] !== 0x1a || buf[i + 1] !== 0x0d || buf[i + 2] !== 0x08) continue;
    if (buf[i + 4] !== 0x80 || buf[i + 5] !== 0xc0 || buf[i + 7] !== 0x01) continue;
    if (buf[i + 8] !== 0x12 || buf[i + 9] !== 0x05 || buf[i + 10] !== 0x0d) continue;
    const kx = buf[i + 3], kg = buf[i + 6];
    const info = SIZING_MAP[`${kx.toString(16)}:${kg.toString(16)}`];
    if (!info) continue;
    out.push({ ...info, value: buf.readFloatLE(i + 11) });
  }
  return out.length ? out : null;
}

// Curve spline point: a sub-message `0d<f32 x> 15<f32 y>` — F1(fixed32)=x, F2(fixed32)=y.
// COORDINATE SPACE DIFFERS BY CURVE TYPE (RE'd 2026-06-22):
//  - Custom Y/R/G/B (0x86000506–509): ~0–1024 (10-bit), tangent handles beyond [0,1024].
//  - HSL curves (0x86000400–405): NORMALIZED — x∈[-1,1] (hue axis, periodic → wrap handles beyond ±1),
//    y∈[0,1] with 0.5=neutral. (Hue-vs-Hue: y = 0.5 − HueRotate°/360.)
// The decoder is space-agnostic — it just reads the raw f32 x/y; the consumer interprets per curve.
function parseSplinePoint(raw) {
  if (!Buffer.isBuffer(raw) && !(raw instanceof Uint8Array)) return null;
  const buf = Buffer.from(raw);
  let p = 0; let x, y;
  while (p < buf.length) {
    const tag = buf[p++]; const fnum = tag >>> 3; const wt = tag & 7;
    if (wt === 5) { const f = buf.readFloatLE(p); p += 4; if (fnum === 1) x = f; else if (fnum === 2) y = f; }
    else if (wt === 2) { let len = 0, s = 0, b; do { b = buf[p++]; len |= (b & 0x7f) << s; s += 7; } while (b & 0x80); p += len; }
    else if (wt === 0) { while (buf[p] & 0x80) p++; p++; }
    else if (wt === 1) { p += 8; } else break;
  }
  return (x !== undefined || y !== undefined) ? { x: x ?? 0, y: y ?? 0 } : null;
}
// Spline data params (custom curves 0x86000506–509, HSL curves 0x86000400–405) store points in F8.F1[].
const SPLINE_POINT_IDS = new Set([
  0x86000506, 0x86000507, 0x86000508, 0x86000509,            // custom Y/R/G/B
  0x86000400, 0x86000401, 0x86000402, 0x86000403, 0x86000404, 0x86000405, // HSL curves
]);
function decodeSplinePoints(splineMsg) {
  const msg = ensureParsed(splineMsg);
  if (!msg) return null;
  const f8 = ensureParsed(msg.F8);
  if (!f8 || f8.F1 === undefined) return null;
  const pts = Array.isArray(f8.F1) ? f8.F1 : [f8.F1];
  return pts.map(parseSplinePoint).filter(Boolean);
}

// Structural containers found in the completeness sweep (RE'd 2026-06-22 off the
// gradient-window fixture, which itself is a live BARS capture):
//   0x0830006f (qualifier corrector, ct2): value envelope = { F2: <varint> } — an
//     internal qualifier mode flag (registry MODE_FLAG; observed 4). Lift the varint.
//   0x88f0000d (gradient corrector, ct65554): value envelope = { F10: { F1..F9 } } — a
//     row-major 3×3 matrix (identity by default). Lift the 9 cells into an array.
const QUALIFIER_MODE_FLAG_ID = 137363567;  // 0x0830006f
const GRADIENT_MATRIX_ID = 2297430029;     // 0x88f0000d
// The gradient window (0x88f0000d), polygon shape (0x88d00014) and LINEAR-window softness mask
// (0x8870001e, ct3) all carry the same structural F10 3×3 matrix container (identity default).
// RE'd 2026-06-22 (gradient + polygon + linear-softness fixtures).
const LINEAR_SOFT_MATRIX_ID = 2289041438;  // 0x8870001e
const STRUCT_MATRIX_NAMES = {
  [GRADIENT_MATRIX_ID]: { name: 'gradientWindow.matrix', key: 'gradientMatrix' },
  2295332884: { name: 'polygonShape.matrix', key: 'polygonMatrix' },           // 0x88d00014
  [LINEAR_SOFT_MATRIX_ID]: { name: 'window.softMatrix', key: 'softMatrix' },   // 0x8870001e (ct3)
};
const STRUCT_MATRIX_IDS = new Set(Object.keys(STRUCT_MATRIX_NAMES).map(Number));
function decodeStructMatrix(env) {
  const m = ensureParsed(env);
  if (!m) return null;
  const f10 = ensureParsed(m.F10);
  if (!f10) return null;
  const out = [];
  for (let i = 1; i <= 9; i++) {
    const v = f10[`F${i}`];
    out.push(typeof v === 'number' ? v : 0);
  }
  return out;
}

// Polygon shape vertices — RE'd 2026-06-22 on DRX_CALIB (drew a 4-vertex polygon window). The shape
// lives under CORRECTOR TYPE 6 (NOT the registry's claimed 0x08B0/ct5; that POLYGON_WINDOW block is
// UNVALIDATED). Vertices are F9.F1[] point sub-messages — the SAME `0d<f32 x>15<f32 y>` codec as curve
// splines but under F9 (splines use F8) — in FRAME-PIXELS from center. IDs 0x08D00006/07/08 each carry
// the vertex ring (shape + inner/outer soft edges). These IDs are currently mislabeled "lumMix.*" in
// the registry (a deeper rename is deferred — see ledger). The vertices are surfaced additively here.
const POLYGON_VERTEX_IDS = new Set([0x08d00006, 0x08d00007, 0x08d00008]);
const LINEAR_SOFT_BBOX_ID = 141557780;  // 0x08700014 — linear-window softness-mask 4-corner ring (ct3)
function decodePolygonVertices(env) {
  const m = ensureParsed(env);
  if (!m) return null;
  const f9 = ensureParsed(m.F9);
  if (!f9 || f9.F1 === undefined) return null;
  const pts = Array.isArray(f9.F1) ? f9.F1 : [f9.F1];
  return pts.map(parseSplinePoint).filter(Boolean);
}

// Color Warper (chroma warp) pin list — RE'd LIVE 2026-06-22 on DRX_CALIB (Resolve 21, harness §16a).
// The registry's old mesh-vertex model (0x86000121 triplets) is WRONG for R21; the real shape is a pin
// list at 0x86000138: value envelope = { F27: { F1: [ <pin>, … ] } }. Each pin sub-message:
//   F1=id, F2/F3=source chroma XY, F4/F5=dest chroma XY, F6=chromaRange, F7=exposure (skip-if-0),
//   F8=tonalLow, F9=tonalHigh, F10=tonalPivot. Floats are identity-scale vs the UI Pin controls.
const COLOR_WARPER_PINS_ID = 0x86000138;  // 2248147256
function parseColorWarperPin(raw) {
  const m = ensureParsed(raw);
  if (!m) return null;
  const num = (v) => (typeof v === 'number' ? v : undefined);
  const pin = {
    id: num(m.F1),
    srcX: num(m.F2), srcY: num(m.F3),
    dstX: num(m.F4), dstY: num(m.F5),
    chromaRange: num(m.F6),
    exposure: num(m.F7) ?? 0,
    tonalLow: num(m.F8), tonalHigh: num(m.F9), tonalPivot: num(m.F10),
  };
  // A real pin always carries the chroma source/dest coords.
  return (pin.srcX !== undefined && pin.dstX !== undefined) ? pin : null;
}
function decodeColorWarperPins(env) {
  const m = ensureParsed(env);
  if (!m) return null;
  const f27 = ensureParsed(m.F27);
  if (!f27 || f27.F1 === undefined) return null;
  const pins = Array.isArray(f27.F1) ? f27.F1 : [f27.F1];
  return pins.map(parseColorWarperPin).filter(Boolean);
}

// Keyframe tracks — RE'd + validated LIVE 2026-06-22 (§16a OPEN ITEM 2, 3-keyframe sweep). When a corrector
// is keyframed its F6 is a REPEATED field: one block per keyframe. Each block = { F1: timeUnits, F2: {F3:[params]} }
// where timeUnits = frame × 2 (half-frame/field units; F1 is ABSENT on block 0 = frame 0). Validated:
// frames 0/60/119 → F1 0/120/238, matte param 0xc30001d → 0.40/1.10/1.70. Builds paramId → [{frame,value}].
function buildKeyframeTracks(f6Blocks) {
  const tracks = {};
  for (const raw of f6Blocks) {
    const b = ensureParsed(raw);
    if (!b) continue;
    const frame = typeof b.F1 === 'number' ? b.F1 / 2 : 0;
    const cont = ensureParsed(b.F2);
    if (!cont || cont.F3 === undefined) continue;
    const params = Array.isArray(cont.F3) ? cont.F3 : [cont.F3];
    for (const p of params) {
      const pp = ensureParsed(p);
      if (!pp || pp.F1 === undefined) continue;
      let v = pp.F2;
      if (v && typeof v === 'object' && v.F1 !== undefined) v = v.F1;
      if (typeof v !== 'number') continue;
      (tracks[pp.F1] || (tracks[pp.F1] = [])).push({ frame, value: v });
    }
  }
  for (const k of Object.keys(tracks)) tracks[k].sort((a, b) => a.frame - b.frame);
  return tracks;
}

/**
 * Extract node data from parsed protobuf
 * @param {Buffer} [rawBody] decompressed body — enables the node-Sizing body-scan (single-node graphs).
 */
function extractNodes(parsed, rawBody) {
  const nodes = [];

  if (!parsed.F1 || !parsed.F1.F7) return nodes;

  const nodeFields = Array.isArray(parsed.F1.F7) ? parsed.F1.F7 : [parsed.F1.F7];

  for (const nodeData of nodeFields) {
    if (!nodeData._fields) continue;

    const node = {
      id: nodeData.F1,
      index: nodeData.F2,
      xPos: nodeData.F4,
      yPos: nodeData.F5,
      label: extractStringField(nodeData, 6),
      // Node color — RE'd LIVE 2026-06-22 (node-convention/provenance spec). Stored in node field F15 as a
      // plain string "ClipColor<Name>" (e.g. ClipColorBlue); absent = no color. Surface the bare color name.
      color: (() => { const s = extractStringField(nodeData, 15); return s ? s.replace(/^ClipColor/, '') : null; })(),
      enabled: nodeData.F7 === 1,
      keyframed: false,  // set true when a corrector carries a repeated F6 (keyframe relocation, §16a OPEN ITEM 2)
      correctors: [],
      // Structured parameters for easy merging
      params: {
        lift: { r: 0, g: 0, b: 0, master: 0 },
        gamma: { r: 0, g: 0, b: 0, master: 0 },
        gain: { r: 1, g: 1, b: 1, master: 1 },
        offset: { r: 0, g: 0, b: 0 },
        saturation: 50,   // Resolve Primaries: 0-100, unity=50
        contrast: 1.0,
        pivot: 0.435,
      },
    };

    // OFX/ResolveFX tool list (node field F10) — plugin params are SELF-DESCRIBING on
    // the wire (name string + float64/string value; enums are label strings), so no
    // per-plugin registry is needed to read them. Verified against real project grades
    // 2026-07-03 (filmgrain/CST/acestransform; 5,977 instances decoded by name). Values
    // are surfaced RAW — float scaling vs the UI is NOT panel-confirmed yet, so treat
    // per valueFidelity until a capture-sweep lands.
    if (nodeData.F10) {
      try {
        // The generic parser recursively converts nested messages to {_fields} objects;
        // extract-ofx-params wants the raw entry BYTES — recover them from rawValue.
        let toolList = nodeData.F10;
        if (toolList && toolList._fields) {
          toolList = toolList._fields
            .filter((f) => f.fieldNum === 1 && f.wireType === 2)
            .map((f) => (Buffer.isBuffer(f.value) ? f.value : f.rawValue))
            .filter(Buffer.isBuffer);
        }
        const ofxTools = require('./extract-ofx-params').extractOFXTools(toolList);
        if (ofxTools.length) node.ofxTools = ofxTools;
      } catch { /* malformed tool list — leave node.ofxTools unset */ }
    }

    // Extract correctors from Field 9
    if (nodeData.F9 && nodeData.F9._fields) {
      const correctorFields = nodeData.F9.F1 ? (Array.isArray(nodeData.F9.F1) ? nodeData.F9.F1 : [nodeData.F9.F1]) : [];

      for (const corrector of correctorFields) {
        if (!corrector._fields) continue;

        const correctorType = corrector.F1;
        const correctorInfo = {
          type: correctorType,
          typeName: CORRECTOR_TYPES[correctorType] || `Type${correctorType}`,
          enabled: corrector.F3 === 1,
          parameters: [],
        };

        // Keyframed grades relocate each corrector's values: F6 becomes a REPEATED field (a static base
        // block + a keyframe-track block, the latter carrying an extra F1 marker). RE'd live 2026-06-22
        // (§16a OPEN ITEM 2). Without this the static path (corrector.F6.F2) was undefined → 0 params for
        // a keyframed grade. Read params from the base block (the one carrying F2.F3) and flag the node.
        let f6 = corrector.F6;
        if (Array.isArray(f6)) {
          node.keyframed = true;
          // Full keyframe-track decode: paramId → [{frame, value}] across all keyframe blocks.
          const tracks = buildKeyframeTracks(f6);
          const named = {};
          for (const [pid, pts] of Object.entries(tracks)) {
            if (pts.length < 2) continue; // a single point isn't an animation
            const info = PARAM_IDS[pid];
            named[info ? info.name : `param_${pid}`] = pts;
          }
          if (Object.keys(named).length) {
            (node.keyframes || (node.keyframes = [])).push({ correctorType, tracks: named });
          }
          // Static-snapshot base block (the first block / frame 0) for the normal param path.
          f6 = f6.find((b) => b && b.F2 && b.F2.F3 !== undefined) || f6[0];
        }

        // Extract parameters from Field 6 -> Field 2 -> Field 3[]
        if (f6 && f6.F2) {
          const paramContainer = f6.F2;
          const paramFields = paramContainer.F3 ? (Array.isArray(paramContainer.F3) ? paramContainer.F3 : [paramContainer.F3]) : [];

          for (const param of paramFields) {
            if (!param._fields) continue;

            const paramId = param.F1;
            let paramValue = param.F2;

            // Tier-2: ColorSlice per-vector grid (0x86000606) — decode the F24
            // sub-messages into named per-vector params instead of an opaque NaN.
            if (paramId === COLORSLICE_VECTOR_DATA_ID) {
              const grid = decodeColorSliceGrid(param.F2);
              if (grid && grid.length) {
                node.params.colorSlice = grid;
                for (const vec of grid) {
                  correctorInfo.parameters.push({ id: paramId, value: vec.enabled ? 1 : 0, name: `colorSlice.${vec.vector}.enabled`, vector: vec.vector, field: 'enabled' });
                  correctorInfo.parameters.push({ id: paramId, value: vec.sat, name: `colorSlice.${vec.vector}.sat`, vector: vec.vector, field: 'sat' });
                  correctorInfo.parameters.push({ id: paramId, value: vec.hue, name: `colorSlice.${vec.vector}.hue`, vector: vec.vector, field: 'hue' });
                }
                continue;
              }
            }

            // Tier-2: ColorSlice per-vector "Center" values — a packed float32 array
            // in GRID_DATA_2 (0x86000607), read from the raw F2 bytes (see §16a, C).
            if (paramId === COLORSLICE_GRID2_ID) {
              const f2 = param._fields && param._fields.find((f) => f.fieldNum === 2);
              const centers = f2 ? decodeColorSliceCenters(f2.rawValue) : null;
              if (centers && centers.length) {
                if (!Array.isArray(node.params.colorSlice)) {
                  node.params.colorSlice = centers.map((_, i) => ({ vector: COLORSLICE_VECTORS[i] || `vec${i}` }));
                }
                centers.forEach((c, i) => {
                  if (node.params.colorSlice[i]) node.params.colorSlice[i].center = c;
                  correctorInfo.parameters.push({ id: paramId, value: c, name: `colorSlice.${COLORSLICE_VECTORS[i] || 'vec' + i}.center`, vector: COLORSLICE_VECTORS[i], field: 'center' });
                });
                continue;
              }
            }

            // Tier-2: HDR zone adjustments (0x86000305) — lift the nested per-zone
            // exposure/saturation/color-balance out of the opaque blob into named params.
            if (paramId === HDR_ZONE_ADJUSTMENTS_ID) {
              const zones = decodeHdrZones(param.F2);
              if (zones && zones.length) {
                node.params.hdrZones = zones;
                for (const z of zones) {
                  const key = z.name.toLowerCase();
                  correctorInfo.parameters.push({ id: paramId, value: z.exposure, name: `hdrZone.${key}.exposure`, zone: z.name, field: 'exposure' });
                  correctorInfo.parameters.push({ id: paramId, value: z.saturation, name: `hdrZone.${key}.saturation`, zone: z.name, field: 'saturation' });
                  if (z.colorBalanceX) correctorInfo.parameters.push({ id: paramId, value: z.colorBalanceX, name: `hdrZone.${key}.colorBalanceX`, zone: z.name, field: 'colorBalanceX' });
                  if (z.colorBalanceY) correctorInfo.parameters.push({ id: paramId, value: z.colorBalanceY, name: `hdrZone.${key}.colorBalanceY`, zone: z.name, field: 'colorBalanceY' });
                }
                continue;
              }
            }

            // Tier-2: 3D-qualifier selection volume (0x0830002A) — lift the packed sample
            // point cloud (see decodeQualifier3dVolume) ADDITIVELY onto node.params.
            if (paramId === QUALIFIER_3D_VOLUME_ID && !node.params.qualifier3d) {
              const vol = decodeQualifier3dVolume(param.F2);
              if (vol) {
                node.params.qualifier3d = vol;
                correctorInfo.parameters.push({ id: paramId, value: vol.count, name: 'qualifier.volume3dSampleCount' });
              }
            }

            // Blob RE: curve spline points (custom + HSL curves) — lift F8.F1[] point
            // sub-messages into {x,y} arrays (coords in ~0–1024 space) on node.params.curvePoints.
            // ADDITIVE: don't touch the param's own value (the extractCustomCurves/HSL secondary
            // decoders still read param.value) — just expose the decoded points alongside.
            if (SPLINE_POINT_IDS.has(paramId)) {
              const pts = decodeSplinePoints(param.F2);
              if (pts && pts.length) {
                const info = PARAM_IDS[paramId];
                const key = info ? info.name : `spline_${paramId}`;
                if (!node.params.curvePoints) node.params.curvePoints = {};
                node.params.curvePoints[key] = pts;
              }
            }

            // Tier-2: Color Warper chroma-warp pin list (0x86000138) — lift F2.F27.F1[] pins into
            // named colorWarper.pin<N>.<field> params + node.params.colorWarper (RE'd live, §16a).
            if (paramId === COLOR_WARPER_PINS_ID) {
              const pins = decodeColorWarperPins(param.F2);
              if (pins && pins.length) {
                node.params.colorWarper = pins;
                pins.forEach((pin, pi) => {
                  for (const [field, val] of Object.entries(pin)) {
                    if (val !== undefined) {
                      correctorInfo.parameters.push({ id: paramId, value: val, name: `colorWarper.pin${pi}.${field}`, pin: pi, field });
                    }
                  }
                });
                continue;
              }
            }

            // Structural container: 3×3 matrix (gradient window 0x88f0000d ct65554, polygon shape
            // 0x88d00014 ct6) — lift F10's 9 cells into an array instead of an opaque unknown_ object.
            if (STRUCT_MATRIX_IDS.has(paramId)) {
              const mtx = decodeStructMatrix(param.F2);
              if (mtx) {
                const meta = STRUCT_MATRIX_NAMES[paramId];
                node.params[meta.key] = mtx;
                correctorInfo.parameters.push({ id: paramId, value: mtx, name: meta.name });
                continue;
              }
            }
            // Polygon shape vertices (additive): lift the F9.F1[] point ring into node.params.polygonVertices.
            if (POLYGON_VERTEX_IDS.has(paramId) && !node.params.polygonVertices) {
              const verts = decodePolygonVertices(param.F2);
              if (verts && verts.length) node.params.polygonVertices = verts;
            }
            // Linear-window softness mask bbox (0x08700014, ct3): same F9.F1[] point ring (the 4 corners).
            if (paramId === LINEAR_SOFT_BBOX_ID && !node.params.softVertices) {
              const verts = decodePolygonVertices(param.F2);
              if (verts && verts.length) node.params.softVertices = verts;
            }
            // Structural container: qualifier internal mode flag (0x0830006f, ct2) —
            // lift the varint out of the { F2 } envelope.
            if (paramId === QUALIFIER_MODE_FLAG_ID && correctorType === 2) {
              const mf = param.F2 && typeof param.F2.F2 === 'number' ? param.F2.F2 : null;
              correctorInfo.parameters.push({ id: paramId, value: mf, name: 'qualifier.modeFlag' });
              continue;
            }

            if (paramValue && paramValue.F1 !== undefined) {
              paramValue = paramValue.F1;
            }

            const paramInfo = PARAM_IDS[paramId];
            // ct-aware override: gradient-window params collide with sat-vs-sat, and polygon-window
            // geometry (ct6) is mis-registered under LUM_MIX (ct5) — relabel by corrector type.
            const ctName =
              (correctorType === GRADIENT_CORRECTOR_TYPE && GRADIENT_NAME_BY_ID[paramId]) ||
              (correctorType === POLYGON_CORRECTOR_TYPE && POLYGON_NAME_BY_ID[paramId]) ||
              null;
            correctorInfo.parameters.push({
              id: paramId,
              value: paramValue,
              name: ctName || (paramInfo ? paramInfo.name : `unknown_${paramId}`),
            });

            // Map to structured params
            if (paramInfo) {
              if (paramInfo.control === 'lift' && paramInfo.channel) {
                node.params.lift[paramInfo.channel] = paramValue;
              } else if (paramInfo.control === 'gamma' && paramInfo.channel) {
                node.params.gamma[paramInfo.channel] = paramValue;
              } else if (paramInfo.control === 'gain' && paramInfo.channel) {
                node.params.gain[paramInfo.channel] = paramValue;
              } else if (paramInfo.control === 'offset' && paramInfo.channel) {
                node.params.offset[paramInfo.channel] = paramValue;
              } else if (paramInfo.control === 'saturation') {
                node.params.saturation = paramValue;
              } else if (paramInfo.control === 'contrast') {
                node.params.contrast = paramValue;
              } else if (paramInfo.control === 'pivot') {
                node.params.pivot = paramValue;
              }
            }
          }
        }

        node.correctors.push(correctorInfo);
      }
    }

    nodes.push(node);
  }

  // Node "Input Sizing" lives outside the corrector list; scan the raw body for its signature.
  // The scan can't attribute entries to a specific node, so only attach for single-node graphs.
  if (rawBody && nodes.length === 1) {
    const sizing = decodeNodeSizing(rawBody);
    if (sizing && sizing.length) {
      const node = nodes[0];
      node.params.sizing = {};
      for (const s of sizing) {
        node.params.sizing[s.channel] = s.value;
        node.correctors[0]?.parameters.push({ id: s.id, value: s.value, name: `sizing.${s.channel}`, channel: s.channel, normalized: s.normalized || null });
      }
    }
  }

  return nodes;
}

/**
 * Extract connections from parsed protobuf
 */
function extractConnections(parsed) {
  const connections = [];

  if (!parsed.F1 || !parsed.F1.F8) return connections;

  const connFields = Array.isArray(parsed.F1.F8) ? parsed.F1.F8 : [parsed.F1.F8];

  for (const conn of connFields) {
    if (!conn._fields) continue;

    connections.push({
      from: conn.F1,
      to: conn.F3,
      sourcePort: conn.F5,
      targetPort: conn.F6,
      index: conn.F7,
    });
  }

  return connections;
}

/**
 * Extract metadata from parsed protobuf
 */
function extractMetadata(parsed) {
  const metadata = {
    version: null,
    width: null,
    height: null,
    timestamp: null,
  };

  if (parsed.F1) {
    metadata.version = parsed.F1.F1;
    if (parsed.F1.F3) {
      metadata.width = parsed.F1.F3.F1;
      metadata.height = parsed.F1.F3.F2;
    }
    metadata.timestamp = parsed.F1.F12;
  }

  return metadata;
}

/**
 * Parse a DRX file and extract its structure
 *
 * @param {string} filePath - Path to the DRX file
 * @returns {Promise<Object>} - Parsed DRX structure with nodes, connections, metadata
 */
async function parseDRX(filePath) {
  const xml = fs.readFileSync(filePath, 'utf-8');
  return parseDRXContent(xml);
}

/**
 * Parse DRX XML content (without reading from file)
 *
 * @param {string} xml - DRX XML content
 * @returns {Promise<Object>} - Parsed DRX structure
 */
async function parseDRXContent(xml) {
  // P4A: Check LRU cache by SHA-256 of input XML
  const cacheKey = crypto.createHash('sha256').update(xml).digest('hex');
  const cached = drxCacheGet(cacheKey);
  if (cached) {
    return cached;
  }

  // Extract XML metadata
  const labelMatch = xml.match(/<Label>([^<]*)<\/Label>/);
  const widthMatch = xml.match(/<Width>(\d+)<\/Width>/);
  const heightMatch = xml.match(/<Height>(\d+)<\/Height>/);
  const srcHintMatch = xml.match(/<SrcHint>([^<]*)<\/SrcHint>/);
  const recTCMatch = xml.match(/<RecTC>([^<]*)<\/RecTC>/);
  const srcTCMatch = xml.match(/<SrcTC>([^<]*)<\/SrcTC>/);

  // Extract pTrackVer section for preservation during merge
  const pTrackVerMatch = xml.match(/<pTrackVer>([\s\S]*?)<\/pTrackVer>/);
  const pTrackVerXml = pTrackVerMatch ? pTrackVerMatch[0] : null;

  // Extract body
  const bodyMatch = xml.match(/<Body>([^<]+)<\/Body>/);
  if (!bodyMatch) {
    throw new Error('No Body found in DRX content');
  }

  const hexBody = bodyMatch[1];
  const buf = Buffer.from(hexBody, 'hex');

  // Verify magic byte. 0x81 = zstd-compressed body; 0x80 = STORED (uncompressed
  // protobuf follows directly) — found in real project exports 2026-07-03 (~10% of
  // grades in large projects; presumably Resolve skips compression for small bodies).
  if (buf[0] !== 0x81 && buf[0] !== 0x80) {
    throw new Error(`Invalid DRX magic byte: 0x${buf[0].toString(16)}`);
  }

  // Decompress (or use the stored bytes directly for 0x80)
  const decompressed = buf[0] === 0x80
    ? buf.slice(1)
    : Buffer.from((await getZstdCodec()).decompress(buf.slice(1)));

  // Parse protobuf
  const parser = new ProtobufParser(decompressed);
  const parsed = parser.parse();

  // Extract structure
  const nodes = extractNodes(parsed, decompressed);
  const connections = extractConnections(parsed);
  const metadata = extractMetadata(parsed);

  const result = {
    // XML metadata
    label: labelMatch ? labelMatch[1] : '',
    width: widthMatch ? parseInt(widthMatch[1], 10) : metadata.width || 1920,
    height: heightMatch ? parseInt(heightMatch[1], 10) : metadata.height || 1080,
    sourceTimeline: srcHintMatch ? srcHintMatch[1] : 'Timeline 1',
    recordTC: recTCMatch ? recTCMatch[1] : '01:00:00:00',
    sourceTC: srcTCMatch ? srcTCMatch[1] : '00:00:00:00',

    // Preserved XML sections for merge
    pTrackVerXml,

    // Protobuf data
    nodes,
    connections,
    metadata,

    // Raw parsed data (for debugging)
    _raw: parsed,
  };

  // P4A: Store in LRU cache
  drxCacheSet(cacheKey, result);
  return result;
}

/**
 * Parse DRX from a hex-encoded body string (for direct API use)
 *
 * @param {string} hexBody - Hex-encoded DRX body
 * @returns {Promise<Object>} - Parsed nodes and connections
 */
async function parseDRXBody(hexBody) {
  const buf = Buffer.from(hexBody, 'hex');

  // 0x81 = zstd-compressed; 0x80 = STORED/uncompressed (see parseDRXContent).
  if (buf[0] !== 0x81 && buf[0] !== 0x80) {
    throw new Error(`Invalid DRX magic byte: 0x${buf[0].toString(16)}`);
  }

  const decompressed = buf[0] === 0x80
    ? buf.slice(1)
    : Buffer.from((await getZstdCodec()).decompress(buf.slice(1)));

  const parser = new ProtobufParser(decompressed);
  const parsed = parser.parse();

  return {
    nodes: extractNodes(parsed, decompressed),
    connections: extractConnections(parsed),
    metadata: extractMetadata(parsed),
  };
}

/**
 * Default parameter values for comparison
 * Uses shared library for consistency
 */
const DEFAULT_PARAMS = {
  lift: drxParams.PARAMETER_RANGES.lift
    ? { r: drxParams.getDefault('lift', 'r'), g: drxParams.getDefault('lift', 'g'), b: drxParams.getDefault('lift', 'b'), master: drxParams.getDefault('lift', 'master') }
    : { r: 0, g: 0, b: 0, master: 0 },
  gamma: drxParams.PARAMETER_RANGES.gamma
    ? { r: drxParams.getDefault('gamma', 'r'), g: drxParams.getDefault('gamma', 'g'), b: drxParams.getDefault('gamma', 'b'), master: drxParams.getDefault('gamma', 'master') }
    : { r: 0, g: 0, b: 0, master: 0 },
  gain: drxParams.PARAMETER_RANGES.gain
    ? { r: drxParams.getDefault('gain', 'r'), g: drxParams.getDefault('gain', 'g'), b: drxParams.getDefault('gain', 'b'), master: drxParams.getDefault('gain', 'master') }
    : { r: 1, g: 1, b: 1, master: 1 },
  offset: drxParams.PARAMETER_RANGES.offset
    ? { r: drxParams.getDefault('offset', 'r'), g: drxParams.getDefault('offset', 'g'), b: drxParams.getDefault('offset', 'b') }
    : { r: 0, g: 0, b: 0 },
  saturation: drxParams.getDefault('saturation', 'master') ?? 50,  // Resolve Primaries: 0-100, unity=50
  contrast: drxParams.getDefault('contrast', 'master') ?? 1.0,
  pivot: drxParams.getDefault('pivotFine', 'master') ?? 0.435,
  temperature: drxParams.getDefault('temperature', 'master') ?? 0,
  tint: drxParams.getDefault('tint', 'master') ?? 0,
  midtoneDetail: drxParams.getDefault('midtoneDetail', 'master') ?? 0,
};

/**
 * Tolerance for floating point comparison
 */
const PARAM_TOLERANCE = 0.001;

/**
 * Check if a node has any non-default parameter values
 * @param {Object} node - Parsed node object with params
 * @returns {boolean} - True if node has actual adjustments
 */
function nodeHasAdjustments(node) {
  if (!node || !node.params) return false;

  const p = node.params;
  const d = DEFAULT_PARAMS;

  // Check lift
  if (Math.abs(p.lift.r - d.lift.r) > PARAM_TOLERANCE ||
      Math.abs(p.lift.g - d.lift.g) > PARAM_TOLERANCE ||
      Math.abs(p.lift.b - d.lift.b) > PARAM_TOLERANCE ||
      Math.abs(p.lift.master - d.lift.master) > PARAM_TOLERANCE) {
    return true;
  }

  // Check gamma
  if (Math.abs(p.gamma.r - d.gamma.r) > PARAM_TOLERANCE ||
      Math.abs(p.gamma.g - d.gamma.g) > PARAM_TOLERANCE ||
      Math.abs(p.gamma.b - d.gamma.b) > PARAM_TOLERANCE ||
      Math.abs(p.gamma.master - d.gamma.master) > PARAM_TOLERANCE) {
    return true;
  }

  // Check gain
  if (Math.abs(p.gain.r - d.gain.r) > PARAM_TOLERANCE ||
      Math.abs(p.gain.g - d.gain.g) > PARAM_TOLERANCE ||
      Math.abs(p.gain.b - d.gain.b) > PARAM_TOLERANCE ||
      Math.abs(p.gain.master - d.gain.master) > PARAM_TOLERANCE) {
    return true;
  }

  // Check offset
  if (Math.abs(p.offset.r - d.offset.r) > PARAM_TOLERANCE ||
      Math.abs(p.offset.g - d.offset.g) > PARAM_TOLERANCE ||
      Math.abs(p.offset.b - d.offset.b) > PARAM_TOLERANCE) {
    return true;
  }

  // Check saturation, contrast, pivot
  if (Math.abs(p.saturation - d.saturation) > PARAM_TOLERANCE ||
      Math.abs(p.contrast - d.contrast) > PARAM_TOLERANCE ||
      Math.abs(p.pivot - d.pivot) > PARAM_TOLERANCE) {
    return true;
  }

  // Check for HDR zone adjustments (FIXED 2026-01-17)
  // HDR zones are detected by:
  // 1. Node label starting with "HDR"
  // 2. Correctors containing HDR zone param ID (0x86000305)
  if (node.label && node.label.startsWith('HDR')) {
    return true;
  }

  // Check correctors for HDR zone/global data
  if (node.correctors && node.correctors.length > 0) {
    const HDR_PARAM_IDS = [
      2248147715, // 0x86000303 - Black Offset
      2248147717, // 0x86000305 - Zone Adjustments
      2248147718, // 0x86000306 - Zone Definitions (range/falloff)
      2248147721, // 0x86000309 - Zone Metadata
    ];
    for (const corrector of node.correctors) {
      if (corrector.parameters) {
        for (const param of corrector.parameters) {
          if (HDR_PARAM_IDS.includes(param.id)) {
            return true;
          }
        }
      }
    }
  }

  // Check for any significant corrector data (curves, power windows, qualifiers, etc.)
  // If a node has correctors with substantial parameter data, it likely has a grade
  if (node.correctors && node.correctors.length > 0) {
    for (const corrector of node.correctors) {
      // If corrector has many parameters, it's likely meaningful grade data
      if (corrector.parameters && corrector.parameters.length > 20) {
        return true;
      }
      // Check for curve data (typically has specific structure)
      if (corrector.curves && Object.keys(corrector.curves).length > 0) {
        return true;
      }
      // Check for power window/qualifier data
      if (corrector.windows && corrector.windows.length > 0) {
        return true;
      }
      if (corrector.qualifiers && Object.keys(corrector.qualifiers).length > 0) {
        return true;
      }
    }
  }

  // Check raw node data for any non-default content
  // This catches grades we can't specifically parse but have data
  if (node.rawData && node.rawData.length > 500) {
    // A default node typically has minimal raw data
    // Significant raw data usually indicates grade adjustments
    return true;
  }

  return false;
}

/**
 * Check if a parsed DRX has any actual color adjustments
 * @param {Object} parsedDRX - Parsed DRX object from parseDRX/parseDRXContent
 * @returns {boolean} - True if any node has non-default adjustments
 */
function hasActualGrade(parsedDRX) {
  if (!parsedDRX || !parsedDRX.nodes || parsedDRX.nodes.length === 0) {
    return false;
  }

  return parsedDRX.nodes.some(node => nodeHasAdjustments(node));
}

/**
 * Format a numeric value for display
 * @param {number} val - Value to format
 * @param {number} defaultVal - Default value (for sign display)
 * @returns {string} - Formatted string with sign
 */
function formatValue(val, defaultVal = 0) {
  if (val === undefined || val === null) return '0';
  const diff = val - defaultVal;
  if (Math.abs(diff) < 0.001) return '0';
  const sign = diff > 0 ? '+' : '';
  return `${sign}${val.toFixed(3)}`;
}

/**
 * Extract comprehensive tool breakdown from grade params
 * Returns structured data for UI display with formatted strings
 *
 * @param {Object} params - Grade parameters (can be from DRX node or high-level params)
 * @returns {Object} - Tool breakdown with raw values, formatted strings, and active tools list
 */
function extractToolBreakdown(params) {
  if (!params) {
    return {
      lift: { r: 0, g: 0, b: 0, master: 0 },
      gamma: { r: 0, g: 0, b: 0, master: 0 },
      gain: { r: 1, g: 1, b: 1, master: 1 },
      offset: { r: 0, g: 0, b: 0 },
      saturation: 50,     // Resolve Primaries: 0-100, unity=50
      contrast: 1.0,
      pivot: 0.435,
      temperature: 0,
      tint: 0,
      formatted: {},
      activeTools: [],
      summary: '',
    };
  }

  const d = DEFAULT_PARAMS;

  // Extract values with defaults
  const breakdown = {
    lift: {
      r: params.lift?.r ?? 0,
      g: params.lift?.g ?? 0,
      b: params.lift?.b ?? 0,
      master: params.lift?.master ?? 0,
    },
    gamma: {
      r: params.gamma?.r ?? 0,
      g: params.gamma?.g ?? 0,
      b: params.gamma?.b ?? 0,
      master: params.gamma?.master ?? 0,
    },
    gain: {
      r: params.gain?.r ?? 1,
      g: params.gain?.g ?? 1,
      b: params.gain?.b ?? 1,
      master: params.gain?.master ?? 1,
    },
    offset: {
      r: params.offset?.r ?? 0,
      g: params.offset?.g ?? 0,
      b: params.offset?.b ?? 0,
    },
    saturation: params.saturation ?? 50,  // Resolve Primaries: unity=50
    contrast: params.contrast ?? 1.0,
    pivot: params.pivot ?? 0.435,
    temperature: params.temperature ?? 0,
    tint: params.tint ?? 0,
    formatted: {},
    activeTools: [],
  };

  // Helper to format wheel controls (R, G, B, Master)
  const formatWheel = (wheel, name, defaultVal = 0) => {
    const parts = [];
    if (Math.abs(wheel.r - defaultVal) > PARAM_TOLERANCE) parts.push(`R:${formatValue(wheel.r, defaultVal)}`);
    if (Math.abs(wheel.g - defaultVal) > PARAM_TOLERANCE) parts.push(`G:${formatValue(wheel.g, defaultVal)}`);
    if (Math.abs(wheel.b - defaultVal) > PARAM_TOLERANCE) parts.push(`B:${formatValue(wheel.b, defaultVal)}`);
    if (wheel.master !== undefined && Math.abs(wheel.master - defaultVal) > PARAM_TOLERANCE) {
      parts.push(`M:${formatValue(wheel.master, defaultVal)}`);
    }

    if (parts.length > 0) {
      breakdown.formatted[name] = `${name}: ${parts.join(' ')}`;
      breakdown.activeTools.push(name);
      return true;
    }
    return false;
  };

  // Format each wheel control
  formatWheel(breakdown.lift, 'Lift', 0);
  formatWheel(breakdown.gamma, 'Gamma', 0);
  formatWheel(breakdown.gain, 'Gain', 1);
  formatWheel(breakdown.offset, 'Offset', 0);

  // Format scalar controls
  if (Math.abs(breakdown.saturation - d.saturation) > PARAM_TOLERANCE) {
    breakdown.formatted.Saturation = `Sat: ${formatValue(breakdown.saturation, 50)}`;
    breakdown.activeTools.push('Saturation');
  }

  if (Math.abs(breakdown.contrast - d.contrast) > PARAM_TOLERANCE) {
    breakdown.formatted.Contrast = `Con: ${formatValue(breakdown.contrast, 1)}`;
    breakdown.activeTools.push('Contrast');
  }

  if (Math.abs(breakdown.pivot - d.pivot) > 0.01) {
    breakdown.formatted.Pivot = `Pivot: ${breakdown.pivot.toFixed(3)}`;
    breakdown.activeTools.push('Pivot');
  }

  if (Math.abs(breakdown.temperature) > PARAM_TOLERANCE) {
    const sign = breakdown.temperature > 0 ? '+' : '';
    breakdown.formatted.Temperature = `Temp: ${sign}${breakdown.temperature.toFixed(2)}`;
    breakdown.activeTools.push('Temperature');
  }

  if (Math.abs(breakdown.tint) > PARAM_TOLERANCE) {
    const sign = breakdown.tint > 0 ? '+' : '';
    breakdown.formatted.Tint = `Tint: ${sign}${breakdown.tint.toFixed(2)}`;
    breakdown.activeTools.push('Tint');
  }

  // Generate summary string
  breakdown.summary = Object.values(breakdown.formatted).join(', ');

  return breakdown;
}

/**
 * Extract tool breakdown from a parsed DRX file
 * Merges params from all nodes
 *
 * @param {Object} parsedDRX - Parsed DRX object from parseDRX/parseDRXContent
 * @returns {Object} - Tool breakdown with merged params from all nodes
 */
function extractToolBreakdownFromDRX(parsedDRX) {
  if (!parsedDRX || !parsedDRX.nodes || parsedDRX.nodes.length === 0) {
    return extractToolBreakdown(null);
  }

  // Merge params from all nodes
  const mergedParams = {
    lift: { r: 0, g: 0, b: 0, master: 0 },
    gamma: { r: 0, g: 0, b: 0, master: 0 },
    gain: { r: 1, g: 1, b: 1, master: 1 },
    offset: { r: 0, g: 0, b: 0 },
    saturation: 50,   // Resolve Primaries: 0-100, unity=50
    contrast: 1.0,
    pivot: 0.435,
    temperature: 0,
    tint: 0,
  };

  for (const node of parsedDRX.nodes) {
    if (!node.params) continue;

    // Merge wheel controls (additive for lift/gamma/offset, multiplicative concept for gain)
    for (const control of ['lift', 'gamma', 'offset']) {
      if (node.params[control]) {
        mergedParams[control].r += node.params[control].r || 0;
        mergedParams[control].g += node.params[control].g || 0;
        mergedParams[control].b += node.params[control].b || 0;
        if (node.params[control].master !== undefined) {
          mergedParams[control].master += node.params[control].master || 0;
        }
      }
    }

    // Gain is multiplicative
    if (node.params.gain) {
      mergedParams.gain.r *= node.params.gain.r ?? 1;
      mergedParams.gain.g *= node.params.gain.g ?? 1;
      mergedParams.gain.b *= node.params.gain.b ?? 1;
      if (node.params.gain.master !== undefined) {
        mergedParams.gain.master *= node.params.gain.master ?? 1;
      }
    }

    // Saturation and contrast are multiplicative
    if (node.params.saturation !== undefined) {
      mergedParams.saturation *= node.params.saturation;
    }
    if (node.params.contrast !== undefined) {
      mergedParams.contrast *= node.params.contrast;
    }

    // Pivot uses last value
    if (node.params.pivot !== undefined) {
      mergedParams.pivot = node.params.pivot;
    }

    // Temperature and tint are additive
    if (node.params.temperature !== undefined) {
      mergedParams.temperature += node.params.temperature;
    }
    if (node.params.tint !== undefined) {
      mergedParams.tint += node.params.tint;
    }
  }

  return extractToolBreakdown(mergedParams);
}

/**
 * Tolerance for sync drift detection (slightly higher than display tolerance)
 * Using 0.01 to avoid false positives from floating point precision issues
 */
const SYNC_DRIFT_TOLERANCE = 0.01;

/**
 * Compare two sets of grade parameters to detect sync drift
 * Returns whether the parameters match within tolerance
 *
 * @param {Object} paramsA - First parameter set (from stored version's cumulativeState)
 * @param {Object} paramsB - Second parameter set (from parsed DRX breakdown)
 * @param {Object} options - Comparison options
 * @param {number} options.tolerance - Override default tolerance (default: 0.01)
 * @returns {Object} - { matches: boolean, differences: Array, summary: string }
 */
function compareGradeParameters(paramsA, paramsB, options = {}) {
  const tolerance = options.tolerance ?? SYNC_DRIFT_TOLERANCE;
  const differences = [];

  // Helper to compare single values
  const compareValue = (valA, valB, paramPath, defaultVal = 0) => {
    const a = valA ?? defaultVal;
    const b = valB ?? defaultVal;
    const diff = Math.abs(a - b);
    if (diff > tolerance) {
      differences.push({
        param: paramPath,
        stored: a,
        current: b,
        diff: diff,
      });
    }
  };

  // Handle case where one or both are null/undefined
  if (!paramsA && !paramsB) {
    return { matches: true, differences: [], summary: 'Both neutral' };
  }
  if (!paramsA) {
    paramsA = DEFAULT_PARAMS;
  }
  if (!paramsB) {
    paramsB = DEFAULT_PARAMS;
  }

  // Compare wheel controls (lift, gamma, gain, offset)
  const wheels = ['lift', 'gamma', 'gain', 'offset'];
  const channels = ['r', 'g', 'b', 'master'];

  for (const wheel of wheels) {
    const wheelA = paramsA[wheel] || {};
    const wheelB = paramsB[wheel] || {};

    for (const ch of channels) {
      // Skip master for offset (it doesn't have master in some representations)
      if (wheel === 'offset' && ch === 'master') continue;

      // Default values differ: gain defaults to 1, others to 0
      const defaultVal = wheel === 'gain' ? 1 : 0;
      const valA = wheelA[ch];
      const valB = wheelB[ch];

      compareValue(valA, valB, `${wheel}.${ch}`, defaultVal);
    }
  }

  // Compare scalar controls
  const scalars = [
    { name: 'saturation', default: 50 },  // Resolve Primaries: 0-100, unity=50
    { name: 'contrast', default: 1 },
    { name: 'pivot', default: 0.435 },
    { name: 'temperature', default: 0 },
    { name: 'tint', default: 0 },
  ];

  for (const scalar of scalars) {
    const valA = paramsA[scalar.name];
    const valB = paramsB[scalar.name];
    compareValue(valA, valB, scalar.name, scalar.default);
  }

  // Generate summary
  let summary = '';
  if (differences.length === 0) {
    summary = 'Parameters match';
  } else if (differences.length <= 3) {
    summary = differences.map(d => `${d.param}: ${d.stored.toFixed(3)} → ${d.current.toFixed(3)}`).join(', ');
  } else {
    summary = `${differences.length} parameters differ`;
  }

  return {
    matches: differences.length === 0,
    differences,
    summary,
  };
}

/**
 * Normalize semantic params (temperature, tint, contrast) to actual wheel values
 * This converts high-level params to the actual lift/gamma/gain values they produce
 *
 * Uses the same formulas as drx-generator.js parseAdjustmentsToNodes:
 * - temperature: gain.r += t*0.15, gain.b -= t*0.15, lift.r += t*0.08, lift.b -= t*0.08
 * - tint: gain.g -= t*0.15, lift.g -= t*0.08
 * - contrast: implemented via lift/gain (not contrast corrector)
 *
 * @param {Object} params - Semantic params (may include temperature, tint, etc.)
 * @returns {Object} - Normalized params with wheel values
 */
function normalizeSemanticParams(params) {
  if (!params) return params;

  const result = {
    lift: { r: 0, g: 0, b: 0, master: 0 },
    gamma: { r: 0, g: 0, b: 0, master: 0 },
    gain: { r: 1, g: 1, b: 1, master: 1 },
    offset: { r: 0, g: 0, b: 0 },
    saturation: 50,    // Resolve Primaries: 0-100, unity=50
    contrast: 1,
    pivot: params.pivot ?? 0.435,
  };

  // Apply temperature to wheel values
  if (params.temperature && Math.abs(params.temperature) > 0.001) {
    const t = params.temperature;
    result.gain.r = 1 + (t * 0.15);
    result.gain.b = 1 - (t * 0.15);
    result.lift.r = t * 0.08;
    result.lift.b = -(t * 0.08);
  }

  // Apply tint to wheel values
  if (params.tint && Math.abs(params.tint) > 0.001) {
    const t = params.tint;
    result.gain.g -= t * 0.15;
    result.lift.g -= t * 0.08;
  }

  // Apply shadowLift to wheel values (matches drx-generator.js)
  if (params.shadowLift && Math.abs(params.shadowLift) > 0.001) {
    const s = params.shadowLift;
    result.lift.r += s * 0.25;
    result.lift.g += s * 0.25;
    result.lift.b += s * 0.25;
    result.lift.master += s * 0.15;
    console.log('[drx-parser] ShadowLift applied:', s, '→ lift.r:', result.lift.r);
  }

  // Apply highlightCompression to wheel values (matches drx-generator.js)
  if (params.highlightCompression && Math.abs(params.highlightCompression) > 0.001) {
    const h = params.highlightCompression;
    result.gain.r -= h * 0.1;
    result.gain.g -= h * 0.1;
    result.gain.b -= h * 0.1;
    console.log('[drx-parser] HighlightCompression applied:', h, '→ gain.r:', result.gain.r);
  }

  // Apply semantic contrast to wheel values (matches drx-generator.js parseAdjustmentsToNodes)
  // IMPORTANT: drx-generator.js parseAdjustmentsToNodes implements contrast via lift/gain,
  // NOT the contrast scalar! The contrast scalar stays at 1.0 (neutral).
  // See drx-generator.js line 1987: "We implement contrast using Lift/Gain instead of the
  // Contrast Corrector (Type 2) because Type 2 was causing HSL qualifier issues."
  if (params.contrast && Math.abs(params.contrast) > 0.01) {
    const c = params.contrast;
    const contrastAmount = c * 0.15;
    // Lower shadows for more contrast (additive to existing lift)
    result.lift.r += -contrastAmount;
    result.lift.g += -contrastAmount;
    result.lift.b += -contrastAmount;
    result.lift.master += -contrastAmount * 0.5;
    // Raise highlights for more contrast (additive to existing gain which defaults to 1.0)
    result.gain.r += contrastAmount;
    result.gain.g += contrastAmount;
    result.gain.b += contrastAmount;
    result.gain.master += contrastAmount * 0.5;
    console.log('[drx-parser] Contrast (via lift/gain) applied:', c, '→ lift.r:', result.lift.r, 'gain.r:', result.gain.r);
  }

  // Apply saturation - ALWAYS convert semantic (-1 to 1) to Resolve Primaries (0 to 100)
  // Semantic model: -1 = desaturated, 0 = neutral, 1 = oversaturated
  // Resolve Primaries: 0 = desaturated, 50 = neutral (unity), 100 = oversaturated
  // Formula matches drx-generator.js: params.saturation = 50 + (adjustments.saturation * 50)
  // NOTE: cumulativeState always stores semantic values from applyTweak() which clamps to -1..1
  if (params.saturation !== undefined) {
    // Always convert from semantic -1..1 to Resolve 0..100
    // semantic 0 -> actual 50, semantic -1 -> actual 0, semantic 1 -> actual 100
    result.saturation = 50 + (params.saturation * 50);
    console.log('[drx-parser] Saturation converted: semantic', params.saturation, '→ actual', result.saturation);
  } else {
    console.log('[drx-parser] Saturation undefined, using default:', result.saturation);
  }

  // DO NOT convert contrast to the contrast scalar!
  // The drx-generator.js parseAdjustmentsToNodes function implements contrast via lift/gain
  // (see above), so the contrast scalar stays at 1.0 (neutral) in the generated DRX.
  // We already applied the contrast adjustment to lift/gain above, so leave scalar at default.
  // result.contrast stays at 1 (the default set at initialization)
  if (params.contrast !== undefined) {
    console.log('[drx-parser] Contrast handled via lift/gain, scalar stays at:', result.contrast);
  }

  // Copy any explicit wheel values from params (they override computed values)
  for (const wheel of ['lift', 'gamma', 'gain', 'offset']) {
    if (params[wheel]) {
      for (const ch of ['r', 'g', 'b', 'master']) {
        if (params[wheel][ch] !== undefined) {
          // For temperature/tint derived values, add to existing
          // For explicit values, use directly
          if ((wheel === 'gain' || wheel === 'lift') && (params.temperature || params.tint)) {
            // Values already applied from temperature/tint
          } else {
            result[wheel][ch] = params[wheel][ch];
          }
        }
      }
    }
  }

  return result;
}

/**
 * Compare a stored version's cumulativeState with current Resolve grade
 * Convenience wrapper that parses the DRX and compares parameters
 *
 * @param {Object} storedParams - The cumulativeState from stored version
 * @param {string} drxContent - DRX content exported from Resolve
 * @returns {Promise<Object>} - { matches, differences, summary, resolveParams }
 */
async function compareSyncState(storedParams, drxContent) {
  try {
    // Debug: Log incoming stored params
    console.log('[drx-parser] compareSyncState input storedParams:', JSON.stringify({
      saturation: storedParams?.saturation,
      contrast: storedParams?.contrast,
      temperature: storedParams?.temperature,
      shadowLift: storedParams?.shadowLift,
      highlightCompression: storedParams?.highlightCompression,
      tint: storedParams?.tint,
    }));

    // Parse the DRX to get current parameters
    const parsedDrx = await parseDRXContent(drxContent);
    const breakdown = extractToolBreakdownFromDRX(parsedDrx);

    // Extract just the parameter values for comparison
    const resolveParams = {
      lift: breakdown.lift,
      gamma: breakdown.gamma,
      gain: breakdown.gain,
      offset: breakdown.offset,
      saturation: breakdown.saturation,
      contrast: breakdown.contrast,
      pivot: breakdown.pivot,
      temperature: breakdown.temperature || 0,
      tint: breakdown.tint || 0,
    };

    // Debug: Log DRX params
    console.log('[drx-parser] compareSyncState DRX resolveParams:', JSON.stringify({
      saturation: resolveParams.saturation,
      contrast: resolveParams.contrast,
    }));

    // Normalize stored params to convert semantic values (temperature, tint)
    // to actual wheel values for accurate comparison
    const normalizedStoredParams = normalizeSemanticParams(storedParams);

    // Debug: Log normalized params
    console.log('[drx-parser] compareSyncState normalized storedParams:', JSON.stringify({
      saturation: normalizedStoredParams?.saturation,
      contrast: normalizedStoredParams?.contrast,
    }));

    const result = compareGradeParameters(normalizedStoredParams, resolveParams);

    return {
      ...result,
      resolveParams,
      nodeCount: parsedDrx.nodes?.length || 0,
    };
  } catch (error) {
    return {
      matches: false,
      differences: [],
      summary: `Parse error: ${error.message}`,
      error: error.message,
    };
  }
}

/**
 * Compare two DRX contents directly (DRX-to-DRX comparison)
 * This is more accurate than comparing cumulativeState to DRX
 * because it avoids normalization/conversion mismatches.
 *
 * @param {string} storedDrxContent - The stored version's DRX content
 * @param {string} currentDrxContent - The current DRX from Resolve
 * @param {Object} options - Comparison options
 * @param {number} options.tolerance - Override default tolerance (default: 0.02 for DRX-to-DRX)
 * @returns {Promise<Object>} - { matches, differences, summary, storedParams, currentParams }
 */
async function compareDRXContent(storedDrxContent, currentDrxContent, options = {}) {
  // Use slightly higher tolerance for DRX-to-DRX since minor floating point
  // differences can occur during export/import cycles
  const tolerance = options.tolerance ?? 0.02;

  try {
    // Parse both DRX files
    const storedParsed = await parseDRXContent(storedDrxContent);
    const currentParsed = await parseDRXContent(currentDrxContent);

    // Extract tool breakdowns (actual wheel values)
    const storedBreakdown = extractToolBreakdownFromDRX(storedParsed);
    const currentBreakdown = extractToolBreakdownFromDRX(currentParsed);

    // Build param objects for comparison
    const storedParams = {
      lift: storedBreakdown.lift,
      gamma: storedBreakdown.gamma,
      gain: storedBreakdown.gain,
      offset: storedBreakdown.offset,
      saturation: storedBreakdown.saturation,
      contrast: storedBreakdown.contrast,
      pivot: storedBreakdown.pivot,
    };

    const currentParams = {
      lift: currentBreakdown.lift,
      gamma: currentBreakdown.gamma,
      gain: currentBreakdown.gain,
      offset: currentBreakdown.offset,
      saturation: currentBreakdown.saturation,
      contrast: currentBreakdown.contrast,
      pivot: currentBreakdown.pivot,
    };

    // Compare parameters with specified tolerance
    const result = compareGradeParameters(storedParams, currentParams, { tolerance });

    return {
      ...result,
      storedParams,
      currentParams,
      storedNodeCount: storedParsed.nodes?.length || 0,
      currentNodeCount: currentParsed.nodes?.length || 0,
    };
  } catch (error) {
    console.error('[drx-parser] compareDRXContent error:', error.message);
    return {
      matches: false,
      differences: [],
      summary: `Parse error: ${error.message}`,
      error: error.message,
    };
  }
}

module.exports = {
  parseDRX,
  parseDRXContent,
  parseDRXBody,
  extractNodes,
  extractConnections,
  extractMetadata,
  ProtobufParser,
  PARAM_IDS,
  CORRECTOR_TYPES,
  DEFAULT_PARAMS,
  nodeHasAdjustments,
  hasActualGrade,
  // Tool breakdown utilities
  extractToolBreakdown,
  extractToolBreakdownFromDRX,
  formatValue,
  // Sync drift detection utilities
  SYNC_DRIFT_TOLERANCE,
  normalizeSemanticParams,
  compareGradeParameters,
  compareSyncState,
  compareDRXContent,
  // Re-export shared library for convenience
  drxParams,
};
