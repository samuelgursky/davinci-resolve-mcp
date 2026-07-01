/**
 * B-roll cohesion (C1 `shot_match`).
 *
 * B-roll shots are all DIFFERENT content, so there is no shared subject mean to match
 * (that's why exposure_level's within_camera_mean and skin_match both refuse this job).
 * What you CAN do is make a run of b-roll feel cohesive — no jarring warm/cool cuts —
 * two ways, both offered here:
 *
 * mode 'neutralize' (default) — per-shot gray-world: pull each shot's own per-channel
 * MEDIAN toward neutral gray at that shot's luma. Removes each shot's individual
 * colour cast; exposure preserved. No hero needed.
 * mode 'hero' — per scene, match every shot's median toward a chosen hero plate's
 * median. Cohere a scene to one look the colourist likes.
 *
 * Why MEDIAN, not mean: b-roll content varies, so a big coloured object drags a mean.
 * The per-channel median is robust to that — it tracks the shot's dominant tone, which
 * is what a cast actually lives in. This is the deliberate difference from exposure_level.
 *
 * `scene` clusters shots (default: one scene). It scopes hero selection and QC grouping;
 * neutralize is per-shot regardless. LOCAL & deterministic: sharp raw pixels -> median ->
 * arithmetic -> drx codec. No Resolve, no LLM vision. Frame extraction + APPLY = caller's.
 *
 * CAVEAT: gray-world neutralize assumes the scene is, on average, neutral. A shot that
 * is GENUINELY dominated by one colour (sunset, neon) will be over-corrected — clamp +
 * the max-correction warning flag these; review before applying.
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
    throw new Error("shot-match needs the optional dep 'sharp' (frame stats). Install: npm i sharp");
  }
}

const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
const median = (a) => {
  const s = [...a].sort((x, y) => x - y);
  const n = s.length;
  return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
};

/**
 * Per-channel MEDIAN of a PNG (downsampled, nearest → no edge-blend). Robust dominant
 * tone. Returns null median if unreadable.
 * @returns {Promise<{median:{r,g,b}|null, nTotal:number}>}
 */
export async function measureToneRGB(pngPath, opts = {}) {
  const sharp = loadSharp();
  const maxSide = opts.maxSide ?? 96; // ~thousands of px: plenty for a median, cheap to sort
  let data, channels;
  try {
    const out = await sharp(pngPath).resize(maxSide, maxSide, { fit: 'inside', kernel: 'nearest' }).raw().toBuffer({ resolveWithObject: true });
    data = out.data;
    channels = out.info.channels;
  } catch {
    return { median: null, nTotal: 0 };
  }
  const R = [],
    G = [],
    B = [];
  for (let i = 0; i < data.length; i += channels) {
    R.push(data[i]);
    G.push(data[i + 1]);
    B.push(data[i + 2]);
  }
  if (!R.length) return { median: null, nTotal: 0 };
  return { median: { r: median(R), g: median(G), b: median(B) }, nTotal: R.length };
}

/**
 * @param {Array<{id:string|number, png:string, scene?:string}>} clips
 * @param {{outDir:string, mode?:'neutralize'|'hero', clampGain?:[number,number],
 * maxCorrWarn?:number, heroId?:string|number}} opts
 * @returns {Promise<{grades:Array, report:Object, warnings:string[], skipped:Array}>}
 */
export async function computeShotMatch(clips, opts = {}) {
  if (!opts.outDir) throw new Error('opts.outDir required');
  const mode = opts.mode || 'neutralize';
  if (mode !== 'neutralize' && mode !== 'hero') throw new Error(`shot_match mode '${mode}' unknown (neutralize | hero)`);
  if (mode === 'hero' && opts.heroId == null) throw new Error("shot_match mode 'hero' requires opts.heroId (the plate to match toward)");
  const [lo, hi] = opts.clampGain || [0.5, 2];
  const maxCorrWarn = opts.maxCorrWarn ?? 0.3; // b-roll deltas run large; flag the genuinely-extreme
  fs.mkdirSync(opts.outDir, { recursive: true });

  const byScene = new Map();
  for (const c of clips) {
    const k = c.scene ?? '_all';
    if (!byScene.has(k)) byScene.set(k, []);
    byScene.get(k).push(c);
  }

  const grades = [];
  const report = {};
  const warnings = [];
  const skipped = [];

  for (const [scene, sclips] of byScene) {
    for (const c of sclips) {
      const t = await measureToneRGB(c.png, opts);
      c.tone = t.median;
    }
    const usable = sclips.filter((c) => c.tone);
    for (const c of sclips.filter((c) => !c.tone)) skipped.push({ id: c.id, scene, reason: 'unreadable frame' });
    if (!usable.length) {
      report[scene] = { error: 'no readable frames' };
      continue;
    }

    let hero = null;
    if (mode === 'hero') {
      hero = usable.find((c) => c.id === opts.heroId);
      if (!hero) {
        report[scene] = { skipped: `heroId ${opts.heroId} not in this scene` };
        continue;
      }
    }

    let maxCorr = 0;
    for (const c of usable) {
      let gain;
      if (mode === 'neutralize') {
        const lumaT = (c.tone.r + c.tone.g + c.tone.b) / 3; // target = this shot's own grey level
        gain = { r: clamp(lumaT / c.tone.r, lo, hi), g: clamp(lumaT / c.tone.g, lo, hi), b: clamp(lumaT / c.tone.b, lo, hi) };
      } else {
        gain = { r: clamp(hero.tone.r / c.tone.r, lo, hi), g: clamp(hero.tone.g / c.tone.g, lo, hi), b: clamp(hero.tone.b / c.tone.b, lo, hi) };
      }
      const corr = Math.max(...['r', 'g', 'b'].map((k) => Math.abs(gain[k] - 1)));
      maxCorr = Math.max(maxCorr, corr);
      const drxPath = `${opts.outDir}/${scene}_${c.id}_shot.drx`;
      await generateAssertedGainDRX(gain, provenanceLabel('shot_match', { source: mode === 'hero' ? `hero:${opts.heroId}` : 'neutralize', gist: gist('gain', gain) }), drxPath);
      grades.push({ id: c.id, scene, mode, gain, correctionPct: +(100 * corr).toFixed(2), drxPath, isHero: hero ? c === hero : false });
    }
    report[scene] = { mode, clips: usable.length, hero_id: hero ? hero.id : null, max_correction_pct: +(100 * maxCorr).toFixed(2) };
    if (maxCorr > maxCorrWarn)
      warnings.push(
        `${scene}: max correction ${(100 * maxCorr).toFixed(1)}% > ${(100 * maxCorrWarn).toFixed(0)}% — a shot may be genuinely one-colour (sunset/neon) and over-corrected by gray-world. Review before applying.`,
      );
  }

  return { grades, report, warnings, skipped };
}
