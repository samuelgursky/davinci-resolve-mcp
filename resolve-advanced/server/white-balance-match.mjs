/**
 * White-balance match on a KNOWN-NEUTRAL patch (C3 `white_balance_match`).
 *
 * Where shot_match's gray-world GUESSES that the whole frame averages neutral,
 * white_balance_match is told WHERE neutral is — a gray card, a white wall, a known-
 * neutral object the colourist points at via a normalized rect. Sampling only that
 * patch makes the WB correction accurate instead of content-dependent.
 *
 * mode 'neutralize' (default) — make the patch read neutral grey at its own luma.
 * mode 'hero' — match each clip's patch to a hero clip's patch (carry a deliberate
 * non-neutral key across a group).
 *
 * Gain-only → reuses exposure_level's round-trip-asserted DRX emission. LOCAL &
 * deterministic; no Resolve. rect = {x,y,w,h} as fractions 0..1 (per-clip rect allowed).
 */
import fs from 'node:fs';
import { createRequire } from 'node:module';
import { generateAssertedGainDRX } from './exposure-level.mjs';
import { provenanceLabel, gist } from './node-provenance.mjs';

const require = createRequire(import.meta.url);
function loadSharp() {
  try {
    return require('sharp');
  } catch {
    throw new Error("white-balance-match needs the optional dep 'sharp'. Install: npm i sharp");
  }
}
const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));

/** Mean RGB inside a fractional rect of a PNG. Returns null if unreadable/empty. */
export async function measurePatchMeanRGB(pngPath, rect, opts = {}) {
  const sharp = loadSharp();
  const r = { x: rect?.x ?? 0, y: rect?.y ?? 0, w: rect?.w ?? 1, h: rect?.h ?? 1 };
  try {
    const meta = await sharp(pngPath).metadata();
    const W = meta.width,
      H = meta.height;
    const left = Math.max(0, Math.round(r.x * W)),
      top = Math.max(0, Math.round(r.y * H));
    const width = Math.max(1, Math.min(W - left, Math.round(r.w * W)));
    const height = Math.max(1, Math.min(H - top, Math.round(r.h * H)));
    // NOTE: sharp's.stats() reads the ORIGINAL input and ignores a prior.extract() in
    // the same pipeline — so materialize the crop to a buffer first, then stat that.
    const cropped = await sharp(pngPath).extract({ left, top, width, height }).png().toBuffer();
    const s = await sharp(cropped).stats();
    return { r: s.channels[0].mean, g: s.channels[1].mean, b: s.channels[2].mean };
  } catch {
    return null;
  }
}

/**
 * @param {Array<{id:string|number, png:string, group?:string, rect?:{x,y,w,h}}>} clips
 * @param {{outDir:string, mode?:'neutralize'|'hero', rect?:object, heroId?:string|number,
 * clampGain?:[number,number], maxCorrWarn?:number}} opts
 * @returns {Promise<{grades:Array, report:Object, warnings:string[], skipped:Array}>}
 */
export async function computeWhiteBalanceMatch(clips, opts = {}) {
  if (!opts.outDir) throw new Error('opts.outDir required');
  const mode = opts.mode || 'neutralize';
  if (mode !== 'neutralize' && mode !== 'hero') throw new Error(`white_balance_match mode '${mode}' unknown (neutralize | hero)`);
  if (mode === 'hero' && opts.heroId == null) throw new Error("white_balance_match mode 'hero' requires opts.heroId");
  const [lo, hi] = opts.clampGain || [0.5, 2];
  const maxCorrWarn = opts.maxCorrWarn ?? 0.2;
  fs.mkdirSync(opts.outDir, { recursive: true });

  const byGroup = new Map();
  for (const c of clips) {
    const k = c.group ?? '_all';
    if (!byGroup.has(k)) byGroup.set(k, []);
    byGroup.get(k).push(c);
  }

  const grades = [];
  const report = {};
  const warnings = [];
  const skipped = [];

  for (const [group, gclips] of byGroup) {
    for (const c of gclips) {
      c.patch = await measurePatchMeanRGB(c.png, c.rect || opts.rect, opts);
    }
    const usable = gclips.filter((c) => c.patch);
    for (const c of gclips.filter((c) => !c.patch)) skipped.push({ id: c.id, group, reason: 'unreadable patch' });
    if (!usable.length) {
      report[group] = { error: 'no readable patch' };
      continue;
    }

    let hero = null;
    if (mode === 'hero') {
      hero = usable.find((c) => c.id === opts.heroId);
      if (!hero) {
        report[group] = { skipped: `heroId ${opts.heroId} not in group` };
        continue;
      }
    }

    let maxCorr = 0;
    for (const c of usable) {
      let gain;
      if (mode === 'neutralize') {
        const lumaT = (c.patch.r + c.patch.g + c.patch.b) / 3;
        gain = { r: clamp(lumaT / c.patch.r, lo, hi), g: clamp(lumaT / c.patch.g, lo, hi), b: clamp(lumaT / c.patch.b, lo, hi) };
      } else {
        gain = { r: clamp(hero.patch.r / c.patch.r, lo, hi), g: clamp(hero.patch.g / c.patch.g, lo, hi), b: clamp(hero.patch.b / c.patch.b, lo, hi) };
      }
      const corr = Math.max(...['r', 'g', 'b'].map((k) => Math.abs(gain[k] - 1)));
      maxCorr = Math.max(maxCorr, corr);
      const drxPath = `${opts.outDir}/${group}_${c.id}_wb.drx`;
      await generateAssertedGainDRX(gain, provenanceLabel('white_balance_match', { source: mode === 'hero' ? `hero:${opts.heroId}` : 'neutralize', gist: gist('gain', gain) }), drxPath);
      grades.push({ id: c.id, group, mode, gain, correctionPct: +(100 * corr).toFixed(2), drxPath, isHero: hero ? c === hero : false });
    }
    report[group] = { mode, clips: usable.length, hero_id: hero ? hero.id : null, max_correction_pct: +(100 * maxCorr).toFixed(2) };
    if (maxCorr > maxCorrWarn)
      warnings.push(
        `${group}: max WB correction ${(100 * maxCorr).toFixed(1)}% > ${(100 * maxCorrWarn).toFixed(0)}% — check the patch actually sits on a neutral surface (not a coloured object).`,
      );
  }
  return { grades, report, warnings, skipped };
}
