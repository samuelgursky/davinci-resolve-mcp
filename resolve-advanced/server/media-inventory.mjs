/**
 * Cluster M — media_inventory (ffprobe) + sync (TC/waveform). Turns cards/turnovers into a
 * manifest and a consistency report; pairs picture↔sound by timecode with drift + MOS flags.
 *
 * media_inventory: fps/codec/colorspace/TC/audio per file + consistency (mixed fps, wrong-space
 *   metadata, card-sequence gaps). Deps: ffprobe (peer).
 * sync: TC-based picture↔sound pairing with per-take offset, long-take drift, and MOS flags.
 *   PURE over a supplied metadata list (fps + TC in/out); waveform-correlation refinement is a
 *   documented follow-up (offset from TC is the deterministic core, honest about its scope).
 *
 * No Resolve, no LLM.
 */
import path from 'node:path';
import { probeMedia } from './ffprobe-media.mjs';

// ── timecode ───────────────────────────────────────────────────────────
/** "HH:MM:SS:FF" (or ';' DF) → integer frames at fps. Returns null if unparseable. */
export function tcToFrames(tc, fps) {
  if (typeof tc !== 'string' || !fps) return null;
  const m = /^(\d{1,2}):(\d{2}):(\d{2})[:;](\d{2,3})$/.exec(tc.trim());
  if (!m) return null;
  const [, h, mm, s, f] = m.map(Number);
  return Math.round((h * 3600 + mm * 60 + s) * fps) + f;
}

export function framesToTc(frames, fps) {
  if (!fps) return null;
  const fpsI = Math.round(fps);
  const f = frames % fpsI;
  const totalSec = Math.floor(frames / fpsI);
  const s = totalSec % 60;
  const mm = Math.floor(totalSec / 60) % 60;
  const h = Math.floor(totalSec / 3600);
  const p2 = (n) => String(n).padStart(2, '0');
  return `${p2(h)}:${p2(mm)}:${p2(s)}:${p2(f)}`;
}

// ── media_inventory ────────────────────────────────────────────────────
// Reel/clip parse for card-gap detection, e.g. A001C012, A001_C012, A001 C012.
const REEL_CLIP_RE = /([A-Z]\d{2,3})[_ ]?C(\d{2,4})/i;

/**
 * @param {Array<{id?:string, path:string, expectedColorspace?:string}>} files
 * @param {{ffprobe?:string}} [opts]
 */
export function mediaInventory(files, opts = {}) {
  const items = [];
  const skipped = [];
  for (const f of files) {
    const p = typeof f === 'string' ? f : f.path;
    const probe = probeMedia(p, opts);
    if (!probe) {
      skipped.push({ path: p, reason: 'unreadable / not media' });
      continue;
    }
    const v = probe.video || {};
    const a0 = (probe.audio || [])[0] || {};
    items.push({
      id: (typeof f === 'object' && f.id) || path.basename(p),
      name: path.basename(p),
      fps: v.fps || null,
      codec: v.codec || null,
      width: v.width || null,
      height: v.height || null,
      colorTransfer: v.colorTransfer || null,
      colorPrimaries: v.colorPrimaries || null,
      colorMatrix: v.colorMatrix || null,
      timecode: probe.format.timecode || null,
      audioChannels: (probe.audio || []).reduce((n, a) => n + (a.channels || 0), 0),
      audioSampleRate: a0.sampleRate || null,
      duration: probe.format.duration,
      expectedColorspace: (typeof f === 'object' && f.expectedColorspace) || null,
    });
  }
  // Consistency.
  const distinct = (key) => [...new Set(items.map((i) => i[key]).filter((x) => x != null))];
  const fpsSet = distinct('fps');
  const warnings = [];
  if (fpsSet.length > 1) warnings.push(`mixed frame rates across cards: ${fpsSet.join(', ')}`);
  for (const it of items) {
    if (it.expectedColorspace && it.colorTransfer && it.colorTransfer !== 'unknown' && it.colorTransfer.toLowerCase() !== it.expectedColorspace.toLowerCase())
      warnings.push(`${it.name}: color transfer '${it.colorTransfer}' ≠ expected '${it.expectedColorspace}'`);
    if (it.audioChannels === 0) warnings.push(`${it.name}: no audio channels (MOS?)`);
  }
  // Card-sequence gaps.
  const byReel = new Map();
  for (const it of items) {
    const m = REEL_CLIP_RE.exec(it.name);
    if (!m) continue;
    const reel = m[1].toUpperCase();
    const clip = Number(m[2]);
    if (!byReel.has(reel)) byReel.set(reel, []);
    byReel.get(reel).push(clip);
  }
  const cardGaps = [];
  for (const [reel, nums] of byReel) {
    nums.sort((a, b) => a - b);
    const missing = [];
    for (let n = nums[0]; n <= nums[nums.length - 1]; n++) if (!nums.includes(n)) missing.push(n);
    if (missing.length) cardGaps.push({ reel, present: nums, missing });
  }
  if (cardGaps.length) warnings.push(`card-sequence gaps: ${cardGaps.map((g) => `${g.reel}[${g.missing.join(',')}]`).join(' ')}`);

  return {
    count: items.length,
    items,
    consistency: { frameRates: fpsSet, codecs: distinct('codec'), colorTransfers: distinct('colorTransfer'), mixedFps: fpsSet.length > 1, cardGaps },
    warnings,
    skipped,
  };
}

