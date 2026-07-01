/**
 * Cross-camera SKIN-tone cohesion (C2 `skin_match`).
 *
 * The problem exposure_level's within_camera_mean can't solve: the same person shot
 * on two cameras / two framings (wide vs CU) has DIFFERENT whole-frame means because
 * the background and headroom differ — so matching overall mean is wrong. The thing
 * that must read consistent across those shots is the PERSON'S SKIN. So we gate each
 * frame to skin-tone pixels, take the mean of ONLY those, and match per-channel gain
 * toward a group hero. Background is ignored by construction.
 *
 * LOCAL & deterministic: sharp raw pixels -> skin gate -> arithmetic -> drx codec.
 * No Resolve, no LLM vision. Frame extraction + grade APPLY are the caller's job.
 *
 * COLOR-SPACE CAVEAT: the skin gate assumes DISPLAY-REFERRED frames (Rec.709 / sRGB).
 * Log frames (SLog3 etc.) are flat & desaturated, so almost nothing passes the gate.
 * Rather than fabricate a match from noise, this module GUARDS: a clip with too few
 * skin pixels is skipped (warned, no DRX), and a job where NO clip has skin THROWS —
 * the loud signal that frames were extracted in the wrong space.
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
    throw new Error("skin-match needs the optional dep 'sharp' (frame stats). Install: npm i sharp");
  }
}

const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
const mean = (a) => a.reduce((x, y) => x + y, 0) / a.length;
const std = (a) => {
  const m = mean(a);
  return Math.sqrt(mean(a.map((x) => (x - m) ** 2)));
};

/**
 * Classic Kovac RGB skin rule for uniform daylight, on 8-bit channels.
 * Conservative on purpose: better to gate out a borderline pixel than to admit a
 * background pixel that drags the skin mean. Tunable via opts but defaults are the
 * literature values.
 */
export function isSkin(r, g, b, opts = {}) {
  const minR = opts.minR ?? 95,
    minG = opts.minG ?? 40,
    minB = opts.minB ?? 20;
  const minSpread = opts.minSpread ?? 15,
    minRG = opts.minRG ?? 15;
  const mx = Math.max(r, g, b),
    mn = Math.min(r, g, b);
  return r > minR && g > minG && b > minB && mx - mn > minSpread && Math.abs(r - g) > minRG && r > g && r > b;
}

/**
 * Mean RGB of skin-gated pixels in a PNG. Downsamples (nearest, no blend → no fake
 * skin on edges) for speed/determinism. Returns null mean if the frame is unreadable.
 * @returns {Promise<{mean:{r,g,b}|null, skinFrac:number, nSkin:number, nTotal:number}>}
 */
export async function measureSkinMeanRGB(pngPath, opts = {}) {
  const sharp = loadSharp();
  const maxSide = opts.maxSide ?? 480;
  let data, channels;
  try {
    const out = await sharp(pngPath).resize(maxSide, maxSide, { fit: 'inside', kernel: 'nearest' }).raw().toBuffer({ resolveWithObject: true });
    data = out.data;
    channels = out.info.channels;
  } catch {
    return { mean: null, skinFrac: 0, nSkin: 0, nTotal: 0 };
  }
  let sr = 0,
    sg = 0,
    sb = 0,
    nSkin = 0;
  const nTotal = Math.floor(data.length / channels);
  for (let i = 0; i < data.length; i += channels) {
    const r = data[i],
      g = data[i + 1],
      b = data[i + 2];
    if (isSkin(r, g, b, opts)) {
      sr += r;
      sg += g;
      sb += b;
      nSkin++;
    }
  }
  const m = nSkin ? { r: sr / nSkin, g: sg / nSkin, b: sb / nSkin } : null;
  return { mean: m, skinFrac: nTotal ? nSkin / nTotal : 0, nSkin, nTotal };
}

/**
 * Match each clip's SKIN mean to a per-group hero via per-channel gain.
 *
 * @param {Array<{id:string|number, png:string, group:string}>} clips
 * @param {{outDir:string, clampGain?:[number,number], minSkinFrac?:number,
 * maxCorrWarn?:number, heroId?:string|number, skin?:object}} opts
 * @returns {Promise<{grades:Array, report:Object, warnings:string[], skipped:Array}>}
 */
