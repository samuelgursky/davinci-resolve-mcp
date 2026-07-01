/**
 * extract_frames (Phase-1a) — the missing front door. ffmpeg-extract DISPLAY-REFERRED
 * frames at oracle/midpoint/TC positions so the whole grading catalog is usable standalone
 * (today extraction is "the caller's job").
 *
 * THE CRUX is the working space (cross-craft review, hard rule): the matchers' skin/tone
 * gates assume Rec.709/sRGB. SLog3 measured raw is garbage, and a caller-supplied-CDL
 * SLog3→709 approximation is DANGEROUS (you'd match the approximation's artifacts). So this
 * tool HARD-REFUSES a log/scene-referred source — it never approximates. Accepted:
 *   - a source ffprobe reports as a known DISPLAY transfer (bt709/601/sRGB/HLG/PQ), or
 *   - an explicit display-referred proxy/render path (opts.proxy / clip.proxy), or
 *   - an explicit caller assertion `displayReferred:true` when ffprobe can't tell (unknown).
 * A known LOG transfer, or 'log' anywhere in the stream tags → THROW. Unknown + no assertion
 * → THROW (skip-not-fake). Resolve against real camera-log footage with a post-ODT render.
 *
 * Silent-lie guard: assert the extracted PNG has bytes>0 (an empty file is the empty-green lie).
 * Deps: ffmpeg + ffprobe on PATH (peer dep; not bundled — GPL). No Resolve, no LLM.
 */
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { requireFfmpeg } from './capabilities.mjs';

// color_transfer values that are DISPLAY-referred (SDR + HDR display). Camera log
// (SLog3/LogC/RedLog) is NOT in ffmpeg's enum — it shows as 'unknown' → we refuse unless asserted.
const DISPLAY_TRANSFERS = new Set([
  'bt709',
  'smpte170m',
  'bt470m',
  'bt470bg',
  'gamma22',
  'gamma28',
  'iec61966-2-1', // sRGB
  'srgb',
  'bt2020-10',
  'bt2020-12',
  'smpte2084', // PQ (HDR display-referred)
  'arib-std-b67', // HLG (HDR display-referred)
]);
// Explicitly scene-referred / camera-log transfers → hard refuse.
const LOG_TRANSFERS = new Set(['log100', 'log316']);
// Known DISPLAY matrices — a fallback display signal when the transfer tag was dropped by the
// muxer (common: libx264/mp4 keeps color_space but not color_transfer). A Rec.709/601 matrix
// strongly implies display-referred SDR. NOT bt2020nc (wide-gamut; ambiguous) — stay conservative.
const DISPLAY_MATRICES = new Set(['bt709', 'smpte170m', 'bt470bg', 'fcc', 'smpte240m']);

/** Probe a media file's video stream: colorspace tags + frame count + fps. */
export function probeStream(source, { ffprobe = 'ffprobe' } = {}) {
  const r = spawnSync(
    ffprobe,
    [
      '-v',
      'error',
      '-select_streams',
      'v:0',
      '-show_entries',
      'stream=color_transfer,color_space,color_primaries,nb_frames,r_frame_rate,duration:stream_tags=color_transfer',
      '-of',
      'json',
      source,
    ],
    { encoding: 'utf8', timeout: 15000 },
  );
  if (r.status !== 0) throw new Error(`ffprobe failed on ${source}: ${(r.stderr || '').slice(-300)}`);
  const j = JSON.parse(r.stdout || '{}');
  const s = (j.streams && j.streams[0]) || {};
  const [num, den] = String(s.r_frame_rate || '0/1')
    .split('/')
    .map(Number);
  const fps = den ? num / den : 0;
  let frameCount = Number(s.nb_frames) || 0;
  if (!frameCount && s.duration && fps) frameCount = Math.round(Number(s.duration) * fps);
  return {
    colorTransfer: s.color_transfer || (s.tags && s.tags.color_transfer) || 'unknown',
    colorSpace: s.color_space || 'unknown',
    colorPrimaries: s.color_primaries || 'unknown',
    fps,
    frameCount,
    duration: Number(s.duration) || 0,
  };
}

/**
 * Decide if a source is safe (display-referred) to measure, or must be refused.
 * @returns {{ok:true, transfer:string, reason:string} | {ok:false, transfer:string, reason:string}}
 */
