'use strict';

/**
 * Comparator tests — verified END-TO-END against the 4 committed golden verdicts
 * (golden_compare.json) and their reference/derived PNG pairs.
 *
 * The PNG pairs live under frames/ which is git-ignored raw material, so the
 * frame-dependent tests SKIP-IF-ABSENT. golden_compare.json itself is committed.
 * The dark_grade_match case is THE TRAP: raw PSNR ~9 but it MUST classify MATCH.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const pkg = require('../index');
const compare = require('../compare');

const DIR = pkg.reelFixtureDir();
const FRAMES = path.join(DIR, 'frames');
const HAVE_FRAMES = fs.existsSync(FRAMES) && fs.readdirSync(FRAMES).some((f) => f.endsWith('.png'));
const SKIP = HAVE_FRAMES ? false : 'frames/ absent (git-ignored raw material) — skipping';

const COMPARE = JSON.parse(fs.readFileSync(path.join(DIR, 'golden_compare.json'), 'utf8'));

test('comparator: alignment mode is a distinct entry point (stub), content-identity is default', async () => {
  // The alignment stub throws clearly (full impl is P4.5).
  assert.throws(() => compare.alignmentVerify(), /alignment verification mode not implemented/);
  // compareFrames routes by mode without needing to decode for the stub path.
  await assert.rejects(
    () => compare.compareFrames('ref', 'der', { mode: 'alignment' }),
    /alignment verification mode not implemented/,
  );
  // An unknown mode errors clearly.
  await assert.rejects(() => compare.compareFrames('ref', 'der', { mode: 'bogus' }), /unknown mode "bogus"/);
  // eslint-disable-next-line no-console
  console.log('[compare] alignment mode: distinct stub entry point, content-identity is default');
});

test('comparator: cross-correlation reports a correctable OFFSET, not WRONG (synthetic, client-free)', () => {
  // A structured pattern with high-frequency detail so a shift decorrelates at
  // zero offset but realigns at the true shift. Deterministic (no RNG).
  const W = 96;
  const H = 64;
  const a = new Float64Array(W * H);
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      a[y * W + x] = 0.5 + 0.25 * Math.sin(x * 0.7) * Math.cos(y * 0.5) + 0.2 * Math.sin((x + y) * 1.3);
    }
  }
  // Displace content by (sx,sy); the correction offset is the inverse (-sx,-sy).
  const sx = 5;
  const sy = -3;
  const b = new Float64Array(W * H);
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const srcx = x - sx;
      const srcy = y - sy;
      b[y * W + x] = srcx >= 0 && srcx < W && srcy >= 0 && srcy < H ? a[srcy * W + srcx] : 0;
    }
  }
  const out = compare.classify(a, b, { width: W, height: H });
  assert.equal(out.verdict, 'OFFSET', `expected OFFSET, got ${out.verdict} (zero-shift structure ${out.structure?.toFixed(3)})`);
  assert.equal(out.offset.dx, -sx, `dx ${out.offset.dx} should be ${-sx}`);
  assert.equal(out.offset.dy, -sy, `dy ${out.offset.dy} should be ${-sy}`);
  // eslint-disable-next-line no-console
  console.log(`[compare] cross-corr offset: applied (${sx},${sy}) -> correction (${out.offset.dx},${out.offset.dy}), verdict OFFSET`);
});

test('comparator: classifies all 4 golden verdicts (dark-grade trap = MATCH)', { skip: SKIP }, async () => {
  const results = [];
  for (const c of COMPARE.cases) {
    const refPath = path.join(DIR, c.reference);
    const derPath = path.join(DIR, c.derived);
    const out = await compare.compareFrames(refPath, derPath);
    results.push({ label: c.label, got: out.verdict, want: c.expected_verdict, structure: out.structure });
    assert.equal(
      out.verdict,
      c.expected_verdict,
      `${c.label}: got ${out.verdict} (structure ${out.structure?.toFixed(4)}), want ${c.expected_verdict}`,
    );
  }
  // Explicit trap assertion — the dark grade must MATCH despite the brightness gap.
  const dark = results.find((r) => r.label === 'dark_grade_match');
  assert.equal(dark.got, 'MATCH', 'dark_grade_match MUST classify MATCH (brightness trap)');
  // eslint-disable-next-line no-console
  console.log('[compare] 4/4 golden verdicts: ' + results.map((r) => `${r.label}=${r.got}`).join(', '));
});

test('comparator: brightness-robust — structure MATCHes the dark grade where full SSIM fails', { skip: SKIP }, async () => {
  const c = COMPARE.cases.find((x) => x.label === 'dark_grade_match');
  const size = compare.DEFAULT_SIZE;
  const ref = await compare.decodeGrayNormalized(path.join(DIR, c.reference), size);
  const der = await compare.decodeGrayNormalized(path.join(DIR, c.derived), size);
  const mask = compare.buildBurnInMask(size.width, size.height);
  const structure = compare.ssimStructure(ref.data, der.data, mask);
  const full = compare.ssimFull(ref.data, der.data, mask);
  // The brightness-robust structure score accepts the dark grade...
  assert.ok(structure >= 0.9, `structure ${structure.toFixed(4)} should be >= 0.90`);
  // ...while naive full SSIM (with the luminance term) FALSE-REJECTS it — the trap.
  assert.ok(full < 0.9, `full SSIM ${full.toFixed(4)} should be < 0.90 (proves the trap)`);
  // eslint-disable-next-line no-console
  console.log(`[compare] brightness trap: structure=${structure.toFixed(3)} (MATCH) vs full SSIM=${full.toFixed(3)} (would false-flag)`);
});

test('comparator: burn-in masking is applied and configurable, and raises the match score', { skip: SKIP }, async () => {
  const c = COMPARE.cases.find((x) => x.label === 'clean_match_hermes');
  const size = compare.DEFAULT_SIZE;
  const ref = await compare.decodeGrayNormalized(path.join(DIR, c.reference), size);
  const der = await compare.decodeGrayNormalized(path.join(DIR, c.derived), size);
  const noMask = new Uint8Array(size.width * size.height);
  const burnMask = compare.buildBurnInMask(size.width, size.height);
  // The default mask covers some pixels (the burn-in regions exist).
  let masked = 0;
  for (let i = 0; i < burnMask.length; i++) masked += burnMask[i];
  assert.ok(masked > 0, 'default burn-in mask must cover the TC/filename regions');
  const sMasked = compare.ssimStructure(ref.data, der.data, burnMask);
  const sUnmasked = compare.ssimStructure(ref.data, der.data, noMask);
  // Masking the burn-in (present in ref, absent in derived) improves the score.
  assert.ok(sMasked > sUnmasked, `masked ${sMasked.toFixed(4)} should beat unmasked ${sUnmasked.toFixed(4)}`);
  // Regions are configurable: a different region set changes the masked count.
  const custom = compare.buildBurnInMask(size.width, size.height, [{ x0: 0, y0: 0, x1: 1, y1: 0.1 }]);
  let customCount = 0;
  for (let i = 0; i < custom.length; i++) customCount += custom[i];
  assert.notEqual(customCount, masked, 'custom regions should change the mask coverage');
  // eslint-disable-next-line no-console
  console.log(`[compare] burn-in mask: ${masked} px masked; masked struct ${sMasked.toFixed(4)} > unmasked ${sUnmasked.toFixed(4)}`);
});

test('comparator: SSIM>=0.90 / PSNR>=25 thresholds separate clean from wrong', { skip: SKIP }, async () => {
  const size = compare.DEFAULT_SIZE;
  const mask = compare.buildBurnInMask(size.width, size.height);
  const t = compare.DEFAULT_THRESHOLDS;
  assert.equal(t.structure, 0.9);
  assert.equal(t.psnrNorm, 25);
  const score = async (label) => {
    const c = COMPARE.cases.find((x) => x.label === label);
    const ref = await compare.decodeGrayNormalized(path.join(DIR, c.reference), size);
    const der = await compare.decodeGrayNormalized(path.join(DIR, c.derived), size);
    return {
      structure: compare.ssimStructure(ref.data, der.data, mask),
      psnr: compare.psnrNormalized(ref.data, der.data, mask),
    };
  };
  const clean = await score('clean_match_hermes');
  const wrong = await score('genuine_wrong');
  assert.ok(clean.structure >= t.structure && clean.psnr >= t.psnrNorm, `clean above thresholds: ${JSON.stringify(clean)}`);
  assert.ok(wrong.structure < t.structure && wrong.psnr < t.psnrNorm, `wrong below thresholds: ${JSON.stringify(wrong)}`);
  // eslint-disable-next-line no-console
  console.log(`[compare] thresholds: clean struct ${clean.structure.toFixed(3)}/psnr ${clean.psnr.toFixed(1)} vs wrong ${wrong.structure.toFixed(3)}/${wrong.psnr.toFixed(1)}`);
});
