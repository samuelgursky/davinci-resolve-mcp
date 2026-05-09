# DaVinci Resolve MCP Server

[![Version](https://img.shields.io/badge/version-2.16.0-blue.svg)](https://github.com/samuelgursky/davinci-resolve-mcp/releases)
[![API Coverage](https://img.shields.io/badge/API%20Coverage-100%25-brightgreen.svg)](#api-coverage)
[![Tools](https://img.shields.io/badge/MCP%20Tools-30%20(328%20full)-blue.svg)](#server-modes)
[![Tested](https://img.shields.io/badge/Live%20Tested-98.5%25-green.svg)](#test-results)
[![DaVinci Resolve](https://img.shields.io/badge/DaVinci%20Resolve-18.5+-darkred.svg)](https://www.blackmagicdesign.com/products/davinciresolve)
[![Python](https://img.shields.io/badge/python-3.10--3.12-green.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://opensource.org/licenses/MIT)

A Model Context Protocol (MCP) server providing **complete coverage** of the DaVinci Resolve Scripting API. Connect AI assistants (Claude, Cursor, Windsurf) to DaVinci Resolve and control every aspect of your post-production workflow through natural language.

Release/version procedure: see [docs/release-process.md](docs/release-process.md). Media analysis workflow: see [docs/media-analysis-guide.md](docs/media-analysis-guide.md).
Resolve developer package notes: [Workflow Integrations](docs/workflow-integrations.md), [OpenFX](docs/openfx-notes.md), [LUTs](docs/lut-notes.md), [Fusion Templates](docs/fusion-template-notes.md), [DCTL](docs/dctl-notes.md), [Codec Plugins](docs/codec-plugin-notes.md), [Fuse + DCTL Authoring](docs/fuse-dctl-authoring.md), [Script Plugin Authoring + Conversational Lua/Python](docs/script-plugin-authoring.md), [Extension Authoring Kernel](docs/extension-authoring-kernel.md).

## Feature Highlights

The compound server now exposes 30 context-efficient tools: full Resolve API
coverage plus guarded kernel workflows that probe, report, dry-run, and apply
changes only when the active Resolve state supports them.

| Area | Agent Workflows | Docs |
|------|-----------------|------|
| Timeline editing | Track/item probing, duplicate/copy/move helpers, state snapshots, transforms, audio, retime, crop, composite, and keyframe edits | [Timeline Edit Kernel](docs/timeline-edit-kernel.md) |
| Media Pool / ingest | Safe media, sequence, and folder import; folder organization; metadata normalization; clip properties; marks; annotations; relink/proxy/full-res guards | [Media Pool / Ingest Kernel](docs/media-pool-ingest-kernel.md) |
| Render / Deliver | Format/codec matrix probing, render settings validation, queued job lifecycle checks, guarded Quick Export, render boundary reports | [Render / Deliver Kernel](docs/render-deliver-kernel.md) |
| Review annotations | Unified marker, custom data, flag, clip color, copy/move, sync, cleanup, and review report workflows across timeline, item, and clip scopes | [Review Annotation Kernel](docs/review-annotation-kernel.md) |
| Color / Grade | Grade item snapshots, node graph probing, CDL validation, grade copy, DRX/LUT helpers, version restore, Gallery, and color group reporting | [Color / Grade Kernel](docs/color-grade-kernel.md) |
| Fusion composition | Timeline-item Fusion comp targeting, safe tool creation, input writes, port inspection, connection validation, scoped bulk writes, comp export | [Fusion Composition Kernel](docs/fusion-composition-kernel.md) |
| Conform / interchange | Timeline structure snapshots, gap/overlap detection, source ranges, checked exports/imports, round-trip comparison, missing media, relink plans | [Timeline Conform / Interchange Kernel](docs/timeline-conform-interchange-kernel.md) |
| Audio / Fairlight | Audio track/item probes, source mapping reports, guarded audio property writes, voice isolation checks, auto-sync planning, transcription/subtitle probes | [Audio / Fairlight Kernel](docs/audio-fairlight-kernel.md) |
| Project lifecycle | Disposable project CRUD, DRP import/export, archive/restore guards, settings snapshots, database dry-runs, preset lifecycle probes | [Project Lifecycle Kernel](docs/project-lifecycle-kernel.md) |
| Extension authoring | Fuse, DCTL, ACES DCTL, and Resolve script lifecycle probes; safe MCP-marked install/remove; refresh/restart requirement classification | [Extension Authoring Kernel](docs/extension-authoring-kernel.md) |

## Kernel Action Coverage

Kernel actions are MCP workflow actions layered on top of the public DaVinci
Resolve Scripting API. They are tracked separately from API method coverage:
API coverage answers "can MCP reach every Blackmagic method?", while kernel
coverage answers "which higher-level, guarded agent workflows are available?".

Current kernel coverage: **109 actions** across **8 compound MCP tools**.

| Kernel | MCP Tool | Actions |
|--------|----------|---------|
| Timeline edit | `timeline` | `duplicate_clips`, `copy_clips`, `move_clips`, `copy_range`, `duplicate_range`, `overwrite_range`, `lift_range`, `edit_kernel_capabilities`, `probe_edit_kernel_item` |
| Media Pool / ingest | `media_pool` | `ingest_capabilities`, `probe_ingest_item`, `probe_media_pool`, `safe_import_media`, `safe_import_sequence`, `safe_import_folder`, `organize_clips`, `copy_metadata`, `normalize_metadata`, `probe_clip_properties`, `safe_relink`, `safe_unlink`, `link_proxy_checked`, `link_full_resolution_checked`, `set_clip_marks`, `clear_clip_marks`, `copy_clip_annotations`, `media_pool_boundary_report` |
| Render / Deliver | `render` | `render_capabilities`, `probe_render_matrix`, `probe_render_settings`, `validate_render_settings`, `safe_set_render_settings`, `prepare_render_job`, `render_job_lifecycle_probe`, `quick_export_capabilities`, `safe_quick_export`, `export_render_boundary_report` |
| Review annotations | `timeline_markers` | `annotation_capabilities`, `probe_annotations`, `normalize_marker_payload`, `copy_annotations`, `move_annotations`, `sync_marker_custom_data`, `clear_annotations_by_scope`, `export_review_report`, `annotation_boundary_report` |
| Color / Grade | `timeline_item_color` | `grade_capabilities`, `probe_grade_item`, `probe_node_graph`, `safe_set_cdl`, `safe_copy_grade`, `safe_apply_drx`, `safe_export_lut`, `grade_version_snapshot`, `grade_version_restore`, `color_group_capabilities`, `gallery_capabilities`, `grade_boundary_report` |
| Fusion composition | `fusion_comp` | `fusion_graph_capabilities`, `probe_fusion_comp`, `probe_fusion_tool`, `safe_add_tool`, `safe_set_inputs`, `safe_connect_tools`, `fusion_boundary_report` |
| Conform / interchange | `timeline` | `conform_capabilities`, `probe_timeline_structure`, `detect_gaps_overlaps`, `source_range_report`, `export_timeline_checked`, `import_timeline_checked`, `compare_timelines`, `probe_interchange_roundtrip`, `detect_missing_media`, `build_relink_plan`, `conform_boundary_report` |
| Audio / Fairlight | `timeline` | `audio_capabilities`, `probe_audio_item`, `probe_audio_track`, `safe_set_audio_properties`, `voice_isolation_capabilities`, `audio_mapping_report`, `safe_auto_sync_audio`, `transcription_capabilities`, `subtitle_generation_probe`, `fairlight_boundary_report` |
| Project lifecycle | `project_manager` | `project_capabilities`, `probe_project_lifecycle`, `probe_project_settings`, `safe_project_create`, `safe_project_export`, `safe_project_import`, `safe_project_archive`, `safe_project_restore`, `safe_project_delete`, `safe_set_project_settings`, `project_settings_snapshot`, `database_capabilities`, `safe_set_current_database`, `preset_lifecycle_probe`, `project_boundary_report` |
| Extension authoring | `script_plugin` | `extension_capabilities`, `probe_fuse_lifecycle`, `probe_dctl_lifecycle`, `probe_script_lifecycle`, `safe_install_extension`, `safe_remove_extension`, `refresh_or_restart_required`, `extension_boundary_report` |

### What's New in v2.16.0

Extension Authoring kernel expansion - adding lifecycle-aware Fuse, DCTL, ACES
DCTL, and Resolve-page script probes around the existing authoring tools.

**New `script_plugin` extension actions**: added `extension_capabilities`,
`probe_fuse_lifecycle`, `probe_dctl_lifecycle`, `probe_script_lifecycle`,
`safe_install_extension`, `safe_remove_extension`,
`refresh_or_restart_required`, and `extension_boundary_report`.

**Lifecycle and cleanup guards**: safe extension installs require `_mcp_` names
and MCP markers by default. Safe removal refuses to delete unmarked files unless
explicitly overridden. The kernel classifies Fuse and ACES DCTL installs as
restart-required, regular LUT DCTLs as `refresh_luts`-driven, and Resolve-page
scripts as menu-refresh-only.

**Documented support map**: added
[`docs/extension-authoring-kernel.md`](docs/extension-authoring-kernel.md) and
updated the Fuse/DCTL and script authoring docs with live lifecycle findings.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with
MCP-marked `_mcp_` extension files only. Final probe result: 14 supported, 1
partially supported installed-Lua-script execution boundary, 1 intentional
unsupported unmarked-source guard, and 0 errors. All generated extension files
and the disposable project were cleaned up.

### v2.15.0

Project / Database / Archive kernel expansion - adding disposable project
lifecycle guards, settings snapshots and write/restore probes, database switch
dry-runs, preset lifecycle probing, archive safety validation, and project
boundary reporting.

**New `project_manager` lifecycle actions**: added `project_capabilities`,
`probe_project_lifecycle`, `probe_project_settings`, `safe_project_create`,
`safe_project_export`, `safe_project_import`, `safe_project_archive`,
`safe_project_restore`, `safe_project_delete`, `safe_set_project_settings`,
`project_settings_snapshot`, `database_capabilities`,
`safe_set_current_database`, `preset_lifecycle_probe`, and
`project_boundary_report`.

**Operational guardrails**: safe project mutation defaults to `_mcp_`
disposable names and temp paths. Database switching dry-runs by default because
Resolve closes open projects when changing databases. Archive source media,
render cache, and proxy media flags are rejected unless explicitly opted in.

**Documented support map**: added
[`docs/project-lifecycle-kernel.md`](docs/project-lifecycle-kernel.md) with
project CRUD, DRP import/export, archive/restore, folder, settings, database,
layout preset, render preset, page, keyframe, and cloud-infrastructure
boundaries.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with
disposable `_mcp_` projects only. Final probe result: 35 supported, 5 partially
supported lifecycle/archive/keyframe/render-preset boundaries, 1 intentional
unsupported archive media-flag guard, 1 not-applicable archive restore boundary,
and 0 errors. Disposable projects, layout presets, and temp work files were
cleaned up.

### v2.14.0

Audio / Fairlight kernel expansion - adding audio track/item probes, source
audio mapping reports, guarded audio property writes, voice isolation
capabilities, auto-sync planning, transcription/subtitle probes, and Fairlight
boundary reporting.

**New `timeline` audio actions**: added `audio_capabilities`,
`probe_audio_track`, `probe_audio_item`, `safe_set_audio_properties`,
`voice_isolation_capabilities`, `audio_mapping_report`, `safe_auto_sync_audio`,
`transcription_capabilities`, `subtitle_generation_probe`, and
`fairlight_boundary_report`.

**Audio state and mapping**: the kernel snapshots audio track state, timeline
item audio properties, source audio channel mapping, MediaPoolItem audio
mapping, and track/item voice isolation availability.

**Guarded AI and sync surfaces**: auto-sync dry-runs by default and normalizes
Resolve audio-sync constants. Subtitle generation dry-runs unless
`allow_generate=True`; transcription capability reporting is read-only by
default.

**Documented support map**: added
[`docs/audio-fairlight-kernel.md`](docs/audio-fairlight-kernel.md) with
track/item state, voice isolation, mapping, transcription, subtitle, auto-sync,
and Fairlight insertion boundaries.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with
generated synthetic video and audio-only media. Final probe result: 13
supported, 3 partially supported audio property/auto-sync/audio-insert
boundaries, and 0 errors. The disposable project and generated media were
cleaned up.

### v2.13.0

Timeline Conform / Interchange kernel expansion - adding timeline structure
snapshots, source range reporting, gap/overlap detection, guarded interchange
export/import, round-trip comparison, missing-media detection, and relink
planning around Resolve's public timeline APIs.

**New `timeline` conform actions**: added `conform_capabilities`,
`probe_timeline_structure`, `detect_gaps_overlaps`, `source_range_report`,
`export_timeline_checked`, `import_timeline_checked`, `compare_timelines`,
`probe_interchange_roundtrip`, `detect_missing_media`, `build_relink_plan`,
and `conform_boundary_report`.

**Interchange probing**: export aliases now cover FCPXML, DRT, EDL, AAF, OTIO,
FCP 7 XML, and EDL subtype variants. FCPXML directory-style exports are
normalized with a `primary_file` path for import.

**Conform analysis**: the kernel reports track/item structure, same-track gaps
and overlaps, source ranges with handles, missing/offline media, and relink
candidates without mutating user source media.

**Documented support map**: added
[`docs/timeline-conform-interchange-kernel.md`](docs/timeline-conform-interchange-kernel.md)
with export, round-trip, missing-media, relink planning, and format-survival
boundaries.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with a
generated synthetic gapped timeline. Final probe result: 17 supported, 1
partially supported FCPXML round-trip survivability boundary, and 0 errors. The
disposable project, generated media, and imported round-trip timelines were
cleaned up.

### v2.12.0

Fusion Composition kernel expansion - adding safe Fusion graph inspection,
tool creation, input writes, connection validation, scoped bulk writes, and
boundary reporting around Resolve's public Fusion comp API.

**New `fusion_comp` kernel actions**: added `fusion_graph_capabilities`,
`probe_fusion_comp`, `probe_fusion_tool`, `safe_add_tool`, `safe_set_inputs`,
`safe_connect_tools`, and `fusion_boundary_report`.

**Timeline item graph automation**: the kernel can target timeline item Fusion
comps via `timeline_item`, `clip_id`, or `timeline_item_id`, then add tools,
write inputs with readback, inspect ports, connect tools, set frame ranges, and
export the comp through `timeline_item_fusion`.

**Scoped bulk writes**: `bulk_set_inputs` remains the safe batch path for
applying input updates across multiple explicitly scoped timeline-item comps,
so agent workflows do not accidentally mutate the active Fusion page comp.

**Documented support map**: added
[`docs/fusion-composition-kernel.md`](docs/fusion-composition-kernel.md) with
tool availability, input/output, scope, comp export, and page-state boundaries.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with a
generated synthetic timeline item Fusion comp. Final probe result: 18
supported, 0 unsupported, 0 partially supported, and 0 errors. The disposable
project, generated media, and exported temp comp were cleaned up.

### v2.11.0

Color / Grade kernel expansion - adding safe grade inspection, CDL validation,
node graph probing, grade copy, LUT export, version restore, Gallery, and color
group boundary reporting around Resolve's public Color API.

**New `timeline_item_color` kernel actions**: added `grade_capabilities`,
`probe_grade_item`, `probe_node_graph`, `safe_set_cdl`, `safe_copy_grade`,
`safe_apply_drx`, `safe_export_lut`, `grade_version_snapshot`,
`grade_version_restore`, `color_group_capabilities`, `gallery_capabilities`,
and `grade_boundary_report`.

**Grade and graph probing**: the kernel snapshots item grade versions, graph
availability, node counts, node LUT/cache/label/tools metadata, color-group
assignment, and cache state without guessing at opaque node internals.

**Safe mutation helpers**: CDL payloads are validated and normalized before
`SetCDL`; grade copy resolves target timeline item IDs first; LUT export is
guarded to temp paths by default; DRX apply requires an existing DRX path and
documents that it replaces the target graph.

**Color groups and Gallery**: color-group capability probes cover project
groups plus pre/post graph availability. Gallery capability probes report album
state and classify still export as UI/page dependent when Resolve returns false.

**Documented support map**: added
[`docs/color-grade-kernel.md`](docs/color-grade-kernel.md) with graph, LUT, DRX,
version, Gallery, color-group, and AI-tool boundaries.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with a
generated synthetic color-bar timeline. Final probe result: 25 supported, 2
version/page-dependent Gallery/DRX export boundaries, 1 not-applicable DRX apply
path because no DRX could be produced in that run, and 0 errors. The disposable
project, generated media, and temp LUT exports were cleaned up.

### v2.10.0

Review Annotation kernel expansion - adding a unified marker, custom data,
flag, clip color, copy/move, and review report layer across timeline, timeline
item, and media pool item scopes.

**New `timeline_markers` kernel actions**: added
`annotation_capabilities`, `probe_annotations`, `normalize_marker_payload`,
`copy_annotations`, `move_annotations`, `sync_marker_custom_data`,
`clear_annotations_by_scope`, `export_review_report`, and
`annotation_boundary_report`.

**Unified annotation scopes**: the new helpers normalize marker payloads,
frame/timecode aliases, custom data aliases, and marker colors before touching
Resolve. `probe_annotations` snapshots timeline, current timeline item, and
media pool item annotations when the current playhead can resolve them.

**Review metadata copying**: `copy_annotations` and `move_annotations` can copy
marker payloads between timeline, timeline item, and media pool item scopes
using direct frame numbers. When supported by both scopes, flags and clip color
can travel with the marker payload.

**Read-only review reports**: `export_review_report` and
`annotation_boundary_report` produce agent-friendly summaries without mutating
media or projects.

**Documented support map**: added
[`docs/review-annotation-kernel.md`](docs/review-annotation-kernel.md) with the
scope matrix, field support, frame-space caveats, and live probe findings.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with a
generated synthetic timeline. Final probe result: 44 supported, 1 expected
unsupported invalid-color boundary, and 0 errors. The disposable project and
generated media were cleaned up after report generation.

### v2.9.0

Render / Deliver kernel expansion — adding a safer render planning, settings,
format/codec compatibility, queue lifecycle, and Quick Export boundary layer.

**New `render` kernel actions**: added `render_capabilities`,
`probe_render_matrix`, `probe_render_settings`, `validate_render_settings`,
`safe_set_render_settings`, `prepare_render_job`,
`render_job_lifecycle_probe`, `quick_export_capabilities`,
`safe_quick_export`, and `export_render_boundary_report`.

**Render compatibility matrix**: `probe_render_matrix` walks available render
formats, codecs, and resolutions so agents can choose what this specific
Resolve install can actually deliver.

**Job-safe rendering helpers**: render settings validation now checks documented
setting keys, value types, frame ranges, and temp-target requirements.
`prepare_render_job` creates queued jobs without starting renders, while
`render_job_lifecycle_probe` validates add/status/delete behavior safely.

**Guarded Quick Export**: `safe_quick_export` validates temp targets, forces
`EnableUpload=False`, and requires `allow_render=True` before it can actually
start Quick Export.

**Documented support map**: added
[`docs/render-deliver-kernel.md`](docs/render-deliver-kernel.md) with
format/codec, settings, render job, and Quick Export boundaries.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with a
two-second generated synthetic timeline. Final probe result: 23 supported, 1
version/page-dependent `GetRenderSettings` readback boundary, and 0 errors. The
probe rendered one tiny synthetic output, then cleaned up the disposable project
and generated files.

### v2.8.0

Media Pool / Ingest kernel expansion — applying the timeline edit kernel probe
pattern to import, organization, metadata, annotation, and media-link boundary
workflows while preserving source media integrity.

**New `media_pool` kernel actions**: added `ingest_capabilities`,
`probe_media_pool`, `probe_ingest_item`, `safe_import_media`,
`safe_import_sequence`, `safe_import_folder`, `organize_clips`,
`copy_metadata`, `normalize_metadata`, `probe_clip_properties`,
`safe_relink`, `safe_unlink`, `link_proxy_checked`,
`link_full_resolution_checked`, `set_clip_marks`, `clear_clip_marks`,
`copy_clip_annotations`, and `media_pool_boundary_report`.

**Safe ingest and organization**: safe import helpers validate paths, sequence
patterns, frame ranges, and optional target folders before calling Resolve.
`organize_clips` can move clips to existing folders or create missing folder
paths explicitly. All helpers support dry-run where useful for planning.

**Metadata and annotation workflows**: bulk metadata normalization, metadata
copying, clip property probes, mark in/out bulk operations, and annotation copy
now have agent-friendly wrappers over Resolve's lower-level clip APIs.

**Documented support map**: added
[`docs/media-pool-ingest-kernel.md`](docs/media-pool-ingest-kernel.md) and
`docs/kernel-expansion-gameplans.md` / `docs/kernel-expansion-ledger.json` so
future kernel waves can be tracked without relying on memory.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with
generated synthetic video, audio, still, image sequence, and non-media
fixtures. Final probe result: 56 supported, 1 expected unsupported non-media
text import, and 0 errors. The disposable project and generated media were
cleaned up after report generation.

### v2.7.0

Timeline edit kernel expansion — turning the v2.6.0 duplicate helper into a
broader, live-probed edit layer for clip duplication, linked audio, range edits,
state copying, and capability reporting while preserving source media integrity.

**Expanded `timeline.duplicate_clips` action**: duplication now supports
`selected=True`, explicit `record_frame`, `track_offset`, and placement modes
`same_time`, `offset`, `at_playhead`, `track_above`, `after_source`, and
`next_gap`. `include_linked=True` duplicates linked audio and restores the
video/audio link state. `copy_clips` is an alias for duplication, and
`move_clips` duplicates successfully first before deleting the original source
items.

**Timeline range operations**: added `copy_range`, `duplicate_range`,
`overwrite_range`, and `lift_range`. Range copies rebuild exact source segments
with positioned append operations. `overwrite_range` deletes whole destination
overlaps before appending. `lift_range` safely deletes whole matching items and
requires explicit `allow_partial_item_delete=True` for whole-item deletion when
a requested range only partially overlaps an item.

**State copying groups**: duplicate/copy operations can now copy transform,
crop, composite, audio, retime, dynamic zoom, scaling, stabilization, clip
color, markers, flags, enabled state, cache, voice isolation, Fusion comps,
grades, takes, and keyframes where Resolve exposes readable/writable item APIs.
Transition cloning is accepted as a requested group but reported unsupported
because Resolve's public scripting API does not expose transition cloning.

**Capability and boundary probes**: added `timeline.edit_kernel_capabilities`
for a maintained support map and `timeline.probe_edit_kernel_item` for read-only
inspection of item methods, properties, keyframes, and linked items. Added
`src/utils/timeline_kernel_live_probe.py` plus offline report/parser tests so
future work can expand the technical boundary without guessing.

**Documented limits**: added
[`docs/timeline-edit-kernel.md`](docs/timeline-edit-kernel.md), which records
the supported, partially supported, unsupported, and version/page-dependent
surfaces. Known public-API boundaries include transition cloning, direct
razor/split edits, true partial lifts, source-less item append cloning, and
opaque speed-ramp internals.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with
disposable projects and synthetic media. Final exhaustive probe result:
255 supported, 4 partially supported, 138 unsupported, 4 version/page
dependent, and 0 errors. Static/unit checks include `tests/test_import.py`,
`scripts/audit_api_parity.py`, `git diff --check`, the focused timeline/helper
unit suite, and the full live duplicate/range/probe harness.

### v2.6.0

Timeline clip duplication — adding an Alt-drag-style helper for duplicating
existing video timeline items without creating proxy media, renders, or source
derivatives.

**New `timeline.duplicate_clips` action**: `timeline(action="duplicate_clips")`
duplicates video timeline items by re-appending the same Media Pool item with
the same source trim via `MediaPool.AppendToTimeline([{clipInfo}])`. It accepts
timeline item IDs from `timeline.get_items`, an optional
`target_track_index`, and `record_frame_offset`; each result reports per-clip
success and the duplicated timeline item ID when Resolve exposes or recovers it.

**Resolve append-result hardening**: duplicate results now tolerate thin
`AppendToTimeline` return objects that lack readable `GetUniqueId()` or
`GetName()` methods, then scan the target video track to recover the real item
handle. Bad inputs now return clean per-clip errors for non-video items,
invalid offsets, and nonexistent target tracks.

**Live-tested source trim semantics**: validation against Resolve Studio
20.3.2.9 confirmed that positioned `AppendToTimeline` treats `endFrame` as an
exclusive source boundary in this workflow. `duplicate_clips` now uses
`TimelineItem.GetDuration()` and `GetSourceStartFrame()` where available, so
the duplicate preserves the original duration and source start.

**Validation**: added `tests/live_duplicate_clips_validation.py`, which creates
a disposable project, imports synthetic media, places a trimmed clip, duplicates
it to another track, verifies record frame/duration/source trim/media identity,
checks the invalid-track error path, and deletes the project. Focused unit
coverage now includes anonymous append objects, source-start preference,
video-only `mediaType`, and target-track ID recovery.

### v2.5.0

Three new compound tools for *authoring and conversationally executing* Resolve extensions: Fusion Fuse plugins, DCTL color transforms, and Resolve-page Lua/Python scripts. Plus a documentation pass on six adjacent Resolve extension systems.

**New `fuse_plugin` tool**: generate, install, list, read, remove, and validate Fusion Fuse plugins (`.fuse`). **18 template kinds** spanning color (`color_matrix`, `per_pixel`, `channel_op`), geometric (`transform`, `spatial_warp`), text/shapes (`text_overlay`, `shape_generator`), source/temporal (`source_generator`, `time_displace`), filters (`builtin_blur`, `builtin_resize`, `variable_blur` SAT-based), modifiers (`modifier`, `point_modifier`), display shaders (`view_lut`, `dctl_kernel`), and reference (`controls_demo`, `notifychanged_demo`). Each generator produces ready-to-install Lua (or Lua + GLSL / Lua + DCTL) source that passes `luac -p` syntax checks across all option branches. **Live-verified in DaVinci Resolve Studio 20.3.2.9**: generated Fuses register on Resolve restart and instantiate via `comp:AddTool`; the `text_overlay` template was confirmed rendering glyphs into the viewer. The `view_lut` template supports `float`, `vec2`, `vec3_rgb`, and `vec4_rgba` shader parameter types. Includes a path-bug fix: corrected install path on macOS to `Fusion/Fuses/` (the SDK doc lists `Support/Fusion/Fuses/`, but Fusion's own `MapPath("Fuses:")` returns the path without `/Support/`).

**New `dctl` tool**: generate, install, list, read, remove, and validate DCTL color-transform files plus ACES IDT/ODT transforms. **8 template kinds** — `transform`, `transform_alpha` (Resolve 19.1+ alpha modes), `transition` (with `TRANSITION_PROGRESS`), `matrix` (3x3 color matrix), `kernel` (TODO stub), `lut_apply` (wraps an external `.cube` LUT via `DEFINE_LUT`/`APPLY_LUT`), `aces_idt`, `aces_odt`. UI-parameter syntax covers all six DCTL UI types (slider float/int, value box, checkbox, combo, color picker) with optional tooltips. Per-template `suggested_category` so callers know whether to install to the regular LUT directory or the separate ACES Transforms tree. Subdir support with strict path-traversal guards. Validator catches missing entry points, brace imbalance, and float literals missing the required `f` suffix. Regular DCTLs pick up via `project_settings(action='refresh_luts')`; ACES DCTLs require a Resolve restart.

**New `script_plugin` tool — conversational Lua/Python execution**: generate, install, and **execute** Resolve-page scripts that appear in the Workspace → Scripts menu. Two template kinds: `scaffold` (minimal stub) and `media_rules` (a comprehensive rules-and-variables DSL with sources, extract patterns, transforms, targets, actions, conditions, dry-run mode, external CSV/JSON data with exact/regex/fuzzy matching, and per-rule metadata — ~22k chars Lua engine and ~18k chars Python engine, both first-class). **Two new actions close the conversational loop**: `run_inline(source, language)` runs an ad-hoc Lua/Python snippet inside Resolve and streams stdout + return value back into the conversation; `execute(name, category, language)` runs an installed script the same way. Python uses subprocess with full stdout/stderr capture; Lua uses `fusion.RunScript()` against a temp file with completion-sentinel polling and `app:SetData()` bridge for return values (Resolve 20.x's `fusion.Execute()` is a no-op from the Python bridge — that quirk is encoded in the implementation). **Live-verified end-to-end** on Resolve Studio 20.3.2.9: Python `run_inline` returned project list and walked media pool; Lua `run_inline` enumerated `MapPath` symbols with stdout AND return value captured.

**`list_templates` action** on all three new tools enumerates available kinds.

**Resolve developer-package reference notes**: added six docs covering Resolve extension systems adjacent to the scripting API — `docs/workflow-integrations.md`, `docs/openfx-notes.md`, `docs/lut-notes.md`, `docs/fusion-template-notes.md`, `docs/dctl-notes.md`, `docs/codec-plugin-notes.md`. Each clarifies what the system does, how it intersects with existing MCP tools, and where the boundary is between Resolve-hosted extensions and the Python MCP server. New authoring docs: `docs/fuse-dctl-authoring.md` and `docs/script-plugin-authoring.md`. README and `docs/SKILL.md` updated to point future agents at the right note for each failure mode.

**Test coverage**: 185 offline tests across 7 modules (`test_fuse_dctl_authoring.py` and `test_script_plugin.py` both new in this release), all green in <2s. Includes hermetic round-trip tests with mocked install paths, DSL-coverage tests confirming every documented source/action/target/transform is in both Lua and Python engines, and Python subprocess execution tests with real captured stdout/stderr.

**Compound tool count: 27 → 30**. Granular tool count unchanged at 328.

### v2.4.1

Release process hardening — documenting the version bump, validation, tag, and GitHub Release checklist.

**Release checklist documented**: added `docs/release-process.md` with semantic version guidance, required version surfaces, validation requirements, tag/release commands, and release-note template.

**Live-test requirement clarified**: Resolve behavior changes must be validated live with disposable projects and synthetic media before release. Docs-only releases do not require a live Resolve run when no behavior changed.

### v2.4.0

Timeline source range extraction — adding a compound workflow helper for frame-pull and conform preparation.

**New `timeline.extract_source_frame_ranges` action**: `timeline(action="extract_source_frame_ranges")` scans every video clip on the current timeline and returns per-source frame ranges, clip occurrences, timeline positions, source offsets, applied handles, and timeline item IDs. Clip names prefer the basename from the Media Pool `File Path`, with audio extensions skipped by default.

**Handle-aware source ranges**: fixed handles default to 24 frames. Passing `handles=0` switches to gap-only auto handles, using neighboring timeline gaps up to `gap_max` frames. Returned `source_range_final` and `frame_ranges` endpoints are inclusive/inclusive for downstream extraction tools.

**Inclusive endpoint fix**: live validation caught and fixed the off-by-one where Resolve's exclusive source boundary was being returned as an inclusive final frame. A 48-frame synthetic clip with `handles=0` now returns `source_used_inclusive_end=47` and `source_range_final=[0, 47]`.

**Live Resolve validation**: verified against DaVinci Resolve Studio 20.3.2.9 in a disposable project with synthetic media. Added unit coverage in `tests/test_extract_source_frame_ranges.py` for zero-handle and fixed-handle ranges.

### v2.3.4

Marker API hardening for Issue #34 — making the compound marker tools match the parameter shapes agents and users naturally send.

**Marker parameter aliases fixed**: `timeline_markers`, `media_pool_item_markers`, and `timeline_item_markers` now accept `frame`, `frame_id`, and `frameId` consistently for add/get/update/delete operations. Marker lookup and delete paths also accept `customData` as an alias for `custom_data`.

**Timeline marker ergonomics improved**: `timeline_markers(action="add")` can now add at the current playhead when no frame/timecode is provided, and also accepts explicit `timecode` input. Optional marker fields now have sensible defaults (`color="Blue"`, `name` from note or `"Marker"`, `note=""`, `duration=1`).

**Resolve overload fallback**: marker creation first uses the documented six-argument `AddMarker(..., customData)` call, and falls back to the five-argument form when `customData` is empty and a Resolve build rejects the optional parameter.

**Live Resolve validation**: verified against DaVinci Resolve Studio 20.3.2.9 with `tests/live_marker_validation.py`. The harness creates a disposable project, imports synthetic media, inserts a visible timeline generator, and live-tests timeline, media-pool-item, and timeline-item marker add/get/update/delete alias paths. A `--keep-open` mode leaves a marked timeline open for visual inspection.

### v2.3.3

Granular layer hardening — closing exposure gaps and dropped-dict-key bugs surfaced by an exhaustive parity audit of every documented Resolve scripting method against both server layers.

**Cloud project helper rewritten** (Critical): `src/utils/cloud_operations.py` was calling `pm.CreateCloudProject(project_name, folder_path)` with positional arguments — but the documented Resolve API signature is `CreateCloudProject({cloudSettings})`, a single dict. Same bug affected `ImportCloudProject` and `RestoreCloudProject`. Helper now builds proper `{cloudSettings}` dicts and exposes all 5 documented keys (`PROJECT_NAME`, `PROJECT_MEDIA_PATH`, `IS_COLLAB`, `SYNC_MODE`, `IS_CAMERA_ACCESS`) per docs lines 576-594. Granular wrappers (`create_cloud_project_tool`, `import_cloud_project_tool`, `restore_cloud_project_tool`) updated to expose the full settings surface; `load_cloud_project_tool` added (was missing entirely from granular).

**Silent-drop bugs fixed** (Critical):
- **`render_with_quick_export()` (granular)** previously dropped the documented `{param_dict}` (TargetDir, CustomName, VideoQuality, EnableUpload). Now forwards all four keys per docs line 179.
- **`timeline_create_compound_clip()` (granular)** previously dropped the documented `{clipInfo}` dict (`name`, `startTimecode`). Now exposes both keys per docs line 369.

**Missing granular tools added**:
- **`append_to_timeline`** — both simple `clip_ids` form and positioned `clip_infos` form (`MediaPool.AppendToTimeline` was completely absent from granular layer; only compound had it).
- **`auto_sync_audio`** — with proper `{audioSyncSettings}` dict mapping per docs lines 600-614 (`sync_mode`, `channel_number` with `'automatic'`/`'mix'` aliases, `retain_embedded_audio`, `retain_video_metadata`).
- **`load_cloud_project_tool`** — was missing entirely; compound had it.
- **`rename_color_group`** — wraps `ColorGroup.SetName` (compound had it via `color_group(action="set_name")` but no granular tool).

**Removed 4 undocumented cloud method wrappers**:
- `get_cloud_projects` resource → `GetCloudProjectList` not in API docs
- `export_project_to_cloud_tool` → `ExportToCloud`/`ExportProjectToCloud` not in API docs
- `add_user_to_cloud_project_tool` → `AddUserToCloudProject` not in API docs
- `remove_user_from_cloud_project_tool` → `RemoveUserFromCloudProject` not in API docs

**Removed 9 legacy granular gallery tools** that wrapped undocumented or renamed methods (`gallery.GetAlbums()`, `gallery.CreateAlbum()`, `still.GetTimecode()`, `still.IsGrabbed()`, etc.). The proper documented Gallery and GalleryStillAlbum wrappers (lines 743+ of the previous gallery.py — all 14 of those, e.g. `get_gallery_still_albums`, `create_gallery_still_album`, `import_stills_to_album`, `export_stills_from_album`, `get_album_stills`, `set_still_label`) cover the documented API surface and remain. Removed: `get_color_presets`, `save_color_preset`, `apply_color_preset`, `delete_color_preset`, `create_color_preset_album`, `delete_color_preset_album`, `export_lut`, `get_lut_formats`, `export_all_powergrade_luts`.

**Removed 2 granular project optimized-media tools** that wrapped undocumented Resolve methods (`Project.GenerateOptimizedMedia`, `Project.DeleteOptimizedMedia`, `MediaPool.SetClipSelection` — none in API docs). Removed: `generate_optimized_media`, `delete_optimized_media`. Use the Resolve UI for optimized-media generation; `set_optimized_media_mode` (which uses the documented `Project.SetSetting("OptimizedMediaMode", ...)`) is preserved.

**Deprecated method call fixed**: `timeline(action="get_items_in_track")` was calling the deprecated `tl.GetItemsInTrack()` form (docs line 989, marked deprecated) instead of the supported `tl.GetItemListInTrack()` (line 350). Every other call site already used the correct form.

**New: API parity CI guard** at `scripts/audit_api_parity.py`. Parses `docs/resolve_scripting_api.txt` and verifies (1) no `from api.X` broken imports remain, (2) every documented Resolve method appears somewhere in `src/`, (3) wrappers calling undocumented methods are flagged for review. Includes an allowlist for legitimate undocumented-but-real Resolve API surface (Fusion compositing API, UIManager methods like `OpenProjectSettings`/`LoadUILayout`/`SaveUILayout`, internal type-discrimination helpers like `TimelineItem.GetType`/`GetMediaType`). Run with `python3 scripts/audit_api_parity.py` — currently passes all three checks cleanly.

**Tool count: 328 granular tools** (was 354 before v2.3.2; net change since v2.3.1 is −26 broken/duplicate/undocumented tools removed and +4 missing tools added). 20 new unit tests against Resolve stubs covering the cloud settings builder, audio sync settings builder, and AppendToTimeline clipInfo builder. All 41 tests pass without a live Resolve connection.

**Live disposable Resolve validation**: every new and changed v2.3.3 granular tool was exercised against DaVinci Resolve Studio 20.3.2.9 in a disposable project with synthetic temp media via `tests/live_v233_validation.py`. 10/10 checks passed: `append_to_timeline` (simple + positioned + failure path), `auto_sync_audio` (settings dict + invalid input rejection), `import_media` image-sequence form, `timeline_create_compound_clip` (info dict forwarded — compound clip created with explicit name), `rename_color_group` (renamed a real color group), `render_with_quick_export` (params dict forwarded — Resolve's structured `{JobStatus, Error}` response confirms the dict reached it), and the compound-side `GetItemListInTrack` deprecated→supported fix.

### v2.3.2

API parity sweep — closing documented overloads and dropped parameters that the v2.3.1 audit surfaced.

- **Positioned `CreateTimelineFromClips` via `clip_infos`** — `media_pool(action="create_timeline_from_clips", params={"clip_infos": [...]})` and the granular `create_timeline_from_clips(clip_infos=[...])` now expose the documented `MediaPool.CreateTimelineFromClips(name, [{clipInfo}, ...])` overload (4 keys: `mediaPoolItem`, `startFrame`, `endFrame`, `recordFrame`)
- **Image-sequence `ImportMedia` via `clip_infos`** — both layers now expose `MediaPool.ImportMedia([{FilePath, StartIndex, EndIndex}, ...])` for DPX/EXR/etc. sequence imports. PascalCase keys preserved per Resolve docs
- **Positioned `AddItemListToMediaPool` via `item_infos`** — `media_storage(action="import_to_pool", params={"item_infos": [{media, startFrame, endFrame}, ...]})` and granular `add_items_to_media_pool_from_storage(item_infos=[...])` now expose the documented `MediaStorage.AddItemListToMediaPool([{itemInfo}, ...])` overload
- **`Timeline.AddTrack` dict form** — replaced the legacy bare-string `sub_type` argument with the documented `newTrackOptions` dict (`audio_type`, `index`). Granular `timeline_add_track(track_type, audio_type=, index=)` and compound `timeline(action="add_track", params={"track_type", "options": {audio_type, index}})`
- **`CreateSubtitlesFromAudio` actually wired up** — granular `timeline_create_subtitles_from_audio` previously advertised `language` and `preset` parameters then silently dropped them. Now maps user strings (e.g. `"korean"`, `"netflix"`, `"double"`) to `resolve.AUTO_CAPTION_*` constants per docs lines 720-761, and exposes the missing `chars_per_line`, `line_break`, `gap` keys
- **Granular `import_media` no longer crashes** — the granular `import_media` tool was importing from a deleted `api.media_operations` module and would throw `ModuleNotFoundError` on first call. Rewritten to call `MediaPool.ImportMedia` directly and to share the new `clip_infos` overload
- **`SetRenderSettings` docstring completeness** — granular `set_render_settings` now documents all 27 keys per docs lines 765-799 (previously omitted `EncodingProfile`, `MultiPassEncode`, `AlphaMode`, `NetworkOptimization`, `PixelAspectRatio`, `ClipStartFrame`, `TimelineStartTimecode`, `ReplaceExistingFilesInPlace`)
- **Removed 18 broken granular tools (+ 7 broken resources)** that imported from a deleted `api.*` namespace and would crash with `ModuleNotFoundError` on first call. All 25 had working equivalents elsewhere or wrapped undocumented Resolve methods. Granular tool count is now **336** (was 354). Migration map for any caller that was hitting them:
  - `delete_media` → `media_pool(action="delete_clips")`
  - `move_media_to_bin` → `media_pool(action="move_clips")`
  - `auto_sync_audio` (granular tool) → `media_pool(action="auto_sync_audio")`
  - `unlink_clips` → `media_pool(action="unlink")`
  - `relink_clips` → `media_pool(action="relink")`
  - `create_bin` → `media_pool(action="add_subfolder")`
  - `list_media_pool_bins` (resource) → `folder(action="get_subfolders")`
  - `get_media_pool_bin_contents` (resource) → `folder(action="get_clips")`
  - `get_timeline_tracks` (resource) → `timeline(action="get_track_count")` + `timeline(action="get_items_in_track")`
  - `create_empty_timeline` → `media_pool(action="create_timeline")`
  - `delete_timeline` → `media_pool(action="delete_timelines")`
  - `add_marker` (granular timeline tool) → `timeline_markers(action="add")`
  - `add_clip_to_timeline` → `media_pool(action="append_to_timeline")`
  - `apply_lut` (granular graph tool) → `graph(action="set_lut")`
  - `copy_grade` → `timeline_item_color(action="copy_grades")`
  - `get_render_presets` (resource) → `render(action="list_presets")`
  - `add_to_render_queue` → `render(action="add_job")`
  - `start_render` (granular project tool) → `render(action="start")`
  - `get_render_queue_status` (resource) → `render(action="list_jobs")` + `render(action="get_job_status")`
  - `clear_render_queue` (granular project tool) → `render(action="delete_all_jobs")`
  - `create_sub_clip`, `get_current_color_node`, `get_color_wheel_params`, `set_color_wheel_param`, `add_node`: removed — these wrapped undocumented Resolve methods that were never exposed in the official scripting API. No replacement exists; use the Resolve UI for now.

### v2.3.1

- **Positioned `AppendToTimeline` via `clip_infos`** — `media_pool(action="append_to_timeline", params={"clip_infos": [...]})` now exposes the documented `MediaPool.AppendToTimeline([{clipInfo}, ...])` overload, accepting per-entry `clip_id`/`media_pool_item_id`, `start_frame`, `end_frame`, `record_frame`, `track_index`, and optional `media_type`. Each appended item returns its `timeline_item_id` for follow-up Fusion ops
- **Positioned append failure reporting** — the same call now returns `{"error": ...}` when Resolve fails to produce valid timeline items, including falsey `AppendToTimeline()` results and returned item handles without a timeline item id
- **Live disposable Resolve validation** — verified the fix against DaVinci Resolve Studio 20.3.2 with synthetic temp media in a disposable project: valid `clip_infos` append returned `success`, `count=1`, and `timeline_item_id`; invalid `clip_infos` calls returned errors

### v2.3.0

- **Resolve 20.2.2 API sync** — added the 12 scripting methods introduced across Resolve 20.0-20.2.2, with compatibility guards so older Resolve builds return clear "requires Resolve 20.x" errors instead of crashing
- **Resolve 20 live validation** — revalidated the new API surface against DaVinci Resolve Studio 20.3.2, bringing live-tested coverage to 331/336 methods (98.5%)
- **Official scripting docs refreshed** — `docs/resolve_scripting_api.txt` now tracks the Resolve 20 scripting README bundled with the installed 20.3.2 developer package
- **AI skill reference updated** — merged PR #30's `docs/SKILL.md` and updated it for the Resolve 20 method count, granular server, version guards, and source media integrity guidance
- **Stale Resolve handle recovery** — both server modes now validate cached Resolve handles and reconnect cleanly after Resolve restarts or Project Manager transitions

### v2.2.0

- **Granular server modularized internally** — `src/resolve_mcp_server.py` is now a thin entrypoint, with the granular implementation split across `src/granular/resolve_control.py`, `project.py`, `timeline.py`, `timeline_item.py`, `media_pool.py`, `folder.py`, `media_pool_item.py`, `gallery.py`, `graph.py`, and `media_storage.py`
- **Installer now emits env blocks for every generated stdio config** — standard `.mcp.json`, VS Code `.vscode/mcp.json`, Zed `context_servers`, and manual snippets now include `RESOLVE_SCRIPT_API`, `RESOLVE_SCRIPT_LIB`, and `PYTHONPATH`
- **Windows Resolve 20.3 hardening** — on Windows, the installer also emits `PYTHONHOME` derived from the selected interpreter's base install so Resolve binds against the intended Python instead of a newer globally registered one
- **Windows stdio transport hardening** — server entrypoints now run FastMCP through strict LF-only stdio wrappers to avoid client disconnects caused by platform newline translation in Windows pipes
- **`set_cdl` accepts arrays cleanly** — both compound and granular servers now normalize JSON array, tuple, and numeric CDL values into Resolve's required string form like `"1.0 1.0 1.0"`
- **`fusion_comp` can target timeline item comps** — node graph actions can now operate on a clip's Fusion comp via `clip_id`, `timeline_item_id`, or `timeline_item`, and `bulk_set_inputs` applies scoped input changes across multiple timeline comps
- **`python src/server.py --full` now stays intact** — the compound entrypoint now correctly launches the granular server instead of importing it and exiting

### v2.1.0

- **New `fusion_comp` tool** — 20-action tool exposing the full Fusion composition node graph API. Add/delete/find nodes, wire connections, set/get parameters, manage keyframes, control undo grouping, set render ranges, and trigger renders — all on the currently active Fusion page composition
- **`timeline_item_fusion` cache actions** — added `get_cache_enabled` and `set_cache` actions for Fusion output cache control directly on timeline items
- **Fusion node graph reference** — docstring includes common tool IDs (Merge, TextPlus, Background, Transform, ColorCorrector, DeltaKeyer, etc.) for discoverability

### v2.0.9

- **Cross-platform sandbox path redirect** — `_resolve_safe_dir()` now handles macOS (`/var/folders`, `/private/var`), Linux (`/tmp`, `/var/tmp`), and Windows (`AppData\Local\Temp`) sandbox paths that Resolve can't write to. Redirects to `~/Documents/resolve-stills` instead of Desktop
- **Auto-cleanup for `grab_and_export`** — exported files are read into the response (DRX as inline text, images as base64) then deleted from disk automatically. Zero file accumulation. Pass `cleanup: false` to keep files on disk
- **Both servers in sync** — `server.py` and `resolve_mcp_server.py` now share the same version and both use `_resolve_safe_dir()` for all Resolve-facing temp paths (project export, LUT export, still export)

### v2.0.8

- **New `grab_and_export` action on `gallery_stills`** — combines `GrabStill()` + `ExportStills()` in a single atomic call, keeping the live GalleryStill reference for reliable export. Returns a file manifest with exported image + companion `.drx` grade file
- **Format fallback chain** — if the requested format fails, automatically retries with tif then dpx
- **macOS sandbox path redirect** — `/var/folders` and `/private/var` paths are redirected to `~/Desktop/resolve-stills` since Resolve's process can't write to sandboxed temp directories
- **Key finding documented** — `ExportStills` requires the Gallery panel to be visible on the Color page. All 9 supported formats (dpx, cin, tif, jpg, png, ppm, bmp, xpm, drx) produce a companion `.drx` grade file alongside the image

### v2.0.7

- **Security: path traversal protection for layout preset tools** — `export_layout_preset`, `import_layout_preset`, and `delete_layout_preset` now validate that resolved file paths stay within the expected Resolve presets directory, preventing path traversal via crafted preset names
- **Security: document destructive tool risk** — added Security Considerations section noting that `quit_app`/`restart_app` tools can terminate Resolve; MCP clients should require user confirmation before invoking

### v2.0.6

- **Fix color group operations crash** — `timeline_item_color` unpacked `_check()` as `(proj, _, _)` but `_check()` returns `(pm, proj, err)`, so `proj` got the ProjectManager instead of the Project, crashing `assign_color_group` and `remove_from_color_group`

### v2.0.5

- **Lazy connection recovery** — full server (`--full` mode) now auto-reconnects and auto-launches Resolve, matching the compound server behavior
- **Null guards on all chained API calls** — `GetProjectManager()`, `GetCurrentProject()`, `GetCurrentTimeline()` failures now return clear errors instead of `NoneType` crashes
- **Helper functions** — `get_resolve()`, `get_project_manager()`, `get_current_project()` replace 178 boilerplate blocks

### v2.0.4

- **Fix apply_grade_from_drx parameter** — renamed `mode` to `grade_mode` to match Resolve API; corrected documentation from replace/append to actual keyframe alignment modes (0=No keyframes, 1=Source Timecode aligned, 2=Start Frames aligned)
- **Backward compatible** — still accepts `mode` for existing clients, `grade_mode` takes precedence

### v2.0.3

- **Fix GetNodeGraph crash** — `GetNodeGraph(0)` returns `False` in Resolve; now calls without args unless `layer_index` is explicitly provided
- **Falsy node graph check** — guard checks `not g` instead of `g is None` to catch `False` returns

### v2.0.2

- **Antigravity support** — Google's agentic AI coding assistant added as 10th MCP client
- **Alphabetical client ordering** — MCP_CLIENTS list sorted for easier maintenance

### v2.0.1

- **26-tool compound server** — all 324 API methods grouped into 26 context-efficient tools (default)
- **Universal installer** — single `python install.py` for macOS/Windows/Linux, 10 MCP clients
- **Dedicated timeline_item actions** — retime/speed, transform, crop, composite, audio, keyframes with validation
- **Lazy Resolve connection** — server starts instantly, connects when first tool is called
- **Bug fixes** — CreateMagicMask param type, GetCurrentClipThumbnailImage args, Python 3.13+ warning

## Key Stats

| Metric | Value |
|--------|-------|
| MCP Tools | **30** compound (default) / **328** granular |
| Kernel Actions | **109** guarded MCP workflow actions across 8 compound tools |
| API Methods Covered | **336/336** (100%) |
| Methods Live Tested | **331/336** (98.5%) |
| Live Test Pass Rate | **331/331** (100%) |
| API Object Classes | 13 |
| Tested Against | DaVinci Resolve 19.1.3 Studio + Resolve 20.3.2 Studio |
| Compatibility Note | Resolve 19.1.3 remains the compatibility baseline; Resolve 20.x scripting calls are additive, version-guarded, and live-tested on 20.3.2; Resolve 21 beta APIs are intentionally deferred until stable |

## API Coverage

Every non-deprecated method in the DaVinci Resolve Scripting API is covered. The default compound server exposes **30 tools** that group related operations by action parameter, keeping LLM context windows lean. The full granular server provides **328 individual tools** for power users. Both modes cover all 13 API object classes. MCP-level kernel actions are tracked separately in [Kernel Action Coverage](#kernel-action-coverage).

| Class | Methods | Tools | Description |
|-------|---------|-------|-------------|
| Resolve | 22 | 22 | App control, pages, layout presets, render/burn-in presets, keyframe mode |
| ProjectManager | 25 | 25 | Project CRUD, folders, databases, cloud projects, archive/restore |
| Project | 43 | 43 | Timelines, render pipeline, settings, LUTs, color groups |
| MediaStorage | 9 | 9 | Volumes, file browsing, media import, mattes |
| MediaPool | 27 | 27 | Folders, clips, timelines, metadata, stereo, sync |
| Folder | 8 | 8 | Clip listing, export, transcription |
| MediaPoolItem | 36 | 36 | Metadata, markers, flags, properties, proxy, transcription |
| Timeline | 58 | 58 | Tracks, markers, items, export, generators, titles, stills, stereo |
| TimelineItem | 80 | 80 | Properties, markers, Fusion comps, versions, takes, CDL, AI tools |
| Gallery | 8 | 8 | Albums, stills, power grades |
| GalleryStillAlbum | 6 | 6 | Stills management, import/export, labels |
| Graph | 11 | 22 | Node operations, LUTs, cache, grades (timeline + clip graph variants) |
| ColorGroup | 5 | 10 | Group management, pre/post clip node graphs |

## Requirements

- **DaVinci Resolve Studio** 18.5+ (macOS, Windows, or Linux) — the free edition does not support external scripting
- **Python 3.10–3.12** recommended (3.13+ may have ABI incompatibilities with Resolve's scripting library)
- DaVinci Resolve running with **Preferences > General > "External scripting using"** set to **Local**

Validated live coverage is based on **DaVinci Resolve 19.1.3 Studio** for the original API surface, plus **DaVinci Resolve 20.3.2 Studio** for the Resolve 20.0-20.2.2 scripting additions. Resolve 21 beta APIs are intentionally deferred until a stable release.

## Quick Start

```bash
# Clone the repository
git clone https://github.com/samuelgursky/davinci-resolve-mcp.git
cd davinci-resolve-mcp

# Make sure DaVinci Resolve is running, then:
python install.py
```

The universal installer auto-detects your platform, finds your DaVinci Resolve installation, creates a virtual environment, and configures your MCP client — all in one step.

### Supported MCP Clients

The installer can automatically configure any of these clients:

| Client | Config Written To |
|--------|-------------------|
| Claude Desktop | `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) |
| Claude Code | `.mcp.json` (project root) |
| Cursor | `~/.cursor/mcp.json` |
| VS Code (Copilot) | `.vscode/mcp.json` (workspace) |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` |
| Cline | VS Code global storage |
| Roo Code | VS Code global storage |
| Zed | `~/.config/zed/settings.json` |
| Continue | `~/.continue/config.json` |
| JetBrains IDEs | Manual (Settings > Tools > AI Assistant > MCP) |

You can configure multiple clients at once, or use `--clients manual` to get copy-paste config snippets.

### Installer Options

```bash
python install.py                              # Interactive mode
python install.py --clients all                # Configure all clients
python install.py --clients cursor,claude-desktop  # Specific clients
python install.py --clients manual             # Just print the config
python install.py --dry-run --clients all      # Preview without writing
python install.py --no-venv --clients cursor   # Skip venv creation
```

### Server Modes

The MCP server comes in two modes:

| Mode | File | Tools | Best For |
|------|------|-------|----------|
| **Compound** (default) | `src/server.py` | 30 | Most users — fast, clean, low context usage |
| **Full** | `src/resolve_mcp_server.py` | 328 | Power users who want one tool per API method |

The compound server's `timeline_item` tool includes dedicated actions for common workflows:

| Category | Actions | Parameters |
|----------|---------|------------|
| **Retime** | `get_retime`, `set_retime` | process (nearest, frame_blend, optical_flow), motion_estimation (0-6) |
| **Transform** | `get_transform`, `set_transform` | Pan, Tilt, ZoomX/Y, RotationAngle, AnchorPointX/Y, Pitch, Yaw, FlipX/Y |
| **Crop** | `get_crop`, `set_crop` | CropLeft, CropRight, CropTop, CropBottom, CropSoftness, CropRetain |
| **Composite** | `get_composite`, `set_composite` | Opacity, CompositeMode |
| **Audio** | `get_audio`, `set_audio` | Volume, Pan, AudioSyncOffset |
| **Keyframes** | `get_keyframes`, `add_keyframe`, `modify_keyframe`, `delete_keyframe`, `set_keyframe_interpolation` | property, frame, value, interpolation (Linear, Bezier, EaseIn, EaseOut, EaseInOut) |

The installer uses the compound server by default. To use the full server:
```bash
python src/server.py --full    # Launch full 328-tool server
# Or point your MCP config directly at src/resolve_mcp_server.py
```

### Manual Configuration

If you prefer to set things up yourself, add to your MCP client config:

```json
{
  "mcpServers": {
    "davinci-resolve": {
      "command": "/path/to/venv/bin/python",
      "args": ["/path/to/davinci-resolve-mcp/src/server.py"],
      "env": {
        "RESOLVE_SCRIPT_API": "/path/to/DaVinci Resolve/Developer/Scripting",
        "RESOLVE_SCRIPT_LIB": "/path/to/fusionscript.so-or-dll",
        "PYTHONPATH": "/path/to/DaVinci Resolve/Developer/Scripting/Modules"
      }
    }
  }
}
```

On Windows, installer-generated configs also include `PYTHONHOME`. That scopes Resolve's Python binding to the selected interpreter and avoids the Resolve 20.3 multi-Python crash reported in [Issue #26](https://github.com/samuelgursky/davinci-resolve-mcp/issues/26).

Platform-specific paths:

| Platform | API Path | Library Path |
|----------|----------|-------------|
| macOS | `/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting` | `fusionscript.so` in DaVinci Resolve.app |
| Windows | `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting` | `fusionscript.dll` in Resolve install dir |
| Linux | `/opt/resolve/Developer/Scripting` | `/opt/resolve/libs/Fusion/fusionscript.so` |

## Usage Examples

Once connected, you can control DaVinci Resolve through natural language:

```
"What version of DaVinci Resolve is running?"
"List all projects and open the one called 'My Film'"
"Create a new timeline called 'Assembly Cut' and add all clips from the media pool"
"Add a blue marker at the current playhead position with note 'Review this'"
"Set up a ProRes 422 HQ render for the current timeline"
"Export the timeline as an EDL"
"Switch to the Color page and grab a still"
"Create a Fusion composition on the selected clip"
```

Recent kernel workflows also support higher-level, state-aware requests:

```
"Probe this timeline for gaps, overlaps, missing media, and source frame ranges"
"Safely import this image sequence, organize it into bins, and normalize clip metadata"
"Build a render plan for ProRes 422 HQ, validate the settings, and queue the job without rendering"
"Copy all review markers from the timeline to the selected clip and export a review report"
"Snapshot this clip's grade, validate a CDL update, and export a temp LUT"
"Create a Fusion TextPlus overlay on the selected clip and verify the graph connections"
"Report audio channel mappings, voice isolation availability, and transcription/subtitle support"
"Create a disposable _mcp_ project, export/import it, snapshot settings, then clean it up"
"Install this MCP-marked DCTL or script, classify whether Resolve needs refresh or restart, then remove it"
```

## Test Results

Baseline testing was performed against **DaVinci Resolve 19.1.3 Studio** on macOS with live API calls (no mocks). Resolve 20 additions were revalidated live against **DaVinci Resolve 20.3.2 Studio**.

| Phase | Tests | Pass Rate | Scope |
|-------|-------|-----------|-------|
| Phase 1 | 204/204 | 100% | Safe read-only operations across all classes |
| Phase 2 | 79/79 | 100% | Destructive operations with create-test-cleanup patterns |
| Phase 3 | 20/20 | 100% | Real media import, sync, transcription, database switching, Resolve.Quit |
| Phase 4 | 10/10 | 100% | AI/ML methods, Fusion clips, stereo, gallery stills |
| Phase 5 | 6/6 | 100% | Scene cuts, subtitles from audio, graph node cache/tools/enable |
| Resolve 20 delta | 12/12 | 100% | Resolve 20.0-20.2.2 scripting additions live-tested on 20.3.2 |
| **Total** | **331/331** | **100%** | **98.5% of current API methods tested live** |

### Untested Methods (5 of 336)

| Method | Reason | Help Wanted |
|--------|--------|-------------|
| `PM.CreateCloudProject` | Requires DaVinci Resolve cloud infrastructure | Yes |
| `PM.LoadCloudProject` | Requires DaVinci Resolve cloud infrastructure | Yes |
| `PM.ImportCloudProject` | Requires DaVinci Resolve cloud infrastructure | Yes |
| `PM.RestoreCloudProject` | Requires DaVinci Resolve cloud infrastructure | Yes |
| `TL.AnalyzeDolbyVision` | Requires HDR/Dolby Vision content | Yes |

---

## Complete API Reference

Every method in the DaVinci Resolve Scripting API and its test status. Methods are listed by object class.

**Status Key:**
- ✅ = Tested live, returned expected result
- ⚠️ = Tested live, API accepted call (returned `False` — needs specific context to fully execute)
- ☁️ = Requires cloud infrastructure (untested)
- 🔬 = Requires specific content/hardware (untested — PRs welcome)

### Resolve

| # | Method | Status | Test Result / Notes |
|---|--------|--------|---------------------|
| 1 | `Fusion()` | ✅ | Returns Fusion object |
| 2 | `GetMediaStorage()` | ✅ | Returns MediaStorage object |
| 3 | `GetProjectManager()` | ✅ | Returns ProjectManager object |
| 4 | `OpenPage(pageName)` | ✅ | Switches Resolve page |
| 5 | `GetCurrentPage()` | ✅ | Returns current page name (e.g. `"edit"`) |
| 6 | `GetProductName()` | ✅ | Returns `"DaVinci Resolve Studio"` |
| 7 | `GetVersion()` | ✅ | Returns `[19, 1, 3, 7, '']` |
| 8 | `GetVersionString()` | ✅ | Returns `"19.1.3.7"` |
| 9 | `LoadLayoutPreset(presetName)` | ✅ | Loads saved layout |
| 10 | `UpdateLayoutPreset(presetName)` | ✅ | Updates existing preset |
| 11 | `ExportLayoutPreset(presetName, presetFilePath)` | ✅ | Exports preset to file |
| 12 | `DeleteLayoutPreset(presetName)` | ✅ | Deletes preset |
| 13 | `SaveLayoutPreset(presetName)` | ⚠️ | API accepts; returns `False` when preset name conflicts |
| 14 | `ImportLayoutPreset(presetFilePath, presetName)` | ✅ | Imports preset from file |
| 15 | `Quit()` | ✅ | Quits DaVinci Resolve |
| 16 | `ImportRenderPreset(presetPath)` | ⚠️ | API accepts; needs valid preset file |
| 17 | `ExportRenderPreset(presetName, exportPath)` | ⚠️ | API accepts; needs valid preset name |
| 18 | `ImportBurnInPreset(presetPath)` | ⚠️ | API accepts; needs valid preset file |
| 19 | `ExportBurnInPreset(presetName, exportPath)` | ⚠️ | API accepts; needs valid preset name |
| 20 | `GetKeyframeMode()` | ✅ | Returns keyframe mode |
| 21 | `SetKeyframeMode(keyframeMode)` | ⚠️ | API accepts; mode must match valid enum |
| 22 | `GetFairlightPresets()` | ✅ | Resolve 20.3.2 live test returns preset map |

### ProjectManager

| # | Method | Status | Test Result / Notes |
|---|--------|--------|---------------------|
| 1 | `ArchiveProject(projectName, filePath, ...)` | ⚠️ | API accepts; archiving is slow |
| 2 | `CreateProject(projectName, mediaLocationPath)` | ✅ | Creates new project; optional media location added in Resolve 20.2.2 |
| 3 | `DeleteProject(projectName)` | ⚠️ | Returns `False` if project is open |
| 4 | `LoadProject(projectName)` | ✅ | Returns Project object |
| 5 | `GetCurrentProject()` | ✅ | Returns current Project |
| 6 | `SaveProject()` | ✅ | Saves current project |
| 7 | `CloseProject(project)` | ✅ | Closes project |
| 8 | `CreateFolder(folderName)` | ✅ | Creates project folder |
| 9 | `DeleteFolder(folderName)` | ✅ | Deletes project folder |
| 10 | `GetProjectListInCurrentFolder()` | ✅ | Returns project name list |
| 11 | `GetFolderListInCurrentFolder()` | ✅ | Returns folder name list |
| 12 | `GotoRootFolder()` | ✅ | Navigates to root |
| 13 | `GotoParentFolder()` | ✅ | Returns `False` at root (expected) |
| 14 | `GetCurrentFolder()` | ✅ | Returns current folder name |
| 15 | `OpenFolder(folderName)` | ✅ | Opens folder |
| 16 | `ImportProject(filePath, projectName)` | ✅ | Imports .drp file |
| 17 | `ExportProject(projectName, filePath, ...)` | ✅ | Exports .drp file |
| 18 | `RestoreProject(filePath, projectName)` | ⚠️ | API accepts; needs backup archive |
| 19 | `GetCurrentDatabase()` | ✅ | Returns `{DbType, DbName}` |
| 20 | `GetDatabaseList()` | ✅ | Returns list of databases |
| 21 | `SetCurrentDatabase({dbInfo})` | ✅ | Switches database |
| 22 | `CreateCloudProject({cloudSettings})` | ☁️ | Requires cloud infrastructure |
| 23 | `LoadCloudProject({cloudSettings})` | ☁️ | Requires cloud infrastructure |
| 24 | `ImportCloudProject(filePath, {cloudSettings})` | ☁️ | Requires cloud infrastructure |
| 25 | `RestoreCloudProject(folderPath, {cloudSettings})` | ☁️ | Requires cloud infrastructure |

### Project

| # | Method | Status | Test Result / Notes |
|---|--------|--------|---------------------|
| 1 | `GetMediaPool()` | ✅ | Returns MediaPool object |
| 2 | `GetTimelineCount()` | ✅ | Returns integer count |
| 3 | `GetTimelineByIndex(idx)` | ✅ | Returns Timeline object |
| 4 | `GetCurrentTimeline()` | ✅ | Returns current Timeline |
| 5 | `SetCurrentTimeline(timeline)` | ✅ | Sets active timeline |
| 6 | `GetGallery()` | ✅ | Returns Gallery object |
| 7 | `GetName()` | ✅ | Returns project name |
| 8 | `SetName(projectName)` | ⚠️ | Returns `False` on open project |
| 9 | `GetPresetList()` | ✅ | Returns preset list with dimensions |
| 10 | `SetPreset(presetName)` | ⚠️ | API accepts; preset must exist |
| 11 | `AddRenderJob()` | ✅ | Returns job ID string |
| 12 | `DeleteRenderJob(jobId)` | ✅ | Deletes render job |
| 13 | `DeleteAllRenderJobs()` | ✅ | Clears render queue |
| 14 | `GetRenderJobList()` | ✅ | Returns job list |
| 15 | `GetRenderPresetList()` | ✅ | Returns preset names |
| 16 | `StartRendering(...)` | ✅ | Starts render |
| 17 | `StopRendering()` | ✅ | Stops render |
| 18 | `IsRenderingInProgress()` | ✅ | Returns `False` when idle |
| 19 | `LoadRenderPreset(presetName)` | ✅ | Loads render preset |
| 20 | `SaveAsNewRenderPreset(presetName)` | ✅ | Creates render preset |
| 21 | `DeleteRenderPreset(presetName)` | ✅ | Deletes render preset |
| 22 | `SetRenderSettings({settings})` | ✅ | Applies render settings; Resolve 20.2 adds `ExportSubtitle` and `SubtitleFormat` keys |
| 23 | `GetRenderJobStatus(jobId)` | ✅ | Returns `{JobStatus, CompletionPercentage}` |
| 24 | `GetQuickExportRenderPresets()` | ✅ | Returns preset names |
| 25 | `RenderWithQuickExport(preset, {params})` | ✅ | Initiates quick export |
| 26 | `GetSetting(settingName)` | ✅ | Returns project settings dict |
| 27 | `SetSetting(settingName, settingValue)` | ✅ | Sets project setting |
| 28 | `GetRenderFormats()` | ✅ | Returns format map |
| 29 | `GetRenderCodecs(renderFormat)` | ✅ | Returns codec map |
| 30 | `GetCurrentRenderFormatAndCodec()` | ✅ | Returns `{format, codec}` |
| 31 | `SetCurrentRenderFormatAndCodec(format, codec)` | ✅ | Sets format and codec |
| 32 | `GetCurrentRenderMode()` | ✅ | Returns mode integer |
| 33 | `SetCurrentRenderMode(renderMode)` | ✅ | Sets render mode |
| 34 | `GetRenderResolutions(format, codec)` | ✅ | Returns resolution list |
| 35 | `RefreshLUTList()` | ✅ | Refreshes LUT list |
| 36 | `GetUniqueId()` | ✅ | Returns UUID string |
| 37 | `InsertAudioToCurrentTrackAtPlayhead(...)` | ⚠️ | Tested; needs Fairlight page context |
| 38 | `LoadBurnInPreset(presetName)` | ⚠️ | API accepts; preset must exist |
| 39 | `ExportCurrentFrameAsStill(filePath)` | ⚠️ | API accepts; needs valid playhead position |
| 40 | `GetColorGroupsList()` | ✅ | Returns color group list |
| 41 | `AddColorGroup(groupName)` | ✅ | Returns ColorGroup object |
| 42 | `DeleteColorGroup(colorGroup)` | ✅ | Deletes color group |
| 43 | `ApplyFairlightPresetToCurrentTimeline(presetName)` | ⚠️ | Resolve 20.3.2 live test accepts call; returns `False` without a named preset |

### MediaStorage

| # | Method | Status | Test Result / Notes |
|---|--------|--------|---------------------|
| 1 | `GetMountedVolumeList()` | ✅ | Returns mounted volume paths |
| 2 | `GetSubFolderList(folderPath)` | ✅ | Returns subfolder paths |
| 3 | `GetFileList(folderPath)` | ✅ | Returns file paths |
| 4 | `RevealInStorage(path)` | ✅ | Reveals path in Media Storage |
| 5 | `AddItemListToMediaPool(...)` | ✅ | Imports media, returns clips |
| 6 | `AddClipMattesToMediaPool(item, [paths], eye)` | ✅ | Adds clip mattes |
| 7 | `AddTimelineMattesToMediaPool([paths])` | ✅ | Returns MediaPoolItem list |

### MediaPool

| # | Method | Status | Test Result / Notes |
|---|--------|--------|---------------------|
| 1 | `GetRootFolder()` | ✅ | Returns root Folder |
| 2 | `AddSubFolder(folder, name)` | ✅ | Creates subfolder |
| 3 | `RefreshFolders()` | ✅ | Refreshes folder list |
| 4 | `CreateEmptyTimeline(name)` | ✅ | Creates timeline |
| 5 | `AppendToTimeline(...)` | ✅ | Appends clips, returns TimelineItems |
| 6 | `CreateTimelineFromClips(name, ...)` | ✅ | Creates timeline from clips |
| 7 | `ImportTimelineFromFile(filePath, {options})` | ✅ | Imports AAF/EDL/XML |
| 8 | `DeleteTimelines([timeline])` | ✅ | Deletes timelines |
| 9 | `GetCurrentFolder()` | ✅ | Returns current Folder |
| 10 | `SetCurrentFolder(folder)` | ✅ | Sets current folder |
| 11 | `DeleteClips([clips])` | ✅ | Deletes clips |
| 12 | `ImportFolderFromFile(filePath)` | ✅ | Imports DRB folder |
| 13 | `DeleteFolders([subfolders])` | ✅ | Deletes folders |
| 14 | `MoveClips([clips], targetFolder)` | ✅ | Moves clips |
| 15 | `MoveFolders([folders], targetFolder)` | ✅ | Moves folders |
| 16 | `GetClipMatteList(item)` | ✅ | Returns matte paths |
| 17 | `GetTimelineMatteList(folder)` | ✅ | Returns matte items |
| 18 | `DeleteClipMattes(item, [paths])` | ✅ | Deletes clip mattes |
| 19 | `RelinkClips([items], folderPath)` | ⚠️ | API accepts; needs offline clips |
| 20 | `UnlinkClips([items])` | ✅ | Unlinks clips |
| 21 | `ImportMedia([items])` | ✅ | Imports media files |
| 22 | `ExportMetadata(fileName, [clips])` | ✅ | Exports metadata CSV |
| 23 | `GetUniqueId()` | ✅ | Returns UUID string |
| 24 | `CreateStereoClip(left, right)` | ✅ | Creates stereo pair |
| 25 | `AutoSyncAudio([items], {settings})` | ⚠️ | Tested; needs matching A/V clips |
| 26 | `GetSelectedClips()` | ✅ | Returns selected clips |
| 27 | `SetSelectedClip(item)` | ✅ | Selects clip |

### Folder

| # | Method | Status | Test Result / Notes |
|---|--------|--------|---------------------|
| 1 | `GetClipList()` | ✅ | Returns clip list |
| 2 | `GetName()` | ✅ | Returns folder name |
| 3 | `GetSubFolderList()` | ✅ | Returns subfolder list |
| 4 | `GetIsFolderStale()` | ✅ | Returns `False` |
| 5 | `GetUniqueId()` | ✅ | Returns UUID string |
| 6 | `Export(filePath)` | ✅ | Exports DRB file |
| 7 | `TranscribeAudio()` | ✅ | Starts audio transcription |
| 8 | `ClearTranscription()` | ✅ | Clears transcription |

### MediaPoolItem

| # | Method | Status | Test Result / Notes |
|---|--------|--------|---------------------|
| 1 | `GetName()` | ✅ | Returns clip name |
| 2 | `GetMetadata(metadataType)` | ✅ | Returns metadata dict |
| 3 | `SetMetadata(type, value)` | ✅ | Sets metadata |
| 4 | `GetThirdPartyMetadata(type)` | ✅ | Returns third-party metadata |
| 5 | `SetThirdPartyMetadata(type, value)` | ✅ | Sets third-party metadata |
| 6 | `GetMediaId()` | ✅ | Returns media UUID |
| 7 | `AddMarker(frameId, color, name, note, duration, customData)` | ✅ | Adds marker |
| 8 | `GetMarkers()` | ✅ | Returns marker dict |
| 9 | `GetMarkerByCustomData(customData)` | ✅ | Finds marker by data |
| 10 | `UpdateMarkerCustomData(frameId, customData)` | ✅ | Updates marker data |
| 11 | `GetMarkerCustomData(frameId)` | ✅ | Returns custom data string |
| 12 | `DeleteMarkersByColor(color)` | ✅ | Deletes markers by color |
| 13 | `DeleteMarkerAtFrame(frameNum)` | ⚠️ | Returns `False` if no marker at frame |
| 14 | `DeleteMarkerByCustomData(customData)` | ⚠️ | Returns `False` if no match |
| 15 | `AddFlag(color)` | ✅ | Adds flag |
| 16 | `GetFlagList()` | ✅ | Returns flag colors |
| 17 | `ClearFlags(color)` | ✅ | Clears flags |
| 18 | `GetClipColor()` | ✅ | Returns clip color |
| 19 | `SetClipColor(colorName)` | ✅ | Sets clip color |
| 20 | `ClearClipColor()` | ✅ | Clears clip color |
| 21 | `GetClipProperty(propertyName)` | ✅ | Returns property dict |
| 22 | `SetClipProperty(propertyName, value)` | ⚠️ | API accepts; some properties read-only |
| 23 | `LinkProxyMedia(proxyMediaFilePath)` | ✅ | Links proxy media |
| 24 | `UnlinkProxyMedia()` | ✅ | Unlinks proxy media |
| 25 | `ReplaceClip(filePath)` | ✅ | Replaces clip source |
| 26 | `GetUniqueId()` | ✅ | Returns UUID string |
| 27 | `TranscribeAudio()` | ✅ | Starts audio transcription |
| 28 | `ClearTranscription()` | ✅ | Clears transcription |
| 29 | `GetAudioMapping()` | ✅ | Returns JSON audio mapping |
| 30 | `GetMarkInOut()` | ✅ | Returns mark in/out dict |
| 31 | `SetMarkInOut(in, out, type)` | ✅ | Sets mark in/out |
| 32 | `ClearMarkInOut(type)` | ✅ | Clears mark in/out |
| 33 | `SetName(clipName)` | ✅ | Resolve 20.3.2 live test renames clip |
| 34 | `LinkFullResolutionMedia(filePath)` | ⚠️ | Resolve 20.3.2 live test accepts call; full-res relink returns `False` without a matching proxy/full-res fixture |
| 35 | `ReplaceClipPreserveSubClip(filePath)` | ✅ | Resolve 20.3.2 live test replaces clip while preserving subclip metadata |
| 36 | `MonitorGrowingFile()` | ✅ | Resolve 20.3.2 live test enables growing-file monitoring |

### Timeline

| # | Method | Status | Test Result / Notes |
|---|--------|--------|---------------------|
| 1 | `GetName()` | ✅ | Returns timeline name |
| 2 | `SetName(timelineName)` | ⚠️ | Returns `False` on active timeline |
| 3 | `GetStartFrame()` | ✅ | Returns start frame |
| 4 | `GetEndFrame()` | ✅ | Returns end frame |
| 5 | `SetStartTimecode(timecode)` | ✅ | Sets start timecode |
| 6 | `GetStartTimecode()` | ✅ | Returns `"01:00:00:00"` |
| 7 | `GetTrackCount(trackType)` | ✅ | Returns track count |
| 8 | `AddTrack(trackType, subTrackType)` | ✅ | Adds track |
| 9 | `DeleteTrack(trackType, trackIndex)` | ✅ | Deletes track |
| 10 | `GetTrackSubType(trackType, trackIndex)` | ✅ | Returns sub-type (e.g. `"stereo"`) |
| 11 | `SetTrackEnable(trackType, trackIndex, enabled)` | ✅ | Enables/disables track |
| 12 | `GetIsTrackEnabled(trackType, trackIndex)` | ✅ | Returns enabled state |
| 13 | `SetTrackLock(trackType, trackIndex, locked)` | ✅ | Locks/unlocks track |
| 14 | `GetIsTrackLocked(trackType, trackIndex)` | ✅ | Returns lock state |
| 15 | `DeleteClips([timelineItems], ripple)` | ✅ | Deletes clips from timeline |
| 16 | `SetClipsLinked([timelineItems], linked)` | ✅ | Links/unlinks clips |
| 17 | `GetItemListInTrack(trackType, index)` | ✅ | Returns items on track |
| 18 | `AddMarker(frameId, color, name, note, duration, customData)` | ✅ | Adds timeline marker |
| 19 | `GetMarkers()` | ✅ | Returns marker dict |
| 20 | `GetMarkerByCustomData(customData)` | ✅ | Finds marker by data |
| 21 | `UpdateMarkerCustomData(frameId, customData)` | ✅ | Updates marker data |
| 22 | `GetMarkerCustomData(frameId)` | ✅ | Returns custom data |
| 23 | `DeleteMarkersByColor(color)` | ✅ | Deletes markers by color |
| 24 | `DeleteMarkerAtFrame(frameNum)` | ⚠️ | Returns `False` if no marker at frame |
| 25 | `DeleteMarkerByCustomData(customData)` | ⚠️ | Returns `False` if no match |
| 26 | `GetCurrentTimecode()` | ✅ | Returns timecode string |
| 27 | `SetCurrentTimecode(timecode)` | ⚠️ | Returns `False` if playback not active |
| 28 | `GetCurrentVideoItem()` | ✅ | Returns item at playhead |
| 29 | `GetCurrentClipThumbnailImage()` | ✅ | Returns thumbnail data |
| 30 | `GetTrackName(trackType, trackIndex)` | ✅ | Returns track name |
| 31 | `SetTrackName(trackType, trackIndex, name)` | ✅ | Sets track name |
| 32 | `DuplicateTimeline(timelineName)` | ✅ | Duplicates timeline |
| 33 | `CreateCompoundClip([items], {clipInfo})` | ✅ | Returns compound clip item |
| 34 | `CreateFusionClip([timelineItems])` | ✅ | Returns Fusion clip item |
| 35 | `ImportIntoTimeline(filePath, {options})` | ⚠️ | Tested; result depends on file format |
| 36 | `Export(fileName, exportType, exportSubtype)` | ✅ | Exports EDL/XML/AAF |
| 37 | `GetSetting(settingName)` | ✅ | Returns settings dict |
| 38 | `SetSetting(settingName, settingValue)` | ⚠️ | API accepts; some settings read-only |
| 39 | `InsertGeneratorIntoTimeline(name)` | ✅ | Inserts generator |
| 40 | `InsertFusionGeneratorIntoTimeline(name)` | ✅ | Inserts Fusion generator |
| 41 | `InsertFusionCompositionIntoTimeline()` | ✅ | Inserts Fusion composition |
| 42 | `InsertOFXGeneratorIntoTimeline(name)` | ⚠️ | API accepts; needs valid OFX plugin |
| 43 | `InsertTitleIntoTimeline(name)` | ✅ | Inserts title |
| 44 | `InsertFusionTitleIntoTimeline(name)` | ✅ | Inserts Fusion title |
| 45 | `GrabStill()` | ✅ | Returns GalleryStill object |
| 46 | `GrabAllStills(stillFrameSource)` | ✅ | Returns list of GalleryStill objects |
| 47 | `GetUniqueId()` | ✅ | Returns UUID string |
| 48 | `CreateSubtitlesFromAudio({settings})` | ✅ | Returns `True` — creates subtitles from audio |
| 49 | `DetectSceneCuts()` | ✅ | Returns `True` — detects scene cuts in timeline |
| 50 | `ConvertTimelineToStereo()` | ✅ | Converts timeline to stereo 3D |
| 51 | `GetNodeGraph()` | ✅ | Returns Graph object |
| 52 | `AnalyzeDolbyVision([items], analysisType)` | 🔬 | Requires HDR/Dolby Vision content |
| 53 | `GetMediaPoolItem()` | ✅ | Returns MediaPoolItem for timeline |
| 54 | `GetMarkInOut()` | ✅ | Returns mark in/out dict |
| 55 | `SetMarkInOut(in, out, type)` | ✅ | Sets mark in/out |
| 56 | `ClearMarkInOut(type)` | ✅ | Clears mark in/out |
| 57 | `GetVoiceIsolationState(trackIndex)` | ✅ | Resolve 20.3.2 live test returns voice isolation state |
| 58 | `SetVoiceIsolationState(trackIndex, {state})` | ✅ | Resolve 20.3.2 live test sets voice isolation state |

### TimelineItem

| # | Method | Status | Test Result / Notes |
|---|--------|--------|---------------------|
| 1 | `GetName()` | ✅ | Returns item name |
| 2 | `GetDuration(subframe_precision)` | ✅ | Returns duration |
| 3 | `GetEnd(subframe_precision)` | ✅ | Returns end frame |
| 4 | `GetSourceEndFrame()` | ✅ | Returns source end frame |
| 5 | `GetSourceEndTime()` | ✅ | Returns source end time |
| 6 | `GetFusionCompCount()` | ✅ | Returns comp count |
| 7 | `GetFusionCompByIndex(compIndex)` | ✅ | Returns Fusion composition |
| 8 | `GetFusionCompNameList()` | ✅ | Returns comp names |
| 9 | `GetFusionCompByName(compName)` | ✅ | Returns Fusion composition |
| 10 | `GetLeftOffset(subframe_precision)` | ✅ | Returns left offset |
| 11 | `GetRightOffset(subframe_precision)` | ✅ | Returns right offset |
| 12 | `GetStart(subframe_precision)` | ✅ | Returns start frame |
| 13 | `GetSourceStartFrame()` | ✅ | Returns source start |
| 14 | `GetSourceStartTime()` | ✅ | Returns source start time |
| 15 | `SetProperty(propertyKey, propertyValue)` | ✅ | Sets item property |
| 16 | `GetProperty(propertyKey)` | ✅ | Returns property dict |
| 17 | `AddMarker(frameId, color, name, note, duration, customData)` | ✅ | Adds marker to item |
| 18 | `GetMarkers()` | ✅ | Returns marker dict |
| 19 | `GetMarkerByCustomData(customData)` | ✅ | Finds marker by data |
| 20 | `UpdateMarkerCustomData(frameId, customData)` | ✅ | Updates marker data |
| 21 | `GetMarkerCustomData(frameId)` | ✅ | Returns custom data |
| 22 | `DeleteMarkersByColor(color)` | ✅ | Deletes markers by color |
| 23 | `DeleteMarkerAtFrame(frameNum)` | ⚠️ | Returns `False` if no marker at frame |
| 24 | `DeleteMarkerByCustomData(customData)` | ⚠️ | Returns `False` if no match |
| 25 | `AddFlag(color)` | ✅ | Adds flag |
| 26 | `GetFlagList()` | ✅ | Returns flag colors |
| 27 | `ClearFlags(color)` | ✅ | Clears flags |
| 28 | `GetClipColor()` | ✅ | Returns clip color |
| 29 | `SetClipColor(colorName)` | ✅ | Sets clip color |
| 30 | `ClearClipColor()` | ✅ | Clears clip color |
| 31 | `AddFusionComp()` | ✅ | Creates Fusion composition |
| 32 | `ImportFusionComp(path)` | ✅ | Imports .comp file |
| 33 | `ExportFusionComp(path, compIndex)` | ✅ | Exports .comp file |
| 34 | `DeleteFusionCompByName(compName)` | ⚠️ | Returns `False` if comp not found |
| 35 | `LoadFusionCompByName(compName)` | ✅ | Loads composition |
| 36 | `RenameFusionCompByName(oldName, newName)` | ✅ | Renames composition |
| 37 | `AddVersion(versionName, versionType)` | ✅ | Adds grade version |
| 38 | `GetCurrentVersion()` | ✅ | Returns version info |
| 39 | `DeleteVersionByName(versionName, versionType)` | ⚠️ | Returns `False` if version not found |
| 40 | `LoadVersionByName(versionName, versionType)` | ✅ | Loads grade version |
| 41 | `RenameVersionByName(oldName, newName, type)` | ✅ | Renames version |
| 42 | `GetVersionNameList(versionType)` | ✅ | Returns version names |
| 43 | `GetMediaPoolItem()` | ✅ | Returns source MediaPoolItem |
| 44 | `GetStereoConvergenceValues()` | ✅ | Returns stereo keyframes |
| 45 | `GetStereoLeftFloatingWindowParams()` | ✅ | Returns stereo params |
| 46 | `GetStereoRightFloatingWindowParams()` | ✅ | Returns stereo params |
| 47 | `SetCDL([CDL map])` | ✅ | Sets CDL values |
| 48 | `AddTake(mediaPoolItem, startFrame, endFrame)` | ✅ | Adds take |
| 49 | `GetSelectedTakeIndex()` | ✅ | Returns selected take index |
| 50 | `GetTakesCount()` | ✅ | Returns take count |
| 51 | `GetTakeByIndex(idx)` | ✅ | Returns take info |
| 52 | `DeleteTakeByIndex(idx)` | ✅ | Deletes take |
| 53 | `SelectTakeByIndex(idx)` | ✅ | Selects take |
| 54 | `FinalizeTake()` | ⚠️ | Returns `False` when no take selected |
| 55 | `CopyGrades([tgtTimelineItems])` | ⚠️ | API accepts; needs matching items |
| 56 | `SetClipEnabled(enabled)` | ✅ | Enables/disables clip |
| 57 | `GetClipEnabled()` | ✅ | Returns enabled state |
| 58 | `UpdateSidecar()` | ⚠️ | Returns `False` for non-BRAW clips |
| 59 | `GetUniqueId()` | ✅ | Returns UUID string |
| 60 | `LoadBurnInPreset(presetName)` | ⚠️ | API accepts; preset must exist |
| 61 | `CreateMagicMask(mode)` | ⚠️ | Tested; needs DaVinci Neural Engine + Color page context |
| 62 | `RegenerateMagicMask()` | ⚠️ | Tested; needs existing mask |
| 63 | `Stabilize()` | ✅ | Returns `True` on supported clips |
| 64 | `SmartReframe()` | ⚠️ | Tested; needs specific aspect ratio setup |
| 65 | `GetNodeGraph(layerIdx)` | ✅ | Returns Graph object |
| 66 | `GetColorGroup()` | ✅ | Returns ColorGroup |
| 67 | `AssignToColorGroup(colorGroup)` | ✅ | Assigns to group |
| 68 | `RemoveFromColorGroup()` | ⚠️ | Returns `False` if not in group |
| 69 | `ExportLUT(exportType, path)` | ✅ | Exports LUT file |
| 70 | `GetLinkedItems()` | ✅ | Returns linked items |
| 71 | `GetTrackTypeAndIndex()` | ✅ | Returns `[trackType, trackIndex]` |
| 72 | `GetSourceAudioChannelMapping()` | ✅ | Returns audio mapping |
| 73 | `GetIsColorOutputCacheEnabled()` | ✅ | Returns cache state |
| 74 | `GetIsFusionOutputCacheEnabled()` | ✅ | Returns cache state |
| 75 | `SetColorOutputCache(cache_value)` | ⚠️ | Tested; needs active color pipeline |
| 76 | `SetFusionOutputCache(cache_value)` | ⚠️ | Tested; needs active Fusion pipeline |
| 77 | `SetName(clipName)` | ✅ | Resolve 20.3.2 live test renames timeline item |
| 78 | `GetVoiceIsolationState()` | ✅ | Resolve 20.3.2 live test returns voice isolation state |
| 79 | `SetVoiceIsolationState({state})` | ✅ | Resolve 20.3.2 live test sets voice isolation state |
| 80 | `ResetAllNodeColors()` | ✅ | Resolve 20.3.2 live test resets node colors |

### Gallery

| # | Method | Status | Test Result / Notes |
|---|--------|--------|---------------------|
| 1 | `GetAlbumName(galleryStillAlbum)` | ✅ | Returns album name |
| 2 | `SetAlbumName(galleryStillAlbum, albumName)` | ✅ | Sets album name |
| 3 | `GetCurrentStillAlbum()` | ✅ | Returns GalleryStillAlbum |
| 4 | `SetCurrentStillAlbum(galleryStillAlbum)` | ✅ | Sets current album |
| 5 | `GetGalleryStillAlbums()` | ✅ | Returns album list |
| 6 | `GetGalleryPowerGradeAlbums()` | ✅ | Returns power grade albums |
| 7 | `CreateGalleryStillAlbum()` | ✅ | Creates still album |
| 8 | `CreateGalleryPowerGradeAlbum()` | ✅ | Creates power grade album |

### GalleryStillAlbum

| # | Method | Status | Test Result / Notes |
|---|--------|--------|---------------------|
| 1 | `GetStills()` | ✅ | Returns list of GalleryStill objects |
| 2 | `GetLabel(galleryStill)` | ✅ | Returns label string |
| 3 | `SetLabel(galleryStill, label)` | ⚠️ | API accepts; may not persist in all versions |
| 4 | `ImportStills([filePaths])` | ✅ | Imports DRX still files (requires Color page) |
| 5 | `ExportStills([stills], folderPath, prefix, format)` | ✅ | Exports stills as image + companion .drx grade file. Requires Color page with Gallery panel visible. Supported formats: dpx, cin, tif, jpg, png, ppm, bmp, xpm, drx. |
| 6 | `DeleteStills([galleryStill])` | ✅ | Deletes stills from album |

> **Note (v2.0.8+):** The compound server's `gallery_stills` tool includes a `grab_and_export` action that combines `GrabStill()` + `ExportStills()` in a single call — more reliable than calling them separately since it keeps the live GalleryStill reference. Returns the list of exported files (image + .drx grade data). Requires the Color page with the Gallery panel open.

### Graph

| # | Method | Status | Test Result / Notes |
|---|--------|--------|---------------------|
| 1 | `GetNumNodes()` | ✅ | Returns node count (via ColorGroup pre/post graphs) |
| 2 | `SetLUT(nodeIndex, lutPath)` | ✅ | Sets LUT on node |
| 3 | `GetLUT(nodeIndex)` | ✅ | Returns LUT path |
| 4 | `SetNodeCacheMode(nodeIndex, cache_value)` | ✅ | Returns `True` |
| 5 | `GetNodeCacheMode(nodeIndex)` | ✅ | Returns `-1` (no cache mode set) |
| 6 | `GetNodeLabel(nodeIndex)` | ✅ | Returns node label string |
| 7 | `GetToolsInNode(nodeIndex)` | ✅ | Returns `None` (no OFX tools in node) |
| 8 | `SetNodeEnabled(nodeIndex, isEnabled)` | ✅ | Returns `True` |
| 9 | `ApplyGradeFromDRX(path, gradeMode)` | ✅ | Applies grade from DRX file |
| 10 | `ApplyArriCdlLut()` | ✅ | Applies ARRI CDL LUT |
| 11 | `ResetAllGrades()` | ✅ | Resets all grades |

### ColorGroup

| # | Method | Status | Test Result / Notes |
|---|--------|--------|---------------------|
| 1 | `GetName()` | ✅ | Returns group name |
| 2 | `SetName(groupName)` | ✅ | Sets group name |
| 3 | `GetClipsInTimeline(timeline)` | ✅ | Returns clips in group |
| 4 | `GetPreClipNodeGraph()` | ✅ | Returns Graph object |
| 5 | `GetPostClipNodeGraph()` | ✅ | Returns Graph object |

---

## Contributing

We welcome contributions! The following areas especially need help:

### Help Wanted: Untested API Methods

**5 methods** (1.5%) remain untested against a live DaVinci Resolve instance. If you have access to the required infrastructure or content, we'd love a PR with test confirmation:

1. **Cloud Project Methods** (4 methods) — Need DaVinci Resolve cloud infrastructure:
   - `ProjectManager.CreateCloudProject`
   - `ProjectManager.LoadCloudProject`
   - `ProjectManager.ImportCloudProject`
   - `ProjectManager.RestoreCloudProject`

2. **HDR Analysis** (1 method) — Needs specific content:
   - `Timeline.AnalyzeDolbyVision` — needs HDR/Dolby Vision content

### How to Contribute

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-contribution`)
3. Run the existing test suite to ensure nothing breaks
4. Add your test results or fixes
5. Submit a pull request

### Other Contribution Ideas

- **Windows testing** — All tests were run on macOS; Windows verification welcome
- **Linux testing** — DaVinci Resolve supports Linux; test coverage needed
- **Resolve version compatibility** — Test against Resolve 18.x, 19.0, or newer versions
- **Bug reports** — If a tool returns unexpected results on your setup, file an issue
- **Documentation** — Improve examples, add tutorials, translate docs

## Platform Support

| Platform | Status | Resolve Paths Auto-Detected | Notes |
|----------|--------|----------------------------|-------|
| macOS | ✅ Tested | `/Library/Application Support/Blackmagic Design/...` | Primary development and test platform |
| Windows | ✅ Supported | `C:\ProgramData\Blackmagic Design\...` | Community-tested; installer now emits env + `PYTHONHOME` for Resolve 20.3 multi-Python setups |
| Linux | ⚠️ Experimental | `/opt/resolve/...` | Should work — testing and feedback welcome |

## Security Considerations

This MCP server controls DaVinci Resolve via its Scripting API. Some tools perform actions that are destructive or interact with the host filesystem:

| Tool | Risk | Mitigation |
|------|------|------------|
| `quit_app` / `restart_app` | Terminates the Resolve process — can cause data loss if unsaved changes exist or a render is in progress | MCP clients should require explicit user confirmation before calling these tools. Subprocess calls use hardcoded command lists (no shell injection possible). |
| `export_layout_preset` / `import_layout_preset` / `delete_layout_preset` | Read/write/delete files in the Resolve layout presets directory | Path traversal protection validates all resolved paths stay within the expected presets directory (v2.0.7+). |
| `save_project` | Creates and removes a temporary `.drp` file in the system temp directory | Path is constructed server-side with no LLM-controlled input. |

**Recommendations for MCP client developers:**
- Enable tool-call confirmation prompts for destructive tools (`quit_app`, `restart_app`, `delete_layout_preset`)
- Do not grant blanket auto-approval to all tools in this server

## Project Structure

```
davinci-resolve-mcp/
├── install.py                    # Universal installer (macOS/Windows/Linux)
├── src/
│   ├── server.py                # Compound MCP server — 30 tools (default)
│   ├── resolve_mcp_server.py    # Thin full-server entrypoint — 328 tools
│   ├── granular/                # Modular full-server implementation
│   └── utils/                   # Platform detection, Resolve connection helpers
├── tests/                       # 5-phase live API test suite + Resolve 20 delta (331/331 pass)
├── docs/
│   └── resolve_scripting_api.txt # Official Resolve Scripting API reference
└── examples/                    # MCP prompt recipes for markers, media, and timeline workflows
```

## License

MIT

## Author

Samuel Gursky (samgursky@gmail.com)
- GitHub: [github.com/samuelgursky](https://github.com/samuelgursky)

## Acknowledgments

- Blackmagic Design for DaVinci Resolve and its scripting API
- The Model Context Protocol team for enabling AI assistant integration
- Anthropic for Claude Code, used extensively in development and testing
