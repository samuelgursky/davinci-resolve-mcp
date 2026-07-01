/**
 * Decode CUSTOM_CURVES (YRGB) corrector params back to the spec shape
 * generator's buildCustomCurveParams accepts (P1.1).
 *
 * Encoding (per drx-generator.js encodeCurveSpline):
 *   - splineId param's F2 contains a wrapped protobuf in field 8
 *   - Field 8 is a nested message containing repeated F1 entries
 *   - Each F1 entry holds { F1: x_scaled_float32, F2: y_scaled_float32 }
 *   - First point is the sentinel (-1024, -1024)
 *   - Then an empty F1 (separator)
 *   - Then user-supplied points scaled by 1023
 *   - Then end point (1023, 1023)
 *
 * Decoded points come back in normalized 0–1 space, sorted by x.
 *
 * @module drx-codec/extract-custom-curves
 */

// IMPORTANT: drx-parameters CUSTOM_CURVES.Y_SPLINE/R/G/B has a documented
// Y/R/G/B → R/G/B/Y inversion (see drx-generator.js comments around
// lines 199-202: "was incorrectly mapped to..."). The GENERATOR'S
// mapping is correct; the registry's is the bug. We mirror the
// generator here so round-trip is byte-symmetrical. Knowledge note
// in docs/design/drp-drx-drt-closeout-harness/knowledge/.
const SPLINE_IDS = {
  y: 2248148233,  // 0x86000509 — registry calls this B_SPLINE (bug)
  r: 2248148230,  // 0x86000506 — registry calls this Y_SPLINE (bug)
  g: 2248148231,  // 0x86000507 — registry calls this R_SPLINE (bug)
  b: 2248148232,  // 0x86000508 — registry calls this G_SPLINE (bug)
};

const SCALE = 1023;
const SENTINEL_X = -1024;

/**
 * Read a single proto field at offset. Returns { wireType, fieldNum,
 * value, next } where value depends on wire type. Mirrors the
 * mini-parser used inside drx-parser.js but limited to what we need.
 */
function readVarint(buf, offset) {
  let result = 0n;
  let shift = 0n;
  let cur = offset;
  while (cur < buf.length) {
    const byte = buf[cur++];
    result |= BigInt(byte & 0x7f) << shift;
    if ((byte & 0x80) === 0) return { value: result, next: cur };
    shift += 7n;
  }
  throw new Error('Truncated varint');
}

function readField(buf, offset) {
  const tag = readVarint(buf, offset);
  const tagNum = Number(tag.value);
  const wireType = tagNum & 0x07;
  const fieldNum = tagNum >>> 3;
  let cur = tag.next;
  if (wireType === 0) {
    const v = readVarint(buf, cur);
    return { wireType, fieldNum, value: v.value, next: v.next };
  }
  if (wireType === 5) {
    // 32-bit fixed (float32)
    const v = buf.readFloatLE(cur);
    return { wireType, fieldNum, value: v, next: cur + 4 };
  }
  if (wireType === 1) {
    // 64-bit fixed (double)
    const v = buf.readDoubleLE(cur);
    return { wireType, fieldNum, value: v, next: cur + 8 };
  }
  if (wireType === 2) {
    const len = readVarint(buf, cur);
    const start = len.next;
    const end = start + Number(len.value);
    return { wireType, fieldNum, value: buf.slice(start, end), next: end };
  }
  throw new Error(`Unsupported wire type ${wireType}`);
}

function readAllFields(buf) {
  const fields = [];
  let cur = 0;
  while (cur < buf.length) {
    const f = readField(buf, cur);
    fields.push(f);
    cur = f.next;
  }
  return fields;
}

/**
 * Decode a single curve point: nested message with { F1: x, F2: y }
 * where both are float32. Accepts either a raw Buffer (when called on
 * raw protobuf bytes) or the parsed structure that drx-parser produces.
 */
function decodePoint(pointBufOrFields) {
  let fields;
  if (Buffer.isBuffer(pointBufOrFields)) {
    fields = readAllFields(pointBufOrFields);
  } else if (pointBufOrFields && pointBufOrFields._fields) {
    fields = pointBufOrFields._fields;
  } else {
    return { x: 0, y: 0 };
  }
  let x = 0, y = 0;
  for (const f of fields) {
    if (f.fieldNum === 1 && f.wireType === 5) x = f.value;
    if (f.fieldNum === 2 && f.wireType === 5) y = f.value;
  }
  return { x, y };
}

