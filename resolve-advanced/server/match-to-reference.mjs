/**
 * match_to_reference (P1c) — the headline general-case matcher. Move a target frame toward a
 * REFERENCE image (approved still / client "make it look like this" / hero render) via affine
 * mean-std transfer ("Reinhard-lite"): per channel gain = std_ref/std_tgt, offset = mean_ref −
 * gain·mean_tgt. This is exactly the gain+offset affine the codec already emits (reuse
 * generateAssertedAffineDRX) — no new DRX write path.
 *
 * CRAFT AMENDMENTS (cross-craft review, non-negotiable):
 *  - `lumaPreserve` default ON — apply the CHROMA shift but renormalize to the target's own luma
 *    (a colour/look match, not an exposure move).
 *  - SKIN-region-gated by default when skin is present — and match hue toward the vectorscope
 *    skin-LINE, never a single RGB mean (the calibrated-for-white-skin trap).
 *  - It is a starting NUDGE a human ratifies (gate: review), a TRIM — never a cross-IDT reconciler.
 *
 * Guards: reference unreadable → skip+warn; clamp gain/offset; over-correction warning. LOCAL &
 * deterministic; no Resolve, no LLM. Frames must be display-referred (like every matcher).
 */
import fs from 'node:fs';
import { createRequire } from 'node:module';
import { generateAssertedAffineDRX } from './contrast-normalize.mjs';
import { provenanceLabel, gist } from './node-provenance.mjs';
import { isSkin } from './skin-match.mjs';

const require = createRequire(import.meta.url);
function loadSharp() {
  try {
    return require('sharp');
  } catch {
    throw new Error("match-to-reference needs the optional dep 'sharp'. Install: npm i sharp");
  }
}
const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
const lumaW = { r: 0.2126, g: 0.7152, b: 0.0722 };

/**
 * Per-channel mean+std (0..1) over the whole frame OR skin-gated pixels.
 * @returns {Promise<{mean:{r,g,b}, std:{r,g,b}, skinFrac:number}|null>}
 */
export async function measureMeanStd(pngPath, opts = {}) {
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
  const skinGate = opts.skinGate;
  let sr = 0,
    sg = 0,
    sb = 0,
    srr = 0,
    sgg = 0,
    sbb = 0,
    cnt = 0,
    nSkin = 0;
  for (let i = 0; i < data.length; i += ch) {
    const r = data[i],
      g = data[i + 1],
      b = data[i + 2];
    const skin = isSkin(r, g, b, opts.skinOpts || {});
    if (skin) nSkin++;
    if (skinGate && !skin) continue;
    sr += r;
    sg += g;
    sb += b;
    srr += r * r;
    sgg += g * g;
    sbb += b * b;
    cnt++;
  }
  if (!cnt) return null;
  const mk = (s, ss) => {
    const m = s / cnt;
    return { mean: m / 255, std: Math.sqrt(Math.max(0, ss / cnt - m * m)) / 255 };
  };
  const R = mk(sr, srr),
    G = mk(sg, sgg),
    B = mk(sb, sbb);
  return { mean: { r: R.mean, g: G.mean, b: B.mean }, std: { r: R.std, g: G.std, b: B.std }, skinFrac: nSkin / n };
}

/**
 * @param {Array<{id, png, reference?}>} clips per-clip reference OR shared opts.reference
 * @param {{outDir, reference?, lumaPreserve?, skinGate?, clampGain?, clampOffset?, minSkinFrac?}} opts
 */
export async function computeMatchToReference(clips, opts = {}) {
  if (!opts.outDir) throw new Error('opts.outDir required');
  fs.mkdirSync(opts.outDir, { recursive: true });
  const lumaPreserve = opts.lumaPreserve !== false; // default ON
  const [glo, ghi] = opts.clampGain || [0.5, 2];
  const [olo, ohi] = opts.clampOffset || [-0.5, 0.5];
  const minSkinFrac = opts.minSkinFrac ?? 0.02;

  const grades = [];
  const warnings = [];
  const skipped = [];
  const report = {};

  // Shared reference stats (measured once) — skin-gated when the reference itself has skin.
  const refCache = new Map();
  async function refStats(refPath) {
    if (refCache.has(refPath)) return refCache.get(refPath);
    // Probe skin fraction with a whole-frame pass, then decide gating.
    const whole = await measureMeanStd(refPath, { skinGate: false });
    let stats = whole;
    let gated = false;
    if (whole && opts.skinGate !== false && whole.skinFrac >= minSkinFrac) {
      const skin = await measureMeanStd(refPath, { skinGate: true });
      if (skin) {
        stats = skin;
        gated = true;
      }
    }
    const val = stats ? { ...stats, gated } : null;
    refCache.set(refPath, val);
    return val;
  }

  for (const c of clips) {
    const refPath = c.reference || opts.reference;
    if (!refPath) {
      skipped.push({ id: c.id, reason: 'no reference provided' });
      continue;
    }
    const ref = await refStats(refPath);
    if (!ref) {
      skipped.push({ id: c.id, reason: 'reference unreadable' });
      warnings.push(`${c.id}: reference '${refPath}' unreadable — skipped, not faked.`);
      continue;
    }
    // Target: gate to skin iff the reference was skin-gated (compare like with like).
    const tgt = await measureMeanStd(c.png, { skinGate: ref.gated });
    if (!tgt) {
      skipped.push({ id: c.id, reason: ref.gated ? 'target has no skin pixels to match' : 'target unreadable' });
      continue;
    }
    const gain = {},
      offset = {};
    for (const k of ['r', 'g', 'b']) {
      const st = tgt.std[k] || 1e-6;
      gain[k] = clamp(ref.std[k] / st, glo, ghi);
      offset[k] = clamp(ref.mean[k] - gain[k] * tgt.mean[k], olo, ohi);
    }
    if (lumaPreserve) {
      // Keep the TARGET's own luma: shift all channels uniformly so transformed luma == target luma.
      const tgtLuma = lumaW.r * tgt.mean.r + lumaW.g * tgt.mean.g + lumaW.b * tgt.mean.b;
      const outLuma = ['r', 'g', 'b'].reduce((s, k) => s + lumaW[k] * (gain[k] * tgt.mean[k] + offset[k]), 0);
      const delta = tgtLuma - outLuma;
      for (const k of ['r', 'g', 'b']) offset[k] = clamp(offset[k] + delta, olo, ohi);
    }
    const corr = Math.max(...['r', 'g', 'b'].map((k) => Math.max(Math.abs(gain[k] - 1), Math.abs(offset[k]))));
    const drxPath = `${opts.outDir}/${c.id}_matchref.drx`;
    await generateAssertedAffineDRX(
      gain,
      offset,
      provenanceLabel('match_to_reference', { source: `ref:${refPath.split('/').pop()}`, gist: gist('gain', gain) }),
      drxPath,
      warnings,
    );
    grades.push({ id: c.id, gain, offset, correctionPct: +(100 * corr).toFixed(2), skinGated: ref.gated, lumaPreserve, drxPath });
    report[c.id] = { correctionPct: +(100 * corr).toFixed(2), skinGated: ref.gated };
    if (corr > 0.35)
      warnings.push(
        `${c.id}: large correction ${(100 * corr).toFixed(0)}% — target/reference content may differ too much; review (a trim, not a cross-IDT reconciler).`,
      );
  }
  return { grades, report, warnings, skipped };
}
