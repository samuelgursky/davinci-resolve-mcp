/**
 * Agent-routable tool catalog (B0) — the descriptor schema + the registered catalog.
 *
 * An LLM agent ROUTES (which tool, when) and judges GATES; the tools DO the work
 * deterministically & locally (no per-run tokens). Each tool is a compact descriptor the
 * agent dispatches from; `not_for` steers it away from the wrong tool (b-roll → shot_match,
 * NOT exposure_level mean).
 *
 * `mode` tells the runner how a stage executes:
 * 'deterministic' — a local tool action runnable NOW in Node (no Resolve).
 * 'resolve' — needs the live scripting API; the runner emits an action plan for
 * the agent/host to apply (Node can't drive Resolve).
 */
import { z } from 'zod';

export const descriptorSchema = z.object({
  id: z.string(),
  summary: z.string(),
  when_to_use: z.string(),
  inputs: z.array(z.string()).default([]),
  deterministic: z.boolean().default(true),
  locality: z.enum(['local', 'resolve', 'cloud']).default('local'),
  cost_class: z.enum(['free', 'cheap', 'moderate', 'expensive']).default('cheap'),
  gate: z.enum(['none', 'review', 'pass']).default('none'),
  not_for: z.string().optional(),
  output: z.string(),
  tool: z.string().optional(), // MCP tool name
  action: z.string().optional(), // action within that tool
  mode: z.enum(['deterministic', 'resolve']).default('deterministic'),
});

