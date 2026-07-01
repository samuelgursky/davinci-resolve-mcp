/**
 * Contrast normalize — black/white-point match (C3 `contrast_normalize`).
 *
 * Where exposure_level matches a MEAN (a single offset), contrast_normalize matches the
 * tonal RANGE: each clip's robust black point and white point are mapped onto a group
 * hero's, per channel, by an affine fit out = scale·in + shift (scale→gain, shift→
 * offset). This lines clips up in the same tonal range BEFORE a shared look, so the look
 * lands consistently. Robust points = 1st/99th percentile (ignores a few hot/black outliers).
 *
 * OFFSET SEMANTICS (live-validated 2026-07-03, DaVinci YRGB/Rec709): Resolve's wire
 * offset shifts output by wire×0.2 normalized, wire range ±1 (→ ±0.2 norm max). The
 * emitter converts normalized intent → wire (×5), clamps, and warns on clamp. The RGB
 * gain wheels are luma-renormalized by Resolve (balance only) — the achromatic level
 * rides gain.master.
 *
 * ACEScct (measured live 2026-07-03, synthetic project, Rec.709 IDT/ODT): the
 * STRUCTURAL semantics hold (luma-renorm of RGB wheels; master carries level), but
 * wheels operate in cct WORKING space before the ACES output tonescale, so the ×0.2
 * display factor does NOT transfer — display response is level-dependent. Under
 * ACEScct, treat emitted trims as directionally-correct starting nudges and CONVERGE
 * by iteration (apply → re-extract → re-measure), per the pass-based review design.
 * LOCAL & deterministic; no Resolve.
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
    throw new Error("contrast-normalize needs the optional dep 'sharp'. Install: npm i sharp");
  }
}
const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
function percentile(sorted, p) {
  if (!sorted.length) return 0;
  const idx = clamp(Math.round((p / 100) * (sorted.length - 1)), 0, sorted.length - 1);
  return sorted[idx];
}

/** Per-channel black/white points (normalized 0..1) at the given percentiles. */
export async function measureBWPoints(pngPath, opts = {}) {
  const sharp = loadSharp();
  const lowP = opts.lowPct ?? 1,
    highP = opts.highPct ?? 99,
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
  const mk = (arr) => ({ black: percentile(arr, lowP) / 255, white: percentile(arr, highP) / 255 });
  return { r: mk(R), g: mk(G), b: mk(B) };
}

/** Wire-offset units per NORMALIZED (0..1) shift. Live-validated 2026-07-03 (DaVinci
 * YRGB / Rec709 render): wire offset −0.1 shifts output by exactly −0.02 normalized
 * (−5/255), i.e. norm = wire × 0.2. Recalibrate for other color sciences (ACEScct) on
 * real-footage validation before trusting large offsets there. */
export const OFFSET_WIRE_PER_NORM = 5;

/** Generate a gain+offset DRX and THROW if a non-identity affine decodes empty.
 * `gain`/`offset` are INTENT in display-normalized units: out = gain·in + offset (0..1).
 * The emitter converts to wire units (offset ×5; gain.master carries the achromatic
 * level — Resolve luma-renormalizes the RGB gain wheels, see generateAssertedGainDRX). */
