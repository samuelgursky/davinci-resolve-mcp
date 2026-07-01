'use strict';

/**
 * compare/metrics.js — the robust comparison metric (spec §8). PURE functions
 * over grayscale pixel buffers (Float64Array, values 0..1). No IO, no decode —
 * frames are decoded by an adapter (compare/decode.js) and passed in.
 *
 * The metric pitfalls all bit us once (spec §8 / non-negotiable #3), so the
 * metric is robust BY CONSTRUCTION:
 *  - mask burn-in regions before comparing,
 *  - compare STRUCTURE, not raw luma (brightness/contrast-invariant) — a dark
 *    temped grade must still MATCH its bright proxy,
 *  - cross-correlate to find residual X/Y offset (a correctable OFFSET, not
 *    WRONG content).
 */

/** Mean/std over the non-masked pixels (mask: 1 = ignore). */
function maskedStats(data, mask) {
  let n = 0;
  let sum = 0;
  for (let i = 0; i < data.length; i++) {
    if (mask && mask[i]) continue;
    sum += data[i];
    n += 1;
  }
  const mean = n ? sum / n : 0;
  let v = 0;
  for (let i = 0; i < data.length; i++) {
    if (mask && mask[i]) continue;
    const d = data[i] - mean;
    v += d * d;
  }
  return { mean, std: Math.sqrt(n ? v / n : 0), n };
}

/**
 * Build a burn-in mask (Uint8Array, 1 = masked-out). Regions are fractions of
 * width/height: {x0,y0,x1,y1} in [0,1]. Defaults cover a common review-render
 * template: a centered top timecode box + a bottom filename/TC strip.
 * Configurable per reference style.
 */
const DEFAULT_BURNIN_REGIONS = Object.freeze([
  { x0: 0, y0: 0.92, x1: 1, y1: 1 }, // bottom filename/TC strip
  { x0: 0.36, y0: 0.07, x1: 0.64, y1: 0.17 }, // centered top timecode
]);

function buildBurnInMask(width, height, regions = DEFAULT_BURNIN_REGIONS) {
  const mask = new Uint8Array(width * height);
  for (let y = 0; y < height; y++) {
    const fy = y / height;
    for (let x = 0; x < width; x++) {
      const fx = x / width;
      for (const r of regions) {
        if (fx >= r.x0 && fx <= r.x1 && fy >= r.y0 && fy <= r.y1) {
          mask[y * width + x] = 1;
          break;
        }
      }
    }
  }
  return mask;
}

/** Covariance of a,b over non-masked pixels, given their means. */
function maskedCovariance(a, b, ma, mb, mask) {
  let cov = 0;
  let n = 0;
  for (let i = 0; i < a.length; i++) {
    if (mask && mask[i]) continue;
    cov += (a[i] - ma) * (b[i] - mb);
    n += 1;
  }
  return n ? cov / n : 0;
}

const C2 = 0.03 ** 2;
const C1 = 0.01 ** 2;

/**
 * SSIM STRUCTURE component: (cov + C2/2) / (σa·σb + C2/2). Brightness- AND
 * contrast-invariant — this is the brightness-robust content-identity score.
 * Returns ~1 for the same picture even when one is a dark temped grade.
 */
function ssimStructure(a, b, mask) {
  const sa = maskedStats(a, mask);
  const sb = maskedStats(b, mask);
  const cov = maskedCovariance(a, b, sa.mean, sb.mean, mask);
  return (cov + C2 / 2) / (sa.std * sb.std + C2 / 2);
}

/**
 * FULL SSIM (luminance·contrast·structure) — NOT brightness-robust. Provided
 * only to demonstrate the trap: it false-rejects a dark grade. Production
 * verdicts use ssimStructure.
 */
function ssimFull(a, b, mask) {
  const sa = maskedStats(a, mask);
  const sb = maskedStats(b, mask);
  const cov = maskedCovariance(a, b, sa.mean, sb.mean, mask);
  const l = (2 * sa.mean * sb.mean + C1) / (sa.mean ** 2 + sb.mean ** 2 + C1);
  const c = (2 * sa.std * sb.std + C2) / (sa.std ** 2 + sb.std ** 2 + C2);
  const s = (cov + C2 / 2) / (sa.std * sb.std + C2 / 2);
  return l * c * s;
}

