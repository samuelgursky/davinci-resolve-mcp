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
