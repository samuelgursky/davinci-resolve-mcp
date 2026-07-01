/**
 * DRX Generator - Programmatic DaVinci Resolve Grade Creation
 *
 * Generates DRX (DaVinci Resolve eXchange) files from color parameters.
 * Based on reverse-engineered format: [0x81] + [ZSTD-compressed protobuf]
 *
 * Uses shared DRX parameter library for consistent parameter handling
 * across the The project platform.
 *
 * @module drx/drx-generator
 */

// ZSTD compression backend selection — priority:
//   1. Node's built-in zlib.zstdCompressSync (Node 22+, available on Vercel)
//      — reliable, no buffer truncation bugs
//   2. zstd-codec (WASM) — falls back here for older Node (Electron dev)
//   3. fzstd (pure JS) — decompress only; compress is undefined, so this
//      fallback exists only for completeness and will throw if reached
//
// HISTORY: zstd-codec's Simple.compress() was observed truncating frames on
// Vercel's Node 22 runtime (body would be valid zstd magic but the compressed
// stream would end prematurely, producing a DRX Resolve couldn't parse and
// silently applied as an empty node graph — the clip grade would not change).
// Using node:zlib.zstdCompressSync when available eliminates that class of
// bug entirely.
// Debug tracing is stdout-hostile inside a stdio MCP server — gate it behind DRX_DEBUG.
const debugLog = process.env.DRX_DEBUG ? console.log.bind(console) : () => {};
const nodeZlib = require('zlib');
const HAS_NATIVE_ZSTD = typeof nodeZlib.zstdCompressSync === 'function';

let ZstdCodec;
try {
  ZstdCodec = require('zstd-codec').ZstdCodec;
} catch {
  ZstdCodec = null;
}
const { v4: uuidv4 } = require('uuid');

// Import shared DRX parameter library
const drxParams = require('../drx-parameters');

// ZSTD codec instance (initialized lazily)
let zstdCompressor = null;

async function getZstdCompressor() {
  if (zstdCompressor) return zstdCompressor;

  // Native Node zstd (Node 22+). Preferred path on Vercel.
  if (HAS_NATIVE_ZSTD) {
    zstdCompressor = {
      compress(data) {
        const buf = data instanceof Buffer
          ? data
          : Buffer.from(data instanceof Uint8Array ? data : new Uint8Array(data));
        return nodeZlib.zstdCompressSync(buf);
      },
    };
    return zstdCompressor;
  }

  // zstd-codec (WASM) — Electron/older-Node fallback
  if (ZstdCodec) {
    return new Promise((resolve) => {
      ZstdCodec.run((zstd) => {
        zstdCompressor = new zstd.Simple();
        resolve(zstdCompressor);
      });
    });
  }

  // Final fallback — fzstd only exposes decompress, so this path will
  // throw at call time. Kept so the error surfaces clearly rather than
  // silently returning undefined and producing a malformed DRX.
  const fzstd = require('fzstd');
  zstdCompressor = {
    compress(data) {
      if (typeof fzstd.compress !== 'function') {
        throw new Error('No zstd compressor available: node:zlib zstd requires Node 22+, zstd-codec failed to load, and fzstd does not support compression.');
      }
      return Buffer.from(fzstd.compress(data instanceof Uint8Array ? data : new Uint8Array(data)));
    },
  };
  return zstdCompressor;
}

/**
 * Parameter ID mappings from shared library
 * See: /lib/drx-parameters for full documentation
 */
const PARAM_IDS = {
  // Primary Corrector - Lift
  LIFT_R: drxParams.LIFT.R,
  LIFT_G: drxParams.LIFT.G,
  LIFT_B: drxParams.LIFT.B,
  LIFT_MASTER: drxParams.LIFT.MASTER,

  // Primary Corrector - Gain
  GAIN_R: drxParams.GAIN.R,
  GAIN_G: drxParams.GAIN.G,
  GAIN_B: drxParams.GAIN.B,
  GAIN_MASTER: drxParams.GAIN.MASTER,

  // Primary Corrector - Gamma
  GAMMA_R: drxParams.GAMMA.R,
  GAMMA_G: drxParams.GAMMA.G,
  GAMMA_B: drxParams.GAMMA.B,
  GAMMA_MASTER: drxParams.GAMMA.MASTER,

  // Primary Corrector - Offset
  OFFSET_R: drxParams.OFFSET.R,
  OFFSET_G: drxParams.OFFSET.G,
  OFFSET_B: drxParams.OFFSET.B,

  // Saturation
  SATURATION_PRIMARY: drxParams.SATURATION.PRIMARY,
  // Hue Rotate — uses SATURATION.LEGACY ID (0x06000004) with nested {F1: float} encoding
  // Encoding: DRX = (UI - 50) / 50. UI range 0-100, default 50.
  // Confirmed 2026-03-18: UI 92 → DRX 0.84, UI 75 → DRX 0.50
  HUE_ROTATE: drxParams.SATURATION.LEGACY,  // 0x06000004

  // Contrast / Pivot (shared controls range — corrected 2026-03-22)
  // NOTE: The old CONTRAST block (0x0830xxxx) was a misidentification of HSL Qualifier params.
  // Real contrast/pivot are in the 0x860000C0 range, already mapped as LOG_CONTRAST and PIVOT_PRIMARY below.

  // Temperature/Tint (all in Primary corrector, Type 1)
  TEMPERATURE: drxParams.TEMP_TINT.TEMPERATURE,
  TINT: drxParams.TEMP_TINT.TINT,
  COLOR_BOOST: drxParams.TEMP_TINT.COLOR_BOOST,
  MIDTONE_DETAIL: drxParams.TEMP_TINT.MIDTONE_DETAIL,
  LOG_CONTRAST: drxParams.TEMP_TINT.CONTRAST,
  // Pivot — TEMP_TINT.CONTRAST - 1, confirmed by manual DRX capture 2026-03-17
  PIVOT_PRIMARY: 2248147136,

  // Soft Clip — per-channel R/G/B in Primary corrector
  // Confirmed by manual DRX capture 2026-03-17: SoftClipHigh=70 → IDs 100663350-352 at 0.70
  SOFT_CLIP_HIGH_R: 100663350,
  SOFT_CLIP_HIGH_G: 100663351,
  SOFT_CLIP_HIGH_B: 100663352,
  // Soft Clip Low — CORRECTED 2026-03-24 via manual DRX capture autoresearch.
  // Original extrapolation had B at 100663349 (0x35) — WRONG. Actual B is at 100663346 (0x32).
  // Layout: B(0x32), R(0x33), G(0x34) — B is BEFORE R, not after G.
  SOFT_CLIP_LOW_R: 100663347,  // 0x06000033
  SOFT_CLIP_LOW_G: 100663348,  // 0x06000034
  SOFT_CLIP_LOW_B: 100663346,  // 0x06000032 (was incorrectly 100663349)

  // Soft Clip Soft (softness controls) — captured 2026-03-18
  // Encoding: UI / 50 (so UI 25 → DRX 0.5, UI 50 → DRX 1.0)
  SOFT_CLIP_LOW_SOFT_R:  100663354,  // 0x0600003A
  SOFT_CLIP_LOW_SOFT_G:  100663355,  // 0x0600003B
  SOFT_CLIP_LOW_SOFT_B:  100663356,  // 0x0600003C
  SOFT_CLIP_HIGH_SOFT_R: 100663358,  // 0x0600003E
  SOFT_CLIP_HIGH_SOFT_G: 100663359,  // 0x0600003F
  SOFT_CLIP_HIGH_SOFT_B: 100663360,  // 0x06000040

  // Contrast Range — confirmed by manual DRX captures 2026-03-18
  // Low Range: 0x860000CB, direct encoding (UI value = DRX value)
  // High Range: 0x860000CC, INVERTED encoding (DRX = 1.0 - UI)
  CONTRAST_LOW_RANGE_PRIMARY: 2248147147,   // 0x860000CB
  CONTRAST_HIGH_RANGE_PRIMARY: 2248147148,  // 0x860000CC

  // HDR Global
  HDR_BLACK_OFFSET: drxParams.HDR_ZONE.BLACK_OFFSET,

  // HDR Zone
  HDR_ZONE_ADJUSTMENTS: drxParams.HDR_ZONE.ZONE_ADJUSTMENTS,
  HDR_ZONE_DEFINITIONS: drxParams.HDR_ZONE.ZONE_DEFINITIONS,
  HDR_ZONE_METADATA: drxParams.HDR_ZONE.ZONE_METADATA,
  HDR_ZONE_PARAM: drxParams.HDR_ZONE.PARAM_1,

  // Log Wheels (R/G/B only - no master channel)
  // Corrected 2026-01-14: Shadow=0xc2-c4, Midtone=0xc5-c7, Highlight=0xc8-ca
  LOG_SHADOW_R: drxParams.LOG_WHEELS.SHADOW_R,
  LOG_SHADOW_G: drxParams.LOG_WHEELS.SHADOW_G,
  LOG_SHADOW_B: drxParams.LOG_WHEELS.SHADOW_B,
  LOG_MIDTONE_R: drxParams.LOG_WHEELS.MIDTONE_R,
  LOG_MIDTONE_G: drxParams.LOG_WHEELS.MIDTONE_G,
  LOG_MIDTONE_B: drxParams.LOG_WHEELS.MIDTONE_B,
  LOG_HIGHLIGHT_R: drxParams.LOG_WHEELS.HIGHLIGHT_R,
  LOG_HIGHLIGHT_G: drxParams.LOG_WHEELS.HIGHLIGHT_G,
  LOG_HIGHLIGHT_B: drxParams.LOG_WHEELS.HIGHLIGHT_B,

  // RGB Mixer (trained 2026-03-17 from rgbmixer_1.1.2.drx)
  RGB_MIXER_RR: drxParams.RGB_MIXER?.RR,
  RGB_MIXER_GR: drxParams.RGB_MIXER?.GR,
  RGB_MIXER_BR: drxParams.RGB_MIXER?.BR,
  RGB_MIXER_RG: drxParams.RGB_MIXER?.RG,
  RGB_MIXER_GG: drxParams.RGB_MIXER?.GG,
  RGB_MIXER_BG: drxParams.RGB_MIXER?.BG,
  RGB_MIXER_RB: drxParams.RGB_MIXER?.RB,
  RGB_MIXER_GB: drxParams.RGB_MIXER?.GB,
  RGB_MIXER_BB: drxParams.RGB_MIXER?.BB,

  // Custom Curves YRGB (trained 2026-03-17, CORRECTED 2026-03-18)
  // Round-trip verification proved drx-parameters mapping was shifted:
  // 0x86000506 = R (not Y), 0x86000507 = G (not R), 0x86000508 = B (not G), 0x86000509 = Y (not B)
  // Metadata IDs: 0xBB=Y, 0xBD=R, 0xBE=G, 0xBF=B (unchanged)
  CURVES_Y_META: drxParams.CUSTOM_CURVES?.Y_META,       // 0x860000BB
  CURVES_R_META: drxParams.CUSTOM_CURVES?.R_META,       // 0x860000BD
  CURVES_G_META: drxParams.CUSTOM_CURVES?.G_META,       // 0x860000BE
  CURVES_B_META: drxParams.CUSTOM_CURVES?.B_META,       // 0x860000BF
  CURVES_Y_SPLINE: 2248148233,  // 0x86000509 — was incorrectly mapped to B_SPLINE
  CURVES_R_SPLINE: 2248148230,  // 0x86000506 — was incorrectly mapped to Y_SPLINE
  CURVES_G_SPLINE: 2248148231,  // 0x86000507 — was incorrectly mapped to R_SPLINE
  CURVES_B_SPLINE: 2248148232,  // 0x86000508 — was incorrectly mapped to G_SPLINE

  // HSL Curves (trained 2026-03-17)
  HSL_COMMON_FLAG: drxParams.HSL_CURVES?.COMMON_FLAG,
  HSL_HUE_VS_HUE_SPLINE: drxParams.HSL_CURVES?.HUE_VS_HUE_SPLINE,
  HSL_HUE_VS_SAT_SPLINE: drxParams.HSL_CURVES?.HUE_VS_SAT_SPLINE,
  HSL_HUE_VS_LUM_SPLINE: drxParams.HSL_CURVES?.HUE_VS_LUM_SPLINE,
  HSL_LUM_VS_SAT_SPLINE: drxParams.HSL_CURVES?.LUM_VS_SAT_SPLINE,
  HSL_SAT_VS_SAT_SPLINE: drxParams.HSL_CURVES?.SAT_VS_SAT_SPLINE,
  HSL_SAT_VS_LUM_SPLINE: drxParams.HSL_CURVES?.SAT_VS_LUM_SPLINE,

  // Additional controls (trained 2026-03-17)
  HIGHLIGHTS: drxParams.ADDITIONAL?.HIGHLIGHTS,
  SHADOWS: drxParams.ADDITIONAL?.SHADOWS,
  LUM_MIX_SLIDER: drxParams.ADDITIONAL?.LUM_MIX_SLIDER,  // 0x8600000B
};

/**
 * Corrector Type IDs from shared library
 */
const CORRECTOR_TYPES = drxParams.CORRECTOR_TYPES;

/**
 * Presence marker IDs from shared library
 */
const PRESENCE_MARKER_IDS = drxParams.PRESENCE_MARKER_IDS;

/**
 * Default neutral grade values from shared library
 */
const NEUTRAL_GRADE = {
  // Color Wheels
  lift: {
    r: drxParams.getDefault('lift', 'r'),
    g: drxParams.getDefault('lift', 'g'),
    b: drxParams.getDefault('lift', 'b'),
    master: drxParams.getDefault('lift', 'master'),
  },
  gamma: {
    r: drxParams.getDefault('gamma', 'r'),
    g: drxParams.getDefault('gamma', 'g'),
    b: drxParams.getDefault('gamma', 'b'),
    master: drxParams.getDefault('gamma', 'master'),
  },
  gain: {
    r: drxParams.getDefault('gain', 'r'),
    g: drxParams.getDefault('gain', 'g'),
    b: drxParams.getDefault('gain', 'b'),
    master: drxParams.getDefault('gain', 'master'),
  },
  offset: {
    r: drxParams.getDefault('offset', 'r'),
    g: drxParams.getDefault('offset', 'g'),
    b: drxParams.getDefault('offset', 'b'),
  },

  // Primary adjustments
  saturation: drxParams.getDefault('saturation', 'master'),
  contrast: drxParams.getDefault('contrast', 'master'),
  pivot: drxParams.getDefault('pivotFine', 'master'),

  // Temperature/Tint
  temperature: drxParams.getDefault('temperature', 'master'),
  tint: drxParams.getDefault('tint', 'master'),

  // Detail
  midtoneDetail: drxParams.getDefault('midtoneDetail', 'master'),

  // Soft clip
  softClipHigh: drxParams.getDefault('softClipHigh', 'master'),
  softClipLow: drxParams.getDefault('softClipLow', 'master'),
};

/**
 * Encode a varint (variable-length integer) for protobuf
 */
function encodeVarint(value) {
  const bytes = [];
  while (value > 0x7f) {
    bytes.push((value & 0x7f) | 0x80);
    value >>>= 7;
  }
  bytes.push(value & 0x7f);
  return Buffer.from(bytes);
}

/**
 * Encode a float32 as little-endian bytes
 */
function encodeFloat32(value) {
  const buf = Buffer.alloc(4);
  buf.writeFloatLE(value, 0);
  return buf;
}

/**
 * Create a protobuf field with varint wire type (0)
 */
function protoVarint(fieldNum, value) {
  const tag = (fieldNum << 3) | 0;
  return Buffer.concat([encodeVarint(tag), encodeVarint(value)]);
}

/**
 * Create a protobuf field with fixed32 wire type (5) for floats
 */
function protoFloat32(fieldNum, value) {
  const tag = (fieldNum << 3) | 5;
  return Buffer.concat([encodeVarint(tag), encodeFloat32(value)]);
}

/**
 * Create a protobuf field with fixed64 wire type (1) for doubles
 */
function protoFloat64(fieldNum, value) {
  const tag = (fieldNum << 3) | 1;
  const buf = Buffer.alloc(8);
  buf.writeDoubleLE(value, 0);
  return Buffer.concat([encodeVarint(tag), buf]);
}

/**
 * Create a protobuf field with length-delimited wire type (2)
 */
function protoBytes(fieldNum, data) {
  const tag = (fieldNum << 3) | 2;
  return Buffer.concat([encodeVarint(tag), encodeVarint(data.length), data]);
}

/**
 * Create a color parameter entry
 * Format: Field 3 { Field 1 (ID), Field 2 { Field 1 (float value) } }
 */
function createParameterEntry(paramId, value) {
  // ── Universal range clamp ──────────────────────────────────────────────────
  // Every float that enters the DRX body passes through here.
  // Look up the param ID in the shared parameter library to get valid range,
  // then hard-clamp. This protects ALL builder functions (Primary, HDR, Curves,
  // Qualifier, Windows, ResolveFX) with zero per-builder code.
  // Unknown param IDs pass through unchanged (future-proof).
  const paramInfo = drxParams.getParamInfo(paramId);
  if (paramInfo) {
    const range = drxParams.getRange(paramInfo.control, paramInfo.channel);
    if (range) {
      const clamped = Math.max(range.min, Math.min(range.max, value));
      if (clamped !== value) {
        console.warn(`[DRX] CLAMPED ${paramInfo.control}.${paramInfo.channel}: ${value} → ${clamped} (range ${range.min}–${range.max})`);
      }
      value = clamped;
    }
  }

  // Inner value message: Field 1 = float
  const valueMsg = protoFloat32(1, value);

  // Outer entry: Field 1 = ID (varint), Field 2 = value message
  const entry = Buffer.concat([
    protoVarint(1, paramId),
    protoBytes(2, valueMsg),
  ]);

  // Wrap in Field 3
  return protoBytes(3, entry);
}

/**
 * Create a varint-valued parameter entry: F3 { F1 (ID), F2 { F2 (varint) } }.
 * Live Resolve stores flag/mode params (window type 0x88500008, qualifier mode,
 * gradient subtype 0x08F00001) in a varint envelope — NOT the float32 F2.F1
 * envelope createParameterEntry writes. Wire-confirmed 2026-07-01 against the
 * power-window/gradient/qualifier fixtures (all carry {F2: <varint>}).
 * No range clamp — these are discrete flags, not ranged floats.
 */
function createVarintParameterEntry(paramId, value) {
  const valueMsg = protoVarint(2, value);
  const entry = Buffer.concat([
    protoVarint(1, paramId),
    protoBytes(2, valueMsg),
  ]);
  return protoBytes(3, entry);
}

/**
 * Create a curve control point
 * Format: Field 1 { Field 1 (x float), Field 2 (y float) }
 */
function createCurvePoint(x, y) {
  const point = Buffer.concat([
    protoFloat32(1, x),
    protoFloat32(2, y),
  ]);
  return protoBytes(1, point);
}

/**
 * Encode a YRGB curve spline as nested protobuf for DRX.
 * Coordinate space: 0–1023. Sentinel: (-1024, -1024). End: (1023, 1023).
 * @param {Array<{x: number, y: number}>} points - Control points in 0–1 normalized space
 * @returns {Buffer} Encoded spline data
 */
function encodeCurveSpline(points) {
  const SCALE = 1023;
  const bufs = [];
  bufs.push(createCurvePoint(-1024, -1024)); // sentinel
  bufs.push(protoBytes(1, Buffer.alloc(0))); // empty separator
  for (const pt of points) {
    bufs.push(createCurvePoint(
      Math.max(0, Math.min(SCALE, pt.x * SCALE)),
      Math.max(0, Math.min(SCALE, pt.y * SCALE)),
    ));
  }
  bufs.push(createCurvePoint(SCALE, SCALE)); // end
  return protoBytes(8, Buffer.concat(bufs));
}

/**
 * Encode an HSL curve spline as nested protobuf for DRX.
 * Coordinate space: raw floats (X = 0.0–1.0 hue fraction with wrap, Y = 0.0–1.0 where 0.5 = neutral).
 * Training samples show X ranges from ~-0.08 to ~1.08 (wrap-around continuity).
 * @param {Array<{x: number, y: number}>} points - Control points in raw float space
 * @returns {Buffer} Encoded spline data
 */
function encodeHSLCurveSpline(points) {
  // HSL curves use a different convention from YRGB:
  // - NO sentinel (-1024, -1024)
  // - NO empty separator
  // - NO end marker
  // - Just raw float data points in F8 wrapper
  // - Points must cover wrap-around range (~-0.08 to ~1.08 in X)
  // - Y: 0.5 = neutral, >0.5 = boost, <0.5 = cut
  // Training evidence: hue_vs_sat_1.1.2.drx has 40 raw points, no sentinels.
  const bufs = [];
  for (const pt of points) {
    bufs.push(createCurvePoint(pt.x, pt.y));
  }
  return protoBytes(8, Buffer.concat(bufs));
}

/**
 * Encode curve metadata (point count) as nested protobuf { F2: varint count }
 */
function encodeCurveMeta(count) {
  return protoVarint(2, count);
}

/**
 * Build Custom Curves (YRGB) parameters.
 * Input: colorParams.customCurves = { y: [{x,y}], r: [{x,y}], g: [{x,y}], b: [{x,y}] }
 * Returns pre-wrapped F3 entries for the Primary corrector.
 */
function buildCustomCurveParams(colorParams) {
  const entries = [];
  if (!colorParams.customCurves) return entries;
  const curves = colorParams.customCurves;
  const channels = [
    { key: 'y', metaId: PARAM_IDS.CURVES_Y_META, splineId: PARAM_IDS.CURVES_Y_SPLINE },
    { key: 'r', metaId: PARAM_IDS.CURVES_R_META, splineId: PARAM_IDS.CURVES_R_SPLINE },
    { key: 'g', metaId: PARAM_IDS.CURVES_G_META, splineId: PARAM_IDS.CURVES_G_SPLINE },
    { key: 'b', metaId: PARAM_IDS.CURVES_B_META, splineId: PARAM_IDS.CURVES_B_SPLINE },
  ];

  // Training evidence (curve_y_scurve_1.1.2.drx): Resolve ALWAYS writes all 4 channels.
  // Untouched channels get identity splines. All 4 metadata entries present.
  // Determine which channels have user data vs identity
  const hasAny = channels.some(({ key }) => curves[key]?.length > 0);
  if (!hasAny) return entries;

  // Identity curve: two points at (0,0) and (1,1) in normalized space → (0,0) and (1023,1023) after scaling
  const IDENTITY_POINTS = [{ x: 0, y: 0 }, { x: 1, y: 1 }];

  for (const { key, metaId, splineId } of channels) {
    const pts = curves[key]?.length > 0 ? curves[key] : IDENTITY_POINTS;
    // Metadata entry — F2 value = point count including sentinel + endpoint
    entries.push(protoBytes(3, Buffer.concat([
      protoVarint(1, metaId),
      protoBytes(2, encodeCurveMeta(pts.length + 2)),
    ])));
    // Spline data entry
    entries.push(protoBytes(3, Buffer.concat([
      protoVarint(1, splineId),
      protoBytes(2, encodeCurveSpline(pts)),
    ])));
    const isIdentity = !curves[key]?.length;
    debugLog('[DRX] Custom Curve ' + key.toUpperCase() + ': ' + pts.length + ' points' + (isIdentity ? ' (identity)' : ''));
  }
  return entries;
}

/**
 * Build HSL Curve parameters.
 * Input: colorParams.hslCurves = { hueVsHue: [{x,y}], hueVsSat: [{x,y}], ... }
 */
