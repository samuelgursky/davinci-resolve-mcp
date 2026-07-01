/**
 * drx tool — DaVinci Resolve per-clip grade (.drx) codec. All actions
 * local/offline. Unlike a managed/API-backed build (which forwarded generate/merge to
 * an API), this exposes the FULL vendored codec: parse, generate, CDL, merge.
 *
 * parse — .drx content/file → node graph + tool breakdown + secondary decoders
 * generate — grade params → .drx content (optionally written to outputPath)
 * generate_from_request — higher-level request object → .drx (resolved generator)
 * export_cdl — .drx → ASC CDL or CCC
 * merge — graft new nodes onto an existing .drx
 *
 * NOTE: structural write paths were live-verified against Resolve 2026-07-01/02 (Phase 2
 * calibration): power windows (circle/linear/gradient + polygon/curve vertex shapes),
 * HSL/RGB/luma qualifiers, HDR zones, ColorSlice globals, sat/lum-axis HSL curves, and
 * hue-axis HSL curves (single- AND multi-band via the canonical bezier-cage emitter;
 * edge-on-band-slot geometry passes through raw), plus blur/key/motionEffects palettes.
 * Still experimental/unsupported to WRITE: Color Warper on Resolve 19 (the pin-list wire
 * format is R21's — pending an R21 verify) and OFX plugin params. See
 * vendor/drx-parameters/CALIBRATION-STATUS.md for the per-control coverage ledger.
 */

import fs from 'node:fs/promises';
import { z } from 'zod';
import { drxParser, drxGenerator, drxCdl, drxMerger, drxCodec, nodeLayout } from '../libs.mjs';
import { computeLevels } from '../exposure-level.mjs';
import { computeSkinMatch } from '../skin-match.mjs';
import { computeShotMatch } from '../shot-match.mjs';
import { importCDL } from '../cdl-io.mjs';
import { computeWhiteBalanceMatch } from '../white-balance-match.mjs';
import { transferGrade } from '../grade-transfer.mjs';
import { computeGamutLegal } from '../gamut-legal.mjs';
import { computeContrastNormalize } from '../contrast-normalize.mjs';
import { scopeRead } from '../scope-read.mjs';
import { deriveIntentTags } from '../shot-intent.mjs';
import { verifyGrade } from '../verify-grade.mjs';
import { extractFrames } from '../extract-frames.mjs';
import { computeMatchToReference } from '../match-to-reference.mjs';
import { computeSaturationMatch } from '../saturation-match.mjs';
import { computeBlackBalance } from '../black-balance.mjs';
import { authorLook, carryLook } from '../season-look.mjs';
import { applyLut } from '../lut-apply.mjs';
import { computeToneCurveTransfer } from '../tone-curve-transfer.mjs';

const levelSchema = z.object({
  clips: z
    .array(z.object({ id: z.union([z.string(), z.number()]), png: z.string(), group: z.string() }))
    .describe('Frames to level: [{id, png (extracted frame), group (camera/role)}]'),
  outDir: z.string().describe('Where to write the per-clip DRX grades'),
  mode: z.string().optional().describe("default within_camera_mean (only valid within one camera's drift)"),
  clampGain: z.array(z.number()).length(2).optional(),
});

const skinMatchSchema = z.object({
  clips: z
    .array(z.object({ id: z.union([z.string(), z.number()]), png: z.string(), group: z.string() }))
    .describe('Frames to skin-match: [{id, png (DISPLAY-REFERRED frame), group (camera/role)}]'),
  outDir: z.string().describe('Where to write the per-clip skin-match DRX grades'),
  heroId: z.union([z.string(), z.number()]).optional().describe('Reference clip id per group (default: first clip in group order)'),
  clampGain: z.array(z.number()).length(2).optional(),
  minSkinFrac: z.number().optional().describe('Skin-pixel fraction floor; clips below it are skipped, not faked (default 0.01)'),
  metric: z.enum(['mean', 'chroma']).optional().describe("v2 metric: 'chroma' = luma-preserving skin-line match (avoids the calibrated-for-white-skin trap); 'mean' = legacy masked-mean (default)"),
});

const toneCurveTransferSchema = z.object({
  clips: z
    .array(z.object({ id: z.union([z.string(), z.number()]), png: z.string(), reference: z.string().optional() }))
    .describe('[{id, png (display-referred), reference? (per-clip reference PNG)}]'),
  outDir: z.string().describe('Where to write the per-clip tone-curve DRX grades'),
  reference: z.string().optional().describe('Shared reference PNG for clips without their own'),
  strength: z.number().optional().describe('Blend toward identity (0..1, default 0.8) — keeps the curve a nudge'),
  maxSlope: z.number().optional().describe('Max per-segment slope (anti-crush/band, default 3)'),
  intentTags: z.record(z.array(z.string())).optional().describe('{clipId: tags[]} — intentional/low-key clips are excluded'),
});

const matchToReferenceSchema = z.object({
  clips: z
    .array(z.object({ id: z.union([z.string(), z.number()]), png: z.string(), reference: z.string().optional() }))
    .describe('[{id, png (display-referred), reference? (per-clip reference PNG)}]'),
  outDir: z.string().describe('Where to write the per-clip match DRX grades'),
  reference: z.string().optional().describe('Shared reference PNG for clips without their own'),
  lumaPreserve: z.boolean().optional().describe('Keep the target luma, apply chroma only (default ON)'),
  skinGate: z.boolean().optional().describe('Match skin-region chroma (skin-line) when skin is present (default ON)'),
  clampGain: z.array(z.number()).length(2).optional(),
  clampOffset: z.array(z.number()).length(2).optional(),
});

const saturationMatchSchema = z.object({
  clips: z.array(z.object({ id: z.union([z.string(), z.number()]), png: z.string(), group: z.string().optional() })).describe('[{id, png (display-referred)}]'),
  outDir: z.string().describe('Where to write the per-clip saturation DRX grades'),
  mode: z.enum(['overall', 'skin']).optional().describe("overall = whole-frame sat (default); skin = gate to skin pixels"),
  heroId: z.union([z.string(), z.number()]).optional(),
  clampScale: z.array(z.number()).length(2).optional(),
});

const blackBalanceSchema = z.object({
  clips: z.array(z.object({ id: z.union([z.string(), z.number()]), png: z.string(), group: z.string().optional() })).describe('[{id, png (display-referred)}]'),
  outDir: z.string().describe('Where to write the per-clip black-balance DRX grades'),
  clampOffset: z.array(z.number()).length(2).optional(),
});

const shotMatchSchema = z.object({
  clips: z
    .array(z.object({ id: z.union([z.string(), z.number()]), png: z.string(), scene: z.string().optional() }))
    .describe('B-roll frames: [{id, png (display-referred frame), scene? (cluster key)}]'),
  outDir: z.string().describe('Where to write the per-shot DRX grades'),
  mode: z.enum(['neutralize', 'hero']).optional().describe('neutralize = per-shot gray-world (default); hero = match scene toward heroId'),
  heroId: z.union([z.string(), z.number()]).optional().describe("Required for mode 'hero': the plate to match toward"),
  clampGain: z.array(z.number()).length(2).optional(),
});

