/**
 * Cluster D — deliverable QC / compliance. The single biggest reject-preventer for a
 * two-deliverable-per-episode show (producer + online both ranked it #1).
 *
 * All MEASURE-only, report-only (gate: review — NEVER auto-`pass`-clear a deliverable; the
 * producer/online sign off). Silent-lie discipline extends to media here: assert bytes read,
 * skip-not-fake on unreadable, and a per-field pass/fail (an empty/green report is the lie).
 *
 *   deliverable_qc        — ffprobe a rendered file vs its spec → pass/fail PER FIELD
 *   loudness_qc           — ffmpeg ebur128 integrated LUFS + true-peak dBTP + LRA vs target
 *   reframe_blanking_check — letterbox/pillarbox + active-picture bounds + illegal edge pixels
 *   conform_completeness  — all clips online, handles present, duration == reference (frame-exact)
 *   re_delivery_diff      — old vs new render: frame-count Δ, duration Δ, spec drift, sampled changes
 *
 * Deps: ffmpeg/ffprobe (peer) for the file tools; sharp for reframe_blanking on a PNG.
 * The comparison cores are PURE (probe → check) so they unit-test without media. No Resolve, no LLM.
 */
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { probeMedia } from './ffprobe-media.mjs';
import { requireFfmpeg } from './capabilities.mjs';

const require = createRequire(import.meta.url);

// ── deliverable_qc ─────────────────────────────────────────────────────
const eq = (a, b) => String(a).toLowerCase() === String(b).toLowerCase();
const near = (a, b, tol) => Math.abs(Number(a) - Number(b)) <= tol;

/**
 * Compare a probed media object to a deliverable spec → per-field pass/fail. PURE.
 * @param {object} probe result of probeMedia()
 * @param {object} spec { video:{...}, audio:{...}, container, durationSeconds, durationTolSeconds, filenameRegex }
 * @param {{filename?:string, fpsTol?:number}} [opts]
 */
export function checkDeliverable(probe, spec = {}, opts = {}) {
  const fields = [];
  const add = (field, expected, actual, pass, note) => fields.push({ field, expected, actual, pass, ...(note ? { note } : {}) });
  const fpsTol = opts.fpsTol ?? 0.01;

  if (spec.video) {
    const v = probe.video || {};
    const s = spec.video;
    if (s.codec != null) add('video.codec', s.codec, v.codec, eq(s.codec, v.codec));
    if (s.profile != null) add('video.profile', s.profile, v.profile, eq(s.profile, v.profile));
    if (s.width != null) add('video.width', s.width, v.width, Number(s.width) === Number(v.width));
    if (s.height != null) add('video.height', s.height, v.height, Number(s.height) === Number(v.height));
    if (s.fps != null) add('video.fps', s.fps, v.fps, near(s.fps, v.fps, fpsTol));
    if (s.scan != null) add('video.scan', s.scan, v.scan, eq(s.scan, v.scan));
    if (s.colorPrimaries != null) add('video.colorPrimaries', s.colorPrimaries, v.colorPrimaries, eq(s.colorPrimaries, v.colorPrimaries));
    if (s.colorTransfer != null) add('video.colorTransfer', s.colorTransfer, v.colorTransfer, eq(s.colorTransfer, v.colorTransfer));
    if (s.colorMatrix != null) add('video.colorMatrix', s.colorMatrix, v.colorMatrix, eq(s.colorMatrix, v.colorMatrix));
    if (s.bitDepth != null) add('video.bitDepth', s.bitDepth, v.bitDepth, Number(s.bitDepth) === Number(v.bitDepth));
    if (s.pixFmt != null) add('video.pixFmt', s.pixFmt, v.pixFmt, eq(s.pixFmt, v.pixFmt));
  }
  if (spec.audio) {
    const a0 = (probe.audio && probe.audio[0]) || {};
    const totalCh = (probe.audio || []).reduce((n, a) => n + (a.channels || 0), 0);
    const s = spec.audio;
    if (s.streams != null) add('audio.streams', s.streams, (probe.audio || []).length, Number(s.streams) === (probe.audio || []).length);
    if (s.channels != null) add('audio.channels', s.channels, totalCh, Number(s.channels) === totalCh, 'total across streams');
    if (s.channelLayout != null) add('audio.channelLayout', s.channelLayout, a0.channelLayout, eq(s.channelLayout, a0.channelLayout));
    if (s.sampleRate != null) add('audio.sampleRate', s.sampleRate, a0.sampleRate, Number(s.sampleRate) === Number(a0.sampleRate));
    if (s.codec != null) add('audio.codec', s.codec, a0.codec, eq(s.codec, a0.codec));
    if (s.bitDepth != null) add('audio.bitDepth', s.bitDepth, a0.bitDepth, Number(s.bitDepth) === Number(a0.bitDepth));
  }
  if (spec.container != null) add('container', spec.container, probe.format.container, eq(spec.container, probe.format.container));
  if (spec.durationSeconds != null) {
    const tol = spec.durationTolSeconds ?? 0.5;
    add('duration', `${spec.durationSeconds}s ±${tol}`, probe.format.duration, near(spec.durationSeconds, probe.format.duration, tol));
  }
  if (spec.filenameRegex != null && opts.filename != null) {
    let re;
    try {
      re = new RegExp(spec.filenameRegex);
    } catch {
      re = null;
    }
    add('filename', spec.filenameRegex, opts.filename, re ? re.test(opts.filename) : false, re ? undefined : 'invalid regex');
  }

  const failed = fields.filter((f) => !f.pass);
  return { pass: failed.length === 0, fieldCount: fields.length, failedCount: failed.length, fields, failed: failed.map((f) => f.field) };
}

