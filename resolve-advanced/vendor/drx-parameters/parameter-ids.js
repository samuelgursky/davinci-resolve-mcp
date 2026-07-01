/**
 * DRX Parameter ID Definitions
 *
 * Complete mapping of parameter IDs used in DaVinci Resolve's DRX format.
 * Includes all known parameters from parser, generator, and analyzer tools.
 *
 * Parameter ID Ranges:
 * - 0x06xxxxxx (100663296+): Primary corrector params
 * - 0x083xxxxx (137363456+): Contrast corrector params
 * - 0x085xxxxx (139460608+): Hue corrector params
 * - 0x08D0xxxx (147849216+): Luma vs Saturation params
 * - 0x08F0xxxx (149946368+): Saturation vs Saturation params
 * - 0x0C3xxxxx (204472320+): Curves/HDR zone params
 * - Negative IDs (0x860xxxxx): Temperature, Tint, Log wheels
 *
 * @module drx-parameters/parameter-ids
 */

// ============================================================================
// PRIMARY CORRECTOR (Type 1) - Color Wheels
// ============================================================================

/**
 * Lift (Shadows) - 4 parameters
 * Range: -1.0 to +1.0, Default: 0.0
 */
const LIFT = {
  R: 100663320,      // 0x6000018
  G: 100663321,      // 0x6000019
  B: 100663322,      // 0x600001a
  MASTER: 100663323, // 0x600001b
};

/**
 * Gain (Highlights) - 4 parameters
 * Range: 0.0 to 4.0, Default: 1.0
 */
const GAIN = {
  R: 100663325,      // 0x600001d
  G: 100663326,      // 0x600001e
  B: 100663327,      // 0x600001f
  MASTER: 100663328, // 0x6000020
};

/**
 * Gamma (Midtones) - 4 parameters
 * Range: -1.0 to +1.0, Default: 0.0
 */
const GAMMA = {
  R: 100663330,      // 0x6000022
  G: 100663331,      // 0x6000023
  B: 100663332,      // 0x6000024
  MASTER: 100663333, // 0x6000025
};

/**
 * Offset - 3 parameters (no master)
 * Range: -1.0 to +1.0, Default: 0.0
 */
const OFFSET = {
  R: 100663421,      // 0x600007d
  G: 100663422,      // 0x600007e
  B: 100663423,      // 0x600007f
};

/**
 * Saturation - Primary corrector saturation
 * Range: 0.0 to 4.0, Default: 1.0
 */
const SATURATION = {
  PRIMARY: 100663301,    // 0x6000005 - Main saturation
  LEGACY: 100663300,     // 0x6000004 - Legacy/alt ID (may also be Hue Rotate — needs confirmation)
};

// ============================================================================
// RGB MIXER (Primary Corrector, Type 1)
// ============================================================================

/**
 * RGB Mixer - 3x3 color channel mixing matrix
 * Encoded as 9 float params in the Primary corrector (0x860000a7–0x860000af)
 *
 * Matrix layout (row = output channel, column = input channel):
 *   R_out = RR*R + GR*G + BR*B
 *   G_out = RG*R + GG*G + BG*B
 *   B_out = RB*R + GB*G + BB*B
 *
 * Default (identity): diagonal = 1.0, off-diagonal = 0.0
 * Range: 0.0 to 2.0 per cell (typical)
 *
 * TRAINED 2026-03-17 from rgbmixer_1.1.2.drx:
 *   0.8 diagonal + 0.1 off-diagonal → desaturated cross-channel blend
 */
const RGB_MIXER = {
  RR: 2248147111,  // 0x860000a7 - Red → Red output
  GR: 2248147112,  // 0x860000a8 - Green → Red output
  BR: 2248147113,  // 0x860000a9 - Blue → Red output
  RG: 2248147114,  // 0x860000aa - Red → Green output
  GG: 2248147115,  // 0x860000ab - Green → Green output
  BG: 2248147116,  // 0x860000ac - Blue → Green output
  RB: 2248147117,  // 0x860000ad - Red → Blue output
  GB: 2248147118,  // 0x860000ae - Green → Blue output
  BB: 2248147119,  // 0x860000af - Blue → Blue output

  // Toggle
  PRESERVE_LUMINANCE: 2248147132, // 0x860000bc - Preserve Luminance (0=off, nested {F2:0})
};

// ============================================================================
// CUSTOM CURVES - YRGB (Primary Corrector, Type 1)
// ============================================================================

/**
 * Custom Curves (YRGB) - Bézier/spline curve adjustment
 *
 * Two param groups per channel:
 * 1. Metadata params (0x860000bb–0x860000bf): nested {F2: pointCount} — number of control points
 * 2. Spline data params (0x86000506–0x86000509): nested {F8: {F1[]: point data}} — actual curve points
 *
 * Spline point encoding: each F1 entry contains F1 (x, fixed32) and F5 (y, fixed32)
 * x,y range: 0.0 to 1.0 (normalized), with endpoints at (0,0) and (1,1) for identity
 *
 * TRAINED 2026-03-17 from curves_yrgb_splines_1.1.2.drx and curve_y_scurve_1.1.2.drx
 */
const CUSTOM_CURVES = {
  // Metadata (control point count per channel)
  Y_META:  2248147131,  // 0x860000bb - Y (luma) curve point count
  // 0x860000bc is RGB Mixer Preserve Luminance (see above)
  R_META:  2248147133,  // 0x860000bd - Red curve point count
  G_META:  2248147134,  // 0x860000be - Green curve point count
  B_META:  2248147135,  // 0x860000bf - Blue curve point count

  // Spline data (actual curve points as nested protobuf)
  Y_SPLINE: 2248148230,  // 0x86000506 - Y (luma) curve spline data
  R_SPLINE: 2248148231,  // 0x86000507 - Red curve spline data
  G_SPLINE: 2248148232,  // 0x86000508 - Green curve spline data
  B_SPLINE: 2248148233,  // 0x86000509 - Blue curve spline data
};

// ============================================================================
// HSL CURVES (Primary Corrector, Type 1)
// ============================================================================

/**
 * HSL Curves — Hue/Saturation/Luminance vs Hue/Saturation/Luminance curves
 *
 * Each curve type has:
 * 1. A metadata param (varies per type) — nested {F2: value}
 * 2. A common metadata flag (0x860000cf) — nested {F2: 2} (always 2 when any HSL curve active)
 * 3. A spline data param (0x86000400–0x86000405) — nested {F8: point data}
 *
 * TRAINED 2026-03-17 from hue_vs_hue, hue_vs_sat, hue_vs_lum, lum_vs_sat, sat_vs_sat, sat_vs_lum
 */
const HSL_CURVES = {
  // Common metadata flag (present whenever any HSL curve is active)
  COMMON_FLAG: 2248147151,  // 0x860000cf - {F2: 2}

  // Per-curve metadata params
  HUE_VS_HUE_META:  2248147127,  // 0x860000b7 - Hue vs Hue metadata
  HUE_VS_SAT_META:  2248147128,  // 0x860000b8 - Hue vs Saturation metadata
  HUE_VS_LUM_META:  2248147129,  // 0x860000b9 - Hue vs Luminance metadata
  LUM_VS_SAT_META:  2248147130,  // 0x860000ba - Luminance vs Saturation metadata
  SAT_VS_SAT_META:  2248147203,  // 0x86000103 - Saturation vs Saturation metadata
  SAT_VS_LUM_META:  2248147458,  // 0x86000202 - Saturation vs Luminance metadata

  // Additional metadata for Hue vs Lum
  HUE_VS_LUM_EXTRA: 2248147224,  // 0x86000118 - Extra metadata for Hue vs Lum

  // Spline data params (actual curve points)
  HUE_VS_HUE_SPLINE: 2248147968,  // 0x86000400
  HUE_VS_SAT_SPLINE: 2248147969,  // 0x86000401
  HUE_VS_LUM_SPLINE: 2248147970,  // 0x86000402
  LUM_VS_SAT_SPLINE: 2248147971,  // 0x86000403
  SAT_VS_SAT_SPLINE: 2248147972,  // 0x86000404
  SAT_VS_LUM_SPLINE: 2248147973,  // 0x86000405
};

// ============================================================================
// ADDITIONAL PRIMARY CONTROLS
// ============================================================================

/**
 * Additional controls discovered from training samples
 *
 * TRAINED 2026-03-17 from highlights_50, shadows_50, lummix_50 DRX captures
 */
const ADDITIONAL = {
  LUM_MIX_SLIDER: 2248146955,  // 0x8600000b - Luminosity Mix (UI 0-100 → stored /100, default 100→1.0). CORRECTED 2026-06-22 (harness, §16a): value was 2248147083=0x8600008b — a typo vs its own comment; Lum Mix decoded as unknown_ until live-measured.
  HIGHLIGHTS: 2248147216,      // 0x86000110 - Highlights slider (direct value, e.g., 50)
  SHADOWS: 2248147217,         // 0x86000111 - Shadows slider (direct value, e.g., 50)
};

// ============================================================================
// TEMPERATURE & TINT (Negative ID Encoding)
// ============================================================================

/**
 * Temperature, Tint, and related parameters
 * Uses unsigned representation of negative IDs
 *
 * Value scaling (from DRX analysis 2026-01-14):
 * - Temperature: Relative offset -4000 to +4000 (NOT Kelvin, warm/cool shift)
 * - Tint: Direct value (e.g., +50, -50)
 * - Midtone Detail: Direct value (e.g., +50, -50)
 * - Color Boost: Direct value 0-100
 * - Contrast (Log): Normalized float, 1.0 = 100%
 */
const TEMP_TINT = {
  TEMPERATURE: 2248147221,    // 0x86000115 - Relative offset -4000 to +4000
  TINT: 2248147222,           // 0x86000116 - Direct value
  MIDTONE_DETAIL: 2248147219, // 0x86000113 - Direct value
  COLOR_BOOST: 2248147218,    // 0x86000112 - Range 0-100 (was SATURATION_ALT)
  CONTRAST: 2248147137,       // 0x860000c1 - Normalized float, 1.0 = 100% (NEW - from DRX analysis)
};

// ============================================================================
// CONTRAST / PIVOT / LOG RANGE (Primary Corrector, Type 1)
// ============================================================================

/**
 * Contrast and Pivot — in the shared controls range (0x860000C0-CC)
 * NOT in the 0x0830xxxx range (those are qualifier params, see below)
 *
 * CORRECTED 2026-03-16: The old CONTRAST block (0x0830xxxx) was a misidentification
 * of HSL Qualifier parameters. Real contrast/pivot live in the shared controls range.
 */
