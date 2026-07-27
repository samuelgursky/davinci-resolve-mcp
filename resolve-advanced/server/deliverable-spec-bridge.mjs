/**
 * deliverable spec BRIDGE — authored deliverable vocabulary → ffprobe-shaped QC spec.
 *
 * The two vocabularies in this repo do not match, and that mismatch is why the
 * `deliver` stage has never actually QC'd anything:
 *
 *   authored (spec-compile / YAML)     ffprobe (checkDeliverable / deliverable-qc)
 *   ------------------------------     ------------------------------------------
 *   video.codec "ProRes 422 HQ"        video.codec "prores"
 *   video.res   "1920x1080"            video.width 1920 + video.height 1080
 *   video.color "Rec.709 Gamma 2.4"    video.colorPrimaries/colorMatrix "bt709"
 *   audio.config "stereo"              audio.channels 2
 *   audio.loudness "-16 LUFS"          (not a QC-spec field — a loudnessQc target)
 *   naming "<SHOW>_<EP>_M_<YYYYMMDD>"  filenameRegex "^..._\\d{8}\\.mov$"
 *   (implied by the naming extension)  container "mov"
 *
 * PURE — no I/O, no Resolve, no ffprobe. Mirrors the live Python server's
 * `src/utils/delivery_targets.py`, which performs the same projection for named
 * render intents; this side handles the *authored* vocabulary, which only exists
 * here. Neither table is duplicated.
 *
 * Two rules carried over from the Python side, for the same reason:
 *
 *   1. Assert only what is actually known. A QC field the spec never pinned
 *      produces a failure that says nothing about the deliverable.
 *   2. Never drop silently. Anything that cannot be mapped is reported in
 *      `unmapped[]` so an unrecognized codec name surfaces instead of quietly
 *      producing a spec with no codec check in it.
 *
 * ffprobe gotcha: `format_name` is "mov,mp4,m4a,3gp,3g2,mj2" for BOTH .mov and
 * .mp4, and ffprobe-media.mjs takes the first token — so `container` is "mov"
 * for both and cannot discriminate them. `video.codec` is the discriminator.
 */

/** Authored codec display name → ffprobe codec_name. Matched case-insensitively by prefix family. */
const CODEC_FAMILIES = [
  { test: /prores/i, codec: 'prores' },
  { test: /dnx(hr|hd)/i, codec: 'dnxhd' },
  { test: /^h\.?264|avc(?!.*intra)|x264|xavc/i, codec: 'h264' },
  { test: /^h\.?265|hevc|x265/i, codec: 'hevc' },
  { test: /avc.?intra/i, codec: 'h264' },
  { test: /jpe?g.?2000|j2k/i, codec: 'jpeg2000' },
  { test: /cineform/i, codec: 'cfhd' },
  { test: /^dv|dvcpro/i, codec: 'dvvideo' },
  { test: /mpeg.?2|xdcam/i, codec: 'mpeg2video' },
  { test: /uncompressed|v210/i, codec: 'v210' },
];

/** Named rasters that appear in authored specs instead of an explicit WxH. */
const NAMED_RASTERS = {
  hd: [1920, 1080],
  '1080p': [1920, 1080],
  fhd: [1920, 1080],
  '720p': [1280, 720],
  uhd: [3840, 2160],
  '2160p': [3840, 2160],
  '4k': [4096, 2160],
  '4kdci': [4096, 2160],
  '2k': [2048, 1080],
};

/** Authored audio layout word → channel count. */
const AUDIO_LAYOUTS = {
  mono: 1,
  stereo: 2,
  '2.0': 2,
  lcr: 3,
  quad: 4,
  '5.1': 6,
  '7.1': 8,
};

/** Container inferred from a filename/naming extension. */
const EXT_CONTAINERS = {
  mov: 'mov',
  mp4: 'mov', // ffprobe first token is "mov" for mp4 too
  m4v: 'mov',
  mxf: 'mxf',
  wav: 'wav',
  mka: 'matroska',
  mkv: 'matroska',
};

/** Date-ish naming tokens with a known shape; everything else is permissive. */
const TOKEN_PATTERNS = {
  YYYYMMDD: '\\d{8}',
  YYYY_MM_DD: '\\d{4}_\\d{2}_\\d{2}',
  'YYYY-MM-DD': '\\d{4}-\\d{2}-\\d{2}',
  YYYY: '\\d{4}',
  YY: '\\d{2}',
  MM: '\\d{2}',
  DD: '\\d{2}',
  VER: 'v?\\d+',
  V: 'v?\\d+',
};

const DEFAULT_TOKEN = '[A-Za-z0-9.-]+';

