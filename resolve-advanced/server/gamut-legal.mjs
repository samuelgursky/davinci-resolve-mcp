/**
 * Broadcast-legal / clipping QC (C3 `gamut_legal`).
 *
 * Pure MEASUREMENT — no grade emitted. On display-referred frames it reports, per
 * channel, how much of the picture sits outside video-legal range (default 8-bit
 * 16–235) and how much is HARD-CLIPPED (==0 crushed / ==255 blown), then gives each
 * clip a pass/fail against a tolerance. The delivery-QC signal before master render
 * (a common master is Rec.709 Gamma 2.4 — many broadcasters want video-legal).
 *
 * Caveat: superwhite/sub-black detail already clipped INTO the PNG can't be recovered
 * here — this flags what the frame shows. For true scope-legal QC use the timeline
 * scopes; this is the cheap local pre-check. LOCAL & deterministic; no Resolve.
 */
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
function loadSharp() {
  try {
    return require('sharp');
  } catch {
    throw new Error("gamut-legal needs the optional dep 'sharp'. Install: npm i sharp");
  }
}
const pct = (n, d) => (d ? +((100 * n) / d).toFixed(3) : 0);

/**
 * @returns {Promise<{channels:Object, illegalPct:number, clippedPct:number, nTotal:number}|null>}
 */
export async function measureLegal(pngPath, opts = {}) {
  const sharp = loadSharp();
  const low = opts.low ?? 16,
    high = opts.high ?? 235,
    maxSide = opts.maxSide ?? 480;
  let data, ch;
  try {
    const out = await sharp(pngPath).resize(maxSide, maxSide, { fit: 'inside', kernel: 'nearest' }).raw().toBuffer({ resolveWithObject: true });
    data = out.data;
    ch = out.info.channels;
  } catch {
    return null;
  }
  const nTotal = Math.floor(data.length / ch);
  const names = ['r', 'g', 'b'];
  const acc = names.map(() => ({ min: 255, max: 0, below: 0, above: 0, at0: 0, at255: 0 }));
  let illegalPx = 0,
    clippedPx = 0;
  for (let i = 0; i < data.length; i += ch) {
    let illegal = false,
      clipped = false;
    for (let c = 0; c < 3; c++) {
      const v = data[i + c],
        a = acc[c];
      if (v < a.min) a.min = v;
      if (v > a.max) a.max = v;
      if (v < low) {
        a.below++;
        illegal = true;
      } else if (v > high) {
        a.above++;
        illegal = true;
      }
      if (v === 0) {
        a.at0++;
        clipped = true;
      } else if (v === 255) {
        a.at255++;
        clipped = true;
      }
    }
    if (illegal) illegalPx++;
    if (clipped) clippedPx++;
  }
  const channels = {};
  names.forEach((n, c) => {
    const a = acc[c];
    channels[n] = {
      min: a.min,
      max: a.max,
      belowPct: pct(a.below, nTotal),
      abovePct: pct(a.above, nTotal),
      crushedPct: pct(a.at0, nTotal),
      blownPct: pct(a.at255, nTotal),
    };
  });
  return { channels, illegalPct: pct(illegalPx, nTotal), clippedPct: pct(clippedPx, nTotal), nTotal };
}

/**
 * @param {Array<{id:string|number, png:string}>} clips
 * @param {{low?:number, high?:number, maxIllegalPct?:number}} opts
 * @returns {Promise<{report:Object, warnings:string[], skipped:Array}>}
 */
export async function computeGamutLegal(clips, opts = {}) {
  const maxIllegalPct = opts.maxIllegalPct ?? 1.0; // tolerate up to 1% out-of-legal by default
  const report = {};
  const warnings = [];
  const skipped = [];
  for (const c of clips) {
    const m = await measureLegal(c.png, opts);
    if (!m) {
      skipped.push({ id: c.id, reason: 'unreadable frame' });
      continue;
    }
    const pass = m.illegalPct <= maxIllegalPct;
    report[c.id] = { pass, illegalPct: m.illegalPct, clippedPct: m.clippedPct, channels: m.channels };
    if (!pass)
      warnings.push(
        `${c.id}: ${m.illegalPct}% out-of-legal (>${maxIllegalPct}% tol) [low ${opts.low ?? 16}/high ${opts.high ?? 235}] — review before broadcast-legal delivery.`,
      );
  }
  return { report, warnings, skipped };
}
