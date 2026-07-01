/**
 * Clip exposure/balance LEVELING — compute a per-clip *general* offset (per-channel
 * gain) toward a group hero from measured frame stats, and emit a round-trip-asserted
 * Primary-Balance DRX (the series' node style, not flat CDL).
 *
 * LOCAL: ffmpeg-extracted PNG frames -> sharp pixel means -> arithmetic -> drx codec.
 * No Resolve, no LLM vision. Frame extraction + grade APPLY are the caller's job
 * (Resolve scripting API). This module is the deterministic core.
 *
 * Modes:
 * within_camera_mean (default) — VALID only for one camera's drift over a record
 * (same framing). Matches each clip's per-channel mean to the group hero.
 * scene_aware / skin_match — NOT IMPLEMENTED (throws). overall-mean is wrong across
 * different shots (b-roll) or different framings/cameras (use skin-match there).
 */
import fs from 'node:fs';
import { createRequire } from 'node:module';
import { drxTool } from './tools/drx.mjs';
import { provenanceLabel, gist } from './node-provenance.mjs';

const require = createRequire(import.meta.url);
function loadSharp() {
  try {
    return require('sharp');
  } catch {
    throw new Error("exposure-level needs the optional dep 'sharp' (frame stats). Install: npm i sharp");
  }
}

const luma = (m) => 0.2126 * m.r + 0.7152 * m.g + 0.0722 * m.b;
const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
const mean = (a) => a.reduce((x, y) => x + y, 0) / a.length;
const std = (a) => {
  const m = mean(a);
  return Math.sqrt(mean(a.map((x) => (x - m) ** 2)));
};

/** Per-channel mean (0..max) of a PNG. */
export async function measureMeanRGB(pngPath) {
  const s = await loadSharp()(pngPath).stats();
  return { r: s.channels[0].mean, g: s.channels[1].mean, b: s.channels[2].mean };
}

/** Generate a Primary-Balance DRX for a per-channel gain, then decode it and THROW if
 * a non-unity grade came back empty (the silent-empty bug guard). Returns the DRX path. */
export async function generateAssertedGainDRX(gain, label, outPath) {
  // gain values are raw multipliers -> pin space:'drx' (UI happens to be 1:1 for gain,
  // but the pin keeps this emitter immune to the space default).
  //
  // Resolve renders the RGB gain wheels as COLOR BALANCE only: the per-channel values
  // are luma-renormalized at render time, so a uniform [1.3,1.3,1.3] with master 1 is a
  // NO-OP (live-validated 2026-07-03, DaVinci YRGB/Rec709). The achromatic level must be
  // carried by gain.master. Emit master = luma-weighted common gain; keep the channels
  // absolute — Resolve's own renormalization then yields exactly the intended per-channel
  // multipliers (master × ch/luma(ch) == ch).
  const master = 0.2126 * gain.r + 0.7152 * gain.g + 0.0722 * gain.b;
  await drxTool.handler({ action: 'generate', args: { gradeParams: { space: 'drx', gain: [gain.r, gain.g, gain.b, master] }, metadata: { label }, outputPath: outPath } });
  const back = await drxTool.handler({ action: 'parse', args: { content: fs.readFileSync(outPath, 'utf8') } });
  const got = (back.nodes || []).flatMap((n) => (n.correctors || []).flatMap((c) => c.parameters || [])).filter((p) => /gain\.(r|g|b)/i.test(p.name)).length;
  const nonUnity = [gain.r, gain.g, gain.b].some((v) => Math.abs(v - 1) > 0.002);
  if (nonUnity && got === 0) throw new Error(`round-trip assert FAILED: ${label} generated an EMPTY grade (gain ${JSON.stringify(gain)})`);
  return outPath;
}

/**
 * @param {Array<{id:string|number, png:string, group:string}>} clips
 * @param {{outDir:string, mode?:string, clampGain?:[number,number], maxCorrWarn?:number}} opts
 * @returns {Promise<{grades:Array, report:Object, warnings:string[]}>}
 */
export async function computeLevels(clips, opts = {}) {
  const mode = opts.mode || 'within_camera_mean';
  if (mode !== 'within_camera_mean') {
    throw new Error(
      `mode '${mode}' not implemented. within_camera_mean only (overall-mean is invalid across different shots/cameras — use skin-match/scene-cluster, TODO).`,
    );
  }
  const [lo, hi] = opts.clampGain || [0.5, 2];
  const maxCorrWarn = opts.maxCorrWarn ?? 0.12; // flag >12% as likely over-correction
  if (!opts.outDir) throw new Error('opts.outDir required');
  fs.mkdirSync(opts.outDir, { recursive: true });

  const byGroup = new Map();
  for (const c of clips) {
    if (!byGroup.has(c.group)) byGroup.set(c.group, []);
    byGroup.get(c.group).push(c);
  }

  const grades = [];
  const report = {};
  const warnings = [];
  for (const [group, gclips] of byGroup) {
    for (const c of gclips) {
      try {
        c.mean = await measureMeanRGB(c.png);
        c.luma = luma(c.mean);
      } catch {
        c.mean = null;
      }
    }
    const valid = gclips.filter((c) => c.mean);
    if (!valid.length) {
      report[group] = { error: 'no measurable frames' };
      continue;
    }
    const H = valid[0].mean; // hero = first clip in group order
    const lr = valid.map((c) => c.luma);
    let maxCorr = 0;
    for (const c of valid) {
      const gain = { r: clamp(H.r / c.mean.r, lo, hi), g: clamp(H.g / c.mean.g, lo, hi), b: clamp(H.b / c.mean.b, lo, hi) };
      const corr = Math.max(...['r', 'g', 'b'].map((k) => Math.abs(gain[k] - 1)));
      maxCorr = Math.max(maxCorr, corr);
      const drxPath = `${opts.outDir}/${group}_${c.id}.drx`;
      await generateAssertedGainDRX(gain, provenanceLabel('exposure_level', { source: `hero:${valid[0].id}`, gist: gist('gain', gain) }), drxPath);
      grades.push({ id: c.id, group, gain, correctionPct: +(100 * corr).toFixed(2), drxPath, isHero: c === valid[0] });
    }
    report[group] = {
      clips: valid.length,
      hero_id: valid[0].id,
      luma_pct_std: +((100 * std(lr)) / mean(lr)).toFixed(2),
      luma_pct_range: +((100 * (Math.max(...lr) - Math.min(...lr))) / mean(lr)).toFixed(2),
      max_correction_pct: +(100 * maxCorr).toFixed(2),
    };
    if (maxCorr > maxCorrWarn)
      warnings.push(
        `${group}: max correction ${(100 * maxCorr).toFixed(1)}% > ${(100 * maxCorrWarn).toFixed(0)}% — likely NOT one-camera drift (different shots?). Review before applying.`,
      );
  }
  return { grades, report, warnings };
}