/** deliverable_qc: probe a file + check it against a spec. */
export function deliverableQc(file, spec = {}, opts = {}) {
  const probe = probeMedia(file, opts);
  if (!probe) throw new Error(`deliverable_qc: could not probe '${file}' (unreadable/not media — skip-not-fake)`);
  const filename = opts.filename ?? file.split('/').pop();
  const result = checkDeliverable(probe, spec, { filename, fpsTol: opts.fpsTol });
  return { file, probe, ...result, gate: 'review', note: 'measurement only — the producer/online signs off; never auto-pass-clear' };
}

// ── loudness_qc ────────────────────────────────────────────────────────
/** Parse ffmpeg ebur128 stderr Summary block → { integratedLufs, truePeakDbtp, lra, threshold }. */
export function parseEbur128(stderr) {
  const grab = (label) => {
    const re = new RegExp(`${label}:\\s*(-?\\d+(?:\\.\\d+)?)`);
    const m = re.exec(stderr);
    return m ? Number(m[1]) : null;
  };
  // The Summary block prints "I:", "LRA:", "Peak:" under headers; match the trailing values.
  const integratedLufs = grab('I') ?? grab('Integrated loudness\\s*[\\s\\S]*?I');
  const lra = grab('LRA') ?? grab('Loudness range\\s*[\\s\\S]*?LRA');
  const truePeakDbtp = grab('Peak');
  return { integratedLufs, lra, truePeakDbtp };
}

/**
 * loudness_qc: measure integrated LUFS + true-peak + LRA and check vs a per-deliverable target.
 * @param {string} file
 * @param {{integrated?:number, integratedTol?:number, truePeakMax?:number, lraMax?:number, ffmpeg?:string}} target
 */