const CONTRAST = {
  CONTRAST: 2248147137,     // 0x860000C1 — normalized float, 1.0 = unity
  PIVOT: 2248147136,        // 0x860000C0 — direct float, default 0.435
  LOW_RANGE: 2248147147,    // 0x860000CB — direct float, default 0.333
  HIGH_RANGE: 2248147148,   // 0x860000CC — INVERTED: DRX = 1.0 - UI
};

// ============================================================================
// LOG WHEELS MODE (Negative ID Encoding)
// ============================================================================

/**
 * Log wheels mode parameters (alternative to Lift/Gamma/Gain)
 * Uses unsigned representation of negative IDs
 *
 * CORRECTED 2026-01-14: Based on DRX sample analysis, the correct mapping is:
 * - Shadow (Low): 0x860000c2-c4 (sequential R, G, B)
 * - Midtone (Mid): 0x860000c5-c7 (sequential R, G, B)
 * - Highlight (High): 0x860000c8-ca (sequential R, G, B)
 */
const LOG_WHEELS = {
  // Shadow (Low) - 0x860000c2-c4
  SHADOW_R: 2248147138,     // 0x860000c2
  SHADOW_G: 2248147139,     // 0x860000c3
  SHADOW_B: 2248147140,     // 0x860000c4

  // Midtone (Mid) - 0x860000c5-c7
  MIDTONE_R: 2248147141,    // 0x860000c5
  MIDTONE_G: 2248147142,    // 0x860000c6
  MIDTONE_B: 2248147143,    // 0x860000c7

  // Highlight (High) - 0x860000c8-ca (NEW - previously unknown)
  HIGHLIGHT_R: 2248147144,  // 0x860000c8
  HIGHLIGHT_G: 2248147145,  // 0x860000c9
  HIGHLIGHT_B: 2248147146,  // 0x860000ca
};

// ============================================================================
// HUE / SATURATION (Primary Corrector, Type 1)
// ============================================================================

/**
 * Hue Rotate and Saturation — in the primary corrector range (0x06000004-05)
 *
 * NOTE: The old HUE block (0x0850xxxx) was a misidentification of Power Window params.
 * Real Hue Rotate is at 0x06000004 (SATURATION.LEGACY), real Saturation at 0x06000005.
 */
const HUE = {
  HUE_ROTATE: 100663300,   // 0x06000004 — DRX = (UI - 50) / 50 (UI 50 = no rotation)
  SATURATION: 100663301,    // 0x06000005 — DRX = UI / 50 (UI 50 = unity = 1.0)
};

// ============================================================================
// LUMA VS SATURATION (Type 5)
// ============================================================================

/**
 * Luma vs Saturation curve parameters
 */
const LUM_MIX = {
  PARAM_1: 147849218,
  PARAM_2: 147849220,
  PARAM_3: 147849222,
  PARAM_4: 147849223,
  PARAM_5: 147849224,
  PARAM_6: 147849225,
  PARAM_7: 147849226,
  PARAM_8: 147849227,
  PARAM_9: 147849228,
  PARAM_10: 147849232,
  PARAM_11: 147849233,
};

// ============================================================================
// SATURATION VS SATURATION (Type 3)
// ============================================================================

/**
 * Saturation vs Saturation curve parameters
 */
const SAT_VS_SAT = {
  PARAM_1: 149946369,
  PARAM_2: 149946371,
  PARAM_3: 149946373,
  PARAM_4: 149946374,
  PARAM_5: 149946377,
  PARAM_6: 149946378,
  PARAM_7: 149946379,
};

// ============================================================================
// HDR ZONE CORRECTOR (Type 9)
// ============================================================================

/**
 * HDR Zone corrector parameters
 *
 * IMPORTANT: HDR Zones use NESTED PROTOBUF structure - unlike standard parameters,
 * zone differentiation is done via embedded zone name strings, not separate IDs.
 *
 * Zone names (embedded strings):
 * - "Dark"      -> Shadows zone (0-20% luminance)
 * - "Shadow"    -> Lower midtones (20-40%)
 * - "Light"     -> Upper midtones (60-80%)
 * - "Highlight" -> Specular zone (80-100%) - NOTE: DRX uses "Highlight" not "Specular"
 * - "Global"    -> Affects entire image
 *
 * Inner field wire types (within nested structure):
 * - 0x0a <len>: Zone name string
 * - 0x15 <f32>: Exposure value (-6.0 to +6.0, default 0)
 * - 0x3d <f32>: Saturation value (0.0 to 4.0, default 1.0)
 * - 0x1d <f32> 0x25 <f32>: Hue rotation (angle, sat modifier)
 *
 * TRAINED 2026-01-14 from 13 HDR DRX samples
 */
const HDR_ZONE = {
  // Global HDR controls
  BLACK_OFFSET: 0x86000303,   // 2248147715 - Global black offset (float, default 0.0)

  // Zone container IDs
  ZONE_ADJUSTMENTS: 0x86000305, // 2248147717 - Per-zone adjustments (exposure, color balance, saturation)
  ZONE_DEFINITIONS: 0x86000306, // 2248147718 - Per-zone definitions (range boundaries, falloff)
  ZONE_METADATA: 0x86000309,   // 2248147721 - Zone count metadata

  // Legacy aliases
  ZONE_DATA: 0x86000305,      // Alias for ZONE_ADJUSTMENTS (backwards compat)

  // Legacy/unknown HDR parameter (from original analysis)
  PARAM_1: 0x0c30001b,        // 204472347 - Purpose TBD

  // Inner field wire type constants for ZONE_ADJUSTMENTS (0x86000305)
  WIRE: {
    ZONE_NAME: 0x0a,          // F1: Length-delimited string
    EXPOSURE: 0x15,           // F2: Fixed32 float (-6.0 to +6.0)
    COLOR_BALANCE_Y: 0x1d,    // F3: Fixed32 float (default 0.0)
    COLOR_BALANCE_X: 0x25,    // F4: Fixed32 float (default 0.0)
    SATURATION: 0x3d,         // F7: Fixed32 float (0.0 to 4.0)
  },

  // Inner field wire type constants for ZONE_DEFINITIONS (0x86000306)
  WIRE_DEF: {
    ZONE_NAME: 0x0a,          // F1: Length-delimited string
    RANGE_1: 0x15,            // F2: Fixed32 float (range boundary in stops)
    RANGE_2: 0x1d,            // F3: Fixed32 float (range boundary 2 in stops)
    BASE_FALLOFF: 0x25,       // F4: Fixed32 float (factory default falloff, immutable)
    FALLOFF: 0x2d,            // F5: Fixed32 float (active zone falloff, user-set)
  },

  // Zone name strings (for matching/generating)
  ZONE_NAMES: {
    BLACK: 'Black',
    DARK: 'Dark',
    SHADOW: 'Shadow',
    LIGHT: 'Light',
    HIGHLIGHT: 'Highlight',
    SPECULAR: 'Specular',
    GLOBAL: 'Global',
  },

  // Default falloff values per zone (from calibration 2026-03-16)
  // Symmetric: Black/Specular=0.10, Dark/Highlight=0.20, Shadow/Light=0.22
  DEFAULT_FALLOFFS: {
    Black: 0.10,
    Dark: 0.20,
    Shadow: 0.22,
    Light: 0.22,
    Highlight: 0.20,
    Specular: 0.10,
    // Global has no falloff control
  },

  // Value ranges
  RANGES: {
    exposure: { min: -6.0, max: 6.0, default: 0.0 },
    saturation: { min: 0.0, max: 4.0, default: 1.0 },
    colorBalanceX: { min: -1.0, max: 1.0, default: 0.0 },
    colorBalanceY: { min: -1.0, max: 1.0, default: 0.0 },
    blackOffset: { min: -1.0, max: 1.0, default: 0.0 },
    falloff: { min: 0.0, max: 2.0, default: 0.2 },
  },
};

// ============================================================================
// HSL QUALIFIER (Secondary Correction)
// ============================================================================

/**
 * Qualifier parameters for secondary color correction (0x0830xxxx range)
 *
 * ALL qualifier types (HSL, RGB, Luma, 3D) share the same param ID range.
 * The qualifier mode selector (0x88300001) determines which type is active.
 * Field meaning changes based on mode.
 *
 * TRAINED 2026-03-16: All IDs confirmed via live Resolve DRX export + protobuf diff.
 * Scale: DRX = UI / 100 for all percentage-based params.
 */
