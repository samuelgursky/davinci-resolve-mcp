# davinci-resolve-advanced-mcp

The **beyond-the-API** half of `davinci-resolve-mcp`: a Node MCP server that authors and edits
DaVinci Resolve **files** (`.drp` / `.drt` / `.drx`) and applies DB/XML-level changes (Fairlight
routing, offline-reference, conform, color-group grade read) — **with no DaVinci Resolve running.**

It ships as a second `bin` inside the `davinci-resolve-mcp` npm package (one install, two servers):

```
bin/davinci-resolve-mcp.mjs           → Python, live, sanctioned scripting API (drives Resolve)
bin/davinci-resolve-advanced-mcp.mjs  → Node, beyond-API file/DB authoring (no Resolve required)   [this]
```

Runs cloud or local — the file tools never touch Resolve.

## Two ways to use it

- **As an MCP server** (the bin above) — point any MCP client at it.
- **As a library** — `import` the engine directly. The package exposes a public API surface
  (`server/lib.mjs`, wired via `package.json` `main`/`exports`), grouped as **codec** (offline
  `.drp/.drt/.drx`), **grading** (deterministic compute cores), **pipeline** (the DB-as-truth
  foundation), **tools** (the MCP tool handlers), and **mcp** (the stdio server entry). The MCP
  server is a thin shell over these same exports.

## Usage

**As a library — a grading core.** You extract display-referred frames per clip (ffmpeg, your
call); the engine computes the grade offline and writes an apply-ready `.drx`. Applying it in
Resolve (via the scripting API) is the caller's job.

```js
import { computeSkinMatch } from 'davinci-resolve-advanced-mcp';

const { grades, report, warnings } = await computeSkinMatch(
  [
    { id: 'B_0008', png: '/frames/B_0008.png', group: 'Guest' },
    { id: 'C_0016', png: '/frames/C_0016.png', group: 'Guest' },
  ],
  { outDir: '/out/skin' },
);
// grades[].drxPath → apply in Resolve; warnings flag over-corrections; low-skin clips are skipped, not faked.
```

**The DB-as-truth pipeline** (via the `pipeline` tool handler — same API the MCP server exposes).
Compile YAML specs into the canonical DB, plan a run, execute a deterministic stage (you supply the
tool inputs), then read decoded state back and check drift:

```js
import { pipelineTool } from 'davinci-resolve-advanced-mcp';
const call = (action, args) => pipelineTool.handler({ action, args });

const dbPath = '/proj/project.db';
const now = new Date().toISOString(); // the tool takes an explicit timestamp

await call('compile', { dbPath, now, yamlDir: '/proj/specs' }); // YAML → resolved entity tree
const { runId, stages } = await call('plan', { dbPath, episodeSlug: 'e012', now });

// Deterministic stages run now (you pass the tool args); Resolve-apply stages return an action plan.
await call('execute_stage', {
  dbPath, runId, stageIndex: 0, now,
  toolArgs: { tool: 'gamut_legal', args: { clips: [{ id: 'f', png: '/frames/f.png' }] } },
});

// Pull decoded actual state up and flag intent↔actual drift.
await call('readback', {
  dbPath, entitySlug: 'e012.group.Host', now,
  facts: { 'look.lut': 'Kodak_5219' }, pushFields: [{ field: 'look.lut' }],
});
```

## Tools (18)

`drp` · `drt` · `drx` · `offline_ref` · `conform` · `color_trace` · `fusion` · `audio` ·
`audio_plan` · `fairlight` · `project_db` · `project_read` · `pipeline` · `capabilities` ·
`deliverable` · `media` · `editorial` · `provenance`

Each dispatches on an `action`. Highlights:

- **`drx`** — per-clip grade (`.drx`) codec: `parse`, `generate`, `generate_from_request`,
  `export_cdl`, `merge`, plus the **grading/QC catalog** below.
- **`drp` / `drt`** — project / timeline file authoring + editing + grade injection + structural diff.
- **`conform`** — offline conform/relink QC engine (frame-oracle math, not filename matching),
  reverse-clip DB repair, sequence lineage store + diff, per-cut frame QC.