export function assessColorspace(probe, opts = {}) {
  const t = String(probe.colorTransfer || 'unknown').toLowerCase();
  if (t.includes('log') || LOG_TRANSFERS.has(t)) {
    return {
      ok: false,
      transfer: t,
      reason: `source transfer '${t}' is LOG/scene-referred — refuse (no approximation; use a post-ODT display-referred render/proxy)`,
    };
  }
  if (DISPLAY_TRANSFERS.has(t)) return { ok: true, transfer: t, reason: `display-referred transfer '${t}'` };
  // Transfer tag missing/unknown but a known display MATRIX survived → treat as display-referred SDR.
  const cs = String(probe.colorSpace || 'unknown').toLowerCase();
  if (DISPLAY_MATRICES.has(cs))
    return { ok: true, transfer: t, matrix: cs, reason: `transfer '${t}' unknown but display matrix '${cs}' → display-referred SDR` };
  // Unknown: camera log commonly probes as 'unknown'. Only proceed if the caller asserts.
  if (opts.displayReferred) return { ok: true, transfer: t, reason: `transfer '${t}' unknown; caller asserts displayReferred` };
  return {
    ok: false,
    transfer: t,
    reason: `source transfer '${t}' is UNKNOWN — camera log often probes as unknown. Point at a display-referred proxy/render, or pass displayReferred:true if you KNOW it's Rec.709/sRGB.`,
  };
}

/** Resolve an `at` position to a 0-based frame index. */
export function resolvePosition(at, probe) {
  if (typeof at === 'number') return Math.max(0, Math.round(at));
  if (at == null || at === 'midpoint') return Math.max(0, Math.floor((probe.frameCount || 1) / 2));
  if (typeof at === 'string' && at.includes(':')) {
    // TC HH:MM:SS:FF → frame index via fps
    const parts = at.split(':').map(Number);
    if (parts.length === 4 && probe.fps) {
      const [h, m, s, f] = parts;
      return Math.max(0, Math.round((h * 3600 + m * 60 + s) * probe.fps) + f);
    }
  }
  throw new Error(`extract_frames: cannot resolve position '${at}'`);
}

function runFfmpegToFile(args, ffmpegPath) {
  return new Promise((resolve, reject) => {
    const proc = spawn(ffmpegPath, args, { stdio: ['ignore', 'ignore', 'pipe'] });
    const err = [];
    proc.stderr.on('data', (d) => err.push(d));
    proc.on('error', reject);
    proc.on('close', (code) => (code === 0 ? resolve() : reject(new Error(`ffmpeg exited ${code}: ${Buffer.concat(err).toString().slice(-300)}`))));
  });
}

/**
 * @param {Array<{id:string|number, source:string, at?:any, proxy?:string, displayReferred?:boolean}>} clips
 * @param {{outDir:string, ffmpeg?:string, ffprobe?:string, displayReferred?:boolean}} opts
 * @returns {Promise<{frames:Object, skipped:Array, warnings:string[]}>}  frames = { id → png path }
 */
export async function extractFrames(clips, opts = {}) {
  requireFfmpeg();
  if (!opts.outDir) throw new Error('opts.outDir required');
  fs.mkdirSync(opts.outDir, { recursive: true });
  const ffmpeg = opts.ffmpeg || 'ffmpeg';
  const ffprobe = opts.ffprobe || 'ffprobe';
  const frames = {};
  const skipped = [];
  const warnings = [];

  for (const c of clips) {
    const src = c.proxy || opts.proxy || c.source;
    let probe;
    try {
      probe = probeStream(src, { ffprobe });
    } catch (e) {
      skipped.push({ id: c.id, reason: `probe failed: ${e.message}` });
      continue;
    }
    const assess = assessColorspace(probe, { displayReferred: c.displayReferred ?? opts.displayReferred });
    if (!assess.ok) {
      // HARD refuse — never approximate a log source into a display-referred measurement.
      skipped.push({ id: c.id, reason: assess.reason, transfer: assess.transfer });
      continue;
    }
    let frameIdx;
    try {
      frameIdx = resolvePosition(c.at, probe);
    } catch (e) {
      skipped.push({ id: c.id, reason: e.message });
      continue;
    }
    const outPng = path.join(opts.outDir, `${c.id}.png`);
    const args = ['-v', 'error', '-i', src, '-vf', `select=eq(n\\,${frameIdx})`, '-vframes', '1', '-y', outPng];
    try {
      await runFfmpegToFile(args, ffmpeg);
    } catch (e) {
      skipped.push({ id: c.id, reason: `extract failed: ${e.message}` });
      continue;
    }
    // Silent-lie guard: assert bytes were actually written.
    let sz = 0;
    try {
      sz = fs.statSync(outPng).size;
    } catch {
      sz = 0;
    }
    if (!sz) {
      skipped.push({ id: c.id, reason: `extracted 0 bytes (frame ${frameIdx} out of range?)` });
      continue;
    }
    frames[c.id] = outPng;
    if (assess.transfer === 'smpte2084' || assess.transfer === 'arib-std-b67')
      warnings.push(`${c.id}: HDR transfer '${assess.transfer}' — display-referred but the SDR matchers' 16–235 assumptions differ; verify.`);
  }
  return { frames, skipped, warnings };
}