function buildHSLCurveParams(colorParams) {
  const entries = [];
  if (!colorParams.hslCurves) return entries;
  const hsl = colorParams.hslCurves;
  const types = [
    { key: 'hueVsHue', splineId: PARAM_IDS.HSL_HUE_VS_HUE_SPLINE, metaId: drxParams.HSL_CURVES.HUE_VS_HUE_META },
    { key: 'hueVsSat', splineId: PARAM_IDS.HSL_HUE_VS_SAT_SPLINE, metaId: drxParams.HSL_CURVES.HUE_VS_SAT_META },
    { key: 'hueVsLum', splineId: PARAM_IDS.HSL_HUE_VS_LUM_SPLINE, metaId: drxParams.HSL_CURVES.HUE_VS_LUM_META },
    { key: 'lumVsSat', splineId: PARAM_IDS.HSL_LUM_VS_SAT_SPLINE, metaId: drxParams.HSL_CURVES.LUM_VS_SAT_META },
    { key: 'satVsSat', splineId: PARAM_IDS.HSL_SAT_VS_SAT_SPLINE, metaId: drxParams.HSL_CURVES.SAT_VS_SAT_META },
    { key: 'satVsLum', splineId: PARAM_IDS.HSL_SAT_VS_LUM_SPLINE, metaId: drxParams.HSL_CURVES.SAT_VS_LUM_META },
  ];
  let hasAny = false;
  // Per-curve meta values observed in LIVE R21 fixtures vary by curve (hueVsHue → 0,
  // satVsSat → 2; the old always-6 came from older training samples). Semantics not fully
  // decoded — callers can override per curve via colorParams.hslCurveMeta = {satVsSat: 2}.
  const metaOverrides = colorParams.hslCurveMeta || {};
  for (const { key, splineId, metaId } of types) {
    const pts = hsl[key];
    if (!pts || pts.length === 0) continue;
    hasAny = true;
    const metaVal = metaOverrides[key] !== undefined ? metaOverrides[key] : 6;
    entries.push(protoBytes(3, Buffer.concat([
      protoVarint(1, metaId),
      protoBytes(2, encodeCurveMeta(metaVal)),
    ])));
    // Spline data — HSL uses raw float coordinate space (NOT 0-1023)
    // X = hue fraction (0.0-1.0 with wrap), Y = value (0.5 = neutral)
    entries.push(protoBytes(3, Buffer.concat([
      protoVarint(1, splineId),
      protoBytes(2, encodeHSLCurveSpline(pts)),
    ])));
    debugLog('[DRX] HSL Curve ' + key + ': ' + pts.length + ' control points (float space)');
  }
  if (hasAny) {
    // Common flag (always {F2: 2} when any HSL curve is active)
    entries.push(protoBytes(3, Buffer.concat([
      protoVarint(1, PARAM_IDS.HSL_COMMON_FLAG),
      protoBytes(2, protoVarint(2, 2)),
    ])));
  }
  return entries;
}

/**
 * Create a basic node structure
 *
 * @param {number} nodeId - Unique node ID
 * @param {number} xPos - X position in node graph
 * @param {number} yPos - Y position in node graph
 * @param {Object} colorParams - Color grading parameters
 * @param {Object} options - Additional options (label, enabled, correctorTypes)
 */
function createNode(nodeId, xPos, yPos, colorParams = null, options = {}) {
  const { label = '', enabled = true, nodeIndex = nodeId } = options;

  // Build node header with fields in order: F1, F2, F4, F5, F6, F7?, F8
  // Native Resolve analysis shows: id(F1), index(F2), pos(F4,F5), label?(F6), F8=44
  // F7 (enabled) only appears when disabled - not included for enabled nodes
  const parts = [
    protoVarint(1, nodeId),       // F1: Node ID (unique identifier, e.g., 36, 37)
    protoVarint(2, nodeIndex),    // F2: Node index (sequential, e.g., 1, 2)
    protoVarint(4, xPos),         // F4: X position
    protoVarint(5, yPos),         // F5: Y position
  ];

  // Add label if provided (F6 comes before F7/F8)
  if (label) {
    parts.push(protoBytes(6, Buffer.from(label, 'utf-8')));
  }

  // F7 = 1 for ENABLED nodes (native Resolve analysis shows F7=1 when enabled)
  // F7 = 0 for DISABLED nodes
  parts.push(protoVarint(7, enabled ? 1 : 0));

  parts.push(protoVarint(8, 44)); // F8: Unknown flag (always 44)

  // Build corrector structure matching Resolve's native format
  // Resolve uses:
  //   F9.F1[] = actual corrector blocks with parameters
  //   F9.F2   = compact byte array of presence marker types [3, 4, 5, 6, 18]
  debugLog('[DRX] createNode called with colorParams:', colorParams ? 'present' : 'null');
  const correctorBlocks = [];  // F1 entries (actual correctors with params)
  const presenceTypes = [];    // Types for compact F2 presence list

  if (colorParams) {
    debugLog('[DRX] colorParams keys:', Object.keys(colorParams));

    // Type 1: Primary Corrector - Lift/Gamma/Gain/Offset/Saturation
    // Only include if there are actual params (Resolve omits neutral Primary)
    const primaryParams = buildPrimaryCorrectorParams(colorParams);
    debugLog('[DRX] Primary params built, length:', primaryParams.length);

    // Type 2: Contrast Corrector - ALWAYS include as F1 block (Resolve pattern)
    // Even when neutral, it gets a presence marker param, NOT the F2 list
    const contrastParams = buildContrastCorrectorParams(colorParams);
    debugLog('[DRX] Contrast params built, length:', contrastParams.length);

    // Custom Curves (YRGB) — spline data goes in Primary corrector as additional F3 entries
    const curveParams = buildCustomCurveParams(colorParams);
    if (curveParams.length > 0) {
      primaryParams.push(...curveParams);
      debugLog('[DRX] Added', curveParams.length, 'custom curve entries to Primary corrector');
    }

    // HSL Curves — spline data also goes in Primary corrector
    const hslParams = buildHSLCurveParams(colorParams);
    if (hslParams.length > 0) {
      primaryParams.push(...hslParams);
      debugLog('[DRX] Added', hslParams.length, 'HSL curve entries to Primary corrector');
    }

    // HDR zones — ALL zones share ONE ZONE_ADJUSTMENTS (0x86000305) param in the
    // Primary corrector, as repeated F16.F1[] zone sub-messages (wire-confirmed on the
    // hdr-zones-grid fixture: 5 zones in a single param, same ct1 block as other params).
    // The old code emitted one param per zone in SEPARATE corrector blocks, so any grade
    // with 2+ zones silently lost all but the last on decode/apply.
    const hdrParams = buildHDRWheelParams(colorParams);
    if (hdrParams.length > 0) {
      const zoneMsgs = hdrParams
        .filter((z) => z.isNested && z.nestedData)
        .map((z) => protoBytes(1, z.nestedData));
      if (zoneMsgs.length > 0) {
        const field16Wrapper = protoBytes(16, Buffer.concat(zoneMsgs));
        const paramEntry = Buffer.concat([
          protoVarint(1, hdrParams[0].paramId),
          protoBytes(2, field16Wrapper),
        ]);
        primaryParams.push(protoBytes(3, paramEntry));
        debugLog('[DRX] Added', zoneMsgs.length, 'HDR zone(s) in one ZONE_ADJUSTMENTS param');
      }
    }

    // HDR zone DEFINITIONS (0x86000306) — custom zone boundary (Max Range) + falloff.
    // Structure decoded 2026-07-03 by two-point capture sweep (see
    // test/hdr-zone-definitions.test.mjs): param value = repeated F17 { F1: record },
    // record = { F1 name (str) · F2 DEFAULT boundary f32 · F3 CURRENT boundary f32 ·
    // F4 DEFAULT falloff f32 · F5 CURRENT falloff f32 }. Defaults ship in native files.
    // STOCK table verification status: Dark [-1.5, 0.2] is capture-VERIFIED; Shadow/
    // Light falloffs 0.22 were read off the panel; the remaining boundaries are
    // UNVERIFIED placeholders — pass explicit defaultBoundary/defaultFalloff for
    // non-Dark zones when display fidelity of the zone editor matters. Only F3/F5
    // (the CURRENT values) affect rendering.
    if (colorParams && Array.isArray(colorParams.hdrZoneDefinitions) && colorParams.hdrZoneDefinitions.length) {
      const STOCK = { Black: [-4.0, 0.2], Dark: [-1.5, 0.2], Shadow: [0.0, 0.22], Light: [0.0, 0.22], Highlight: [2.0, 0.25], Specular: [4.0, 0.25] };
      const f32 = (tag, v) => { const b = Buffer.alloc(5); b[0] = tag; b.writeFloatLE(v, 1); return b; };
      const zoneMsgs = [];
      for (const z of colorParams.hdrZoneDefinitions) {
        if (!z || !z.name) continue;
        const stock = STOCK[z.name] || [z.boundary ?? 0, z.falloff ?? 0.2];
        const defB = z.defaultBoundary ?? stock[0];
        const defF = z.defaultFalloff ?? stock[1];
        const name = Buffer.from(String(z.name), 'utf8');
        const rec = Buffer.concat([
          Buffer.from([0x0a, name.length]), name,
          f32(0x15, defB),
          f32(0x1d, z.boundary ?? defB),
          f32(0x25, defF),
          f32(0x2d, z.falloff ?? defF),
        ]);
        zoneMsgs.push(protoBytes(17, protoBytes(1, rec)));
      }
      if (zoneMsgs.length) {
        primaryParams.push(protoBytes(3, Buffer.concat([
          protoVarint(1, drxParams.HDR_ZONE.ZONE_DEFINITIONS),
          protoBytes(2, Buffer.concat(zoneMsgs)),
        ])));
        debugLog('[DRX] Added', zoneMsgs.length, 'HDR zone DEFINITION record(s)');
      }
    }

    // Add Primary corrector block if we have params
    if (primaryParams.length > 0) {
      correctorBlocks.push(buildCorrectorBlock(CORRECTOR_TYPES.PRIMARY, primaryParams));
    }

    // COMPANION BLOCK + PRESENCE MARKERS
    // Training evidence: Native Resolve DRX exports with curves have NO companion block
    // (Type 2 with 0x88300001). Only Primary (Type 1) + F2 presence markers.
    // The companion block causes errant L.Mix=100 when combined with curve splines
    // and complete desaturation when combined with HSL curves.
    // For non-curve grades (CDL, wheels, etc.) the companion block is harmless but unnecessary.
    const hasCurves = curveParams.length > 0 || hslParams.length > 0;
    if (primaryParams.length > 0 && !hasCurves) {
      // Companion block: corrector type 2 with param 0x88300001 = {F2: 0}
      // Only include for non-curve grades (matches Resolve behavior for simple CDL grades)
      const companionParam = protoBytes(3, Buffer.concat([
        protoVarint(1, 2284847105),  // 0x88300001
        protoBytes(2, protoVarint(2, 0)),
      ]));
      correctorBlocks.push(buildCorrectorBlock(2, [companionParam]));
    }
    if (primaryParams.length > 0) {
      // Presence marker list: types 3, 4, 5, 6, 18 (always present per training evidence)
      presenceTypes.push(3, 4, 5, 6, 18);
    }

    if (contrastParams.length > 0) {
      correctorBlocks.push(buildCorrectorBlock(CORRECTOR_TYPES.CONTRAST, contrastParams));
    }
    // NOTE: Do NOT add presence marker corrector blocks when there are no contrast params.
    // Presence markers cause Resolve to show qualifier/sub-corrector panel indicators,
    // making nodes appear to have HSL qualifiers set when they don't.
    // Resolve adds its own presence markers when it imports the grade.

    // (HDR zones are folded into primaryParams above — single ZONE_ADJUSTMENTS param.)
  } else {
    debugLog('[DRX] No colorParams - using presence marker for Contrast');
    // Contrast still needs F1 block with presence marker
    const contrastPresenceBlock = buildPresenceMarkerCorrectorBlock(CORRECTOR_TYPES.CONTRAST);
    if (contrastPresenceBlock && contrastPresenceBlock.length > 0) {
      correctorBlocks.push(contrastPresenceBlock);
    }
  }

  // Type 3: Saturation vs Saturation
  if (colorParams) {
    const satVsSatParams = buildSatVsSatCorrectorParams(colorParams);
    if (satVsSatParams.length > 0) {
      correctorBlocks.push(buildCorrectorBlock(CORRECTOR_TYPES.SATURATION, satVsSatParams));
    }
  }

  // Type 4: Hue Corrector
  if (colorParams) {
    const hueParams = buildHueCorrectorParams(colorParams);
    if (hueParams.length > 0) {
      correctorBlocks.push(buildCorrectorBlock(CORRECTOR_TYPES.HUE, hueParams));
    }
  }

  // Type 5: Luma vs Saturation
  if (colorParams) {
    const lumMixParams = buildLumMixCorrectorParams(colorParams);
    if (lumMixParams.length > 0) {
      correctorBlocks.push(buildCorrectorBlock(CORRECTOR_TYPES.LUM_MIX, lumMixParams));
    }
  }

  // Type 2 (HSL Qualifier), Type 4 (Power Window), Type 9 (Matte Finesse).
  // Wired in Session 25 after extractQualifier/extractPowerWindow/
  // extractMatteFinesse (P1.3/P1.4/P1.5) had to use synthesized inputs
  // because these emissions never reached createNode. Each is gated on
  // the corresponding param block being non-empty.
  if (colorParams) {
    // One qualifier per node (Resolve has a single qualifier with a mode). Precedence:
    // HSL (`qualifier`) > RGB (`rgbQualifier`) > luma (`lumaQualifier`). RGB/luma wired
    // 2026-07-02 — the builders existed with live-corrected ids but were unreachable.
    let qualParams = buildQualifierParams(colorParams.qualifier);
    if (qualParams.length === 0) qualParams = buildRGBQualifierParams(colorParams.rgbQualifier);
    if (qualParams.length === 0) qualParams = buildLumaQualifierParams(colorParams.lumaQualifier);
    if (qualParams.length > 0) {
      correctorBlocks.push(buildCorrectorBlock(CORRECTOR_TYPES.QUALIFIER, qualParams));
    }
  }
  if (colorParams) {
    const win = buildWindowParams(colorParams.window);
    if (win.transform.length > 0) {
      correctorBlocks.push(buildCorrectorBlock(CORRECTOR_TYPES.POWER_WINDOW, win.transform));
    }
    if (win.softMask.length > 0) {
      // Linear-window softness mask (0x0870xxxx) lives under corrector type 3 in live data.
      correctorBlocks.push(buildCorrectorBlock(CORRECTOR_TYPES.WINDOW_SOFTNESS, win.softMask));
    }
    if (win.gradient.length > 0) {
      // Gradient window (0x08F0xxxx) lives under compound corrector type 65554.
      correctorBlocks.push(buildCorrectorBlock(CORRECTOR_TYPES.GRADIENT_WINDOW, win.gradient));
    }
    if (win.shape.length > 0) {
      // Polygon/curve freeform shape (0x08D0xxxx vertex rings) lives under corrector
      // type 6 in live data (the registry's ct6 "OFFSET" label predates that finding).
      correctorBlocks.push(buildCorrectorBlock(6, win.shape));
    }
  }
  if (colorParams && (colorParams.matteFinesse || colorParams.key)) {
    // ct9 hosts BOTH Matte Finesse (0x0C30002x, DRX = UI/100) and the Key palette
    // (0x0C30001x, identity — live-swept 2026-07-02). One shared block.
    const { MATTE_FINESSE, KEY_PALETTE } = drxParams;
    const mf = colorParams.matteFinesse || {};
    const mfMap = [
      [MATTE_FINESSE.DENOISE,      mf.denoise],
      [MATTE_FINESSE.BLACK_CLIP,   mf.blackClip],
      [MATTE_FINESSE.WHITE_CLIP,   mf.whiteClip],
      [MATTE_FINESSE.IN_OUT_RATIO, mf.inOutRatio],
      [MATTE_FINESSE.CLEAN_BLACK,  mf.cleanBlack],
      [MATTE_FINESSE.CLEAN_WHITE,  mf.cleanWhite],
      [MATTE_FINESSE.MORPH_RADIUS, mf.morphRadius],
      [MATTE_FINESSE.PRE_FILTER,   mf.preFilter],
      [MATTE_FINESSE.POST_FILTER,  mf.postFilter],
      [MATTE_FINESSE.SHADOW,       mf.shadow],
      [MATTE_FINESSE.MIDTONE,      mf.midtone],
      [MATTE_FINESSE.HIGHLIGHT,    mf.highlight],
    ];
    const ct9Params = [];
    for (const [id, uiVal] of mfMap) {
      if (uiVal !== undefined) ct9Params.push(createParameterEntry(id, uiVal / 100));
    }
    const key = colorParams.key || {};
    const keyMap = [
      [KEY_PALETTE.INPUT_GAIN,    key.inputGain,    1],
      [KEY_PALETTE.INPUT_OFFSET,  key.inputOffset,  0],
      [KEY_PALETTE.OUTPUT_GAIN,   key.outputGain,   1],
      [KEY_PALETTE.OUTPUT_OFFSET, key.outputOffset, 0],
    ];
    for (const [id, uiVal, def] of keyMap) {
      if (uiVal !== undefined && uiVal !== def) ct9Params.push(createParameterEntry(id, uiVal));
    }
    if (ct9Params.length > 0) {
      correctorBlocks.push(buildCorrectorBlock(CORRECTOR_TYPES.MATTE_FINESSE, ct9Params));
    }
  }

  // Blur palette (ct1 scalars, live-swept 2026-07-02): radius/hvRatio stored (UI−0.5)×2,
  // scaling identity. Input: colorParams.blur = { radius, hvRatio, scaling } (UI units,
  // 0.5-neutral for radius/hvRatio, 0.25 default for scaling). Written per-RGB (linked).
  if (colorParams && colorParams.blur) {
    const { BLUR_PALETTE } = drxParams;
    const b = colorParams.blur;
    const blurParams = [];
    if (b.radius !== undefined && b.radius !== 0.5) {
      const v = (b.radius - 0.5) * 2;
      for (const id of [BLUR_PALETTE.RADIUS_R, BLUR_PALETTE.RADIUS_G, BLUR_PALETTE.RADIUS_B]) blurParams.push(createParameterEntry(id, v));
    }
    if (b.hvRatio !== undefined && b.hvRatio !== 0.5) {
      const v = (b.hvRatio - 0.5) * 2;
      for (const id of [BLUR_PALETTE.HV_RATIO_R, BLUR_PALETTE.HV_RATIO_G, BLUR_PALETTE.HV_RATIO_B]) blurParams.push(createParameterEntry(id, v));
    }
    if (b.scaling !== undefined && b.scaling !== 0.25) {
      for (const id of [BLUR_PALETTE.SCALING_R, BLUR_PALETTE.SCALING_G, BLUR_PALETTE.SCALING_B]) blurParams.push(createParameterEntry(id, b.scaling));
    }
    if (blurParams.length > 0) {
      correctorBlocks.push(buildCorrectorBlock(CORRECTOR_TYPES.PRIMARY, blurParams));
    }
  }

  // Motion Effects palette (NEW corrector type ct15, live-swept 2026-07-02). Identity
  // params write 1:1; frames writes the observed varint form (UI frames × 2 —
  // single-point hypothesis, matches the keyframe half-frame convention).
  // temporalMotion/motionBlur scales CONFIRMED by three-point panel capture 2026-07-03:
  //   temporalMotion: stored = 0.28×UI + 2.0  (UI 35→11.8, 60→18.8, 80→24.4 exact)
  //   motionBlur:     stored = 0.0099×UI      (UI 50→0.495, 25→0.2475 exact)
  // Callers pass UI panel values; the mapping is applied here.
  if (colorParams && colorParams.motionEffects) {
    const { MOTION_EFFECTS } = drxParams;
    const m = colorParams.motionEffects;
    const meParams = [];
    const meMap = [
      [MOTION_EFFECTS.SPATIAL_LUMA,    m.spatialLuma],
      [MOTION_EFFECTS.SPATIAL_CHROMA,  m.spatialChroma],
      [MOTION_EFFECTS.SPATIAL_BLEND,   m.spatialBlend],
      [MOTION_EFFECTS.TEMPORAL_LUMA,   m.temporalLuma],
      [MOTION_EFFECTS.TEMPORAL_CHROMA, m.temporalChroma],
      [MOTION_EFFECTS.TEMPORAL_BLEND,  m.temporalBlend],
      [MOTION_EFFECTS.TEMPORAL_MOTION, m.temporalMotion === undefined ? undefined : 0.28 * m.temporalMotion + 2.0],
      [MOTION_EFFECTS.MOTION_BLUR,     m.motionBlur === undefined ? undefined : 0.0099 * m.motionBlur],
    ];
    for (const [id, uiVal] of meMap) {
      if (uiVal !== undefined && uiVal !== 0) meParams.push(createParameterEntry(id, uiVal));
    }
    if (m.frames !== undefined && m.frames !== 0) {
      meParams.push(createVarintParameterEntry(MOTION_EFFECTS.FRAMES_FLAG, m.frames * 2));
    }
    if (meParams.length > 0) {
      correctorBlocks.push(buildCorrectorBlock(CORRECTOR_TYPES.MOTION_EFFECTS, meParams));
    }
  }

  // NOTE: Types 3, 4, 5, 6, 18 are OMITTED from the F2 presence list.
  // While native Resolve DRX files include these as markers for sub-corrector
  // panels (Sat vs Sat, Hue, Lum vs Sat, Offset, Curves), our encoding was
  // causing Resolve to interpret nodes as having HSL qualifiers set.
  // The F1 corrector blocks (Primary + Contrast) are sufficient for the
  // corrections to apply. Users can manually add sub-correctors in Resolve.
  // If we need to encode these in the future, the wire format needs to match
  // Resolve's native packed-varint encoding exactly.

  // Build F9 node settings: F1[] for corrector blocks, F2 for presence list
  const f9Parts = [];

  // Add corrector blocks as F1 entries
  for (const block of correctorBlocks) {
    if (block && block.length > 0) {
      f9Parts.push(block);  // Already wrapped as F1
    }
  }

  // Add compact presence list as F2 (raw byte array of type IDs)
  if (presenceTypes.length > 0) {
    const presenceBytes = Buffer.from(presenceTypes);
    f9Parts.push(protoBytes(2, presenceBytes));
    debugLog('[DRX] Added F2 presence list:', presenceTypes);
  }

  debugLog('[DRX] Total F1 corrector blocks:', correctorBlocks.filter(b => b && b.length > 0).length);
  debugLog('[DRX] Presence types in F2:', presenceTypes.length);

  if (f9Parts.length > 0) {
    const nodeSettings = protoBytes(9, Buffer.concat(f9Parts));
    parts.push(nodeSettings);
  } else {
    debugLog('[DRX] WARNING: No correctors generated for this node');
  }

  // F10: node tool list. Default = the bare node marker; when the node carries an
  // OFX spec ({ofx:{pluginId, params, options?}}), emit the full OFX container instead
  // (params are self-describing name/value pairs on the wire — see extract-ofx-params).
  if (colorParams && colorParams.ofx && colorParams.ofx.pluginId) {
    parts.push(buildOFXToolEntry(colorParams.ofx.pluginId, colorParams.ofx.params || {}, colorParams.ofx.options || {}));
  } else {
    // Structure: F10 = {F1 = {F1=0xC0000001, F2={F2=2}}}
    const f10InnerInner = Buffer.concat([
      protoVarint(1, 0xC0000001),       // F1 = 0xC0000001
      protoBytes(2, protoVarint(2, 2)), // F2 = {F2=2}
    ]);
    const f10Outer = protoBytes(1, f10InnerInner);
    parts.push(protoBytes(10, f10Outer));
  }

  // F12: Timestamp - native Resolve analysis shows this IS present in nodes
  const timestamp = Math.floor(Date.now() / 1000);
  parts.push(protoVarint(12, timestamp));

  return protoBytes(7, Buffer.concat(parts));
}

/**
 * Build Primary Corrector parameters (Lift/Gamma/Gain/Offset)
 */
