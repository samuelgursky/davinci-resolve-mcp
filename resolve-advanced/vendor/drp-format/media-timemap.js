/**
 * media-timemap — decode/encode the per-clip MediaTimemapBA (retime / speed map).
 *
 * Resolve writes this blob in TWO forms:
 *
 *  1. IDENTITY (1× speed) — compact:  [u8 0x02][ BE float64 seconds … ]
 *     The doubles are source time extents in seconds; a media clip's identity map is
 *     `[02][end,0,end',0,end]` (end == lastFrameIndex/fps). Generators/titles carry the
 *     degenerate `[02][duration]`.
 *
 *  2. RETIMED (non-1×) — a `Sm2TimeMap` keyed-dict:
 *       YMin/YMax        : -1 (sentinels)
 *       XMax (double)    : RECORD (timeline) duration in seconds
 *       LastValidYOffset : SOURCE duration in seconds
 *       KeyframesBA      : protobuf curve — field 1 holds [double recordSec][double sourceSec]
 *       DbType           : "Sm2TimeMap"
 *     => constant SPEED = LastValidYOffset / XMax  (source/record).
 *
 * Verified live: a 50% clip exported XMax=305.33, LastValidYOffset=152.65 → speed 0.4999.
 * encode(decode(x)) reproduces both forms exactly. See knowledge/blob-map.md.
 *
 * @module drp-format/media-timemap
 */

const { decodeKeyedDict, encodeKeyedDict, T_DOUBLE, T_STRING, T_BYTES } = require('./keyed-dict');
const { decodeProtobuf, encodeProtobuf } = require('./protobuf-wire');

const TYPE_LINEAR = 0x02;

function _isKeyedForm(b) {
  return b.length >= 8 && b.readUInt32BE(0) === 1;
}

/**
 * Decode → for identity form { form:'identity', type, seconds }.
 *          for retimed form { form:'retimed', speed, sourceDurationSec, recordDurationSec, entries }.
 */
/**
 * Parse the KeyframesBA protobuf → ordered keyframe points [{ recordSec, sourceSec }].
 * KeyframesBA = { field 160: 0, field 1 (REPEATED): Keyframe{ f1: recordSec, f2: sourceSec } }
 * (fixed64 LE doubles). The map starts at the implicit (0,0); constant speed has one keyframe,
 * a variable-speed ramp has one keyframe per added speed point.
 */
/**
 * One keyframe point: an inner message of field 1 (recordSec) and field 2
 * (sourceSec), both wire type 1 (64-bit double) — tags 0x09 and 0x11.
 *
 * Both are OPTIONAL. Protobuf omits a field whose value is the default (0), so
 * a point can legitimately carry only one of the two, and fixed offsets do not
 * work. This is not theoretical: a REVERSED clip exported by Resolve 21.0.4.5
 * encodes its points as `0a 09 11 <double>` (sourceSec only) and
 * `0a 09 09 <double>` (recordSec only), and the previous fixed-offset reader
 * — `readDoubleLE(1)` / `readDoubleLE(10)` — threw
 * "offset out of range … Received 10" on every reversed map. Forward maps only
 * decoded because both values happened to be non-zero.
 */
function _decodeKeyframePoint(buf) {
  let recordSec = 0;
  let sourceSec = 0;
  let i = 0;
  while (i < buf.length) {
    const tag = buf[i];
    if (tag === 0x09 && i + 9 <= buf.length) { recordSec = buf.readDoubleLE(i + 1); i += 9; }
    else if (tag === 0x11 && i + 9 <= buf.length) { sourceSec = buf.readDoubleLE(i + 1); i += 9; }
    else break; // unknown tag or truncated — stop rather than misread
  }
  return { recordSec, sourceSec };
}