const cdlIoSchema = z
  .object({
    cdlPath: z.string().optional().describe('Path to a .cc/.ccc/.cdl file'),
    content: z.string().optional().describe('Raw CDL XML (alternative to cdlPath)'),
    outDir: z.string().describe('Where to write the imported per-correction.drx'),
  })
  .refine((a) => a.cdlPath || a.content, { message: 'provide cdlPath or content' });

const relayoutSchema = z
  .object({
    drxPath: z.string().optional().describe('Source .drx whose node layout to tidy'),
    content: z.string().optional().describe('Source .drx XML (alternative to drxPath)'),
    outPath: z.string().optional().describe('Where to write the relaid-out .drx (else content is returned)'),
    positions: z
      .array(z.array(z.number().int()).length(2))
      .optional()
      .describe('Explicit [x,y] per node in node-index order; omit for the Resolve-cleanup clean row'),
    originX: z.number().int().optional().describe('Clean-row start x (default 290 — matches native Cleanup Node Graph)'),
    originY: z.number().int().optional().describe('Clean-row y (default 428)'),
    spacingX: z.number().int().optional().describe('Clean-row x spacing (default 495)'),
  })
  .refine((a) => a.drxPath || a.content, { message: 'provide drxPath or content' });

const gradeTransferSchema = z
  .object({
    drpPath: z.string().optional().describe('Source .drp to pull a colour-group look from'),
    group: z.string().optional().describe('Group name in the .drp (required with drpPath)'),
    which: z.enum(['post', 'pre']).optional().describe('Group body to copy (default post-clip)'),
    drxPath: z.string().optional().describe('Source .drx to re-wrap (alternative to drpPath)'),
    content: z.string().optional().describe('Source .drx XML (alternative to drxPath)'),
    outPath: z.string().describe('Where to write the apply-ready .drx'),
    label: z.string().optional(),
  })
  .refine((a) => (a.drpPath && a.group) || a.drxPath || a.content, { message: 'provide drpPath+group, or drxPath/content' });

const contrastNormSchema = z.object({
  clips: z
    .array(z.object({ id: z.union([z.string(), z.number()]), png: z.string(), group: z.string() }))
    .describe('Frames: [{id, png (display-referred), group}]'),
  outDir: z.string().describe('Where to write the per-clip contrast DRX grades'),
  heroId: z.union([z.string(), z.number()]).optional().describe('Reference clip per group (default: first)'),
  clampGain: z.array(z.number()).length(2).optional(),
  clampOffset: z.array(z.number()).length(2).optional(),
});

const gamutLegalSchema = z.object({
  clips: z.array(z.object({ id: z.union([z.string(), z.number()]), png: z.string() })).describe('Frames to QC: [{id, png (display-referred)}]'),
  low: z.number().optional().describe('Legal low (8-bit, default 16)'),
  high: z.number().optional().describe('Legal high (8-bit, default 235)'),
  maxIllegalPct: z.number().optional().describe('Out-of-legal tolerance before fail (default 1.0%)'),
});

const rectSchema = z.object({ x: z.number(), y: z.number(), w: z.number(), h: z.number() });
const wbMatchSchema = z.object({
  clips: z
    .array(z.object({ id: z.union([z.string(), z.number()]), png: z.string(), group: z.string().optional(), rect: rectSchema.optional() }))
    .describe('Frames: [{id, png, group?, rect? (per-clip neutral patch, fractions 0..1)}]'),
  outDir: z.string().describe('Where to write the per-clip WB DRX grades'),
  rect: rectSchema.optional().describe('Default neutral-patch rect (fractions 0..1) for clips without their own'),
  mode: z.enum(['neutralize', 'hero']).optional().describe('neutralize = make patch neutral (default); hero = match patch toward heroId'),
  heroId: z.union([z.string(), z.number()]).optional(),
  clampGain: z.array(z.number()).length(2).optional(),
});

const lutApplySchema = z
  .object({
    drxPath: z.string().optional(),
    content: z.string().optional(),
    lutPath: z.string().describe('The .cube name/path to attach (e.g. "Kodak_5219.cube")'),
    nodeIndex: z.number().optional().describe('Node to attach the LUT to (default 0)'),
    slotMeta: z.number().optional().describe('LUT slot metadata (default 6)'),
    outPath: z.string().optional().describe('Write the LUT-attached .drx here'),
  })
  .refine((a) => a.drxPath || a.content, { message: 'provide drxPath or content' });

const authorLookSchema = z.object({
  drpPath: z.string().optional(),
  group: z.string().optional(),
  which: z.enum(['post', 'pre']).optional(),
  drxPath: z.string().optional(),
  content: z.string().optional(),
  name: z.string().describe('Look identity (e.g. "Series host")'),
  version: z.number().describe('Look version'),
  approvedBy: z.string().optional(),
  outPath: z.string().describe('Where to write the apply-ready look .drx'),
});

const carryLookSchema = z.object({
  look: z.object({ name: z.string(), version: z.number(), sourceHash: z.string().optional(), drxPath: z.string() }).describe('An authored look manifest'),
  targets: z.array(z.union([z.string(), z.object({ group: z.string(), episode: z.string().optional() })])),
  gradeMode: z.string().optional(),
});

const scopeReadSchema = z.object({
  png: z.string().describe('Display-referred PNG to read (Rec.709/sRGB)'),
  rect: rectSchema.optional().describe('Optional measurement region (fractions 0..1)'),
  satBins: z.number().optional().describe('Saturation-histogram bin count (default 16)'),
});

const gradeRefSchema = z.object({ drxPath: z.string().optional(), content: z.string().optional() }).refine((a) => a.drxPath || a.content, { message: 'provide drxPath or content' });
const verifyGradeSchema = z.object({
  intended: gradeRefSchema.describe('The intended .drx (what we generated)'),
  applied: gradeRefSchema.describe('The applied grade read back from Resolve (group/clip via Route A)'),
  tol: z.number().optional().describe('Param-delta tolerance (default 1e-3)'),
});

const extractFramesSchema = z.object({
  clips: z
    .array(z.object({ id: z.union([z.string(), z.number()]), source: z.string(), at: z.union([z.string(), z.number()]).optional(), proxy: z.string().optional(), displayReferred: z.boolean().optional() }))
    .describe('[{id, source (media path), at? (frame|midpoint|TC), proxy?, displayReferred?}]'),
  outDir: z.string().describe('Where to write the extracted PNGs'),
  displayReferred: z.boolean().optional().describe('Assert sources are display-referred when ffprobe reports unknown (NEVER for log)'),
});