export async function generateAssertedAffineDRX(gain, offset, label, outPath, warnings) {
  const master = 0.2126 * gain.r + 0.7152 * gain.g + 0.0722 * gain.b;
  // Wire offset range is ±1 (decode clamps beyond it — live-validated: wrote −1.22,
  // read back −1.0). Clamp HERE and warn so intent and wire never silently diverge.
  const wire = {};
  for (const k of ['r', 'g', 'b']) {
    const w = offset[k] * OFFSET_WIRE_PER_NORM;
    wire[k] = Math.max(-1, Math.min(1, w));
    if (w !== wire[k] && Array.isArray(warnings))
      warnings.push(`${label}: offset.${k} ${offset[k].toFixed(4)} (norm) exceeds the wire range ±1 (=±0.2 norm) — clamped; the black/white point will land short. Split the move across gain/lift or grade manually.`);
  }
  await drxTool.handler({
    action: 'generate',
    // gain/offset here are computed in raw DRX-internal units → pin to space:'drx'
    // (the tool default is 'ui', which would rescale offset by ÷25).
    args: {
      gradeParams: {
        space: 'drx',
        gain: [gain.r, gain.g, gain.b, master],
        offset: [wire.r, wire.g, wire.b, 0.0],
      },
      metadata: { label },
      outputPath: outPath,
    },
  });
  const back = await drxTool.handler({ action: 'parse', args: { content: fs.readFileSync(outPath, 'utf8') } });
  const got = (back.nodes || [])
    .flatMap((n) => (n.correctors || []).flatMap((c) => c.parameters || []))
    .filter((p) => /(gain|offset)\.(r|g|b)/i.test(p.name)).length;
  const nonIdentity = ['r', 'g', 'b'].some((k) => Math.abs(gain[k] - 1) > 0.002 || Math.abs(offset[k]) > 0.002);
  if (nonIdentity && got === 0)
    throw new Error(`round-trip assert FAILED: ${label} affine decoded EMPTY (gain ${JSON.stringify(gain)} offset ${JSON.stringify(offset)})`);
  return outPath;
}

/**
 * @param {Array<{id:string|number, png:string, group:string}>} clips
 * @param {{outDir:string, heroId?:string|number, clampGain?:[number,number],
 * clampOffset?:[number,number], maxCorrWarn?:number}} opts
 */
export async function computeContrastNormalize(clips, opts = {}) {
  if (!opts.outDir) throw new Error('opts.outDir required');
  const [glo, ghi] = opts.clampGain || [0.5, 2];
  const [olo, ohi] = opts.clampOffset || [-0.5, 0.5];
  const maxCorrWarn = opts.maxCorrWarn ?? 0.3;
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

  for (const [group, gclips] of byGroup) {
    for (const c of gclips) {
      c.bw = await measureBWPoints(c.png, opts);
    }
    const usable = gclips.filter((c) => c.bw);
    for (const c of gclips.filter((c) => !c.bw)) skipped.push({ id: c.id, group, reason: 'unreadable frame' });
    if (!usable.length) {
      report[group] = { error: 'no readable frames' };
      continue;
    }
    const hero = (opts.heroId != null && usable.find((c) => c.id === opts.heroId)) || usable[0];

    let maxCorr = 0;
    for (const c of usable) {
      const gain = {},
        offset = {};
      for (const k of ['r', 'g', 'b']) {
        const H = hero.bw[k],
          C = c.bw[k];
        const span = C.white - C.black || 1e-6;
        const scale = clamp((H.white - H.black) / span, glo, ghi);
        const shift = clamp(H.black - scale * C.black, olo, ohi);
        gain[k] = scale;
        offset[k] = shift;
      }
      const corr = Math.max(...['r', 'g', 'b'].map((k) => Math.max(Math.abs(gain[k] - 1), Math.abs(offset[k]))));
      maxCorr = Math.max(maxCorr, corr);
      const drxPath = `${opts.outDir}/${group}_${c.id}_contrast.drx`;
      await generateAssertedAffineDRX(gain, offset, provenanceLabel('contrast_normalize', { source: `hero:${hero.id}`, gist: gist('gain', gain) }), drxPath, warnings);
      grades.push({ id: c.id, group, gain, offset, correctionPct: +(100 * corr).toFixed(2), drxPath, isHero: c === hero });
    }
    report[group] = { clips: usable.length, hero_id: hero.id, max_correction_pct: +(100 * maxCorr).toFixed(2) };
    if (maxCorr > maxCorrWarn)
      warnings.push(
        `${group}: max contrast correction ${(100 * maxCorr).toFixed(1)}% — large; check the hero is representative and frames are display-referred.`,
      );
  }
  return { grades, report, warnings, skipped };
}
