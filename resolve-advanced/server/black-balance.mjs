/**
 * black_balance (P1d) — neutralize a SHADOW cast specifically. Where white_balance_match
 * balances a mid/highlight neutral patch, this operates on the p1 shadow point ONLY: it aligns
 * each channel's black point to a common target (the lowest channel black), removing a colour
 * cast in the shadows WITHOUT lifting or crushing them (gain=1, offset-only).
 *
 * Emits an offset-only affine (reuse generateAssertedAffineDRX). Skips a clip whose shadows are
 * already neutral (nothing to do — skip-not-fake). LOCAL & deterministic; no Resolve.
 */
import fs from 'node:fs';
import { createRequire } from 'node:module';
import { generateAssertedAffineDRX } from './contrast-normalize.mjs';
import { provenanceLabel, gist } from './node-provenance.mjs';

const require = createRequire(import.meta.url);
function loadSharp() {
  try {
    return require('sharp');
  } catch {
    throw new Error("black-balance needs the optional dep 'sharp'. Install: npm i sharp");
  }
}
const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
function percentile(sorted, p) {
  if (!sorted.length) return 0;
  const idx = clamp(Math.round((p / 100) * (sorted.length - 1)), 0, sorted.length - 1);
  return sorted[idx];
}

/** Per-channel black point (p1, 0..1). Returns {r,g,b} or null. */
export async function measureBlackPoint(pngPath, opts = {}) {
  const sharp = loadSharp();
  const lowP = opts.lowPct ?? 1,
    maxSide = opts.maxSide ?? 480;
  let data, ch;
  try {
    const out = await sharp(pngPath).resize(maxSide, maxSide, { fit: 'inside', kernel: 'nearest' }).raw().toBuffer({ resolveWithObject: true });
    data = out.data;
    ch = out.info.channels;
  } catch {
    return null;
  }
  const R = [],
    G = [],
    B = [];
  for (let i = 0; i < data.length; i += ch) {
    R.push(data[i]);
    G.push(data[i + 1]);
    B.push(data[i + 2]);
  }
  if (!R.length) return null;
  R.sort((a, b) => a - b);
  G.sort((a, b) => a - b);
  B.sort((a, b) => a - b);
  return { r: percentile(R, lowP) / 255, g: percentile(G, lowP) / 255, b: percentile(B, lowP) / 255 };
}

/**
 * @param {Array<{id, png, group?}>} clips
 * @param {{outDir, castThreshold?:number, clampOffset?:[number,number]}} opts
 */
export async function computeBlackBalance(clips, opts = {}) {
  if (!opts.outDir) throw new Error('opts.outDir required');
  fs.mkdirSync(opts.outDir, { recursive: true });
  const castThreshold = opts.castThreshold ?? 0.004; // ~1/255 — below this the shadows are already neutral
  const [olo, ohi] = opts.clampOffset || [-0.2, 0.2];

  const grades = [];
  const warnings = [];
  const skipped = [];
  const report = {};
  for (const c of clips) {
    const bp = await measureBlackPoint(c.png, opts);
    if (!bp) {
      skipped.push({ id: c.id, reason: 'unreadable frame' });
      continue;
    }
    const target = Math.min(bp.r, bp.g, bp.b); // align to the lowest black — pull casts DOWN, don't lift
    const spread = Math.max(bp.r, bp.g, bp.b) - target;
    if (spread < castThreshold) {
      skipped.push({ id: c.id, reason: 'shadows already neutral', castSpread: +spread.toFixed(4) });
      continue;
    }
    const gain = { r: 1, g: 1, b: 1 };
    const offset = { r: clamp(target - bp.r, olo, ohi), g: clamp(target - bp.g, olo, ohi), b: clamp(target - bp.b, olo, ohi) };
    const drxPath = `${opts.outDir}/${c.id}_blackbal.drx`;
    await generateAssertedAffineDRX(gain, offset, provenanceLabel('black_balance', { source: 'shadow-neutral', gist: gist('offset', offset) }), drxPath, warnings);
    grades.push({ id: c.id, offset, castSpreadPct: +(100 * spread).toFixed(2), drxPath });
    report[c.id] = { castSpreadPct: +(100 * spread).toFixed(2) };
  }
  return { grades, report, warnings, skipped };
}
