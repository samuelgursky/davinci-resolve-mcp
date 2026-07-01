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
function _decodeKeyframes(hex) {
  if (hex == null) return [];
  const fields = decodeProtobuf(hex);
  return fields
    .filter((f) => f.field === 1 && f.wire === 2)
    .map((f) => ({ recordSec: f.value.readDoubleLE(1), sourceSec: f.value.readDoubleLE(10) }));
}

/** Per-segment speeds from the keyframe points (slope Δsource/Δrecord); starts at (0,0). */
function _segments(keyframes) {
  const pts = [{ recordSec: 0, sourceSec: 0 }, ...keyframes];
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
    const keyframes = _decodeKeyframes(get('KeyframesBA'));
    const segments = _segments(keyframes);
    // The EXACT speed lives in the keyframe ratios (source/record per segment); XMax and
    // LastValidYOffset are frame-quantized. `speed` is the first segment's (whole clip if 1 kf);
    // `segments` carries the full variable-speed ramp.
    const speed = segments.length ? segments[0].speed : sourceDurationSec / recordDurationSec;
    const variable = segments.length > 1;
    return {
      form: 'retimed', variable, speed, segments, keyframes,
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

module.exports = {
  decodeTimemap, encodeTimemap, encodeRetimedTimemap,
  identityTimemap, buildConstantSpeedTimemap, buildTimemap, decodeProtobuf,
  TYPE_LINEAR,
};
