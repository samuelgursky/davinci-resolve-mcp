const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const JSZip = require('jszip');
const {
  decodeTimemap, encodeTimemap, encodeRetimedTimemap,
  identityTimemap, buildConstantSpeedTimemap, buildTimemap,
} = require('../media-timemap');

const FIXTURE = 'docs/design/drp-drx-drt-closeout-harness/fixtures/canary-resolve21.drp';
// Live-captured retimes (Sm2TimeMap keyed-dicts) from real Resolve 21 exports.
const RETIMED_50 = fs.readFileSync(
  require('path').join(__dirname, 'fixtures', 'retimed-timemap-50pct.hex'), 'utf8').trim();
// Dynamic ramp: 50% for the first segment, then a speed point, then 200%.
const RETIMED_DYNAMIC = fs.readFileSync(
  require('path').join(__dirname, 'fixtures', 'retimed-timemap-dynamic.hex'), 'utf8').trim();

async function grab(tag) {
  const zip = await JSZip.loadAsync(fs.readFileSync(FIXTURE));
  for (const name of Object.keys(zip.files)) {
    if (!name.endsWith('.xml')) continue;
    const x = await zip.files[name].async('string');
    const m = x.match(new RegExp(`<${tag}>([0-9a-f]+)</${tag}>`));
    if (m) return m[1];
  }
  return null;
}

test('decodeTimemap reads the identity (1x) compact form', async (t) => {
  if (!fs.existsSync(FIXTURE)) { t.skip('fixture missing'); return; }
  const { form, type, seconds } = decodeTimemap(await grab('MediaTimemapBA'));
  assert.strictEqual(form, 'identity');
  assert.strictEqual(type, 2);
  assert.strictEqual(seconds.length, 5);
  // 152.6525 s * 29.97 fps == 4575 (canary clip last-frame index).
  assert.strictEqual(Math.round(seconds[0] * (30000 / 1001)), 4575);
  assert.strictEqual(seconds[1], 0);
});

test('encodeTimemap round-trips the identity blob byte-for-byte', async (t) => {
  if (!fs.existsSync(FIXTURE)) { t.skip('fixture missing'); return; }
  const hex = await grab('MediaTimemapBA');
  assert.strictEqual(encodeTimemap(decodeTimemap(hex)).toString('hex'), hex);
});

test('decodeTimemap handles the degenerate (title) 9-byte form', () => {
  const { form, type, seconds } = decodeTimemap('024013d55555555555');
  assert.strictEqual(form, 'identity');
  assert.strictEqual(type, 2);
  assert.strictEqual(seconds.length, 1);
});

test('decodeTimemap reads the retimed Sm2TimeMap form + exact keyframe speed', () => {
  const d = decodeTimemap(RETIMED_50);
  assert.strictEqual(d.form, 'retimed');
  // Exact speed comes from the keyframe ratio: 0.5 (the dialog input), not the
  // frame-quantized LastValidYOffset/XMax (≈0.49996).
  assert.strictEqual(d.speed, 0.5);
  assert.ok(Math.abs(d.sourceDurationSec - 152.6525) < 1e-3);
  assert.ok(Math.abs(d.recordDurationSec - 305.33) < 1e-2);
});

test('encodeRetimedTimemap round-trips the live 50% blob byte-for-byte', () => {
  const d = decodeTimemap(RETIMED_50);
  assert.strictEqual(encodeRetimedTimemap(d).toString('hex'), RETIMED_50);
});

test('buildConstantSpeedTimemap rebuilds the exact captured 50% blob', () => {
  // Given Resolve's frame-quantized XMax, everything else (keyframe endpoint) is derived.
  const built = buildConstantSpeedTimemap({
    speed: 0.5,
    sourceDurationSec: 152.6525,
    recordDurationSec: 305.33006666666665,
    uniqueId: '346625ac-b0e3-4768-8418-276483860709',
  });
  assert.strictEqual(built.toString('hex'), RETIMED_50);
});

test('buildConstantSpeedTimemap default (nominal XMax) decodes to the exact speed', () => {
  const built = buildConstantSpeedTimemap({
    speed: 0.5, sourceDurationSec: 152.6525, uniqueId: '346625ac-b0e3-4768-8418-276483860709',
  });
  const d = decodeTimemap(built);
  assert.strictEqual(d.form, 'retimed');
  assert.strictEqual(d.speed, 0.5);
});