const intentTagsSchema = z.object({
  png: z.string().describe('Display-referred PNG to derive shot-intent signals from'),
  rect: rectSchema.optional(),
  meta: z.object({}).passthrough().optional().describe('Optional clip metadata: whiteBalanceK, tint, timeOfDay, gel, iso'),
});

const parseSchema = z
  .object({
    drxPath: z.string().optional().describe('Absolute path to a .drx file'),
    content: z.string().optional().describe('Raw .drx XML content (alternative to drxPath)'),
  })
  .refine((a) => a.drxPath || a.content, { message: 'provide drxPath or content' });

const generateSchema = z.object({
  gradeParams: z
    .object({})
    .passthrough()
    .describe(
      "Grade params: lift/gamma/gain/offset as {r,g,b,master} (or [r,g,b,master] / flat liftR..), plus " +
        'contrast, pivot, saturation, temperature, tint, etc. One unified value space via `space` (all ' +
        "params obey it — no per-control cases): space:'ui' (DEFAULT) = Resolve panel numbers " +
        '(lift/gamma ~+/-0.05, gain ~0.90-1.10, offset panel-delta, saturation 0-100/50=neutral); scaled ' +
        "internally (lift x2, gamma x4, gain x1, offset x0.04, sat /50). space:'drx' = raw DRX-internal " +
        'units (wheels raw, saturation ~1.0 neutral) for lossless/programmatic callers.'
    ),
  metadata: z.object({}).passthrough().optional().describe('Optional { label, width, height } metadata'),
  outputPath: z.string().optional().describe('If set, write the .drx here'),
});

const generateFromRequestSchema = z.object({
  request: z.object({}).passthrough().describe('Higher-level grade request for the resolved generator'),
  outputPath: z.string().optional(),
});

const exportCdlSchema = z
  .object({
    drxPath: z.string().optional(),
    content: z.string().optional(),
    params: z.object({}).passthrough().optional().describe('Primary-corrector params (alternative to drx content)'),
    format: z.enum(['cdl', 'ccc']).optional().describe('Output format (default cdl)'),
  })
  .refine((a) => a.drxPath || a.content || a.params, { message: 'provide drxPath, content, or params' });

const mergeSchema = z
  .object({
    basePath: z.string().optional().describe('Existing .drx path to merge into'),
    baseContent: z.string().optional().describe('Existing .drx content (alternative to basePath)'),
    newNodes: z
      .array(z.object({}).passthrough())
      .describe(
        'Nodes to graft on. Each: { label?, params: {lift,gamma,gain,offset,saturation,...} } — or put grade ' +
          "keys at the top level. Supports space:'ui'|'drx' (same scaling AND same default as generate: " +
          "'ui' — Resolve panel units; pass space:'drx' explicitly when grafting raw decoded values)."
      ),
    metadata: z.object({}).passthrough().optional(),
    outputPath: z.string().optional(),
  })
  .refine((a) => a.basePath || a.baseContent, { message: 'provide basePath or baseContent' });

async function readContent(path, content) {
  if (content) return content;
  return fs.readFile(path, 'utf8');
}

// F3: the generator wants color wheels as { r, g, b, master } objects. Accept the
// ergonomic [r, g, b, master] array form too and normalize, so primary lift/gamma/
// gain/offset aren't silently dropped (the cause of the "no round-trip" finding).
const WHEEL_MASTER_DEFAULT = { lift: 0, gamma: 0, offset: 0, gain: 1 };
// UI (Resolve on-screen panel) → DRX-internal scaling, calibrated live against
// Resolve 19 Studio (2026-07): a known DRX value was applied to a node and the
// Primaries panel readout compared. lift 0.10→0.05, gamma 0.20→0.05, gain 1.10→1.10,
// offset 0.04→panel +1.00 (neutral 25), saturation 1.04→panel 52. So DRX = UI × factor:
//   lift ×2, gamma ×4, gain ×1 (panel == DRX), offset ×0.04 (panel-delta), saturation ×(1/50).
// The value space is UNIFIED behind one flag — every primary obeys the same `space`, no
// per-control special cases:
//   • space:'ui'  (DEFAULT) — all params in Resolve panel units. Wheels are panel numbers,
//     offset a panel delta, saturation 0–100 (50=neutral). Intuitive; matches the UI.
//   • space:'drx' — all params in raw DRX-internal units (wheels raw, saturation ≈1.0 neutral,
//     offset ≈±0.04). Lossless/programmatic escape hatch for callers holding native values.
// The encoder consumes panel-scale saturation (÷50 internally) and raw wheels, so this
// function is the single conversion point that reconciles both into what the encoder wants.
const UI_TO_DRX = { lift: 2, gamma: 4, gain: 1, offset: 0.04 };