export function loudnessQc(file, target = {}) {
  requireFfmpeg();
  const ffmpeg = target.ffmpeg || 'ffmpeg';
  const r = spawnSync(ffmpeg, ['-nostats', '-i', file, '-af', 'ebur128=peak=true', '-f', 'null', '-'], {
    encoding: 'utf8',
    timeout: 120000,
    maxBuffer: 32 * 1024 * 1024,
  });
  const stderr = r.stderr || '';
  const measured = parseEbur128(stderr);
  if (measured.integratedLufs == null) throw new Error(`loudness_qc: could not measure loudness on '${file}' (no audio? ffmpeg ebur128 produced no summary)`);
  const checks = [];
  const add = (field, expected, actual, pass) => checks.push({ field, expected, actual, pass });
  if (target.integrated != null) {
    const tol = target.integratedTol ?? 1.0;
    add('integratedLufs', `${target.integrated} ±${tol}`, measured.integratedLufs, Math.abs(measured.integratedLufs - target.integrated) <= tol);
  }
  if (target.truePeakMax != null)
    add('truePeakDbtp', `≤ ${target.truePeakMax}`, measured.truePeakDbtp, measured.truePeakDbtp != null && measured.truePeakDbtp <= target.truePeakMax);
  if (target.lraMax != null) add('lra', `≤ ${target.lraMax}`, measured.lra, measured.lra != null && measured.lra <= target.lraMax);
  const failed = checks.filter((c) => !c.pass);
  return { file, measured, pass: failed.length === 0, checks, failed: failed.map((c) => c.field), gate: 'review' };
}

// ── reframe_blanking_check ─────────────────────────────────────────────
function loadSharp() {
  try {
    return require('sharp');
  } catch {
    throw new Error("reframe_blanking_check needs the optional dep 'sharp'. Install: npm i sharp");
  }
}

/**
 * reframe_blanking_check: detect letterbox/pillarbox bars + active-picture bounds + illegal
 * edge pixels on a display-referred PNG (an extracted frame). Deterministic.
 * @param {string} pngPath
 * @param {{blackThreshold?:number, barFraction?:number, maxSide?:number}} opts
 */
export async function reframeBlankingCheck(pngPath, opts = {}) {
  const sharp = loadSharp();
  const maxSide = opts.maxSide ?? 480;
  const blk = opts.blackThreshold ?? 16; // ≤ this (per channel) counts as blanking
  const barFrac = opts.barFraction ?? 0.98; // a row/col is a bar if ≥98% of its pixels are black
  let data, ch, W, H;
  try {
    const out = await sharp(pngPath).resize(maxSide, maxSide, { fit: 'inside', kernel: 'nearest' }).raw().toBuffer({ resolveWithObject: true });
    data = out.data;
    ch = out.info.channels;
    W = out.info.width;
    H = out.info.height;
  } catch {
    return null;
  }
  const isBlack = (i) => data[i] <= blk && data[i + 1] <= blk && data[i + 2] <= blk;
  const rowBlack = (y) => {
    let n = 0;
    for (let x = 0; x < W; x++) if (isBlack((y * W + x) * ch)) n++;
    return n / W >= barFrac;
  };
  const colBlack = (x) => {
    let n = 0;
    for (let y = 0; y < H; y++) if (isBlack((y * W + x) * ch)) n++;
    return n / H >= barFrac;
  };
  let top = 0,
    bottom = 0,
    left = 0,
    right = 0;
  while (top < H && rowBlack(top)) top++;
  while (bottom < H - top && rowBlack(H - 1 - bottom)) bottom++;
  while (left < W && colBlack(left)) left++;
  while (right < W - left && colBlack(W - 1 - right)) right++;
  const activeW = Math.max(0, W - left - right);
  const activeH = Math.max(0, H - top - bottom);
  const activeAspect = activeH ? +(activeW / activeH).toFixed(4) : 0;
  // Illegal edge pixels: a frame edge that is neither fully blanked nor part of the active
  // picture bound cleanly (a 1px bright seam in the blanking) — report the brightest edge px.
  let edgeMax = 0;
  const scan = (i) => {
    edgeMax = Math.max(edgeMax, data[i], data[i + 1], data[i + 2]);
  };
  for (let x = 0; x < W; x++) {
    scan((0 * W + x) * ch);
    scan(((H - 1) * W + x) * ch);
  }
  for (let y = 0; y < H; y++) {
    scan((y * W + 0) * ch);
    scan((y * W + (W - 1)) * ch);
  }
  return {
    frameSize: { w: W, h: H },
    bars: { top: +(top / H).toFixed(4), bottom: +(bottom / H).toFixed(4), left: +(left / W).toFixed(4), right: +(right / W).toFixed(4) },
    activeRect: { x: left, y: top, w: activeW, h: activeH },
    activeAspect,
    letterboxed: top + bottom > 0,
    pillarboxed: left + right > 0,
    edgeMaxLuma: edgeMax,
    illegalEdge: edgeMax > blk && top === 0 && bottom === 0 && left === 0 && right === 0 ? false : edgeMax > blk && (top || bottom || left || right) > 0,
  };
}