// ── sync (TC-based) ────────────────────────────────────────────────────
/**
 * Pair picture↔sound by timecode overlap; per-take offset + long-take drift + MOS flags. PURE.
 * @param {Array<{id, type:'picture'|'sound', tcStart:string, tcEnd?:string, fps:number, hasAudio?:boolean, durationFrames?:number}>} clips
 * @param {{driftToleranceFrames?:number, longTakeFrames?:number}} [opts]
 */
export function syncByTC(clips, opts = {}) {
  const driftTol = opts.driftToleranceFrames ?? 2;
  const longTake = opts.longTakeFrames ?? 3600; // ~2min @30 → "long take" where drift matters
  const pics = clips.filter((c) => c.type === 'picture');
  const sounds = clips.filter((c) => c.type === 'sound');
  const spanOf = (c) => {
    const start = tcToFrames(c.tcStart, c.fps);
    if (start == null) return null;
    const len = c.durationFrames ?? (c.tcEnd ? tcToFrames(c.tcEnd, c.fps) - start : null);
    return { start, end: len != null ? start + len : null, len };
  };
  const pairs = [];
  const mos = [];
  const usedSound = new Set();
  for (const pic of pics) {
    const ps = spanOf(pic);
    if (pic.hasAudio === false || !sounds.length) {
      if (pic.hasAudio === false) mos.push({ id: pic.id, reason: 'flagged MOS (no sync audio)' });
    }
    // Find the sound whose TC span overlaps the most.
    let best = null,
      bestOverlap = -1;
    for (const snd of sounds) {
      if (usedSound.has(snd.id)) continue;
      const ss = spanOf(snd);
      if (!ps || !ss || ps.end == null || ss.end == null) continue;
      const overlap = Math.min(ps.end, ss.end) - Math.max(ps.start, ss.start);
      if (overlap > bestOverlap) {
        bestOverlap = overlap;
        best = { snd, ss };
      }
    }
    if (best && bestOverlap > 0) {
      usedSound.add(best.snd.id);
      const offsetFrames = best.ss.start - ps.start;
      // Drift: on a long take, a length mismatch beyond tol suggests clock drift / pulldown slip.
      let drift = null;
      if (ps.len != null && best.ss.len != null) {
        const lenDelta = best.ss.len - ps.len;
        const isLong = Math.max(ps.len, best.ss.len) >= longTake;
        drift = { lenDeltaFrames: lenDelta, longTake: isLong, flagged: Math.abs(lenDelta) > driftTol && isLong };
      }
      pairs.push({ picture: pic.id, sound: best.snd.id, offsetFrames, drift });
    } else if (pic.hasAudio !== false) {
      mos.push({ id: pic.id, reason: 'no overlapping sound found (guide-track only / MOS?)' });
    }
  }
  const unmatchedSound = sounds.filter((s) => !usedSound.has(s.id)).map((s) => s.id);
  const driftFlags = pairs.filter((p) => p.drift && p.drift.flagged).map((p) => p.picture);
  return { pairs, mos, unmatchedSound, driftFlags, note: 'TC-based pairing (deterministic). Waveform cross-correlation is a follow-up refinement.' };
}