// ── Hue-axis HSL curve canonicalization (v1 — PENDING live rig verification) ────────
// Resolve 19 silently IGNORES hue-axis curves (hueVsHue/hueVsSat/hueVsLum) written as a
// naive [0,1] point list, even with correct ids and meta. The canonical structure it
// emits itself (captured live 2026-07-02 from a Resolve 19 reference grade) is:
// neutral band anchors + the user's points + PERIODIC
// WRAP copies (every point duplicated at x±1, clipped to a [-2/3, 4/3] window), 19 points
// for a single-band edit. This helper reproduces that shape from a naive [0,1] input.
// Callers holding an already-canonical list (any x outside [0,1]) pass through untouched.
// ⚠ Not yet accepted-verified live: a hand-built wrap variant coincided with a Resolve
// 19.1.3 crash, so verification belongs on the DRX_CALIB rig, never a production project.
const HUE_AXIS_CURVES = ['hueVsHue', 'hueVsSat', 'hueVsLum'];
// Anchor positions mirror the live reference: Resolve's own serialization anchors the
// SECONDARY bands only (yellow 1/6, cyan 1/2, magenta 5/6) — no points at 0 or 1.
const HUE_ANCHOR_XS = [1 / 6, 1 / 2, 5 / 6];
const WRAP_WINDOW = [-2 / 3, 4 / 3];
function canonicalizeHueAxisPoints(points) {
  if (!Array.isArray(points) || points.length === 0) return points;
  if (points.some((p) => p.x < 0 || p.x > 1)) return points; // already canonical/wrapped
  // The hue-axis spline is a STRICT bezier control cage, not a polyline — live-bisected
  // 2026-07-02 on the rig: only the exact pattern Resolve itself serializes renders
  // (fewer points → tool registers but renders flat; same count with plain points →
  // renders garbage; malformed wrap lists can CRASH 19.1.3). This reproduces the
  // captured single-band reference pattern, generalized to bump center x and value y:
  //   window   = [x−1, x+1] (list starts/ends on the wrapped bump center)
  //   bump     = neutral→y pair at x−1/12 · center (x,y) · y→neutral pair at x+1/12
  //   tangents = slope samples at x±0.04623 with y_t = 0.5 + 0.72264·(y−0.5),
  //              present ONLY in the wrap copies (descending half at x−1, ascending at x+1)
  //   anchors  = secondaries (1/6, 1/2, 5/6) outside the bump; the last down-wrap point
  //              and the last core point are DOUBLED (segment-boundary markers)
  // Canonicalized cases: 1..N bumps with centers in [1/8, 7/8], pairwise ≥ 1/6 apart,
  // and NO bump edge (x ± 1/12) landing on a band slot (k/6) — an edge-on-anchor cage
  // renders flat (live-bisected: bumps at 1/3+2/3 render, 0.25+0.7 didn't because
  // 0.25 − 1/12 = 1/6 exactly). Anything else passes through raw.
  const bumps = points.filter((p) => p.y !== 0.5).sort((a, b) => a.x - b.x);
  if (bumps.length === 0) return points;
  if (bumps.some((b) => b.x < 1 / 8 || b.x > 7 / 8)) return points;
  for (let i = 1; i < bumps.length; i++) {
    if (bumps[i].x - bumps[i - 1].x < 1 / 6 - 1e-9) return points;
  }
  // Tight tolerance: a verified bump at 0.6 has an edge 0.0167 from the cyan slot and
  // renders — only (near-)exact collisions fail.
  const onSlot = (v) => Math.abs(v * 6 - Math.round(v * 6)) < 0.06; // x within 0.01 of k/6
  if (bumps.some((b) => onSlot(b.x - 1 / 12) || onSlot(b.x + 1 / 12))) return points;
  const HW = 1 / 12; // bump half-width
  if (bumps.length === 1) {
    // Single band — exact replica of the captured reference (verified to 1e-5).
    const { x, y } = bumps[0];
    const TDX = 0.04623;
    const TY = 0.5 + 0.72264 * (y - 0.5);
    const anchors = HUE_ANCHOR_XS.filter((ax) => Math.abs(ax - x) > HW + 1e-9);
    const above = anchors.filter((ax) => ax > x).sort((a, b) => a - b);
    const below = anchors.filter((ax) => ax < x).sort((a, b) => a - b);
    const out = [];
    out.push({ x: x - 1, y });
    out.push({ x: x + TDX - 1, y: TY });
    out.push({ x: x + HW - 1, y: 0.5 });
    above.forEach((ax, i) => {
      out.push({ x: ax - 1, y: 0.5 });
      if (i === above.length - 1) out.push({ x: ax - 1, y: 0.5 }); // segment-end double
    });
    const core = [
      ...below.map((ax) => ({ x: ax, y: 0.5 })),
      { x: x - HW, y: 0.5 }, { x: x - HW, y },
      { x, y },
      { x: x + HW, y }, { x: x + HW, y: 0.5 },
      ...above.map((ax) => ({ x: ax, y: 0.5 })),
    ];
    out.push(...core);
    out.push({ ...core[core.length - 1] }); // segment-end double
    below.forEach((ax) => out.push({ x: ax + 1, y: 0.5 }));
    out.push({ x: x - HW + 1, y: 0.5 });
    out.push({ x: x - TDX + 1, y: TY });
    out.push({ x: x + 1, y });
    return out;
  }
  // Multi-band — segment layout live-verified with a 2-band probe (approximate tangent
  // values render fine; only the SLOTS are load-bearing; wrap halves use the slope form
  // center→tangent→outer, never copied pairs — pair-only wraps render flat):
  //   core      = all six band anchors outside bumps (0-anchor doubled) + bump quintets
  //               (vertical pairs both sides), path-ordered
  //   down-wrap = last bump's descending half at −1 + anchors above it at −1
  //   up-wrap   = anchors below the first bump at +1 (0-anchor double → 1×2) + the first
  //               bump's ascending half at +1
  const ANCHORS6 = [0, 1 / 6, 1 / 3, 1 / 2, 2 / 3, 5 / 6];
  const near = (a, b) => Math.abs(a - b) <= HW + 1e-9;
  const anchors = ANCHORS6.filter((ax) => !bumps.some((b) => near(ax, b.x) || near(ax + 1, b.x) || near(ax - 1, b.x)));
  const first = bumps[0];
  const last = bumps[bumps.length - 1];
  const out = [];
  const slope = (x0, y0, x1, y1) => [{ x: x0, y: y0 }, { x: (x0 + x1) / 2, y: (y0 + y1) / 2 }, { x: x1, y: y1 }];
  // Down-wrap: descending half of the LAST bump, then anchors above it, all at −1.
  out.push(...slope(last.x - 1, last.y, last.x + HW - 1, 0.5));
  for (const ax of anchors.filter((a) => a > last.x + HW)) out.push({ x: ax - 1, y: 0.5 });
  // Core in path order. Outer-facing bump edges use vertical PAIRS; edges BETWEEN two
  // bumps use the slope-through-anchor form with midpoint tangent slots (live-bisected:
  // pair-only between-bump regions render flat; the working probe used inner-edge →
  // tangent → anchor → tangent → inner-edge).
  const between = (a, b0, b1) => a > b0.x && a < b1.x;
  for (let i = 0; i < bumps.length; i++) {
    const b = bumps[i];
    const prev = bumps[i - 1];
    const isFirst = i === 0;
    // Anchors before this bump (after the previous one), flat at 0.5.
    for (const ax of anchors.filter((a) => (isFirst ? a < b.x - HW : between(a, prev, b)))) {
      if (isFirst) {
        out.push({ x: ax, y: 0.5 });
        if (ax === 0) out.push({ x: ax, y: 0.5 }); // segment-boundary double
      }
      // (between-bump anchors are emitted by the gap connector below)
    }
    if (isFirst) {
      out.push({ x: b.x - HW, y: 0.5 }, { x: b.x - HW, y: b.y }); // enter pair
    } else {
      // Gap connector from the previous bump: inner → tangent → anchors → tangent → inner.
      const gapAnchors = anchors.filter((a) => between(a, prev, b));
      const from = { x: prev.x + HW, y: prev.y };
      const to = { x: b.x - HW, y: b.y };
      out.push({ x: from.x, y: from.y });
      if (gapAnchors.length > 0) {
        const a0 = gapAnchors[0];
        const aN = gapAnchors[gapAnchors.length - 1];
        out.push({ x: (from.x + a0) / 2, y: (from.y + 0.5) / 2 });
        for (const ax of gapAnchors) out.push({ x: ax, y: 0.5 });
        out.push({ x: (aN + to.x) / 2, y: (0.5 + to.y) / 2 });
      } else {
        out.push({ x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 });
      }
      out.push({ x: to.x, y: to.y });
    }
    out.push({ x: b.x, y: b.y }); // center
    if (i === bumps.length - 1) {
      out.push({ x: b.x + HW, y: b.y }, { x: b.x + HW, y: 0.5 }); // exit pair
    }
  }
  // Anchors after the last bump, flat at 0.5.
  for (const ax of anchors.filter((a) => a > last.x + HW)) out.push({ x: ax, y: 0.5 });
  // Up-wrap: anchors below the first bump at +1 (0-double carries), then the first
  // bump's ascending half at +1.
  for (const ax of anchors.filter((a) => a < first.x - HW)) {
    out.push({ x: ax + 1, y: 0.5 });
    if (ax === 0) out.push({ x: ax + 1, y: 0.5 });
  }
  out.push(...slope(first.x - HW + 1, 0.5, first.x + 1, first.y));
  return out;
}
export { canonicalizeHueAxisPoints };