/**
 * Keyframe points plus the map's ORIGIN.
 *
 * The origin is not always (0,0). A reversed clip starts at the far end of the
 * source and walks backwards, and Resolve encodes that starting source offset as
 * a TOP-LEVEL field 2 double alongside the keyframe messages. Measured on a
 * reversed clip exported by Studio 21.0.4.5:
 *
 *   80 0a 09                      field 160 = 9
 *   11 5655555555d51740           field 2   = 5.9583  <- origin sourceSec
 *   0a 09 09 5655555555d51740     field 1   = { recordSec: 5.9583 }
 *
 * Reading that as an implicit (0,0) origin yields a segment from (0,0) to
 * (5.9583, 0) — slope 0 — so a reverse decodes as "speed 0", a plausible-looking
 * wrong answer rather than an error. With the origin it is (0, 5.9583) to
 * (5.9583, 0): slope -1, a reverse.
 */
function _decodeKeyframes(hex) {
  if (hex == null) return { origin: { recordSec: 0, sourceSec: 0 }, keyframes: [] };
  // r19 KEYED-DICT form (E144): Resolve 19.1.3.7 itself writes KeyframesBA
  // as a keyed dict of keyed-dict keyframes ({interp,YOut,YIn,Y,XOut,XIn,X}
  // under keys '0','1',…) on every retime it makes (XMEML import, UI speed
  // change, EDL M2 freeze) — the same shape buildConstantSpeedTimemapKeyed
  // emits — while an EXPORT_DRT of a hand-conformed reel carried protobuf
  // points. The reader used to throw on the keyed form ("unsupported wire
  // type 7"), so a Resolve-made retime read as unknown. Keyframe 0 at X=0 is
  // the origin (its Y = the source second the map starts on: 4.0 on a real
  // ramp harvest); the rest are the points.
  const kh = String(hex).replace(/[^0-9a-fA-F]/g, '');
  if (kh.startsWith('00000001')) {
    const pts = [];
    for (const e of decodeKeyedDict(Buffer.from(kh, 'hex')).entries) {
      const inner = decodeKeyedDict(Buffer.from(String(e.value), 'hex')).entries;
      const get = (k) => { const f = inner.find((x) => x.key === k); return f ? Number(f.value) : 0; };
      pts.push({ recordSec: get('X'), sourceSec: get('Y') });
    }
    pts.sort((a, b) => a.recordSec - b.recordSec);
    const origin = pts.length && pts[0].recordSec === 0 ? pts.shift() : { recordSec: 0, sourceSec: 0 };
    return { origin, keyframes: pts, keyed: true };
  }
  const fields = decodeProtobuf(hex);
  const originField = fields.find((f) => f.field === 2 && f.wire === 1);
  const originSource = originField
    ? (Buffer.isBuffer(originField.value)
      ? originField.value.readDoubleLE(0)
      : Number(originField.value))
    : 0;
  return {
    origin: { recordSec: 0, sourceSec: Number.isFinite(originSource) ? originSource : 0 },
    keyframes: fields
      .filter((f) => f.field === 1 && f.wire === 2)
      .map((f) => _decodeKeyframePoint(f.value)),
  };
}

/** Per-segment speeds from the keyframe points (slope Δsource/Δrecord). */
function _segments(keyframes, origin = { recordSec: 0, sourceSec: 0 }) {
  const pts = [origin, ...keyframes];
  const segs = [];
  for (let i = 1; i < pts.length; i++) {
    const dr = pts[i].recordSec - pts[i - 1].recordSec;
    const ds = pts[i].sourceSec - pts[i - 1].sourceSec;
    segs.push({ fromRecordSec: pts[i - 1].recordSec, toRecordSec: pts[i].recordSec, speed: dr ? ds / dr : 0 });
  }
  return segs;
}