/** The C-tier grading/QC catalog built this cycle (all local, deterministic). */
export const CATALOG = [
  {
    id: 'exposure_level',
    summary: 'Level within-camera exposure/WB drift to a group hero (whole-frame mean)',
    when_to_use: 'many clips of ONE camera drift over a long record; same framing',
    inputs: ['clips', 'group', 'hero'],
    gate: 'review',
    not_for: 'different shots / cross-camera / b-roll (use shot_match or skin_match)',
    output: 'drift report + per-clip gain DRX + over-correction warnings',
    tool: 'drx',
    action: 'level_clips',
  },
  {
    id: 'skin_match',
    summary: 'Cross-camera skin-tone cohesion (gate to skin pixels, match masked mean)',
    when_to_use: 'same person across cameras/framings (wide↔CU) should read consistent',
    inputs: ['clips', 'group', 'hero'],
    gate: 'review',
    not_for: 'shots with no people / b-roll (use shot_match)',
    output: 'per-clip skin-match DRX; skips low-skin clips; throws on log/wrong-space frames',
    tool: 'drx',
    action: 'skin_match',
  },
  {
    id: 'shot_match',
    summary: 'B-roll cohesion: neutralize (gray-world) or match a hero plate (per-channel median)',
    when_to_use: 'b-roll / all-different shots that should feel cohesive',
    inputs: ['clips', 'scene', 'mode', 'heroId'],
    gate: 'review',
    not_for: 'one camera drift (exposure_level) / faces across cameras (skin_match)',
    output: 'per-shot DRX; warns on one-colour shots gray-world over-corrects',
    tool: 'drx',
    action: 'shot_match',
  },
  {
    id: 'white_balance_match',
    summary: 'WB on a KNOWN-neutral patch (gray card) — accurate, not gray-world guess',
    when_to_use: 'a neutral reference (card/wall) is visible to balance against',
    inputs: ['clips', 'rect', 'mode', 'heroId'],
    gate: 'review',
    not_for: 'no neutral surface visible (use shot_match neutralize)',
    output: 'per-clip WB DRX',
    tool: 'drx',
    action: 'white_balance_match',
  },
  {
    id: 'contrast_normalize',
    summary: 'Match black/white points to a group hero (affine gain+offset)',
    when_to_use: 'line clips up in the same tonal range before a shared look',
    inputs: ['clips', 'group', 'heroId'],
    gate: 'review',
    not_for: 'colour-cast correction (use WB/shot_match); offset semantics pending live validation',
    output: 'per-clip affine DRX',
    tool: 'drx',
    action: 'contrast_normalize',
  },
  {
    id: 'cdl_io',
    summary: 'Import ASC CDL (.cc/.ccc/.cdl) → .drx (on-set/DIT looks)',
    when_to_use: 'a DIT/on-set CDL should seed the grade',
    inputs: ['cdlPath', 'outDir'],
    not_for: 'exporting (use drx export_cdl)',
    output: 'one .drx per ColorCorrection',
    tool: 'drx',
    action: 'cdl_io',
  },
  {
    id: 'grade_transfer',
    summary: 'Lossless Body copy: a .drp group /.drx look → apply-ready .drx',
    when_to_use: 'carry a decoded season/host look onto an episode (Route A)',
    inputs: ['drpPath', 'group', 'outPath'],
    not_for: 'synthesising a NEW grade (use generate); applying a NEW .cube LUT (live API)',
    output: 'apply-ready GyStill.drx (byte-faithful)',
    tool: 'drx',
    action: 'grade_transfer',
  },
  {
    id: 'match_to_reference',
    summary: 'Affine mean-std transfer toward a reference still (skin-line, luma-preserve ON)',
    when_to_use: 'match a shot to an approved still / client "make it look like this" / hero render',
    inputs: ['clips', 'reference', 'outDir'],
    gate: 'review',
    not_for: 'neutralizing (use WB) or exposure-only leveling (exposure_level); a trim, NOT a cross-IDT reconciler',
    output: 'per-clip affine DRX (gain+offset) + over-correction warnings',
    tool: 'drx',
    action: 'match_to_reference',
  },
  {
    id: 'tone_curve_transfer',
    summary: 'Match a clip\'s CONTRAST SHAPE to a reference via a nonlinear luma tone curve (CDF matching)',
    when_to_use: 'carry a reference S-curve / filmic roll-off / soft profile a gain+offset trim can\'t express',
    inputs: ['clips', 'reference', 'outDir'],
    gate: 'review',
    not_for: 'exposure-only leveling (exposure_level) or colour cast (WB/black_balance); a curve is a look decision',
    output: 'per-clip luma tone-curve DRX (round-trip asserted); skips near-identity + intent-tagged clips',
    tool: 'drx',
    action: 'tone_curve_transfer',
  },
  {
    id: 'saturation_match',
    summary: 'Match skin/overall saturation cohesion toward a hero (sat scale)',
    when_to_use: 'a scene reads with inconsistent chroma across cameras',
    inputs: ['clips', 'mode', 'heroId'],
    gate: 'review',
    not_for: 'colour-cast correction (use WB/black_balance)',
    output: 'per-clip saturation DRX',
    tool: 'drx',
    action: 'saturation_match',
  },
  {
    id: 'black_balance',
    summary: 'Neutralize a shadow colour cast (p1 black point only, offset-only)',
    when_to_use: 'shadows carry a colour cast but mids/highlights are fine',
    inputs: ['clips', 'outDir'],
    gate: 'review',
    not_for: 'overall WB (use white_balance_match); tonal range (contrast_normalize)',
    output: 'per-clip offset-only DRX; skips already-neutral shadows',
    tool: 'drx',
    action: 'black_balance',
  },
  {
    id: 'scope_read',
    summary: 'Read a frame: parade balance, vectorscope skin-line, black-balance, %clip/%crush + intent signals',
    when_to_use: 'QC a frame / feed the matchers stats / derive shot-intent signals (low-key, monochromatic)',
    inputs: ['png', 'rect'],
    gate: 'none',
    not_for: 'emitting a grade (this only measures); log/scene-referred frames (readouts assume Rec.709)',
    output: 'per-channel stats + luma + colorist readouts + deterministic intent signals',
    tool: 'drx',
    action: 'scope_read',
  },
  {
    id: 'verify_grade',
    summary: 'Compare an intended .drx vs the applied grade read back from Resolve → drift verdict',
    when_to_use: 'after applying a grade, prove it landed (landed/drifted/missing/unverifiable)',
    inputs: ['intended', 'applied'],
    gate: 'none',
    not_for: 'judging OFX/keyframed nodes (flagged unverifiable — use live scopes)',
    output: 'per-node verdict + param deltas + overall landed/drifted/missing/unverifiable',
    tool: 'drx',
    action: 'verify_grade',
  },
  {
    id: 'extract_frames',
    summary: 'ffmpeg-extract DISPLAY-REFERRED frames (oracle/midpoint/TC) for the matchers',
    when_to_use: 'produce the display-referred PNGs the grading catalog consumes',
    inputs: ['clips', 'outDir'],
    gate: 'none',
    not_for: 'log/scene-referred sources (HARD refused — point at a post-ODT proxy/render)',
    output: '{ id → png } + skipped (with refuse reasons) + warnings',
    tool: 'drx',
    action: 'extract_frames',
  },
  {
    id: 'intent_tags',
    summary: 'Derive L1 shot-intent tags (low_key, monochromatic, motivated_warm/cool) from a frame',
    when_to_use: 'before a neutralize/level pass, to EXCLUDE intentionally-graded shots',
    inputs: ['png', 'meta'],
    gate: 'review',
    not_for: 'deciding intent unilaterally (candidates only — the client + human ratify)',
    output: 'candidate intent tags with evidence + confidence + scope signals',
    tool: 'drx',
    action: 'intent_tags',
  },
  {
    id: 'lut_apply',
    summary: 'Attach a named .cube LUT to a node (Body-LUT write path, round-trip asserted)',
    when_to_use: 'apply a film/print LUT (e.g. Kodak 5219) to a grade node offline',
    inputs: ['drxPath', 'lutPath'],
    gate: 'review',
    not_for: 'synthesising a grade (use generate); live-apply confirmation pending real-footage validation',
    output: 'LUT-attached .drx (verified) — the LUT taking effect in Resolve is live-pending',
    tool: 'drx',
    action: 'lut_apply',
  },
  {
    id: 'author_look',
    summary: 'Author a versioned, hashed season/host look from a group/DRX (Route A)',
    when_to_use: 'register an approved host/season look to carry forward across episodes',
    inputs: ['drpPath', 'group', 'name', 'version'],
    gate: 'review',
    not_for: 'a NEW grade (use generate); applying it (use carry_look)',
    output: 'apply-ready look .drx + a versioned manifest (name/version/hash/approvedBy)',
    tool: 'drx',
    action: 'author_look',
  },
  {
    id: 'carry_look',
    summary: 'Plan carrying a versioned look onto target groups (group safe_apply_drx)',
    when_to_use: 'apply an authored season look to this episode\'s groups',
    inputs: ['look', 'targets'],
    gate: 'review',
    not_for: 'authoring (use author_look)',
    output: 'per-target apply plan with look provenance',
    tool: 'drx',
    action: 'carry_look',
  },
  {
    id: 'gamut_legal',
    summary: 'Broadcast-legal + hard-clip QC (no grade emitted)',
    when_to_use: 'pre-delivery legal-range / clipping check',
    inputs: ['clips', 'low', 'high'],
    gate: 'pass',
    output: 'per-clip pass/fail + out-of-legal/clip %',
    tool: 'drx',
    action: 'gamut_legal',
  },
].map((d) => descriptorSchema.parse({ ...d, mode: 'deterministic' }));