export async function computeSkinMatch(clips, opts = {}) {
  if (!opts.outDir) throw new Error('opts.outDir required');
  const [lo, hi] = opts.clampGain || [0.5, 2];
  const minSkinFrac = opts.minSkinFrac ?? 0.01; // <1% skin → can't trust the mean
  const maxCorrWarn = opts.maxCorrWarn ?? 0.25; // cross-camera deltas run larger than 1-cam drift
  fs.mkdirSync(opts.outDir, { recursive: true });

  const byGroup = new Map();
  for (const c of clips) {
    if (!byGroup.has(c.group)) byGroup.set(c.group, []);
    byGroup.get(c.group).push(c);
  }

  const grades = [];
  const report = {};
  const warnings = [];
  const skipped = [];
  let anySkinAnywhere = false;

  for (const [group, gclips] of byGroup) {
    for (const c of gclips) {
      const s = await measureSkinMeanRGB(c.png, opts.skin || {});
      c.skin = s.mean;
      c.skinFrac = s.skinFrac;
      if (s.mean) anySkinAnywhere = true;
      // Skin-line sanity: the Kovac RGB gate passes fire/wood/orange content too
      // (live finding 2026-07-03: a car fire read 8.3% "skin"). Real faces sit within
      // a few degrees of the canonical vectorscope skin line (~123°); non-skin
      // Kovac-positives land far off it (fire read −22°). Warn — don't skip — when
      // the gated region's hue deviates hard; the review gate owns the decision.
      if (s.mean) {
        const { r, g, b } = s.mean;
        const y = 0.2126 * r + 0.7152 * g + 0.0722 * b;
        // Same convention as scope-read.mjs (Rec.709 full-range chroma, atan2(cr, cb),
        // canonical skin line 123°).
        const cb = (b - y) / 1.8556, cr = (r - y) / 1.5748;
        const angle = (Math.atan2(cr, cb) * 180) / Math.PI;
        const dev = angle - 123;
        if (Math.abs(dev) > 12)
          warnings.push(
            `${c.id}: skin-gated region sits ${dev.toFixed(1)}° off the vectorscope skin line — likely NOT skin (fire/wood/orange content). Review before applying; consider excluding via intent tags.`,
          );
      }
    }
    // A clip is usable only if it cleared the skin-fraction floor.
    const usable = gclips.filter((c) => c.skin && c.skinFrac >= minSkinFrac);
    for (const c of gclips.filter((c) => !usable.includes(c))) {
      skipped.push({ id: c.id, group, skinFrac: +(100 * (c.skinFrac || 0)).toFixed(2), reason: 'insufficient skin pixels' });
    }
    if (!usable.length) {
      report[group] = { error: 'no clip cleared the skin-fraction floor', minSkinFracPct: 100 * minSkinFrac };
      continue;
    }

    const hero = (opts.heroId != null && usable.find((c) => c.id === opts.heroId)) || usable[0];
    const H = hero.skin;
    // v2 metric='chroma' (skin-LINE preserving): match each clip's skin CHROMATICITY (channel/luma)
    // to the hero, preserving the clip's OWN luma. This matches skin hue/chroma direction without
    // dragging a darker face's brightness up to the hero — the calibrated-for-white-skin trap that
    // masked-mean equality ('mean', legacy default) falls into. See node-provenance skin_match v2.
    const metric = opts.metric || 'mean';
    const lumaOf = (m) => 0.2126 * m.r + 0.7152 * m.g + 0.0722 * m.b;
    const Hl = lumaOf(H) || 1e-6;
    let maxCorr = 0;
    for (const c of usable) {
      let gain;
      if (metric === 'chroma') {
        const cl = lumaOf(c.skin) || 1e-6;
        gain = {
          r: clamp((H.r / Hl) / (c.skin.r / cl), lo, hi),
          g: clamp((H.g / Hl) / (c.skin.g / cl), lo, hi),
          b: clamp((H.b / Hl) / (c.skin.b / cl), lo, hi),
        };
      } else {
        gain = { r: clamp(H.r / c.skin.r, lo, hi), g: clamp(H.g / c.skin.g, lo, hi), b: clamp(H.b / c.skin.b, lo, hi) };
      }
      const corr = Math.max(...['r', 'g', 'b'].map((k) => Math.abs(gain[k] - 1)));
      maxCorr = Math.max(maxCorr, corr);
      const drxPath = `${opts.outDir}/${group}_${c.id}_skin.drx`;
      await generateAssertedGainDRX(gain, provenanceLabel('skin_match', { source: `hero:${hero.id}`, gist: gist('gain', gain) }), drxPath);
      grades.push({ id: c.id, group, gain, correctionPct: +(100 * corr).toFixed(2), skinFracPct: +(100 * c.skinFrac).toFixed(2), drxPath, isHero: c === hero });
    }
    const sf = usable.map((c) => 100 * c.skinFrac);
    report[group] = {
      clips: usable.length,
      hero_id: hero.id,
      skin_frac_pct_mean: +mean(sf).toFixed(2),
      skin_frac_pct_min: +Math.min(...sf).toFixed(2),
      max_correction_pct: +(100 * maxCorr).toFixed(2),
    };
    if (maxCorr > maxCorrWarn)
      warnings.push(
        `${group}: max skin correction ${(100 * maxCorr).toFixed(1)}% > ${(100 * maxCorrWarn).toFixed(0)}% — large for a skin match; check hero choice / mixed lighting before applying.`,
      );
  }

  // Loud guard: zero skin anywhere almost always means log/wrong-space frames, not a real "no people" job.
  if (!anySkinAnywhere)
    throw new Error(
      'skin_match found NO skin-tone pixels in ANY frame — frames are likely LOG/scene-referred (skin gate assumes display-referred Rec.709/sRGB). Re-extract display-referred frames, or this is the wrong tool.',
    );

  return { grades, report, warnings, skipped };
}