function decodeTimemap(input) {
  const b = Buffer.isBuffer(input) ? input : Buffer.from(input, 'hex');
  if (_isKeyedForm(b)) {
    const { entries } = decodeKeyedDict(b);
    const get = (k) => { const e = entries.find((x) => x.key === k); return e ? e.value : undefined; };
    const recordDurationSec = get('XMax');
    const sourceDurationSec = get('LastValidYOffset');
    const { origin, keyframes, keyed } = _decodeKeyframes(get('KeyframesBA'));
    const segments = _segments(keyframes, origin);
    // The EXACT speed lives in the keyframe ratios (source/record per segment); XMax and
    // LastValidYOffset are frame-quantized. `speed` is the first segment's (whole clip if 1 kf);
    // `segments` carries the full variable-speed ramp.
    const speed = segments.length ? segments[0].speed : sourceDurationSec / recordDurationSec;
    const variable = segments.length > 1;
    return {
      form: 'retimed', variable, speed, segments, keyframes, origin, keyframeForm: keyed ? 'keyed' : 'protobuf',
      sourceDurationSec, recordDurationSec, entries,
    };
  }
  if (b.length < 1 || (b.length - 1) % 8 !== 0) {
    throw new Error(`MediaTimemapBA: unexpected length ${b.length}`);
  }
  const seconds = [];
  for (let o = 1; o + 8 <= b.length; o += 8) seconds.push(b.readDoubleBE(o));
  return { form: 'identity', type: b[0], seconds };
}

/** Encode the identity (compact) form { type, seconds } → Buffer (round-trips exactly). */
function encodeTimemap({ type = TYPE_LINEAR, seconds }) {
  const b = Buffer.alloc(1 + seconds.length * 8);
  b.writeUInt8(type, 0);
  seconds.forEach((s, i) => b.writeDoubleBE(s, 1 + i * 8));
  return b;
}

/** Re-encode a decoded retimed timemap ({ entries }) → Buffer (round-trips exactly). */
function encodeRetimedTimemap({ entries }) {
  return encodeKeyedDict({ hdr: 1, entries });
}

/**
 * Build the identity (1×) compact map for a clip of `frameCount` frames at `fps`.
 * Matches the real Resolve shape `[02][end,0,end,0,end]` (end = (frameCount-1)/fps).
 */
function identityTimemap(frameCount, fps) {
  const end = (frameCount - 1) / fps;
  return encodeTimemap({ type: TYPE_LINEAR, seconds: [end, 0, end, 0, end] });
}

/** Encode KeyframesBA from ordered (recordSec, sourceSec) points. */
function _encodeKeyframes(keyframes) {
  const msgs = keyframes.map((k) => {
    const inner = Buffer.alloc(18);
    inner.writeUInt8(0x09, 0); inner.writeDoubleLE(k.recordSec, 1);
    inner.writeUInt8(0x11, 9); inner.writeDoubleLE(k.sourceSec, 10);
    return { field: 1, wire: 2, value: inner };
  });
  return encodeProtobuf([{ field: 160, wire: 0, value: 0n }, ...msgs]);
}

/**
 * Build a retimed `Sm2TimeMap` keyed-dict from explicit keyframe points
 * `[{ recordSec, sourceSec }]` (ordered; the implicit (0,0) start is NOT included).
 * `sourceDurationSec` = LastValidYOffset; `recordDurationSec` defaults to the last keyframe's
 * recordSec (= XMax). This is the general (variable-speed) authoring entry point.
 */
function buildTimemap({ keyframes, sourceDurationSec, recordDurationSec, uniqueId }) {
  if (!keyframes || !keyframes.length) throw new Error('need at least one keyframe');
  const record = recordDurationSec == null ? keyframes[keyframes.length - 1].recordSec : recordDurationSec;
  const entries = [
    { key: 'YMin', type: T_DOUBLE, subType: 0, value: -1 },
    { key: 'YMax', type: T_DOUBLE, subType: 0, value: -1 },
    { key: 'XMax', type: T_DOUBLE, subType: 0, value: record },
    { key: 'UniqueId', type: T_STRING, subType: 0, value: uniqueId },
    { key: 'LastValidYOffset', type: T_DOUBLE, subType: 0, value: sourceDurationSec },
    { key: 'KeyframesBA', type: T_BYTES, subType: 0, value: _encodeKeyframes(keyframes).toString('hex') },
    { key: 'DbType', type: T_STRING, subType: 0, value: 'Sm2TimeMap' },
  ];
  return encodeKeyedDict({ hdr: 1, entries });
}

/**
 * Build a constant-speed retimed map for a clip whose source runs `sourceDurationSec`, played
 * at `speed` (0.5 = half speed → 2× longer). Single keyframe at the geometric line end.
 */