function normalizeGradeParams(gp = {}, warnings = null) {
  const out = { ...gp };
  const space = String(gp.space || 'ui').toLowerCase();
  delete out.space;
  for (const w of ['lift', 'gamma', 'gain', 'offset']) {
    const v = gp[w];
    if (Array.isArray(v)) {
      out[w] = { r: v[0] ?? 0, g: v[1] ?? 0, b: v[2] ?? 0, master: v[3] ?? WHEEL_MASTER_DEFAULT[w] };
    } else {
      // Fold the flat <wheel>R/<wheel>G/<wheel>B/<wheel>Master ergonomic form into the
      // nested object — otherwise the generator silently dropped it (empty correctors).
      const flat = ['R', 'G', 'B', 'Master'].some((c) => gp[w + c] !== undefined);
      if (flat && (v === undefined || typeof v !== 'object')) {
        const d = WHEEL_MASTER_DEFAULT[w];
        out[w] = { r: gp[w + 'R'] ?? d, g: gp[w + 'G'] ?? d, b: gp[w + 'B'] ?? d, master: gp[w + 'Master'] ?? d };
        for (const c of ['R', 'G', 'B', 'Master']) delete out[w + c];
      }
    }
    // Convert Resolve panel numbers → DRX-internal units when in UI space.
    // gain is multiplicative (neutral 1, factor 1) so it passes through unchanged either way.
    if (space === 'ui' && w !== 'gain' && out[w] && typeof out[w] === 'object') {
      const f = UI_TO_DRX[w];
      const scaled = { ...out[w] };
      for (const ch of ['r', 'g', 'b', 'master']) {
        if (typeof scaled[ch] === 'number') scaled[ch] *= f;
      }
      out[w] = scaled;
    }
  }
  // Controls the ENCODER stores as UI/50 (it expects panel-scale 0–100): saturation and the
  // two soft-clip softness params. In UI space, pass 0–100 as-is (the encoder ÷50s downstream).
  // In DRX space the caller supplies the raw internal float, so pre-multiply ×50 to cancel the
  // encoder's ÷50 — keeping these on the SAME axis as the wheels. (Calibrated 2026-07: a raw
  // softClip*Soft input round-trips as input/50, exactly like saturation.)
  if (space === 'drx') {
    for (const k of ['saturation', 'softClipHighSoft', 'softClipLowSoft']) {
      if (typeof out[k] === 'number') out[k] *= 50;
    }
    // Two more encoder-UI transforms, LIVE-CONFIRMED correct by panel readback 2026-07-01
    // (apply generated DRX → read Resolve panel):
    //  • hueRotate: encoder stores (UI−50)/50; input 60 → stored 0.2 → panel Hue 60.00. In
    //    DRX space the caller holds the stored value, so invert: UI = 50 + 50×raw.
    //  • contrastHighRange: RESOLVE ITSELF stores 1−UI (input 0.70 → stored 0.30 → panel
    //    ↑Rng 0.700) — the Phase-1 "encoder bug" hypothesis was WRONG; the inversion is
    //    Resolve-native (contrastLowRange stays 1:1). Pre-invert so raw values round-trip.
    if (typeof out.hueRotate === 'number') out.hueRotate = 50 + 50 * out.hueRotate;
    if (typeof out.contrastHighRange === 'number') out.contrastHighRange = 1 - out.contrastHighRange;
    // ColorSlice Hue is stored NEGATED (UI +X → −X, calibrated 2026-06-22); the encoder
    // negates UI input, so drx-space (raw stored) callers pre-negate to cancel.
    if (out.colorSlice && typeof out.colorSlice.hue === 'number') {
      out.colorSlice = { ...out.colorSlice, hue: -out.colorSlice.hue };
    }
  }
  // HSL curves: canonicalize naive hue-axis point lists (band anchors + periodic wrap —
  // see canonicalizeHueAxisPoints) and default the per-curve meta to the {F2:2} value both
  // live "edited curve" fixtures carry (the vendor generator's bare default is the legacy
  // 6, which live Resolve ignores). Opt out with hslCanonicalize:false.
  if (out.hslCurves && typeof out.hslCurves === 'object') {
    const canon = out.hslCanonicalize !== false;
    delete out.hslCanonicalize;
    const allowWrapped = out.allowWrappedHueCage === true;
    delete out.allowWrappedHueCage;
    if (canon) {
      const curves = { ...out.hslCurves };
      for (const k of HUE_AXIS_CURVES) {
        if (!Array.isArray(curves[k])) continue;
        // CRASH GUARD: a pre-wrapped list (x outside [0,1]) is encoded VERBATIM, and a
        // malformed hue-axis cage can crash Resolve 19 outright (live-bisected 2026-07-02).
        // Refuse by default; allowWrappedHueCage:true is the explicit escape hatch for
        // re-encoding a cage that Resolve itself serialized (decode → verbatim re-encode).
        if (curves[k].some((p) => p && (p.x < 0 || p.x > 1))) {
          if (!allowWrapped) {
            throw new Error(
              `${k}: pre-wrapped hue-axis point list (x outside [0,1]) is passed to Resolve verbatim, ` +
                'and a malformed cage can CRASH Resolve 19. Pass naive [0,1] points (they are ' +
                'canonicalized automatically), or set allowWrappedHueCage:true ONLY to re-encode a ' +
                'cage decoded from Resolve itself.',
            );
          }
          continue; // explicitly allowed — verbatim passthrough
        }
        const canonized = canonicalizeHueAxisPoints(curves[k]);
        if (canonized === curves[k] && curves[k].some((p) => p && p.y !== 0.5)) {
          // Canonicalizer declined (unsupported geometry: center outside [1/8,7/8], bumps
          // <1/6 apart, or a bump edge on a band slot) — Resolve renders the raw list flat.
          warnings?.push(
            `${k}: hue-axis geometry not canonicalizable (see CALIBRATION-STATUS.md) — ` +
              'passed through raw; Resolve will register the curve but render it FLAT.',
          );
        }
        curves[k] = canonized;
      }
      out.hslCurves = curves;
    }
    const meta = { ...(out.hslCurveMeta || {}) };
    for (const k of Object.keys(out.hslCurves)) {
      if (Array.isArray(out.hslCurves[k]) && meta[k] === undefined) meta[k] = 2;
    }
    out.hslCurveMeta = meta;
  }
  return out;
}

