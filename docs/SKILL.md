# DaVinci Resolve MCP Server — AI Skill Reference

This document gives AI assistants the context needed to use the DaVinci Resolve
MCP server effectively. It covers the tool landscape, page prerequisites,
common workflow patterns, error recovery, and known gotchas.

---

## What This Server Does

The DaVinci Resolve MCP server bridges AI assistants to DaVinci Resolve Studio
via its official Scripting API. You can control every aspect of a post-production
session — projects, timelines, clips, color grading, Fusion compositions, audio,
render queues, and more — through natural language.

DaVinci Resolve must be running with **Preferences > General > "External scripting
using"** set to **Local**. The server auto-launches Resolve if it is not running,
but that first connection can take up to 60 seconds.

Workflow Integration plugins/scripts are a separate Resolve-hosted UI mechanism.
They are not required for this MCP server, but `docs/integrations/workflow-integrations.md`
summarizes when they are useful for optional in-Resolve panels, UIManager
scripts, and render callback companions.

OpenFX plugins are native C++ image-effect plugins, not an MCP control surface.
Use `docs/notes/openfx-notes.md` when diagnosing `insert_ofx_generator` failures or
discussing optional OFX plugin development.

LUT files are directly relevant to Color-page graph actions. Use
`docs/notes/lut-notes.md` when diagnosing `graph.set_lut` failures, validating `.cube`
files, or explaining `project_settings.refresh_luts`.

Fusion templates are relevant to Edit/Cut page insertion actions. Use
`docs/notes/fusion-template-notes.md` when diagnosing `insert_fusion_generator` or
`insert_fusion_title` failures, template paths, `.setting` files, or `.drfx`
bundles.

DCTL files are programmable color transforms/effects adjacent to LUT and OpenFX
workflows. Use `docs/notes/dctl-notes.md` when diagnosing `.dctl`/`.dctle` discovery,
ResolveFX DCTL plugin behavior, ACES DCTL IDT/ODT setup, or DCTL-as-LUT usage.

Codec plugins are native IO encode plugins that extend Deliver-page render
formats/codecs. Use `docs/notes/codec-plugin-notes.md` when diagnosing missing custom
render formats/codecs, `.dvcp.bundle` packaging, or IOPlugins install paths.

The `fuse_plugin`, `dctl`, and `script_plugin` compound tools (v2.5.0+) write
Fuse plugin source, DCTL files, and Lua/Python scripts into Resolve's install
directories. They are *authoring* tools — every other tool in this server wraps
Resolve's scripting API, while these three emit and install plugin/script
source. Status: lifecycle-verified in DaVinci Resolve Studio 20.3.2.9 for
MCP-marked install/read/list/remove, regular DCTL `refresh_luts`, ACES/Fuse
restart-required classification, Python installed-script execution, and
Python/Lua `run_inline`. Use `docs/kernels/extension-authoring-kernel.md` for the
kernel boundary map, `docs/authoring/fuse-dctl-authoring.md` for the Fuse + DCTL coverage
matrix, and `docs/authoring/script-plugin-authoring.md` for the script DSL spec and the
conversational-execution model. For hand-authoring `.setting` template files
(Edit effects/transitions/titles/generators and Fusion macros) — the format,
control catalog, thumbnail conventions, install paths, and gotchas, plus copyable
starter templates — see `docs/authoring/setting-files/`.

Extension Authoring kernel actions (v2.16.0+) are exposed through
`script_plugin`:

- `extension_capabilities`
- `probe_fuse_lifecycle(name?, kind?, install?, cleanup?)`
- `probe_dctl_lifecycle(name?, kind?, category?, install?, refresh_luts?, cleanup?)`
- `probe_script_lifecycle(name?, language?, category?, install?, execute?, cleanup?)`
- `safe_install_extension(extension_type, name, source?|kind?, dry_run?)`
- `safe_remove_extension(extension_type, name, dry_run?)`
- `refresh_or_restart_required(extension_type, category?)`
- `extension_boundary_report(include_template_matrix?)`

Key behavioral notes for `script_plugin`:
- `run_inline(source, language)` runs ad-hoc Lua/Python in Resolve and returns
  stdout + result — use this for one-off conversational queries against the
  Resolve API instead of building+installing a script.
- `language` accepts `lua`, `py`, or the human-facing aliases `python` and
  `python3`.
- `execute(name, category, language)` runs an installed script; Python stdout
  and stderr are captured, while installed Lua execution can return false from
  the Python bridge even when install/read/list/remove worked.
- Lua scripts: `fusion.Execute()` from the Python bridge is a no-op in
  Resolve 20.x — `_run_inline_lua` works around this with `RunScript` against
  a temp file plus completion-sentinel polling on `app:SetData/GetData`.
- Fuse install path on macOS is `…/DaVinci Resolve/Fusion/Fuses/` (NOT
  `Support/Fusion/Fuses/` as the SDK doc lists). The MCP path helpers handle
  this; if you're staging files manually, use the path the implementation
  emits.
- Resolve picks up new scripts without a restart; new Fuses need a restart
  to register; new DCTLs need `project_settings(action='refresh_luts')`
  (regular LUT category) or a restart (ACES IDT/ODT category).

Tool metadata (v2.17.1+) includes MCP `ToolAnnotations` for read-only,
destructive, idempotent, and external-resource hints. Treat compound tool
annotations as conservative because a single compound tool may expose both probe
and mutation actions behind its `action` parameter. Continue to prefer
`safe_*`, `dry_run`, `probe_*`, `capabilities`, and `boundary_report` actions
before mutating Resolve state.

---

## Two Server Modes

| Mode | Entry point | Tool count | Use when |
|---|---|---|---|
| Compound (default) | `src/server.py` | 32 tools | Most workflows — keeps context lean |
| Granular (full) | `src/server.py --full` | 341 tools | Power users needing one tool per API method |

This skill document covers the **compound server** (the default). Each compound
tool accepts an `action` string and an optional `params` object.

The compound server also registers MCP prompts. Use `davinci_resolve_workflow`
as the compact operating brief, and use `analyze_media` as a slash-command style
entry point for source-safe project, selected-clip, bin, file, or sequence
analysis. The Analyze Media prompt executes directly by default, persists
inspectable reports/artifacts under the project analysis root, requests
`host_chat_paths` visual analysis (frames are extracted to disk and the host
chat finalizes each clip via `media_analysis(action="commit_vision", ...)`),
runs local transcription through the configured backend, and writes metadata
plus source-time Media Pool markers back to the Resolve project unless the
user opts out.