/** Map an authored codec name to an ffprobe codec_name, or null if unrecognized. */
export function codecToFfprobe(name) {
  if (typeof name !== 'string' || !name.trim()) return null;
  for (const { test, codec } of CODEC_FAMILIES) {
    if (test.test(name)) return codec;
  }
  return null;
}

/** Parse "1920x1080" / "1920 X 1080" / "UHD" / "HD" → {width, height}, or null. */
export function parseRaster(res) {
  if (res == null) return null;
  if (typeof res === 'object' && res.width && res.height) {
    return { width: Number(res.width), height: Number(res.height) };
  }
  if (typeof res !== 'string') return null;
  const explicit = res.trim().match(/^(\d{2,5})\s*[x×]\s*(\d{2,5})$/i);
  if (explicit) return { width: Number(explicit[1]), height: Number(explicit[2]) };
  const named = NAMED_RASTERS[res.trim().toLowerCase().replace(/[\s_]/g, '')];
  return named ? { width: named[0], height: named[1] } : null;
}

/** Parse an authored fps ("23.976", 23.98, "24000/1001") → number, or null. */
export function parseFps(fps) {
  if (typeof fps === 'number' && Number.isFinite(fps)) return fps;
  if (typeof fps !== 'string' || !fps.trim()) return null;
  const ratio = fps.trim().match(/^(\d+)\s*\/\s*(\d+)$/);
  if (ratio) return Number(ratio[1]) / Number(ratio[2]);
  const n = Number(fps);
  return Number.isFinite(n) ? n : null;
}

/** Parse "-16 LUFS" / -16 / "-16LUFS" → number, or null. */
export function parseLoudness(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value !== 'string') return null;
  const m = value.trim().match(/^(-?\d+(?:\.\d+)?)\s*(?:lufs)?$/i);
  return m ? Number(m[1]) : null;
}

/**
 * Map an authored color description to the ffprobe tags that are UNAMBIGUOUS.
 *
 * Primaries and matrix follow from the colorimetry name. The transfer does NOT:
 * "Rec.709 Gamma 2.4" names a display gamma, which is not the same thing as the
 * BT.709 OETF that ffprobe would report as color_transfer=bt709. Asserting one
 * for the other produces a QC failure that is about vocabulary, not the file, so
 * the transfer is deliberately left unmapped and reported.
 *
 * @returns {{tags: object, unmapped: string[]}}
 */
export function parseColor(color) {
  if (typeof color !== 'string' || !color.trim()) return { tags: {}, unmapped: [] };
  const text = color.toLowerCase();
  const tags = {};
  const unmapped = [];

  if (/rec\.?\s*709|bt\.?\s*709/.test(text)) {
    tags.colorPrimaries = 'bt709';
    tags.colorMatrix = 'bt709';
  } else if (/rec\.?\s*2020|bt\.?\s*2020/.test(text)) {
    tags.colorPrimaries = 'bt2020';
    tags.colorMatrix = /ncl/.test(text) ? 'bt2020nc' : 'bt2020nc';
  } else if (/p3/.test(text)) {
    tags.colorPrimaries = 'smpte432';
  } else if (/rec\.?\s*601|bt\.?\s*601/.test(text)) {
    tags.colorPrimaries = 'bt470bg';
    tags.colorMatrix = 'bt470bg';
  } else if (text.trim()) {
    unmapped.push(`color '${color}': unrecognized colorimetry`);
  }

  if (/pq|st\.?\s*2084/.test(text)) tags.colorTransfer = 'smpte2084';
  else if (/hlg|arib/.test(text)) tags.colorTransfer = 'arib-std-b67';
  else if (/gamma/.test(text)) {
    unmapped.push(
      `color '${color}': display gamma is not an ffprobe color_transfer value; transfer left unasserted`,
    );
  }

  return { tags, unmapped };
}

/**
 * Turn a naming template into an anchored filename regex.
 * `<SHOW>_<EP>_MASTER_<YYYYMMDD>.mov` → `^[A-Za-z0-9.-]+_[A-Za-z0-9.-]+_MASTER_\d{8}\.mov$`
 */
export function namingToRegex(naming) {
  if (typeof naming !== 'string' || !naming.trim()) return null;
  let out = '';
  let rest = naming.trim();
  const tokenRe = /<([^<>]+)>/;
  for (;;) {
    const m = rest.match(tokenRe);
    if (!m) {
      out += escapeRegex(rest);
      break;
    }
    out += escapeRegex(rest.slice(0, m.index));
    const key = m[1].trim().toUpperCase().replace(/[\s]/g, '');
    out += TOKEN_PATTERNS[key] ?? DEFAULT_TOKEN;
    rest = rest.slice(m.index + m[0].length);
  }
  return `^${out}$`;
}

