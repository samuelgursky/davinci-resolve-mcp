# Render / Deliver Kernel

The Render / Deliver kernel adds a safer planning and validation layer over
Resolve's render queue, render settings, format/codec discovery, presets, and
Quick Export APIs.

Live probes use disposable `_mcp_...` projects, generated synthetic media, and
temporary output directories only. They may render derivatives of generated
fixtures, but never render, transcode, proxy, or overwrite user source media.

## New Compound Actions

All actions are under `render(action=...)`.

| Action | Status | Purpose |
| --- | --- | --- |
| `render_capabilities` | Supported | Reports render method availability, formats, presets, quick-export presets, setting keys, and safety guards. |
| `probe_render_matrix` | Supported | Builds a format/codec/resolution compatibility matrix. |
| `probe_render_settings` | Supported with readback boundary | Captures current format/codec, mode, jobs, render state, and settings when Resolve exposes settings readback. |
| `validate_render_settings` | Supported | Validates supported setting keys, value types, frame ranges, and optional temp-target requirements. |
| `safe_set_render_settings` | Supported | Validates settings before `SetRenderSettings`, reports post-set readback/coercion when available, and supports dry-run. |
| `prepare_render_job` | Supported | Validates target directory/settings, optionally sets format/codec, applies settings, and adds a render job without starting it. |
| `render_job_lifecycle_probe` | Supported | Adds a job, reads status, and deletes the job to validate queue lifecycle safely. |
| `quick_export_capabilities` | Supported | Lists Quick Export presets and enforced safety guards. |
| `safe_quick_export` | Supported dry-run | Validates temp target, forces `EnableUpload=False`, and requires `allow_render=True` before actual Quick Export execution. |
| `export_render_boundary_report` | Supported | Combines capabilities, settings snapshot, format matrix, and Quick Export capabilities. |
| `list_delivery_targets` | Supported | Lists named render intents, optionally filtered by tier and checked against the live format/codec matrix. |
| `resolve_delivery_target` | Supported | Resolves a named target to live format/codec ids plus its render settings and QC spec. |
| `prepare_delivery_job` | Supported | Resolves a named target and queues a render job for it, returning the QC spec that verifies the output. |

## Delivery Targets

A delivery target is a **named render intent** (`prores422hq_master`,
`h264_1080p_web`, `dnxhr_hqx_master`, ...) defined once in
`src/utils/delivery_targets.py` and projected two ways: onto Resolve
`SetRenderSettings` keys, and onto the ffprobe-shaped spec the advanced server's
`deliverable_qc` consumes. The render and the check that verifies it therefore
come from one definition.

- **Ids describe the deliverable; platform names are aliases.** `youtube`,
  `tiktok`, `reels` and friends point at spec-descriptive ids. When a platform
  changes its guidance you repoint an alias rather than rewrite a target, so no
  committed id can become a lie about what it produces.
- **Format and codec are candidate lists**, resolved against the live matrix at
  call time. Codec description strings vary by Resolve version, license, and
  installed IO plugins, so a target names the spellings it knows and the first
  available one wins.
- **Unavailable targets fail loudly** with `DELIVERY_TARGET_FORMAT_UNAVAILABLE` /
  `DELIVERY_TARGET_CODEC_UNAVAILABLE` and the machine's actual available lists.
  Use `list_delivery_targets` with `check_availability` to see what this install
  can render before planning around it.
- **The QC spec asserts only what the render settings pin.** Bitrate is not
  encoded (Resolve exposes no bitrate key — only `VideoQuality`, whose type
  varies per codec), and image-sequence targets carry no QC spec at all because
  `deliverable_qc` probes a single file.
- Users can add targets in `logs/delivery-targets.json` (override the path with
  `DAVINCI_RESOLVE_MCP_DELIVERY_TARGETS`). A malformed entry is skipped with a
  warning rather than taking out the shipped set.

## Supported Boundaries

- Format discovery through `GetRenderFormats`.
- Codec discovery for every returned format through `GetRenderCodecs`.
- Resolution discovery for every format/codec pair through
  `GetRenderResolutions`.
- Current format/codec set and readback.
- Current render mode get/set.
- Render preset list, save, and delete for temporary MCP-named presets.
- Render setting validation for documented `SetRenderSettings` keys.
- Safe render job preparation into a temp target directory.
- Job queue lifecycle: add, status, delete.
- Actual synthetic render start/completion for a two-second generated timeline.
- Quick Export preset discovery and guarded dry-run planning.

## Version Or Page Dependent Boundaries