function buildConstantSpeedTimemap({ speed, sourceDurationSec, uniqueId, recordDurationSec }) {
  if (!(speed > 0)) throw new Error('speed must be > 0');
  // XMax is Resolve's frame-quantized record duration. Default to source/speed; pass the
  // exact value for byte-parity with a specific Resolve export.
  const record = recordDurationSec == null ? sourceDurationSec / speed : recordDurationSec;
  return buildTimemap({
    keyframes: [{ recordSec: record, sourceSec: record * speed }],
    sourceDurationSec, recordDurationSec: record, uniqueId,
  });
}

/**
 * r19-generation constant-speed Sm2TimeMap. Resolve 19.x encodes KeyframesBA
 * as a keyed-dict of keyed-dict keyframes ({interp,YOut,YIn,Y,XOut,XIn,X}),
 * NOT the R21 protobuf points — and 19 silently IGNORES the protobuf form on
 * import (measured: item read back at 100%). Shape harvested from a live
 * 19.1.3.7 XMEML retime and rebuilt byte-exact. The map spans the ENTIRE
 * source stretched by 1/speed (the clip's Start/Duration/In window into it):
 *   YMax = (sourceFrames-1)/fps          — full source extent, seconds
 *   XMax = (sourceFrames/speed - 1)/fps  — full retimed extent, seconds
 *   kf0 = (0,0); kf1 = (XMax, XMax*speed); linear (zero handles, interp 0)
 *
 * @param {object} p
 * @param {number} p.speed        - source/record ratio (0.5 = 50%). Forward only.
 * @param {number} p.sourceFrames - full source frame count at p.fps.
 * @param {number} [p.fps=24]
 * @param {string} p.uniqueId     - fresh uuid (bare, no braces).
 * @returns {Buffer}
 */
function buildConstantSpeedTimemapKeyed({ speed, sourceFrames, fps = 24, uniqueId, reverse = false }) {
  if (!(speed > 0)) throw new RangeError('buildConstantSpeedTimemapKeyed: speed must be > 0 (pass reverse:true for backwards)');
  if (!Number.isInteger(sourceFrames) || sourceFrames < 1) throw new TypeError('buildConstantSpeedTimemapKeyed: sourceFrames must be a positive integer');
  const YMax = (sourceFrames - 1) / fps;
  const XMax = (sourceFrames / speed - 1) / fps;
  const kf = (X, Y) => encodeKeyedDict({ hdr: 1, entries: [
    { key: 'interp', type: 0x02, subType: 0, value: 0 },
    { key: 'YOut', type: T_DOUBLE, subType: 0, value: 0 },
    { key: 'YIn', type: T_DOUBLE, subType: 0, value: 0 },
    { key: 'Y', type: T_DOUBLE, subType: 0, value: Y },
    { key: 'XOut', type: T_DOUBLE, subType: 0, value: 0 },
    { key: 'XIn', type: T_DOUBLE, subType: 0, value: 0 },
    { key: 'X', type: T_DOUBLE, subType: 0, value: X },
  ] }).toString('hex');
  // Reverse (harvested from a live 19.1.3.7 -100% XMEML retime): the SAME
  // envelope with the Y endpoints swapped — kf0=(0, YMax), kf1=(XMax, 0),
  // a descending line. Forward keeps kf1 Y = XMax*speed (harvest: +half-frame
  // convention falls out of the arithmetic, byte-exact either way).
  const keyframes = encodeKeyedDict({ hdr: 1, entries: [
    { key: '1', type: T_BYTES, subType: 0, value: reverse ? kf(XMax, 0) : kf(XMax, XMax * speed) },
    { key: '0', type: T_BYTES, subType: 0, value: reverse ? kf(0, YMax) : kf(0, 0) },
  ] }).toString('hex');
  return encodeKeyedDict({ hdr: 1, entries: [
    { key: 'YMax', type: T_DOUBLE, subType: 0, value: YMax },
    { key: 'XMax', type: T_DOUBLE, subType: 0, value: XMax },
    { key: 'UniqueId', type: T_STRING, subType: 0, value: uniqueId },
    { key: 'LastValidYOffset', type: T_DOUBLE, subType: 0, value: YMax },
    { key: 'KeyframesBA', type: T_BYTES, subType: 0, value: keyframes },
    { key: 'DbType', type: T_STRING, subType: 0, value: 'Sm2TimeMap' },
  ] });
}