/**
 * Decode an encodeCurveSpline value to normalized {x,y} points.
 *
 * Accepts EITHER a raw Buffer (when working with un-parsed bytes) OR
 * the parsed structure that drx-parser surfaces — the parser walks the
 * nested protobuf eagerly so by the time the parameter value reaches a
 * caller it already has `_fields`, `F8`, etc.
 */
function decodeSpline(splineValue) {
  if (splineValue == null) return [];

  // Case 1 — raw buffer (e.g. when caller has unparsed bytes).
  if (Buffer.isBuffer(splineValue)) {
    if (splineValue.length === 0) return [];
    const fields = readAllFields(splineValue);
    const innerField = fields.find((f) => f.fieldNum === 8 && f.wireType === 2);
    if (!innerField) return [];
    return decodeInnerBuf(innerField.value);
  }

  // Case 2 — parsed structure with F8 already decoded.
  if (typeof splineValue === 'object' && splineValue.F8 !== undefined) {
    const inner = splineValue.F8;
    if (inner && inner._fields) {
      return decodeInnerFromParsed(inner._fields);
    }
    if (Buffer.isBuffer(inner)) {
      return decodeInnerBuf(inner);
    }
  }

  return [];
}

function decodeInnerBuf(innerBuf) {
  if (!Buffer.isBuffer(innerBuf)) return [];
  const innerFields = readAllFields(innerBuf);
  const points = [];
  for (const f of innerFields) {
    if (f.fieldNum !== 1 || f.wireType !== 2) continue;
    if (f.value.length === 0) continue; // empty separator
    const pt = decodePoint(f.value);
    if (pt.x === SENTINEL_X) continue;
    points.push({ x: pt.x / SCALE, y: pt.y / SCALE });
  }
  points.sort((a, b) => a.x - b.x);
  return points;
}

function decodeInnerFromParsed(innerFields) {
  const points = [];
  for (const f of innerFields) {
    if (f.fieldNum !== 1 || f.wireType !== 2) continue;
    // Empty separators come through as zero-length buffers / empty
    // objects depending on the parser path.
    if (Buffer.isBuffer(f.value) && f.value.length === 0) continue;
    if (!Buffer.isBuffer(f.value) && (!f.value || !f.value._fields || f.value._fields.length === 0)) continue;
    const pt = decodePoint(f.value);
    if (pt.x === SENTINEL_X) continue;
    if (pt.x === 0 && pt.y === 0) continue; // empty separator surfaces as (0,0) sometimes
    points.push({ x: pt.x / SCALE, y: pt.y / SCALE });
  }
  points.sort((a, b) => a.x - b.x);
  return points;
}

/**
 * Given a corrector's parameter list (as drx-parser surfaces it under
 * corrector.parameters), extract per-channel custom curves.
 *
 * @param {Array<{id, value, name}>} parameters
 * @returns {{y: Array, r: Array, g: Array, b: Array} | null}
 *   null if no spline params present; per-channel arrays if found.
 *   Identity curves (only endpoint, no user points) come back as empty
 *   arrays — matches what buildCustomCurveParams treats as "no user
 *   data for this channel".
 */
function extractCustomCurves(parameters) {
  if (!Array.isArray(parameters)) return null;
  const out = { y: [], r: [], g: [], b: [] };
  let anyFound = false;
  for (const param of parameters) {
    const splineChannel = Object.entries(SPLINE_IDS).find(([, id]) => id === param.id);
    if (!splineChannel) continue;
    const [channel] = splineChannel;
    if (param.value == null) continue;
    const points = decodeSpline(param.value);
    // Identity curves end at (1, 1) only. Strip the endpoint sentinel
    // from the user-visible result.
    const userPoints = points.filter((p) => !(p.x === 1 && p.y === 1));
    if (userPoints.length > 0) anyFound = true;
    out[channel] = userPoints;
  }
  return anyFound ? out : null;
}

module.exports = {
  extractCustomCurves,
  // Exposed for testing only.
  _internals: { decodeSpline, decodePoint, readAllFields, SPLINE_IDS },
};