// merge()'s newNodes may carry grade values under `params` OR as top-level wheel keys
// ({ label, lift:{...} }). The merger only reads `.params`, so top-level keys were silently
// dropped → an empty appended node. Fold both shapes into `.params` and apply the same
// UI→DRX normalization/scaling as generate, so space:'ui' and the ergonomic forms work here too.
const NODE_META_KEYS = new Set(['label', 'xPos', 'yPos', 'enabled', 'id', 'nodeId']);
function normalizeNewNode(node = {}, warnings = null) {
  if (!node || typeof node !== 'object') return node;
  const meta = {};
  for (const k of NODE_META_KEYS) if (node[k] !== undefined) meta[k] = node[k];
  const rawParams =
    node.params && typeof node.params === 'object'
      ? { ...node.params }
      : Object.fromEntries(Object.entries(node).filter(([k]) => !NODE_META_KEYS.has(k) && k !== 'params'));
  if (node.space !== undefined && rawParams.space === undefined) rawParams.space = node.space;
  return { ...meta, params: normalizeGradeParams(rawParams, warnings) };
}

// Pull the first node's params out of a parsed DRX (for CDL export from content).
function firstNodeParams(parsed) {
  if (parsed?.nodes?.length) return parsed.nodes[0].params || parsed.nodes[0];
  return parsed;
}

// ── value-fidelity flag ────────────────────────────────────
// Decoded grade VALUES are exact only for the calibrated native control set; OFX/ResolveFX plugin
// params + the uncalibrated long tail decode raw/unscaled, and KEYFRAMED grades relocate their values
// to a track block the static decoder doesn't read (so per-corrector params come back empty). This
// marker keeps callers from mistaking decoded values for ground truth. ColorTrace is unaffected
// (lossless Body pass-through — it never re-derives values).
const VALUE_FIDELITY_NOTE =
  'Decoded values are EXACT for the calibrated native control set (primaries, log wheels, curves, ' +
  'HSL/RGB/3D qualifier ranges, power/linear/polygon windows, Color Warper, ColorSlice, HDR zones, ' +
  'node sizing). They are raw/unscaled — NOT ground truth — for OFX/ResolveFX plugin params and any ' +
  'uncalibrated long-tail IDs. ColorTrace / grade-transfer is unaffected (lossless Body pass-through).';

// A keyframed node relocates its grade out of the static per-corrector lists into a keyframe-track
// block (node.F10) the static decoder doesn't read yet — leaving the correctors as empty placeholders.
// Signature: ≥1 corrector present, but zero parameters across all of them AND no lifted structured
// params (colorWarper/curvePoints/polygonVertices/etc.). OPEN ITEM 2.
const LIFTED_PARAM_KEYS = [
  'colorWarper',
  'curvePoints',
  'polygonVertices',
  'softVertices',
  'colorSlice',
  'hdrZones',
  'gradientMatrix',
  'polygonMatrix',
  'softMatrix',
];
function countKeyframedNodes(nodes) {
  if (!Array.isArray(nodes)) return 0;
  let n = 0;
  for (const node of nodes) {
    // Preferred signal: the parser flags keyframe relocation (repeated F6 per corrector) directly.
    if (node.keyframed) {
      n++;
      continue;
    }
    // Fallback heuristic (older parser output / hand-built nodes): correctors present but no params
    // and nothing lifted → the keyframe relocation signature.
    const cors = node.correctors || [];
    if (cors.length === 0) continue;
    const totalParams = cors.reduce((s, c) => s + ((c.parameters && c.parameters.length) || 0), 0);
    const hasLifted = node.params && LIFTED_PARAM_KEYS.some((k) => node.params[k] != null);
    if (totalParams === 0 && !hasLifted) n++;
  }
  return n;
}

function computeValueFidelity(nodes) {
  const fidelity = { level: 'calibrated-subset-only', note: VALUE_FIDELITY_NOTE };
  const keyframed = countKeyframedNodes(nodes);
  if (keyframed > 0) {
    fidelity.keyframed = true;
    fidelity.keyframedNodeCount = keyframed;
    fidelity.warning =
      `${keyframed} node(s) are KEYFRAMED (animated). The static per-corrector params report each track's ` +
      'BASE (frame-0) value; the full animation is decoded under node.keyframes as per-param ' +
      '[{frame, value}] points. Use node.keyframes for time-accurate values.';
  }
  return fidelity;
}

// Exported for unit tests (keyframe-detection signature + fidelity shape).
export { computeValueFidelity, countKeyframedNodes, normalizeGradeParams, normalizeNewNode, UI_TO_DRX };