- **`color_trace`** — cross-project clip matching → a trace plan for carrying grades across a re-conform.
- **`project_read` / `project_db`** — read/patch the Resolve project DB (SQLite or Postgres).
- **`pipeline`** — the DB-as-truth pipeline foundation (see below).
- **`deliverable`** — deliverable QC / compliance: `deliverable_qc` (ffprobe a render vs its spec →
  pass/fail per field), `loudness_qc` (ebur128 LUFS/true-peak/LRA), `reframe_blanking_check`,
  `conform_completeness`, `re_delivery_diff`, `render_manifest` (build/reconcile), `expand_deliverable`
  (texted/textless/stems/slate/leader entities). Report-only (`gate: review` — never auto-pass-clear).
- **`media`** — media front-end / AE: `ingest_verify` (hash seal/verify/dupes-by-hash), `media_inventory`
  (fps/codec/colorspace/TC + card gaps), `sync` (TC picture↔sound + drift/MOS), `relink_manifest`,
  `rename_plan` (refuses camera originals) / `reel_normalize`, `turnover_package`, `project_hygiene`.
- **`editorial`** — editorial integrity: `parse_interchange` (EDL/OTIO/XMEML; AAF = honest refuse),
  `turnover_changelist` (moved/retimed/replaced/new/gone + timing silent-lie guards), `conform_manifest`,
  `marker_roundtrip`.
