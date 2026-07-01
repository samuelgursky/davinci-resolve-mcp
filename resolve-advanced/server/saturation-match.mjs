/**
 * saturation_match (P1d) — skin/overall saturation cohesion. Scale each clip's saturation
 * toward a hero/reference so a scene reads with consistent chroma. Emits a Primary saturation
 * grade (the codec maps value/50 → the multiplier, so value = 50·satScale).
 *
 * skin mode gates saturation to skin pixels (a face's chroma must be consistent across cameras);
 * overall mode uses the whole frame. LOCAL & deterministic; no Resolve. Round-trip-asserted.
 */
import fs from 'node:fs';
import { createRequire } from 'node:module';
import { drxTool } from './tools/drx.mjs';
import { provenanceLabel } from './node-provenance.mjs';
import { isSkin } from './skin-match.mjs';

const require = createRequire(import.meta.url);
function loadSharp() {
  try {
    return require('sharp');
  } catch {
    throw new Error("saturation-match needs the optional dep 'sharp'. Install: npm i sharp");
  }
}
const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
const satOf = (r, g, b) => {
  const mx = Math.max(r, g, b),
    mn = Math.min(r, g, b);
  return mx ? (mx - mn) / mx : 0;
};

/** Mean HSV saturation (0..1), whole-frame or skin-gated. Returns {sat, skinFrac} or null. */
export async function measureSaturation(pngPath, opts = {}) {
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
  let s = 0,
    cnt = 0,
    nSkin = 0;
  for (let i = 0; i < data.length; i += ch) {
    const r = data[i],
      g = data[i + 1],
      b = data[i + 2];
    const skin = isSkin(r, g, b, opts.skinOpts || {});
    if (skin) nSkin++;
    if (opts.skinGate && !skin) continue;
    s += satOf(r, g, b);
    cnt++;
  }
  if (!cnt) return null;
  return { sat: s / cnt, skinFrac: nSkin / n };
}

/** Generate a saturation grade + THROW if a non-unity sat scale decodes empty. */
export async function generateAssertedSatDRX(satScale, label, outPath) {
  // satScale (neutral 1.0) -> panel units (neutral 50) -> pin space:'ui' so the
  // conversion stays correct regardless of the space default.
  const value = clamp(50 * satScale, 0, 100);
  await drxTool.handler({ action: 'generate', args: { gradeParams: { space: 'ui', saturation: value }, metadata: { label }, outputPath: outPath } });
  const back = await drxTool.handler({ action: 'parse', args: { content: fs.readFileSync(outPath, 'utf8') } });
  const got = (back.nodes || []).flatMap((n) => (n.correctors || []).flatMap((c) => c.parameters || [])).filter((p) => /sat/i.test(p.name)).length;
  if (Math.abs(satScale - 1) > 0.01 && got === 0) throw new Error(`round-trip assert FAILED: ${label} sat scale ${satScale} decoded EMPTY`);
  return outPath;
}

/**
 * @param {Array<{id, png, group?}>} clips
 * @param {{outDir, mode?:'overall'|'skin', heroId?, clampScale?:[number,number], minSkinFrac?}} opts
 */
export async function computeSaturationMatch(clips, opts = {}) {
  if (!opts.outDir) throw new Error('opts.outDir required');
  fs.mkdirSync(opts.outDir, { recursive: true });
  const mode = opts.mode || 'overall';
  const skinGate = mode === 'skin';
  const [lo, hi] = opts.clampScale || [0.5, 2];
  const minSkinFrac = opts.minSkinFrac ?? 0.02;

  for (const c of clips) {
    const m = await measureSaturation(c.png, { skinGate });
    c.sat = m ? m.sat : null;
    c.skinFrac = m ? m.skinFrac : 0;
  }
  const usable = clips.filter((c) => c.sat != null && (!skinGate || c.skinFrac >= minSkinFrac));
  const skipped = clips.filter((c) => !usable.includes(c)).map((c) => ({ id: c.id, reason: skinGate ? 'insufficient skin' : 'unreadable' }));
  if (!usable.length) return { grades: [], report: { error: 'no usable clips' }, warnings: [], skipped };

  const hero = (opts.heroId != null && usable.find((c) => c.id === opts.heroId)) || usable[0];
  const grades = [];
  const warnings = [];
  let maxCorr = 0;
  for (const c of usable) {
    const scale = clamp((hero.sat || 1e-6) / (c.sat || 1e-6), lo, hi);
    const corr = Math.abs(scale - 1);
    maxCorr = Math.max(maxCorr, corr);
    const drxPath = `${opts.outDir}/${c.id}_sat.drx`;
    await generateAssertedSatDRX(scale, provenanceLabel('saturation_match', { source: `hero:${hero.id}`, gist: `sat(${scale.toFixed(2)})` }), drxPath);
    grades.push({ id: c.id, satScale: +scale.toFixed(3), correctionPct: +(100 * corr).toFixed(2), drxPath, isHero: c === hero });
  }
  if (maxCorr > 0.4) warnings.push(`saturation correction up to ${(100 * maxCorr).toFixed(0)}% — check the hero is representative before applying.`);
  return { grades, report: { mode, hero_id: hero.id, max_correction_pct: +(100 * maxCorr).toFixed(2) }, warnings, skipped };
}
