/**
 * tone_curve_transfer (P1d) — match a clip's CONTRAST SHAPE to a reference via a nonlinear luma
 * TONE CURVE. Every other matcher is affine (gain+offset, 2 params); this is the one that can carry
 * an S-curve / filmic roll-off / soft profile a linear trim can't express.
 *
 * Math = histogram specification (CDF matching) reduced to a spline: build luma CDFs of source and
 * reference, then for control points x_i solve y_i = CDF_ref⁻¹(CDF_src(x_i)). The result is
 * monotonic by construction; we additionally clamp per-segment slope (anti-band/crush) and blend by
 * `strength` toward identity so it stays a ratifiable NUDGE, not a slam.
 *
 * Emit path: the DRX `y` (luma) custom curve, ROUND-TRIP ASSERTED (generate → parse →
 * node.customCurves.y within tolerance) — the same silent-lie guard the affine matchers use.
 *
 * Intent-aware (cross-craft review): a soft/low-contrast curve is often the MOOD, so gate: review,
 * honor shot-intent tags (exclude intentional/low-key), and default a conservative strength. LOCAL &
 * deterministic; no Resolve, no LLM. Display-referred frames only (like every matcher).
 */
import fs from 'node:fs';
import { createRequire } from 'node:module';
import { drxTool } from './tools/drx.mjs';
import { provenanceLabel } from './node-provenance.mjs';
import { shouldExcludeFromNeutralize } from './shot-intent.mjs';

const require = createRequire(import.meta.url);
function loadSharp() {
  try {
    return require('sharp');
  } catch {
    throw new Error("tone-curve-transfer needs the optional dep 'sharp'. Install: npm i sharp");
  }
}
const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
const lumaOf = (r, g, b) => 0.2126 * r + 0.7152 * g + 0.0722 * b;

// Default control-point x positions (0..1). Endpoints anchor identity (the generator drops them);
// the interior points are what the round-trip assert verifies.
export const DEFAULT_XS = [0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1];

/** 256-bin luma CDF (normalized 0..1) of a PNG. Returns null if unreadable. */
export async function measureLumaCDF(pngPath, opts = {}) {
  const sharp = loadSharp();
  const maxSide = opts.maxSide ?? 480;
  let data, ch, n;
  try {
    const out = await sharp(pngPath).resize(maxSide, maxSide, { fit: 'inside', kernel: 'nearest' }).raw().toBuffer({ resolveWithObject: true });
    data = out.data;
    ch = out.info.channels;
    n = Math.floor(data.length / ch);
  } catch {
    return null;
  }
  if (!n) return null;
  const hist = new Array(256).fill(0);
  for (let i = 0; i < data.length; i += ch) {
    const y = clamp(Math.round(lumaOf(data[i], data[i + 1], data[i + 2])), 0, 255);
    hist[y]++;
  }
  const cdf = new Array(256);
  let acc = 0;
  for (let i = 0; i < 256; i++) {
    acc += hist[i];
    cdf[i] = acc / n;
  }
  return cdf;
}

const cdfAt = (cdf, x) => cdf[clamp(Math.round(x * 255), 0, 255)];
/** CDF⁻¹: smallest luma level (0..1) whose CDF ≥ p. */
function invCdf(cdf, p) {
  for (let j = 0; j < 256; j++) if (cdf[j] >= p) return j / 255;
  return 1;
}

/**
 * Compute a monotonic, slope-clamped, strength-blended tone curve mapping source→reference.
 * @returns {Array<{x:number,y:number}>} control points including endpoints.
 */
export function computeToneCurve(srcCdf, refCdf, opts = {}) {
  const xs = opts.xs || DEFAULT_XS;
  const strength = opts.strength ?? 0.8;
  const maxSlope = opts.maxSlope ?? 3;
  const minSlope = opts.minSlope ?? 0; // never invert (monotonic non-decreasing)
  const raw = xs.map((x) => ({ x, y: invCdf(refCdf, cdfAt(srcCdf, x)) }));
  // Anchor endpoints to identity (a tone curve keeps black at black / white at white).
  raw[0] = { x: 0, y: 0 };
  raw[raw.length - 1] = { x: 1, y: 1 };
  // Blend toward identity by strength.
  for (const p of raw) p.y = clamp(p.x * (1 - strength) + p.y * strength, 0, 1);
  // Enforce monotonic + slope clamp left→right.
  for (let i = 1; i < raw.length; i++) {
    const dx = raw[i].x - raw[i - 1].x || 1e-6;
    let y = Math.max(raw[i].y, raw[i - 1].y); // non-decreasing
    const slope = (y - raw[i - 1].y) / dx;
    if (slope > maxSlope) y = raw[i - 1].y + maxSlope * dx;
    if (slope < minSlope) y = raw[i - 1].y + minSlope * dx;
    raw[i].y = clamp(y, 0, 1);
  }
  raw[raw.length - 1].y = 1; // re-anchor white after clamping
  return raw.map((p) => ({ x: +p.x.toFixed(4), y: +p.y.toFixed(4) }));
}