export const drxTool = {
  name: 'drx',
  description:
    "DaVinci Resolve per-clip grade (.drx) codec — offline, no Resolve required. Actions: parse (decode node graph + qualifiers/curves/windows/OFX), generate (params → .drx), generate_from_request, export_cdl (→ ASC CDL/CCC), merge, level_clips, skin_match, shot_match, cdl_io (import ASC CDL→ .drx; export_cdl is the reverse), white_balance_match (neutral-patch WB), grade_transfer (lossless Body copy → apply-ready .drx), relayout (tidy node-graph LAYOUT only — rewrites node x/y to Resolve's clean row, grade content byte-preserved; live recipe: grab still → relayout → reset_all_grades → ApplyGradeFromDRX. The reset is REQUIRED: same-structure applies keep the existing layout, positions in the .drx are ignored), contrast_normalize (black/white-point match), gamut_legal (broadcast-legal/clip QC), scope_read (frame stats + colorist readouts: parade delta, vectorscope skin-line, black-balance, %clip/%crush + deterministic intent signals). parse/export_cdl include a `valueFidelity` marker — decoded values are exact only for the calibrated native control set (OFX/uncalibrated params are raw; keyframed grades flagged), so don't treat decoded values as ground truth. Structural WRITE paths live-verified 2026-07: power windows (incl. polygon/curve vertex shapes), HSL/RGB/luma qualifiers, HDR zones + zone DEFINITIONS (custom Max Range/falloff), ColorSlice, sat/lum-axis + hue-axis HSL curves (single- and multi-band canonical cage), blur/key/motionEffects palettes, LUT attach (lut_apply; .cube must be Resolve-resolvable, e.g. the LUT dir), and OFX plugin params (any pluginId; params are self-describing name/value pairs, enum strings are PER-PLUGIN vocabularies — use the ResolveFX registry/observed values). Still experimental to write: Color Warper on Resolve 19 (R21 wire format). See CALIBRATION-STATUS.md.",
  async handler({ action, args }) {
    if (action === 'parse') {
      const p = parseSchema.parse(args);
      const xml = await readContent(p.drxPath, p.content);
      const result = await drxParser().parseDRXContent(xml);
      // Augment with secondary decoders where available (mirrors a managed build's grade.parse_local).
      const codec = (() => {
        try {
          return drxCodec();
        } catch {
          return null;
        }
      })();
      if (codec && Array.isArray(result.nodes)) {
        for (const node of result.nodes) {
          // These secondary decoders take the FLAT corrector.parameters array (not the node params
          // object) — passing node.params silently returned null for curves/qualifiers/windows.
          const params = (node.correctors || []).flatMap((c) => c.parameters || []);
          if (!params.length) continue;
          try {
            if (codec.extractCustomCurves && node.customCurves == null) node.customCurves = codec.extractCustomCurves(params);
            if (codec.extractHSLCurves && node.hslCurves == null) node.hslCurves = codec.extractHSLCurves(params);
            if (codec.extractQualifier && node.qualifier == null) node.qualifier = codec.extractQualifier(params);
            if (codec.extractPowerWindow && node.powerWindow == null) node.powerWindow = codec.extractPowerWindow(params);
          } catch {
            /* decoder gap — leave field unset, don't fail the parse */
          }
        }
      }
      const toolBreakdown = drxParser().extractToolBreakdown ? drxParser().extractToolBreakdown(result.nodes) : undefined;
      return { ...result, toolBreakdown, valueFidelity: computeValueFidelity(result.nodes) };
    }

    if (action === 'generate') {
      const p = generateSchema.parse(args);
      const warnings = [];
      const out = await drxGenerator().generateDRX(normalizeGradeParams(p.gradeParams, warnings), p.metadata || {});
      const content = typeof out === 'string' ? out : out?.content || out?.drxContent;
      const warn = warnings.length ? { warnings } : {};
      if (p.outputPath && content) {
        await fs.writeFile(p.outputPath, content);
        return { outputPath: p.outputPath, bytes: Buffer.byteLength(content), ...warn };
      }
      return typeof out === 'string' ? { content: out, ...warn } : { ...out, ...warn };
    }

    if (action === 'generate_from_request') {
      const p = generateFromRequestSchema.parse(args);
      const out = await drxCodec().generateFromRequest(p.request);
      const content = typeof out === 'string' ? out : out?.content || out?.drxContent;
      if (p.outputPath && content) {
        await fs.writeFile(p.outputPath, content);
        return { outputPath: p.outputPath, bytes: Buffer.byteLength(content) };
      }
      return typeof out === 'string' ? { content: out } : out;
    }

    if (action === 'export_cdl') {
      const p = exportCdlSchema.parse(args);
      let params = p.params;
      let parsedNodes = null;
      if (!params) {
        const xml = await readContent(p.drxPath, p.content);
        const parsed = await drxParser().parseDRXContent(xml);
        parsedNodes = parsed?.nodes || null;
        params = firstNodeParams(parsed);
      }
      const cdl = drxCdl();
      const result = p.format === 'ccc' ? cdl.generateCCC(params) : cdl.drxToCDL ? cdl.drxToCDL(params) : cdl.generateCDL(params);
      const valueFidelity = parsedNodes ? computeValueFidelity(parsedNodes) : { level: 'calibrated-subset-only', note: VALUE_FIDELITY_NOTE };
      // CDL of a primary grade is a non-identity model conversion — call it out.
      valueFidelity.cdlNote =
        'ASC CDL is a model conversion of the primary corrector (slope/offset/power/sat); it is approximate by design, not a 1:1 readout of the grade.';
      return { format: p.format || 'cdl', cdl: result, valueFidelity };
    }

    if (action === 'merge') {
      const p = mergeSchema.parse(args);
      const merger = drxMerger();
      const warnings = [];
      const newNodes = Array.isArray(p.newNodes) ? p.newNodes.map((n) => normalizeNewNode(n, warnings)) : p.newNodes;
      const out = p.basePath
        ? await merger.quickMerge(p.basePath, newNodes, p.metadata || {})
        : await merger.mergeFromContent(p.baseContent, newNodes, p.metadata || {});
      const content = typeof out === 'string' ? out : out?.content || out?.drxContent;
      const warn = warnings.length ? { warnings } : {};
      if (p.outputPath && content) {
        await fs.writeFile(p.outputPath, content);
        return { outputPath: p.outputPath, bytes: Buffer.byteLength(content), ...warn };
      }
      return typeof out === 'string' ? { content: out, ...warn } : { ...out, ...warn };
    }

    if (action === 'level_clips') {
      const p = levelSchema.parse(args);
      const r = await computeLevels(p.clips, { outDir: p.outDir, mode: p.mode, clampGain: p.clampGain });
      // compact: don't echo every gain — return report + warnings + grade paths
      return {
        groups: r.report,
        warnings: r.warnings,
        gradeCount: r.grades.length,
        grades: r.grades.map((g) => ({ id: g.id, group: g.group, correctionPct: g.correctionPct, drxPath: g.drxPath })),
      };
    }

    if (action === 'skin_match') {
      const p = skinMatchSchema.parse(args);
      const r = await computeSkinMatch(p.clips, { outDir: p.outDir, heroId: p.heroId, clampGain: p.clampGain, minSkinFrac: p.minSkinFrac, metric: p.metric });
      return {
        groups: r.report,
        warnings: r.warnings,
        skipped: r.skipped,
        gradeCount: r.grades.length,
        grades: r.grades.map((g) => ({ id: g.id, group: g.group, correctionPct: g.correctionPct, skinFracPct: g.skinFracPct, drxPath: g.drxPath })),
      };
    }

    if (action === 'shot_match') {
      const p = shotMatchSchema.parse(args);
      const r = await computeShotMatch(p.clips, { outDir: p.outDir, mode: p.mode, heroId: p.heroId, clampGain: p.clampGain });
      return {
        scenes: r.report,
        warnings: r.warnings,
        skipped: r.skipped,
        gradeCount: r.grades.length,
        grades: r.grades.map((g) => ({ id: g.id, scene: g.scene, mode: g.mode, correctionPct: g.correctionPct, drxPath: g.drxPath })),
      };
    }

    if (action === 'cdl_io') {
      const p = cdlIoSchema.parse(args);
      const xml = await readContent(p.cdlPath, p.content);
      const r = await importCDL(xml, { outDir: p.outDir });
      return { imported: r.grades.length, grades: r.grades, warnings: r.warnings };
    }

    if (action === 'white_balance_match') {
      const p = wbMatchSchema.parse(args);
      const r = await computeWhiteBalanceMatch(p.clips, { outDir: p.outDir, rect: p.rect, mode: p.mode, heroId: p.heroId, clampGain: p.clampGain });
      return {
        groups: r.report,
        warnings: r.warnings,
        skipped: r.skipped,
        gradeCount: r.grades.length,
        grades: r.grades.map((g) => ({ id: g.id, group: g.group, mode: g.mode, correctionPct: g.correctionPct, drxPath: g.drxPath })),
      };
    }

    if (action === 'grade_transfer') {
      const p = gradeTransferSchema.parse(args);
      const r = await transferGrade(
        { drpPath: p.drpPath, group: p.group, which: p.which, drxPath: p.drxPath, content: p.content },
        { outPath: p.outPath, label: p.label },
      );
      return { outPath: r.outPath, nodeCount: r.nodeCount, bodyBytes: r.bodyBytes, label: r.label, source: r.source };
    }

    if (action === 'relayout') {
      const p = relayoutSchema.parse(args);
      const xml = await readContent(p.drxPath, p.content);
      const m = xml.match(/<Body>([0-9a-fA-F]+)<\/Body>/);
      if (!m) throw new Error('no <Body> found — not a grade .drx');
      const layout = nodeLayout();
      const before = await layout.readNodePositions(Buffer.from(m[1], 'hex'));
      const r = await layout.relayoutBodyHex(m[1], {
        positions: p.positions,
        originX: p.originX,
        originY: p.originY,
        spacingX: p.spacingX,
      });
      // Splice the new Body into the ORIGINAL envelope (byte-lossless outside the
      // position varints — labels, keyframes, OFX, still metadata all pass through).
      const out = xml.replace(m[0], `<Body>${r.bodyHex}</Body>`);
      // Guard: the rewrite must not change the node count (silent-corruption check).
      const reparsed = await drxParser().parseDRXContent(out);
      if ((reparsed.nodes || []).length !== r.nodeCount) {
        throw new Error(`relayout self-check failed: ${r.nodeCount} nodes in, ${(reparsed.nodes || []).length} after rewrite`);
      }
      if (p.outPath) {
        await fs.writeFile(p.outPath, out);
        return { outPath: p.outPath, nodeCount: r.nodeCount, positionsBefore: before, positions: r.positions };
      }
      return { content: out, nodeCount: r.nodeCount, positionsBefore: before, positions: r.positions };
    }

    if (action === 'contrast_normalize') {
      const p = contrastNormSchema.parse(args);
      const r = await computeContrastNormalize(p.clips, { outDir: p.outDir, heroId: p.heroId, clampGain: p.clampGain, clampOffset: p.clampOffset });
      return {
        groups: r.report,
        warnings: r.warnings,
        skipped: r.skipped,
        gradeCount: r.grades.length,
        grades: r.grades.map((g) => ({ id: g.id, group: g.group, correctionPct: g.correctionPct, drxPath: g.drxPath })),
      };
    }

    if (action === 'lut_apply') {
      const p = lutApplySchema.parse(args);
      const r = await applyLut({ drxPath: p.drxPath, content: p.content }, { lutPath: p.lutPath, nodeIndex: p.nodeIndex, slotMeta: p.slotMeta, outPath: p.outPath });
      // Don't echo the whole XML unless it wasn't written to disk.
      return { lutPath: r.lutPath, slotMeta: r.slotMeta, nodeIndex: r.nodeIndex, verified: r.verified, liveConfirm: r.liveConfirm, outPath: r.outPath, ...(r.outPath ? {} : { bytes: Buffer.byteLength(r.content) }) };
    }

    if (action === 'author_look') {
      const p = authorLookSchema.parse(args);
      const r = await authorLook(
        { drpPath: p.drpPath, group: p.group, which: p.which, drxPath: p.drxPath, content: p.content },
        { name: p.name, version: p.version, approvedBy: p.approvedBy, outPath: p.outPath },
      );
      return r.manifest;
    }

    if (action === 'carry_look') {
      const p = carryLookSchema.parse(args);
      return carryLook(p.look, p.targets, { gradeMode: p.gradeMode });
    }

    if (action === 'tone_curve_transfer') {
      const p = toneCurveTransferSchema.parse(args);
      const r = await computeToneCurveTransfer(p.clips, { outDir: p.outDir, reference: p.reference, strength: p.strength, maxSlope: p.maxSlope, intentTags: p.intentTags });
      return {
        report: r.report,
        warnings: r.warnings,
        skipped: r.skipped,
        gradeCount: r.grades.length,
        grades: r.grades.map((g) => ({ id: g.id, maxDeltaPct: g.maxDeltaPct, points: g.points.length, drxPath: g.drxPath })),
      };
    }

    if (action === 'match_to_reference') {
      const p = matchToReferenceSchema.parse(args);
      const r = await computeMatchToReference(p.clips, {
        outDir: p.outDir,
        reference: p.reference,
        lumaPreserve: p.lumaPreserve,
        skinGate: p.skinGate,
        clampGain: p.clampGain,
        clampOffset: p.clampOffset,
      });
      return {
        report: r.report,
        warnings: r.warnings,
        skipped: r.skipped,
        gradeCount: r.grades.length,
        grades: r.grades.map((g) => ({ id: g.id, correctionPct: g.correctionPct, skinGated: g.skinGated, lumaPreserve: g.lumaPreserve, drxPath: g.drxPath })),
      };
    }

    if (action === 'saturation_match') {
      const p = saturationMatchSchema.parse(args);
      const r = await computeSaturationMatch(p.clips, { outDir: p.outDir, mode: p.mode, heroId: p.heroId, clampScale: p.clampScale });
      return { report: r.report, warnings: r.warnings, skipped: r.skipped, gradeCount: r.grades.length, grades: r.grades.map((g) => ({ id: g.id, satScale: g.satScale, correctionPct: g.correctionPct, drxPath: g.drxPath })) };
    }

    if (action === 'black_balance') {
      const p = blackBalanceSchema.parse(args);
      const r = await computeBlackBalance(p.clips, { outDir: p.outDir, clampOffset: p.clampOffset });
      return { report: r.report, warnings: r.warnings, skipped: r.skipped, gradeCount: r.grades.length, grades: r.grades.map((g) => ({ id: g.id, castSpreadPct: g.castSpreadPct, drxPath: g.drxPath })) };
    }

    if (action === 'scope_read') {
      const p = scopeReadSchema.parse(args);
      const r = await scopeRead(p.png, { rect: p.rect, satBins: p.satBins });
      if (!r) throw new Error(`scope_read: unreadable frame '${p.png}' (skip-not-fake)`);
      return r;
    }

    if (action === 'verify_grade') {
      const p = verifyGradeSchema.parse(args);
      return verifyGrade({ intended: p.intended, applied: p.applied }, { tol: p.tol });
    }

    if (action === 'extract_frames') {
      const p = extractFramesSchema.parse(args);
      return extractFrames(p.clips, { outDir: p.outDir, displayReferred: p.displayReferred });
    }

    if (action === 'intent_tags') {
      const p = intentTagsSchema.parse(args);
      const scope = await scopeRead(p.png, { rect: p.rect });
      if (!scope) throw new Error(`intent_tags: unreadable frame '${p.png}' (skip-not-fake)`);
      const { tags } = deriveIntentTags(scope, p.meta || {});
      return { tags, signals: scope.signals, note: 'L1 deterministic candidates — the CLIENT reviews with the human; ratified tags persist and the matchers consume them' };
    }

    if (action === 'gamut_legal') {
      const p = gamutLegalSchema.parse(args);
      const r = await computeGamutLegal(p.clips, { low: p.low, high: p.high, maxIllegalPct: p.maxIllegalPct });
      return { clips: r.report, warnings: r.warnings, skipped: r.skipped };
    }

    throw new Error(`Unknown drx action: ${action}`);
  },
};
