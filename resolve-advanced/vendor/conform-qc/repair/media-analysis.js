'use strict';

/**
 * repair/media-analysis.js — analyze target media so the conform emulator knows
 * the real qualities/options on the volume (stage 1).
 *
 * Resolve frames a clip from the RELINKED media's real geometry, not the proxy
 * dims in the turnover (a scaleToFit bug arises when a highres relink has different
 * dims/aspect than the proxy the editor framed against). So before emulating we
 * probe each candidate: resolution,
 * pixel aspect (SAR/DAR), codec, fps, bit-depth, colour — and rank quality tiers
 * so the relink can choose the intended original over a proxy/test.
 *
 * Split for testability: `parseFfprobe` is PURE (ffprobe JSON -> normalized info);
 * `probeMedia` shells out to ffprobe and calls it.
 */

const { spawnSync } = require('child_process');

/** Parse an `r_frame_rate`/`avg_frame_rate` "24000/1001" string to a number. */
function parseRate(r) {
  if (!r || typeof r !== 'string') return null;
  const [n, d] = r.split('/').map(Number);
  if (!n || !d) return n || null;
  return +(n / d).toFixed(6);
}

/** Bit depth from bits_per_raw_sample, else inferred from pix_fmt (…p10/12/16…). */
function bitDepth(stream) {
  const b = Number(stream.bits_per_raw_sample);
  if (Number.isFinite(b) && b > 0) return b;
  const pf = String(stream.pix_fmt || '');
  const m = pf.match(/p(\d{1,2})(le|be)?$/);
  if (m) return Number(m[1]);
  return pf ? 8 : null;
}

/** Effective display aspect = (W/H) * (SAR), so anamorphic media reports its true shape. */
function aspectOf(w, h, sar) {
  if (!w || !h) return null;
  let par = 1;
  if (sar && typeof sar === 'string' && sar.includes(':')) {
    const [sn, sd] = sar.split(':').map(Number);
    if (sn > 0 && sd > 0) par = sn / sd;
  }
  return +((w / h) * par).toFixed(4);
}

/**
 * Normalize an ffprobe `-of json` result (first video stream + format) into a
 * compact media-info record. Pure.
 */
function parseFfprobe(jsonStr, path) {
  let doc;
  try {
    doc = typeof jsonStr === 'string' ? JSON.parse(jsonStr) : jsonStr;
  } catch (e) {
    return { path: path || null, ok: false, error: 'ffprobe JSON parse failed' };
  }
  // We pass -select_streams v:0, so streams[0] is the video stream even when
  // codec_type isn't among the requested entries; prefer an explicit match.
  const streams = doc.streams || [];
  const v = streams.find((s) => s.codec_type === 'video') || streams[0] || null;
  if (!v || v.width == null) return { path: path || null, ok: false, error: 'no video stream' };
  const w = Number(v.width) || null;
  const h = Number(v.height) || null;
  const fpsVal = parseRate(v.r_frame_rate) || parseRate(v.avg_frame_rate);
  const durVal = doc.format && doc.format.duration ? Number(doc.format.duration) : null;
  // Exact container frame count when present; else derive from duration*fps.
  // Used to end-anchor reversed clips (no reference render required).
  let frames = Number(v.nb_frames);
  if (!Number.isFinite(frames) || frames <= 0) {
    frames = fpsVal && durVal ? Math.round(durVal * fpsVal) : null;
  }
  return {
    path: path || null,
    ok: true,
    width: w,
    height: h,
    frames: frames || null,
    sar: v.sample_aspect_ratio || null,
    dar: v.display_aspect_ratio || null,
    aspect: aspectOf(w, h, v.sample_aspect_ratio),
    codec: v.codec_name || null,
    profile: v.profile || null,
    pixFmt: v.pix_fmt || null,
    bitDepth: bitDepth(v),
    fps: fpsVal,
    colorPrimaries: v.color_primaries || null,
    colorTransfer: v.color_transfer || null,
    durationSec: durVal != null ? +durVal.toFixed(3) : null,
  };
}

const FFPROBE_ARGS = [
  '-v', 'error', '-select_streams', 'v:0',
  '-show_entries',
  'stream=width,height,codec_name,profile,pix_fmt,r_frame_rate,avg_frame_rate,sample_aspect_ratio,display_aspect_ratio,color_primaries,color_transfer,bits_per_raw_sample,nb_frames:format=duration',
  '-of', 'json',
];

/** Probe one file via ffprobe. Returns the normalized record (ok:false on failure). */
function probeMedia(path, { ffprobePath = 'ffprobe' } = {}) {
  const r = spawnSync(ffprobePath, [...FFPROBE_ARGS, path], { encoding: 'utf8', maxBuffer: 8 * 1024 * 1024 });
  if (r.status !== 0) return { path, ok: false, error: (r.stderr || 'ffprobe failed').slice(-200) };
  return parseFfprobe(r.stdout, path);
}

/**
 * Quality rank for choosing among options for the same shot (higher = better
 * original). ProRes 4444/XQ and higher resolution/bit-depth win; h264/proxy and a
 * "proxy"/"test" path lose. Used by the relink to pick the intended source.
 */
const CODEC_RANK = { prores: 50, dnxhd: 45, dnxhr: 45, h264: 10, hevc: 12, mjpeg: 8 };
function qualityRank(info) {
  if (!info || !info.ok) return -1;
  let s = 0;
  const codec = String(info.codec || '').toLowerCase();
  for (const k of Object.keys(CODEC_RANK)) if (codec.includes(k)) s += CODEC_RANK[k];
  if (/4444|xq|hq/.test(String(info.profile || '').toLowerCase())) s += 20;
  s += (info.width || 0) / 100; // resolution
  s += (info.bitDepth || 8) * 2;
  const p = String(info.path || '').toLowerCase();
  if (/\bproxy\b/.test(p) || /\.mp4$/.test(p)) s -= 40;
  if (/\btest(s)?\b/.test(p)) s -= 25;
  return +s.toFixed(2);
}

/** Probe a list of paths; returns records sorted by quality (best first). */
function analyzeMediaList(paths, opts = {}) {
  const out = (paths || []).map((p) => {
    const info = probeMedia(p, opts);
    return { ...info, qualityRank: qualityRank(info) };
  });
  out.sort((a, b) => b.qualityRank - a.qualityRank);
  return out;
}

module.exports = { parseFfprobe, probeMedia, analyzeMediaList, qualityRank, aspectOf, bitDepth, parseRate };