/**
 * FREEZE frame map — r19 keyed form, harvested from a live 19.1.3.7 EDL
 * `M2 <reel> 000.0` import (E55, 2026-08-31; render-proven frozen by
 * freezedetect). A real freeze is NOT the flat frame-domain line the earlier
 * synthetic attempt used (that one reads back frozen but RENDERS moving —
 * the readback-blind divergence measured in E41-era work). The engine's
 * shape is a flat line in SECONDS with two extra conventions:
 *
 *   YMin = YMax = Y(kf0) = Y(kf1) = frozen source position in SECONDS
 *   XMax = 60000 (a fixed sentinel domain, not the clip length)
 *   LastValidYOffset = (sourceFrames-1)/fps  (whole-source extent, as always)
 *
 * The clip's <In> is EMPTY on a frozen item (record windowing does not
 * apply to a constant map). Byte-exact vs the harvest for equal inputs.
 */
function buildFreezeTimemapKeyed({ freezeFrame, sourceFrames, fps = 24, uniqueId }) {
  if (!Number.isInteger(freezeFrame) || freezeFrame < 0) throw new TypeError('buildFreezeTimemapKeyed: freezeFrame must be a non-negative integer (source frame to hold)');
  if (!Number.isInteger(sourceFrames) || sourceFrames < 1) throw new TypeError('buildFreezeTimemapKeyed: sourceFrames must be a positive integer');
  if (freezeFrame >= sourceFrames) throw new RangeError(`buildFreezeTimemapKeyed: freezeFrame ${freezeFrame} outside source (${sourceFrames} frames)`);
  const freezeSec = freezeFrame / fps;
  const XMAX_SENTINEL = 60000;
  const kf = (X, Y) => encodeKeyedDict({ hdr: 1, entries: [
    { key: 'interp', type: 0x02, subType: 0, value: 0 },
    { key: 'YOut', type: T_DOUBLE, subType: 0, value: 0 },
    { key: 'YIn', type: T_DOUBLE, subType: 0, value: 0 },
    { key: 'Y', type: T_DOUBLE, subType: 0, value: Y },
    { key: 'XOut', type: T_DOUBLE, subType: 0, value: 0 },
    { key: 'XIn', type: T_DOUBLE, subType: 0, value: 0 },
    { key: 'X', type: T_DOUBLE, subType: 0, value: X },
  ] }).toString('hex');
  const keyframes = encodeKeyedDict({ hdr: 1, entries: [
    { key: '1', type: T_BYTES, subType: 0, value: kf(XMAX_SENTINEL, freezeSec) },
    { key: '0', type: T_BYTES, subType: 0, value: kf(0, freezeSec) },
  ] }).toString('hex');
  return encodeKeyedDict({ hdr: 1, entries: [
    { key: 'YMin', type: T_DOUBLE, subType: 0, value: freezeSec },
    { key: 'YMax', type: T_DOUBLE, subType: 0, value: freezeSec },
    { key: 'XMax', type: T_DOUBLE, subType: 0, value: XMAX_SENTINEL },
    { key: 'UniqueId', type: T_STRING, subType: 0, value: uniqueId },
    { key: 'LastValidYOffset', type: T_DOUBLE, subType: 0, value: (sourceFrames - 1) / fps },
    { key: 'KeyframesBA', type: T_BYTES, subType: 0, value: keyframes },
    { key: 'DbType', type: T_STRING, subType: 0, value: 'Sm2TimeMap' },
  ] });
}