/**
 * Z-normalized PSNR (the spec's fallback threshold). Each image is normalized to
 * zero-mean/unit-std before the error, so a uniform brightness/contrast shift
 * doesn't penalize it. Peak set to 6 (±3σ covers the normalized signal).
 */
function psnrNormalized(a, b, mask) {
  const sa = maskedStats(a, mask);
  const sb = maskedStats(b, mask);
  if (sa.std === 0 || sb.std === 0) return 0;
  let se = 0;
  let n = 0;
  for (let i = 0; i < a.length; i++) {
    if (mask && mask[i]) continue;
    const za = (a[i] - sa.mean) / sa.std;
    const zb = (b[i] - sb.mean) / sb.std;
    se += (za - zb) ** 2;
    n += 1;
  }
  const mse = n ? se / n : 0;
  if (mse === 0) return Infinity;
  return 10 * Math.log10(6 ** 2 / mse);
}

/** Shift b by (dx,dy); out-of-bounds source pixels are masked (1). */
function shiftMask(mask, width, height, dx, dy) {
  const out = new Uint8Array(width * height);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const sx = x - dx;
      const sy = y - dy;
      if (sx < 0 || sx >= width || sy < 0 || sy >= height) {
        out[y * width + x] = 1;
      } else {
        out[y * width + x] = mask ? mask[sy * width + sx] || mask[y * width + x] : 0;
      }
    }
  }
  return out;
}

/** Structure score of a vs b shifted by (dx,dy). */
function structureAtShift(a, b, mask, width, height, dx, dy) {
  const bs = new Float64Array(width * height);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const sx = x - dx;
      const sy = y - dy;
      bs[y * width + x] = sx < 0 || sx >= width || sy < 0 || sy >= height ? 0 : b[sy * width + sx];
    }
  }
  return ssimStructure(a, bs, shiftMask(mask, width, height, dx, dy));
}

/** Box-downsample a Float64 image by an integer factor (averaging). */
function downsample(data, width, height, factor) {
  const ow = Math.floor(width / factor);
  const oh = Math.floor(height / factor);
  const out = new Float64Array(ow * oh);
  for (let y = 0; y < oh; y++) {
    for (let x = 0; x < ow; x++) {
      let sum = 0;
      let cnt = 0;
      for (let dy = 0; dy < factor; dy++) {
        const sy = y * factor + dy;
        if (sy >= height) break;
        for (let dx = 0; dx < factor; dx++) {
          const sx = x * factor + dx;
          if (sx >= width) break;
          sum += data[sy * width + sx];
          cnt += 1;
        }
      }
      out[y * ow + x] = cnt ? sum / cnt : 0;
    }
  }
  return { data: out, width: ow, height: oh };
}

/** Downsample a mask: a coarse cell is masked if ANY covered fine pixel is. */
function downsampleMask(mask, width, height, factor) {
  if (!mask) return null;
  const ow = Math.floor(width / factor);
  const oh = Math.floor(height / factor);
  const out = new Uint8Array(ow * oh);
  for (let y = 0; y < oh; y++) {
    for (let x = 0; x < ow; x++) {
      let m = 0;
      for (let dy = 0; dy < factor && !m; dy++) {
        const sy = y * factor + dy;
        if (sy >= height) break;
        for (let dx = 0; dx < factor; dx++) {
          const sx = x * factor + dx;
          if (sx >= width) break;
          if (mask[sy * width + sx]) { m = 1; break; }
        }
      }
      out[y * ow + x] = m;
    }
  }
  return out;
}

/** Brute-force the structure peak over a rectangular shift window (inclusive). */
function searchShiftWindow(a, b, mask, width, height, dxlo, dxhi, dylo, dyhi) {
  let best = { dx: 0, dy: 0, score: -Infinity };
  for (let dy = dylo; dy <= dyhi; dy++) {
    for (let dx = dxlo; dx <= dxhi; dx++) {
      const s = structureAtShift(a, b, mask, width, height, dx, dy);
      if (s > best.score) best = { dx, dy, score: s };
    }
  }
  return best;
}

