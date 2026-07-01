/**
 * scope_read (Layer-3 substrate) — the shared frame→stats measurement primitive.
 *
 * ONE deterministic downsample + one pass over a display-referred PNG that produces
 * everything the grading catalog and a human colorist need from a frame:
 *   - per-channel {mean,min,max,p1,p50,p99} (the matchers consume the relevant stat)
 *   - luma stats (Rec.709 weighting)
 *   - a saturation histogram (HSV S) + mean saturation
 *   - COLORIST READOUTS a human acts on: RGB-parade balance delta, vectorscope skin-line
 *     angle/distance, per-channel black-balance point, %clip / %crush
 *   - deterministic INTENT SIGNALS (L1): low-key? monochromatic? dominant hue? contrast?
 *     — these feed shot-intent tagging (shot-intent.mjs); the conversational L2 review is
 *     the CLIENT's job, never this tool's.
 *
 * LOCAL & deterministic: sharp raw pixels → arithmetic. No Resolve, no LLM. Display-referred
 * frames only (Rec.709/sRGB) — the skin-line + saturation readouts assume it; a LOG frame is
 * flat/desaturated and its readouts are meaningless (guarded by callers that gate on skin).
 *
 * This is a MEASURE-only primitive (gate: none) — it decides nothing, emits no grade.
 */
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
function loadSharp() {
  try {
    return require('sharp');
  } catch {
    throw new Error("scope-read needs the optional dep 'sharp' (frame stats). Install: npm i sharp");
  }
}

const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
const mean = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0);

/** Percentile of a pre-sorted ascending array (nearest-rank, deterministic). */
function percentile(sorted, p) {
  if (!sorted.length) return 0;
  const idx = clamp(Math.round((p / 100) * (sorted.length - 1)), 0, sorted.length - 1);
  return sorted[idx];
}

// The vectorscope flesh-tone ("I") line — where healthy skin clusters regardless of tone.
// Matching HUE toward this line (not RGB-mean equality) is the correct skin move; chasing a
// single skin *mean* across cameras is the calibrated-for-white-skin trap (cross-craft review).
export const SKIN_LINE_DEG = 123;

// Rec.709 luma + chroma (full-range coefficients). Scale-consistent for angle/distance.
const lumaOf = (r, g, b) => 0.2126 * r + 0.7152 * g + 0.0722 * b;
const cbOf = (r, g, b, y) => (b - y) / 1.8556;
const crOf = (r, g, b, y) => (r - y) / 1.5748;

/** HSV saturation of an 8-bit RGB pixel (0..1). */
function satOf(r, g, b) {
  const mx = Math.max(r, g, b);
  const mn = Math.min(r, g, b);
  return mx ? (mx - mn) / mx : 0;
}

/** HSV hue in degrees (0..360) of an 8-bit RGB pixel; -1 for achromatic. */
function hueOf(r, g, b) {
  const mx = Math.max(r, g, b);
  const mn = Math.min(r, g, b);
  const d = mx - mn;
  if (d === 0) return -1;
  let h;
  if (mx === r) h = ((g - b) / d) % 6;
  else if (mx === g) h = (b - r) / d + 2;
  else h = (r - g) / d + 4;
  h *= 60;
  return h < 0 ? h + 360 : h;
}

// Import the skin gate so the skin-line readout uses the SAME classifier as skin_match
// (one source of truth for "what is a skin pixel").
import { isSkin } from './skin-match.mjs';

/**
 * Read raw downsampled pixels from a PNG, optionally cropped to a fractional rect.
 * @returns {Promise<{data:Buffer, ch:number, width:number, height:number}|null>}
 */
async function readPixels(pngPath, opts = {}) {
  const sharp = loadSharp();
  const maxSide = opts.maxSide ?? 480;
  try {
    let img = sharp(pngPath);
    if (opts.rect) {
      const meta = await img.metadata();
      const W = meta.width || 0;
      const H = meta.height || 0;
      const x = clamp(Math.round(opts.rect.x * W), 0, Math.max(0, W - 1));
      const y = clamp(Math.round(opts.rect.y * H), 0, Math.max(0, H - 1));
      const w = clamp(Math.round(opts.rect.w * W), 1, W - x);
      const h = clamp(Math.round(opts.rect.h * H), 1, H - y);
      img = sharp(pngPath).extract({ left: x, top: y, width: w, height: h });
    }
    const out = await img.resize(maxSide, maxSide, { fit: 'inside', kernel: 'nearest' }).raw().toBuffer({ resolveWithObject: true });
    return { data: out.data, ch: out.info.channels, width: out.info.width, height: out.info.height };
  } catch {
    return null;
  }
}

/**
 * Full frame readout. Single downsample + single pass.
 * @param {string} pngPath display-referred PNG
 * @param {{rect?:{x,y,w,h}, maxSide?:number, satBins?:number, skinOpts?:object}} opts
 * @returns {Promise<object|null>} null if unreadable (skip-not-fake).
 */