- `GetRenderSettings` is documented, but in the final Resolve Studio 20.3.2.9
  live probe the project attribute was not callable. The kernel treats settings
  readback as version/page dependent and still validates and applies settings
  through `SetRenderSettings`.
- Render format and codec availability is machine, OS, license, and plugin
  dependent, and it varies a lot: a live probe found 23 formats / 99 pairs on one
  build, and 20 formats / 271 pairs on Studio 19.1.3.7. Treat neither figure as
  the expected count — probe the machine you are on
  (`probe_render_matrix`, or `list_delivery_targets` with `check_availability`).
- Codec **descriptions are not codec ids**. `GetRenderCodecs` returns
  `{description: id}` and every setter wants the id, so the name shown in the
  Deliver page is rejected — for `H.264` (`H264`) just as much as for
  `Apple ProRes 422 HQ` (`ProRes422HQ`). `src/utils/render_ids.py` normalizes
  either form; see `docs/reference/api-limitations.md`.
- Some formats expose **no codecs at all** (`Wave`, `GIF` on 19.1.3.7) and then
  reject every codec value, so they cannot be selected through this API.
- Some settings may be accepted but not readable for coercion checks on builds
  where `GetRenderSettings` is unavailable.
- Quick Export actual execution is intentionally gated behind
  `allow_render=True`, because it starts rendering immediately and can involve
  upload-capable presets. The safe helper always forces `EnableUpload=False`.

## Unsupported Or Guarded

- Render lifecycle helpers require temp output directories by default. Passing
  real delivery paths requires explicit lower-level actions or disabling the
  temp guard.
- Upload-enabled Quick Export is not allowed through `safe_quick_export`.
- Import/export of render and burn-in preset files remains exposed through the
  existing `render_presets` tool, but the live kernel probe does not fabricate
  arbitrary preset files.

## Advanced (offline) server — deliverable QC, media front-end, provenance

The live actions above plan and drive renders in a *running* Resolve. The
companion advanced server (`davinci-resolve-advanced`, see
`resolve-advanced/README.md`) QCs the **finished render** and manages media/
provenance with **no Resolve running**. It is report-only —
**`gate: review`, never auto-pass-clear.**

- **`deliverable`** — `deliverable_qc` (ffprobe a render vs its spec → pass/fail
  **per field**), `loudness_qc` (ebur128 LUFS/true-peak/LRA),
  `reframe_blanking_check`, `conform_completeness` (every intended shot present),
  `re_delivery_diff`, `render_manifest` (build/reconcile), `expand_deliverable`
  (texted/textless/stems/slate/leader entities).
- **`media`** (front-end / AE) — `ingest_verify` (hash seal/verify/dupes),
  `media_inventory` (fps/codec/colorspace/TC + card gaps), `sync` (picture↔sound
  TC + drift/MOS), `relink_manifest`, `rename_plan` (**refuses camera
  originals**) / `reel_normalize`, `turnover_package`, `project_hygiene`.
- **`provenance`** (audit) — `grade_provenance` ("why is this graded this way"),
  `gallery_lineage`, `cdl_export` / `cdl_diff` (round-trip asserted),
  `revision_tracking`, `episode_report`.

Rules an agent must know:

- QC tools **refuse rather than fabricate** — a "refused" result means missing
  file, wrong spec, or a metric it cannot honestly compute.
- Deliverable gates never auto-clear; surface the per-field verdict to a human.
- **Deps.** `deliverable`/`media` QC needs **ffmpeg + ffprobe on PATH** (GPL, not
  bundled) — call the advanced `capabilities` tool for status + install hints.

See the `resolve-delivery` skill (`.agents/skills/resolve-delivery/SKILL.md`) for the
craft ↔ live ↔ offline routing.

## Live Evidence

Final validation ran on May 9, 2026 with DaVinci Resolve Studio 20.3.2.9 and
Python 3.11.14.

```
python3.11 tests/live_render_deliver_validation.py \
  --output-dir /private/tmp/render-deliver-probe-20260509-release
```

Result:

- `supported`: 23
- `version_or_page_dependent`: 1
- `unsupported`: 0
- `partially_supported`: 0
- `write_only_unverifiable`: 0
- `read_only`: 0
- `not_applicable`: 0
- `error`: 0

The live harness created and deleted a disposable project named
`_mcp_render_deliver_probe_1778342107`, generated synthetic media, probed 23
formats and 99 format/codec pairs **on that build** (a later probe on Studio
19.1.3.7 saw 20 formats / 271 pairs — the counts are not portable), rendered one
tiny synthetic output, wrote
JSON and Markdown reports, and removed the generated media and render output
directories after the report was written.