/** Top-K scoring shifts over a window (descending). Used to seed pyramid refine. */
function topShifts(a, b, mask, width, height, dxlo, dxhi, dylo, dyhi, k) {
  const all = [];
  for (let dy = dylo; dy <= dyhi; dy++) {
    for (let dx = dxlo; dx <= dxhi; dx++) {
      all.push({ dx, dy, score: structureAtShift(a, b, mask, width, height, dx, dy) });
    }
  }
  all.sort((p, q) => q.score - p.score);
  return all.slice(0, k);
}

/**
 * Search integer X/Y shifts for the structure peak. Returns the best offset and
 * its score relative to the zero-shift baseline.
 *
 * For a wide search (maxShift > 16) a brute force costs (2·maxShift+1)² full-image
 * SSIM evals; instead we go COARSE→FINE on an image pyramid: score the down-sampled
 * copy over the full range, then refine at full resolution around the TOP-K coarse
 * candidates. Refining several candidates (not just the single coarse max) guards
 * against the coarse peak landing on an aliased false max — the full-res score
 * still decides. Same answer as brute force at ~1–2 orders of magnitude fewer
 * full-res evaluations. Small ranges stay exact brute force, preserving prior
 * behaviour for the sub-pixel-sensitive callers.
 */
function findOffset(a, b, mask, width, height, maxShift = 12) {
  const zero = ssimStructure(a, b, mask);
  const COARSE_THRESHOLD = 16;
  let best;
  if (maxShift <= COARSE_THRESHOLD || width < 64 || height < 64) {
    best = searchShiftWindow(a, b, mask, width, height, -maxShift, maxShift, -maxShift, maxShift);
  } else {
    const factor = 4;
    const da = downsample(a, width, height, factor);
    const db = downsample(b, width, height, factor);
    const dm = downsampleMask(mask, width, height, factor);
    const cMax = Math.ceil(maxShift / factor);
    const cands = topShifts(da.data, db.data, dm, da.width, da.height, -cMax, cMax, -cMax, cMax, 4);
    const r = factor + 1; // refine radius covers the downsample quantization
    best = { dx: 0, dy: 0, score: -Infinity };
    const seen = new Set();
    for (const c of cands) {
      const cx = c.dx * factor;
      const cy = c.dy * factor;
      const key = `${cx},${cy}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const local = searchShiftWindow(
        a, b, mask, width, height,
        Math.max(-maxShift, cx - r), Math.min(maxShift, cx + r),
        Math.max(-maxShift, cy - r), Math.min(maxShift, cy + r),
      );
      if (local.score > best.score) best = local;
    }
  }
  // The zero shift is always a candidate (a no-op offset must never lose to noise).
  if (zero >= best.score) best = { dx: 0, dy: 0, score: zero };
  return { ...best, zeroShiftScore: zero };
}

/** Resample b by factor s about the frame center into a w×h buffer (nearest). */
function scaleAbout(b, width, height, s) {
  const out = new Float64Array(width * height);
  const cx = (width - 1) / 2;
  const cy = (height - 1) / 2;
  for (let y = 0; y < height; y++) {
    const sy = Math.round((y - cy) / s + cy);
    for (let x = 0; x < width; x++) {
      const sx = Math.round((x - cx) / s + cx);
      out[y * width + x] = sx >= 0 && sx < width && sy >= 0 && sy < height ? b[sy * width + sx] : 0;
    }
  }
  return out;
}

/**
 * Scale-residual search: find the scale factor applied to b that best matches a
 * (structure peak). residual ≈ 1.0 means b is already at the right scale vs the
 * reference a; residual = 1.06 means b must be enlarged 6% to match (i.e. b is
 * ~6% too small). Coarse→fine over [lo,hi]. Returns { residual, score, atOneScore }.
 */
function findScale(a, b, mask, width, height, opts = {}) {
  const lo = opts.lo != null ? opts.lo : 0.85;
  const hi = opts.hi != null ? opts.hi : 1.18;
  const atOne = ssimStructure(a, b, mask);
  let best = { residual: 1, score: atOne };
  const scan = (from, to, step) => {
    for (let s = from; s <= to + 1e-9; s += step) {
      const score = ssimStructure(a, scaleAbout(b, width, height, s), mask);
      if (score > best.score) best = { residual: +s.toFixed(4), score };
    }
  };
  scan(lo, hi, 0.02);
  scan(Math.max(lo, best.residual - 0.02), Math.min(hi, best.residual + 0.02), 0.005);
  return { residual: best.residual, score: best.score, atOneScore: atOne };
}

/**
 * Coarse→fine 1D peak search over an integer domain [lo, hi], minimizing calls to
 * scoreAt (memoized) — for locating the best matching FRAME when each evaluation
 * is an expensive extract+decode+SSIM. Scans on `coarseStep`, then refines ±step
 * around the coarse peak down to step 1. Returns { x, score, evals }.
 *
 * scoreAt(x) -> number (higher is better; may be async). A linear scan of N
 * candidates costs N evals; this costs ~ N/coarseStep + 2·coarseStep, e.g. a
 * 300-frame window at coarseStep 8 ≈ 38+16 ≈ 54 evals instead of 300.
 */
async function coarseToFinePeak(scoreAt, lo, hi, coarseStep = 8) {
  const cache = new Map();
  const ev = async (x) => {
    if (x < lo || x > hi) return -Infinity;
    if (cache.has(x)) return cache.get(x);
    const s = await scoreAt(x);
    cache.set(x, s);
    return s;
  };
  let best = { x: lo, score: -Infinity };
  for (let x = lo; x <= hi; x += coarseStep) {
    const s = await ev(x);
    if (s > best.score) best = { x, score: s };
  }
  let step = Math.floor(coarseStep / 2);
  while (step >= 1) {
    const left = await ev(best.x - step);
    const right = await ev(best.x + step);
    if (left > best.score && left >= right) best = { x: best.x - step, score: left };
    else if (right > best.score) best = { x: best.x + step, score: right };
    else step = Math.floor(step / 2);
  }
  return { x: best.x, score: best.score, evals: cache.size };
}

const DEFAULT_THRESHOLDS = Object.freeze({ structure: 0.9, psnrNorm: 25, offsetGain: 0.15 });

/**
 * Classify a derived-vs-reference pair (content-identity mode).
 * verdict ∈ MATCH | OFFSET(dx,dy,ds) | WRONG | UNREADABLE.
 */
function classify(a, b, opts = {}) {
  const { width, height } = opts;
  const mask = opts.mask || null;
  const t = { ...DEFAULT_THRESHOLDS, ...(opts.thresholds || {}) };

  const sa = maskedStats(a, mask);
  const sb = maskedStats(b, mask);
  if (sa.std < 1e-6 || sb.std < 1e-6) {
    return { verdict: 'UNREADABLE', structure: null, psnrNorm: null, offset: null };
  }

  const structure = ssimStructure(a, b, mask);
  const psnrNorm = psnrNormalized(a, b, mask);
  if (structure >= t.structure || psnrNorm >= t.psnrNorm) {
    return { verdict: 'MATCH', structure, psnrNorm, offset: { dx: 0, dy: 0, ds: 0 } };
  }

  // Not a zero-shift match — is it a correctable X/Y offset?
  if (width && height) {
    const off = findOffset(a, b, mask, width, height, opts.maxShift || 12);
    if ((off.dx !== 0 || off.dy !== 0) && off.score >= t.structure && off.score - off.zeroShiftScore >= t.offsetGain) {
      return {
        verdict: 'OFFSET',
        structure,
        psnrNorm,
        offset: { dx: off.dx, dy: off.dy, ds: 0, scoreAtOffset: off.score },
      };
    }
  }

  return { verdict: 'WRONG', structure, psnrNorm, offset: null };
}

module.exports = {
  DEFAULT_BURNIN_REGIONS,
  DEFAULT_THRESHOLDS,
  maskedStats,
  buildBurnInMask,
  ssimStructure,
  ssimFull,
  psnrNormalized,
  findOffset,
  findScale,
  scaleAbout,
  structureAtShift,
  downsample,
  downsampleMask,
  searchShiftWindow,
  topShifts,
  coarseToFinePeak,
  classify,
};