test('decodeTimemap reads a DYNAMIC ramp: per-segment speeds 50% then 200%', () => {
  const d = decodeTimemap(RETIMED_DYNAMIC);
  assert.strictEqual(d.form, 'retimed');
  assert.strictEqual(d.variable, true);
  assert.strictEqual(d.keyframes.length, 2);
  assert.strictEqual(d.segments.length, 2);
  assert.ok(Math.abs(d.segments[0].speed - 0.5) < 1e-3, `seg0 ${d.segments[0].speed}`);
  assert.ok(Math.abs(d.segments[1].speed - 2.0) < 1e-3, `seg1 ${d.segments[1].speed}`);
});

test('encodeRetimedTimemap round-trips the dynamic ramp byte-for-byte', () => {
  const d = decodeTimemap(RETIMED_DYNAMIC);
  assert.strictEqual(encodeRetimedTimemap(d).toString('hex'), RETIMED_DYNAMIC);
});

test('buildTimemap rebuilds the captured dynamic ramp byte-for-byte', () => {
  const d = decodeTimemap(RETIMED_DYNAMIC);
  const built = buildTimemap({
    keyframes: d.keyframes,
    sourceDurationSec: d.sourceDurationSec,
    recordDurationSec: d.recordDurationSec,
    uniqueId: d.entries.find((e) => e.key === 'UniqueId').value,
  });
  assert.strictEqual(built.toString('hex'), RETIMED_DYNAMIC);
});

test('identityTimemap builds a [02][end,0,end,0,end] map', () => {
  const b = decodeTimemap(identityTimemap(4576, 30000 / 1001));
  assert.strictEqual(b.form, 'identity');
  assert.strictEqual(b.seconds.length, 5);
  assert.strictEqual(Math.round(b.seconds[0] * (30000 / 1001)), 4575);
});

// --- Reverse maps: the origin is NOT always (0,0) ---------------------------
// Captured from a clip reversed via EDL M2 / OTIO negative time_scalar and
// exported by DaVinci Resolve Studio 21.0.4.5. Two things here used to break:
//   1. Each keyframe point omits whichever of recordSec/sourceSec is 0 —
//      protobuf default-omission — so the old fixed-offset reader
//      (readDoubleLE(1) / readDoubleLE(10)) threw "offset out of range".
//   2. The starting source offset is a TOP-LEVEL field 2 double. Assuming a
//      (0,0) origin made a reverse decode as speed 0 — a plausible wrong
//      number rather than an error, which is the worse failure.
const REVERSED_KEYFRAMES_BA = '800a09115655555555d517400a09095655555555d51740';

function reversedMapHex() {
  const { encodeKeyedDict } = require('../keyed-dict');
  const T_DOUBLE = 6; const T_STRING = 10; const T_BYTES = 12;
  return encodeKeyedDict({
    hdr: 1,
    entries: [
      { key: 'YMin', type: T_DOUBLE, subType: 0, value: -1 },
      { key: 'YMax', type: T_DOUBLE, subType: 0, value: -1 },
      { key: 'XMax', type: T_DOUBLE, subType: 0, value: 5.958333333333334 },
      { key: 'UniqueId', type: T_STRING, subType: 0, value: '4dbe3e42-ab1e-4b93-8118-67fdc376c962' },
      { key: 'LastValidYOffset', type: T_DOUBLE, subType: 0, value: 5.958333333333333 },
      { key: 'KeyframesBA', type: T_BYTES, subType: 0, value: REVERSED_KEYFRAMES_BA },
      { key: 'DbType', type: T_STRING, subType: 0, value: 'Sm2TimeMap' },
    ],
  }).toString('hex');
}

test('decodeTimemap: a reversed map decodes without throwing', () => {
  assert.doesNotThrow(() => decodeTimemap(reversedMapHex()));
});

test('decodeTimemap: a reversed map reports NEGATIVE speed, not 0', () => {
  const d = decodeTimemap(reversedMapHex());
  assert.equal(d.segments.length, 1);
  assert.equal(d.segments[0].speed, -1);
  assert.ok(d.segments[0].speed < 0, 'reverse must not decode as speed 0');
});

test('_decodeKeyframePoint: a point may omit either value (protobuf default 0)', () => {
  // sourceSec-only and recordSec-only points both appear in one real reversed map.
  const d = decodeTimemap(reversedMapHex());
  assert.equal(d.recordDurationSec, 5.958333333333334);
  assert.equal(d.sourceDurationSec, 5.958333333333333);
});

test('forward maps are unaffected by the origin fix', () => {
  const fwd = buildTimemap({
    keyframes: [{ recordSec: 2, sourceSec: 1 }, { recordSec: 4, sourceSec: 5 }],
    sourceDurationSec: 6, recordDurationSec: 4, uniqueId: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
  });
  const d = decodeTimemap(fwd.toString('hex'));
  assert.equal(d.variable, true);
  assert.deepEqual(d.segments.map((s) => s.speed), [0.5, 2]);
});