/**
 * VARIABLE-SPEED RAMP — piecewise-constant speed segments as a multi-keyframe
 * r19 keyed Sm2TimeMap. E63 (2026-08-31): the engine honors intermediate
 * keyframes with the SAME seconds-domain conventions as the constant maps —
 * a synthesized 3-keyframe 50%→100% ramp read back source 0..36 over 48
 * record frames AND rendered with exactly the predicted cadence (11/23
 * doubled frames in the 50% window, 0/24 at 100%). Record domain starts at
 * the cut head (clip In stays 0); srcIn bakes into the first keyframe's Y.
 *
 * @param {Array<{durationFrames:number, speed:number}>} segments - record-domain
 *   pieces, in order from the cut head; speeds are source/record multipliers.
 */
function buildRampTimemapKeyed({ segments, srcIn = 0, sourceFrames, fps = 24, uniqueId }) {
  if (!Array.isArray(segments) || segments.length < 2) throw new TypeError('buildRampTimemapKeyed: segments must be an array of >= 2 {durationFrames, speed} pieces (use speed/freeze for a single one)');
  if (!Number.isInteger(sourceFrames) || sourceFrames < 1) throw new TypeError('buildRampTimemapKeyed: sourceFrames must be a positive integer');
  if (!Number.isInteger(srcIn) || srcIn < 0) throw new TypeError('buildRampTimemapKeyed: srcIn must be a non-negative integer');
  const kf = (X, Y) => encodeKeyedDict({ hdr: 1, entries: [
    { key: 'interp', type: 0x02, subType: 0, value: 0 },
    { key: 'YOut', type: T_DOUBLE, subType: 0, value: 0 },
    { key: 'YIn', type: T_DOUBLE, subType: 0, value: 0 },
    { key: 'Y', type: T_DOUBLE, subType: 0, value: Y },
    { key: 'XOut', type: T_DOUBLE, subType: 0, value: 0 },
    { key: 'XIn', type: T_DOUBLE, subType: 0, value: 0 },
    { key: 'X', type: T_DOUBLE, subType: 0, value: X },
  ] }).toString('hex');
  let x = 0;
  let y = srcIn / fps;
  const points = [[x, y]];
  for (const [i, seg] of segments.entries()) {
    if (!Number.isInteger(seg.durationFrames) || seg.durationFrames < 1) throw new TypeError(`buildRampTimemapKeyed: segments[${i}].durationFrames must be a positive integer`);
    if (!(seg.speed > 0)) throw new RangeError(`buildRampTimemapKeyed: segments[${i}].speed must be > 0 (freeze/reverse segments are not authorable in a ramp)`);
    x += seg.durationFrames / fps;
    y += (seg.durationFrames * seg.speed) / fps;
    points.push([x, y]);
  }
  const sourceEnd = y * fps;
  if (sourceEnd > sourceFrames) {
    throw new RangeError(`buildRampTimemapKeyed: ramp consumes source frame ${Math.ceil(sourceEnd)} but the media has ${sourceFrames}`);
  }
  const entries = points.map(([X, Y], i) => ({ key: String(i), type: T_BYTES, subType: 0, value: kf(X, Y) })).reverse();
  const keyframes = encodeKeyedDict({ hdr: 1, entries }).toString('hex');
  const [XMax, YMax] = points[points.length - 1];
  return encodeKeyedDict({ hdr: 1, entries: [
    { key: 'YMax', type: T_DOUBLE, subType: 0, value: YMax },
    { key: 'XMax', type: T_DOUBLE, subType: 0, value: XMax },
    { key: 'UniqueId', type: T_STRING, subType: 0, value: uniqueId },
    { key: 'LastValidYOffset', type: T_DOUBLE, subType: 0, value: (sourceFrames - 1) / fps },
    { key: 'KeyframesBA', type: T_BYTES, subType: 0, value: keyframes },
    { key: 'DbType', type: T_STRING, subType: 0, value: 'Sm2TimeMap' },
  ] });
}

module.exports = {
  decodeTimemap, encodeTimemap, encodeRetimedTimemap,
  identityTimemap, buildConstantSpeedTimemap, buildConstantSpeedTimemapKeyed,
  buildFreezeTimemapKeyed, buildRampTimemapKeyed,
  buildTimemap, decodeProtobuf,
  TYPE_LINEAR,
};