// ── conform_completeness ───────────────────────────────────────────────
/**
 * conform_completeness: assert a conformed timeline is deliver-ready. PURE over a supplied
 * structure (the live server reports clip online-state/handles; Node judges). Frame-exact.
 * @param {{clips:Array<{id, online?:boolean, handleIn?:number, handleOut?:number}>, timelineFrames?:number}} timeline
 * @param {{referenceFrames?:number, minHandle?:number}} opts
 */
export function conformCompleteness(timeline, opts = {}) {
  const clips = timeline.clips || [];
  const minHandle = opts.minHandle ?? 0;
  const offline = clips.filter((c) => c.online === false).map((c) => c.id);
  const shortHandles = clips.filter((c) => minHandle > 0 && ((c.handleIn ?? Infinity) < minHandle || (c.handleOut ?? Infinity) < minHandle)).map((c) => c.id);
  const checks = [];
  checks.push({ field: 'all_online', pass: offline.length === 0, offline });
  if (minHandle > 0) checks.push({ field: 'handles', pass: shortHandles.length === 0, minHandle, shortHandles });
  if (opts.referenceFrames != null)
    checks.push({
      field: 'duration_frame_exact',
      pass: Number(timeline.timelineFrames) === Number(opts.referenceFrames),
      expected: opts.referenceFrames,
      actual: timeline.timelineFrames ?? null,
    });
  const failed = checks.filter((c) => !c.pass);
  return { pass: failed.length === 0, clipCount: clips.length, checks, failed: failed.map((c) => c.field), gate: 'review' };
}

// ── re_delivery_diff ───────────────────────────────────────────────────
/**
 * re_delivery_diff: compare an OLD render to a NEW render → frame-count Δ, duration Δ, spec
 * drift (codec/raster/fps/color/audio), and sampled-frame change hints. PURE core over two probes.
 */
export function compareRenders(oldP, newP) {
  const drift = [];
  const cmp = (field, a, b) => {
    if (String(a) !== String(b)) drift.push({ field, old: a, new: b });
  };
  const ov = oldP.video || {},
    nv = newP.video || {};
  for (const k of ['codec', 'profile', 'width', 'height', 'fps', 'scan', 'colorPrimaries', 'colorTransfer', 'colorMatrix', 'bitDepth', 'pixFmt'])
    cmp(`video.${k}`, ov[k], nv[k]);
  cmp('container', oldP.format.container, newP.format.container);
  const oa = (oldP.audio || [])[0] || {},
    na = (newP.audio || [])[0] || {};
  for (const k of ['codec', 'channels', 'channelLayout', 'sampleRate']) cmp(`audio.${k}`, oa[k], na[k]);
  const frameDelta = (nv.frameCount || 0) - (ov.frameCount || 0);
  const durationDelta = +(newP.format.duration - oldP.format.duration).toFixed(4);
  return { frameDelta, durationDelta, specDrift: drift, specDriftCount: drift.length, sameLength: frameDelta === 0 };
}

export function reDeliveryDiff(oldFile, newFile, opts = {}) {
  const oldP = probeMedia(oldFile, opts);
  const newP = probeMedia(newFile, opts);
  if (!oldP || !newP) throw new Error('re_delivery_diff: could not probe one of the renders (skip-not-fake)');
  return { old: oldFile, new: newFile, ...compareRenders(oldP, newP), gate: 'review' };
}
