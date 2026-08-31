---
name: resolve-delivery
description: Delivery, rendering, and deliverable QC in the DaVinci Resolve MCP. Apply when preparing render jobs, validating render settings, QCing a finished render against a spec (video/loudness/blanking/completeness), building or reconciling a render manifest, expanding texted/textless/stems/slate deliverables, verifying media ingest, or producing a provenance/episode report — live in a running Resolve OR offline against rendered files and the project DB. Routes to the live render tools, the offline deliverable/media/provenance tools, and the deliverables craft skills.
---

# Resolve Delivery / Deliverable QC
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

## Delivery targets (the short path)

Named render intents. `list_delivery_targets` → `prepare_delivery_job(target,
target_dir)`. Ask for `prores422hq_master`, `dnxhr_hqx_master`, `h264_1080p_web`,
or an alias (`youtube`, `tiktok`, `avid`, `stems`). One definition emits BOTH the
Resolve render settings and the `deliverable_qc` spec, so the returned `qc_spec`
is what you QC the finished file against — do not hand-write a second spec.

- Format/codec resolve against the **live** matrix. A target this machine or
  license cannot render fails with the available lists; it never silently
  substitutes. Use `check_availability: true` to see what this install supports.
- Image-sequence targets return `qc_spec: null` — `deliverable_qc` probes one
  file, a sequence is many. That is expected, not a gap.
- Bitrate is deliberately unset (Resolve has no bitrate key). Pin quality
  yourself via `settings` if a spec demands it.

- **Programme loudness is a separate projection.** A target names a standard via
  `overrides: {loudness_standard: "ebu_r128"}`; `resolve_delivery_target` then
  returns a `loudness_target` alongside `qc_spec`. Hand `loudness_target.target`
  to advanced `loudness_qc`. `render(action='list_loudness_standards')` lists the
  five named contracts (`web`, `podcast`, `ebu_r128`, `atsc_a85`,
  `ott_dialogue_gated`) — cite one, never invent the numbers.
- No shipped target names a loudness standard by default: a ProRes master has no
  inherent programme loudness and a broadcast handoff depends on territory.
  A `loudness_note` tells you when none is pinned.
- **Dialogue-gated standards emit no gradeable `integrated`.** `loudness_qc`
  measures full-programme; grading a dialogue-gated figure against that means
  nothing. The number rides in `meta` for a properly gated meter and only true
  peak is asserted. This is deliberate, not a missing field.

Use the lower-level path below when you need something no target covers.

## Live render essentials

- Discover then validate then apply: `probe_render_matrix` (formats/codecs/res) →
  `validate_render_settings` → `safe_set_render_settings` (dry-run capable) →
  `prepare_render_job` (adds a job, does **not** start it).
- Format AND codec accept display names or ids; both normalize against the live
  maps. A rejected pair is a hard error with the available codecs — it never
  queues a job in the previously set codec.
- Render lifecycle helpers require **temp output dirs by default**; real delivery
  paths need explicit lower-level actions.
- `GetRenderSettings` readback is version/page dependent — the kernel validates
  and applies through `SetRenderSettings` regardless.
- `safe_quick_export` forces `EnableUpload=False` and needs `allow_render=True`
  before it actually renders.
- **Pin the base render state with `prepare_render_job(from_preset=...)`.**
  `SetRenderSettings` applies your keys *on top of* whatever the Deliver page is
  holding rather than replacing it, and a loaded preset carries more state than
  the keys you pass. An Audio Only preset plus an explicit `ExportVideo: true`
  has been measured to queue a job that reads back `IsExportVideo: true` and
  renders an mp4 with **no video stream** (issue #123). There is no way to detect
  this: the API documents neither `GetRenderSettings` nor
  `GetCurrentRenderPresetName`, so the inherited state cannot be read — only
  pinned. Verify the OUTPUT, not the job: ffprobe for a `codec_type=video`
  stream. A long timeline that "renders" in seconds is the tell.
- **Three render keys are 21.0.4+**: `UseFullExtents`, `AddFrameHandles`,
  `DataBurnIn` (issue #131). `SetRenderSettings` ignores unknown keys **silently**,
  so on an older build these are dropped with no signal rather than refused —
  which is exactly the failure mode that produces a deliverable missing handles
  nobody notices until the conform. Check `resolve_control check_version_support`
  before offering them, and note `AddFrameHandles` is also ignored when full
  extents is enabled, so it can do nothing for two different reasons.

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
- `spec_from_authored` — turn the authored deliverable vocabulary (codec display
  names, `"1920x1080"`, `"-16 LUFS"`, `<SHOW>_<EP>_<YYYYMMDD>.mov` naming) into a
  `deliverable_qc` spec plus a `loudness_qc` target. Anything it cannot map is
  listed in `unmapped[]` rather than dropped, so an unrecognized codec surfaces
  instead of quietly producing a spec with no codec check in it.

Two things that bite when hand-writing specs, both handled by the projections:

- `container` is `"mov"` for **both** .mov and .mp4 — ffprobe reports
  `format_name=mov,mp4,m4a,...` for each and only the first token is kept. Use
  `video.codec` to tell them apart; a spec asserting `container: "mp4"` always fails.
- Loudness is **not** a `deliverable_qc` field. It comes back as a separate
  `loudnessTarget` for `loudness_qc`.

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