const HSL_QUALIFIER = {
  // Mode selector — determines which qualifier type is active
  QUALIFIER_MODE: 2284847105,  // 0x88300001 — 0=HSL (default/absent), 2=RGB, 4=Luma, 6=3D

  // === HSL MODE (0x88300001 = 0 or absent) ===
  // Hue selection
  HUE_CENTER:     137363470,   // 0x0830000E — DRX = UI / 100
  HUE_WIDTH:      137363471,   // 0x0830000F — DRX = UI / 100
  HUE_SYM:        137363472,   // 0x08300010 — DRX = UI / 100
  HUE_SOFT:       137363473,   // 0x08300011 — DRX = UI / 100

  // Saturation selection
  SAT_HIGH:       137363474,   // 0x08300012 — DRX = UI / 100
  SAT_LOW:        137363475,   // 0x08300013 — DRX = UI / 100
  SAT_HIGH_SOFT:  137363476,   // 0x08300014 — DRX = UI / 100
  SAT_LOW_SOFT:   137363477,   // 0x08300015 — DRX = UI / 100

  // Luminance selection
  LUM_HIGH:       137363478,   // 0x08300016 — DRX = UI / 100
  LUM_LOW:        137363479,   // 0x08300017 — DRX = UI / 100
  LUM_HIGH_SOFT:  137363480,   // 0x08300018 — DRX = UI / 100
  LUM_LOW_SOFT:   137363481,   // 0x08300019 — DRX = UI / 100

  // Additional HSL qualifier params
  HUE_WIDTH_DUP:  137363493,   // 0x08300025 — possible duplicate/linked param
  HUE_SOFT_DUP:   137363494,   // 0x08300026 — possible duplicate/linked param
  MODE_FLAG:      137363567,   // 0x0830006F — varint=4 (internal mode indicator)

  // === RGB MODE (0x88300001 = 2) ===
  // Uses 0x08300002–0x0830000D for per-channel ranges. Scale: DRX = UI / 100.
  // ⚠ FIELD ORDER CORRECTED 2026-06-22 (harness §16a, live RGB sweep on DRX_CALIB). The prior
  // "TRAINED 2026-03-16" layout [Low, High, LowSoft, HighSoft] was WRONG — both order and pairing.
  // Live (Red Low 12/High 88/LSoft 5/HSoft 7 → 0x04 0.12 / 0x02 0.88 / 0x05 0.05 / 0x03 0.07) proves the
  // real per-channel layout is [High, HighSoft, Low, LowSoft] from the base id. Const NAMES kept (so the
  // generator's q.rLow/rHigh API stays correct); only the id VALUES are re-pointed to the right fields.
  RGB_R_HIGH:     137363458,   // 0x08300002 — Red High
  RGB_R_HIGH_SOFT:137363459,   // 0x08300003 — Red High Soft
  RGB_R_LOW:      137363460,   // 0x08300004 — Red Low
  RGB_R_LOW_SOFT: 137363461,   // 0x08300005 — Red Low Soft
  RGB_G_HIGH:     137363462,   // 0x08300006 — Green High
  RGB_G_HIGH_SOFT:137363463,   // 0x08300007 — Green High Soft
  RGB_G_LOW:      137363464,   // 0x08300008 — Green Low
  RGB_G_LOW_SOFT: 137363465,   // 0x08300009 — Green Low Soft
  RGB_B_HIGH:     137363466,   // 0x0830000A — Blue High
  RGB_B_HIGH_SOFT:137363467,   // 0x0830000B — Blue High Soft
  RGB_B_LOW:      137363468,   // 0x0830000C — Blue Low
  RGB_B_LOW_SOFT: 137363469,   // 0x0830000D — Blue Low Soft

  // === 3D MODE (0x88300001 = 6) === VALIDATED LIVE 2026-06-22 (harness §16a): drew a 3D key stroke +
  // set Despill 35 → these six params serialized. Volume/extra/cspace ids confirmed present (nested blobs).
  QUALIFIER_3D_VOLUME: 137363498,  // 0x0830002A — nested blob (3D selection volume)
  QUALIFIER_3D_EXTRA:  2284847150, // 0x8830002E — nested blob (additional 3D data)
  QUALIFIER_3D_CSPACE: 2284847152, // 0x88300030 — color-space container (YUV)
  QUALIFIER_3D_EXTRA2: 2284847154, // 0x88300032 — nested blob (additional 3D data, NEW 2026-06-22)
  // ⚠ DESPILL ID CORRECTED 2026-06-22: registry had 0x08300033 (137363507); live measurement shows the
  // real id is 0x88300033 (2284847155), Despill 35 → stored 0.35 (scale /100).
  QUALIFIER_3D_DESPILL:2284847155, // 0x88300033 — float despill (scale /100)

  // Qualifier output — shared across all qualifier modes
  // CORRECTED 2026-06-22 (harness §16a): value was 2248146001 — a typo vs its own hex comment
  // (0x86000051 = 2248147025, off by 0x400). Blur Radius decoded as unknown_ until live-measured
  // on the DRX_CALIB bars rig: UI 46 → stored 0.46 at 0x86000051, scale /100.
  BLUR_RADIUS:    2248147025,  // 0x86000051 — in corrector type 1, scale /100
  // Matte finesse params are in the MATTE_FINESSE block (corrector type 9)
};

// ============================================================================
// MATTE FINESSE (Corrector Type 9, 0x0C30xxxx range)
// ============================================================================

/**
 * Matte Finesse parameters — qualifier output cleanup controls
 *
 * Applied after qualifier selection to refine the matte/key signal.
 * All scale: DRX = UI / 100
 *
 * TRAINED 2026-03-16: All IDs confirmed.
 */
const MATTE_FINESSE = {
  // CORRECTED 2026-03-22: Names were swapped in March 16 calibration.
  // Verified empirically: Denoise=15 → 0x0C300020=0.15, CleanBlack=30 → 0x0C300024=0.30
  DENOISE:      204472352,   // 0x0C300020 — was incorrectly labeled CLEAN_BLACK
  BLACK_CLIP:   204472353,   // 0x0C300021
  WHITE_CLIP:   204472354,   // 0x0C300022
  IN_OUT_RATIO: 204472355,   // 0x0C300023
  CLEAN_BLACK:  204472356,   // 0x0C300024 — was incorrectly labeled CLEAN_WHITE
  CLEAN_WHITE:  204472357,   // 0x0C300025 — was incorrectly labeled DENOISE
  MORPH_RADIUS: 204472368,   // 0x0C300030
  PRE_FILTER:   204472369,   // 0x0C300031
  POST_FILTER:  204472370,   // 0x0C300032
  SHADOW:       204472371,   // 0x0C300033
  MIDTONE:      204472372,   // 0x0C300034
  HIGHLIGHT:    204472373,   // 0x0C300035
};

// ============================================================================
// POWER WINDOWS (Spatial Correction)
// ============================================================================

/**
 * Power Window parameters for spatial grading (0x0850xxxx / 0x8850xxxx range)
 *
 * Corrector Type 4. Window types: 1=Circular, 2=Linear, 3=Polygon, 4=Curve, 5=Gradient
 *
 * TRAINED 2026-03-16: Position/size/type confirmed. Softness partially mapped.
 * Softness uses corrector type 3 (0x0870xxxx) auto-generated alongside window.
 */
const POWER_WINDOWS = {
  // Transform controls
  ROTATE:       139460609,   // 0x08500001 — rotation; scale CONFIRMED 2026-06-22 (multi-point): stored = −UI°/180 (neutral 0; UI 27→-0.15, 49→-0.2722). The "direct degrees" note was WRONG.
  // ⚠ SIZE/ASPECT IDS WERE SWAPPED — corrected 2026-06-22 via isolated multi-point fit (vary one, hold the
  // other neutral). 0x08500004 is ASPECT = (50−UI)/50 (neutral 0); 0x08500006 is SIZE = 1+(UI−50)×0.08 (neutral 1.0).
  ASPECT:       139460612,   // 0x08500004 — aspect, scale (50−UI)/50, neutral 0
  SOFT_REF:     139460613,   // 0x08500005 — pixel reference = Soft1 × 16 (CONFIRMED 2026-06-22: Soft1 67 → 1072)
  SIZE:         139460614,   // 0x08500006 — size, scale 1+(UI−50)×0.08, neutral 1.0
  PAN:          139460619,   // 0x0850000B — pixel offset from center (horizontal)
  TILT:         139460620,   // 0x0850000C — pixel offset from center (vertical)
  OPACITY:      139460626,   // 0x08500012 — window opacity, scale /100 (UI 66 → 0.66). ADDED 2026-06-22 (harness §16a) — was unwired (decoded unknown_).

  // Type selector
  WINDOW_TYPE:  2286944264,  // 0x88500008 — varint: 1=Circular, 2=Linear, 3=Polygon, 4=Curve, 5=Gradient
  REF_WIDTH:    2286944269,  // 0x8850000D — reference dimension (288.0 typical)

  // Unknown positional params (observed but not yet mapped)
  UNK_0E:       2286944270,  // 0x8850000E — 0.0
  UNK_0F:       2286944271,  // 0x8850000F — 0.0
  TRACKING_BLOB:2286944272,  // 0x88500010 — blob (tracking keyframe data)

  // Softness mask shape — LINEAR/CURVE windows. CORRECTOR TYPE 3 (VALIDATED LIVE 2026-06-22 on DRX_CALIB:
  // dumped corrector.F1 directly = 3; the prior "type 65539 = 0x10003" claim is WRONG/version-stale).
  // SOFT_1–4 scale: UI × 16 — RE-CONFIRMED LIVE 2026-06-22 with asymmetric softness (4.50/6.25/8.75/11.00
  // → 72/100/140/176, all ÷16 exact). PAN/TILT/WIDTH/HEIGHT observed at defaults (0/0/1/1); BBOX = nested blob.
  SOFT_1: 141557769,         // 0x08700009 — Soft 1 (also used by circle via SoftRef)
  SOFT_2: 141557770,         // 0x0870000A — Soft 2
  SOFT_3: 141557771,         // 0x0870000B — Soft 3
  SOFT_4: 141557772,         // 0x0870000C — Soft 4
  SOFT_BBOX: 141557780,      // 0x08700014 — vertex/bbox data blob (4 corners of linear window)
  SOFT_PAN: 141557781,       // 0x08700015 — Pan offset within softness mask (0.0)
  SOFT_TILT: 141557782,      // 0x08700016 — Tilt offset (0.0)
  SOFT_WIDTH: 141557783,     // 0x08700017 — Width scale (1.0)
  SOFT_HEIGHT: 141557784,    // 0x08700018 — Height scale (1.0)
  SOFT_UNK_1: 141557788,    // 0x0870001C — unknown (0.0)
  SOFT_UNK_2: 141557789,    // 0x0870001D — unknown (0.0)
  // Structural containers on the same ct3 corrector (RE'd live 2026-06-22):
  SOFT_STRUCT_0F: 2289041423, // 0x8870000F — nested {F2} default container
  SOFT_STRUCT_12: 2289041426, // 0x88700012 — varint (default 0)
  SOFT_MATRIX:    2289041438, // 0x8870001E — structural 3×3 matrix (identity default), decoded by decodeStructMatrix
};

// ============================================================================
// NODE SIZING / INPUT SIZING (Corrector Type 10)
// ============================================================================

/**
 * Node "Input Sizing" transform — Pan/Tilt/Zoom/Width/Height/Rotate/Pitch/Yaw.
 *
 * REVERSE-ENGINEERED 2026-06-22 (harness §16a) on the DRX_CALIB SMPTE-bars compound clip.
 * Stored as CORRECTOR TYPE 10. Params live in F6.F2.F3[] as `1a`-tagged sub-messages, each
 * { F1: <key varint>, F2: { F1: <fixed32 float> } }. Two key groups (the varint encodes the
 * group): group A keys 0x10310001–06, group B keys 0x10B10001–02.
 *
 * Scales (live-measured): Zoom/Width/Height = direct multiplier (1.0 = neutral); Rotate = degrees;
 * Pan = UI px / frame width (71 → 0.03698 = 71/1920); Tilt = UI px / frame height (72 → 0.0667 = 72/1080);
 * Pitch/Yaw = direct (0.77/0.78).
 *
 * NOTE: the drx-parser does NOT yet surface corrector type 10, so these decode to nothing today.
 * Recorded here from the RE; needs a parser extension (extract ct10 + its 1a-entry params). See
 * the internal calibration program ledger (Node Sizing section).
 */
const NODE_SIZING = {
  WIDTH:  0x10310001,  // ZoomX / Width — direct multiplier
  HEIGHT: 0x10310002,  // ZoomY / Height — direct multiplier
  ZOOM:   0x10310003,  // Zoom — direct multiplier
  ROTATE: 0x10310004,  // Rotate — degrees
  PAN:    0x10310005,  // Pan — normalized: UI px / frame width (1920)
  TILT:   0x10310006,  // Tilt — normalized: UI px / frame height (1080)
  PITCH:  0x10B10001,  // Pitch — direct
  YAW:    0x10B10002,  // Yaw — direct
};