function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** Container from an explicit value, else inferred from a naming/filename extension. */
export function inferContainer(explicit, naming) {
  if (typeof explicit === 'string' && explicit.trim()) {
    const key = explicit.trim().toLowerCase().replace(/^\./, '');
    return EXT_CONTAINERS[key] ?? key;
  }
  if (typeof naming !== 'string') return null;
  const m = naming.trim().match(/\.([A-Za-z0-9]+)\s*$/);
  if (!m) return null;
  return EXT_CONTAINERS[m[1].toLowerCase()] ?? m[1].toLowerCase();
}

/**
 * Project ONE authored deliverable onto a checkDeliverable spec + a loudness target.
 *
 * @param {object} deliverable Authored shape: { id?, video:{codec,res,fps,color,scan?},
 *   audio:{config,loudness,sampleRate?,bitDepth?}, container?, naming?, durationSeconds? }
 * @returns {{id, spec, loudnessTarget, unmapped, note}}
 *   `spec` feeds deliverable_qc; `loudnessTarget` feeds loudness_qc (null when not authored).
 */
export function deliverableSpecFromAuthored(deliverable) {
  const d = deliverable || {};
  const v = d.video || {};
  const a = d.audio || {};
  const unmapped = [];

  const video = {};
  const ffCodec = codecToFfprobe(v.codec);
  if (ffCodec) video.codec = ffCodec;
  else if (v.codec) unmapped.push(`video.codec '${v.codec}': no known ffprobe codec_name`);

  const raster = parseRaster(v.res ?? v.resolution);
  if (raster) {
    video.width = raster.width;
    video.height = raster.height;
  } else if (v.res ?? v.resolution) {
    unmapped.push(`video.res '${v.res ?? v.resolution}': unparseable raster`);
  }

  const fps = parseFps(v.fps);
  if (fps != null) video.fps = fps;
  else if (v.fps != null) unmapped.push(`video.fps '${v.fps}': unparseable frame rate`);

  if (typeof v.scan === 'string' && v.scan.trim()) video.scan = v.scan.trim().toLowerCase();
  if (v.bitDepth != null) video.bitDepth = Number(v.bitDepth);

  const color = parseColor(v.color);
  Object.assign(video, color.tags);
  unmapped.push(...color.unmapped);

  const audio = {};
  if (a.channels != null) audio.channels = Number(a.channels);
  else if (typeof a.config === 'string') {
    const channels = AUDIO_LAYOUTS[a.config.trim().toLowerCase()];
    if (channels) audio.channels = channels;
    else unmapped.push(`audio.config '${a.config}': unknown layout`);
  }
  if (a.sampleRate != null) audio.sampleRate = Number(a.sampleRate);
  if (a.bitDepth != null) audio.bitDepth = Number(a.bitDepth);
  if (typeof a.channelLayout === 'string') audio.channelLayout = a.channelLayout;

  const spec = {};
  if (Object.keys(video).length) spec.video = video;
  if (Object.keys(audio).length) spec.audio = audio;

  const container = inferContainer(d.container, d.naming);
  if (container) spec.container = container;

  const filenameRegex = namingToRegex(d.naming);
  if (filenameRegex) spec.filenameRegex = filenameRegex;

  if (d.durationSeconds != null) spec.durationSeconds = Number(d.durationSeconds);
  if (d.durationTolSeconds != null) spec.durationTolSeconds = Number(d.durationTolSeconds);

  const integrated = parseLoudness(a.loudness);
  const loudnessTarget = integrated == null ? null : { integrated };
  if (a.loudness != null && integrated == null) {
    unmapped.push(`audio.loudness '${a.loudness}': unparseable target`);
  }
  if (a.truePeakMax != null && loudnessTarget) loudnessTarget.truePeakMax = Number(a.truePeakMax);
  if (a.lraMax != null && loudnessTarget) loudnessTarget.lraMax = Number(a.lraMax);
  if (a.loudnessTol != null && loudnessTarget) loudnessTarget.integratedTol = Number(a.loudnessTol);

  return {
    id: d.id ?? null,
    spec,
    loudnessTarget,
    unmapped,
    note:
      'Loudness is NOT part of the deliverable_qc spec — run loudness_qc separately with loudnessTarget.',
  };
}

/** Project an authored `deliverables:` list. Non-object entries are reported, not dropped. */
export function deliverableSpecsFromAuthored(deliverables) {
  if (!Array.isArray(deliverables)) return [];
  return deliverables.map((d, i) =>
    d && typeof d === 'object'
      ? deliverableSpecFromAuthored(d)
      : { id: null, spec: {}, loudnessTarget: null, unmapped: [`deliverables[${i}] is not an object`], note: null },
  );
}