const BY_ID = new Map(CATALOG.map((d) => [d.id, d]));
export const getDescriptor = (id) => BY_ID.get(id) || null;
/** Compact list for the agent (id + summary + when + not_for) — small context footprint. */
export const listCatalog = () => CATALOG.map((d) => ({ id: d.id, summary: d.summary, when_to_use: d.when_to_use, not_for: d.not_for, gate: d.gate }));

/**
 * Pipeline stage → how it executes. Stages with a catalog tool run deterministically;
 * Resolve-apply stages (conform, groups, render, audio) emit an action plan for the agent.
 */
export const STAGE_PLAN = {
  ingest: { mode: 'resolve', note: 'card checksum/proxy/metadata — live/IO stage' },
  conform: { mode: 'resolve', note: 'path-translate + sanitize + import_timeline (live)' },
  offline_ref: { mode: 'resolve', note: 'attach PICREF via DB patch (live)' },
  color_groups: { mode: 'resolve', note: 'create + assign color groups (live API)' },
  leveling: {
    mode: 'deterministic',
    tools: ['exposure_level', 'skin_match', 'shot_match', 'white_balance_match', 'contrast_normalize'],
    note: 'pick by group type via not_for guidance',
  },
  grade: { mode: 'deterministic', tools: ['grade_transfer'], note: 'Route A look transfer; new looks via generate/live' },
  audio_sync: { mode: 'resolve', note: 'AutoSyncAudio + routing + loudness (live)' },
  qc: { mode: 'deterministic', tools: ['gamut_legal'], note: 'legal/clip QC; conform-QC + loudness later' },
  deliver: { mode: 'resolve', note: 'render queue from deliverable specs (live)' },
};