// ============================================================================
// POLYGON WINDOW (Corrector Type 5, 0x08B0xxxx range)
// ============================================================================

/**
 * Polygon window parameters — arbitrary vertex shapes
 *
 * DECODED 2026-03-23: Vertex array format fully reverse-engineered.
 *
 * Vertex array (0x08B00006) protobuf structure:
 *   N repeated sub-messages, one per vertex:
 *   Each: { F1 = X (float32), F2 = Y (float32) }
 *   Coordinates are pixels relative to frame center.
 *   Y axis: negative = top, positive = bottom.
 *
 * Default rectangle at Size=50 on 1920×1080:
 *   (-480,-270), (-480,270), (480,270), (480,-270)
 *   = ±(halfWidth×0.5), ±(halfHeight×0.5)
 */
const POLYGON_WINDOW = {
  SHAPE_TYPE:    145752066,  // 0x08B00002 — varint 2 (polygon shape type)
  VERTEX_MODE:   145752068,  // 0x08B00004 — varint 0
  VERTEX_ARRAY:  145752070,  // 0x08B00006 — N×12B vertex sub-msgs {F1=X, F2=Y} float32 pixels from center
  CLOSE_FLAG:    145752071,  // 0x08B00007 — varint 0 (closed shape flag?)
  FILL_FLAG_1:   145752072,  // 0x08B00008 — varint 0
  INSIDE_FILL:   145752073,  // 0x08B00009 — varint 1 (inside fill enabled)
  ENABLED:       145752074,  // 0x08B0000A — varint 1 (window enabled)
  UNK_0E:        145752078,  // 0x08B0000E — varint 0
  UNK_0F:        145752079,  // 0x08B0000F — varint 0
};

// ============================================================================
// GRADIENT WINDOW (Corrector Type 65554 = 0x10012, 0x08F0xxxx range)
// ============================================================================

/**
 * Gradient window parameters — different range than circle/linear windows
 *
 * TRAINED 2026-03-22: Softness scale is ×100 (not ×16 like circle/linear).
 * Uses corrector type 65554 (0x10000 + 18).
 */
const GRADIENT_WINDOW = {
  TYPE:          149946369,  // 0x08F00001 — varint 2 (gradient subtype)
  ROTATION:      149946371,  // 0x08F00003 — float (rotation; UI 83 → -0.461 on a moved gradient — odd scale, like power-window rotate)
  HANDLE_1_POS:  149946373,  // 0x08F00005 — float (handle 1 position, pixels; UI Pan 81 → 2539.52)
  HANDLE_2_POS:  149946374,  // 0x08F00006 — float (handle 2 position, pixels; UI Tilt 82 → 2621.44)
  OFFSET_X:      149946377,  // 0x08F00009 — float (horizontal offset, 0.0)
  OFFSET_Y:      149946378,  // 0x08F0000A — float (vertical offset, 0.0)
  SOFTNESS:      149946379,  // 0x08F0000B — float (softness × 100 — CONFIRMED 2026-06-22: Soft1 85 → 8500)
  OPACITY:       149946385,  // 0x08F00011 — float opacity, scale /100 (UI 84 → 0.84). ADDED 2026-06-22 (harness §16a) — was unwired.
  MATRIX:        2297430029, // 0x88F0000D — structural container: F10 = row-major 3×3 matrix (identity default). NAMED 2026-06-22 (completeness sweep; off the gradient-window fixture). Exact semantic role (color/orientation) unconfirmed.
  // ⚠ ID COLLISION: TYPE/ROTATION/HANDLE_1/2/OFFSET_X/Y/SOFTNESS share IDs with SAT_VS_SAT.PARAM_1–7
  // (both 0x08F000xx), distinguished ONLY by corrector type (gradient = 65554, sat-v-sat = 3). The flat
  // PARAM_ID_MAP is keyed by id alone, so it resolves these to satVsSat.* — gradient-window params
  // currently MISLABEL as satVsSat. Proper fix = corrector-type-aware naming (follow-up). 0x08F00011
  // (opacity) is collision-free, so it's mapped below.
};

// ============================================================================
// NODE LUT REF (per-node LUT attachment, 0x860000A0–A1)
// ============================================================================

/**
 * Per-node LUT references — when a Resolve color node has a LUT attached
 * via Right-click → LUT, the LUT path is stored as two parameters inside
 * a corrector block at the node level (NOT the corrector list — same
 * location in F9 the existing parser treats as a corrector, but the
 * params carry LUT data instead of grade controls).
 *
 * DECODED 2026-06-19 (P5.1, Session 31) from a paired DRX capture
 * (no-LUT vs with-LUT, same clip + node):
 *   - SLOT_META (0x860000A0): varint, value=6 in captured fixture.
 *     Likely encodes the LUT slot kind (node-LUT vs other). Value
 *     persists across LUT changes per fixture but exact taxonomy
 *     is queued for a follow-up multi-fixture capture.
 *   - LUT_PATH (0x860000A1): value envelope's F5 carries the LUT
 *     basename/path as a string. In the captured fixture it was the
 *     bare basename "FilmUnlimited_2383_Rec709_Finished.cube"; absolute
 *     paths likely also live here for custom (non-built-in) LUTs.
 *
 * Encoding scheme (value envelope F5 = string) differs from the
 * float/int envelopes used by grade controls. The decoder
 * `extract-lut-refs.js` reads F5 directly rather than going through
 * the standard parameter-codec int/float unwrap path.
 */
const NODE_LUT_REF = {
  SLOT_META: 2248147104,  // 0x860000A0 — varint (slot/kind code, e.g. 6)
  LUT_PATH:  2248147105,  // 0x860000A1 — string in F5 of value envelope (LUT path or basename)
};

// ============================================================================
// COLOR WARPER (Primary Corrector, Type 1, 0x86000120+ range)
// ============================================================================

/**
 * Color Warper parameters — chroma-warp PIN list (Primary corrector, ct1).
 *
 * RE-CALIBRATED LIVE 2026-06-22 on DRX_CALIB (Resolve 21, harness §16a). The prior
 * "DECODED 2026-03-23" mesh-vertex model (0x86000121: F1=ver/F2=config/F3=N×12B
 * float32 triplets, "5 vertices per moved point") is **WRONG for R21** — exactly the
 * kind of unverified registry claim the validation rule warns about (cf. the polygon
 * 0x08B0/ct5 claim, also wrong). A live chroma-warp move emits **none** of
 * 0x86000121/126/129/12C/12D/130; the entire 0x86000120+ scan turns up only
 * 0x86000133, 0x86000136, 0x86000137 and 0x86000138.
 *
 * R21 stores the Color Warper (Chroma Warp) as a list of **pins**, not a vertex mesh:
 *   0x86000133  MODE_FLAG    varint (observed 2)
 *   0x86000136  CONFIG_A     varint (observed 2 — was labeled COLOR_SPACE "HS mode")
 *   0x86000137  CONFIG_B     varint (observed 0/2)
 *   0x86000138  PINS         value envelope = { F2: { F27: { F1: [ <pin>, … ] } } }
 *
 * Each pin sub-message (validated identity-scale against the UI Pin controls):
 *   F1  varint  pin id/index (observed 1)
 *   F2  f32     source chroma X
 *   F3  f32     source chroma Y
 *   F4  f32     dest chroma X
 *   F5  f32     dest chroma Y
 *   F6  f32     Chroma Range       (UI "Chroma Range")
 *   F7  f32     Exposure           (UI "Exposure"; default 0 is NOT serialized)
 *   F8  f32     Tonal Range Low    (UI "Tonal Range Low")
 *   F9  f32     Tonal Range High   (UI "Tonal Range High")
 *   F10 f32     Tonal Range Pivot  (UI "Tonal Range Pivot")
 * F2–F5 are normalized chroma-plane coords (source→dest warp vector). Default-valued
 * fields are omitted (e.g. F7 only appears when Exposure≠0). Lifted into named
 * `colorWarper.pin<N>.<field>` params + `node.params.colorWarper` by decodeColorWarperPins.
 * Luma Warp (the palette's second mode) is a parallel pin list — UI-gated, not yet swept.
 */
const COLOR_WARPER = {
  MODE_FLAG: 2248147251,  // 0x86000133 — varint warper mode (observed 2)
  CONFIG_A:  2248147254,  // 0x86000136 — varint config (observed 2)
  CONFIG_B:  2248147255,  // 0x86000137 — varint config (observed 0/2)
  PINS:      2248147256,  // 0x86000138 — pin list: F2.F27.F1[] (see block comment)
};

// ============================================================================
// COLORSLICE (OFX Tool 0xC00000DC, 0x86000600+ range)
// ============================================================================

/**
 * ColorSlice parameters — global controls + per-vector color adjustment grid
 *
 * TRAINED 2026-03-16: Confirmed IN DRX (manual study was wrong).
 * Uses OFX tool container + dedicated param IDs.
 *
 * DECODED 2026-03-23: Per-vector format fully reverse-engineered.
 *
 * CALIBRATED 2026-06-22 (automated harness, design note §16a): the 6 GLOBAL controls
 * at 0x86000600–0x86000605 were previously MISSED (the range was thought to start at
 * 0x86000606). Measured live by setting each UI field to known values on the Color
 * page and reading back the encoded value from Project.db. Scales: identity for all
 * except Hue, which is NEGATED (UI +X → stored −X), consistent with the per-vector
 * note below. Sat default 1.0 (range up to 2.0); others default 0.0.
 *
 * Grid blob (0x86000606) stored in protobuf F24:
 *   7 repeated sub-messages, one per color vector:
 *   Order: Red, Skin, Yellow, Green, Cyan, Blue, Magenta
 *   Each: F1=enabled(varint), F3=sat(float32), F4=hue(float32, optional, absent=0)
 *
 * Sat default = 1.0, Hue default = 0.0 (absent). Hue stored as negative of UI value.
 */
