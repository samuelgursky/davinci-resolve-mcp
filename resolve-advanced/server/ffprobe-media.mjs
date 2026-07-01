/**
 * ffprobe-media — one normalized media-probe helper the deliverable/media QC tools share.
 * Wraps `ffprobe -show_streams -show_format` into a compact { video, audio[], format } shape.
 * Deps: ffprobe on PATH (peer; not bundled — GPL). Deterministic read; no Resolve, no LLM.
 */
import { spawnSync } from 'node:child_process';
import { requireFfmpeg } from './capabilities.mjs';

/** Parse an "a/b" rational string → number (0 on divide-by-zero). */
export function ratio(s) {
  const [n, d] = String(s || '0/1')
    .split('/')
    .map(Number);
  return d ? n / d : 0;
}

/**
 * Probe a media file. Returns null on failure (skip-not-fake at the caller).
 * @param {string} file
 * @param {{ffprobe?:string}} [opts]
 */
export function probeMedia(file, opts = {}) {
  requireFfmpeg();
  const ffprobe = opts.ffprobe || 'ffprobe';
  const r = spawnSync(ffprobe, ['-v', 'error', '-show_streams', '-show_format', '-of', 'json', file], {
    encoding: 'utf8',
    timeout: 30000,
    maxBuffer: 32 * 1024 * 1024,
  });
  if (r.status !== 0) return null;
  let j;
  try {
    j = JSON.parse(r.stdout || '{}');
  } catch {
    return null;
  }
  const streams = j.streams || [];
  const vs = streams.find((s) => s.codec_type === 'video') || null;
  const as = streams.filter((s) => s.codec_type === 'audio');
  const fmt = j.format || {};
  const fps = vs ? ratio(vs.r_frame_rate) : 0;
  let frameCount = vs ? Number(vs.nb_frames) || 0 : 0;
  const duration = Number(fmt.duration) || (vs ? Number(vs.duration) : 0) || 0;
  if (!frameCount && duration && fps) frameCount = Math.round(duration * fps);
  const video = vs
    ? {
        codec: vs.codec_name || 'unknown',
        profile: vs.profile != null ? String(vs.profile) : null,
        width: vs.width || 0,
        height: vs.height || 0,
        fps: +fps.toFixed(4),
        fpsExact: vs.r_frame_rate,
        fieldOrder: vs.field_order || 'progressive',
        scan: vs.field_order && vs.field_order !== 'progressive' ? 'interlaced' : 'progressive',
        pixFmt: vs.pix_fmt || 'unknown',
        colorPrimaries: vs.color_primaries || 'unknown',
        colorTransfer: vs.color_transfer || 'unknown',
        colorMatrix: vs.color_space || 'unknown',
        colorRange: vs.color_range || 'unknown',
        bitDepth: vs.bits_per_raw_sample ? Number(vs.bits_per_raw_sample) : null,
        sampleAspect: vs.sample_aspect_ratio || '1:1',
        displayAspect: vs.display_aspect_ratio || null,
        frameCount,
      }
    : null;
  const audio = as.map((a) => ({
    codec: a.codec_name || 'unknown',
    channels: a.channels || 0,
    channelLayout: a.channel_layout || 'unknown',
    sampleRate: Number(a.sample_rate) || 0,
    bitDepth: a.bits_per_raw_sample ? Number(a.bits_per_raw_sample) : a.bits_per_sample || null,
  }));
  // Timecode: format tag, then any stream tag (camera TC usually rides a data/video stream tag).
  const timecode = (fmt.tags && fmt.tags.timecode) || streams.map((s) => s.tags && s.tags.timecode).find(Boolean) || null;
  return {
    video,
    audio,
    format: {
      container: (fmt.format_name || '').split(',')[0] || 'unknown',
      duration: +duration.toFixed(4),
      size: Number(fmt.size) || 0,
      bitRate: Number(fmt.bit_rate) || 0,
      nbStreams: streams.length,
      tags: fmt.tags || {},
      timecode,
    },
  };
}
