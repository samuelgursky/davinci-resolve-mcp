---
name: resolve-delivery
description: Delivery, rendering, and deliverable QC in the DaVinci Resolve MCP. Apply when preparing render jobs, validating render settings, QCing a finished render against a spec (video/loudness/blanking/completeness), building or reconciling a render manifest, expanding texted/textless/stems/slate deliverables, verifying media ingest, or producing a provenance/episode report — live in a running Resolve OR offline against rendered files and the project DB. Routes to the live render tools, the offline deliverable/media/provenance tools, and the deliverables craft skills.
---

# Resolve Delivery / Deliverable QC — Claude Code Skill

Bridges delivery *craft* to this repo's *tools*.

- **Craft / specs** — the global `deliverables-knowledge`, `post-supervisor`, and
  `quality-control` / `qc-domain` skills (distributor specs, mastering, QC
  discipline). Use for *what the spec should be*, not tool mechanics.
- **Live tool mechanics** — `docs/kernels/render-deliver-kernel.md` (the `render`
  planning/validation boundary + Quick Export).
- **Offline deliverable QC** — `resolve-advanced/README.md` → `deliverable`,
  `media`, `provenance`.

## Two servers

| Job | Server | Tools |
|---|---|---|
| Plan / validate / run renders in a **running** Resolve | `davinci-resolve` (Python, live) | `render`, `render_presets` |
| QC a **finished render** vs spec, verify ingest, build manifests/provenance with **no Resolve open** | `davinci-resolve-advanced` (Node) | `deliverable`, `media`, `provenance` |

## Live render essentials

- Discover then validate then apply: `probe_render_matrix` (formats/codecs/res) →
  `validate_render_settings` → `safe_set_render_settings` (dry-run capable) →
  `prepare_render_job` (adds a job, does **not** start it).
- Render lifecycle helpers require **temp output dirs by default**; real delivery
  paths need explicit lower-level actions.
- `GetRenderSettings` readback is version/page dependent — the kernel validates
  and applies through `SetRenderSettings` regardless.
- `safe_quick_export` forces `EnableUpload=False` and needs `allow_render=True`
  before it actually renders.

## Offline deliverable QC (`deliverable` actions)

Report-only, **`gate: review` — never auto-pass-clear.** Run these on the finished
file, not the timeline:

- `deliverable_qc` — ffprobe a render vs its spec → pass/fail **per field**.
- `loudness_qc` — ebur128 LUFS / true-peak / LRA.
- `reframe_blanking_check` — pillar/letterbox/blanking vs expected framing.
- `conform_completeness` — every intended shot present in the delivered cut.
- `re_delivery_diff` — what changed between two delivery versions.
- `render_manifest` — build / reconcile the manifest of what was delivered.
- `expand_deliverable` — derive texted / textless / stems / slate / leader
  entities from a master.

## Media front-end + provenance

- **`media`** (front-end / AE): `ingest_verify` (hash seal / verify / dupes),
  `media_inventory` (fps/codec/colorspace/TC + card gaps), `sync` (picture↔sound
  TC + drift/MOS), `relink_manifest`, `rename_plan` (**refuses camera
  originals**) / `reel_normalize`, `turnover_package`, `project_hygiene`.
- **`provenance`** (audit): `grade_provenance` ("why is this graded this way"),
  `gallery_lineage`, `cdl_export` / `cdl_diff` (round-trip asserted),
  `revision_tracking`, `episode_report`.

## Gotchas

- QC tools **refuse rather than fabricate** — a "refused" result means missing
  file, wrong spec, or a metric it cannot honestly compute; read it, don't retry
  blind. `deliverable`/`media` QC needs **ffmpeg + ffprobe on PATH** (GPL, not
  bundled) — call the advanced `capabilities` tool for live status + install hints.
- Deliverable gates never auto-clear; surface the per-field verdict to a human.

## Source-media safety (AGENTS.md)

Render probes may render derivatives of *synthetic* fixtures, never user source
media. `media.rename_plan` refuses camera originals by design — do not override
without explicit approval. Preserve the camera-original-to-delivery chain.