function buildPrimaryCorrectorParams(colorParams) {
  const paramEntries = [];

  debugLog('[DRX] Building primary corrector from params:', JSON.stringify(colorParams, null, 2));

  // Lift (default 0 — guard against undefined to prevent NaN in protobuf)
  if (colorParams.lift) {
    if (colorParams.lift.r != null && colorParams.lift.r !== 0) { debugLog('[DRX] Adding lift.r:', colorParams.lift.r); paramEntries.push(createParameterEntry(PARAM_IDS.LIFT_R, colorParams.lift.r)); }
    if (colorParams.lift.g != null && colorParams.lift.g !== 0) { debugLog('[DRX] Adding lift.g:', colorParams.lift.g); paramEntries.push(createParameterEntry(PARAM_IDS.LIFT_G, colorParams.lift.g)); }
    if (colorParams.lift.b != null && colorParams.lift.b !== 0) { debugLog('[DRX] Adding lift.b:', colorParams.lift.b); paramEntries.push(createParameterEntry(PARAM_IDS.LIFT_B, colorParams.lift.b)); }
    if (colorParams.lift.master != null && colorParams.lift.master !== 0) { debugLog('[DRX] Adding lift.master:', colorParams.lift.master); paramEntries.push(createParameterEntry(PARAM_IDS.LIFT_MASTER, colorParams.lift.master)); }
  }

  // Gain (default 1.0 — guard against undefined)
  if (colorParams.gain) {
    if (colorParams.gain.r != null && colorParams.gain.r !== 1) { debugLog('[DRX] Adding gain.r:', colorParams.gain.r); paramEntries.push(createParameterEntry(PARAM_IDS.GAIN_R, colorParams.gain.r)); }
    if (colorParams.gain.g != null && colorParams.gain.g !== 1) { debugLog('[DRX] Adding gain.g:', colorParams.gain.g); paramEntries.push(createParameterEntry(PARAM_IDS.GAIN_G, colorParams.gain.g)); }
    if (colorParams.gain.b != null && colorParams.gain.b !== 1) { debugLog('[DRX] Adding gain.b:', colorParams.gain.b); paramEntries.push(createParameterEntry(PARAM_IDS.GAIN_B, colorParams.gain.b)); }
    if (colorParams.gain.master != null && colorParams.gain.master !== 1) { debugLog('[DRX] Adding gain.master:', colorParams.gain.master); paramEntries.push(createParameterEntry(PARAM_IDS.GAIN_MASTER, colorParams.gain.master)); }
  }

  // Gamma (default 0 — guard against undefined)
  if (colorParams.gamma) {
    if (colorParams.gamma.r != null && colorParams.gamma.r !== 0) paramEntries.push(createParameterEntry(PARAM_IDS.GAMMA_R, colorParams.gamma.r));
    if (colorParams.gamma.g != null && colorParams.gamma.g !== 0) paramEntries.push(createParameterEntry(PARAM_IDS.GAMMA_G, colorParams.gamma.g));
    if (colorParams.gamma.b != null && colorParams.gamma.b !== 0) paramEntries.push(createParameterEntry(PARAM_IDS.GAMMA_B, colorParams.gamma.b));
    if (colorParams.gamma.master != null && colorParams.gamma.master !== 0) paramEntries.push(createParameterEntry(PARAM_IDS.GAMMA_MASTER, colorParams.gamma.master));
  }

  // Offset (default 0)
  if (colorParams.offset) {
    if (colorParams.offset.r != null && colorParams.offset.r !== 0) paramEntries.push(createParameterEntry(PARAM_IDS.OFFSET_R, colorParams.offset.r));
    if (colorParams.offset.g != null && colorParams.offset.g !== 0) paramEntries.push(createParameterEntry(PARAM_IDS.OFFSET_G, colorParams.offset.g));
    if (colorParams.offset.b != null && colorParams.offset.b !== 0) paramEntries.push(createParameterEntry(PARAM_IDS.OFFSET_B, colorParams.offset.b));
  }

  // Saturation (Resolve Primaries UI: 0-100, unity=50)
  // DRX ENCODING: float multiplier where 1.0 = unity (50 on UI)
  // Conversion: UI value / 50 = DRX float (0→0.0, 50→1.0, 70→1.4, 100→2.0)
  // Discovered via DRX AutoResearch 2026-03-17: manual Sat 70 in Resolve → 1.4 in DRX body.
  if (colorParams.saturation !== undefined && colorParams.saturation !== 50) {
    const satFloat = colorParams.saturation / 50;
    debugLog('[DRX] Adding saturation:', colorParams.saturation, '→ DRX float:', satFloat);
    paramEntries.push(createParameterEntry(PARAM_IDS.SATURATION_PRIMARY, satFloat));
  } else {
    debugLog('[DRX] Skipping saturation - value:', colorParams.saturation, '(unity=50)');
  }

  // Hue Rotate (0-100 UI, default 50, DRX encoding: (UI - 50) / 50)
  if (colorParams.hueRotate !== undefined && colorParams.hueRotate !== 50) {
    const hueFloat = (colorParams.hueRotate - 50) / 50;
    debugLog('[DRX] Adding hueRotate:', colorParams.hueRotate, '→ DRX float:', hueFloat);
    paramEntries.push(createParameterEntry(PARAM_IDS.HUE_ROTATE, hueFloat));
  }

  // Temperature (default 0)
  if (colorParams.temperature !== undefined && colorParams.temperature !== 0) {
    paramEntries.push(createParameterEntry(PARAM_IDS.TEMPERATURE, colorParams.temperature));
  }

  // Tint (default 0)
  if (colorParams.tint !== undefined && colorParams.tint !== 0) {
    paramEntries.push(createParameterEntry(PARAM_IDS.TINT, colorParams.tint));
  }

  // Midtone Detail (default 0)
  // Scaling happens in parseAdjustments (simple mode ×100, direct mode pass-through)
  if (colorParams.midtoneDetail !== undefined && colorParams.midtoneDetail !== 0) {
    debugLog('[DRX] Adding midtoneDetail:', colorParams.midtoneDetail);
    paramEntries.push(createParameterEntry(PARAM_IDS.MIDTONE_DETAIL, colorParams.midtoneDetail));
  }

  // Contrast (default 1.0)
  if (colorParams.contrast !== undefined && colorParams.contrast !== 1) {
    debugLog('[DRX] Adding contrast to Primary block via LOG_CONTRAST:', colorParams.contrast);
    paramEntries.push(createParameterEntry(PARAM_IDS.LOG_CONTRAST, colorParams.contrast));
  }

  // Pivot (default 0.435)
  if (colorParams.pivot !== undefined && colorParams.pivot !== 0.435) {
    debugLog('[DRX] Adding pivot to Primary block:', colorParams.pivot);
    paramEntries.push(createParameterEntry(PARAM_IDS.PIVOT_PRIMARY, colorParams.pivot));
  }

  // Color Boost (default 0)
  if (colorParams.colorBoost !== undefined && colorParams.colorBoost !== 0) {
    debugLog('[DRX] Adding colorBoost to Primary block:', colorParams.colorBoost);
    paramEntries.push(createParameterEntry(PARAM_IDS.COLOR_BOOST, colorParams.colorBoost));
  }

  // Soft Clip High (default 1.0)
  if (colorParams.softClipHigh !== undefined && colorParams.softClipHigh !== 1) {
    const scVal = colorParams.softClipHigh;
    debugLog('[DRX] Adding softClipHigh R/G/B to Primary block:', scVal);
    paramEntries.push(createParameterEntry(PARAM_IDS.SOFT_CLIP_HIGH_R, scVal));
    paramEntries.push(createParameterEntry(PARAM_IDS.SOFT_CLIP_HIGH_G, scVal));
    paramEntries.push(createParameterEntry(PARAM_IDS.SOFT_CLIP_HIGH_B, scVal));
  }

  // Soft Clip Low (default 0)
  if (colorParams.softClipLow !== undefined && colorParams.softClipLow !== 0) {
    const scVal = colorParams.softClipLow;
    debugLog('[DRX] Adding softClipLow R/G/B to Primary block:', scVal);
    paramEntries.push(createParameterEntry(PARAM_IDS.SOFT_CLIP_LOW_R, scVal));
    paramEntries.push(createParameterEntry(PARAM_IDS.SOFT_CLIP_LOW_G, scVal));
    paramEntries.push(createParameterEntry(PARAM_IDS.SOFT_CLIP_LOW_B, scVal));
  }

  // Soft Clip Low Soft (default 0, encoding: UI / 50)
  if (colorParams.softClipLowSoft !== undefined && colorParams.softClipLowSoft !== 0) {
    const scVal = colorParams.softClipLowSoft / 50;
    debugLog('[DRX] Adding softClipLowSoft R/G/B:', colorParams.softClipLowSoft, '→', scVal);
    paramEntries.push(createParameterEntry(PARAM_IDS.SOFT_CLIP_LOW_SOFT_R, scVal));
    paramEntries.push(createParameterEntry(PARAM_IDS.SOFT_CLIP_LOW_SOFT_G, scVal));
    paramEntries.push(createParameterEntry(PARAM_IDS.SOFT_CLIP_LOW_SOFT_B, scVal));
  }

  // Soft Clip High Soft (default 0, encoding: UI / 50)
  if (colorParams.softClipHighSoft !== undefined && colorParams.softClipHighSoft !== 0) {
    const scVal = colorParams.softClipHighSoft / 50;
    debugLog('[DRX] Adding softClipHighSoft R/G/B:', colorParams.softClipHighSoft, '→', scVal);
    paramEntries.push(createParameterEntry(PARAM_IDS.SOFT_CLIP_HIGH_SOFT_R, scVal));
    paramEntries.push(createParameterEntry(PARAM_IDS.SOFT_CLIP_HIGH_SOFT_G, scVal));
    paramEntries.push(createParameterEntry(PARAM_IDS.SOFT_CLIP_HIGH_SOFT_B, scVal));
  }

  // Contrast High Range (default 0.550 in UI, INVERTED encoding: DRX = 1.0 - UI)
  if (colorParams.contrastHighRange !== undefined && Math.abs(colorParams.contrastHighRange - 0.55) > 0.001) {
    const drxVal = 1.0 - colorParams.contrastHighRange;
    debugLog('[DRX] Adding contrastHighRange to Primary block: UI', colorParams.contrastHighRange, '→ DRX', drxVal);
    paramEntries.push(createParameterEntry(PARAM_IDS.CONTRAST_HIGH_RANGE_PRIMARY, drxVal));
  }

  // Contrast Low Range (default 0.333)
  if (colorParams.contrastLowRange !== undefined && Math.abs(colorParams.contrastLowRange - 0.333) > 0.001) {
    debugLog('[DRX] Adding contrastLowRange to Primary block:', colorParams.contrastLowRange);
    paramEntries.push(createParameterEntry(PARAM_IDS.CONTRAST_LOW_RANGE_PRIMARY, colorParams.contrastLowRange));
  }

  // Black Offset (default 0)
  if (colorParams.blackOffset !== undefined && colorParams.blackOffset !== 0) {
    debugLog('[DRX] Adding blackOffset:', colorParams.blackOffset);
    paramEntries.push(createParameterEntry(PARAM_IDS.HDR_BLACK_OFFSET, colorParams.blackOffset));
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // LOG WHEELS (offset-style grading) - correctorType: 1 (Primary)
  // These are part of the Primary corrector, NOT contrast corrector
  // ═══════════════════════════════════════════════════════════════════════════

  // Log Shadow (Low)
  if (colorParams.logShadow) {
    if (colorParams.logShadow.r != null && colorParams.logShadow.r !== 0) {
      debugLog('[DRX] Adding logShadow.r:', colorParams.logShadow.r);
      paramEntries.push(createParameterEntry(PARAM_IDS.LOG_SHADOW_R, colorParams.logShadow.r));
    }
    if (colorParams.logShadow.g != null && colorParams.logShadow.g !== 0) {
      debugLog('[DRX] Adding logShadow.g:', colorParams.logShadow.g);
      paramEntries.push(createParameterEntry(PARAM_IDS.LOG_SHADOW_G, colorParams.logShadow.g));
    }
    if (colorParams.logShadow.b != null && colorParams.logShadow.b !== 0) {
      debugLog('[DRX] Adding logShadow.b:', colorParams.logShadow.b);
      paramEntries.push(createParameterEntry(PARAM_IDS.LOG_SHADOW_B, colorParams.logShadow.b));
    }
  }

  // Log Midtone (Mid)
  if (colorParams.logMid) {
    if (colorParams.logMid.r != null && colorParams.logMid.r !== 0) {
      debugLog('[DRX] Adding logMid.r:', colorParams.logMid.r);
      paramEntries.push(createParameterEntry(PARAM_IDS.LOG_MIDTONE_R, colorParams.logMid.r));
    }
    if (colorParams.logMid.g != null && colorParams.logMid.g !== 0) {
      debugLog('[DRX] Adding logMid.g:', colorParams.logMid.g);
      paramEntries.push(createParameterEntry(PARAM_IDS.LOG_MIDTONE_G, colorParams.logMid.g));
    }
    if (colorParams.logMid.b != null && colorParams.logMid.b !== 0) {
      debugLog('[DRX] Adding logMid.b:', colorParams.logMid.b);
      paramEntries.push(createParameterEntry(PARAM_IDS.LOG_MIDTONE_B, colorParams.logMid.b));
    }
  }

  // Log Highlight (High)
  if (colorParams.logHigh) {
    if (colorParams.logHigh.r != null && colorParams.logHigh.r !== 0) {
      debugLog('[DRX] Adding logHigh.r:', colorParams.logHigh.r);
      paramEntries.push(createParameterEntry(PARAM_IDS.LOG_HIGHLIGHT_R, colorParams.logHigh.r));
    }
    if (colorParams.logHigh.g != null && colorParams.logHigh.g !== 0) {
      debugLog('[DRX] Adding logHigh.g:', colorParams.logHigh.g);
      paramEntries.push(createParameterEntry(PARAM_IDS.LOG_HIGHLIGHT_G, colorParams.logHigh.g));
    }
    if (colorParams.logHigh.b != null && colorParams.logHigh.b !== 0) {
      debugLog('[DRX] Adding logHigh.b:', colorParams.logHigh.b);
      paramEntries.push(createParameterEntry(PARAM_IDS.LOG_HIGHLIGHT_B, colorParams.logHigh.b));
    }
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // RGB MIXER (3x3 channel mixing matrix)
  // Param IDs trained 2026-03-17 from rgbmixer_1.1.2.drx
  // ═══════════════════════════════════════════════════════════════════════════
  if (colorParams.rgbMixer) {
    const mx = colorParams.rgbMixer;
    // Identity matrix defaults: diagonal=1.0, off-diagonal=0.0
    const entries = [
      { id: PARAM_IDS.RGB_MIXER_RR, val: mx.rr, def: 1.0 },
      { id: PARAM_IDS.RGB_MIXER_GR, val: mx.gr, def: 0.0 },
      { id: PARAM_IDS.RGB_MIXER_BR, val: mx.br, def: 0.0 },
      { id: PARAM_IDS.RGB_MIXER_RG, val: mx.rg, def: 0.0 },
      { id: PARAM_IDS.RGB_MIXER_GG, val: mx.gg, def: 1.0 },
      { id: PARAM_IDS.RGB_MIXER_BG, val: mx.bg, def: 0.0 },
      { id: PARAM_IDS.RGB_MIXER_RB, val: mx.rb, def: 0.0 },
      { id: PARAM_IDS.RGB_MIXER_GB, val: mx.gb, def: 0.0 },
      { id: PARAM_IDS.RGB_MIXER_BB, val: mx.bb, def: 1.0 },
    ];
    // Always write all 9 values when RGB mixer is specified (Resolve expects complete matrix)
    for (const { id, val, def } of entries) {
      const v = val !== undefined ? val : def;
      paramEntries.push(createParameterEntry(id, v));
    }
    debugLog('[DRX] RGB Mixer: RR=' + (mx.rr ?? 1) + ' GG=' + (mx.gg ?? 1) + ' BB=' + (mx.bb ?? 1));
  }

  // Highlights slider (default 0)
  if (colorParams.highlights !== undefined && colorParams.highlights !== 0) {
    debugLog('[DRX] Adding highlights:', colorParams.highlights);
    paramEntries.push(createParameterEntry(PARAM_IDS.HIGHLIGHTS, colorParams.highlights));
  }

  // Shadows slider (direct value, e.g., 50)
  if (colorParams.shadows !== undefined && colorParams.shadows !== 0) {
    debugLog('[DRX] Adding shadows:', colorParams.shadows);
    paramEntries.push(createParameterEntry(PARAM_IDS.SHADOWS, colorParams.shadows));
  }

  // Lum Mix slider (0.0-1.0, default 0)
  if (colorParams.lumMixSlider !== undefined && colorParams.lumMixSlider !== 0) {
    debugLog('[DRX] Adding lumMixSlider:', colorParams.lumMixSlider);
    paramEntries.push(createParameterEntry(PARAM_IDS.LUM_MIX_SLIDER, colorParams.lumMixSlider));
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // COLORSLICE global controls (0x86000600–605, ct1) — WRITE PATH ADDED 2026-07-02.
  // Identity scale for all except Hue, which Resolve stores NEGATED (UI +X → −X);
  // calibrated live 2026-06-22. Per-vector grid (0x86000606 blob) is decode-only.
  // ═══════════════════════════════════════════════════════════════════════════
  if (colorParams.colorSlice) {
    const CS = drxParams.COLORSLICE;
    const cs = colorParams.colorSlice;
    const csMap = [
      [CS.DENSITY, cs.density, 0],
      [CS.DENSITY_DEPTH, cs.densityDepth, 0],
      [CS.SAT, cs.sat, 1],
      [CS.SAT_BALANCE, cs.satBalance, 0],
      [CS.SAT_DEPTH, cs.satDepth, 0],
      [CS.HUE, cs.hue !== undefined ? -cs.hue : undefined, 0], // NEGATED
    ];
    let n = 0;
    for (const [id, val, def] of csMap) {
      if (val !== undefined && val !== def) { paramEntries.push(createParameterEntry(id, val)); n++; }
    }
    if (n) debugLog('[DRX] ColorSlice global params:', n);
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // COLOR WARPER (chroma-warp pin list, ct1) — WRITE PATH ADDED 2026-07-02.
  // Wire (RE'd live 2026-06-22): mode/config varints 0x86000133/136/137 + pins at
  // 0x86000138 = { F2: { F27: { F1: [ <pin>, … ] } } }; pin = { F1=id, F2/F3=src XY,
  // F4/F5=dst XY, F6=chromaRange, F7=exposure (omit 0), F8/F9/F10=tonal low/high/pivot }.
  // All floats identity-scale vs the UI Pin controls.
  // ═══════════════════════════════════════════════════════════════════════════
  if (colorParams.colorWarper && Array.isArray(colorParams.colorWarper.pins) && colorParams.colorWarper.pins.length > 0) {
    const CW = drxParams.COLOR_WARPER;
    const w = colorParams.colorWarper;
    // The live chroma-warp fixture carries configA=2 + configB=2 and NO MODE_FLAG param —
    // mirror it exactly (a mode override is still possible via w.mode).
    if (w.mode !== undefined) paramEntries.push(createVarintParameterEntry(CW.MODE_FLAG, w.mode));
    paramEntries.push(createVarintParameterEntry(CW.CONFIG_A, w.configA !== undefined ? w.configA : 2));
    paramEntries.push(createVarintParameterEntry(CW.CONFIG_B, w.configB !== undefined ? w.configB : 2));
    const pinMsgs = [];
    for (const [i, pin] of w.pins.entries()) {
      const parts = [protoVarint(1, pin.id !== undefined ? pin.id : i + 1)];
      const f32 = (fieldNum, v) => { if (typeof v === 'number') parts.push(protoFloat32(fieldNum, v)); };
      f32(2, pin.srcX); f32(3, pin.srcY);
      f32(4, pin.dstX); f32(5, pin.dstY);
      f32(6, pin.chromaRange);
      if (typeof pin.exposure === 'number' && pin.exposure !== 0) f32(7, pin.exposure);
      f32(8, pin.tonalLow); f32(9, pin.tonalHigh); f32(10, pin.tonalPivot);
      pinMsgs.push(protoBytes(1, Buffer.concat(parts)));
    }
    const envelope = protoBytes(27, Buffer.concat(pinMsgs)); // F27 = pin list container
    const pinsEntry = protoBytes(3, Buffer.concat([
      protoVarint(1, CW.PINS),
      protoBytes(2, envelope),
    ]));
    paramEntries.push(pinsEntry);
    debugLog('[DRX] Color Warper pins:', w.pins.length);
  }

  debugLog('[DRX] Primary corrector entries count:', paramEntries.length);
  return paramEntries;
}

/**
 * Build Contrast Corrector parameters (Contrast, Pivot, Soft Clip)
 */
function buildContrastCorrectorParams(colorParams) {
  const paramEntries = [];

  // NOTE: ALL params that were formerly in this Type 2 block have been moved to
  // buildPrimaryCorrectorParams() (Type 1). DRX AutoResearch 2026-03-17 confirmed
  // that Resolve stores contrast, pivot, colorBoost, softClip, and range controls
  // in the Primary corrector with TEMP_TINT-style param IDs. Putting them in the
  // Type 2 Contrast corrector causes Resolve to misinterpret the block as an
  // HSL Qualifier, corrupting the grade.
  //
  // This function now returns empty — the Type 2 corrector block will not be generated.
  debugLog('[DRX] Contrast corrector (Type 2) empty - all params in Primary (Type 1)');
  return paramEntries;
}

/**
 * Build Hue Corrector parameters (Type 4).
 *
 * Hue correction adjusts hue rotation per tonal range. The 6 parameter IDs
 * have been discovered from DRX analysis but their semantic mapping (which
 * param controls which hue range) is NOT yet confirmed from training data.
 *
 * HYPOTHESIZED semantic mapping (needs training session to confirm):
 *   PARAM_1 (139460609) — possibly master hue rotate or red hue shift
 *   PARAM_2 (139460612) — possibly yellow or green hue shift
 *   PARAM_3 (139460613) — possibly green or cyan hue shift
 *   PARAM_4 (139460614) — possibly cyan or blue hue shift
 *   PARAM_5 (139460619) — possibly blue or magenta hue shift
 *   PARAM_6 (139460620) — possibly magenta hue shift or mix
 *
 * Usage: Pass raw param values keyed by ID until semantics are confirmed:
 *   { hue: { [HUE.PARAM_1]: 0.5, [HUE.PARAM_3]: -0.2 } }
 *
 * @param {object} colorParams - contains `hue` object with paramId keys
 * @returns {Buffer[]} - encoded parameter entries
 */
function buildHueCorrectorParams(colorParams) {
  const paramEntries = [];
  if (!colorParams.hue) return paramEntries;

  const hueParams = colorParams.hue;
  for (const [paramId, value] of Object.entries(hueParams)) {
    const id = Number(paramId);
    if (isNaN(id) || value === undefined || value === 0) continue;
    paramEntries.push(createParameterEntry(id, value));
  }

  if (paramEntries.length > 0) {
    debugLog('[DRX] Hue corrector entries:', paramEntries.length);
  }
  return paramEntries;
}

/**
 * Build Luma vs Saturation parameters (Type 5).
 *
 * Controls how saturation is modulated based on luminance. The 11 parameter IDs
 * have been discovered but their semantic mapping is NOT yet confirmed.
 *
 * HYPOTHESIZED: These likely represent control points on a curve where:
 *   - X axis = luminance (dark to bright)
 *   - Y axis = saturation multiplier
 *   - 11 points define the spline shape
 *
 * Usage: Pass raw param values keyed by ID:
 *   { lumMix: { [LUM_MIX.PARAM_1]: 0.8, [LUM_MIX.PARAM_5]: 1.2 } }
 *
 * @param {object} colorParams - contains `lumMix` object with paramId keys
 * @returns {Buffer[]} - encoded parameter entries
 */
function buildLumMixCorrectorParams(colorParams) {
  const paramEntries = [];
  if (!colorParams.lumMix) return paramEntries;

  const lumParams = colorParams.lumMix;
  for (const [paramId, value] of Object.entries(lumParams)) {
    const id = Number(paramId);
    if (isNaN(id) || value === undefined) continue;
    paramEntries.push(createParameterEntry(id, value));
  }

  if (paramEntries.length > 0) {
    debugLog('[DRX] LumMix corrector entries:', paramEntries.length);
  }
  return paramEntries;
}

/**
 * Build Saturation vs Saturation parameters (Type 3).
 *
 * Controls how saturation is modulated based on existing saturation level.
 * The 7 parameter IDs are discovered but semantics NOT confirmed.
 *
 * Usage: Pass raw param values keyed by ID:
 *   { satVsSat: { [SAT_VS_SAT.PARAM_1]: 0.5 } }
 *
 * @param {object} colorParams - contains `satVsSat` object with paramId keys
 * @returns {Buffer[]} - encoded parameter entries
 */
function buildSatVsSatCorrectorParams(colorParams) {
  const paramEntries = [];
  if (!colorParams.satVsSat) return paramEntries;

  const satParams = colorParams.satVsSat;
  for (const [paramId, value] of Object.entries(satParams)) {
    const id = Number(paramId);
    if (isNaN(id) || value === undefined) continue;
    paramEntries.push(createParameterEntry(id, value));
  }

  if (paramEntries.length > 0) {
    debugLog('[DRX] SatVsSat corrector entries:', paramEntries.length);
  }
  return paramEntries;
}

/**
 * Build a presence marker parameter entry for corrector types 2-18
 * These markers tell Resolve the corrector exists but is at neutral/bypass state
 *
 * Real Resolve format: F3 { F1=presenceId, F2={ F2=0 } }
 * Much simpler than originally thought - just a single nested F2=0
 */
function createPresenceMarkerEntry(correctorType) {
  const presenceId = PRESENCE_MARKER_IDS[correctorType];
  if (!presenceId) return null;

  // Value message: F2 = 0 (simple varint, matching real Resolve format)
  // Real Resolve uses: 10 00 = F2 = 0
  const valueMsg = protoVarint(2, 0);

  // Outer entry: F1=presenceId, F2=valueMsg
  const entry = Buffer.concat([
    protoVarint(1, presenceId),
    protoBytes(2, valueMsg),
  ]);

  return protoBytes(3, entry);
}

/**
 * Build a presence marker corrector block (for types 2, 3, 4, 5, 6, 18)
 * These are minimal correctors that tell Resolve the node has these capabilities
 */
function buildPresenceMarkerCorrectorBlock(correctorType) {
  const presenceEntry = createPresenceMarkerEntry(correctorType);
  if (!presenceEntry) return Buffer.alloc(0);

  // Parameter container: F1=1 (header), F3=presence entry
  const field2Content = Buffer.concat([
    protoVarint(1, 1),
    presenceEntry,
  ]);
  const field2 = protoBytes(2, field2Content);

  // Outer container
  const field6 = protoBytes(6, field2);

  // Build corrector block
  const correctorBlock = Buffer.concat([
    protoVarint(1, correctorType),
    protoVarint(3, 1), // Enabled
    field6,
  ]);

  return protoBytes(1, correctorBlock);
}

/**
 * Build a corrector block (wraps parameters in proper protobuf structure)
 *
 * Based on training-analyzer.js parser, the structure is:
 * Field 1 (corrector block wrapper):
 *   Field 1: corrector type ID
 *   Field 3: enabled flag (1 = enabled)
 *   Field 6: outer container
 *     Field 2: parameter container
 *       Field 1: header (value 1)
 *       Field 3[]: parameter entries (Field 1=ID, Field 2={Field 1=float})
 */
function buildCorrectorBlock(correctorType, paramEntries) {
  if (paramEntries.length === 0) return Buffer.alloc(0);

  // Parameter container: Field 1 = 1 (header), then Field 3[] for each param
  const field2Content = Buffer.concat([
    protoVarint(1, 1), // Required header field (F1 = 1)
    ...paramEntries,   // Each param is wrapped in Field 3
  ]);
  const field2 = protoBytes(2, field2Content);

  // Outer container: Field 6 wraps Field 2
  const field6 = protoBytes(6, field2);

  // Build corrector block
  const correctorBlock = Buffer.concat([
    protoVarint(1, correctorType), // Corrector type ID
    protoVarint(3, 1),             // Enabled flag
    field6,                        // Parameters in F6->F2
  ]);

  debugLog('[DRX] Built corrector block type:', correctorType, 'with', paramEntries.length, 'params');
  return protoBytes(1, correctorBlock);
}

/**
 * Create a node connection
 */
function createConnection(sourceNode, targetNode, index) {
  const conn = Buffer.concat([
    protoVarint(1, sourceNode),
    protoVarint(3, targetNode),
    protoVarint(5, 64),
    protoVarint(6, 64),
    protoVarint(7, index),
  ]);
  return protoBytes(8, conn);
}

/**
 * Create resolution/transform message
 */
function createResolution(width = 1920, height = 1080) {
  return protoBytes(3, Buffer.concat([
    protoVarint(1, width),
    protoVarint(2, height),
    protoFloat32(3, 1.0),
    protoVarint(4, width),
    protoVarint(5, height),
    protoFloat32(6, 1.0),
    protoVarint(7, width),
    protoVarint(8, height),
    protoVarint(9, 0xFFFFFFFF), // F9 = -1 (required by Resolve, matches native exports)
  ]));
}

/**
 * Create Input/Output node markers (Field 9 and Field 10 in main container)
 * These are required for Resolve to recognize the grade structure
 *
 * Based on ULTRA-DEEP analysis of Resolve's 1-6 node DRX exports:
 * Pattern discovered (using firstNodeId=36 as example):
 * - Input (F9): F1=66(+30), F2=80, F3={F1=69(+33), F2=64, F3=66(+30), F4=firstNodeId}
 * - Output (F10): F1=67(+31), F2=64, F3={F1=69+nodeCount, F2=64, F3=67(+31), F4=lastNodeId}
 *
 * The input marker values are CONSTANT (don't change with node count)
 * Only output F3.F1 and F3.F4 change based on node count
 *
 * @param {number} firstNodeId - ID of the first node (input connects TO this)
 * @param {number} lastNodeId - ID of the last node (output connects FROM this)
 * @param {number} nodeCount - Total number of nodes
 */
function createInputOutputMarkers(firstNodeId = 1, lastNodeId = 1, nodeCount = 1) {
  // CRITICAL: F9/F10 values must be calculated from actual node IDs
  //
  // Analysis of Resolve's native DRX export for node ID 66:
  //   F9.F1 = 72 = 66 + 6
  //   F10.F1 = 73 = 66 + 7
  //   F9.F3.F1 = 88 = 66 + 22
  //   F10.F3.F1 = 89 = 66 + 23
  //
  // The formula is:
  //   F9.F1 = firstNodeId + 6
  //   F10.F1 = lastNodeId + 7
  //   F9.F3.F1 = firstNodeId + 22
  //   F10.F3.F1 = lastNodeId + 23
  //
  // Using actual node IDs ensures Resolve recognizes the grade structure

  const inputF1 = firstNodeId + 6;        // F9.F1 = firstNodeId + 6
  const outputF1 = lastNodeId + 7;        // F10.F1 = lastNodeId + 7
  const inputInnerF1 = firstNodeId + 22;  // F9.F3.F1 = firstNodeId + 22
  const outputInnerF1 = lastNodeId + 23;  // F10.F3.F1 = lastNodeId + 23

  // Field 9: Input node marker
  // Structure: F1=inputF1, F2=80, F3={F1=inputInnerF1, F2=64, F3=inputF1, F4=firstNodeId}
  const inputInner = Buffer.concat([
    protoVarint(1, inputInnerF1),   // F1 = firstNodeId + 22
    protoVarint(2, 64),             // F2 = 64
    protoVarint(3, inputF1),        // F3 = same as outer F1
    protoVarint(4, firstNodeId),    // F4 = first node ID (chainStart)
  ]);
  const inputContent = Buffer.concat([
    protoVarint(1, inputF1),        // F1 = firstNodeId + 6
    protoVarint(2, 80),             // F2 = 80 (0x50)
    protoBytes(3, inputInner),      // F3 = connection info
  ]);
  const inputMarker = protoBytes(9, inputContent);

  // Field 10: Output node marker
  // Structure: F1=outputF1, F2=64, F3={F1=outputInnerF1, F2=64, F3=outputF1, F4=lastNodeId}
  const outputInner = Buffer.concat([
    protoVarint(1, outputInnerF1),  // F1 = lastNodeId + 23
    protoVarint(2, 64),             // F2 = 64
    protoVarint(3, outputF1),       // F3 = same as outer F1
    protoVarint(4, lastNodeId),     // F4 = last node ID (chainEnd)
  ]);
  const outputContent = Buffer.concat([
    protoVarint(1, outputF1),       // F1 = lastNodeId + 7
    protoVarint(2, 64),             // F2 = 64 (0x40)
    protoBytes(3, outputInner),     // F3 = connection info
  ]);
  const outputMarker = protoBytes(10, outputContent);

  return { inputMarker, outputMarker };
}

/**
 * Generate a timestamp for DRX files (used in Field 12 and top-level Field 4)
 * Based on analysis, this appears to be a time-based value
 */
function generateTimestamp() {
  // Use current time in a format similar to what Resolve uses
  // The sample value was 149252784 which seems to be seconds from some epoch
  const now = Math.floor(Date.now() / 1000);
  return now;
}

/**
 * Generate the static pTrackVer body
 * From analysis: pTrackVer is IDENTICAL across 1-6 node DRX files
 * Only F1.F12 (timestamp) changes
 *
 * Structure:
 * - F1.F1 = 0xFFFFFFFF (no version)
 * - F1.F2 = 1
 * - F1.F3 = resolution (1920x1080)
 * - F1.F4 = 310722
 * - F1.F9 = {F1=2, F2=64} (input marker)
 * - F1.F10 = {F1=3, F2=64} (output marker)
 * - F1.F11 = 1
 * - F1.F12 = timestamp
 * - F3 = {F4=190, F5=180, F7=1, F8=85} (node position info)
 */
async function generatePTrackVerBody(width = 1920, height = 1080) {
  const timestamp = generateTimestamp();

  // F1 container
  const f1Parts = [
    protoVarint(1, 0xFFFFFFFF),  // F1.F1 = 0xFFFFFFFF (no version)
    protoVarint(2, 1),           // F1.F2 = 1
    createResolution(width, height), // F1.F3 = resolution
    protoVarint(4, 310722),      // F1.F4 = 310722 (constant)
  ];

  // F1.F9 = input marker (simplified)
  const f1f9 = protoBytes(9, Buffer.concat([
    protoVarint(1, 2),
    protoVarint(2, 64),
  ]));
  f1Parts.push(f1f9);

  // F1.F10 = output marker (simplified)
  const f1f10 = protoBytes(10, Buffer.concat([
    protoVarint(1, 3),
    protoVarint(2, 64),
  ]));
  f1Parts.push(f1f10);

  f1Parts.push(protoVarint(11, 1));        // F1.F11 = 1
  f1Parts.push(protoVarint(12, timestamp)); // F1.F12 = timestamp

  const f1Content = protoBytes(1, Buffer.concat(f1Parts));

  // F3 = node position info (matches native Resolve export)
  const f3Parts = [
    protoVarint(4, 190),  // F3.F4 = 190 (x pos)
    protoVarint(5, 180),  // F3.F5 = 180 (y pos)
    protoVarint(7, 1),    // F3.F7 = 1
    protoVarint(8, 85),   // F3.F8 = 85 (0x55, matches native Resolve export)
    protoBytes(9, Buffer.alloc(0)), // F3.F9 = empty
  ];

  // F3.F10 = node metadata
  const f3f10Inner = protoBytes(1, Buffer.concat([
    protoVarint(1, 0xC0000001), // F1 = 0xC0000001
    protoBytes(2, protoVarint(2, 2)), // F2 = {F2=2}
  ]));
  f3Parts.push(protoBytes(10, f3f10Inner));
  f3Parts.push(protoVarint(12, timestamp + 100)); // F3.F12 = timestamp + offset

  const f3Content = protoBytes(3, Buffer.concat(f3Parts));

  // Combine F1 and F3
  const trackBody = Buffer.concat([f1Content, f3Content]);

  // Compress
  const zstd = await getZstdCompressor();
  const compressed = zstd.compress(trackBody);
  return Buffer.concat([Buffer.from([0x81]), Buffer.from(compressed)]).toString('hex');
}

/**
 * Generate the complete protobuf body for a DRX grade
 *
 * @param {Object} gradeParams - Color grading parameters (single node) OR array of nodes
 * @param {Object} options - Generation options
 * @returns {Buffer} - Uncompressed protobuf data
 */
function generateProtobuf(gradeParams, options = {}) {
  const {
    width = 1920,
    height = 1080,
    label = '',
  } = options;

  const timestamp = generateTimestamp();

  // Build main content for Field 1 container
  const containerParts = [
    protoVarint(1, 16),  // Version (always 16)
    protoVarint(2, 1),   // Flag (always 1)
    createResolution(width, height),
  ];

  // Determine first and last node IDs for input/output markers
  let firstNodeId = 1;
  let lastNodeId = 1;

  // Check if we have multiple nodes or a single grade
  if (Array.isArray(gradeParams)) {
    // Multi-node mode
    const nodeSpacing = 270;
    const baseX = 190;
    const baseY = 180;

    lastNodeId = gradeParams.length; // Last node is the count of nodes

    gradeParams.forEach((nodeConfig, index) => {
      const nodeId = index + 1;
      const xPos = baseX + (index * nodeSpacing);
      const yPos = nodeConfig.yPos || baseY;
      const node = createNode(nodeId, xPos, yPos, nodeConfig.params, {
        label: nodeConfig.label || `Node ${nodeId}`,
        enabled: nodeConfig.enabled !== false,
      });
      containerParts.push(node);
    });

    // Create serial connections between nodes
    for (let i = 1; i < gradeParams.length; i++) {
      const conn = createConnection(i, i + 1, i);
      containerParts.push(conn);
    }
  } else {
    // Single node mode (backwards compatible)
    // SAFETY: if gradeParams hasn't been through parseAdjustments yet (e.g. has
    // a 'mode' key or semantic-range temperature like 0.5), warn — callers should
    // always run parseAdjustments() first so scaling and clamping are applied.
    if (gradeParams.temperature !== undefined && Math.abs(gradeParams.temperature) <= 1 && gradeParams.temperature !== 0) {
      console.warn('[DRX] WARNING: gradeParams.temperature=' + gradeParams.temperature + ' looks like semantic range (-1 to +1) — did you forget to call parseAdjustments() first?');
    }
    const node = createNode(1, 500, 300, gradeParams, {
      label: label,
    });
    containerParts.push(node);
    // firstNodeId and lastNodeId both stay 1
  }

  // Determine node count for markers
  const nodeCount = Array.isArray(gradeParams) ? gradeParams.length : 1;

  // Create input/output markers with correct node IDs and count
  const { inputMarker, outputMarker } = createInputOutputMarkers(firstNodeId, lastNodeId, nodeCount);

  // Add required input/output markers and metadata
  containerParts.push(inputMarker);
  containerParts.push(outputMarker);
  containerParts.push(protoVarint(11, 1));        // Unknown flag (always 1)
  containerParts.push(protoVarint(12, timestamp)); // Timestamp

  // Wrap in root Field 1
  const mainContent = protoBytes(1, Buffer.concat(containerParts));

  // Add root-level F3 (node position info) - matches native format
  // Structure: F3 = {F4=190, F5=180, F7=1, F8=84, F9=empty, F10={F1={F1=0xC0000001, F2={F2=2}}}, F12=timestamp}
  const rootF3InnerInner = Buffer.concat([
    protoVarint(1, 0xC0000001),       // F1 = 0xC0000001
    protoBytes(2, protoVarint(2, 2)), // F2 = {F2=2}
  ]);
  const rootF3F10 = protoBytes(1, rootF3InnerInner);

  const rootF3Parts = [
    protoVarint(4, 190),              // F4 = 190 (x pos)
    protoVarint(5, 180),              // F5 = 180 (y pos)
    protoVarint(7, 1),                // F7 = 1
    protoVarint(8, 84),               // F8 = 84 (native analysis shows 0x54)
    protoBytes(9, Buffer.alloc(0)),   // F9 = empty
    protoBytes(10, rootF3F10),        // F10 = node metadata
    protoVarint(12, timestamp),       // F12 = timestamp
  ];
  const rootF3 = protoBytes(3, Buffer.concat(rootF3Parts));

  // Combine F1 and F3 at root level
  const topLevel = Buffer.concat([mainContent, rootF3]);

  return topLevel;
}

/**
 * Generate a multi-node DRX with custom node graph
 *
 * @param {Array} nodes - Array of node configurations
 * @param {Array} connections - Array of connection objects {from, to}
 * @param {Object} metadata - DRX metadata
 * @returns {Promise<string>} - Complete DRX XML content
 */
async function generateMultiNodeDRX(nodes, connections, metadata = {}) {
  const {
    label = 'AI Multi-Node Grade',
    width = 1920,
    height = 1080,
    sourceTimeline = 'Timeline 1',
    sourceTC = '00:00:00:00',
    recordTC = '01:00:00:00',
    pTrackVerXml = null,  // Preserved from original DRX during merge
    preserveNodeIds = false,  // When true, use node.id as-is (for merge mode)
    baseNodeId: passedBaseNodeId,
    firstNodeId: passedFirstNodeId,
    lastNodeId: passedLastNodeId,
  } = metadata;

  const timestamp = generateTimestamp();

  // Determine node ID scheme
  let baseNodeId, firstNodeId, lastNodeId;
  if (preserveNodeIds && passedBaseNodeId !== undefined) {
    // MERGE MODE: use preserved IDs from original grade
    baseNodeId = passedBaseNodeId;
    firstNodeId = passedFirstNodeId;
    lastNodeId = passedLastNodeId;
    debugLog('[DRX] generateMultiNodeDRX: MERGE MODE - preserving node IDs', firstNodeId, '-', lastNodeId);
  } else {
    // FRESH MODE: use standard ID scheme starting from 2 (matches production DRX)
    // Production DRX files NEVER use node ID 1 - minimum is always 2
    // Analysis of 240 production files shows minNodeId is always >= 2
    baseNodeId = 1; // So first node is 2 (production pattern)
    firstNodeId = baseNodeId + 1;
    lastNodeId = baseNodeId + nodes.length;
    debugLog('[DRX] generateMultiNodeDRX: FRESH MODE - generating IDs', firstNodeId, '-', lastNodeId);
  }

  const version = lastNodeId; // Resolve sets version = lastNodeId
  const nodeCount = nodes.length;

  // Build main content for Field 1 container
  const containerParts = [
    protoVarint(1, version),  // Version = lastNodeId (Resolve pattern)
    protoVarint(2, 1),        // Flag
    createResolution(width, height),
  ];

  // Add all nodes
  debugLog('[DRX] generateMultiNodeDRX: processing', nodes.length, 'nodes');
  nodes.forEach((nodeConfig, index) => {
    // Use node's own ID if preserving, otherwise compute from baseNodeId
    const nodeId = preserveNodeIds ? nodeConfig.id : (baseNodeId + index + 1);
    const nodeIndex = index + 1;           // 1, 2, 3, ... (F2 field)
    debugLog(`[DRX] Node ${nodeIndex}: id=${nodeId}, label="${nodeConfig.label}", params:`, nodeConfig.params ? 'present' : 'null');
    if (nodeConfig.params) {
      debugLog(`[DRX] Node ${nodeIndex} params keys:`, Object.keys(nodeConfig.params));
    }
    const node = createNode(
      nodeId,
      nodeConfig.xPos || 190 + (index * 270),
      nodeConfig.yPos || 180,
      nodeConfig.params,
      {
        label: nodeConfig.label || `Node ${nodeIndex}`,
        enabled: nodeConfig.enabled !== false,
        nodeIndex: nodeIndex, // Pass separate index for F2 field
      }
    );
    containerParts.push(node);
  });

  // Add all connections using Resolve's ID scheme
  // Connection F7 starts at (firstNodeId - 40) and increments (discovered from Resolve export analysis)
  // Example: 10-node export with firstNodeId=70 uses F7 = 30, 31, 32...
  const connBaseF7 = preserveNodeIds ? Math.max(firstNodeId - 40, 3) : 3;
  connections.forEach((conn, index) => {
    // In merge mode, connections already have actual node IDs
    // In fresh mode, connections are 1-based and need baseNodeId offset
    const fromId = preserveNodeIds ? conn.from : (baseNodeId + conn.from);
    const toId = preserveNodeIds ? conn.to : (baseNodeId + conn.to);
    const connIndex = connBaseF7 + index;
    const connection = createConnection(fromId, toId, connIndex);
    containerParts.push(connection);
  });

  // Create input/output markers with correct node IDs and node count
  const { inputMarker, outputMarker } = createInputOutputMarkers(firstNodeId, lastNodeId, nodeCount);

  // Add required input/output markers and metadata
  containerParts.push(inputMarker);
  containerParts.push(outputMarker);
  containerParts.push(protoVarint(11, 1));        // Unknown flag (always 1)
  containerParts.push(protoVarint(12, timestamp)); // Timestamp

  // Wrap in root Field 1
  const mainContent = protoBytes(1, Buffer.concat(containerParts));

  // Add root-level F3 (node position info) - native Resolve includes this
  // Structure from native analysis:
  // F3 = {F4=190, F5=180, F7=1, F8=84, F9=empty, F10={F1={F1=0xC0000001, F2={F2=2}}}, F12=timestamp}
  const rootF3InnerInner = Buffer.concat([
    protoVarint(1, 0xC0000001),       // F1 = 0xC0000001
    protoBytes(2, protoVarint(2, 2)), // F2 = {F2=2}
  ]);
  const rootF3F10 = protoBytes(1, rootF3InnerInner);

  const rootF3Parts = [
    protoVarint(4, 190),              // F4 = 190 (x pos)
    protoVarint(5, 180),              // F5 = 180 (y pos)
    protoVarint(7, 1),                // F7 = 1
    protoVarint(8, 84),               // F8 = 84 (NOT 85 - native analysis shows 0x54 = 84)
    protoBytes(9, Buffer.alloc(0)),   // F9 = empty (native has empty F9)
    protoBytes(10, rootF3F10),        // F10 = node metadata
    protoVarint(12, timestamp),       // F12 = timestamp
  ];
  const rootF3 = protoBytes(3, Buffer.concat(rootF3Parts));

  // Combine F1 and F3 at root level
  const topLevel = Buffer.concat([mainContent, rootF3]);

  // Compress and generate DRX
  const zstd = await getZstdCompressor();
  const compressed = zstd.compress(topLevel);
  const body = Buffer.concat([Buffer.from([0x81]), Buffer.from(compressed)]);
  const bodyHex = body.toString('hex');

  // Generate UUIDs
  const { v4: uuidv4 } = require('uuid');
  const stillId = uuidv4();
  const clipVersionId = uuidv4();

  const now = new Date().toISOString().replace('Z', '');

  // Build pTrackVer section - always include it (native Resolve DRX always has pTrackVer)
  // Use preserved one if available, otherwise generate a default one
  let pTrackVerSection;
  if (pTrackVerXml) {
    pTrackVerSection = `
 ${pTrackVerXml}`;
  } else {
    // Generate default pTrackVer body
    const trackVersionId = require('uuid').v4();
    const trackBodyHex = await generatePTrackVerBody(width, height);
    pTrackVerSection = `
 <pTrackVer>
  <ListMgt::LmVersion DbId="${trackVersionId}">
   <FieldsBlob/>
   <Name/>
   <HasCorrection>false</HasCorrection>
   <VerType>1</VerType>
   <ImplVersion>1</ImplVersion>
   <IncludedInRecording>true</IncludedInRecording>
   <FlatPassEnabled>false</FlatPassEnabled>
   <RGBAOutputEnabled>false</RGBAOutputEnabled>
   <Body>${trackBodyHex}</Body>
   <UseVersionClipProcParams>true</UseVersionClipProcParams>
  </ListMgt::LmVersion>
 </pTrackVer>`;
  }

  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<!--DbAppVer="19.1.3.0007" DbPrjVer="14"-->
<Gallery::GyStill DbId="${stillId}">
 <FieldsBlob/>
 <SrcHint>${sourceTimeline}</SrcHint>
 <SrcType>1</SrcType>
 <GalleryPath/>
 <Label>${label}</Label>
 <RecTC>${recordTC}</RecTC>
 <SrcTC>${sourceTC}</SrcTC>
 <DpxDescriptor>50</DpxDescriptor>
 <Width>${width}</Width>
 <Height>${height}</Height>
 <BitDepth>10</BitDepth>
 <PAR>1</PAR>
 <Endianship>1</Endianship>
 <CreateTime>${now}</CreateTime>
 <pClipFullVer>
  <ListMgt::LmVersion DbId="${clipVersionId}">
   <FieldsBlob/>
   <Name/>
   <HasCorrection>true</HasCorrection>
   <VerType>0</VerType>
   <ImplVersion>1</ImplVersion>
   <IncludedInRecording>true</IncludedInRecording>
   <FlatPassEnabled>false</FlatPassEnabled>
   <RGBAOutputEnabled>false</RGBAOutputEnabled>
   <Body>${bodyHex}</Body>
   <UseVersionClipProcParams>true</UseVersionClipProcParams>
  </ListMgt::LmVersion>
 </pClipFullVer>${pTrackVerSection}
 <PrimaryCCMode>0</PrimaryCCMode>
</Gallery::GyStill>
`;

  return xml;
}

/**
 * Generate a DRX Body (compressed format)
 *
 * @param {Object} gradeParams - Color grading parameters
 * @param {Object} options - Generation options
 * @returns {Promise<Buffer>} - Complete DRX body ([0x81] + ZSTD compressed protobuf)
 */
async function generateDRXBody(gradeParams, options = {}) {
  // Generate protobuf
  const protobufData = generateProtobuf(gradeParams, options);

  // Get ZSTD compressor
  const zstd = await getZstdCompressor();

  // Compress with ZSTD (returns Uint8Array)
  const compressed = zstd.compress(protobufData);

  // Prepend type byte
  return Buffer.concat([Buffer.from([0x81]), Buffer.from(compressed)]);
}

/**
 * Generate complete DRX XML file
 *
 * @param {Object} gradeParams - Color grading parameters
 * @param {Object} metadata - DRX metadata (label, source, etc.)
 * @returns {Promise<string>} - Complete DRX XML content
 */
async function generateDRX(gradeParams, metadata = {}) {
  const {
    label = 'AI Generated Grade',
    width = 1920,
    height = 1080,
    sourceTimeline = 'Timeline 1',
    sourceTC = '00:00:00:00',
    recordTC = '01:00:00:00',
  } = metadata;

  // Generate the body (pass label for single-node mode)
  const body = await generateDRXBody(gradeParams, { width, height, label });
  const bodyHex = body.toString('hex');

  // Generate UUIDs
  const stillId = uuidv4();
  const versionId = uuidv4();
  const thumbnailId = uuidv4();

  // Current timestamp
  const now = new Date().toISOString().replace('Z', '');

  // Build DRX XML
  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<!--DbAppVer="19.1.3.0007" DbPrjVer="14"-->
<Gallery::GyStill DbId="${stillId}">
 <FieldsBlob/>
 <SrcHint>${sourceTimeline}</SrcHint>
 <SrcType>1</SrcType>
 <GalleryPath/>
 <Label>${label}</Label>
 <RecTC>${recordTC}</RecTC>
 <SrcTC>${sourceTC}</SrcTC>
 <DpxDescriptor>50</DpxDescriptor>
 <Width>${width}</Width>
 <Height>${height}</Height>
 <BitDepth>10</BitDepth>
 <PAR>1</PAR>
 <Endianship>1</Endianship>
 <CreateTime>${now}</CreateTime>
 <pClipFullVer>
  <ListMgt::LmVersion DbId="${versionId}">
   <FieldsBlob/>
   <Name/>
   <HasCorrection>true</HasCorrection>
   <VerType>0</VerType>
   <ImplVersion>1</ImplVersion>
   <IncludedInRecording>true</IncludedInRecording>
   <FlatPassEnabled>false</FlatPassEnabled>
   <RGBAOutputEnabled>false</RGBAOutputEnabled>
   <Body>${bodyHex}</Body>
   <UseVersionClipProcParams>true</UseVersionClipProcParams>
  </ListMgt::LmVersion>
 </pClipFullVer>
 <PrimaryCCMode>0</PrimaryCCMode>
</Gallery::GyStill>
`;

  return xml;
}

/**
 * Parse cinematographer language into grade parameters
 * Supports both simple mode (temperature, exposure) and per-channel mode (liftR, gainB)
 *
 * @param {Object} adjustments - High-level adjustments from AI
 * @returns {Object} - Grade parameters for DRX generation
 */

/**
 * Hard-clamp all grade parameters to valid DRX ranges.
 * Uses parameter-ranges.js as the single source of truth.
 * Called at the end of parseAdjustments for both SIMPLE and DIRECT modes
 * to prevent out-of-range values from reaching the encoder.
 *
 * @param {Object} params - Mutable params object (clamped in-place)
 */
function clampAllParams(params) {
  // Helper for params without a parameter-ranges entry — uses inline min/max
  const sc = (val, min, max) => Math.max(min, Math.min(max, val));

  // ── Color Wheels ──────────────────────────────────────────────────────────
  for (const ch of ['r', 'g', 'b', 'master']) {
    if (params.lift[ch] !== undefined)  params.lift[ch]  = drxParams.clamp('lift', ch, params.lift[ch]);
    if (params.gamma[ch] !== undefined) params.gamma[ch] = drxParams.clamp('gamma', ch, params.gamma[ch]);
    if (params.gain[ch] !== undefined)  params.gain[ch]  = drxParams.clamp('gain', ch, params.gain[ch]);
  }
  for (const ch of ['r', 'g', 'b']) {
    if (params.offset[ch] !== undefined) params.offset[ch] = drxParams.clamp('offset', ch, params.offset[ch]);
  }

  // ── Primary Adjustments ───────────────────────────────────────────────────
  params.saturation    = drxParams.clamp('saturation', 'master', params.saturation);
  params.temperature   = drxParams.clamp('temperature', 'master', params.temperature);
  params.tint          = drxParams.clamp('tint', 'master', params.tint);
  params.contrast      = drxParams.clamp('contrast', 'master', params.contrast);
  params.pivot         = drxParams.clamp('pivotFine', 'master', params.pivot);
  params.midtoneDetail = drxParams.clamp('midtoneDetail', 'master', params.midtoneDetail);

  // ── Color Boost: 0-100 ────────────────────────────────────────────────────
  if (params.colorBoost !== undefined) {
    params.colorBoost = drxParams.clamp('colorBoost', 'master', params.colorBoost);
  }

  // ── Hue Rotate: 0-100 (UI), default 50 ───────────────────────────────────
  if (params.hueRotate !== undefined) {
    params.hueRotate = sc(params.hueRotate, 0, 100);
  }

  // ── Highlights/Shadows sliders: -100 to +100 ─────────────────────────────
  if (params.highlights !== undefined) params.highlights = sc(params.highlights, -100, 100);
  if (params.shadows !== undefined)    params.shadows    = sc(params.shadows, -100, 100);

  // ── Soft Clips: 0-1 ──────────────────────────────────────────────────────
  if (params.softClipHigh !== undefined) params.softClipHigh = drxParams.clamp('softClipHigh', 'master', params.softClipHigh);
  if (params.softClipLow !== undefined)  params.softClipLow  = drxParams.clamp('softClipLow', 'master', params.softClipLow);
  if (params.softClipHighSoft !== undefined) params.softClipHighSoft = sc(params.softClipHighSoft, 0, 100);
  if (params.softClipLowSoft !== undefined)  params.softClipLowSoft  = sc(params.softClipLowSoft, 0, 100);

  // ── Contrast Range: 0-1 ──────────────────────────────────────────────────
  if (params.contrastHighRange !== undefined) params.contrastHighRange = drxParams.clamp('highRange', 'master', params.contrastHighRange);
  if (params.contrastLowRange !== undefined)  params.contrastLowRange  = drxParams.clamp('lowRange', 'master', params.contrastLowRange);

  // ── Log Wheels: -1 to +1 per channel ─────────────────────────────────────
  if (params.logShadow) {
    for (const ch of ['r', 'g', 'b']) {
      if (params.logShadow[ch] !== undefined) params.logShadow[ch] = drxParams.clamp('logShadow', ch, params.logShadow[ch]);
    }
  }
  if (params.logMid) {
    for (const ch of ['r', 'g', 'b']) {
      if (params.logMid[ch] !== undefined) params.logMid[ch] = drxParams.clamp('logMidtone', ch, params.logMid[ch]);
    }
  }
  if (params.logHigh) {
    for (const ch of ['r', 'g', 'b']) {
      if (params.logHigh[ch] !== undefined) params.logHigh[ch] = drxParams.clamp('logHighlight', ch, params.logHigh[ch]);
    }
  }

  // ── HDR Black Offset: -1 to +1 ───────────────────────────────────────────
  if (params.blackOffset !== undefined) params.blackOffset = drxParams.clamp('hdrBlackOffset', 'master', params.blackOffset);

  // ── RGB Mixer: each channel -2 to +2 (identity diagonal=1.0) ─────────────
  if (params.rgbMixer) {
    for (const key of ['rr', 'gr', 'br', 'rg', 'gg', 'bg', 'rb', 'gb', 'bb']) {
      if (params.rgbMixer[key] !== undefined) params.rgbMixer[key] = sc(params.rgbMixer[key], -2, 2);
    }
  }
}

function parseAdjustments(adjustments) {
  // Deep copy to avoid mutating NEUTRAL_GRADE
  const params = {
    lift: { ...NEUTRAL_GRADE.lift },
    gamma: { ...NEUTRAL_GRADE.gamma },
    gain: { ...NEUTRAL_GRADE.gain },
    offset: { ...NEUTRAL_GRADE.offset },
    saturation: NEUTRAL_GRADE.saturation,
    contrast: NEUTRAL_GRADE.contrast,
    pivot: NEUTRAL_GRADE.pivot,
    temperature: NEUTRAL_GRADE.temperature,
    tint: NEUTRAL_GRADE.tint,
    midtoneDetail: NEUTRAL_GRADE.midtoneDetail,
    softClipHigh: NEUTRAL_GRADE.softClipHigh,
    softClipLow: NEUTRAL_GRADE.softClipLow,
    // Log wheels (offset-style grading)
    logShadow: { r: 0, g: 0, b: 0 },
    logMid: { r: 0, g: 0, b: 0 },
    logHigh: { r: 0, g: 0, b: 0 },
    // Additional controls
    colorBoost: 0,
    contrastHighRange: 0.55,   // Resolve default ↑ Rng
    contrastLowRange: 0.333,  // Resolve default ↓ Rng
    // HDR Global controls
    blackOffset: 0,
  };

  // ═══════════════════════════════════════════════════════════════════════════
  // DIRECT MODE — absolute Resolve UI values (calibration-informed)
  // When mode='direct', values are Resolve-scale: saturation 0-100 (50=unity),
  // contrast 0-2 (1=unity), lift/gamma/offset -0.5 to +0.5, gain 0.5-2.0, etc.
  // ═══════════════════════════════════════════════════════════════════════════

  if (adjustments.mode === 'direct') {
    // Lift (shadows) — R/G/B/Master: -0.5 to +0.5, unity=0
    if (adjustments.lift) {
      if (adjustments.lift.r !== undefined) params.lift.r = adjustments.lift.r;
      if (adjustments.lift.g !== undefined) params.lift.g = adjustments.lift.g;
      if (adjustments.lift.b !== undefined) params.lift.b = adjustments.lift.b;
      if (adjustments.lift.master !== undefined) params.lift.master = adjustments.lift.master;
    }
    // Gamma (midtones) — R/G/B/Master: -0.5 to +0.5, unity=0
    if (adjustments.gamma) {
      if (adjustments.gamma.r !== undefined) params.gamma.r = adjustments.gamma.r;
      if (adjustments.gamma.g !== undefined) params.gamma.g = adjustments.gamma.g;
      if (adjustments.gamma.b !== undefined) params.gamma.b = adjustments.gamma.b;
      if (adjustments.gamma.master !== undefined) params.gamma.master = adjustments.gamma.master;
    }
    // Gain (highlights) — R/G/B/Master: 0.5 to 2.0, unity=1.0
    if (adjustments.gain) {
      if (adjustments.gain.r !== undefined) params.gain.r = adjustments.gain.r;
      if (adjustments.gain.g !== undefined) params.gain.g = adjustments.gain.g;
      if (adjustments.gain.b !== undefined) params.gain.b = adjustments.gain.b;
      if (adjustments.gain.master !== undefined) params.gain.master = adjustments.gain.master;
    }
    // Offset — R/G/B: -0.2 to +0.2, unity=0
    if (adjustments.offset) {
      if (adjustments.offset.r !== undefined) params.offset.r = adjustments.offset.r;
      if (adjustments.offset.g !== undefined) params.offset.g = adjustments.offset.g;
      if (adjustments.offset.b !== undefined) params.offset.b = adjustments.offset.b;
    }
    // Saturation — 0-100, unity=50
    if (adjustments.saturation !== undefined) params.saturation = adjustments.saturation;
    // Contrast — 0-2, unity=1.0 (usable range roughly 0.5-1.1 before clipping)
    if (adjustments.contrast !== undefined) params.contrast = adjustments.contrast;
    // Pivot — 0-1, default=0.435
    if (adjustments.pivot !== undefined) params.pivot = adjustments.pivot;
    // Temperature — -4000 to +4000, unity=0
    if (adjustments.temperature !== undefined) params.temperature = adjustments.temperature;
    // Tint — -100 to +100, unity=0
    if (adjustments.tint !== undefined) params.tint = adjustments.tint;
    // Midtone Detail — -100 to +100, unity=0
    if (adjustments.midtoneDetail !== undefined) params.midtoneDetail = adjustments.midtoneDetail;
    // Log wheels
    if (adjustments.logShadow) Object.assign(params.logShadow, adjustments.logShadow);
    if (adjustments.logMid) Object.assign(params.logMid, adjustments.logMid);
    if (adjustments.logHigh) Object.assign(params.logHigh, adjustments.logHigh);
    // RGB Mixer
    if (adjustments.rgbMixer) params.rgbMixer = adjustments.rgbMixer;
    // Color Boost — 0-100, unity=0
    if (adjustments.colorBoost !== undefined) params.colorBoost = adjustments.colorBoost;
    // Hue Rotate — 0-100, unity=50
    if (adjustments.hueRotate !== undefined) params.hueRotate = adjustments.hueRotate;
    // Soft Clips — 0-1 (DRX space)
    if (adjustments.softClipHigh !== undefined) params.softClipHigh = adjustments.softClipHigh;
    if (adjustments.softClipLow !== undefined) params.softClipLow = adjustments.softClipLow;
    // Soft Clip Softness — 0-100 UI (÷50 happens in buildPrimaryCorrectorParams)
    if (adjustments.softClipHighSoft !== undefined) params.softClipHighSoft = adjustments.softClipHighSoft;
    if (adjustments.softClipLowSoft !== undefined) params.softClipLowSoft = adjustments.softClipLowSoft;
    // Contrast Range — 0-1
    if (adjustments.contrastHighRange !== undefined) params.contrastHighRange = adjustments.contrastHighRange;
    if (adjustments.contrastLowRange !== undefined) params.contrastLowRange = adjustments.contrastLowRange;
    // HDR Black Offset — -1 to +1
    if (adjustments.blackOffset !== undefined) params.blackOffset = adjustments.blackOffset;
    // Highlights/Shadows sliders — direct values
    if (adjustments.highlights !== undefined) params.highlights = adjustments.highlights;
    if (adjustments.shadows !== undefined) params.shadows = adjustments.shadows;
    // Custom Curves
    if (adjustments.customCurves) params.customCurves = adjustments.customCurves;
    // HSL Curves
    if (adjustments.hslCurves) params.hslCurves = adjustments.hslCurves;

    // Hard clamp all values to valid DRX ranges (same as SIMPLE mode)
    clampAllParams(params);

    return params;
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // SIMPLE MODE (backwards compatible — relative adjustments -1 to +1)
  // ═══════════════════════════════════════════════════════════════════════════

  // Apply temperature shift (warm/cool)
  // Sets the actual Resolve Temp parameter (-4000 to +4000, unity=0)
  // Also applies subtle gain/lift tinting for per-channel looks (unless per-channel specified)
  if (adjustments.temperature) {
    const t = adjustments.temperature; // -1 (cool) to +1 (warm)
    // Map to Resolve's Temp parameter range: -4000 to +4000
    params.temperature = t * 4000;
    // Also apply subtle gain/lift tinting unless per-channel overrides are present
    if (!hasPerChannelGain(adjustments)) {
      params.gain.r += t * 0.1;
      params.gain.b -= t * 0.1;
      params.lift.r += t * 0.05;
      params.lift.b -= t * 0.05;
    }
  }

  // Apply tint shift (green/magenta)
  // Sets the actual Resolve Tint parameter (-100 to +100, unity=0)
  if (adjustments.tint) {
    const t = adjustments.tint; // -1 (green) to +1 (magenta)
    // Map to Resolve's Tint parameter range: -100 to +100
    params.tint = t * 100;
    params.gain.g -= t * 0.1;
    params.lift.g -= t * 0.05;
  }

  // Apply contrast
  // Resolve Primaries Contrast: floating point, 0.0-2.0, unity=1.0
  if (adjustments.contrast) {
    params.contrast = 1.0 + (adjustments.contrast * 1.0);
  }

  // Apply saturation
  // Resolve Primaries Saturation: 0-100, unity=50
  if (adjustments.saturation) {
    params.saturation = 50 + (adjustments.saturation * 50);
  }

  // Apply exposure (overall brightness) - only if per-channel gain master not specified
  if (adjustments.exposure && adjustments.gainMaster === undefined) {
    const e = adjustments.exposure;
    params.gain.master += e;
  }

  // Apply shadow lift - only if per-channel lift not specified
  if (adjustments.shadowLift && !hasPerChannelLift(adjustments)) {
    const s = adjustments.shadowLift;
    params.lift.r += s * 0.1;
    params.lift.g += s * 0.1;
    params.lift.b += s * 0.1;
  }

  // Apply highlight compression - only if per-channel gain not specified
  if (adjustments.highlightCompression && !hasPerChannelGain(adjustments)) {
    const h = adjustments.highlightCompression;
    params.gain.r -= h * 0.1;
    params.gain.g -= h * 0.1;
    params.gain.b -= h * 0.1;
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // PER-CHANNEL PRIMARY WHEELS (for looks like teal/orange)
  // ═══════════════════════════════════════════════════════════════════════════

  // Lift (shadows) per-channel
  if (adjustments.liftR !== undefined) params.lift.r += adjustments.liftR;
  if (adjustments.liftG !== undefined) params.lift.g += adjustments.liftG;
  if (adjustments.liftB !== undefined) params.lift.b += adjustments.liftB;
  if (adjustments.liftMaster !== undefined) params.lift.master += adjustments.liftMaster;

  // Gamma (midtones) per-channel
  if (adjustments.gammaR !== undefined) params.gamma.r += adjustments.gammaR;
  if (adjustments.gammaG !== undefined) params.gamma.g += adjustments.gammaG;
  if (adjustments.gammaB !== undefined) params.gamma.b += adjustments.gammaB;
  if (adjustments.gammaMaster !== undefined) params.gamma.master += adjustments.gammaMaster;

  // Gain (highlights) per-channel
  if (adjustments.gainR !== undefined) params.gain.r += adjustments.gainR;
  if (adjustments.gainG !== undefined) params.gain.g += adjustments.gainG;
  if (adjustments.gainB !== undefined) params.gain.b += adjustments.gainB;
  if (adjustments.gainMaster !== undefined) params.gain.master += adjustments.gainMaster;

  // Offset (exposure compensation) per-channel
  // Note: Tool resolver outputs offsetR/offsetG/offsetB
  if (adjustments.offsetR !== undefined) params.offset.r += adjustments.offsetR;
  if (adjustments.offsetG !== undefined) params.offset.g += adjustments.offsetG;
  if (adjustments.offsetB !== undefined) params.offset.b += adjustments.offsetB;

  // ═══════════════════════════════════════════════════════════════════════════
  // LOG WHEELS (offset-style grading)
  // ═══════════════════════════════════════════════════════════════════════════

  // Log Shadow
  if (adjustments.logShadowR !== undefined) params.logShadow.r = adjustments.logShadowR;
  if (adjustments.logShadowG !== undefined) params.logShadow.g = adjustments.logShadowG;
  if (adjustments.logShadowB !== undefined) params.logShadow.b = adjustments.logShadowB;

  // Log Mid
  if (adjustments.logMidR !== undefined) params.logMid.r = adjustments.logMidR;
  if (adjustments.logMidG !== undefined) params.logMid.g = adjustments.logMidG;
  if (adjustments.logMidB !== undefined) params.logMid.b = adjustments.logMidB;

  // Log High
  if (adjustments.logHighR !== undefined) params.logHigh.r = adjustments.logHighR;
  if (adjustments.logHighG !== undefined) params.logHigh.g = adjustments.logHighG;
  if (adjustments.logHighB !== undefined) params.logHigh.b = adjustments.logHighB;

  // ═══════════════════════════════════════════════════════════════════════════
  // ADDITIONAL CONTROLS
  // ═══════════════════════════════════════════════════════════════════════════

  // Color Boost (intelligent saturation / vibrance)
  // DRX AutoResearch 2026-03-17: DRX stores raw value (e.g. 50.0 for UI +50).
  // User-space in autoresearch experiments: -1 to +1, needs scaling to -100 to +100.
  if (adjustments.colorBoost !== undefined) {
    params.colorBoost = adjustments.colorBoost * 100;
  }

  // Contrast range controls
  if (adjustments.contrastHighRange !== undefined) {
    params.contrastHighRange = adjustments.contrastHighRange;
  }
  if (adjustments.contrastLowRange !== undefined) {
    params.contrastLowRange = adjustments.contrastLowRange;
  }

  // Pivot (contrast center point)
  if (adjustments.pivot !== undefined) {
    params.pivot = adjustments.pivot;
  }

  // Midtone detail — scale from user-space (-1 to +1) to Resolve range (-100 to +100)
  // Matches temperature/tint pattern: all scaling in parseAdjustments, not buildPrimaryCorrectorParams
  if (adjustments.midtoneDetail !== undefined) {
    params.midtoneDetail = adjustments.midtoneDetail * 100;
  }

  // Black Offset (HDR global control)
  // Resolve range: -1.0 to +1.0, default 0. User-space same as Resolve-space.
  if (adjustments.blackOffset !== undefined) {
    params.blackOffset = adjustments.blackOffset;
  }

  // RGB Mixer (3x3 channel mixing matrix)
  // User provides { rr, gr, br, rg, gg, bg, rb, gb, bb } in DRX-space (identity = diagonal 1.0)
  if (adjustments.rgbMixer) {
    params.rgbMixer = adjustments.rgbMixer;
  }

  // Highlights/Shadows sliders (direct values, e.g., 50)
  if (adjustments.highlights !== undefined) {
    params.highlights = adjustments.highlights;
  }
  if (adjustments.shadows !== undefined) {
    params.shadows = adjustments.shadows;
  }

  // Custom Curves (YRGB) — pass through control points
  // Format: { y: [{x, y}], r: [{x, y}], g: [{x, y}], b: [{x, y}] }
  if (adjustments.customCurves) {
    params.customCurves = adjustments.customCurves;
  }

  // HSL Curves — pass through control points
  // Format: { hueVsHue: [{x, y}], hueVsSat: [{x, y}], ... }
  if (adjustments.hslCurves) {
    params.hslCurves = adjustments.hslCurves;
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // HARD CLAMP — prevent out-of-range values from reaching the DRX encoder.
  // Uses parameter-ranges.js as the single source of truth for valid ranges.
  // This catches overflow from additive stacking (temperature + exposure on gain,
  // tint side-effects on lift, etc.) and out-of-range user inputs.
  // ═══════════════════════════════════════════════════════════════════════════
  clampAllParams(params);

  return params;
}

/**
 * Check if per-channel lift parameters are specified
 */
function hasPerChannelLift(adjustments) {
  return adjustments.liftR !== undefined ||
         adjustments.liftG !== undefined ||
         adjustments.liftB !== undefined ||
         adjustments.liftMaster !== undefined;
}

// ═══════════════════════════════════════════════════════════════════════════
// STUB ENCODING FUNCTIONS (Awaiting DRX Training)
// These functions are ready to encode when parameter IDs are discovered
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Check if a parameter ID is available (not null/undefined)
 * @param {*} paramId - Parameter ID to check
 * @param {string} name - Human-readable name for logging
 * @returns {boolean}
 */
function isParamIdAvailable(paramId, name) {
  if (paramId === null || paramId === undefined) {
    console.warn(`[DRX] Parameter ID not yet captured: ${name} (needs DRX training sample)`);
    return false;
  }
  return true;
}

/**
 * Encode a single HDR zone's nested structure
 * HDR zones use nested protobuf with zone name + exposure/saturation/hue fields
 *
 * @param {string} zoneName - Zone name ("Dark", "Shadow", "Light", "Highlight", "Global")
 * @param {Object} zoneParams - { exposure, saturation, colorBalanceX, colorBalanceY }
 *   (also accepts legacy hueAngle/hueSat as aliases for colorBalanceY/colorBalanceX)
 * @returns {Buffer} - Encoded zone data
 */
function encodeHDRZoneData(zoneName, zoneParams) {
  const parts = [];
  const { HDR_ZONE } = drxParams;

  // Zone name string (wire type 0x0a = length-delimited)
  const nameBytes = Buffer.from(zoneName, 'utf8');
  parts.push(Buffer.from([HDR_ZONE.WIRE.ZONE_NAME, nameBytes.length]));
  parts.push(nameBytes);

  // Exposure (wire type 0x15 = fixed32)
  if (zoneParams.exposure !== undefined && zoneParams.exposure !== 0) {
    const expBuf = Buffer.alloc(5);
    expBuf[0] = HDR_ZONE.WIRE.EXPOSURE;
    expBuf.writeFloatLE(zoneParams.exposure, 1);
    parts.push(expBuf);
  }

  // Color Balance Y (wire type 0x1d = F3 fixed32)
  // Accept both new name (colorBalanceY) and legacy (hueAngle)
  const cbY = zoneParams.colorBalanceY ?? zoneParams.hueAngle;
  if (cbY !== undefined && cbY !== 0) {
    const cbYBuf = Buffer.alloc(5);
    cbYBuf[0] = HDR_ZONE.WIRE.COLOR_BALANCE_Y;
    cbYBuf.writeFloatLE(cbY, 1);
    parts.push(cbYBuf);
  }

  // Color Balance X (wire type 0x25 = F4 fixed32)
  // Accept both new name (colorBalanceX) and legacy (hueSat)
  const cbX = zoneParams.colorBalanceX ?? zoneParams.hueSat;
  if (cbX !== undefined && cbX !== 0) {
    const cbXBuf = Buffer.alloc(5);
    cbXBuf[0] = HDR_ZONE.WIRE.COLOR_BALANCE_X;
    cbXBuf.writeFloatLE(cbX, 1);
    parts.push(cbXBuf);
  }

  // Falloff (wire type 0x2d = F5 fixed32, default 0.2)
  // Confirmed 2026-03-18: Dark zone falloff=0.50 → field 5 = 0.5, default field 4 = 0.2
  if (zoneParams.falloff !== undefined) {
    const falloffBuf = Buffer.alloc(5);
    falloffBuf[0] = 0x2d; // Field 5, wire type 5 (fixed32)
    falloffBuf.writeFloatLE(zoneParams.falloff, 1);
    parts.push(falloffBuf);
  }

  // Saturation (wire type 0x3d = fixed32)
  // FIXED 2026-01-17: Always include saturation even at default (1.0) - Resolve expects it
  const satValue = zoneParams.saturation !== undefined ? zoneParams.saturation : 1.0;
  const satBuf = Buffer.alloc(5);
  satBuf[0] = HDR_ZONE.WIRE.SATURATION;
  satBuf.writeFloatLE(satValue, 1);
  parts.push(satBuf);

  return Buffer.concat(parts);
}

/**
 * Build HDR Wheel parameters using nested protobuf structure
 * TRAINED 2026-01-14 from 13 HDR DRX samples
 *
 * HDR Zones use a fundamentally different encoding than standard parameters:
 * - Zone adjustments container (0x86000305): exposure, color balance X/Y, saturation
 * - Zone definitions container (0x86000306): range boundaries, falloff
 * - Zone differentiation via embedded zone name strings
 *
 * @param {Object} colorParams - Color parameters containing hdrDark, hdrShadow, etc.
 * @returns {Array} - Array of parameter entries with nested zone data
 */
function buildHDRWheelParams(colorParams) {
  const paramEntries = [];
  const { HDR_ZONE } = drxParams;

  // Map semantic names to DRX zone names
  const zoneMapping = {
    hdrBlack: HDR_ZONE.ZONE_NAMES.BLACK,
    hdrDark: HDR_ZONE.ZONE_NAMES.DARK,
    hdrShadow: HDR_ZONE.ZONE_NAMES.SHADOW,
    hdrLight: HDR_ZONE.ZONE_NAMES.LIGHT,
    hdrHighlight: HDR_ZONE.ZONE_NAMES.HIGHLIGHT,
    hdrSpecular: HDR_ZONE.ZONE_NAMES.SPECULAR,
    hdrGlobal: HDR_ZONE.ZONE_NAMES.GLOBAL,
  };

  // Check each zone and encode if it has non-default values
  for (const [semanticKey, zoneName] of Object.entries(zoneMapping)) {
    const zoneParams = colorParams[semanticKey];
    if (!zoneParams) continue;

    // Check if zone has any non-default values
    const hasExposure = zoneParams.exposure !== undefined && zoneParams.exposure !== 0;
    const hasSaturation = zoneParams.saturation !== undefined && zoneParams.saturation !== 1.0;
    const hasCBX = (zoneParams.colorBalanceX ?? zoneParams.hueSat) !== undefined && (zoneParams.colorBalanceX ?? zoneParams.hueSat ?? 0) !== 0;
    const hasCBY = (zoneParams.colorBalanceY ?? zoneParams.hueAngle) !== undefined && (zoneParams.colorBalanceY ?? zoneParams.hueAngle ?? 0) !== 0;

    if (hasExposure || hasSaturation || hasCBX || hasCBY) {
      // Encode this zone's nested structure
      const zoneData = encodeHDRZoneData(zoneName, zoneParams);

      // Wrap in parameter entry with ZONE_DATA ID
      // The createParameterEntry function needs to handle this specially for nested data
      paramEntries.push({
        paramId: HDR_ZONE.ZONE_DATA,
        nestedData: zoneData,
        zoneName: zoneName,
        isNested: true,
      });

      debugLog(`[DRX] HDR Zone ${zoneName}: exp=${zoneParams.exposure || 0}, sat=${zoneParams.saturation || 1}, cbX=${zoneParams.colorBalanceX || 0}, cbY=${zoneParams.colorBalanceY || 0}`);
    }
  }

  if (paramEntries.length > 0) {
    debugLog('[DRX] HDR Wheel zones built:', paramEntries.length);
  }
  return paramEntries;
}

/**
 * Build HSL Qualifier parameters (STUB - awaiting training)
 * Will encode once HSL_QUALIFIER parameter IDs are captured from DRX samples
 *
 * @param {Object} qualifierParams - Qualifier settings (hueCenter, hueWidth, satLow, etc.)
 * @returns {Array} - Array of parameter entries (empty until trained)
 */
/**
 * Build HSL Qualifier parameters (Corrector Type 2).
 *
 * All values should be in UI units (0-100 for percentages, 0-360 for hue).
 * Internally converts to DRX encoding (÷100).
 *
 * TRAINED 2026-03-22: All 12 qualifier IDs + mode flag + softness confirmed.
 *
 * @param {Object} qualifierParams - Qualifier settings in UI values
 * @param {number} [qualifierParams.hueCenter] - Hue center (0-100, maps to 0-360°)
 * @param {number} [qualifierParams.hueWidth] - Hue width
 * @param {number} [qualifierParams.hueSoft] - Hue edge softness
 * @param {number} [qualifierParams.hueSymmetry=50] - Hue symmetry
 * @param {number} [qualifierParams.satLow] - Saturation low threshold
 * @param {number} [qualifierParams.satHigh] - Saturation high threshold
 * @param {number} [qualifierParams.satLowSoft] - Sat low softness
 * @param {number} [qualifierParams.satHighSoft] - Sat high softness
 * @param {number} [qualifierParams.lumLow] - Luminance low threshold
 * @param {number} [qualifierParams.lumHigh] - Luminance high threshold
 * @param {number} [qualifierParams.lumLowSoft] - Lum low softness
 * @param {number} [qualifierParams.lumHighSoft] - Lum high softness
 * @param {number} [qualifierParams.blur] - Blur radius (on primary corrector)
 * @returns {Array} - Parameter entries for corrector type 2
 */
function buildQualifierParams(qualifierParams) {
  const paramEntries = [];
  const { HSL_QUALIFIER } = drxParams;

  if (!qualifierParams) return paramEntries;

  // All qualifier params encode as UI ÷ 100
  const q = qualifierParams;
  const add = (id, val) => {
    if (val !== undefined) paramEntries.push(createParameterEntry(id, val / 100));
  };

  // Hue selection
  add(HSL_QUALIFIER.HUE_CENTER, q.hueCenter);
  add(HSL_QUALIFIER.HUE_WIDTH, q.hueWidth);
  add(HSL_QUALIFIER.HUE_SYM, q.hueSymmetry !== undefined ? q.hueSymmetry : (q.hueCenter !== undefined ? 50 : undefined));
  add(HSL_QUALIFIER.HUE_SOFT, q.hueSoft);

  // Saturation selection
  add(HSL_QUALIFIER.SAT_HIGH, q.satHigh);
  add(HSL_QUALIFIER.SAT_LOW, q.satLow);
  add(HSL_QUALIFIER.SAT_HIGH_SOFT, q.satHighSoft);
  add(HSL_QUALIFIER.SAT_LOW_SOFT, q.satLowSoft);

  // Luminance selection
  add(HSL_QUALIFIER.LUM_HIGH, q.lumHigh);
  add(HSL_QUALIFIER.LUM_LOW, q.lumLow);
  add(HSL_QUALIFIER.LUM_HIGH_SOFT, q.lumHighSoft);
  add(HSL_QUALIFIER.LUM_LOW_SOFT, q.lumLowSoft);

  // Duplicate hue params (Resolve stores these)
  if (q.hueWidth !== undefined) add(HSL_QUALIFIER.HUE_WIDTH_DUP, q.hueWidth);
  if (q.hueSoft !== undefined) add(HSL_QUALIFIER.HUE_SOFT_DUP, q.hueSoft);

  // Duplicate hue params removed from above — already handled

  // Mode flags (wire-confirmed 2026-07-01): BOTH are varint envelopes {F2: n} in live
  // data — MODE_FLAG (0x0830006F) observed 4; QUALIFIER_MODE (0x88300001) carries the
  // qualifier mode (HSL=0, RGB=2, luma=4, 3D=6). The old float32 encoding decoded as
  // null/garbage and was wire-unfaithful.
  if (paramEntries.length > 0) {
    paramEntries.push(createVarintParameterEntry(HSL_QUALIFIER.MODE_FLAG, 4));
    paramEntries.push(createVarintParameterEntry(HSL_QUALIFIER.QUALIFIER_MODE, 0));
  }

  if (paramEntries.length > 0) {
    debugLog('[DRX] HSL Qualifier params built:', paramEntries.length);
  }
  return paramEntries;
}

/**
 * Build RGB Qualifier parameters (Corrector Type 2, Mode 2).
 *
 * Uses same corrector type as HSL but with QUALIFIER_MODE=2.
 * Params at 0x08300002-0x0830000D for per-channel R/G/B Low/High/Soft.
 * All values in UI units (0-100), internally converts ÷100.
 *
 * TRAINED 2026-03-16: IDs confirmed in calibration session.
 *
 * @param {Object} rgbParams - RGB qualifier settings
 * @param {number} [rgbParams.rLow] - Red low threshold
 * @param {number} [rgbParams.rHigh] - Red high threshold
 * @param {number} [rgbParams.rLowSoft] - Red low softness
 * @param {number} [rgbParams.rHighSoft] - Red high softness
 * @param {number} [rgbParams.gLow] - Green low threshold (etc.)
 * @param {number} [rgbParams.bLow] - Blue low threshold (etc.)
 * @returns {Array} - Parameter entries for corrector type 2 with mode=2
 */
function buildRGBQualifierParams(rgbParams) {
  const paramEntries = [];
  const { HSL_QUALIFIER } = drxParams;

  if (!rgbParams) return paramEntries;

  const q = rgbParams;
  const add = (id, val) => {
    if (val !== undefined) paramEntries.push(createParameterEntry(id, val / 100));
  };

  // Red channel
  add(HSL_QUALIFIER.RGB_R_LOW, q.rLow);
  add(HSL_QUALIFIER.RGB_R_HIGH, q.rHigh);
  add(HSL_QUALIFIER.RGB_R_LOW_SOFT, q.rLowSoft);
  add(HSL_QUALIFIER.RGB_R_HIGH_SOFT, q.rHighSoft);

  // Green channel
  add(HSL_QUALIFIER.RGB_G_LOW, q.gLow);
  add(HSL_QUALIFIER.RGB_G_HIGH, q.gHigh);
  add(HSL_QUALIFIER.RGB_G_LOW_SOFT, q.gLowSoft);
  add(HSL_QUALIFIER.RGB_G_HIGH_SOFT, q.gHighSoft);

  // Blue channel
  add(HSL_QUALIFIER.RGB_B_LOW, q.bLow);
  add(HSL_QUALIFIER.RGB_B_HIGH, q.bHigh);
  add(HSL_QUALIFIER.RGB_B_LOW_SOFT, q.bLowSoft);
  add(HSL_QUALIFIER.RGB_B_HIGH_SOFT, q.bHighSoft);

  // Mode = RGB (2) — varint envelope (wire-confirmed: qualifier-rgb fixture {F2:2})
  if (paramEntries.length > 0) {
    paramEntries.push(createVarintParameterEntry(HSL_QUALIFIER.QUALIFIER_MODE, 2));
  }

  if (paramEntries.length > 0) {
    debugLog('[DRX] RGB Qualifier params built:', paramEntries.length);
  }
  return paramEntries;
}

/**
 * Build Luma Qualifier parameters (Corrector Type 2, Mode 4).
 *
 * Uses same corrector type with QUALIFIER_MODE=4.
 * Reuses Lum Low/High/Soft params from HSL qualifier.
 * All values in UI units (0-100), internally converts ÷100.
 *
 * @param {Object} lumaParams - Luma qualifier settings
 * @param {number} [lumaParams.lumLow] - Luminance low threshold
 * @param {number} [lumaParams.lumHigh] - Luminance high threshold
 * @param {number} [lumaParams.lumLowSoft] - Lum low softness
 * @param {number} [lumaParams.lumHighSoft] - Lum high softness
 * @returns {Array} - Parameter entries for corrector type 2 with mode=4
 */
function buildLumaQualifierParams(lumaParams) {
  const paramEntries = [];
  const { HSL_QUALIFIER } = drxParams;

  if (!lumaParams) return paramEntries;

  const q = lumaParams;
  const add = (id, val) => {
    if (val !== undefined) paramEntries.push(createParameterEntry(id, val / 100));
  };

  add(HSL_QUALIFIER.LUM_HIGH, q.lumHigh);
  add(HSL_QUALIFIER.LUM_LOW, q.lumLow);
  add(HSL_QUALIFIER.LUM_HIGH_SOFT, q.lumHighSoft);
  add(HSL_QUALIFIER.LUM_LOW_SOFT, q.lumLowSoft);

  // Mode = Luma (4) — varint envelope (same wire form as the confirmed HSL/RGB modes)
  if (paramEntries.length > 0) {
    paramEntries.push(createVarintParameterEntry(HSL_QUALIFIER.QUALIFIER_MODE, 4));
  }

  if (paramEntries.length > 0) {
    debugLog('[DRX] Luma Qualifier params built:', paramEntries.length);
  }
  return paramEntries;
}

/**
 * Build Power Window parameters (STUB - awaiting training)
 * Will encode once POWER_WINDOWS parameter IDs are captured from DRX samples
 *
 * @param {Object} windowParams - Window settings (type, centerX, centerY, width, etc.)
 * @returns {Array} - Array of parameter entries (empty until trained)
 */
/**
 * Build Power Window parameters (Corrector Type 4 for circle, 65539 for linear, 65554 for gradient).
 *
 * TRAINED 2026-03-22: All window types confirmed with correct scaling.
 * - Circle: type 4, pan/tilt in pixels, softness via SoftRef (UI × 16)
 * - Linear: type 65539 (0x10003), Soft1-4 in 0x0870xxxx range (UI × 16)
 * - Gradient: type 65554 (0x10012), 0x08F0xxxx range, softness (UI × 100)
 *
 * @param {Object} windowParams - Window settings in UI values
 * @param {number} windowParams.type - 1=Circle, 2=Linear, 5=Gradient
 * @param {number} [windowParams.pan=50] - Horizontal position (UI 0-100, 50=center)
 * @param {number} [windowParams.tilt=50] - Vertical position (UI 0-100, 50=center)
 * @param {number} [windowParams.size=50] - Size (UI 0-100, 50=default)
 * @param {number} [windowParams.aspect=50] - Aspect ratio (UI 0-100, 50=1:1)
 * @param {number} [windowParams.rotate=0] - Rotation degrees
 * @param {number} [windowParams.soft1=0] - Softness 1
 * @param {number} [windowParams.soft2=0] - Softness 2 (linear only)
 * @param {number} [windowParams.soft3=0] - Softness 3 (linear only)
 * @param {number} [windowParams.soft4=0] - Softness 4 (linear only)
 * @returns {Array} - Parameter entries for window corrector
 */
function buildWindowParams(windowParams) {
  const groups = { transform: [], softMask: [], gradient: [], shape: [] };
  const paramEntries = groups.transform;
  const { POWER_WINDOWS } = drxParams;

  if (!windowParams || windowParams.type === 0) return groups;

  const w = windowParams;

  // SHAPE MODEL (wire-confirmed 2026-07-01 against the live fixtures): Resolve does NOT
  // discriminate window shape via 0x88500008 — that flag is a CONSTANT varint {F2:2} in
  // every shape's fixture (circle/linear/gradient/polygon/curve). Shape is expressed by
  // WHICH corrector blocks exist: circle = ct4 transform only; linear = ct4 + ct3
  // softness mask (0x0870xxxx, UI×16); gradient = ct65554 (0x08F0xxxx); polygon/curve =
  // ct4 + ct6 vertex ring (no write support — decode-only).
  // The ct4 type flag accompanies circle/linear windows. For vertex shapes (polygon/
  // curve) it spawns a SEPARATE empty circle window row (live-observed 2026-07-02), so
  // skip it — the ct6 shape block alone should define the window.
  if (w.type !== undefined && w.type !== 5 && !(w.type === 3 || w.type === 4)) {
    paramEntries.push(createVarintParameterEntry(POWER_WINDOWS.WINDOW_TYPE, 2));
  }

  // TRUE transform scales — live multi-point fit 2026-06-22 (§16a), applied to the
  // generator 2026-07-01 after the registry window ranges were widened to the real
  // DRX-internal spans (they previously clamped pan/tilt/softRef to ±1, which is why
  // the generator had kept placeholder conventions). The same scales are locked in
  // test/power-window-transform-calibration.test.mjs and mirrored by
  // extract-power-window.js, so UI-in → UI-out round-trips AND matches Resolve.
  //   rotate = −UI°/180 · aspect = (50−UI)/50 · size = 1+(UI−50)×0.08 ·
  //   pan/tilt = (UI−50)/50 × 4096 (frame-pixel space).

  const isGradient = w.type === 5;
  const isLinear = w.type === 2;
  const isVertexShape = (w.type === 3 || w.type === 4) && Array.isArray(w.vertices) && w.vertices.length >= 3;

  if (isVertexShape) {
    // Polygon (3) / Curve (4) windows carry their freeform shape in a ct6 block
    // (live-RE'd 2026-06-22, write path added 2026-07-02 — PENDING live rig verify):
    //   0x08D00002 varint {F2:2} · 0x08D00004 = 0 · three vertex RINGS at
    //   0x08D00006/07/08 (value envelope F9.F1[] of f32 {x,y} points, FRAME PIXELS from
    //   center) · 0x08D00009/0A = 0 · 0x08D0000B/0C = 1 · identity 3×3 at 0x88D00014
    //   (F10.F1–F9). Ring = bezier corner repetition: first corner ×2, others ×3,
    //   closed with the first corner ×2 (4-corner fixture → 13 points, all three rings
    //   identical for straight edges). 0x08D00010/11 (unknown floats) omitted in v1.
    const s = groups.shape;
    const ring = [];
    w.vertices.forEach((v, i) => {
      const reps = i === 0 ? 2 : 3;
      for (let r = 0; r < reps; r++) ring.push(createCurvePoint(v.x, v.y));
    });
    ring.push(createCurvePoint(w.vertices[0].x, w.vertices[0].y));
    ring.push(createCurvePoint(w.vertices[0].x, w.vertices[0].y));
    const ringEnvelope = protoBytes(9, Buffer.concat(ring)); // F9 { F1[] points }
    s.push(createVarintParameterEntry(0x08d00002, 2));
    s.push(createParameterEntry(0x08d00004, 0));
    for (const ringId of [0x08d00006, 0x08d00007, 0x08d00008]) {
      s.push(protoBytes(3, Buffer.concat([protoVarint(1, ringId), protoBytes(2, ringEnvelope)])));
    }
    s.push(createParameterEntry(0x08d00009, 0));
    s.push(createParameterEntry(0x08d0000a, 0));
    s.push(createParameterEntry(0x08d0000b, 1));
    s.push(createParameterEntry(0x08d0000c, 1));
    const IDENTITY = [1, 0, 0, 0, 1, 0, 0, 0, 1];
    const matrixMsg = Buffer.concat(IDENTITY.map((v, i) => protoFloat32(i + 1, v)));
    s.push(protoBytes(3, Buffer.concat([protoVarint(1, 0x88d00014), protoBytes(2, protoBytes(10, matrixMsg))])));
    debugLog('[DRX] Window vertex shape (ct6):', w.vertices.length, 'corners →', 13, 'ring points');
  }

  if (isGradient) {
    // Gradient windows live ENTIRELY in a ct65554 block (0x08F0xxxx). The old code wrote
    // these ids into the ct4 transform block, where live data never puts them.
    const GW = drxParams.GRADIENT_WINDOW;
    const g = groups.gradient;
    g.push(createVarintParameterEntry(GW.TYPE, 2));
    if (w.rotate !== undefined && w.rotate !== 0) {
      g.push(createParameterEntry(GW.ROTATION, -w.rotate / 180));
    }
    // Handle positions carry the gradient's placement in the same (UI−50)/50 × 4096
    // frame-pixel space as the ct4 pan/tilt (fixture: Pan 81 → 2539.52, Tilt 82 → 2621.44).
    if (w.pan !== undefined && w.pan !== 50) {
      g.push(createParameterEntry(GW.HANDLE_1_POS, ((w.pan - 50) / 50) * 4096));
    }
    if (w.tilt !== undefined && w.tilt !== 50) {
      g.push(createParameterEntry(GW.HANDLE_2_POS, ((w.tilt - 50) / 50) * 4096));
    }
    if (w.soft1 !== undefined && w.soft1 !== 0) {
      g.push(createParameterEntry(GW.SOFTNESS, w.soft1 * 100));
    }
    if (w.opacity !== undefined && w.opacity !== 100) {
      g.push(createParameterEntry(GW.OPACITY, w.opacity / 100));
    }
    debugLog('[DRX] Window params built:', g.length, '(gradient, ct65554)');
    return groups;
  }

  // Transform: rotation, stored = −UI°/180 (neutral 0)
  if (w.rotate !== undefined && w.rotate !== 0) {
    paramEntries.push(createParameterEntry(POWER_WINDOWS.ROTATE, -w.rotate / 180));
  }

  // Size: UI 50 = default = DRX 1.0; stored = 1 + (UI−50)×0.08
  if (w.size !== undefined && w.size !== 50) {
    paramEntries.push(createParameterEntry(POWER_WINDOWS.SIZE, 1 + (w.size - 50) * 0.08));
  }

  // Aspect: UI 50 = 1:1 = DRX 0.0; stored = (50−UI)/50
  if (w.aspect !== undefined && w.aspect !== 50) {
    paramEntries.push(createParameterEntry(POWER_WINDOWS.ASPECT, (50 - w.aspect) / 50));
  }

  // Pan/Tilt: stored = (UI−50)/50 × 4096 (frame-pixel offset from center)
  if (w.pan !== undefined && w.pan !== 50) {
    paramEntries.push(createParameterEntry(POWER_WINDOWS.PAN, ((w.pan - 50) / 50) * 4096));
  }
  if (w.tilt !== undefined && w.tilt !== 50) {
    paramEntries.push(createParameterEntry(POWER_WINDOWS.TILT, ((w.tilt - 50) / 50) * 4096));
  }

  // Opacity: /100 (live-confirmed: UI 66 → 0.66)
  if (w.opacity !== undefined && w.opacity !== 100) {
    paramEntries.push(createParameterEntry(POWER_WINDOWS.OPACITY, w.opacity / 100));
  }

  // Softness — UI × 16 (live-confirmed both circle SoftRef and linear Soft1–4).
  if (isLinear) {
    // Linear softness mask lives in a ct3 block (0x08700009–0C), NOT the ct4 transform
    // (linear-window-softness fixture: ct3, ÷16 exact). The old code wrote Soft1–4 into ct4.
    const m = groups.softMask;
    if (w.soft1 !== undefined && w.soft1 !== 0) m.push(createParameterEntry(POWER_WINDOWS.SOFT_1, w.soft1 * 16));
    if (w.soft2 !== undefined && w.soft2 !== 0) m.push(createParameterEntry(POWER_WINDOWS.SOFT_2, w.soft2 * 16));
    if (w.soft3 !== undefined && w.soft3 !== 0) m.push(createParameterEntry(POWER_WINDOWS.SOFT_3, w.soft3 * 16));
    if (w.soft4 !== undefined && w.soft4 !== 0) m.push(createParameterEntry(POWER_WINDOWS.SOFT_4, w.soft4 * 16));
  } else if (w.soft1 !== undefined && w.soft1 !== 0) {
    // Circle: softness rides SoftRef on the ct4 transform (live: Soft1 67 → 1072).
    paramEntries.push(createParameterEntry(POWER_WINDOWS.SOFT_REF, w.soft1 * 16));
  }

  if (paramEntries.length > 0 || groups.softMask.length > 0) {
    debugLog('[DRX] Window params built:', paramEntries.length, '+', groups.softMask.length, isLinear ? '(linear: ct4 + ct3 mask)' : '(circle: ct4)');
  }
  return groups;
}

/**
 * Check if any secondary correction tools are used (qualifier, window, HDR wheels)
 * Used to determine if we need to add those corrector blocks
 *
 * @param {Object} colorParams - Full color parameters object
 * @returns {Object} - { hasQualifier, hasWindow, hasHDRWheels }
 */
function hasSecondaryCorrections(colorParams) {
  const hasQualifier = colorParams.qualifier &&
    (colorParams.qualifier.hueCenter !== undefined ||
     colorParams.qualifier.satLow !== undefined ||
     colorParams.qualifier.lumLow !== undefined);

  const hasWindow = colorParams.window &&
    colorParams.window.type !== undefined &&
    colorParams.window.type !== 0;

  const hasHDRWheels = colorParams.hdrDark || colorParams.hdrShadow ||
    colorParams.hdrLight || colorParams.hdrHighlight || colorParams.hdrGlobal ||
    colorParams.hdrSpecular;

  return { hasQualifier, hasWindow, hasHDRWheels };
}

/**
 * Check if per-channel gain parameters are specified
 */
function hasPerChannelGain(adjustments) {
  return adjustments.gainR !== undefined ||
         adjustments.gainG !== undefined ||
         adjustments.gainB !== undefined ||
         adjustments.gainMaster !== undefined;
}

/**
 * PNT1: Create parallel node structure for skin protection workflow
 * Creates: Input -> Splitter -> [Node A, Node B] -> Combiner -> Output
 *
 * Parallel nodes allow processing the same input through multiple paths
 * that are then combined. Common use cases:
 * - Skin protection: Keep skin tones on path A, apply heavy grade on path B
 * - Selective processing: Different treatments for shadows vs highlights
 * - Creative blending: Mix multiple looks together
 *
 * @param {Object} options - Configuration options
 * @param {Object} options.nodeA - First parallel node configuration
 * @param {Object} options.nodeA.params - Color parameters for node A
 * @param {string} options.nodeA.label - Label for node A (default: 'Path A')
 * @param {Object} options.nodeB - Second parallel node configuration
 * @param {Object} options.nodeB.params - Color parameters for node B
 * @param {string} options.nodeB.label - Label for node B (default: 'Path B')
 * @param {number} options.mixRatio - Mix ratio between paths (0=all A, 1=all B, 0.5=equal, default: 0.5)
 * @param {string} options.combineMode - How to combine paths ('mix' | 'add' | 'multiply', default: 'mix')
 * @returns {Object} - Parallel node graph structure with nodes and connections
 */
function createParallelNodes(options = {}) {
  const {
    nodeA = { params: null, label: 'Path A' },
    nodeB = { params: null, label: 'Path B' },
    mixRatio = 0.5,
    combineMode = 'mix',
  } = options;

  // Node IDs in the parallel structure (these will be offset by baseNodeId in generateMultiNodeDRX)
  // Structure: Splitter (1) -> [Node A (2), Node B (3)] -> Combiner (4)
  const nodes = [
    {
      id: 1,
      label: 'Splitter',
      type: 'splitter',
      params: null, // Splitter has no color params
      xPos: 100,
      yPos: 180,
    },
    {
      id: 2,
      label: nodeA.label || 'Path A',
      type: 'corrector',
      params: nodeA.params || null,
      xPos: 370,
      yPos: 100, // Upper path
    },
    {
      id: 3,
      label: nodeB.label || 'Path B',
      type: 'corrector',
      params: nodeB.params || null,
      xPos: 370,
      yPos: 260, // Lower path
    },
    {
      id: 4,
      label: 'Combiner',
      type: 'combiner',
      params: null, // Combiner has no color params
      mixRatio,
      combineMode,
      xPos: 640,
      yPos: 180,
    },
  ];

  // Connections for parallel structure
  // Splitter outputs to both paths, both paths feed into combiner
  const connections = [
    { from: 1, to: 2 }, // Splitter -> Path A
    { from: 1, to: 3 }, // Splitter -> Path B
    { from: 2, to: 4 }, // Path A -> Combiner
    { from: 3, to: 4 }, // Path B -> Combiner
  ];

  return {
    type: 'parallel',
    nodes,
    connections,
    metadata: {
      mixRatio,
      combineMode,
      nodeALabel: nodeA.label,
      nodeBLabel: nodeB.label,
    },
  };
}

/**
 * PNT2: Create layer mixer node for blending
 * Layer mixers allow blending foreground and background nodes with various blend modes.
 *
 * Blend modes:
 * - normal: Standard opacity blend (foreground over background)
 * - overlay: Increases contrast, combines multiply and screen
 * - softLight: Softer version of overlay, good for subtle adjustments
 * - multiply: Darkens by multiplying colors (black stays black)
 * - screen: Lightens by inverting, multiplying, inverting again
 * - add: Additive blending (can blow out highlights)
 * - subtract: Subtractive blending (can crush blacks)
 *
 * @param {string} blendMode - Blend mode ('normal' | 'overlay' | 'softLight' | 'multiply' | 'screen' | 'add' | 'subtract')
 * @param {number} opacity - Opacity of blend (0-1, where 1 = full effect)
 * @param {Object} foregroundNode - Foreground node configuration
 * @param {Object} foregroundNode.params - Color parameters for foreground
 * @param {string} foregroundNode.label - Label for foreground node
 * @param {Object} backgroundNode - Background node configuration
 * @param {Object} backgroundNode.params - Color parameters for background
 * @param {string} backgroundNode.label - Label for background node
 * @returns {Object} - Layer mixer node configuration with nodes and connections
 */
function createLayerMixer(blendMode, opacity, foregroundNode, backgroundNode) {
  // Validate blend mode
  const validBlendModes = ['normal', 'overlay', 'softLight', 'multiply', 'screen', 'add', 'subtract'];
  if (!validBlendModes.includes(blendMode)) {
    console.warn(`[DRX] Invalid blend mode '${blendMode}', defaulting to 'normal'`);
    blendMode = 'normal';
  }

  // Clamp opacity to valid range
  opacity = Math.max(0, Math.min(1, opacity));

  // Map blend mode to DaVinci Resolve layer mixer type ID
  // These are approximations based on Resolve's internal blend mode encoding
  const blendModeIds = {
    normal: 0,
    overlay: 1,
    softLight: 2,
    multiply: 3,
    screen: 4,
    add: 5,
    subtract: 6,
  };

  const nodes = [
    {
      id: 1,
      label: backgroundNode?.label || 'Background',
      type: 'corrector',
      params: backgroundNode?.params || null,
      xPos: 100,
      yPos: 180,
    },
    {
      id: 2,
      label: foregroundNode?.label || 'Foreground',
      type: 'corrector',
      params: foregroundNode?.params || null,
      xPos: 370,
      yPos: 100, // Foreground above background in node graph
    },
    {
      id: 3,
      label: `Layer Mixer (${blendMode})`,
      type: 'layer_mixer',
      blendMode,
      blendModeId: blendModeIds[blendMode],
      opacity,
      xPos: 640,
      yPos: 180,
    },
  ];

  // Connections: Background and Foreground both feed into Layer Mixer
  const connections = [
    { from: 1, to: 3 }, // Background -> Layer Mixer (as background input)
    { from: 2, to: 3 }, // Foreground -> Layer Mixer (as foreground input)
  ];

  return {
    type: 'layer_mixer',
    nodes,
    connections,
    metadata: {
      blendMode,
      blendModeId: blendModeIds[blendMode],
      opacity,
      foregroundLabel: foregroundNode?.label || 'Foreground',
      backgroundLabel: backgroundNode?.label || 'Background',
    },
  };
}

/**
 * PNT3: Create outside node (inverse of qualified/windowed area)
 * Used for: grade everything EXCEPT the qualified area
 *
 * Outside nodes are essential for workflows like:
 * - Sky replacement: Grade the sky, leave the rest untouched
 * - Subject isolation: Protect skin tones, grade everything else
 * - Vignette effects: Grade the edges, leave center clean
 *
 * The outside node inverts the effect of a qualifier or power window,
 * applying corrections to the non-selected area.
 *
 * @param {Object} qualifierNode - The node containing the qualifier/window
 * @param {Object} qualifierNode.params - Color parameters of the qualified node
 * @param {string} qualifierNode.label - Label for the qualified node
 * @param {Object} qualifierNode.qualifier - HSL qualifier settings (optional)
 * @param {Object} qualifierNode.window - Power window settings (optional)
 * @param {Object} outsideParams - Color parameters to apply to the outside (non-qualified) area
 * @param {Object} outsideParams.params - Color correction parameters for outside
 * @param {string} outsideParams.label - Label for the outside node
 * @returns {Object} - Outside node configuration with paired qualifier and outside nodes
 */
function createOutsideNode(qualifierNode, outsideParams) {
  // Default configurations
  const qualifiedLabel = qualifierNode?.label || 'Qualified Area';
  const outsideLabel = outsideParams?.label || 'Outside (Inverse)';

  const nodes = [
    {
      id: 1,
      label: qualifiedLabel,
      type: 'corrector',
      params: qualifierNode?.params || null,
      qualifier: qualifierNode?.qualifier || null, // HSL qualifier settings
      window: qualifierNode?.window || null, // Power window settings
      xPos: 100,
      yPos: 180,
    },
    {
      id: 2,
      label: outsideLabel,
      type: 'outside', // Special type indicating this is an outside node
      params: outsideParams?.params || null,
      // The outside node references the qualifier from node 1
      outsideOf: 1, // Reference to the qualified node
      invertQualifier: true, // Flag indicating this inverts the qualifier
      xPos: 370,
      yPos: 180,
    },
  ];

  // Serial connection - the outside node follows the qualified node
  const connections = [
    { from: 1, to: 2 }, // Qualified -> Outside
  ];

  return {
    type: 'outside',
    nodes,
    connections,
    metadata: {
      qualifiedNodeId: 1,
      outsideNodeId: 2,
      qualifiedLabel,
      outsideLabel,
      hasQualifier: !!(qualifierNode?.qualifier),
      hasWindow: !!(qualifierNode?.window),
    },
  };
}

/**
 * Helper: Create a neutral node base for professional node structures
 * @returns {Object} - Neutral grade parameters
 */
function createNeutralNodeParams() {
  return {
    lift: { r: 0, g: 0, b: 0, master: 0 },
    gamma: { r: 0, g: 0, b: 0, master: 0 },
    gain: { r: 1, g: 1, b: 1, master: 1 },
    offset: { r: 0, g: 0, b: 0 },
    saturation: 1.0,
    contrast: 1.0,
    pivot: 0.435,
  };
}

/**
 * Parse AI adjustments into separate labeled nodes for modular grading
 * Each adjustment type gets its own node with a descriptive label
 *
 * @param {Object} adjustments - AI adjustment parameters
 * @param {Object} options - Optional settings
 * @param {boolean} options.forceNeutralIfEmpty - If true, return a neutral "Reset" node when all values are near-neutral
 *                                                 (useful for tweaks that cancel out, e.g., "warm" then "cool")
 * @returns {Array} - Array of node definitions for multi-node DRX
 */
function parseAdjustmentsToNodes(adjustments, options = {}) {
  const { forceNeutralIfEmpty = false } = options;
  debugLog('[DRX] parseAdjustmentsToNodes input:', JSON.stringify(adjustments, null, 2));
  debugLog('[DRX] parseAdjustmentsToNodes options:', { forceNeutralIfEmpty });

  // ═══════════════════════════════════════════════════════════════════════════
  // SEMANTIC RANGE DETECTION — auto-scale values sent in -1/+1 range
  // LLMs sometimes send semantic values (saturation: 0.6) instead of UI values
  // (saturation: 60). Detect this and correct it to prevent catastrophic results
  // like near-zero saturation (B&W image) or silent temperature drops.
  // ═══════════════════════════════════════════════════════════════════════════
  adjustments = { ...adjustments }; // shallow copy to avoid mutating caller's object

  // Saturation: UI range 0-100 (50=neutral). Semantic range -1 to +1.
  // If value is between -1.5 and +1.5 and not exactly 0, it's almost certainly semantic.
  if (adjustments.saturation !== undefined && Math.abs(adjustments.saturation) <= 1.5 && adjustments.saturation !== 0) {
    const original = adjustments.saturation;
    // Convert: semantic -1→0, 0→50, +1→100
    adjustments.saturation = 50 + (adjustments.saturation * 50);
    console.warn(`[DRX] AUTO-SCALED saturation: ${original} (semantic) → ${adjustments.saturation} (UI). Caller should send UI values 0-100 where 50=neutral.`);
  }

  // Temperature: UI range -4000 to +4000 (0=neutral). Semantic range -1 to +1.
  // If abs(value) <= 1.5, it's semantic (a real UI temp of 1 is invisible).
  if (adjustments.temperature !== undefined && Math.abs(adjustments.temperature) <= 1.5 && adjustments.temperature !== 0) {
    const original = adjustments.temperature;
    adjustments.temperature = adjustments.temperature * 4000;
    console.warn(`[DRX] AUTO-SCALED temperature: ${original} (semantic) → ${adjustments.temperature} (UI). Caller should send UI values -4000 to +4000.`);
  }

  // Tint: UI range -100 to +100 (0=neutral). Semantic range -1 to +1.
  // If abs(value) <= 1.5, it's semantic.
  if (adjustments.tint !== undefined && Math.abs(adjustments.tint) <= 1.5 && adjustments.tint !== 0) {
    const original = adjustments.tint;
    adjustments.tint = adjustments.tint * 100;
    console.warn(`[DRX] AUTO-SCALED tint: ${original} (semantic) → ${adjustments.tint} (UI). Caller should send UI values -100 to +100.`);
  }

  // MidtoneDetail: UI range -100 to +100. Semantic range -1 to +1.
  if (adjustments.midtoneDetail !== undefined && Math.abs(adjustments.midtoneDetail) <= 1.5 && adjustments.midtoneDetail !== 0) {
    const original = adjustments.midtoneDetail;
    adjustments.midtoneDetail = adjustments.midtoneDetail * 100;
    console.warn(`[DRX] AUTO-SCALED midtoneDetail: ${original} (semantic) → ${adjustments.midtoneDetail} (UI). Caller should send UI values -100 to +100.`);
  }

  const nodes = [];

  // Helper to create a neutral node base
  const createNeutralParams = () => ({
    lift: { r: 0, g: 0, b: 0, master: 0 },
    gamma: { r: 0, g: 0, b: 0, master: 0 },
    gain: { r: 1, g: 1, b: 1, master: 1 },
    offset: { r: 0, g: 0, b: 0 },
    saturation: 50,      // Resolve Primaries: 0-100, unity=50
    contrast: 1.0,       // Resolve Primaries: 0.0-2.0, unity=1.0
    pivot: 0.435,
    temperature: 0,      // Resolve Primaries: -4000 to +4000, unity=0
    tint: 0,             // Resolve Primaries: -100 to +100, unity=0
  });

  // Node 1: Exposure (if adjusted)
  if (adjustments.exposure && Math.abs(adjustments.exposure) > 0.01) {
    const params = createNeutralParams();
    params.gain.master = 1 + adjustments.exposure;
    debugLog('[DRX] Exposure node: input=', adjustments.exposure, 'output gain.master=', params.gain.master);
    const direction = adjustments.exposure > 0 ? 'Brighter' : 'Darker';
    nodes.push({
      label: `Exposure (${direction})`,
      params,
    });
  }

  // Node 2: Temperature/Tint (if adjusted)
  // Input: Resolve UI values — Temperature: -4000 to +4000, Tint: -100 to +100
  if ((adjustments.temperature && Math.abs(adjustments.temperature) > 1) ||
      (adjustments.tint && Math.abs(adjustments.tint) > 0.5)) {
    const params = createNeutralParams();
    if (adjustments.temperature) {
      const t = adjustments.temperature;
      // Pass through as Resolve UI value (already -4000 to +4000)
      params.temperature = t;
      // Also apply subtle gain/lift tinting for richer look
      // Normalize to -1..+1 range for tinting multipliers
      const tNorm = t / 4000;
      params.gain.r += tNorm * 0.15;
      params.gain.b -= tNorm * 0.15;
      params.lift.r += tNorm * 0.08;
      params.lift.b -= tNorm * 0.08;
      debugLog('[DRX] Color Balance node: temp=', t, '(UI value, normalized=', tNorm, ') gain.r=', params.gain.r);
    }
    if (adjustments.tint) {
      const t = adjustments.tint;
      // Pass through as Resolve UI value (already -100 to +100)
      params.tint = t;
      // Normalize to -1..+1 range for tinting multipliers
      const tNorm = t / 100;
      params.gain.g -= tNorm * 0.15;
      params.lift.g -= tNorm * 0.08;
    }
    const tempLabel = adjustments.temperature > 0 ? 'Warm' : adjustments.temperature < 0 ? 'Cool' : '';
    nodes.push({
      label: `Color Balance${tempLabel ? ` (${tempLabel})` : ''}`,
      params,
    });
  }

  // Node 2b: Shadow/Highlight Color Split (Teal/Orange effect)
  // This handles shadowTemperature, highlightTemperature, shadowTint, highlightTint
  const hasShadowTemp = adjustments.shadowTemperature && Math.abs(adjustments.shadowTemperature) > 0.01;
  const hasHighlightTemp = adjustments.highlightTemperature && Math.abs(adjustments.highlightTemperature) > 0.01;
  const hasShadowTint = adjustments.shadowTint && Math.abs(adjustments.shadowTint) > 0.01;
  const hasHighlightTint = adjustments.highlightTint && Math.abs(adjustments.highlightTint) > 0.01;

  if (hasShadowTemp || hasHighlightTemp || hasShadowTint || hasHighlightTint) {
    const params = createNeutralParams();

    // Calibrated multipliers for zone-based temperature
    // These convert normalized (-1 to +1) parameters to Resolve lift/gain values
    // Calibrated for visible but tasteful color shifts
    const SHADOW_TEMP_MULTIPLIER = 0.40;   // Lift RGB shift per unit temp
    const HIGHLIGHT_TEMP_MULTIPLIER = 0.35; // Gain RGB shift per unit temp
    const TINT_MULTIPLIER = 0.30;           // Green channel shift for tint

    // Shadow temperature affects lift (shadows)
    // Negative = teal/cool (more blue, less red)
    // Positive = warm (more red, less blue)
    if (hasShadowTemp) {
      const st = adjustments.shadowTemperature;
      // Temperature shifts R and B in opposite directions
      params.lift.r += st * SHADOW_TEMP_MULTIPLIER;
      params.lift.b -= st * SHADOW_TEMP_MULTIPLIER;
      // Add green for true teal/cyan (cyan = blue + green)
      params.lift.g -= st * (SHADOW_TEMP_MULTIPLIER * 0.35);
    }

    // Highlight temperature affects gain (highlights)
    // Positive = orange/warm, Negative = cool
    if (hasHighlightTemp) {
      const ht = adjustments.highlightTemperature;
      // Orange = red boost + blue reduction
      params.gain.r += ht * HIGHLIGHT_TEMP_MULTIPLIER;
      params.gain.b -= ht * (HIGHLIGHT_TEMP_MULTIPLIER * 0.85);
      // Slight green for gold/yellow tone
      params.gain.g += ht * (HIGHLIGHT_TEMP_MULTIPLIER * 0.15);
    }

    // Shadow tint affects lift green (magenta/green in shadows)
    if (hasShadowTint) {
      const stint = adjustments.shadowTint;
      params.lift.g -= stint * TINT_MULTIPLIER;
    }

    // Highlight tint affects gain green (magenta/green in highlights)
    if (hasHighlightTint) {
      const htint = adjustments.highlightTint;
      params.gain.g -= htint * TINT_MULTIPLIER;
    }

    // Create descriptive label
    let splitLabel = 'Color Split';
    if (hasShadowTemp && hasHighlightTemp) {
      const shadowDir = adjustments.shadowTemperature < 0 ? 'Teal' : 'Orange';
      const highlightDir = adjustments.highlightTemperature > 0 ? 'Orange' : 'Teal';
      splitLabel = `${shadowDir} Shadows / ${highlightDir} Highlights`;
    } else if (hasShadowTemp) {
      splitLabel = adjustments.shadowTemperature < 0 ? 'Teal Shadows' : 'Warm Shadows';
    } else if (hasHighlightTemp) {
      splitLabel = adjustments.highlightTemperature > 0 ? 'Orange Highlights' : 'Cool Highlights';
    }

    nodes.push({
      label: splitLabel,
      params,
    });
  }

  // Node 3: Contrast (if adjusted)
  // Input: Resolve UI value — 0 to 2, unity=1.0
  // NOTE: We implement contrast using Lift/Gain instead of the Contrast Corrector (Type 2)
  // because Type 2 was causing HSL qualifier issues. Lift/Gain achieves the same effect
  // and works reliably with the Primary Corrector (Type 1).
  if (adjustments.contrast !== undefined && Math.abs(adjustments.contrast - 1.0) > 0.01) {
    const params = createNeutralParams();
    const c = adjustments.contrast;

    // Implement contrast using Lift (shadows) and Gain (highlights)
    // Offset from unity (1.0): positive = more contrast, negative = less
    const contrastAmount = (c - 1.0) * 0.15; // Scale for subtlety

    // Adjust lift (shadows) - lower for more contrast
    params.lift.r = -contrastAmount;
    params.lift.g = -contrastAmount;
    params.lift.b = -contrastAmount;
    params.lift.master = -contrastAmount * 0.5;

    // Adjust gain (highlights) - raise for more contrast
    params.gain.r = 1.0 + contrastAmount;
    params.gain.g = 1.0 + contrastAmount;
    params.gain.b = 1.0 + contrastAmount;
    params.gain.master = 1.0 + (contrastAmount * 0.5);

    debugLog('[DRX] Contrast node: input=', c, '(offset from unity=', c - 1.0, ') lift=', params.lift.r, 'gain=', params.gain.r);

    const direction = adjustments.contrast > 1.0 ? 'More' : 'Less';
    nodes.push({
      label: `Contrast (${direction})`,
      params,
    });
  }

  // Node 4: Shadows (if adjusted)
  if (adjustments.shadowLift && Math.abs(adjustments.shadowLift) > 0.01) {
    const params = createNeutralParams();
    const s = adjustments.shadowLift;
    // Stronger multiplier for visible shadow changes (0.25 instead of 0.1)
    params.lift.r += s * 0.25;
    params.lift.g += s * 0.25;
    params.lift.b += s * 0.25;
    params.lift.master += s * 0.15; // Also adjust master for overall effect
    debugLog('[DRX] Shadows node: input=', s, 'output lift.r=', params.lift.r, 'lift.master=', params.lift.master);
    const direction = adjustments.shadowLift > 0 ? 'Lifted' : 'Crushed';
    nodes.push({
      label: `Shadows (${direction})`,
      params,
    });
  }

  // Node 5: Highlights (if adjusted)
  if (adjustments.highlightCompression && Math.abs(adjustments.highlightCompression) > 0.01) {
    const params = createNeutralParams();
    const h = adjustments.highlightCompression;
    params.gain.r -= h * 0.1;
    params.gain.g -= h * 0.1;
    params.gain.b -= h * 0.1;
    nodes.push({
      label: 'Highlights (Rolled)',
      params,
    });
  }

  // Node 6: Saturation (if adjusted)
  // Input: Resolve UI value — 0 to 100, unity=50
  if (adjustments.saturation !== undefined && Math.abs(adjustments.saturation - 50) > 0.5) {
    const params = createNeutralParams();
    params.saturation = adjustments.saturation;
    debugLog('[DRX] Saturation node: input=', adjustments.saturation, '(UI value, unity=50)');
    const direction = adjustments.saturation > 50 ? 'Vibrant' : 'Muted';
    nodes.push({
      label: `Saturation (${direction})`,
      params,
    });
  }

  // Node 7: Midtone Detail (if adjusted)
  // Input: Resolve UI value — -100 to +100, unity=0
  // buildPrimaryCorrectorParams now passes through (no ×100 scaling)
  if (adjustments.midtoneDetail !== undefined && Math.abs(adjustments.midtoneDetail) > 0.5) {
    const params = createNeutralParams();
    // Midtone Detail maps to DaVinci's Mid/Detail slider in the Primaries panel
    // Positive values = sharper midtones, negative = softer midtones
    // Pass through directly — buildPrimary clamps to [-100, +100]
    params.midtoneDetail = adjustments.midtoneDetail;
    debugLog('[DRX] Midtone Detail node: input=', adjustments.midtoneDetail, '(UI value)');
    const direction = adjustments.midtoneDetail > 0 ? 'Sharper' : 'Softer';
    nodes.push({
      label: `Midtone Detail (${direction})`,
      params,
    });
  }

  // Node 8: HDR Zones + Black Offset (if adjusted)
  // Check for hdrDark, hdrShadow, hdrLight, hdrHighlight, hdrGlobal
  const hdrZones = ['hdrDark', 'hdrShadow', 'hdrLight', 'hdrHighlight', 'hdrGlobal'];
  const activeHdrZones = hdrZones.filter(zone => {
    const zoneParams = adjustments[zone];
    if (!zoneParams) return false;
    // Check if zone has non-default exposure (non-zero) or saturation (non-1)
    const hasExposure = zoneParams.exposure !== undefined && Math.abs(zoneParams.exposure) > 0.01;
    const hasSaturation = zoneParams.saturation !== undefined && Math.abs(zoneParams.saturation - 1) > 0.01;
    return hasExposure || hasSaturation;
  });
  const hasBlackOffset = adjustments.blackOffset !== undefined && Math.abs(adjustments.blackOffset) > 0.001;

  if (activeHdrZones.length > 0 || hasBlackOffset) {
    const params = createNeutralParams();
    // Copy HDR zone params to the node params so buildHDRWheelParams can find them
    for (const zone of activeHdrZones) {
      params[zone] = adjustments[zone];
    }
    // Black Offset is a global HDR control, encoded as flat param in Primary corrector
    if (hasBlackOffset) {
      params.blackOffset = adjustments.blackOffset;
    }
    // Generate descriptive label
    const zoneDescriptions = activeHdrZones.map(zone => {
      const zoneParams = adjustments[zone];
      const zoneName = zone.replace('hdr', '');
      const exp = zoneParams.exposure || 0;
      return `${zoneName} ${exp > 0 ? '+' : ''}${exp.toFixed(2)}`;
    });
    if (hasBlackOffset) {
      zoneDescriptions.push(`BlackOffset ${adjustments.blackOffset > 0 ? '+' : ''}${adjustments.blackOffset.toFixed(3)}`);
    }
    debugLog('[DRX] HDR Zones node: zones=', activeHdrZones.join(', '));
    nodes.push({
      label: `HDR (${zoneDescriptions.join(', ')})`,
      params,
      hasHDRWheels: true,  // Flag for createNode to call buildHDRWheelParams
    });
  }

  // Node 9: LOG Wheels (if adjusted)
  // Check for logShadowR/G/B, logMidR/G/B, logHighR/G/B
  const logChannels = ['logShadowR', 'logShadowG', 'logShadowB', 'logMidR', 'logMidG', 'logMidB', 'logHighR', 'logHighG', 'logHighB'];
  const activeLogChannels = logChannels.filter(ch => {
    return adjustments[ch] !== undefined && Math.abs(adjustments[ch]) > 0.005;
  });

  if (activeLogChannels.length > 0) {
    const params = createNeutralParams();
    // Convert flat logShadowR/G/B to nested logShadow: {r, g, b} structure for encoding
    params.logShadow = { r: 0, g: 0, b: 0 };
    params.logMid = { r: 0, g: 0, b: 0 };
    params.logHigh = { r: 0, g: 0, b: 0 };

    for (const ch of activeLogChannels) {
      if (ch.startsWith('logShadow')) {
        const channel = ch.replace('logShadow', '').toLowerCase();
        params.logShadow[channel] = adjustments[ch];
      } else if (ch.startsWith('logMid')) {
        const channel = ch.replace('logMid', '').toLowerCase();
        params.logMid[channel] = adjustments[ch];
      } else if (ch.startsWith('logHigh')) {
        const channel = ch.replace('logHigh', '').toLowerCase();
        params.logHigh[channel] = adjustments[ch];
      }
    }
    debugLog('[DRX] LOG Wheels node: logShadow=', params.logShadow, 'logMid=', params.logMid, 'logHigh=', params.logHigh);
    nodes.push({
      label: 'LOG Wheels',
      params,
    });
  }

  // Node 9b: RGB Mixer (if adjusted)
  if (adjustments.rgbMixer) {
    const params = createNeutralParams();
    params.rgbMixer = adjustments.rgbMixer;
    debugLog('[DRX] RGB Mixer node');
    nodes.push({
      label: 'RGB Mixer',
      params,
    });
  }

  // Node 9c: Custom Curves YRGB (if adjusted)
  if (adjustments.customCurves) {
    const params = createNeutralParams();
    params.customCurves = adjustments.customCurves;
    const channelList = Object.keys(adjustments.customCurves).filter(k => adjustments.customCurves[k]?.length > 0);
    debugLog('[DRX] Custom Curves node: channels=', channelList.join(','));
    nodes.push({
      label: 'Curves (' + channelList.map(c => c.toUpperCase()).join('/') + ')',
      params,
    });
  }

  // Node 9d: HSL Curves (if adjusted)
  if (adjustments.hslCurves) {
    const params = createNeutralParams();
    params.hslCurves = adjustments.hslCurves;
    const curveList = Object.keys(adjustments.hslCurves).filter(k => adjustments.hslCurves[k]?.length > 0);
    debugLog('[DRX] HSL Curves node: curves=', curveList.join(','));
    nodes.push({
      label: 'HSL Curves',
      params,
    });
  }

  // Node 10: Per-channel primaries (liftR/G/B, gammaR/G/B, gainR/G/B)
  const perChannelKeys = [
    'liftR', 'liftG', 'liftB', 'liftMaster',
    'gammaR', 'gammaG', 'gammaB', 'gammaMaster',
    'gainR', 'gainG', 'gainB', 'gainMaster',
  ];
  const activePerChannel = perChannelKeys.filter(k => {
    return adjustments[k] !== undefined && Math.abs(adjustments[k]) > 0.005;
  });

  if (activePerChannel.length > 0) {
    const params = createNeutralParams();
    // Apply per-channel adjustments to the nested structure
    for (const key of activePerChannel) {
      if (key.startsWith('lift')) {
        const ch = key.replace('lift', '').toLowerCase();
        params.lift[ch] = (params.lift[ch] || 0) + adjustments[key];
      } else if (key.startsWith('gamma')) {
        const ch = key.replace('gamma', '').toLowerCase();
        params.gamma[ch] = (params.gamma[ch] || 0) + adjustments[key];
      } else if (key.startsWith('gain')) {
        const ch = key.replace('gain', '').toLowerCase();
        // Gain defaults to 1, so add to existing
        params.gain[ch] = (params.gain[ch] || 1) + adjustments[key];
      }
    }
    debugLog('[DRX] Per-channel primaries node:', activePerChannel.join(', '));
    nodes.push({
      label: 'Color Wheels',
      params,
    });
  }

  // Node 11: ColorBoost (if adjusted)
  if (adjustments.colorBoost !== undefined && Math.abs(adjustments.colorBoost) > 0.5) {
    const params = createNeutralParams();
    params.colorBoost = adjustments.colorBoost;
    debugLog('[DRX] ColorBoost node: input=', adjustments.colorBoost);
    nodes.push({
      label: `Color Boost (${adjustments.colorBoost > 0 ? '+' : ''}${adjustments.colorBoost})`,
      params,
    });
  }

  // Node 12: Pivot/Contrast Range (if adjusted)
  const hasPivot = adjustments.pivot !== undefined && Math.abs(adjustments.pivot - 0.435) > 0.01;
  const hasHighRange = adjustments.contrastHighRange !== undefined && Math.abs(adjustments.contrastHighRange - 0.75) > 0.01;
  const hasLowRange = adjustments.contrastLowRange !== undefined && Math.abs(adjustments.contrastLowRange - 0.25) > 0.01;

  if (hasPivot || hasHighRange || hasLowRange) {
    const params = createNeutralParams();
    if (hasPivot) params.pivot = adjustments.pivot;
    if (hasHighRange) params.contrastHighRange = adjustments.contrastHighRange;
    if (hasLowRange) params.contrastLowRange = adjustments.contrastLowRange;
    debugLog('[DRX] Pivot/Range node: pivot=', params.pivot, 'highRange=', params.contrastHighRange, 'lowRange=', params.contrastLowRange);
    nodes.push({
      label: 'Contrast Range',
      params,
    });
  }

  // If no adjustments detected
  if (nodes.length === 0) {
    if (forceNeutralIfEmpty) {
      // Caller explicitly wants a neutral grade (e.g., tweak that cancelled out to neutral)
      // Generate a Reset node that clears all adjustments
      debugLog('[DRX] No adjustments but forceNeutralIfEmpty=true - generating Reset node');
      const neutralParams = createNeutralParams();
      return [{
        label: 'Reset (Neutral)',
        params: neutralParams,
      }];
    }
    debugLog('[DRX] No adjustments detected - returning empty nodes to avoid overwriting existing grade');
    // Previously we returned a "Base Grade" neutral node, but that was overwriting existing grades
    // Now we return empty so the caller can decide whether to error or proceed
    return [];
  }

  debugLog('[DRX] parseAdjustmentsToNodes output: created', nodes.length, 'nodes');
  nodes.forEach((n, i) => {
    debugLog(`[DRX] Output node ${i + 1}: "${n.label}"`, 'saturation:', n.params.saturation, 'contrast:', n.params.contrast, 'gain.master:', n.params.gain.master);
  });
  return nodes;
}

/**
 * Generate a delta-only DRX containing ONLY adjustment nodes (no base grade).
 * Used for storing deltas that can be re-applied to any base.
 *
 * This function is part of the DRX Audit Trail System:
 * - Produces a DRX file that contains only the new adjustments
 * - Can be merged with any base grade to produce the same result
 * - Used for debugging and auditing grade changes
 *
 * @param {Object} deltaParams - Adjustment parameters (from tweak or LLM)
 * @param {Object} metadata - Optional metadata for the DRX
 * @param {string} metadata.label - Label for the delta DRX
 * @param {boolean} metadata.skipNeutralNodes - Skip nodes that have no effect (default: true)
 * @returns {Promise<string|null>} - DRX XML content, or null if no adjustments
 */
async function generateDeltaDRX(deltaParams, metadata = {}) {
  const {
    label = 'Delta Grade',
    skipNeutralNodes = true,
    width = 1920,
    height = 1080,
  } = metadata;

  debugLog('[DRX] generateDeltaDRX input:', JSON.stringify(deltaParams, null, 2));

  // Parse adjustments into nodes
  const nodes = parseAdjustmentsToNodes(deltaParams, { forceNeutralIfEmpty: false });

  // If no adjustments, return null (caller can decide what to do)
  if (!nodes || nodes.length === 0) {
    debugLog('[DRX] generateDeltaDRX: no adjustments - returning null');
    return null;
  }

  // Optionally filter out neutral nodes
  let filteredNodes = nodes;
  if (skipNeutralNodes) {
    filteredNodes = nodes.filter(node => {
      if (!node.params) return false;
      const p = node.params;

      // Check if any parameter is non-neutral
      const hasLift = p.lift && (
        Math.abs(p.lift.r) > 0.001 ||
        Math.abs(p.lift.g) > 0.001 ||
        Math.abs(p.lift.b) > 0.001 ||
        Math.abs(p.lift.master) > 0.001
      );
      const hasGamma = p.gamma && (
        Math.abs(p.gamma.r) > 0.001 ||
        Math.abs(p.gamma.g) > 0.001 ||
        Math.abs(p.gamma.b) > 0.001 ||
        Math.abs(p.gamma.master) > 0.001
      );
      const hasGain = p.gain && (
        Math.abs(p.gain.r - 1) > 0.001 ||
        Math.abs(p.gain.g - 1) > 0.001 ||
        Math.abs(p.gain.b - 1) > 0.001 ||
        Math.abs(p.gain.master - 1) > 0.001
      );
      const hasOffset = p.offset && (
        Math.abs(p.offset.r) > 0.001 ||
        Math.abs(p.offset.g) > 0.001 ||
        Math.abs(p.offset.b) > 0.001
      );
      const hasSaturation = p.saturation !== undefined && Math.abs(p.saturation - 50) > 0.001;
      const hasContrast = p.contrast !== undefined && Math.abs(p.contrast - 1.0) > 0.001;
      const hasMidtoneDetail = p.midtoneDetail !== undefined && Math.abs(p.midtoneDetail) > 0.001;

      return hasLift || hasGamma || hasGain || hasOffset || hasSaturation || hasContrast || hasMidtoneDetail;
    });

    if (filteredNodes.length === 0) {
      debugLog('[DRX] generateDeltaDRX: all nodes filtered as neutral - returning null');
      return null;
    }
  }

  debugLog('[DRX] generateDeltaDRX: generating DRX with', filteredNodes.length, 'delta nodes');

  // Create connections for serial node chain
  const connections = [];
  for (let i = 0; i < filteredNodes.length - 1; i++) {
    connections.push({ from: i + 1, to: i + 2 });
  }

  // Generate the delta DRX using multi-node generator
  const drxContent = await generateMultiNodeDRX(filteredNodes, connections, {
    label: `[DELTA] ${label}`,
    width,
    height,
    isDelta: true,  // Flag for identification
  });

  return drxContent;
}

/**
 * Compute SHA-256 hash of DRX content for sync verification
 *
 * @param {string} drxContent - DRX XML content
 * @returns {string} - SHA-256 hash (first 16 characters)
 */
function computeDrxHash(drxContent) {
  if (!drxContent) return null;
  const crypto = require('crypto');
  return crypto
    .createHash('sha256')
    .update(drxContent)
    .digest('hex')
    .slice(0, 16);
}

/**
 * Validate a generated DRX body hex string
 *
 * Decompresses (0x81 + zstd) and parses the protobuf to verify that
 * node(s) contain corrector blocks (F9) with parameter entries (F3).
 * Run this after every DRX generation to catch encoding failures before
 * applying broken DRXs to Resolve.
 *
 * @param {string} bodyHex - The hex-encoded DRX body (0x81 + zstd data)
 * @returns {Promise<{valid: boolean, summary: string, nodes: Array}>}
 */
async function validateDRXBody(bodyHex) {
  const { parseDRXBody } = require('./drx-parser');

  try {
    const result = await parseDRXBody(bodyHex);
    const { nodes } = result;

    if (!nodes || nodes.length === 0) {
      return { valid: false, summary: 'No nodes found in DRX body', nodes: [] };
    }

    const nodeDetails = [];
    let totalParams = 0;
    let nodesWithCorrectors = 0;

    for (const node of nodes) {
      const detail = {
        id: node.id,
        label: node.label || '(unlabeled)',
        hasCorrectors: false,
        paramCount: 0,
        params: [],
      };

      // Check if the node has any non-default parameters
      if (node.params) {
        // Count non-default primary params
        const checks = [
          { name: 'lift.r', val: node.params.lift?.r, def: 0 },
          { name: 'lift.g', val: node.params.lift?.g, def: 0 },
          { name: 'lift.b', val: node.params.lift?.b, def: 0 },
          { name: 'lift.master', val: node.params.lift?.master, def: 0 },
          { name: 'gamma.r', val: node.params.gamma?.r, def: 0 },
          { name: 'gamma.g', val: node.params.gamma?.g, def: 0 },
          { name: 'gamma.b', val: node.params.gamma?.b, def: 0 },
          { name: 'gamma.master', val: node.params.gamma?.master, def: 0 },
          { name: 'gain.r', val: node.params.gain?.r, def: 1 },
          { name: 'gain.g', val: node.params.gain?.g, def: 1 },
          { name: 'gain.b', val: node.params.gain?.b, def: 1 },
          { name: 'gain.master', val: node.params.gain?.master, def: 1 },
          { name: 'offset.r', val: node.params.offset?.r, def: 0 },
          { name: 'offset.g', val: node.params.offset?.g, def: 0 },
          { name: 'offset.b', val: node.params.offset?.b, def: 0 },
          { name: 'saturation', val: node.params.saturation, def: 50 },
          { name: 'temperature', val: node.params.temperature, def: 0 },
          { name: 'tint', val: node.params.tint, def: 0 },
          { name: 'contrast', val: node.params.contrast, def: 1 },
        ];

        for (const { name, val, def } of checks) {
          if (val != null && Math.abs(val - def) > 0.001) {
            detail.params.push(`${name}=${val}`);
            detail.paramCount++;
          }
        }

        // Check for NaN values (the bug we're fixing)
        for (const { name, val } of checks) {
          if (val != null && isNaN(val)) {
            return {
              valid: false,
              summary: `NaN detected in parameter ${name} on node "${detail.label}" — undefined value leaked into protobuf`,
              nodes: nodeDetails,
            };
          }
        }
      }

      // Check raw corrector data from the parser
      if (node.correctors && node.correctors.length > 0) {
        detail.hasCorrectors = true;
        nodesWithCorrectors++;
      } else if (detail.paramCount > 0) {
        detail.hasCorrectors = true;
        nodesWithCorrectors++;
      }

      totalParams += detail.paramCount;
      nodeDetails.push(detail);
    }

    const summary = `${nodes.length} node(s), ${nodesWithCorrectors} with correctors, ${totalParams} non-default param(s): ${nodeDetails.map(n => `[${n.label}: ${n.params.join(', ') || 'neutral'}]`).join(' ')}`;

    return {
      valid: totalParams > 0 || nodesWithCorrectors > 0,
      summary,
      nodes: nodeDetails,
    };
  } catch (err) {
    return {
      valid: false,
      summary: `DRX parse failed: ${err.message}`,
      nodes: [],
    };
  }
}

// ── OFX / ResolveFX generic encoder ─────────────────────────────────────────

/**
 * Build a ResolveFX OFX tool entry for inclusion in F7.F10 (node tool list).
 *
 * TRAINED 2026-03-22: OFX container format fully decoded from Film Grain DRX.
 * Generic for ANY ResolveFX plugin — just pass the plugin ID and param name/value pairs.
 *
 * OFX container structure:
 *   F7.F10.F1 (tool entry):
 *     F2.F21 (OFX container):
 *       F1 = 0x4F4659 ("OFY" marker)
 *       F2 = plugin ID string (e.g., "com.blackmagicdesign.resolvefx.filmgrain")
 *       F3 = instance ID string
 *       F4 = 1 (enabled)
 *       F5[] (repeated) = param entries:
 *         F1 = param name (string)
 *         F2.F2 = param value (double) OR F2.F5 = param value (string)
 *
 * @param {string} pluginId — OFX plugin identifier (e.g., "com.blackmagicdesign.resolvefx.filmgrain")
 * @param {Object} params — Map of param name → value (number or string)
 * @param {Object} [options]
 * @param {string} [options.instanceId] — custom instance ID (auto-generated if omitted)
 * @param {string} [options.version='3.2'] — ResolveFX version
 * @returns {Object} — OFX plugin definition for inclusion in DRX adjustments
 */
function buildResolveFXParams(pluginId, params, options = {}) {
  const version = options.version || '3.2';
  const instanceId = options.instanceId || `OfxImageEffectContext_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

  return {
    _ofxPlugin: true,
    pluginId,
    instanceId,
    version,
    params: { ...params, resolvefxVersion: version },
  };
}

/**
 * Encode an OFX plugin tool entry as protobuf bytes for F7.F10.
 *
 * Generates the complete OFX container structure:
 *   F10.F1[0] = { F1=0xC0000001, F2={F2=2} }  (standard node marker)
 *   F10.F1[1] = { F1=toolId, F2.F5=pluginId }  (plugin identifier)
 *   F10.F1[2] = { F1=toolId+3, F2.F5=instanceId } (instance)
 *   F10.F1[3] = { F1=toolId+6, F2.F4=enabled }  (enable flag)
 *   F10.F1[4] = { F1=toolId+42, F2.F21=OFXContainer } (params)
 *   F10.F1[5] = { F1=toolId+63, F2.F4=0 }  (end marker)
 *
 * @param {string} pluginId — e.g., "com.blackmagicdesign.resolvefx.filmgrain"
 * @param {Object} params — name→value pairs (number or string)
 * @param {Object} [options]
 * @returns {Buffer} — F10 field bytes (length-delimited)
 */
function buildOFXToolEntry(pluginId, params, options = {}) {
  // Entry ids are UNIVERSAL CONSTANTS across every plugin (verified 2026-07-03 by
  // byte-diffing native tool lists for filmgrain/CST/acestransform/deflicker/NeatVideo:
  // all use marker 0xC0000001 · pluginId 0xC0000049 · instanceId 0xC000005E ·
  // enable 0xC0000063 · OFX container 0xC0000087 · end 0xC00000D2). The old
  // "Film Grain toolId 0xC0000087 + offsets" scheme misplaced every entry — Resolve
  // hard-CRASHED deserializing a string where it expected the container. Resolve keys
  // plugins by the pluginId STRING; there is no per-plugin tool id.
  const ID_PLUGIN = 0xC0000049, ID_INSTANCE = 0xC000005E, ID_ENABLE = 0xC0000063,
        ID_CONTAINER = 0xC0000087, ID_END = 0xC00000D2;
  // F3 is the OFX CONTEXT name, not a unique instance id — native captures carry the
  // standardized "OfxImageEffectContextFilter" (a synthesized unique string leaves the
  // plugin un-instantiated: node applies but the effect never engages — found live
  // 2026-07-03). Callers can still override for generator/transition contexts.
  const instanceId = options.instanceId || 'OfxImageEffectContextFilter';

  // Build F5 repeated param entries. Native containers always carry resolvefxVersion
  // and serialize params in name order — mirror both.
  const withVersion = { resolvefxVersion: options.version || '3.2', ...params };
  const paramEntries = [];
  for (const name of Object.keys(withVersion).sort()) {
    const value = withVersion[name];
    const nameBuf = Buffer.from(name, 'utf-8');
    let valueBuf;
    if (typeof value === 'string') {
      const strBuf = Buffer.from(value, 'utf-8');
      valueBuf = protoBytes(5, strBuf);
    } else {
      valueBuf = protoFloat64(2, value);
    }
    paramEntries.push(protoBytes(5, Buffer.concat([
      protoBytes(1, nameBuf),
      protoBytes(2, valueBuf),
    ])));
  }

  // Build F2.F21 OFX container
  const ofxContainer = protoBytes(21, Buffer.concat([
    protoVarint(1, 0x4F4659),  // "OFY" marker
    protoBytes(2, Buffer.from(pluginId, 'utf-8')),
    protoBytes(3, Buffer.from(instanceId, 'utf-8')),
    protoVarint(4, 1),          // enabled
    ...paramEntries,
  ]));

  // Build tool list entries
  const entries = [
    // Standard node marker
    protoBytes(1, Buffer.concat([
      protoVarint(1, 0xC0000001),
      protoBytes(2, protoVarint(2, 2)),
    ])),
    // Plugin ID
    protoBytes(1, Buffer.concat([
      protoVarint(1, ID_PLUGIN),
      protoBytes(2, protoBytes(5, Buffer.from(pluginId, 'utf-8'))),
    ])),
    // Instance ID
    protoBytes(1, Buffer.concat([
      protoVarint(1, ID_INSTANCE),
      protoBytes(2, protoBytes(5, Buffer.from(instanceId, 'utf-8'))),
    ])),
    // Enable flag (native captures carry 0 here for enabled plugins)
    protoBytes(1, Buffer.concat([
      protoVarint(1, ID_ENABLE),
      protoBytes(2, protoVarint(4, 0)),
    ])),
    // OFX container with params
    protoBytes(1, Buffer.concat([
      protoVarint(1, ID_CONTAINER),
      protoBytes(2, ofxContainer),
    ])),
    // End marker
    protoBytes(1, Buffer.concat([
      protoVarint(1, ID_END),
      protoBytes(2, protoVarint(4, 0)),
    ])),
  ];

  return protoBytes(10, Buffer.concat(entries));
}

/**
 * Known ResolveFX plugin IDs and their parameter names.
 * Populated from OFX calibration autoresearch data.
 */
const RESOLVEFX_PLUGINS = {
  filmGrain: {
    pluginId: 'com.blackmagicdesign.resolvefx.filmgrain',
    params: {
      grainMean: 'GrainMean',       // 0.0-1.0, default ~0.482
      grainSize: 'GrainSize',       // 0.0-1.0, default ~0.5
      grainSkew: 'GrainSkew',       // 0.0-1.0, default 0.5
      grainStrength: 'GrainStrength', // 0.0-1.0, default ~0.149
      textureness: 'Textureness',    // 0.0-1.0, default ~0.704
      saturation: 'saturation',      // 0.0-1.0, default 0.0
      softness: 'softness',          // 0.0-1.0, default ~0.298
    },
  },
  // Add more plugins as they're calibrated
};

// CR3: Import CDL exporter for re-export
const cdlExporter = require('./cdl-exporter');

module.exports = {
  generateDRX,
  generateDRXBody,
  generateProtobuf,
  generateMultiNodeDRX,
  // DRX Audit Trail System
  generateDeltaDRX,
  computeDrxHash,
  parseAdjustments,
  parseAdjustmentsToNodes,
  createNode,
  createConnection,
  createResolution,
  buildPrimaryCorrectorParams,
  buildContrastCorrectorParams,
  buildCorrectorBlock,
  // PNT1: Parallel node support
  createParallelNodes,
  // PNT2: Layer mixer support
  createLayerMixer,
  // PNT3: Outside node support
  createOutsideNode,
  // Helper for professional node structures
  createNeutralNodeParams,
  // CR3: CDL export functionality
  ...cdlExporter,
  // Stub encoding functions (awaiting DRX training)
  buildHDRWheelParams,
  buildHueCorrectorParams,
  buildLumMixCorrectorParams,
  buildSatVsSatCorrectorParams,
  buildQualifierParams,
  buildRGBQualifierParams,
  buildLumaQualifierParams,
  buildWindowParams,
  buildCustomCurveParams,
  buildHSLCurveParams,
  hasSecondaryCorrections,
  isParamIdAvailable,
  // OFX / ResolveFX
  buildResolveFXParams,
  buildOFXToolEntry,
  RESOLVEFX_PLUGINS,
  // Validation
  validateDRXBody,
  // Constants
  PARAM_IDS,
  CORRECTOR_TYPES,
  NEUTRAL_GRADE,
};
