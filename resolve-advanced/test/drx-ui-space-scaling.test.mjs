// Calibration-backed test for the UNIFIED grade value space (space:'ui'|'drx') and the
// merge top-level-key fold. Factors verified live against Resolve 19 Studio (2026-07):
//   lift x2, gamma x4, gain x1, offset-delta x0.04, saturation /50.  See DRX-VALUE-SCALING.md.
// Default space is 'ui' (Resolve panel units); 'drx' is the raw-internal escape hatch.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { normalizeGradeParams, normalizeNewNode, UI_TO_DRX } from '../server/tools/drx.mjs';

const approx = (a, b, eps = 1e-9) => Math.abs(a - b) <= eps;

test('DEFAULT space is ui — wheels scale to panel units with no flag', () => {
  const out = normalizeGradeParams({ lift: { master: 0.05 }, gamma: { master: 0.05 }, offset: { g: -1.0 } });
  assert.ok(approx(out.lift.master, 0.1), `lift ${out.lift.master}`); // 0.05 x2
  assert.ok(approx(out.gamma.master, 0.2), `gamma ${out.gamma.master}`); // 0.05 x4
  assert.ok(approx(out.offset.g, -0.04), `offset ${out.offset.g}`); // -1 x0.04
});

test('explicit space:ui matches the default', () => {
  const a = normalizeGradeParams({ lift: { b: -0.05 }, gain: { master: 0.95 } });
  const b = normalizeGradeParams({ space: 'ui', lift: { b: -0.05 }, gain: { master: 0.95 } });
  assert.deepEqual(a.lift, b.lift);
  assert.ok(approx(b.lift.b, -0.1)); // x2
  assert.ok(approx(b.gain.master, 0.95)); // gain x1 (unchanged)
  assert.ok(!('space' in b));
});

test('space:drx takes raw DRX-internal units (no wheel scaling)', () => {
  const out = normalizeGradeParams({
    space: 'drx',
    lift: { master: -0.05 },
    gamma: { r: 0.1 },
    gain: { g: 0.95 },
    offset: { g: -0.042 },
  });
  assert.equal(out.lift.master, -0.05);
  assert.equal(out.gamma.r, 0.1);
  assert.equal(out.gain.g, 0.95);
  assert.equal(out.offset.g, -0.042);
});

test('saturation shares the unified axis: ui=0-100 as-is, drx=raw float pre-scaled x50', () => {
  // ui: caller passes panel 0-100; encoder divides by 50 downstream, so pass through.
  assert.equal(normalizeGradeParams({ space: 'ui', saturation: 52 }).saturation, 52);
  assert.equal(normalizeGradeParams({ saturation: 52 }).saturation, 52); // default ui
  // drx: caller passes raw float (~1.0 neutral); ×50 cancels the encoder's ÷50 → 1.04 stored.
  assert.ok(approx(normalizeGradeParams({ space: 'drx', saturation: 1.04 }).saturation, 52));
  assert.ok(approx(normalizeGradeParams({ space: 'drx', saturation: 1.0 }).saturation, 50)); // neutral
});

test('space:ui does not mutate the caller-supplied object', () => {
  const gp = { space: 'ui', lift: { master: 0.05 } };
  normalizeGradeParams(gp);
  assert.equal(gp.lift.master, 0.05, 'input lift.master must be untouched');
});

test('array and flat wheel forms normalize to nested {r,g,b,master}', () => {
  const arr = normalizeGradeParams({ space: 'drx', lift: [0.01, 0.02, 0.03, 0.04] });
  assert.deepEqual(arr.lift, { r: 0.01, g: 0.02, b: 0.03, master: 0.04 });
  const flat = normalizeGradeParams({ space: 'drx', liftR: 0.01, liftMaster: 0.04 });
  assert.equal(flat.lift.r, 0.01);
  assert.equal(flat.lift.master, 0.04);
  assert.ok(!('liftR' in flat));
});

test('merge newNode folds top-level wheel keys into params (was silently dropped)', () => {
  const n = normalizeNewNode({ label: 'Tone', space: 'drx', lift: { master: 0.03 }, saturation: 1.0 });
  assert.equal(n.label, 'Tone');
  assert.equal(n.params.lift.master, 0.03);
  assert.ok(approx(n.params.saturation, 50));
});

test('merge newNode honors space on top-level or nested params (default ui)', () => {
  const top = normalizeNewNode({ label: 'A', gamma: { master: 0.05 } }); // default ui
  assert.ok(approx(top.params.gamma.master, 0.2), `top ${top.params.gamma.master}`);
  const nested = normalizeNewNode({ label: 'B', params: { space: 'drx', gamma: { master: 0.05 } } });
  assert.ok(approx(nested.params.gamma.master, 0.05), `nested ${nested.params.gamma.master}`); // raw
});

test('UI_TO_DRX factor table matches the live calibration', () => {
  assert.deepEqual(UI_TO_DRX, { lift: 2, gamma: 4, gain: 1, offset: 0.04 });
});

test('soft-clip softness shares saturation axis: ui 0-100 as-is, drx pre-scaled x50', () => {
  // The encoder stores softClip*Soft as input/50 (like saturation). UI passes 0-100 through;
  // DRX must ×50 so a raw internal value round-trips. (Regression guard for the 2026-07 fix.)
  assert.equal(normalizeGradeParams({ space: 'ui', softClipHighSoft: 40 }).softClipHighSoft, 40);
  assert.equal(normalizeGradeParams({ softClipHighSoft: 40 }).softClipHighSoft, 40); // default ui
  assert.equal(normalizeGradeParams({ space: 'drx', softClipHighSoft: 0.8 }).softClipHighSoft, 40);
  assert.equal(normalizeGradeParams({ space: 'drx', softClipLowSoft: 0.6 }).softClipLowSoft, 30);
});