const COLORSLICE = {
  // Global controls (0x86000600–605) — CALIBRATED 2026-06-22.
  DENSITY:      2248148480,  // 0x86000600 — "Den"          (identity)
  DENSITY_DEPTH:2248148481,  // 0x86000601 — "Den.Depth"    (identity)
  SAT:          2248148482,  // 0x86000602 — "Sat"          (identity, default 1.0, max 2.0)
  SAT_BALANCE:  2248148483,  // 0x86000603 — "Sat.Balance"  (identity)
  SAT_DEPTH:    2248148484,  // 0x86000604 — "Sat.Depth"    (identity)
  HUE:          2248148485,  // 0x86000605 — "Hue"          (NEGATED: UI +X → stored −X)
  // Per-vector grid (0x86000606+) — structure documented above.
  VECTOR_DATA:  2248148486,  // 0x86000606 — 7 per-vector sub-msgs (Red,Skin,Yel,Grn,Cyn,Blu,Mag)
  GRID_DATA_2:  2248148487,  // 0x86000607 — additional grid data
  OFX_TOOL_ID:  0xC00000DC,  // OFX tool type ID when ColorSlice is active
};

// ============================================================================
// RESOLVEFX / OFX PLUGIN ENCODING (F7.F10 container)
// ============================================================================

/**
 * ResolveFX plugin parameters — stored in node tool list F7.F10
 *
 * NOT in corrector chain. Uses OFX string-named parameters, not integer IDs.
 * Each plugin has its own param names (e.g., Film Grain: "inMean", "inSize", etc.)
 *
 * TRAINED 2026-03-16: Container structure confirmed. Per-plugin param mapping
 * needs autoresearch Phase 6.
 */
const RESOLVEFX = {
  // Known OFX tool type IDs (in F7.F10)
  FILM_GRAIN:   0xC0000087,
  OFX_MARKER:   0x4F4659,     // "OFY" — marker byte in F2.F21.F1

  // Plugin container structure:
  // F7.F10 (tool list)
  //   F2.F21 → F1 = 0x4F4659 ("OFY" = OFX marker)
  //   F5 (repeated) → F1 = descriptor with string name, F2 = value

  // ────────────────────────────────────────────────────────────────────
  // Plugin slugs (P2.1 discovery 2026-06-19, Session 32)
  // ────────────────────────────────────────────────────────────────────
  //
  // The OFX container's F2.F5 field carries a string slug — the canonical
  // identifier the protobuf bag uses to name the plugin. Slugs MAY carry
  // a version suffix (e.g. `facerefinement2`, `lensflarev2`); newer
  // plugin revisions land at a new slug while the old one persists.
  //
  // Discovery: scripts/drx-autoresearch/discover-ofx-tools.mjs against
  // the Session 30 capture set.
  //
  // Knowledge: docs/design/drp-drx-drt-closeout-harness/knowledge/
  //   ofx-tool-ids.md
  SLUGS: {
    FILM_GRAIN:        'com.blackmagicdesign.resolvefx.filmgrain',
    BEAUTY:            'com.blackmagicdesign.resolvefx.beauty',
    FACE_REFINEMENT2:  'com.blackmagicdesign.resolvefx.facerefinement2',
    LENS_FLARE_V2:     'com.blackmagicdesign.resolvefx.lensflarev2',
    GLOW:              'com.blackmagicdesign.resolvefx.glow',
  },

  // Known parameter names per plugin slug. Partial: only the
  // fixture-perturbed param + the always-present `resolvefxVersion`
  // are confirmed. Expanded coverage requires a per-plugin
  // single-param sweep (queued follow-up).
  KNOWN_PARAMS: {
    'com.blackmagicdesign.resolvefx.filmgrain':       ['filmGrainPresets', 'resolvefxVersion'],
    'com.blackmagicdesign.resolvefx.beauty':          ['watercolorBlend', 'resolvefxVersion'],
    'com.blackmagicdesign.resolvefx.facerefinement2': ['gradShineRemoval', 'resolvefxVersion'],
    'com.blackmagicdesign.resolvefx.lensflarev2':     ['xyPosition', 'resolvefxVersion'],
    'com.blackmagicdesign.resolvefx.glow':            ['inputAlphaUsage', 'resolvefxVersion'],
  },
};

// ============================================================================
// CURVES CORRECTOR (Type 18) — LEGACY MISLABEL, superseded 2026-07-02
// ============================================================================

/**
 * ⚠ The old "Curves corrector (Type 18)" grouping was an unvalidated legacy claim
 * (same class as the Color Warper mesh / polygon 0x08B0 claims — wrong when measured).
 * A live palette sweep on R19.1.3 (bars rig; distinctive values) proves these ids are:
 *   0x0C30001x → the KEY palette, corrector type 9 (shared with Matte Finesse 0x0C30002x)
 *   0x0C4000xx → the MOTION EFFECTS palette, corrector type 15 (NEW corrector type)
 * The CURVES constants are kept for source compatibility; PARAM_ID_MAP now carries the
 * measured names below.
 */
const CURVES = {
  PARAM_1: 204472349,
  PARAM_2: 205520898,
  PARAM_3: 205520899,
  PARAM_4: 205520900,
  PARAM_5: 205520903,
  PARAM_6: 205520904,
  PARAM_7: 205520905,
  PARAM_8: 205520907,
  PARAM_9: 205520908,
  PARAM_10: 205520909,
  PARAM_11: 205520917,
  PARAM_12: 205520918,
  PARAM_13: 205520919,
};

// ============================================================================
// BLUR PALETTE (Blur / Sharpen / Mist) — ct1, swept live 2026-07-02
// ============================================================================

/**
 * Blur palette, Blur mode (Radius 0.73 / H-V Ratio 0.62 / Scaling 0.31 sweep):
 *   RADIUS   0x86000052–54 (R/G/B)  stored = (UI − 0.5) × 2   (0.73 → 0.46; neutral 0.5 → 0)
 *   HV_RATIO 0x86000056–58 (R/G/B)  stored = (UI − 0.5) × 2   (0.62 → 0.24)
 *   SCALING  0x8600005B–5D (R/G/B)  identity observed          (0.31 → 0.31)
 * Single-point fits — affine forms consistent with the 0.5-neutral sliders. Sharpen/Mist
 * share the palette (mode presumably flagged elsewhere); not separately swept.
 */
const BLUR_PALETTE = {
  RADIUS_R: 2248147026,   // 0x86000052
  RADIUS_G: 2248147027,   // 0x86000053
  RADIUS_B: 2248147028,   // 0x86000054
  HV_RATIO_R: 2248147030, // 0x86000056
  HV_RATIO_G: 2248147031, // 0x86000057
  HV_RATIO_B: 2248147032, // 0x86000058
  SCALING_R: 2248147035,  // 0x8600005B
  SCALING_G: 2248147036,  // 0x8600005C
  SCALING_B: 2248147037,  // 0x8600005D
};

// ============================================================================
// KEY PALETTE — ct9 (0x0C30001x), swept live 2026-07-02
// ============================================================================

/**
 * Key palette (Key Input Gain 0.85 / Offset 0.12, Key Output Gain 0.65 / Offset 0.08
 * sweep): all identity scale. NOTE 0x0C30001D (Key Output Gain) is the param the June
 * keyframe sweep animated — it was labeled curves.param1 then.
 */
const KEY_PALETTE = {
  INPUT_GAIN: 204472345,    // 0x0C300019 — identity (0.85 → 0.85)
  INPUT_OFFSET: 204472346,  // 0x0C30001A — identity
  OUTPUT_GAIN: 204472349,   // 0x0C30001D — identity (== CURVES.PARAM_1)
  OUTPUT_OFFSET: 204472350, // 0x0C30001E — identity
};

// ============================================================================
// MOTION EFFECTS PALETTE — ct15 (0x0C4000xx), swept live 2026-07-02
// ============================================================================

/**
 * Motion Effects (Spatial NR luma/chroma 27, blend 0.15; Temporal frames 2,
 * luma/chroma 21, motion 35, blend 0.25; Motion Blur 0.4 sweep):
 *   SPATIAL_LUMA/CHROMA identity (UI 27 → 27) · SPATIAL_BLEND identity (0.15)
 *   TEMPORAL_LUMA/CHROMA identity (21) · TEMPORAL_BLEND identity (0.25)
 *   FRAMES_FLAG varint {F2:4} at UI frames 2 (2× or enum — single point, unconfirmed)
 *   TEMPORAL_MOTION: UI 35 → 11.8 (scale unconfirmed, single point)
 *   MOTION_BLUR: UI 0.4 → 0.0044 (scale unconfirmed, single point)
 */
const MOTION_EFFECTS = {
  SPATIAL_LUMA: 205520898,    // 0x0C400002 (== CURVES.PARAM_2)
  SPATIAL_CHROMA: 205520899,  // 0x0C400003
  SPATIAL_BLEND: 205520900,   // 0x0C400004
  FRAMES_FLAG: 205520903,     // 0x0C400007 — varint
  TEMPORAL_MOTION: 205520906, // 0x0C40000A — scale unconfirmed
  TEMPORAL_LUMA: 205520907,   // 0x0C40000B
  TEMPORAL_CHROMA: 205520908, // 0x0C40000C
  TEMPORAL_BLEND: 205520909,  // 0x0C40000D
  MOTION_BLUR: 205520913,     // 0x0C400011 — scale unconfirmed
};

// ============================================================================
// UNIFIED PARAMETER MAP
// ============================================================================

/**
 * Complete parameter ID to metadata mapping
 * Used for parsing DRX files and extracting parameters
 */