/** Generate a luma (y) tone-curve DRX and THROW if the interior points don't round-trip. */
export async function generateAssertedYCurveDRX(points, label, outPath, tol = 0.01) {
  await drxTool.handler({ action: 'generate', args: { gradeParams: { customCurves: { y: points } }, metadata: { label }, outputPath: outPath } });
  const back = await drxTool.handler({ action: 'parse', args: { content: fs.readFileSync(outPath, 'utf8') } });
  const decoded = (back.nodes || []).map((n) => n.customCurves && n.customCurves.y).find((y) => Array.isArray(y) && y.length) || [];
  const interior = points.filter((p) => p.x > 0.0001 && p.x < 0.9999);
  // A non-identity curve must decode SOME interior points; each decoded point must match an input within tol.
  const nonIdentity = interior.some((p) => Math.abs(p.y - p.x) > 0.002);
  if (nonIdentity && !decoded.length) throw new Error(`round-trip assert FAILED: ${label} tone curve decoded EMPTY`);
  for (const d of decoded) {
    const match = interior.find((p) => Math.abs(p.x - d.x) < 0.02);
    if (match && Math.abs(match.y - d.y) > tol) throw new Error(`round-trip assert FAILED: ${label} point x=${d.x} y=${match.y}→${d.y} exceeds tol ${tol}`);
  }
  return outPath;
}

/**
 * @param {Array<{id, png, reference?}>} clips per-clip reference OR shared opts.reference
 * @param {{outDir, reference?, strength?, maxSlope?, xs?, intentTags?:Object, nearIdentity?:number, overCorrWarn?:number}} opts
 *   intentTags: { [clipId]: string[] } — clips tagged intentional are skipped (a curve is a look decision).
 */
export async function computeToneCurveTransfer(clips, opts = {}) {
  if (!opts.outDir) throw new Error('opts.outDir required');
  fs.mkdirSync(opts.outDir, { recursive: true });
  const nearIdentity = opts.nearIdentity ?? 0.01;
  const overCorrWarn = opts.overCorrWarn ?? 0.3;
  const intentTags = opts.intentTags || {};

  const grades = [];
  const warnings = [];
  const skipped = [];
  const report = {};

  const refCache = new Map();
  async function refCdf(refPath) {
    if (refCache.has(refPath)) return refCache.get(refPath);
    const c = await measureLumaCDF(refPath, opts);
    refCache.set(refPath, c);
    return c;
  }

  for (const c of clips) {
    if (shouldExcludeFromNeutralize(intentTags[c.id])) {
      skipped.push({ id: c.id, reason: 'intent-tagged (intentional look) — a tone curve is a look decision, excluded' });
      continue;
    }
    const refPath = c.reference || opts.reference;
    if (!refPath) {
      skipped.push({ id: c.id, reason: 'no reference provided' });
      continue;
    }
    const ref = await refCdf(refPath);
    if (!ref) {
      skipped.push({ id: c.id, reason: 'reference unreadable' });
      warnings.push(`${c.id}: reference '${refPath}' unreadable — skipped, not faked.`);
      continue;
    }
    const src = await measureLumaCDF(c.png, opts);
    if (!src) {
      skipped.push({ id: c.id, reason: 'target unreadable' });
      continue;
    }
    const points = computeToneCurve(src, ref, opts);
    const maxDelta = Math.max(...points.map((p) => Math.abs(p.y - p.x)));
    if (maxDelta < nearIdentity) {
      skipped.push({ id: c.id, reason: 'tone already matches the reference (near-identity curve)', maxDeltaPct: +(100 * maxDelta).toFixed(2) });
      continue;
    }
    const drxPath = `${opts.outDir}/${c.id}_tonecurve.drx`;
    await generateAssertedYCurveDRX(
      points,
      provenanceLabel('tone_curve_transfer', { source: `ref:${refPath.split('/').pop()}`, gist: `Δ${(100 * maxDelta).toFixed(0)}%` }),
      drxPath,
    );
    grades.push({ id: c.id, points, maxDeltaPct: +(100 * maxDelta).toFixed(2), drxPath });
    report[c.id] = { maxDeltaPct: +(100 * maxDelta).toFixed(2), points: points.length };
    if (maxDelta > overCorrWarn)
      warnings.push(
        `${c.id}: large tone shift ${(100 * maxDelta).toFixed(0)}% — the reference contrast may not fit this shot; review (a curve is a look decision).`,
      );
  }
  return { grades, report, warnings, skipped };
}