export async function scopeRead(pngPath, opts = {}) {
  const px = await readPixels(pngPath, opts);
  if (!px) return null;
  const { data, ch } = px;
  const nTotal = Math.floor(data.length / ch);
  if (!nTotal) return null;
  const satBins = opts.satBins ?? 16;

  const R = new Array(nTotal);
  const G = new Array(nTotal);
  const B = new Array(nTotal);
  const L = new Array(nTotal);
  const satHist = new Array(satBins).fill(0);
  let satSum = 0;
  // Skin-gated chroma accumulation (vectorscope skin-line readout).
  let skinCb = 0,
    skinCr = 0,
    nSkin = 0;
  let at0 = 0,
    at255 = 0;
  // Hue mass for dominant-hue / monochromatic signals (coarse 12-bucket wheel over chromatic px).
  const HUE_BUCKETS = 12;
  const hueMass = new Array(HUE_BUCKETS).fill(0);
  let nChromatic = 0;

  let pi = 0;
  for (let i = 0; i < data.length; i += ch, pi++) {
    const r = data[i],
      g = data[i + 1],
      b = data[i + 2];
    R[pi] = r;
    G[pi] = g;
    B[pi] = b;
    const y = lumaOf(r, g, b);
    L[pi] = y;
    const s = satOf(r, g, b);
    satSum += s;
    satHist[clamp(Math.floor(s * satBins), 0, satBins - 1)]++;
    if (r === 0 || g === 0 || b === 0) at0++;
    if (r === 255 || g === 255 || b === 255) at255++;
    if (isSkin(r, g, b, opts.skinOpts || {})) {
      skinCb += cbOf(r, g, b, y);
      skinCr += crOf(r, g, b, y);
      nSkin++;
    }
    const h = hueOf(r, g, b);
    if (h >= 0 && s > 0.15) {
      // ignore near-gray pixels when judging dominant hue
      hueMass[clamp(Math.floor((h / 360) * HUE_BUCKETS), 0, HUE_BUCKETS - 1)] += s;
      nChromatic++;
    }
  }

  R.sort((a, b) => a - b);
  G.sort((a, b) => a - b);
  B.sort((a, b) => a - b);
  L.sort((a, b) => a - b);
  const chStats = (arr) => ({
    mean: +mean(arr).toFixed(3),
    min: arr[0],
    max: arr[arr.length - 1],
    p1: percentile(arr, 1),
    p50: percentile(arr, 50),
    p99: percentile(arr, 99),
  });
  const channels = { r: chStats(R), g: chStats(G), b: chStats(B) };
  const luma = chStats(L);

  // ── colorist readouts ────────────────────────────────────────────────
  // RGB-parade balance delta: how far apart the channel means sit (a neutral frame → ~0).
  const means = [channels.r.mean, channels.g.mean, channels.b.mean];
  const parade = {
    rg: +(channels.r.mean - channels.g.mean).toFixed(3),
    gb: +(channels.g.mean - channels.b.mean).toFixed(3),
    rb: +(channels.r.mean - channels.b.mean).toFixed(3),
    spread: +(Math.max(...means) - Math.min(...means)).toFixed(3),
  };
  // Per-channel black-balance point (the p1 shadow value) + shadow cast spread.
  const blacks = [channels.r.p1, channels.g.p1, channels.b.p1];
  const blackBalance = {
    r: channels.r.p1,
    g: channels.g.p1,
    b: channels.b.p1,
    castSpread: Math.max(...blacks) - Math.min(...blacks),
  };
  // Vectorscope skin-line readout (only meaningful with skin pixels).
  let skinLine = null;
  if (nSkin > 0) {
    const cb = skinCb / nSkin;
    const cr = skinCr / nSkin;
    const angle = (Math.atan2(cr, cb) * 180) / Math.PI;
    const distance = Math.hypot(cb, cr);
    skinLine = {
      angleDeg: +angle.toFixed(2),
      distance: +distance.toFixed(2),
      deviationDeg: +(angle - SKIN_LINE_DEG).toFixed(2),
      skinFrac: +(nSkin / nTotal).toFixed(4),
    };
  }
  const clipPct = +((100 * at255) / nTotal).toFixed(3);
  const crushPct = +((100 * at0) / nTotal).toFixed(3);
  const meanSat = +(satSum / nTotal).toFixed(4);

  // ── deterministic intent SIGNALS (L1) ────────────────────────────────
  // Dominant hue: bucket with the most saturation-weighted mass; concentration ratio.
  let domIdx = -1,
    domMass = 0,
    totalMass = 0;
  for (let k = 0; k < hueMass.length; k++) {
    totalMass += hueMass[k];
    if (hueMass[k] > domMass) {
      domMass = hueMass[k];
      domIdx = k;
    }
  }
  const hueConcentration = totalMass ? +(domMass / totalMass).toFixed(3) : 0;
  const dominantHueDeg = domIdx >= 0 ? Math.round(((domIdx + 0.5) / hueMass.length) * 360) : -1;
  const contrastRange = luma.p99 - luma.p1;
  const signals = {
    lumaMedian: luma.p50,
    contrastRange,
    meanSat,
    dominantHueDeg,
    hueConcentration,
    chromaticFrac: +(nChromatic / nTotal).toFixed(4),
    // low-key: mostly shadow with the median down in the low third
    lowKey: luma.p50 < 70 && percentile(L, 75) < 128,
    // monochromatic: chromatic pixels cluster in one hue bucket AND overall sat is modest
    monochromatic: hueConcentration >= 0.6 && meanSat > 0.08,
    // near-neutral: little saturation anywhere
    lowSaturation: meanSat < 0.06,
    highContrast: contrastRange > 200,
    lowContrast: contrastRange < 60,
  };

  return {
    channels,
    luma,
    parade,
    blackBalance,
    skinLine,
    satHistogram: satHist,
    meanSat,
    clipPct,
    crushPct,
    signals,
    nTotal,
  };
}
