/**
 * Decode HSL_CURVES corrector params back to the spec shape that
 * generateDRX's hslCurves input accepts (P1.2).
 *
 * HSL curves use a different encoding from YRGB custom curves
 * (encodeHSLCurveSpline in drx-generator.js):
 *   - NO sentinel (-1024, -1024)
 *   - NO empty separator
 *   - NO end marker
 *   - Just raw float data points wrapped in F8
 *   - X = hue fraction (0..1 with wrap-around continuity, e.g. -0.08..1.08)
 *   - Y = neutral 0.5, >0.5 = boost, <0.5 = cut
 *
 * The 6 HSL curve types: hueVsHue, hueVsSat, hueVsLum, lumVsSat,
 * satVsSat, satVsLum.
 *
 * @module drx-codec/extract-hsl-curves
 */

const drxParams = require('../drx-parameters');

const HSL_SPLINE_IDS = {
  hueVsHue: drxParams.HSL_CURVES.HUE_VS_HUE_SPLINE,
  hueVsSat: drxParams.HSL_CURVES.HUE_VS_SAT_SPLINE,
  hueVsLum: drxParams.HSL_CURVES.HUE_VS_LUM_SPLINE,
  lumVsSat: drxParams.HSL_CURVES.LUM_VS_SAT_SPLINE,
  satVsSat: drxParams.HSL_CURVES.SAT_VS_SAT_SPLINE,
  satVsLum: drxParams.HSL_CURVES.SAT_VS_LUM_SPLINE,
};

// ─── Mini protobuf reader (shared shape with extract-custom-curves) ─────

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
    const v = buf.readFloatLE(cur);
    return { wireType, fieldNum, value: v, next: cur + 4 };
  }
  if (wireType === 1) {
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
 * Decode an encodeHSLCurveSpline value to raw {x, y} float points.
 *
 * HSL is simpler than YRGB: no sentinel, no separator, no end marker.
 * Just F1 entries inside the F8 wrapper.
 */
function decodeHSLSpline(splineValue) {
  if (splineValue == null) return [];

  if (Buffer.isBuffer(splineValue)) {
    if (splineValue.length === 0) return [];
    const fields = readAllFields(splineValue);
    const inner = fields.find((f) => f.fieldNum === 8 && f.wireType === 2);
    if (!inner) return [];
    return decodeInnerBuf(inner.value);
  }

  if (typeof splineValue === 'object' && splineValue.F8 !== undefined) {
    const inner = splineValue.F8;
    if (inner && inner._fields) return decodeInnerFromParsed(inner._fields);
    if (Buffer.isBuffer(inner)) return decodeInnerBuf(inner);
  }

  return [];
}

function decodeInnerBuf(innerBuf) {
  if (!Buffer.isBuffer(innerBuf)) return [];
  const innerFields = readAllFields(innerBuf);
  const points = [];
  for (const f of innerFields) {
    if (f.fieldNum !== 1 || f.wireType !== 2) continue;
    if (f.value.length === 0) continue;
    points.push(decodePoint(f.value));
  }
  return points;
}

function decodeInnerFromParsed(innerFields) {
  const points = [];
  for (const f of innerFields) {
    if (f.fieldNum !== 1 || f.wireType !== 2) continue;
    if (Buffer.isBuffer(f.value) && f.value.length === 0) continue;
    if (!Buffer.isBuffer(f.value) && (!f.value || !f.value._fields || f.value._fields.length === 0)) continue;
    points.push(decodePoint(f.value));
  }
  return points;
}

/**
 * Given a corrector's parameter list, extract per-type HSL curves.
 *
 * @param {Array<{id, value, name}>} parameters
 * @returns {{hueVsHue?, hueVsSat?, hueVsLum?, lumVsSat?, satVsSat?, satVsLum?} | null}
 *   null if no HSL spline params present; otherwise an object with one
 *   entry per detected curve type. Each entry is the array of float
 *   {x, y} points in raw (un-normalized) space.
 */
function extractHSLCurves(parameters) {
  if (!Array.isArray(parameters)) return null;
  const out = {};
  let anyFound = false;
  for (const param of parameters) {
    const splineEntry = Object.entries(HSL_SPLINE_IDS).find(([, id]) => id === param.id);
    if (!splineEntry) continue;
    const [curveType] = splineEntry;
    if (param.value == null) continue;
    const points = decodeHSLSpline(param.value);
    if (points.length > 0) {
      out[curveType] = points;
      anyFound = true;
    }
  }
  return anyFound ? out : null;
}

module.exports = {
  extractHSLCurves,
  _internals: { decodeHSLSpline, decodePoint, readAllFields, HSL_SPLINE_IDS },
};