const PARAM_ID_MAP = {
  // Lift
  [LIFT.R]: { control: 'lift', channel: 'r', correctorType: 1 },
  [LIFT.G]: { control: 'lift', channel: 'g', correctorType: 1 },
  [LIFT.B]: { control: 'lift', channel: 'b', correctorType: 1 },
  [LIFT.MASTER]: { control: 'lift', channel: 'master', correctorType: 1 },

  // Gain
  [GAIN.R]: { control: 'gain', channel: 'r', correctorType: 1 },
  [GAIN.G]: { control: 'gain', channel: 'g', correctorType: 1 },
  [GAIN.B]: { control: 'gain', channel: 'b', correctorType: 1 },
  [GAIN.MASTER]: { control: 'gain', channel: 'master', correctorType: 1 },

  // Gamma
  [GAMMA.R]: { control: 'gamma', channel: 'r', correctorType: 1 },
  [GAMMA.G]: { control: 'gamma', channel: 'g', correctorType: 1 },
  [GAMMA.B]: { control: 'gamma', channel: 'b', correctorType: 1 },
  [GAMMA.MASTER]: { control: 'gamma', channel: 'master', correctorType: 1 },

  // Offset
  [OFFSET.R]: { control: 'offset', channel: 'r', correctorType: 1 },
  [OFFSET.G]: { control: 'offset', channel: 'g', correctorType: 1 },
  [OFFSET.B]: { control: 'offset', channel: 'b', correctorType: 1 },

  // Saturation
  [SATURATION.PRIMARY]: { control: 'saturation', channel: 'master', correctorType: 1 },
  [SATURATION.LEGACY]: { control: 'saturation', channel: 'master', correctorType: 1 },

  // Temperature/Tint
  [TEMP_TINT.TEMPERATURE]: { control: 'temperature', channel: 'master', correctorType: 1 },
  [TEMP_TINT.TINT]: { control: 'tint', channel: 'master', correctorType: 1 },
  [TEMP_TINT.MIDTONE_DETAIL]: { control: 'midtoneDetail', channel: 'master', correctorType: 1 },
  [TEMP_TINT.COLOR_BOOST]: { control: 'colorBoost', channel: 'master', correctorType: 1 },
  [TEMP_TINT.CONTRAST]: { control: 'contrast', channel: 'master', correctorType: 1, note: 'Log contrast' },

  // Contrast / Pivot / Log Range (Primary corrector, shared controls range)
  [CONTRAST.CONTRAST]: { control: 'contrast', channel: 'master', correctorType: 1 },
  [CONTRAST.PIVOT]: { control: 'pivot', channel: 'master', correctorType: 1 },
  [CONTRAST.LOW_RANGE]: { control: 'lowRange', channel: 'master', correctorType: 1 },
  [CONTRAST.HIGH_RANGE]: { control: 'highRange', channel: 'master', correctorType: 1, note: 'INVERTED: DRX = 1.0 - UI' },

  // HSL Qualifier (corrector type 2, 0x0830xxxx range — trained 2026-03-16)
  [HSL_QUALIFIER.HUE_CENTER]: { control: 'qualifier', channel: 'hueCenter', correctorType: 2 },
  [HSL_QUALIFIER.HUE_WIDTH]: { control: 'qualifier', channel: 'hueWidth', correctorType: 2 },
  [HSL_QUALIFIER.HUE_SYM]: { control: 'qualifier', channel: 'hueSymmetry', correctorType: 2 },
  [HSL_QUALIFIER.HUE_SOFT]: { control: 'qualifier', channel: 'hueSoft', correctorType: 2 },
  [HSL_QUALIFIER.SAT_HIGH]: { control: 'qualifier', channel: 'satHigh', correctorType: 2 },
  [HSL_QUALIFIER.SAT_LOW]: { control: 'qualifier', channel: 'satLow', correctorType: 2 },
  [HSL_QUALIFIER.SAT_HIGH_SOFT]: { control: 'qualifier', channel: 'satHighSoft', correctorType: 2 },
  [HSL_QUALIFIER.SAT_LOW_SOFT]: { control: 'qualifier', channel: 'satLowSoft', correctorType: 2 },
  [HSL_QUALIFIER.LUM_HIGH]: { control: 'qualifier', channel: 'lumHigh', correctorType: 2 },
  [HSL_QUALIFIER.LUM_LOW]: { control: 'qualifier', channel: 'lumLow', correctorType: 2 },
  [HSL_QUALIFIER.LUM_HIGH_SOFT]: { control: 'qualifier', channel: 'lumHighSoft', correctorType: 2 },
  [HSL_QUALIFIER.LUM_LOW_SOFT]: { control: 'qualifier', channel: 'lumLowSoft', correctorType: 2 },

  // RGB-mode qualifier ranges (correctorType 2, scale UI/100) — VALIDATED LIVE 2026-06-22. Distinct id
  // range (0x02–0x0d) from HSL mode (0x0e+), so no collision; mode flag 0x88300001=2 selects RGB.
  [HSL_QUALIFIER.RGB_R_HIGH]: { control: 'qualifier', channel: 'rgbRHigh', correctorType: 2, note: 'UI/100' },
  [HSL_QUALIFIER.RGB_R_HIGH_SOFT]: { control: 'qualifier', channel: 'rgbRHighSoft', correctorType: 2, note: 'UI/100' },
  [HSL_QUALIFIER.RGB_R_LOW]: { control: 'qualifier', channel: 'rgbRLow', correctorType: 2, note: 'UI/100' },
  [HSL_QUALIFIER.RGB_R_LOW_SOFT]: { control: 'qualifier', channel: 'rgbRLowSoft', correctorType: 2, note: 'UI/100' },
  [HSL_QUALIFIER.RGB_G_HIGH]: { control: 'qualifier', channel: 'rgbGHigh', correctorType: 2, note: 'UI/100' },
  [HSL_QUALIFIER.RGB_G_HIGH_SOFT]: { control: 'qualifier', channel: 'rgbGHighSoft', correctorType: 2, note: 'UI/100' },
  [HSL_QUALIFIER.RGB_G_LOW]: { control: 'qualifier', channel: 'rgbGLow', correctorType: 2, note: 'UI/100' },
  [HSL_QUALIFIER.RGB_G_LOW_SOFT]: { control: 'qualifier', channel: 'rgbGLowSoft', correctorType: 2, note: 'UI/100' },
  [HSL_QUALIFIER.RGB_B_HIGH]: { control: 'qualifier', channel: 'rgbBHigh', correctorType: 2, note: 'UI/100' },
  [HSL_QUALIFIER.RGB_B_HIGH_SOFT]: { control: 'qualifier', channel: 'rgbBHighSoft', correctorType: 2, note: 'UI/100' },
  [HSL_QUALIFIER.RGB_B_LOW]: { control: 'qualifier', channel: 'rgbBLow', correctorType: 2, note: 'UI/100' },
  [HSL_QUALIFIER.RGB_B_LOW_SOFT]: { control: 'qualifier', channel: 'rgbBLowSoft', correctorType: 2, note: 'UI/100' },

  // 3D-mode qualifier (correctorType 2) — VALIDATED LIVE 2026-06-22. Volume/extra/cspace are nested blobs
  // (named, not deep-decoded — bounded scope); Despill is a /100 float.
  [HSL_QUALIFIER.QUALIFIER_3D_VOLUME]: { control: 'qualifier', channel: 'volume3d', correctorType: 2, nested: true, note: '3D selection volume blob' },
  [HSL_QUALIFIER.QUALIFIER_3D_EXTRA]: { control: 'qualifier', channel: 'extra3d', correctorType: 2, nested: true },
  [HSL_QUALIFIER.QUALIFIER_3D_CSPACE]: { control: 'qualifier', channel: 'cspace3d', correctorType: 2, nested: true, note: 'color-space container (YUV)' },
  [HSL_QUALIFIER.QUALIFIER_3D_EXTRA2]: { control: 'qualifier', channel: 'extra3d2', correctorType: 2, nested: true },
  [HSL_QUALIFIER.QUALIFIER_3D_DESPILL]: { control: 'qualifier', channel: 'despill3d', correctorType: 2, note: 'UI/100' },
  [HSL_QUALIFIER.QUALIFIER_MODE]: { control: 'qualifier', channel: 'mode', correctorType: 2, note: '0=HSL, 2=RGB, 4=Luma, 6=3D' },
  [HSL_QUALIFIER.MODE_FLAG]: { control: 'qualifier', channel: 'modeFlag', correctorType: 2, note: 'internal mode indicator (varint, observed 4); value envelope F2. NAMED 2026-06-22' },
  [HSL_QUALIFIER.BLUR_RADIUS]: { control: 'qualifier', channel: 'blurRadius', correctorType: 1 },

  // Matte Finesse (corrector type 9, 0x0C30xxxx — trained 2026-03-16)
  [MATTE_FINESSE.DENOISE]: { control: 'matteFinesse', channel: 'denoise', correctorType: 9 },
  [MATTE_FINESSE.BLACK_CLIP]: { control: 'matteFinesse', channel: 'blackClip', correctorType: 9 },
  [MATTE_FINESSE.WHITE_CLIP]: { control: 'matteFinesse', channel: 'whiteClip', correctorType: 9 },
  [MATTE_FINESSE.IN_OUT_RATIO]: { control: 'matteFinesse', channel: 'inOutRatio', correctorType: 9 },
  [MATTE_FINESSE.CLEAN_BLACK]: { control: 'matteFinesse', channel: 'cleanBlack', correctorType: 9 },
  [MATTE_FINESSE.CLEAN_WHITE]: { control: 'matteFinesse', channel: 'cleanWhite', correctorType: 9 },
  [MATTE_FINESSE.MORPH_RADIUS]: { control: 'matteFinesse', channel: 'morphRadius', correctorType: 9 },
  [MATTE_FINESSE.PRE_FILTER]: { control: 'matteFinesse', channel: 'preFilter', correctorType: 9 },
  [MATTE_FINESSE.POST_FILTER]: { control: 'matteFinesse', channel: 'postFilter', correctorType: 9 },
  [MATTE_FINESSE.SHADOW]: { control: 'matteFinesse', channel: 'shadow', correctorType: 9 },
  [MATTE_FINESSE.MIDTONE]: { control: 'matteFinesse', channel: 'midtone', correctorType: 9 },
  [MATTE_FINESSE.HIGHLIGHT]: { control: 'matteFinesse', channel: 'highlight', correctorType: 9 },

  // Power Windows (corrector type 4, 0x0850xxxx — trained 2026-03-16)
  [POWER_WINDOWS.ROTATE]: { control: 'window', channel: 'rotate', correctorType: 4, note: 'stored = −UI°/180' },
  [POWER_WINDOWS.SIZE]: { control: 'window', channel: 'size', correctorType: 4, note: '0x08500006; stored = 1+(UI−50)×0.08, neutral 1.0' },
  [POWER_WINDOWS.SOFT_REF]: { control: 'window', channel: 'softRef', correctorType: 4 },
  [POWER_WINDOWS.ASPECT]: { control: 'window', channel: 'aspect', correctorType: 4, note: '0x08500004; stored = (50−UI)/50, neutral 0' },
  [POWER_WINDOWS.PAN]: { control: 'window', channel: 'pan', correctorType: 4 },
  [POWER_WINDOWS.TILT]: { control: 'window', channel: 'tilt', correctorType: 4 },
  [POWER_WINDOWS.WINDOW_TYPE]: { control: 'window', channel: 'type', correctorType: 4, note: '1=Circ, 2=Lin, 3=Poly, 4=Curve, 5=Grad' },
  [POWER_WINDOWS.OPACITY]: { control: 'window', channel: 'opacity', correctorType: 4, note: 'scale /100' },
  [POWER_WINDOWS.REF_WIDTH]: { control: 'window', channel: 'refWidth', correctorType: 4, note: 'reference dimension (288 typical)' },
  [POWER_WINDOWS.UNK_0E]: { control: 'window', channel: 'unk0e', correctorType: 4 },
  [POWER_WINDOWS.UNK_0F]: { control: 'window', channel: 'unk0f', correctorType: 4 },
  [POWER_WINDOWS.TRACKING_BLOB]: { control: 'window', channel: 'trackingBlob', correctorType: 4, nested: true, note: 'tracking keyframe data blob' },

  // Linear/Curve window softness mask (corrector type 3, VALIDATED LIVE 2026-06-22). Soft 1-4 = UI × 16.
  [POWER_WINDOWS.SOFT_1]: { control: 'window', channel: 'soft1', correctorType: 3, note: 'stored = UI × 16' },
  [POWER_WINDOWS.SOFT_2]: { control: 'window', channel: 'soft2', correctorType: 3, note: 'stored = UI × 16' },
  [POWER_WINDOWS.SOFT_3]: { control: 'window', channel: 'soft3', correctorType: 3, note: 'stored = UI × 16' },
  [POWER_WINDOWS.SOFT_4]: { control: 'window', channel: 'soft4', correctorType: 3, note: 'stored = UI × 16' },
  [POWER_WINDOWS.SOFT_BBOX]: { control: 'window', channel: 'softBbox', correctorType: 3, nested: true, note: 'softness-mask bbox blob' },
  [POWER_WINDOWS.SOFT_PAN]: { control: 'window', channel: 'softPan', correctorType: 3, note: 'mask pan offset (default 0)' },
  [POWER_WINDOWS.SOFT_TILT]: { control: 'window', channel: 'softTilt', correctorType: 3, note: 'mask tilt offset (default 0)' },
  [POWER_WINDOWS.SOFT_WIDTH]: { control: 'window', channel: 'softWidth', correctorType: 3, note: 'mask width scale (default 1)' },
  [POWER_WINDOWS.SOFT_HEIGHT]: { control: 'window', channel: 'softHeight', correctorType: 3, note: 'mask height scale (default 1)' },
  [POWER_WINDOWS.SOFT_UNK_1]: { control: 'window', channel: 'softUnk1', correctorType: 3 },
  [POWER_WINDOWS.SOFT_UNK_2]: { control: 'window', channel: 'softUnk2', correctorType: 3 },
  [POWER_WINDOWS.SOFT_STRUCT_0F]: { control: 'window', channel: 'softStruct0f', correctorType: 3, nested: true },
  [POWER_WINDOWS.SOFT_STRUCT_12]: { control: 'window', channel: 'softStruct12', correctorType: 3 },
  // SOFT_MATRIX (0x8870001E) is decoded structurally by decodeStructMatrix → window.softMatrix.

  // Log wheels (corrected 2026-01-14)
  [LOG_WHEELS.SHADOW_R]: { control: 'logShadow', channel: 'r', correctorType: 1 },
  [LOG_WHEELS.SHADOW_G]: { control: 'logShadow', channel: 'g', correctorType: 1 },
  [LOG_WHEELS.SHADOW_B]: { control: 'logShadow', channel: 'b', correctorType: 1 },
  [LOG_WHEELS.MIDTONE_R]: { control: 'logMidtone', channel: 'r', correctorType: 1 },
  [LOG_WHEELS.MIDTONE_G]: { control: 'logMidtone', channel: 'g', correctorType: 1 },
  [LOG_WHEELS.MIDTONE_B]: { control: 'logMidtone', channel: 'b', correctorType: 1 },
  [LOG_WHEELS.HIGHLIGHT_R]: { control: 'logHighlight', channel: 'r', correctorType: 1 },
  [LOG_WHEELS.HIGHLIGHT_G]: { control: 'logHighlight', channel: 'g', correctorType: 1 },
  [LOG_WHEELS.HIGHLIGHT_B]: { control: 'logHighlight', channel: 'b', correctorType: 1 },

  // Hue / Saturation (Primary corrector)
  [HUE.HUE_ROTATE]: { control: 'hueRotate', channel: 'master', correctorType: 1 },
  [HUE.SATURATION]: { control: 'saturation', channel: 'primary', correctorType: 1 },

  // Luma vs Saturation
  [LUM_MIX.PARAM_1]: { control: 'lumMix', channel: 'param1', correctorType: 5 },
  [LUM_MIX.PARAM_2]: { control: 'lumMix', channel: 'param2', correctorType: 5 },
  [LUM_MIX.PARAM_3]: { control: 'lumMix', channel: 'param3', correctorType: 5 },
  [LUM_MIX.PARAM_4]: { control: 'lumMix', channel: 'param4', correctorType: 5 },
  [LUM_MIX.PARAM_5]: { control: 'lumMix', channel: 'param5', correctorType: 5 },
  [LUM_MIX.PARAM_6]: { control: 'lumMix', channel: 'param6', correctorType: 5 },
  [LUM_MIX.PARAM_7]: { control: 'lumMix', channel: 'param7', correctorType: 5 },
  [LUM_MIX.PARAM_8]: { control: 'lumMix', channel: 'param8', correctorType: 5 },
  [LUM_MIX.PARAM_9]: { control: 'lumMix', channel: 'param9', correctorType: 5 },
  [LUM_MIX.PARAM_10]: { control: 'lumMix', channel: 'param10', correctorType: 5 },
  [LUM_MIX.PARAM_11]: { control: 'lumMix', channel: 'param11', correctorType: 5 },

  // Saturation vs Saturation
  [SAT_VS_SAT.PARAM_1]: { control: 'satVsSat', channel: 'param1', correctorType: 3 },
  [SAT_VS_SAT.PARAM_2]: { control: 'satVsSat', channel: 'param2', correctorType: 3 },
  [SAT_VS_SAT.PARAM_3]: { control: 'satVsSat', channel: 'param3', correctorType: 3 },
  [SAT_VS_SAT.PARAM_4]: { control: 'satVsSat', channel: 'param4', correctorType: 3 },
  [SAT_VS_SAT.PARAM_5]: { control: 'satVsSat', channel: 'param5', correctorType: 3 },
  [SAT_VS_SAT.PARAM_6]: { control: 'satVsSat', channel: 'param6', correctorType: 3 },
  [SAT_VS_SAT.PARAM_7]: { control: 'satVsSat', channel: 'param7', correctorType: 3 },

  // Node LUT reference (Primary corrector ct1) — the value envelopes are read by extract-lut-refs.js
  // (LUT_PATH carries the basename in F5); named here so the main param path doesn't report unknown_.
  [NODE_LUT_REF.SLOT_META]: { control: 'nodeLut', channel: 'slotMeta', correctorType: 1, note: 'varint slot/kind (e.g. 6)' },
  [NODE_LUT_REF.LUT_PATH]: { control: 'nodeLut', channel: 'lutPath', correctorType: 1, nested: true, note: 'LUT basename/path in value-envelope F5' },

  // Color Warper (chroma warp, Primary corrector ct1) — pins live in 0x86000138 (decoded
  // into colorWarper.pin<N>.* by decodeColorWarperPins); the three flags decode as scalars.
  [COLOR_WARPER.MODE_FLAG]: { control: 'colorWarper', channel: 'modeFlag', correctorType: 1 },
  [COLOR_WARPER.CONFIG_A]: { control: 'colorWarper', channel: 'configA', correctorType: 1 },
  [COLOR_WARPER.CONFIG_B]: { control: 'colorWarper', channel: 'configB', correctorType: 1 },
  [COLOR_WARPER.PINS]: { control: 'colorWarper', channel: 'pins', correctorType: 1, nested: true, note: 'F2.F27.F1[] chroma-warp pin list' },

  // Gradient window opacity — collision-free (0x08F00011 isn't used by SAT_VS_SAT). The other
  // gradient params collide with SAT_VS_SAT (see GRADIENT_WINDOW note) and need ct-aware naming.
  [GRADIENT_WINDOW.OPACITY]: { control: 'gradientWindow', channel: 'opacity', correctorType: 65554, note: 'scale /100' },
  [GRADIENT_WINDOW.MATRIX]: { control: 'gradientWindow', channel: 'matrix', correctorType: 65554, note: 'structural: F10 = row-major 3×3 matrix (identity default)' },

  // HDR Global
  [HDR_ZONE.BLACK_OFFSET]: { control: 'hdrBlackOffset', channel: 'master', correctorType: 1 },

  // HDR Zone (nested protobuf structure - see HDR_ZONE docs)
  [HDR_ZONE.ZONE_ADJUSTMENTS]: { control: 'hdrZone', channel: 'adjustments', correctorType: 1, nested: true },
  [HDR_ZONE.ZONE_DEFINITIONS]: { control: 'hdrZone', channel: 'definitions', correctorType: 1, nested: true },
  [HDR_ZONE.ZONE_METADATA]: { control: 'hdrZone', channel: 'metadata', correctorType: 1 },
  [HDR_ZONE.PARAM_1]: { control: 'hdrZone', channel: 'param1', correctorType: 9 },

  // Curves (legacy IDs from Type 18 corrector — may be alternate encoding)
  // Key palette (ct9) + Motion Effects (ct15) — live-measured 2026-07-02; the old
  // curves.param* (ct18) labels for these ids were an unvalidated legacy claim.
  [KEY_PALETTE.INPUT_GAIN]: { control: 'key', channel: 'inputGain', correctorType: 9 },
  [KEY_PALETTE.INPUT_OFFSET]: { control: 'key', channel: 'inputOffset', correctorType: 9 },
  [KEY_PALETTE.OUTPUT_GAIN]: { control: 'key', channel: 'outputGain', correctorType: 9 },
  [KEY_PALETTE.OUTPUT_OFFSET]: { control: 'key', channel: 'outputOffset', correctorType: 9 },
  [MOTION_EFFECTS.SPATIAL_LUMA]: { control: 'motionEffects', channel: 'spatialLuma', correctorType: 15 },
  [MOTION_EFFECTS.SPATIAL_CHROMA]: { control: 'motionEffects', channel: 'spatialChroma', correctorType: 15 },
  [MOTION_EFFECTS.SPATIAL_BLEND]: { control: 'motionEffects', channel: 'spatialBlend', correctorType: 15 },
  [MOTION_EFFECTS.FRAMES_FLAG]: { control: 'motionEffects', channel: 'framesFlag', correctorType: 15, note: 'varint; observed {F2:4} at UI frames 2' },
  [MOTION_EFFECTS.TEMPORAL_MOTION]: { control: 'motionEffects', channel: 'temporalMotion', correctorType: 15, note: 'stored = 0.28×UI + 2.0 (three-point panel fit 2026-07-03: 35→11.8, 60→18.8, 80→24.4)' },
  [MOTION_EFFECTS.TEMPORAL_LUMA]: { control: 'motionEffects', channel: 'temporalLuma', correctorType: 15 },
  [MOTION_EFFECTS.TEMPORAL_CHROMA]: { control: 'motionEffects', channel: 'temporalChroma', correctorType: 15 },
  [MOTION_EFFECTS.TEMPORAL_BLEND]: { control: 'motionEffects', channel: 'temporalBlend', correctorType: 15 },
  [MOTION_EFFECTS.MOTION_BLUR]: { control: 'motionEffects', channel: 'motionBlur', correctorType: 15, note: 'stored = 0.0099×UI (panel fit 2026-07-03: 50→0.495, 25→0.2475; the old 0.4→0.0044 point was UI 0.44)' },
  [CURVES.PARAM_6]: { control: 'motionEffects', channel: 'unk08', correctorType: 15 },
  [CURVES.PARAM_7]: { control: 'motionEffects', channel: 'unk09', correctorType: 15 },
  [CURVES.PARAM_12]: { control: 'motionEffects', channel: 'unk12', correctorType: 15 },
  [CURVES.PARAM_13]: { control: 'motionEffects', channel: 'unk13', correctorType: 15 },
  // Blur palette (ct1) — live-measured 2026-07-02 (see BLUR_PALETTE block for scales).
  [BLUR_PALETTE.RADIUS_R]: { control: 'blur', channel: 'radiusR', correctorType: 1, note: 'stored = (UI−0.5)×2' },
  [BLUR_PALETTE.RADIUS_G]: { control: 'blur', channel: 'radiusG', correctorType: 1, note: 'stored = (UI−0.5)×2' },
  [BLUR_PALETTE.RADIUS_B]: { control: 'blur', channel: 'radiusB', correctorType: 1, note: 'stored = (UI−0.5)×2' },
  [BLUR_PALETTE.HV_RATIO_R]: { control: 'blur', channel: 'hvRatioR', correctorType: 1, note: 'stored = (UI−0.5)×2' },
  [BLUR_PALETTE.HV_RATIO_G]: { control: 'blur', channel: 'hvRatioG', correctorType: 1, note: 'stored = (UI−0.5)×2' },
  [BLUR_PALETTE.HV_RATIO_B]: { control: 'blur', channel: 'hvRatioB', correctorType: 1, note: 'stored = (UI−0.5)×2' },
  [BLUR_PALETTE.SCALING_R]: { control: 'blur', channel: 'scalingR', correctorType: 1 },
  [BLUR_PALETTE.SCALING_G]: { control: 'blur', channel: 'scalingG', correctorType: 1 },
  [BLUR_PALETTE.SCALING_B]: { control: 'blur', channel: 'scalingB', correctorType: 1 },

  // RGB Mixer (Primary corrector — trained 2026-03-17)
  [RGB_MIXER.RR]: { control: 'rgbMixer', channel: 'rr', correctorType: 1 },
  [RGB_MIXER.GR]: { control: 'rgbMixer', channel: 'gr', correctorType: 1 },
  [RGB_MIXER.BR]: { control: 'rgbMixer', channel: 'br', correctorType: 1 },
  [RGB_MIXER.RG]: { control: 'rgbMixer', channel: 'rg', correctorType: 1 },
  [RGB_MIXER.GG]: { control: 'rgbMixer', channel: 'gg', correctorType: 1 },
  [RGB_MIXER.BG]: { control: 'rgbMixer', channel: 'bg', correctorType: 1 },
  [RGB_MIXER.RB]: { control: 'rgbMixer', channel: 'rb', correctorType: 1 },
  [RGB_MIXER.GB]: { control: 'rgbMixer', channel: 'gb', correctorType: 1 },
  [RGB_MIXER.BB]: { control: 'rgbMixer', channel: 'bb', correctorType: 1 },
  [RGB_MIXER.PRESERVE_LUMINANCE]: { control: 'rgbMixer', channel: 'preserveLuminance', correctorType: 1, nested: true },

  // Custom Curves YRGB (Primary corrector — trained 2026-03-17)
  [CUSTOM_CURVES.Y_META]: { control: 'customCurves', channel: 'yMeta', correctorType: 1, nested: true },
  [CUSTOM_CURVES.R_META]: { control: 'customCurves', channel: 'rMeta', correctorType: 1, nested: true },
  [CUSTOM_CURVES.G_META]: { control: 'customCurves', channel: 'gMeta', correctorType: 1, nested: true },
  [CUSTOM_CURVES.B_META]: { control: 'customCurves', channel: 'bMeta', correctorType: 1, nested: true },
  [CUSTOM_CURVES.Y_SPLINE]: { control: 'customCurves', channel: 'ySpline', correctorType: 1, nested: true },
  [CUSTOM_CURVES.R_SPLINE]: { control: 'customCurves', channel: 'rSpline', correctorType: 1, nested: true },
  [CUSTOM_CURVES.G_SPLINE]: { control: 'customCurves', channel: 'gSpline', correctorType: 1, nested: true },
  [CUSTOM_CURVES.B_SPLINE]: { control: 'customCurves', channel: 'bSpline', correctorType: 1, nested: true },

  // HSL Curves (Primary corrector — trained 2026-03-17)
  [HSL_CURVES.COMMON_FLAG]: { control: 'hslCurves', channel: 'commonFlag', correctorType: 1, nested: true },
  [HSL_CURVES.HUE_VS_HUE_META]: { control: 'hslCurves', channel: 'hueVsHueMeta', correctorType: 1, nested: true },
  [HSL_CURVES.HUE_VS_SAT_META]: { control: 'hslCurves', channel: 'hueVsSatMeta', correctorType: 1, nested: true },
  [HSL_CURVES.HUE_VS_LUM_META]: { control: 'hslCurves', channel: 'hueVsLumMeta', correctorType: 1, nested: true },
  [HSL_CURVES.LUM_VS_SAT_META]: { control: 'hslCurves', channel: 'lumVsSatMeta', correctorType: 1, nested: true },
  [HSL_CURVES.SAT_VS_SAT_META]: { control: 'hslCurves', channel: 'satVsSatMeta', correctorType: 1, nested: true },
  [HSL_CURVES.SAT_VS_LUM_META]: { control: 'hslCurves', channel: 'satVsLumMeta', correctorType: 1, nested: true },
  [HSL_CURVES.HUE_VS_LUM_EXTRA]: { control: 'hslCurves', channel: 'hueVsLumExtra', correctorType: 1, nested: true },
  [HSL_CURVES.HUE_VS_HUE_SPLINE]: { control: 'hslCurves', channel: 'hueVsHueSpline', correctorType: 1, nested: true },
  [HSL_CURVES.HUE_VS_SAT_SPLINE]: { control: 'hslCurves', channel: 'hueVsSatSpline', correctorType: 1, nested: true },
  [HSL_CURVES.HUE_VS_LUM_SPLINE]: { control: 'hslCurves', channel: 'hueVsLumSpline', correctorType: 1, nested: true },
  [HSL_CURVES.LUM_VS_SAT_SPLINE]: { control: 'hslCurves', channel: 'lumVsSatSpline', correctorType: 1, nested: true },
  [HSL_CURVES.SAT_VS_SAT_SPLINE]: { control: 'hslCurves', channel: 'satVsSatSpline', correctorType: 1, nested: true },
  [HSL_CURVES.SAT_VS_LUM_SPLINE]: { control: 'hslCurves', channel: 'satVsLumSpline', correctorType: 1, nested: true },

  // Additional controls (trained 2026-03-17)
  [ADDITIONAL.LUM_MIX_SLIDER]: { control: 'lumMixSlider', channel: 'master', correctorType: 1 },
  [ADDITIONAL.HIGHLIGHTS]: { control: 'highlights', channel: 'master', correctorType: 1 },
  [ADDITIONAL.SHADOWS]: { control: 'shadows', channel: 'master', correctorType: 1 },

  // ColorSlice global controls — CALIBRATED 2026-06-22 (automated harness, design note §16a).
  [COLORSLICE.DENSITY]:       { control: 'colorSlice', channel: 'density', correctorType: 1 },
  [COLORSLICE.DENSITY_DEPTH]: { control: 'colorSlice', channel: 'densityDepth', correctorType: 1 },
  [COLORSLICE.SAT]:           { control: 'colorSlice', channel: 'sat', correctorType: 1 },
  [COLORSLICE.SAT_BALANCE]:   { control: 'colorSlice', channel: 'satBalance', correctorType: 1 },
  [COLORSLICE.SAT_DEPTH]:     { control: 'colorSlice', channel: 'satDepth', correctorType: 1 },
  [COLORSLICE.HUE]:           { control: 'colorSlice', channel: 'hue', correctorType: 1, scale: 'negated' },
};