Anti-regression rule: do not silently downgrade media analysis. Source-safe
means source media stays untouched; it does not mean no visuals, no transcript,
no persisted report, no metadata writeback, or no Media Pool markers. Do not
add `include_visuals=false`, `include_transcription=false`,
`publish_metadata=false`, `timed_markers=no`, `session_only=true`, or
`dry_run=true` unless the user explicitly asks for that opt-out, the target is a
raw file path that cannot receive Resolve project writeback. The host_chat_paths
vision protocol is: `analyze_*` returns a deferred payload with absolute
`frame_paths` and a JSON schema; you must read those frames as images (Claude
Code's Read tool handles JPG/PNG natively), produce the JSON, and call
`commit_vision` for each clip. Skipping `commit_vision` leaves the run in
`pending_host_vision_analysis` — surface that explicitly; do not call the
analysis complete.

The deferred payload also includes a `host_tool_choice_hint` block. Hosts that
respect this hint pass it as `tool_choice={type:"tool", name:"media_analysis"}`
on the next API turn, hard-locking the agent into the correct next call. Hosts
that don't recognize the field ignore it — the flow is unchanged for them.

## Local Control Panel

If the user asks to open, launch, or inspect the Resolve MCP control panel, run
this from the repository root:

```bash
venv/bin/python -m src.control_panel
```

The command starts the local control panel and opens the default browser. Use
`--no-open` when running in a headless context, then give the user the printed
localhost URL. The panel is local and single-user; it is an operational surface
for server status, Resolve clips, source-safe analysis jobs, preferences, and
diagnostics as those sections are added.

The **Review tab → History** button opens the timeline-history surface:
per-timeline version chain, brain-edit deltas, manual archive, and rollback.
Backed by `timeline_versioning` MCP actions; see that tool's section below for
the underlying primitives.

---

## Editorial Memory And Decision-Making

When the user asks for cutting, pacing, story shape, suspense, comedy timing, or
tonal reframing, operate like an editor, not just a metadata scanner. Use
`docs/guides/editorial-decision-guide.md` as the project-owned craft reference. The
short version: emotion and story come first, then clarity, rhythm, eye trace,
screen geography, continuity, and coverage variety.

Before analyzing or rebuilding anything, check whether the active project already
contains useful evidence:

- `media_analysis(action="coverage_report", params={"target": {...}})` — the
  pre-flight contract. Pure read; never triggers analysis. Returns per-clip
  state (analyzed / stale / missing / reuse_blocked / superseded_by_relink),
  layer presence, `source_trust` tier, and a `recommended_action`. The response
  carries an `evidence_base` summary string — **lead any editorial or color
  recommendation with that line, before the creative answer.**
- `media_analysis(action="summarize")` for project-wide rollup of warnings,
  motion distribution, and signed-report counts.
- `media_analysis(action="get_report")` when a manifest or report path is known.
- `timeline(action="list")`
- `timeline(action="get_current")`
- `timeline(action="probe_timeline_structure")`
- `timeline(action="source_range_report")`
- `timeline_markers(action="get_all")`
- `media_analysis(action="review_timeline_markers")` when marker imagery matters

Reuse prior analysis unless it is stale, incomplete, missing a modality, or
flagged `superseded_by_relink` because Resolve's source clip was replaced after
analysis ran. Coverage_report surfaces all of these in one read. Do not re-run
visual analysis just because the edit task is new if a current report already
has keyframes, motion variance, and usable visual descriptions. Add
transcription, host_chat_paths vision (followed by commit_vision), marker
review, or source range checks only when that missing evidence changes the
decision. Use `force_refresh=true` only when the user asks for a fresh read or
when cache signatures show the source, prompt, depth, or requested modality has
changed.

Source-trust filtering: `coverage_report` accepts `min_source_trust` (one of
`auto`, `filename`, `low`, `medium`, `high`). Clips below the threshold appear
in `summary.clips_needs_higher_trust` and are reported with
`below_min_source_trust=true`. Use `medium` for routine work, `high` for
shot-matching or look-development passes where confident scene/identity reads
matter.

For finished-video editorial work, scene detection and motion variance are
guardrails, not story. Use them to avoid black frames, flash frames, corrupt
ranges, and accidental cut points. Let transcript, sound events, complete
thoughts, reactions, and decisive visual frames drive the actual edit.

After creating or modifying a timeline variant, do a second pass before calling
the work done:

- `timeline(action="detect_gaps_overlaps")`
- `timeline(action="source_range_report")`
- `timeline_markers(action="get_thumbnail_image")` at important markers and cuts
- Compare each marker name against the Resolve-rendered frame; revise the marker
  or edit if the image contradicts the plan.

Do not depend on personal, external, or workstation-specific editorial context.
For this project, keep the editorial craft reference self-contained in
`docs/guides/editorial-decision-guide.md` and keep this `SKILL.md` focused on
operational use of the MCP.

---

## Color Memory And Decision-Making

When the user asks for color correction, shot matching, look development, LUTs,
DCTLs, DRX grades, Gallery stills, or color-group workflows, use
`docs/guides/color-decision-guide.md` as the project-owned color reference.

Be explicit about the API boundary:

- Directly creatable/control surfaces: CDL values on an existing node, grade
  versions, color-group assignment, LUT assignment on existing nodes, node
  enable/cache state, LUT/DCTL assets, Gallery still import/export, and grade
  copy/export helpers.
- Opaque full-grade surfaces: copied grades, imported/exported `.drx` stills,
  and manually built Resolve node graphs. These can carry full grades, but the
  MCP applies or copies them as packages.
- Not directly creatable from structured params: new node trees, Lift/Gamma/Gain
  wheel values, log/HDR palette values, curves, qualifiers, power windows,
  tracking, Color Warper, and detailed ResolveFX/OFX parameter edits.

Before any color recommendation, run
`media_analysis(action="coverage_report", params={"target": {...},
"min_source_trust": "medium"})` (use `"high"` for shot-matching or
look-development passes). Lead the response with the returned `evidence_base`
line before the grade plan. Coverage_report surfaces relink-superseded clips
that must be re-analyzed before being graded from prior visual descriptions.

For safe color work, start with `timeline_item_color(action="grade_boundary_report")`,
`timeline_item_color(action="grade_version_snapshot")`,
`timeline_item_color(action="probe_node_graph")`, and a Resolve-rendered frame
reference for the target shot or shots. Use thumbnails, contact sheets, Gallery
stills, marker frames, or existing visual analysis reports before writing a
grade, and cite the inspected frames in the response. When the API can safely
provide them, compare matched untreated/bypass, current, and after frames at the
same timecodes, then restore the previous active version or node-enabled state
after any temporary bypass capture. Treat untreated frames as diagnostic
evidence, not as permission to discard an existing creative grade.

Prefer `safe_set_cdl` for small reversible primary corrections. Use DRX/stills
or grade copy only when the user accepts whole-grade replacement/transfer
semantics. Use DCTL/LUT authoring only for reusable mathematical transforms, not
as a substitute for hand-built windows, qualifiers, or tracked secondaries. Do
not apply blind/global grades unless the user explicitly asks for that. When the
user asks to build on or adjust an existing grade, preserve the current
grade/version as the starting point, create or switch to a recoverable
adjustment version, and apply only incremental changes through supported
controls. Do not reset grades, replace graphs, or apply DRX/copy-grade
whole-grade artifacts unless replacement or transfer semantics are explicitly
accepted. Distinguish Resolve's default one-node graph from an existing creative
grade; only describe a creative grade when active tools, LUTs, or other grade
state are present.

For sequence-wide looks, prefer a duplicated timeline, batch creation of
reference/current/look versions across all target clips, and one bulk Resolve
script for repeated version, group, or CDL operations. Use color groups for shared
scene-level intent only when they fit the work: group pre-clip for shared
normalization, clip versions for shot-specific matching, and group post-clip for
the creative look. Sampling can guide a first pass, but final handoff should
state the reviewed scope; short sequences should be checked shot by shot.

---

## Page Context Requirements

DaVinci Resolve is a page-based application. Certain operations only work on
specific pages. Always confirm or switch pages before calling page-sensitive tools.

| Operation category | Required page | How to switch |
|---|---|---|
| Color grading, node graphs, CDL | Color | `resolve_control(action="open_page", params={"page": "color"})` |
| Gallery stills export, `grab_and_export` | Color, Gallery panel open | `resolve_control` + open Gallery panel in Workspace menu |
| Fusion compositions (page comp) | Fusion | `resolve_control(action="open_page", params={"page": "fusion"})` |
| Timeline editing, track operations | Edit or Cut | `resolve_control(action="open_page", params={"page": "edit"})` |
| Fairlight audio | Fairlight | `resolve_control(action="open_page", params={"page": "fairlight"})` |
| Render / deliver | Deliver | `resolve_control(action="open_page", params={"page": "deliver"})` |
| Media import, storage browsing | Media | `resolve_control(action="open_page", params={"page": "media"})` |

When a tool returns an unexpected `False` or an error about context, check whether
you are on the correct page first.

---

## Tool Map

### App Control

**`resolve_control`** — App-level operations.

Key actions:
- `launch` — connect to or start Resolve; call this first if any tool returns a
  "Not connected" error
- `get_version` — returns `{product, version, version_string}`
- `api_truth(query?)` — look up behaviorally-verified facts about quirky/unreliable
  Resolve API behavior (no connection needed); filter by substring
- `verification_stats` — readback-verification tally (verified/contradicted/
  unverified) since server start (no connection needed)
- `get_page` / `open_page(page)` — read or switch the active page
- `get_keyframe_mode` / `set_keyframe_mode(mode)`
- `get_fairlight_presets` — Resolve 20.2.2+; returns available Fairlight
  preset names
- `quit` — terminates Resolve (destructive; confirm with user first)

**`layout_presets`** — Save, load, export, import, delete UI layout presets.

**`render_presets`** — Import and export render and burn-in presets.

---

### Project Management

**`project_manager`** — CRUD on projects.

Key actions: `list`, `get_current`, `create(name, media_location_path?)`,
`load(name)`, `save`, `close`,
`delete(name)`, `import_project(path)`, `export_project(name, path)`, `archive`,
`restore`

Project / Database / Archive kernel actions (v2.15.0+) add guarded project
lifecycle, settings, database, preset, and archive boundary helpers:

- `project_capabilities`
- `probe_project_lifecycle`
- `probe_project_settings(keys?, try_write?, dry_run?)`
- `safe_project_create(name, media_location_path?, dry_run?)`
- `safe_project_export(name, path, with_stills_and_luts?, dry_run?)`
- `safe_project_import(path, name, dry_run?)`
- `safe_project_archive(name, path, src_media=false, render_cache=false, proxy_media=false, dry_run?)`
- `safe_project_restore(path, name, dry_run?)`
- `safe_project_delete(name, close_current?, dry_run?)`
- `safe_set_project_settings(settings, restore?, dry_run?)`
- `project_settings_snapshot(name?)`
- `database_capabilities`
- `safe_set_current_database(db_info, dry_run?, allow_switch?)`
- `preset_lifecycle_probe`
- `project_boundary_report`

Health check and declarative spec (v2.28.0+):

- `lint` — graded project health pre-flight returning `{ok, counts, issues}`.
  Issues (error / warning / info) cover: no project, no current timeline, mixed
  frame rates across timelines, empty timeline, render format unset, color
  science unmanaged, offline media, and unanalyzed clips. Composed from existing
  probes; safe read-only.
- `diff_to_spec(spec_path | spec)` — preview drift between a declarative spec and
  the live project WITHOUT mutating. Returns `{actions, diff, change_count}`.
- `plan_spec(spec_path | spec)` — the ordered action list as a dry run.
- `apply_spec(spec_path | spec, dry_run?, run_hooks?, continue_on_error?)` —
  reconcile the project toward the spec. Idempotent (re-runs are no-ops); color/
  HDR settings apply in dependency order; markers added only when absent; explicit
  `settings` override a named `color_preset`; before/after shell hooks run only
  with `run_hooks=true`. The spec is YAML or JSON:
  `{project, color_preset?, settings?, timelines:[{name, fps?, settings?, markers?}], hooks?}`.
  Note: `apply_spec` reconciles the **currently open or already-existing** project;
  creating a brand-new project from a spec depends on Resolve's `CreateProject`
  succeeding (it can return None when an unsaved project blocks the switch).

Safe project actions require `_mcp_` names and temp paths by default. Database
switching dry-runs by default because Resolve closes open projects when
switching databases. Archive source media/cache/proxy flags are rejected unless
explicitly opted in.

**`project_manager_folders`** — Navigate project folders.

Key actions: `list`, `get_current`, `create(name)`, `open(name)`, `goto_root`,
`goto_parent`

**`project_manager_database`** — Switch databases.

Key actions: `get_current`, `list`, `set_current(db_info)`

**`project_manager_cloud`** — Cloud projects (requires Resolve cloud
infrastructure; most users will not have this).

**`project_settings`** — Project metadata, settings, color groups, and misc
operations on the open project.

Key actions: `get_name`, `set_name(name)`, `get_setting(name?)`,
`set_setting(name, value)`, `get_color_groups`, `add_color_group(name)`,
`delete_color_group(name)`, `export_frame_as_still(path)`,
`load_burnin_preset(name)`, `insert_audio(media_path, ...)`,
`apply_fairlight_preset(preset_name)`,
`project_summary(include_clips?, clip_limit?)` — live structural readout
(current page, timeline count, media-pool inventory by type)

---

### Media

**`media_storage`** — Browse mounted volumes and import files.

Key actions: `get_volumes`, `get_subfolders(path)`, `get_files(path)`,
`import_to_pool(items)` — `items` is a list of file path strings

**`media_pool`** — Full Media Pool management.

Key actions: `get_root_folder`, `get_current_folder`, `set_current_folder(path)`,
`add_subfolder(name)`, `create_timeline(name)`, `import_timeline(path, options?)`,
`import_media(paths)`, `delete_clips(clip_ids)`, `move_clips(clip_ids, target_path)`,
`setup_multicam_timeline(name, clip_ids|angles, sync_mode?, include_audio?, dry_run?)`,
`get_selected`, `set_selected(clip_id)`, `export_metadata(path, clip_ids?)`

Media Pool / Ingest kernel actions (v2.8.0+) add safer agent-facing workflows:
`ingest_capabilities`, `probe_media_pool`, `probe_ingest_item`,
`safe_import_media`, `safe_import_sequence`, `safe_import_folder`,
`organize_clips`, `copy_metadata`, `normalize_metadata`,
`probe_clip_properties`, `metadata_field_inventory`, `safe_relink`,
`safe_unlink`, `link_proxy_checked`, `link_full_resolution_checked`,
`set_clip_marks`, `clear_clip_marks`, `copy_clip_annotations`,
`setup_multicam_timeline`, and
`media_pool_boundary_report`. See
`docs/kernels/media-pool-ingest-kernel.md` for the live-tested support map.

`setup_multicam_timeline` is a helper, not a native multicam API wrapper. It
creates a source-safe stacked prep timeline with one angle per video track,
optional matching audio tracks, and `stack_start`, `source_timecode`, or
explicit `record_frame` placement. Native multicam clip creation, angle
switching, and flattening remain Resolve UI workflows; see
`docs/guides/multicam-setup-guide.md`.

Note: `folder path` arguments use slash notation like `"Master/SubFolder"`.
`"Master"` or `"/"` refers to the root folder.

**`folder`** — Operations on a specific Media Pool folder.

Key actions: `get_clips(path?)`, `get_subfolders(path?)`, `export(path?, export_path)`,
`transcribe_audio(path?, use_speaker_detection?)`, `clear_transcription(path?)`,
`perform_audio_classification(path?)`, `analyze_for_intellisearch(path?, identify_faces?, is_better_mode?)`,
`analyze_for_slate(path?, marker_color?)`, `remove_motion_blur(path?, deblur_option?)` (Resolve 21+;
the last three need AI Extras, and `remove_motion_blur` is confirm-token gated)

**`media_pool_item`** — Read/write clip metadata and properties. All actions
require a `clip_id` (the UUID returned by `GetUniqueId()`).

Key actions: `get_name`, `get_metadata(key?)`, `set_metadata(key, value)`,
`get_clip_property(key?)`, `set_clip_property(key, value)`, `get_clip_color`,
`set_clip_color(color)`, `link_proxy(proxy_path)`, `replace_clip(path)`,
`set_name(name)`, `link_full_resolution_media(path)`,
`replace_clip_preserve_sub_clip(path)`, `monitor_growing_file`,
`transcribe_audio(use_speaker_detection?)`, `clear_transcription`,
`get_transcription` (read back `{text, truncated, status, has_transcription}`;
`truncated` flags when Resolve's preview cut the text off),
`perform_audio_classification`,
`analyze_for_intellisearch(identify_faces?, is_better_mode?)`, `analyze_for_slate(marker_color?)`,
`remove_motion_blur(deblur_option?)` (Resolve 21+; AI Extras / confirm-token gated as noted above),
`get_audio_mapping`, `get_mark_in_out`, `set_mark_in_out`

**`media_pool_item_markers`** — Markers and flags on clips in the Media Pool.
All actions require a `clip_id`.

Key actions: `add(frame, color, name, note, duration)`, `get_all`, `delete_by_color(color)`,
`delete_at_frame(frame)`, `add_flag(color)`, `get_flags`, `set_name(name)`

**`media_analysis`** — Project-scoped media intelligence and guarded metadata publishing.

Media Analysis and editorial-assist actions (v2.17.0+) add source-safe planning,
report reuse, persisted analysis execution, host_chat_paths visual review
(finalized per clip via `commit_vision`), transcription, default Resolve
metadata/marker writeback, and timeline-level editorial helpers.

Key actions: `capabilities`, `install_guidance`, `resolve_output_root`, `plan`,
`coverage_report`, `analyze_file`, `analyze_clip`, `analyze_bin`,
`analyze_project`, `detect_sync_events`, `add_sync_event_markers`,
`publish_clip_metadata`, `commit_vision`, `summarize`, `get_report`,
`build_index`, `index_status`, `query_index`, `start_batch_job`,
`run_batch_job_slice`, `batch_job_status`, `list_batch_jobs`,
`cancel_batch_job`, `resume_batch_job`, `review_timeline_markers`,
`cleanup_artifacts`, `db_status`, `db_ingest`, `get_panel_state`,
`set_panel_state`, `session_start_context`, `update_clip_field`,
`update_shot_field`, `get_field_history`, `revert_field`,
`list_corrections`, `deepen`, `commit_shot_vision`, `vision_pending_sweep`,
`build_embeddings`, `find_similar`, `detect_entities`, `commit_entities`,
`list_entities`, `prepare_bin_briefing`, `commit_bin_summary`,
`detect_shot_relationships`, `commit_shot_relationships`, and
`list_shot_relationships`.

**Cross-clip entities + bin briefing v2 (v2.44.0+).** Recurring
people/places/props across a project's media, found cheaply and confirmed
with ONE vision call per cluster:
- `detect_entities(threshold?, min_cluster_size?)` clusters the v10 CLIP
  frame vectors (build visual embeddings first), writes provisional entity
  rows + appearances, and returns a deferred payload with one
  representative frame per cluster (caps pre-checked, estimate inlined).
  The host chat reads those frames and calls
  `commit_entities(entities=[{entity_index, kind, label, description,
  confidence, merge_with?}], vision_token)` — conservative labels only
  (describe what's visible; never guess names). `merge_with` collapses
  clusters that show the same entity.
- `list_entities` returns labeled entities with per-clip/shot appearances;
  the panel's Review page shows a "Recurring across this bin" card.
- `prepare_bin_briefing` returns entities + per-clip summaries (text-only,
  no vision cost); the host writes a colleague-style markdown briefing and
  calls `commit_bin_summary(briefing, briefing_token)`, which lands in
  `memory/bin_summary.md` above the v2.0 aggregate.

**Cross-shot relationships (v2.49.0+).** Pattern recognition only (spec §4 —
no editorial suggestions): `same_setup_as` / `alt_take_of` (symmetric) and
`continues_from` (directional; the source shot continues from the target).
- `detect_shot_relationships(setup_threshold?, alt_take_threshold?,
  continues_band?, max_candidates?)` — pairwise cosine over the per-shot
  visual vectors (build visual embeddings first; raise
  `max_frames_per_clip` if shot coverage is partial), plus transcript
  continuity as a second signal for `continues_from`. Returns a deferred
  payload with a representative frame PAIR per candidate (caps pre-checked,
  two frames per candidate). Candidates live only in the detection-state
  stash until committed — re-detect replaces them.
- The host chat reads BOTH frames of each pair and calls
  `commit_shot_relationships(relationships=[{candidate_index, verdict:
  confirm|reject, relationship_type?, confidence?}], vision_token)`.
  Confirm only what the frames show; reject lookalikes. Overriding the
  suggested type is allowed. Committed rows supersede prior machine rows
  for the same pair.
- `list_shot_relationships(clip_id?, shot_uuid?, relationship_type?)` —
  current rows with clip/shot context on both ends. The shot page's
  Relationships group fills from these rows, and `plan_swap` prefers
  confirmed `alt_take_of` alternates over raw cosine (the rationale states
  which basis ranked each alternate).

**Embeddings + similarity (v2.43.0+).** Local-compute semantic search; no
vendor tokens, so nothing here touches the caps ledger. Backends are
detected, never installed (capabilities lists them with install guidance):
text = ollama serving `nomic-embed-text` or sentence-transformers; visual =
open_clip (ViT-B-32, needs torch); audio (v2.51.0+) = CLAP via
`transformers` (laion/clap-htsat-unfused, preferred) or the `laion_clap`
package — needs torch + ffmpeg.
- `build_embeddings(kinds=["text","visual","audio"]?, clip_id?)` —
  idempotent; embeds clip summaries, shot descriptions (+ deep field
  groups), transcript segments, and sampled frames (per-shot visual vector
  = mean of its frames'). `kinds=["audio"]` embeds one CLAP window per shot
  (center-cropped to ~10s, piped from the source media as raw PCM —
  read-only, no temp files) plus a clip-level mean vector; clips whose
  media is offline are reported in `skipped_missing_media`. Only re-embeds
  entities whose content changed.
- `find_similar(text=… | clip_id=… | clip_id+shot_index,
  kind="text"|"visual"|"audio", entity_types?, limit?)` — brute-force
  cosine over the project's vectors. Free-text visual queries use the CLIP
  text encoder ("cracked windshield" finds the frame); free-text audio
  queries use the CLAP text encoder ("engine revving" finds the shot).
  Results carry scores plus clip/shot/segment context.
The panel search box gains a `Semantic` toggle when a text backend is
detected. Vectors live in the per-project DB (schema v10).

**Deep shot-level vision tier (v2.42.0+).** Opt-in, estimate-first. Two
entry points share one per-shot schema (Visual / Content / Production /
Editorial / Cuttability / description / confidence):
- `depth="deep"` on any analyze action extends the deferred host-vision
  payload with `deep_shot_schema`; each `shot_descriptions` entry must carry
  the field groups. The first deep run returns `confirmation_required` with
  a token-cost estimate — re-call with `confirm_deep=true`. Caps still apply.
- `deepen(clip_id|clip_dir, shot_index?|shot_indices?)` runs the pass
  post-hoc on an already-analyzed clip. First call returns the estimate +
  `confirm_token`; re-call with the token to get the deferred payload, read
  its `frame_paths`, and commit via
  `commit_shot_vision(clip_id, shots=[{shot_index, ...groups...}],
  vision_token)`. Deep fields land as `vision_deep_v1` provenance rows;
  human corrections always survive. Shots with no sampled frames on disk get
  1–2 frames re-extracted via ffmpeg (read-only on source media).
`vision_pending_sweep(expire?, max_age_days?, reoffer?)` lists clips stuck
in `pending_host_analysis`; `reoffer=true` returns each clip's stored
deferred payload to finish the run, `expire=true` stamps them
`expired_host_analysis` so pendings never linger silently.

**DB-canonical analysis store (v2.41.0+).** The per-project SQLite DB
(`_soul/timeline_brain.sqlite`, schema v9+) is the source of truth for clip
analysis; `analysis.json` is a derived export written in lockstep. Analysis
runs write rows first (clips, shots, per-field subjective provenance,
transcript segments, sampled frames, QC observations) and then export the
JSON. Human corrections recorded via `update_clip_field` / `update_shot_field`
live as row-level provenance and always survive re-analysis. Readers
(panel API, exports) load DB-first and fall back to `analysis.json` for
reports that predate v9. `db_status` reports schema version + row counts;
`db_ingest` migrates an existing project's JSON reports (and
`corrections.json` sidecars) into the DB — run it once on older analysis
roots.
The tool never installs
dependencies and validates that outputs stay under
`davinci-resolve-mcp-analysis` project roots rather than beside source media.
Executed Resolve-target analysis defaults to running, persisting inspectable
artifacts, and publishing metadata plus Media Pool clip markers. Use
`dry_run=true`, `publish_metadata=false`, `timed_markers=no`, or
`session_only=true` with `keep_artifacts=false` to disable those defaults for a
run. Persisted analysis refreshes the local SQLite search index automatically unless
`auto_build_index=false` is set; `build_index` remains the manual rebuild action
for existing reports. `quick` uses ffprobe metadata; `standard` adds ffmpeg
read-through checks,
cut-boundary analysis from full-stream scene detection, flash-frame candidates,
motion/variance scoring, analysis keyframes, and sidecar reports.
`depth` controls which layers run; a separate `sampling_mode` controls how many
frames each clip gets for visual analysis (and thus token cost): `fixed`
(Economy, flat content-blind frames), `per_minute` (Balanced, frames scale with
duration), `adaptive_capped` (Thorough, content-aware bounded to
`[frame_floor, frame_ceiling]` — recommended/default), or `adaptive` (Thorough
uncapped). When no default is saved, the first analyze returns
`confirmation_required` with a `sampling_mode_prompt`; choosing a mode saves it
as the default. Pass `sampling_mode` per call for a one-off. The mode owns frame
count — `analysis_caps.frames_per_clip` is a safety ceiling above it, not the
primary dial.
By default, planning checks the active project's analysis root and bounded
related project-version roots for existing reports, then marks matching clips
`skip_execution=true` when those reports already contain the requested
technical, motion, transcription, and vision layers.
Resolve clip records also carry the published third-party
`davinci_resolve_mcp.analysis_report_path` when metadata writeback has run; use
that provenance as a first-class reuse hint even if the report lives under a
previous project-version analysis root.
The planner also maintains an `analysis_registry.json` under the analysis base
root. This registry indexes report paths by source path, clip id, media id, and
signature so project renames and versioned Resolve projects can still find prior
work quickly.
Reports include cache signatures with source stat, depth, frame budget, prompt
hash, and requested modalities. Use `force_refresh=true` for a fresh read,
`max_report_age_days` for freshness limits, and `reuse_policy="fresh"` when
unsigned older reports should not be reused. Pass `reuse_existing=false` only
when the user explicitly wants to ignore memory; pass
`search_related_project_roots=false` only for intentionally isolated runs.
If Resolve metadata shows prior MCP analysis but the planner cannot validate a
matching report, execution returns `status="reuse_blocked"` instead of silently
reanalyzing. Treat that as a project-memory integrity warning; restore the
report or pass `force_refresh=true` only when the user explicitly wants fresh
analysis.
Transcription, visual analysis, metadata writeback, and Media Pool marker
writeback are default-on. Vision uses
`vision.provider="host_chat_paths"`: analyze actions extract representative
frames to disk under the project analysis root and return a deferred payload
containing absolute `frame_paths`, a `shot_table` mapping each detected shot
range to its in-shot `frame_indices`, the JSON schema, and a `commit_action`.
The host chat must read those frames as local images, produce JSON per the
schema (including one `shot_descriptions` entry per `shot_index` in the
`shot_table`, grounded only in the frames listed for that shot), and call
`media_analysis(action="commit_vision", params={clip_id, visual,
vision_token})` per clip to merge the visual report, rebuild Media Pool clip
markers, and publish vision-dependent metadata to Resolve. Each Resolve shot
marker inherits its description from `shot_descriptions[shot_index]`; missing
entries fall back to an in-range `analysis_keyframe` and finally to a
clip-summary-tagged fallback — never to a neighbour shot's description. The manifest exposes
`vision_pending=True` and `pending_action` so callers know what is incomplete.
Pass `include_visuals=false`, `include_transcription=false`,
`publish_metadata=false`, or `timed_markers=no` to opt out. Agents must not add
those opt-out flags preemptively; use them only when requested or when a target
boundary requires it. Standard/deep runs prioritize first/last usable frames
plus before/after cut-boundary frames as the sampled set. Skipping
`commit_vision` leaves the run in `pending_host_vision_analysis` — that is a
failure mode to surface, not a silent downgrade. The local mock providers are
for tests and do not send frames off-machine.

When creating timelines through `media_pool`, use `if_exists="reuse"` for
idempotent reruns, `if_exists="version"` for deliberate alternate cuts, and
`if_exists="fail"` when duplicate names indicate a workflow error.
Use `detect_sync_events` before multicam setup, deliverable QC, or single-camera
sync review when the user needs likely 2-pop or slate-clap locations. It reads
source audio through FFmpeg/FFprobe only, returns advisory frames/timecodes and
per-file `record_offset` suggestions, and never installs FFmpeg automatically.
It also returns marker suggestions; `add_sync_event_markers` remains an explicit
marker-write action for standalone sync detections.
Use `publish_clip_metadata` when the user wants analysis to become searchable
inside Resolve. It analyzes or reuses reports, proposes field-specific merges
for `Description`, `Comments`, `Keywords`, `People`, and optional slate-derived
fields, stores provenance in third-party metadata, and writes metadata plus
source-time markers by default for executed Resolve-target analysis. Disable a
write run with `dry_run=true`, `publish_metadata=false`, or `timed_markers=no`.
`review_timeline_markers` creates a labeled
Resolve-rendered marker contact sheet plus JSON sidecar; with
`vision.enabled=true` it returns a host_chat_paths review payload (image_path +
prompt) so the host chat can read the sheet and answer inline — no commit step
required for marker review.

Before calling `analyze_*`, prefer `summarize` and `get_report` to discover
existing reports for the active project. If reports exist, use them as the
working memory for edit decisions and only request fresh analysis when a missing
layer changes the decision. If a user is
making story or audio-spine decisions and transcription is available but disabled,
tell them that transcript analysis may materially improve the edit instead of
silently skipping it. Resolve-native transcription changes project state; use it
only when that mutation is intentional.

---

### Timelines

**`edit_engine`** — Evidence-driven edit loops (v2.45.0+): selects assembly,
tighten, swap.

Every loop is plan → confirm → execute. plan_* actions are dry-run by
construction: they query the DB-canonical analysis store and return a
per-decision rationale plus a stored `plan_id` (plans persist under
`memory/edit_plans/` with a content fingerprint, so a stale plan cannot run
against a changed project). execute_* actions require a `confirm_token`, run
under the version-on-mutate hook, and return before/after duration and
clip-count readback plus `brain_edits` rationale rows.

- `plan_selects(min_select_potential?, max_duration_seconds?, max_shots?,
  timeline_name?, analysis_root?)` — ranks shots by deep-tier
  `editorial.select_potential` / best moments (clip-level fallback for
  standard-analyzed clips), story-spine order.
  `execute_selects(plan_id)` creates a NEW selects timeline from the plan's
  per-shot source ranges — additive; nothing existing is touched.
- `plan_tighten(timeline_name?, target_ratio?, min_pause_seconds?,
  handle_seconds?, include_audio?)` — dead-air lifts from transcript-gap
  evidence for each timeline item (items without transcripts are reported in
  `skipped`, never silently trimmed). `execute_tighten(plan_id)` assembles a
  tightened VARIANT timeline from the plan's keep ranges — true partial
  trims; the original timeline is never mutated. v2.52.0+: kept ranges mirror
  onto each item's linked audio track(s) so the variant is audible (a
  speech-driven cut was previously silent — #67); pass
  `include_audio=false` for a video-only assembly, and the
  `execute_tighten` readback carries an `audio_accounting` block.
- `plan_swap(timeline_start_frame | item_name, kind="visual"|"text",
  limit?)` — alternates for one timeline item via the similarity index,
  filtered to shots long enough to fill the slot exactly.
  `execute_swap(plan_id, alternate_index)` replaces the item in place
  (lift + positioned append at the same record frame) on the
  version-archived timeline. v2.48.0+: the lift is scoped to the target's
  video track plus its linked audio tracks (GetLinkedItems with a
  media-id fallback), and `readback` carries per-track-type
  `track_counts` plus an `audio_accounting` block so swap symmetry is
  verifiable. `execute_tighten` readback gains `structural_diff` (source
  vs variant, via the same engine as `diff_timelines`); `execute_selects`
  readback gains a `usage_summary`.
- `list_plans(limit?)` / `get_plan(plan_id)`.

The engine needs the analysis substrate: analyzed clips in the DB (run
`db_ingest` on older roots), transcripts for tighten, and visual embeddings
(`build_embeddings(kinds=['visual'])`) for swap.

Plans are reviewable in the control panel (Media → Edit Plans, v2.47.0+):
decisions/lifts/alternates with thumbnails and rationale, deep links to shot
pages, and a copyable per-kind execute prompt. The panel never executes —
when the user says they reviewed a plan there, execution still comes back
through chat with the confirm-token gate.

**`timeline_versioning`** — Version-on-mutate, archive, rollback, brain-edit history (C6).

Every destructive timeline op (compound, captions, ripple delete, gap close,
retime, marker batch, track add/delete, take swaps, color grade, etc.) auto-
archives the working timeline to the `Archive` bin under an `analysis_run_id`
before the mutation runs. This tool surfaces and controls that history.

Key actions:
- `begin_run(label?, initiator?, analysis_run_id?)` — open a multi-step run.
  Subsequent destructive calls auto-thread this run's ID, so a brain
  operation that touches 5 clips creates ONE archive + 5 logged edits
  instead of 5 separate archives.
- `end_run(analysis_run_id?)` — close the run; aggregates brain_edits into
  per-metric rollup in `analysis_runs.summary_json`.
- `list_runs(limit?)` — recent runs newest first with their summaries.
- `archive_current(reason?, analysis_run_id?)` — manual checkpoint of the
  current timeline. Idempotent within an `analysis_run_id`. Also captures a
  structural snapshot (every clip's placement, written to `timeline_clip_usage`)
  and a thumbnail (when the Color page has a current clip).
- `list_versions(timeline_name)` — version chain, oldest first. Each row
  includes `archived_timeline_name`, `created_at`, `analysis_run_id`,
  `initiator`, `thumbnail_path`, and `drt_export_path` (set when the version
  was retention-collapsed to disk).
- `diff_versions(timeline_name, from_version, to_version)` — structural diff
  between two snapshots: `{added, removed, moved, trimmed, summary}`. `trimmed`
  lists clips kept in place but re-trimmed (carries `out_frame_before`); `summary`
  has per-bucket counts plus `before_clip_count`/`after_clip_count`. Clips are
  keyed by media_pool_item_id and timeline position.
- `diff_timelines(from_timeline, to_timeline)` (v2.48.0+) — the same
  structural diff between two LIVE timelines by NAME, read-only, no archived
  snapshots needed. Built for edit-engine variants (tighten/selects produce
  new-name timelines with no shared version chain). For unrelated timelines
  everything reports as added/removed.
- `get_history(timeline_name?, analysis_run_id?, limit?)` — brain-edit rows
  with `edit_type`, `target_metric`, `before_value`, `after_value`, `delta`,
  `rationale`, and `initiator`. Filter by timeline or run; defaults to 50.
- `media_pool_changes(analysis_run_id?, media_pool_action?, limit?)` —
  destructive media-pool history (deletes, replaces, relinks) from the
  `media_pool_changes` table. Separate from brain_edits because the
  addressable entity is a media_pool_item, not a timeline.
- `rollback(timeline_name, version, analysis_run_id?)` — archive current first,
  then duplicate the archived version back as a new `<name>_rolled_back_<HHMMSS>`.
- `prune(timeline_name, keep_n=10)` — collapse old versions to `.drt` exports
  under `<project>/_soul/timeline_versions/<slug>/` and remove them from the
  bin. DB row preserved with `drt_export_path` populated for later rollback.
- `registry()` — cross-project brain-edits registry that lives at the analysis
  base root (one level above each project_root). Mirrors `analysis_registry.json`.

**Strict mode** — `timeline.delete_timelines`, `timeline.delete_track`, and
`timeline.delete_clips(ripple=True)` REFUSE to run when the pre-mutation
archive can't be created. Pass `strict=true` on any destructive op to opt in.
This prevents catastrophic ops from proceeding when versioning is broken.

**Action filtering** — `timeline_item.set_property(key='Notes')` and
`timeline.set_clip_property(key='Notes'|'Comments')` bypass versioning because
free-text metadata isn't worth archiving. See `NO_ARCHIVE_ON_KEYS` in
`src/utils/destructive_hook.py` to add more.

**Preferences** — `timeline_versioning_auto_save_after_archive` (default false)
triggers `project.SaveProject()` after every archive so Resolve crashes don't
lose history. Configure via the `setup` tool's preferences.

### Analysis Caps

`media_analysis` honors a project-wide caps preset that controls 7 dimensions
of analysis cost: response payload size, frames per clip, vision tokens per
clip / per job / per day, wall-clock seconds per call, and the maximum frame
image dimension before upload. Four named presets, plus per-field overrides.

| Dimension                     | minimal | standard | generous  | unlimited |
|------------------------------:|--------:|---------:|----------:|----------:|
| response_chars                | 5,000   | 25,000   | 100,000   | none      |
| vision_tokens_per_clip        | 5,000   | 25,000   | 100,000   | none      |
| frames_per_clip               | 4       | 8        | 24        | none      |
| vision_tokens_per_job         | 50,000  | 250,000  | 1,000,000 | none      |
| vision_tokens_per_day         | 100,000 | 500,000  | 2,000,000 | none      |
| wall_clock_seconds_per_call   | 30      | 90       | 300       | none      |
| max_frame_dim_pixels          | 512     | 768      | 1280      | none      |

Default preset: `standard`. Set via `media_analysis(action="set_caps_preset",
preset=…, overrides={...})` or the dashboard's **Preferences → Analysis Caps**
panel. Inspect via `media_analysis(action="get_caps")` which returns the
effective values + a usage rollup (clip / job / day) with percent-consumed.
`media_analysis(action="get_usage", scope="day"|"job"|"clip")` returns raw
counts for one scope. Usage is tracked in
`<project>/_soul/timeline_brain.sqlite` (`analysis_token_usage` table).

Resolve 21's local AI ops (audio classification, IntelliSearch, slate,
motion-deblur, speech generation) run on Resolve's own GPU/AI engine and do NOT
spend the Claude analysis token budget — they are tracked separately in the
`resolve_ai_op_usage` table. Inspect with
`media_analysis(action="get_resolve_ai_usage", session_only?, op?, limit?)` →
`{summary, recent}` (invocation counts, wall-clock, and files/bytes created by
`remove_motion_blur` / `generate_speech`). The control panel shows the same as a
read-only "Resolve 21 AI ops" card.

The two media-creating ops also have **soft governance tiers**
(`off`|`lenient`|`standard`|`strict`, default `standard`) capping per-session
deblur/speech runs, bytes, and render time. It is advisory — the confirm dialog
warns when near/over the tier but never blocks (the ops are confirm-gated).
Inspect/set with `media_analysis(action="get_ai_governance")` and
`media_analysis(action="set_ai_governance", preset=…, mode=…, overrides={...})`.
Governance `mode` is `advisory` by default (preview warnings only); `enforce`
blocks an over-tier run with `GOVERNANCE_BLOCKED` until the tier is raised, the
mode is relaxed, or the op is re-called with `override_governance=true`. Ledger
rows, brain edits, and timeline versions record the acting instance
(`stdio` / `network-sse` / `network-http` / `control-panel` / `batch-cli` + pid)
in an `actor` field; the AI
Console's Governance section offers a tier picker + consumption gauges.

The caps layer:
- Slices `frame_paths` to `frames_per_clip` before the host LLM sees them.
- Downscales each sampled frame in place to `max_frame_dim_pixels` (Pillow;
  degrades silently to original-resolution upload if not installed).
- Trims the analysis response payload to `response_chars`, dropping the
  largest list/string fields first and marking the trim under `_trimmed`.
- Records actual token usage from the host's `commit_vision` payload's
  optional `usage: {vision_tokens, ...}` block. Hosts that don't report
  tokens still get `frames_uploaded` recorded.

Wall-clock timeout + cumulative-budget refusal are implemented in
`src/utils/analysis_caps.py` and ready to hook at additional call sites in
the analysis pipeline; the initial integration is at frame sampling +
response construction + commit_vision usage recording.

**Declared edits** — when the brain (or an agent acting deliberately) wants to
measure an edit, pass `metric`, `direction`, and `rationale` in the params of
the destructive call. The hook captures `before_value` and `after_value` from
the live timeline (using the metric vocabulary in `brain_edits.py`) and writes
them to the `brain_edits` row. Without these, the edit is still logged but with
null metric — gives history without requiring deliberate intent.

Supported metrics: `duration_seconds`, `avg_performance_score`, `clip_count`,
`gap_count`, `total_gap_seconds`, `redundancy_score`.

**`timeline`** — Timeline operations: tracks, clips, import/export, generators.

Key actions:
- `list` — all timelines in the project
- `get_current` — current timeline info
- `set_current(index)` — switch timeline by 1-based index
- `get_track_count(track_type)` — track_type: `"video"`, `"audio"`, `"subtitle"`
- `get_transcript(with_timecodes?)` — read the subtitle track(s) as transcript
  text `{text, cue_count, has_subtitles, cues}`
- `propose_cuts(cues?, long_pause_frames?)` — DRY-RUN: mechanically detect
  candidate cuts (fillers, long pauses, repeats) from the transcript; proposes only
- `apply_cuts(cuts, dry_run?, confirm_token?)` — apply a CutList as lift/ripple
  deletes. DRY-RUN by default; applying is destructive (confirm-token gated, a
  timeline version is archived first). Cuts apply latest-first
- `add_track(track_type, sub_type?)` / `delete_track(track_type, index)`
- `get_items(track_type, index)` — items on a track
- `clip_where(track_type?, track_index?, name_contains?, duration_lt?, duration_gt?)` —
  (v2.28.0+) return clips on the current timeline matching named filters (AND),
  instead of walking tracks by hand. Filters may be passed inline or as a
  `filters` dict; a mistyped filter name is rejected rather than silently
  matching everything. Returns `{clips, match_count, total_clips}`.
- `delete_clips(clip_ids, ripple?)` — IDs are unique IDs from `get_items`
- `duplicate_clips(clip_ids?, selected?, target_track_index?, track_offset?, placement?, record_frame?, record_frame_offset?, copy_properties?, include_linked?)` —
  duplicate existing video timeline items by re-appending the same Media Pool
  item with the same source trim; `selected=True` uses Resolve's selected/current
  item when available, `placement` supports `"same_time"`, `"offset"`,
  `"at_playhead"`, `"track_above"`, `"after_source"`, and `"next_gap"`, and
  `include_linked=True` duplicates linked audio and restores link state.
  `copy_properties` can copy `transform`, `crop`, `composite`, `audio`,
  `retime`, `dynamic_zoom`, `scaling`, `stabilization`, `clip_color`,
  `markers`, `flags`, `enabled`, `cache`, `voice_isolation`, `fusion`,
  `grades`, `takes`, and `keyframes`; `transitions` is accepted but reported
  unsupported because Resolve's public scripting API does not expose transition
  cloning. `copy_keyframes=True` adds the `keyframes` group.
- `copy_clips(...)` / `move_clips(...)` — same safe append path; `move_clips`
  deletes successfully duplicated source items afterward
- `copy_range` / `duplicate_range` — copy exact video/audio source segments
  from `start_frame`/`end_frame` or mark in/out to `record_frame`
- `overwrite_range` — delete whole destination overlaps, then copy the exact
  range segment
- `lift_range` — delete whole items in a range; partial overlaps require
  `allow_partial_item_delete=True` because Resolve does not expose a safe
  partial lift primitive here
- `story_spine_report` — read markers, source ranges, and audio/video structure
  into an editor-facing beat report
- `create_variant_from_ranges(name, ranges, markers?, cdl?, dry_run?)` — create
  a guarded timeline variant from declarative source ranges, optional markers,
  transforms, and CDL
- `bulk_set_item_properties(ops, dry_run?, readback?)` — apply transforms,
  crop/composite/audio/property groups to many timeline items in one call
- `apply_look_to_items(target_ids, cdl?|copy_from_item_id?, dry_run?)` — apply a
  normalized CDL and/or copy a source grade to multiple video items
- `thumbnail_contact_sheet` / `marker_thumbnail_review` — sample Resolve-rendered
  thumbnails under the project analysis root for visual verification
- `edit_kernel_capabilities` — report supported, partially supported, and
  unsupported timeline edit kernel behavior
- `probe_edit_kernel_item(clip_ids? selected? timeline_item?)` — read-only
  capability/property probe for timeline items, including available item
  methods, `GetProperty()` values, known property keys, keyframe counts, and
  linked item summaries
- `title_property_scan(clip_id|timeline_item_id|timeline_item)` — inspect
  undocumented Edit-page title/generator `TimelineItem.GetProperty()` keys
- `set_title_text(clip_id|..., text, property_key?, as_styled_xml?, try_plain_first?, try_heuristic_keys?, readback?)`
  / `bulk_set_title_text(ops, ...)` — update title text via explicit or scanned
  keys when the current Resolve build accepts the `SetProperty()` write
- `export(path, type, subtype?)` — type: `"AAF"`, `"EDL"`, `"FCPXML"`, `"DRT"`, etc.
- `insert_generator(name)`, `insert_title(name)`, `insert_fusion_title(name)`
- `get_mark_in_out`, `set_mark_in_out(mark_in, mark_out, type?)`
- `duplicate(name?)` — duplicate the current timeline
- `get_voice_isolation_state(track_index)` / `set_voice_isolation_state`
- `extract_source_frame_ranges(handles?, gap_max?, skip_extensions?)` — return
  inclusive source frame ranges for current-timeline video clips, with fixed
  handles or gap-only auto handles when `handles=0`

Timeline Conform / Interchange kernel actions (v2.13.0+) add live-tested
structure, interchange, comparison, missing-media, and relink-planning helpers:

- `conform_capabilities`
- `probe_timeline_structure(track_types?, include_markers?, include_clip_properties?)`
- `detect_gaps_overlaps(track_types?, min_gap?)`
- `source_range_report(handles?, merge?)`
- `export_timeline_checked(path, format?|type?, subtype?, require_temp_path?, dry_run?)`
- `import_timeline_checked(path, options?, timeline_name?, import_source_clips?, require_temp_path?, dry_run?)`
- `compare_timelines(right_timeline_id?|right_timeline_index?|left_snapshot?, right_snapshot?)`
- `probe_interchange_roundtrip(format?, output_dir?, cleanup_imported?)`
- `detect_missing_media(sanitized?|sanitize_paths?, omit_raw_paths?)`
- `build_relink_plan(search_roots, max_depth?, max_seconds?, max_files_scanned?, skip_search_when_volume_missing?, sanitized?)`
- `conform_boundary_report`

For offline media, prefer the sanitized readback first:
`timeline(action="detect_missing_media", params={"sanitized": true})`. The
response includes a `diagnosis` block with deduplicated Media Pool items,
missing volume roots, sample basenames, and a recommended next step. If a source
volume such as a camera card is not mounted, `build_relink_plan` skips broad
search by default and reports `skip_reason="missing_source_volume_not_mounted"`;
mount the volume or pass `skip_search_when_volume_missing=false` only when a
bounded scan of approved roots is intentional.

Audio / Fairlight kernel actions (v2.14.0+) add live-tested audio state,
mapping, voice-isolation, sync, transcription, subtitle, and Fairlight boundary
helpers:

- `audio_capabilities`
- `probe_audio_track(track_index?)`
- `probe_audio_item(track_type?, track_index?, item_index?)`
- `safe_set_audio_properties(properties, restore?, dry_run?, track_type?, track_index?, item_index?)`
- `audio_mix_capability_report(...)`
- `voice_isolation_capabilities(track_index?, track_type?, item_index?)`
- `audio_mapping_report(clip_ids?)`
- `safe_auto_sync_audio(clip_ids|selected, settings?, dry_run?)` — `settings`
  accepts human-readable keys: `method`/`mode` (`waveform`|`timecode`),
  `channel` (`auto`|`mix`|int), `retain_embedded_audio`, `retain_video_metadata`.
  Unrecognized keys are dropped and echoed back in `ignored_settings` rather than
  silently failing the call.
- `transcription_capabilities(clip_ids?|selected?)`
- `subtitle_generation_probe(settings?, allow_generate?)` — `settings` accepts
  human-readable keys resolved to live `SUBTITLE_*`/`AUTO_CAPTION_*` enums:
  `language` (e.g. `english`, `korean`), `preset` (`default`|`teletext`|`netflix`),
  `line_break` (`single`|`double`), `chars_per_line` (1–60), `gap` (0–10).
  Unrecognized keys/values are dropped and echoed in `ignored_settings`; generation
  is read-back verified against the subtitle track count.
- `fairlight_boundary_report`

**`timeline_markers`** — Markers and playhead on the current timeline.

Key actions: `add(frame|frame_id|timecode?, color?, name?, note?, duration?)`, `get_all`,
`get_current_timecode`, `set_current_timecode(timecode)`,
`get_current_video_item`, `get_thumbnail`, `get_thumbnail_image`

Review Annotation kernel actions (v2.10.0+) add a unified review layer across
timeline, timeline item, and media pool item scopes: `annotation_capabilities`,
`probe_annotations`, `normalize_marker_payload`, `copy_annotations`,
`move_annotations`, `sync_marker_custom_data`, `clear_annotations_by_scope`,
`export_review_report`, and `annotation_boundary_report`. See
`docs/kernels/review-annotation-kernel.md` for the live-tested scope and boundary map.

For `add`, omit `frame`/`timecode` to create the marker at the current playhead.
The compound tool accepts `frame`, `frame_id`, and `frameId` aliases.

Note: `get_thumbnail` returns raw pixel data from `GetCurrentClipThumbnailImage()`.
The dictionary includes `data` (raw bytes as a Python bytes-like object),
`format`, `width`, `height`, `noOfComponents`, and `depth`. This reflects the
current frame as rendered by Resolve — including any color grading or effects
applied — which is different from reading the source file directly.

Use `get_thumbnail_image` when the MCP client can display image content directly.
It converts the same Resolve thumbnail payload to PNG bytes without writing a
file to disk.

**`timeline_ai`** — AI/ML analysis on the current timeline.

Key actions: `create_subtitles(settings?)` (human-readable settings resolved to
`SUBTITLE_*`/`AUTO_CAPTION_*` enums + read-back verified — see
`subtitle_generation_probe`), `detect_scene_cuts`,
`grab_still`, `grab_all_stills(source?)`, `analyze_dolby_vision`

---

### Timeline Items

Timeline items are identified by `track_type`, `track_index`, and `item_index`
(all default to `"video"`, `1`, `0` respectively — the first clip on the first
video track). Always retrieve item IDs via `timeline.get_items` before operating
on specific items.

**`timeline_item`** — Properties, transform, speed, audio, keyframes.

Key actions:
- `get_property(key?)` / `set_property(key, value)` — raw property access
- `get_name` / `set_name(name)`
- `get_duration`, `get_start`, `get_end`
- `get_retime` / `set_retime(process?, motion_estimation?)`
  - process: `"nearest"`, `"frame_blend"`, `"optical_flow"` (or 0–3)
  - motion_estimation: integer 0–6
- `get_transform` / `set_transform(Pan?, Tilt?, ZoomX?, ZoomY?, RotationAngle?, ...)`
- `get_crop` / `set_crop(CropLeft?, CropRight?, CropTop?, CropBottom?, ...)`
- `get_composite` / `set_composite(Opacity?, CompositeMode?)`
- `get_audio` / `set_audio(Volume?, Pan?, AudioSyncOffset?)`
- `get_voice_isolation_state` / `set_voice_isolation_state(state)` — Resolve
  20.1+; audio timeline items only
- `get_keyframes(property)`, `add_keyframe(property, frame, value)`,
  `modify_keyframe`, `delete_keyframe`, `set_keyframe_interpolation`
  - interpolation values: `"Linear"`, `"Bezier"`, `"EaseIn"`, `"EaseOut"`, `"EaseInOut"`
- `get_unique_id` — use this to get the ID for other tool calls
- `get_media_pool_item` — get the source clip from the Media Pool

**`timeline_item_markers`** — Markers, flags, clip color on timeline items.

**`timeline_item_fusion`** — Fusion comp management on timeline items.

Key actions: `add_comp`, `get_comp_count`, `get_comp_names`, `export_comp(path, index)`,
`import_comp(path)`, `delete_comp(name)`, `load_comp(name)`, `rename_comp`,
`get_cache_enabled`, `set_cache(value)` — value: `"Auto"`, `"On"`, `"Off"`

**`timeline_item_color`** — Color grading on timeline items. Requires Color page
for most operations.

Key actions:
- `set_cdl(cdl)` — cdl: `{NodeIndex, Slope, Offset, Power, Saturation}`
  - Slope/Offset/Power can be arrays `[R, G, B]` or strings like `"1.0 1.0 1.0"`
- `add_version(name, type?)`, `load_version(name, type?)`, `get_version_names(type?)`
  - type: `0` = local, `1` = remote
- `assign_color_group(group_name)`, `remove_from_color_group`
- `export_lut(type, path)`
- `reset_all_node_colors` — Resolve 20.2+; resets node colors for the active
  clip version
- `stabilize`, `smart_reframe`
- `create_magic_mask(mode)` — mode: `"F"` forward, `"B"` backward, `"BI"` bidirectional
  (requires DaVinci Neural Engine and Color page)

Color / Grade kernel actions (v2.11.0+) add safer grade inspection and
boundary helpers: `grade_capabilities`, `probe_grade_item`,
`probe_node_graph`, `safe_set_cdl`, `safe_copy_grade`, `safe_apply_drx`,
`safe_export_lut`, `grade_version_snapshot`, `grade_version_restore`,
`color_group_capabilities`, `gallery_capabilities`, and
`grade_boundary_report`. See `docs/kernels/color-grade-kernel.md` for the live-tested
support map, and `docs/guides/color-decision-guide.md` for the practical distinction
between direct API color controls and opaque full-grade artifacts.

**`timeline_item_takes`** — Take management.

Key actions: `add(clip_id, start_frame?, end_frame?)`, `get_count`,
`get_selected_index`, `select(index)`, `delete(index)`, `finalize`

---

### Gallery

**`gallery`** — Gallery album management.

Key actions: `get_still_albums`, `get_current_album`, `set_current_album(album_index)`,
`create_still_album`, `create_power_grade_album`

**`gallery_stills`** — Manage stills within an album. Requires Color page.

Key actions:
- `get_stills(album_index?)` — returns count
- `get_label(still_index)` / `set_label(still_index, label)`
- `import_stills(paths)` — paths to `.drx` files
- `export_stills(folder_path, prefix?, format?, album_index?)`
  - formats: `dpx`, `cin`, `tif`, `jpg`, `png`, `ppm`, `bmp`, `xpm`, `drx`
- `grab_and_export(folder_path, prefix?, format?, album_index?, cleanup?)` —
  grabs a still from the current frame and exports it in one atomic call.
  Returns `{files, format, folder, cleaned_up}` where each file entry includes
  `data_base64` for image files and `data` (text) for `.drx` grade files.
  `cleanup` defaults to `true` — files are deleted from disk after being inlined.
  Requires Color page with Gallery panel visible.
- `delete_stills(still_indices)`

---

### Node Graphs

**`graph`** — Node graph operations on timeline, timeline item, or color group.

The `source` parameter controls which graph you target:
- `"timeline"` (default) — the timeline node graph
- `"item"` — a specific timeline item (needs `track_type`, `track_index`, `item_index`)
- `"color_group_pre"` / `"color_group_post"` — group pre/post graphs (needs `group_name`)

Key actions: `get_num_nodes(source?)`, `set_lut(node_index, lut_path, source?)`,
`get_lut(node_index, source?)`, `get_node_label(node_index, source?)`,
`set_node_enabled(node_index, enabled, source?)`,
`apply_grade_from_drx(path, grade_mode?, source?)` — grade_mode: `0`=no keyframes,
`1`=source timecode aligned, `2`=start frames aligned,
`reset_all_grades(source?)`

**`color_group`** — Manage color groups.

Key actions: `list`, `get_name(group_name)`, `set_name(group_name, new_name)`,
`get_clips(group_name)`, `get_pre_clip_graph(group_name)`,
`get_post_clip_graph(group_name)`

---

### Fusion

**`fusion_comp`** — Fusion composition node graph operations.

Target a comp either from a timeline item (pass `clip_id`, `timeline_item_id`, or
`timeline_item={track_type, track_index, item_index}`) or from the active Fusion
page comp (omit timeline scope).

Key actions:
- `add_tool(tool_type, x?, y?, name?)` — common types: `Merge`, `Background`,
  `TextPlus`, `Transform`, `Blur`, `ColorCorrector`, `RectangleMask`,
  `EllipseMask`, `Tracker`, `MediaIn`, `MediaOut`, `Glow`, `DeltaKeyer`,
  `UltraKeyer`, `FilmGrain`, `CornerPositioner`
- `delete_tool(tool_name)`, `get_tool_list(type?)`, `find_tool(name)`
- `connect(target_tool, input_name, source_tool, output_name?)`
- `disconnect(tool_name, input_name)`
- `set_input(tool_name, input_name, value, time?)` /
  `get_input(tool_name, input_name, time?)`
- `get_inputs(tool_name)` / `get_outputs(tool_name)`
- `set_attrs(tool_name, attrs)` / `get_attrs(tool_name)`
- `add_keyframe(tool_name, input_name, time, value)`
- `get_position(tool_name)` / `set_position(tool_name, x, y)` — read/write a node's
  position on the FlowView canvas; `set_position` returns a position read-back
- `copy_tool(tool_name, name?, x?, y?)` — duplicate a node (settings copied via a
  temp `.setting` file), optionally renaming and repositioning it
- `auto_arrange(tool_names?, direction?, spacing?, x?, y?)` — lay tools out in a row
  (`direction="horizontal"`, default) or column (`"vertical"`)
- `get_comp_info`, `set_frame_range(start, end)`, `get_frame_range`, `render`
- `start_undo(name?)` / `end_undo(keep?)`
- `bulk_set_inputs(ops)` — batch set inputs across multiple timeline item comps in
  one call; each op requires timeline scope plus `tool_name`, `input_name`, `value`
- `bulk_set_expressions(ops)` — batch attach expressions across multiple timeline
  item comps in one call; each op requires timeline scope plus `tool_name`,
  `input_name`, `expression`
- `group_settings_export(group_name, path, include_advisory?)` — write a
  `GroupOperator` to disk and return a parsed published-input summary
- `group_settings_splice_inputs(source_path, template_path, dest_path?, source_group_name?, template_group_name?)` —
  replace one `.setting` file's `Inputs = ordered() { ... }` block with the
  matching block from another, preserving inner tools and outer structure;
  balanced-brace parser handles nested `UserControls`
- `group_settings_load(group_name, settings_path, backup_path?, undo_name?)` —
  apply a `.setting` to a live group with an auto backup and an undo wrap so
  Ctrl+Z reverses the change

Fusion Composition kernel actions (v2.12.0+) add safer graph inspection and
mutation wrappers around the raw Fusion API:

- `fusion_graph_capabilities`
- `probe_fusion_comp(include_io?, max_tools?)`
- `probe_fusion_tool(tool_name, include_io?)`
- `safe_add_tool(tool_type, name?, dry_run?)`
- `safe_set_inputs(tool_name, inputs, readback?)`
- `safe_connect_tools(target_tool, input_name, source_tool, dry_run?)`
- `fusion_boundary_report(include_io?)`
- `add_fusion_mask(mask_type?, width?, height?, corner_radius?, center?|center_x?/center_y?,
  angle?, soft_edge?, border_width?, invert?, inputs?, connect_to?, connect_input?, readback?)`
  — one-call Rectangle/Ellipse mask (e.g. rounded corners): adds the mask tool, sets its
  params (0..1), and optionally wires it into `connect_to`'s mask input (`EffectMask` default).
- `set_text_plus(text, tool_name?, input_name?, readback?)` / `get_text_plus(tool_name?, input_name?)`
  — read/write the text of a Fusion `Text+` tool or Fusion title template (e.g. a "Deep"
  title). Auto-finds the `Text+` tool when `tool_name` is omitted; `input_name` defaults to
  `StyledText`. For non-Fusion generator titles, use `timeline(action="set_title_text")` instead.

---

### Render

**`render`** — Render pipeline: jobs, presets, formats, codecs.

Key actions: `add_job`, `list_jobs`, `delete_job(job_id)`, `delete_all_jobs`,
`start(job_ids?, interactive?)`, `stop`, `is_rendering`, `get_formats`,
`get_codecs(format)`, `set_format_and_codec(format, codec)`,
`get_resolutions(format, codec)`, `set_settings(settings)`,
`list_presets`, `load_preset(name)`, `save_preset(name)`,
`quick_export_presets`, `quick_export(preset, params?)`

Render / Deliver kernel actions (v2.9.0+) add planning and safety layers:
`render_capabilities`, `probe_render_matrix`, `probe_render_settings`,
`validate_render_settings`, `safe_set_render_settings`,
`prepare_render_job`, `render_job_lifecycle_probe`,
`quick_export_capabilities`, `safe_quick_export`, and
`export_render_boundary_report`. See `docs/kernels/render-deliver-kernel.md` for the
live-tested format/codec, settings, job, and Quick Export boundary map.

---

## Common Workflows

### 1. Connect and verify

```
resolve_control(action="launch")
resolve_control(action="get_version")
resolve_control(action="mcp_update_status")
setup(action="get_defaults")
resolve_control(action="get_page")
```

Always call `launch` first in a new session. It is safe to call when Resolve is
already running.

Use `setup(action="schema")`, `setup(action="get_defaults")`, and
`setup(action="set_defaults")` when the user wants durable conversation
defaults for media analysis, metadata publishing, timed markers, report style,
or MCP update behavior. Setup defaults may shape future tool parameters, but
confirmed Resolve project writes still require the relevant action's explicit
confirmation flag.

### 2. Open a project and navigate timelines

```
project_manager(action="list")
project_manager(action="load", params={"name": "My Film"})
timeline(action="list")
timeline(action="set_current", params={"index": 2})
timeline(action="get_current")
```

### 3. Add clips to Media Pool and build a timeline

```
media_storage(action="get_volumes")
media_storage(action="import_to_pool", params={"items": ["/path/to/clip.mp4"]})
media_pool(action="get_current_folder")
media_pool(action="create_timeline", params={"name": "Assembly"})
media_pool(action="get_selected")
media_pool(action="append_to_timeline", params={"clip_ids": ["<uuid>", ...]})
media_pool(action="safe_import_sequence", params={
  "pattern": "/path/to/frames/shot_%04d.dpx",
  "start_index": 1001,
  "end_index": 1048,
  "target_folder": "Master/Plates"
})
media_pool(action="media_pool_boundary_report", params={"selected": True, "depth": 2})
# Positioned append (MediaPool.AppendToTimeline([{clipInfo}, ...])) — e.g. rebuild a subtitle row after delete_clips
media_pool(action="append_to_timeline", params={"clip_infos": [
  {"clip_id": "<uuid>", "start_frame": 0, "end_frame": 100, "record_frame": 1200, "track_index": 4}
]})
```

### 4. Inspect and annotate timeline items

```
timeline(action="get_items", params={"track_type": "video", "index": 1})
timeline(action="duplicate_clips", params={
  "clip_ids": ["<timeline-item-uuid>"], "target_track_index": 2, "record_frame_offset": 120
})
timeline(action="duplicate_clips", params={
  "selected": True,
  "placement": "track_above",
  "include_linked": True,
  "copy_properties": ["transform", "crop", "composite", "audio", "dynamic_zoom", "scaling", "stabilization", "clip_color", "markers", "enabled"],
  "copy_keyframes": True
})
timeline(action="probe_edit_kernel_item", params={"selected": True})
timeline(action="copy_range", params={
  "start_frame": 110, "end_frame": 130, "record_frame": 900,
  "track_types": ["video", "audio"], "target_track_index": 2
})
timeline_item(action="get_name", params={"track_type": "video", "track_index": 1, "item_index": 0})
timeline_item(action="get_property", params={"track_type": "video", "track_index": 1, "item_index": 0})
timeline_markers(action="add", params={"color": "Blue", "note": "Review this"})
timeline_item_markers(action="add", params={"frame": 100, "color": "Blue", "name": "Review", "note": "Check this", "duration": 1, "track_type": "video", "track_index": 1, "item_index": 0})
```

For an exhaustive live boundary map of the timeline edit kernel, run:

```
python3.11 tests/live_duplicate_clips_validation.py --output-dir /tmp/timeline-kernel-probe
```

The live harness first validates duplicate/range edit behavior, then runs the
exhaustive probe. It creates disposable projects with synthetic media, emits
JSON and Markdown reports, and classifies each API surface as `supported`,
`partially_supported`, `read_only`, `write_only_unverifiable`,
`version_or_page_dependent`, `unsupported`, `not_applicable`, or `error`.
See `docs/kernels/timeline-edit-kernel.md` for the maintained support map and current
Resolve API limitations.

For the Media Pool / Ingest boundary map, run:

```
python3.11 tests/live_media_pool_ingest_validation.py --output-dir /tmp/media-pool-ingest-probe
```

The harness creates a disposable project, generates synthetic video/audio/still
and image-sequence fixtures, probes safe import/metadata/annotation/link
helpers, writes JSON and Markdown reports, deletes the project, and removes the
generated media directory. See `docs/kernels/media-pool-ingest-kernel.md`.

For the Review Annotation boundary map, run:

```
python3.11 tests/live_review_annotation_validation.py --output-dir /tmp/review-annotation-probe
```

The harness creates a disposable project, generates synthetic video/audio media,
probes timeline, timeline item, and media pool item marker/flag/color/report
behavior, writes JSON and Markdown reports, deletes the project, and removes the
generated media directory. See `docs/kernels/review-annotation-kernel.md`.

### 5. Color grading

```
resolve_control(action="open_page", params={"page": "color"})
timeline_item_color(action="set_cdl", params={"cdl": {"NodeIndex": 1, "Slope": [1.1, 1.0, 0.9], "Offset": [0.0, 0.0, 0.0], "Power": [1.0, 1.0, 1.0], "Saturation": 1.0}, "track_type": "video", "track_index": 1, "item_index": 0})
timeline_item_color(action="add_version", params={"name": "Grade v2", "track_type": "video", "track_index": 1, "item_index": 0})
timeline_item_color(action="grade_boundary_report", params={"track_type": "video", "track_index": 1, "item_index": 0})
timeline_item_color(action="safe_export_lut", params={"type": "33ptcube", "path": "/tmp/look.cube", "track_type": "video", "track_index": 1, "item_index": 0})
```

For the Color / Grade boundary map, run:

```
python3.11 tests/live_color_grade_validation.py --output-dir /tmp/color-grade-probe
```

The harness creates a disposable project, generates synthetic color-bar media,
probes grade, node graph, version, copy, LUT, Gallery, and color-group
behavior, writes JSON and Markdown reports, deletes the project, and removes
generated media and exported probe files. See `docs/kernels/color-grade-kernel.md`.

### 6. Grab a still and read the grade data

```
resolve_control(action="open_page", params={"page": "color"})
gallery_stills(action="grab_and_export", params={"folder_path": "/tmp/stills", "format": "jpg"})
```

The response includes `files[].data_base64` (the image as base64) and
`files[].data` for the companion `.drx` grade file (plain text XML). The
image reflects the color-graded frame as Resolve sees it, not the raw source.

### 7. Export the timeline

```
timeline(action="export", params={"path": "/tmp/export.edl", "type": "EDL", "subtype": "CMX3600"})
timeline(action="export", params={"path": "/tmp/export.fcpxml", "type": "FCPXML"})
timeline(action="export_timeline_checked", params={"path": "/tmp/export.drt", "format": "drt"})
timeline(action="detect_gaps_overlaps")
timeline(action="conform_boundary_report", params={"handles": 8})
```

For the Timeline Conform / Interchange boundary map, run:

```
python3.11 tests/live_timeline_conform_validation.py --output-dir /tmp/timeline-conform-probe
```

The harness creates a disposable project, generates synthetic media, builds a
gapped timeline, probes structure, source ranges, gap/overlap detection,
interchange export/import/round-trip behavior, synthetic missing-media relink
planning, writes reports, deletes the project, and removes generated media.
See `docs/kernels/timeline-conform-interchange-kernel.md`.

For the Audio / Fairlight boundary map, run:

```
python3.11 tests/live_audio_fairlight_validation.py --output-dir /tmp/audio-fairlight-probe
```

The harness creates a disposable project, generates synthetic video and audio
media, probes track/item audio state, mappings, voice isolation, property
writes, auto-sync, transcription, subtitle generation, Fairlight preset listing,
audio insertion, writes reports, deletes the project, and removes generated
media. See `docs/kernels/audio-fairlight-kernel.md`.

### 8. Add and start a render job

```
render(action="get_formats")
render(action="probe_render_matrix")
render(action="set_format_and_codec", params={"format": "QuickTime", "codec": "H.265 Master"})
render(action="validate_render_settings", params={"settings": {"TargetDir": "/tmp/renders", "CustomName": "review", "SelectAllFrames": true}, "require_temp_target": true})
render(action="prepare_render_job", params={"target_dir": "/tmp/renders", "settings": {"CustomName": "review", "SelectAllFrames": true}})
render(action="add_job")
render(action="list_jobs")
render(action="start")
render(action="is_rendering")
```

For the Render / Deliver boundary map, run:

```
python3.11 tests/live_render_deliver_validation.py --output-dir /tmp/render-deliver-probe
```

The harness creates a disposable project, generates a synthetic timeline, probes
format/codec/resolution compatibility, validates settings, runs a tiny temp
render job, writes reports, deletes the project, and removes generated media and
render outputs.

### 9. Apply a Fusion effect to a timeline item

```
timeline_item_fusion(action="add_comp", params={"track_type": "video", "track_index": 1, "item_index": 0})
fusion_comp(action="add_tool", params={"tool_type": "Glow", "timeline_item": {"track_type": "video", "track_index": 1, "item_index": 0}})
fusion_comp(action="set_input", params={"tool_name": "Glow1", "input_name": "Gain", "value": 0.8, "timeline_item": {"track_type": "video", "track_index": 1, "item_index": 0}})
fusion_comp(action="fusion_boundary_report", params={"timeline_item": {"track_type": "video", "track_index": 1, "item_index": 0}})
```

For the Fusion Composition boundary map, run:

```
python3.11 tests/live_fusion_composition_validation.py --output-dir /tmp/fusion-composition-probe
```

The harness creates a disposable project, generates synthetic video media,
probes timeline item comp creation, safe tool creation, input writes, graph
inspection, connections, bulk writes, frame range, and comp export, writes
reports, deletes the project, and removes generated media. See
`docs/kernels/fusion-composition-kernel.md`.

---

## Error Handling and Recovery

| Error message | Cause | Fix |
|---|---|---|
| `"Not connected to DaVinci Resolve"` | Resolve is not running or scripting is disabled | Call `resolve_control(action="launch")`, wait, retry |
| `"No project open"` | No project is currently loaded | Call `project_manager(action="load", params={"name": "..."})` |
| `"No current timeline"` | Project has no timeline set as current | Call `timeline(action="set_current", params={"index": 1})` |
| `"No item at index N"` | `item_index` out of range for the track | Call `timeline(action="get_items", ...)` first to find valid indices |
| `"Clip not found"` | Stale or wrong `clip_id` | Re-fetch IDs via `media_pool(action="get_selected")` or `folder(action="get_clips")` |
| `"Gallery not available"` | Not on Color page | `resolve_control(action="open_page", params={"page": "color"})` |
| `"GrabStill failed"` | Not on Color page or no clip under playhead | Switch to Color page, move playhead over a clip |
| `"ExportStills failed"` | Gallery panel not open in UI | Instruct user to open Workspace > Gallery |
| `"Tool '...' not found"` | Wrong tool name in Fusion comp | Use `fusion_comp(action="get_tool_list")` to list available tools |
| `"Color group '...' not found"` | Group name mismatch | Use `color_group(action="list")` first |

When a tool returns `{"success": False}` without an error key, the underlying
Resolve API returned `False`. This usually means a precondition was not met
(wrong page, wrong state, context missing). Check the API reference in
`docs/reference/resolve_scripting_api.txt` for the specific method.

---

## Known Gotchas

**Resolve API object lifetimes** — Objects like timelines, clips, and color groups
returned by the API are live references that can become stale if the project state
changes (e.g., the user deletes a timeline). Always re-fetch IDs after any
destructive action.

**`SetName` on the active timeline** — `timeline(action="set_name")` returns
`False` if you try to rename the currently active timeline. Switch to a different
timeline first, rename, then switch back.

**`DeleteProject`** — Returns `False` if the project is currently open. Close it
first.

**CDL value format** — `set_cdl` accepts Slope/Offset/Power as arrays `[R, G, B]`,
tuples, or space-separated strings like `"1.0 1.0 1.0"`. All forms are normalized
internally.

**`GetNodeGraph(0)`** — Passing `0` as `layer_index` to `GetNodeGraph` on a
timeline item returns `False` in Resolve. Use `get_node_graph` without a
`layer_index` to get the default graph.

**Gallery export requires the Gallery panel visible** — `ExportStills` only works
if the Gallery panel is open in the Resolve UI on the Color page. Instruct the
user to open it via Workspace menu if export fails.

**Python version** — the only hard requirement is Python **3.10+** (the MCP SDK
floor). There is no upper cap: 3.13/3.14 are accepted, and Python 3.14 is verified
working against Resolve Studio 20.3.2. On *older* Resolve builds the scripting
bridge may still fail to load on 3.13+ (`scriptapp("Resolve")` returns `None`);
`setup`/`doctor` warn on 3.13+ and their connection check surfaces a real failure.
If that happens, recreate the venv with Python 3.10–3.12 (the lowest-risk range).
The running server only warns on 3.13+ rather than exiting.

**Resolve version guards** — Resolve 20-specific actions return a clear
`requires DaVinci Resolve 20.x+` error when called against older builds. Resolve
19.1.3 remains the compatibility baseline; Resolve 20 additions were live-tested
on Resolve Studio 20.3.2.

**Source media integrity** — Do not transcode, convert, create proxies, or write
derivatives of source media unless the user explicitly asks. Analysis and tests
should write sidecars or synthetic fixtures, never modify camera originals.

**Windows multi-Python setups** — On Windows with multiple Python installations,
Resolve 20.3 may crash on import unless `PYTHONHOME` is set to the interpreter
used to build the venv. The installer handles this automatically; manual configs
may need it added.

**`item_index` is 0-based** — When specifying `item_index` in params, `0` is the
first item on the track, not `1`.

**`track_index` is 1-based** — Track indices start at `1`, not `0`.

**Fusion comp scope** — `fusion_comp` actions without a timeline scope target the
active composition on the Fusion page. If you intend to operate on a specific
clip's comp, always pass `clip_id`, `timeline_item_id`, or `timeline_item`.

---

## Seeing What Resolve Sees (Visual Context)

The server provides two mechanisms to inspect a frame as Resolve has processed it,
including color grading, effects, and compositing — not just the raw source file.

**`timeline_markers(action="get_thumbnail")`** — Returns raw thumbnail data at
the current playhead position. The response is a dictionary with keys `data`,
`format`, `width`, `height`, `noOfComponents`, and `depth`.

**`timeline_markers(action="get_thumbnail_image")`** — Converts the same current
frame thumbnail to PNG bytes and returns MCP image content without writing a file.

**`gallery_stills(action="grab_and_export", params={...})`** — Grabs a still from
the current frame on the Color page and returns the image encoded as base64 in the
response (`files[].data_base64`). This is the most reliable way to get a
color-graded frame preview as a standard image format (jpg, tif, dpx, etc.)
that can be passed directly to a vision-capable AI model. Requires the Color page
with Gallery panel visible.

To use `grab_and_export` for visual inspection:

```
resolve_control(action="open_page", params={"page": "color"})
gallery_stills(action="grab_and_export", params={
  "folder_path": "/tmp/resolve-preview",
  "format": "jpg",
  "cleanup": true
})
```

The response `files[0].data_base64` is a standard JPEG, base64-encoded. Feed it
to a vision model to describe what Resolve is displaying — including all grading
and effects applied to the source.

---

## Clip ID Reference Pattern

Many tools require a `clip_id` (the UUID of a Media Pool clip) or a timeline item
identified by `track_type + track_index + item_index`. Use this pattern to resolve
both:

```
# List clips in the Media Pool
folder(action="get_clips")
# -> returns [{name, id}, ...]  — use id as clip_id

# List items on a timeline track
timeline(action="get_items", params={"track_type": "video", "index": 1})
# -> returns [{name, id, start, end, duration}, ...]
# Use track_type="video", track_index=1, item_index=<position in this list>
# Or use id to look up later via timeline_item(action="get_unique_id", ...)
```

---

## API Coverage

All 336 non-deprecated methods of the DaVinci Resolve Scripting API are covered.
331 methods have been live-tested across Resolve 19.1.3 Studio and Resolve
20.3.2 Studio. Five methods require infrastructure not available in typical
setups:

| Method | Requires |
|---|---|
| `ProjectManager.CreateCloudProject` | Resolve cloud infrastructure |
| `ProjectManager.LoadCloudProject` | Resolve cloud infrastructure |
| `ProjectManager.ImportCloudProject` | Resolve cloud infrastructure |
| `ProjectManager.RestoreCloudProject` | Resolve cloud infrastructure |
| `Timeline.AnalyzeDolbyVision` | HDR / Dolby Vision content |

The full API reference is in `docs/reference/resolve_scripting_api.txt`.