- **`provenance`** — provenance / audit: `gallery_lineage`, `grade_provenance` ("why is this graded this
  way"), `cdl_export` (+ `cdl_diff`, round-trip asserted), `revision_tracking`, `episode_report`.

### Grading / QC catalog (`drx` actions — all local, deterministic, no Resolve)

Frame-stats → arithmetic → `.drx` grade. Frame extraction and grade **apply** are the caller's job;
these compute the grade offline. Each carries guards that refuse to fabricate a match rather than emit
a silent no-op.

| Action | What |
|---|---|
| `level_clips` | within-camera exposure/WB drift → a group hero (whole-frame mean) |
| `skin_match` | cross-camera skin-tone cohesion (skin-gated mean; throws on log/wrong-space frames) |
| `shot_match` | b-roll cohesion — gray-world `neutralize` or `hero` match (per-channel median) |
| `white_balance_match` | WB from a known-neutral patch (gray card) — accurate, not gray-world guess |
| `contrast_normalize` | match black/white points to a hero (affine gain+offset) |
| `match_to_reference` | affine mean-std transfer toward an approved still (skin-line gated, luma-preserve) |
| `saturation_match` | skin/overall saturation cohesion toward a hero |
| `black_balance` | neutralize a shadow colour cast (p1 black point, offset-only) |
| `cdl_io` | import ASC CDL (`.cc`/`.ccc`/`.cdl`) → `.drx` |
| `grade_transfer` | lossless Body copy — a `.drp` group / `.drx` look → an apply-ready `.drx` |
| `relayout` | programmatic "Cleanup Node Graph" (the UI command has no API) — rewrite node x/y to Resolve's clean row, grade byte-preserved. Live recipe: grab → `relayout` → reset grade → apply (same-structure applies keep the old layout). Bulk whole-project sweep: `project_db` `relayout_node_graphs` |
| `author_look` / `carry_look` | version an approved season/host look + plan carrying it across episodes |
| `lut_apply` | attach a named `.cube` LUT to a node (Body-LUT write path, round-trip asserted) |
| `scope_read` | frame readouts: parade balance, vectorscope skin-line, black-balance, %clip/%crush + intent signals |
| `intent_tags` | derive L1 shot-intent tags (low_key, monochromatic, motivated_warm) to exclude from neutralize |
| `verify_grade` | intended vs applied `.drx` → landed/drifted/missing/unverifiable |
| `extract_frames` | ffmpeg display-referred frame extraction (hard log-refuse) |
| `gamut_legal` | broadcast-legal + hard-clip QC (measurement only, no grade emitted) |

### Pipeline foundation (`pipeline` tool — DB-as-truth)

A canonical local **SQLite project DB** is the source of truth; **YAML authoring compiles into it**
(4-layer inheritance: type → series → episode → deliverable, with validation); a **runner** reads the
resolved `pipeline:` and executes stages with gates + provenance; **readback** records decoded actual
state and flags intent↔actual **drift**. Deterministic stages run in Node; Resolve-apply stages emit an
action plan for the live agent (Node can't drive Resolve). Actions: `compile`, `list_entities`,
`get_entity`, `ancestry`, `catalog`, `plan`, `execute_stage`, `approve_gate`, `mark_applied`,
`readback`, `get_run`, `list_runs`, `provenance`, `drift`.

## Layout
- `vendor/` — vendored, MIT copies of the format libraries (CommonJS):
  - `drp-format/` — `.drp` project authoring/editing + grade injection + structural diff
  - `drt-format/` — `.drt` timeline authoring (delegates to drp-format)
  - `drx-codec/` — per-clip DRX grade parse/generate, CDL export, node-tree/curves/qualifier/window codecs
  - `drx-parameters/` — calibrated parameter ranges/ids consumed by drx-codec
  - `conform-qc/` — the offline conform/relink QC engine
- `server/` — the MCP server, tools, grading cores, and the DB-as-truth pipeline foundation
- `test/` — offline unit suite (`npm test`); `.prettierrc.json` — formatting config
- `package.json` — manifest; intentionally CommonJS (no `"type": "module"`) so the vendored libs load
  under the repo's `type: module` root.

## Requirements & optional features

The **core is pure-JS / MIT with zero required native modules or bundled binaries** — `drp`, `drt`,
`drx` (incl. the grading catalog needs `sharp`, see below), `offline_ref`, `fusion`, `audio_plan`,
`conform` (core), `color_trace`, `project_read`, `capabilities` all work out of the box, cloud or local.

A few features need something the **user installs themselves** (call the `capabilities` tool for live
status + install hints):

| Feature | Needs | Why not bundled / Install |
|---|---|---|
| `audio` (split/trim/convert), conform frame ops | **ffmpeg + ffprobe on PATH** | FFmpeg binaries are **GPL** — bundling them would taint this MIT package. `brew install ffmpeg` / `apt install ffmpeg` / `choco install ffmpeg`. |
| grading/QC catalog, `conform.verify` (frame compare) | `sharp` (optional) | native module; `npm i sharp` |
| `pipeline` (project DB), `fairlight` live-DB path, conform lineage/reverse | `better-sqlite3` (optional) | native module; `npm i better-sqlite3`. (The `.drp`-zip Fairlight path needs none.) |
| YAML authoring (`pipeline compile` from a YAML dir) | `js-yaml` (optional) | pure JS; `npm i js-yaml` |

Missing features fail with a clear, actionable message rather than crashing; the server logs a one-line
"needs setup" summary to stderr at startup.

## Provenance & license
Vendored libraries are clean offline format-interop and deterministic compute code: no secrets, no
external service coupling, no network calls, no LLM dependency. Where a feature can take a second
opinion from an AI (the conform engine's advisory `VisionValidator`), it does so only through a
host-injected adapter — the engine ships the interface and a deterministic fake, never a concrete
LLM client. Licensed **MIT** under this repo's root `LICENSE` (Copyright DaVinci Resolve MCP
Contributors and Bradford Operations LLC).

> The bundled `vendor/drp-format/templates/media-clip-h264.drp` uses a neutral synthetic source
> (`/Media/sample.mp4`) — scrubbed of any personal path / third-party clip reference.

DRX write paths were calibrated live against DaVinci Resolve 19 Studio (2026-07): primaries use one
unified `space: 'ui' | 'drx'` value-space flag (panel units by default), and the structural writes —
power windows (circle/linear/gradient + polygon/curve vertex shapes), HSL/RGB/luma qualifiers, HDR
zones, ColorSlice globals, blur/key/motion-effects palettes, sat/lum-axis HSL curves, and hue-axis
HSL curves (single- **and** multi-band, via a canonical bezier-cage emitter that replicates Resolve's
own serialization; edge-on-band-slot geometry passes through raw) — are panel-readback-verified.
OFX/ResolveFX plugin params are read AND write verified (params are self-describing
on the wire; writes render-confirmed live — see the ResolveFX registry for the full
plugin universe, measured ranges, and per-plugin enum vocabularies). HDR zone
DEFINITIONS (custom Max Range/falloff), Motion Effects scales, and the tracker-data
blob are decoded and (where applicable) write-verified. Still experimental to write:
Color Warper on Resolve 19 (the pin-list wire format is R21's). Per-control status
lives in `vendor/drx-parameters/CALIBRATION-STATUS.md` — capabilities are flagged
honestly, not overclaimed.
The grading catalog and pipeline foundation are unit-tested offline; their Resolve **apply** is the
caller's job and is validated live separately.