/**
 * Get parameter metadata by ID
 * @param {number} paramId - Parameter ID
 * @returns {object|null} Parameter metadata or null if unknown
 */
function getParamInfo(paramId) {
  return PARAM_ID_MAP[paramId] || null;
}

/**
 * Get all parameter IDs for a control type
 * @param {string} control - Control name (e.g., 'lift', 'gain', 'temperature')
 * @returns {number[]} Array of parameter IDs
 */
function getParamIdsForControl(control) {
  return Object.entries(PARAM_ID_MAP)
    .filter(([, meta]) => meta.control === control)
    .map(([id]) => Number(id));
}

/**
 * Check if a parameter ID is known
 * @param {number} paramId - Parameter ID
 * @returns {boolean}
 */
function isKnownParam(paramId) {
  return paramId in PARAM_ID_MAP;
}

/**
 * Get total count of known parameters
 * @returns {number}
 */
function getKnownParamCount() {
  return Object.keys(PARAM_ID_MAP).length;
}

module.exports = {
  // Parameter ID constants — Primary Corrector
  LIFT,
  GAIN,
  GAMMA,
  OFFSET,
  SATURATION,
  TEMP_TINT,
  CONTRAST,
  LOG_WHEELS,
  HUE,
  LUM_MIX,
  SAT_VS_SAT,
  HDR_ZONE,
  CURVES,
  BLUR_PALETTE,
  KEY_PALETTE,
  MOTION_EFFECTS,
  RGB_MIXER,
  CUSTOM_CURVES,
  HSL_CURVES,
  ADDITIONAL,

  // Secondary Correction — trained 2026-03-16
  HSL_QUALIFIER,
  MATTE_FINESSE,
  POWER_WINDOWS,

  // Per-node attachments — trained 2026-06-19 (P5.1)
  NODE_LUT_REF,

  // Spatial / Effect tools — trained 2026-03-16 + 2026-03-22
  GRADIENT_WINDOW,
  POLYGON_WINDOW,
  NODE_SIZING,
  COLOR_WARPER,
  COLORSLICE,
  RESOLVEFX,

  // Unified map
  PARAM_ID_MAP,

  // Utility functions
  getParamInfo,
  getParamIdsForControl,
  isKnownParam,
  getKnownParamCount,
};
