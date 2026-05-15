# Changelog

Release history for the DaVinci Resolve MCP Server. The latest release is summarized in the root README; older entries live here to keep the README focused.

## What's New in v2.17.2

**Edit-page title / Text+ text (undocumented keys)** — `timeline.title_property_scan`,
`timeline.set_title_text`, and `timeline.bulk_set_title_text` use
`TimelineItem.GetProperty` / `SetProperty` to discover and update generator Text+
payloads when `GetFusionCompCount()` is zero (no Fusion comp for `fusion_comp`).
Heuristic key ranking and a minimal styled-text XML fallback are included; callers
should confirm keys with `title_property_scan` on their Resolve build.

## What's New in v2.17.1

Operational and client-safety hardening for the v2.17 media-analysis release.

**MCP tool metadata**: compound and granular tools now publish MCP
`ToolAnnotations` with conservative read-only, destructive, idempotent, and
external-resource hints. Compound tool annotations are intentionally conservative
because each tool groups multiple actions behind an `action` parameter.

**MCPSafe report cleanup**: explicitly annotated the granular tools highlighted
by the public MCPSafe report, including project settings, media import, page
switching, proxy linking, Gallery album reads, and timeline-item transforms.

**Operational guardrails**: Resolve app-control subprocess fallbacks now use
bounded timeouts and report non-zero exits. Best-effort Resolve object
inspection and state probes now log swallowed exceptions at debug level instead
of failing silently.

**Correctness fix**: fixed the granular
`media_pool.append_to_timeline(clip_infos=...)` path so it retains the current
project handle while normalizing positioned appends against the active timeline
start frame.

**Documentation**: added `SECURITY.md` with the local stdio trust boundary,
confirmation guidance for destructive tools, source-media safety boundaries, and
private vulnerability reporting guidance. The README now links the security
policy and summarizes the local-only auth posture.

**Validation**: static/import checks, API parity audit, compileall, and 161
focused unit tests passed. Live validated against DaVinci Resolve Studio 20.3.2.9
with a direct external-scripting smoke test, `tests/live_v233_validation.py`
passing 10/10 checks, and a v2.17.1 disposable-project
`media_pool.append_to_timeline(clip_infos=...)` normalization probe passing 2/2
checks. The v2.17.1 probe used synthetic media only and verified the default
relative `record_frame` path landed at timeline start frame 86400 + 12 = 86412,
while `record_frame_mode="absolute"` preserved frame 86484.

## What's New in v2.17.0

Media analysis and editorial-assist expansion - `media_analysis` now reuses
existing project reports when cache signatures satisfy the requested analysis
layers, can review timeline marker contact sheets with chat-context vision, and
`timeline` adds editor-facing helpers for story-spine reports, declarative
variant creation, bulk item property writes, multi-item look application,
thumbnail contact sheets, marker thumbnail review, and audio mix capability
fallback reporting.

**New `media_analysis` compound tool**: added `capabilities`,
`install_guidance`, `resolve_output_root`, `plan`, `analyze_file`,
`analyze_clip`, `analyze_bin`, `analyze_project`, `review_timeline_markers`,
`summarize`, `get_report`, and `cleanup_artifacts`.

**MCP prompts and visual review**: the compound server now registers
`davinci_resolve_workflow` and `analyze_media` prompts. `analyze_media` defaults
to chat-context visual analysis when MCP sampling is available, while
`timeline_markers.get_thumbnail_image` returns current Resolve frames as MCP
image content without writing a file.

**Source-safe editorial helpers**: timeline actions now support
`story_spine_report`, `create_variant_from_ranges`, `bulk_set_item_properties`,
`apply_look_to_items`, `thumbnail_contact_sheet`, `marker_thumbnail_review`, and
`audio_mix_capability_report`. Positioned timeline appends normalize
`record_frame` relative to the active timeline start by default, matching
Resolve's common 01:00:00:00 start-frame behavior.

**Documentation reorganization**: moved durable references into `docs/guides`,
`docs/kernels`, `docs/authoring`, `docs/notes`, `docs/process`, and
`docs/reference`, added a compact docs index, and kept local gameplans/scratch
artifacts ignored.

**Privacy cleanup**: sanitized tracked live-test fixtures and scripts that had
workstation-specific source-media paths while leaving public project contact
information intact.

**Validation**: static/import checks, API parity audit, and 141 focused unit
tests passed. Live validated against DaVinci Resolve Studio 20.3.2.9 with a
disposable `_mcp_media_analysis_v2170_probe` project and a generated synthetic
clip only. The run covered source-adjacent output-root rejection,
`media_analysis.plan`, session-only `analyze_file`, `story_spine_report`,
`audio_mix_capability_report`, raw thumbnail retrieval, `thumbnail_contact_sheet`,
and `review_timeline_markers`; the disposable project and temp artifacts were
cleaned up.

## v2.16.0

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
[`docs/kernels/extension-authoring-kernel.md`](docs/kernels/extension-authoring-kernel.md) and
updated the Fuse/DCTL and script authoring docs with live lifecycle findings.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with
MCP-marked `_mcp_` extension files only. Final probe result: 14 supported, 1
partially supported installed-Lua-script execution boundary, 1 intentional
unsupported unmarked-source guard, and 0 errors. All generated extension files
and the disposable project were cleaned up.

## v2.15.0

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
[`docs/kernels/project-lifecycle-kernel.md`](docs/kernels/project-lifecycle-kernel.md) with
project CRUD, DRP import/export, archive/restore, folder, settings, database,
layout preset, render preset, page, keyframe, and cloud-infrastructure
boundaries.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with
disposable `_mcp_` projects only. Final probe result: 35 supported, 5 partially
supported lifecycle/archive/keyframe/render-preset boundaries, 1 intentional
unsupported archive media-flag guard, 1 not-applicable archive restore boundary,
and 0 errors. Disposable projects, layout presets, and temp work files were
cleaned up.

## v2.14.0

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
[`docs/kernels/audio-fairlight-kernel.md`](docs/kernels/audio-fairlight-kernel.md) with
track/item state, voice isolation, mapping, transcription, subtitle, auto-sync,
and Fairlight insertion boundaries.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with
generated synthetic video and audio-only media. Final probe result: 13
supported, 3 partially supported audio property/auto-sync/audio-insert
boundaries, and 0 errors. The disposable project and generated media were
cleaned up.

## v2.13.0

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
[`docs/kernels/timeline-conform-interchange-kernel.md`](docs/kernels/timeline-conform-interchange-kernel.md)
with export, round-trip, missing-media, relink planning, and format-survival
boundaries.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with a
generated synthetic gapped timeline. Final probe result: 17 supported, 1
partially supported FCPXML round-trip survivability boundary, and 0 errors. The
disposable project, generated media, and imported round-trip timelines were
cleaned up.

## v2.12.0

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
[`docs/kernels/fusion-composition-kernel.md`](docs/kernels/fusion-composition-kernel.md) with
tool availability, input/output, scope, comp export, and page-state boundaries.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with a
generated synthetic timeline item Fusion comp. Final probe result: 18
supported, 0 unsupported, 0 partially supported, and 0 errors. The disposable
project, generated media, and exported temp comp were cleaned up.

## v2.11.0

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
[`docs/kernels/color-grade-kernel.md`](docs/kernels/color-grade-kernel.md) with graph, LUT, DRX,
version, Gallery, color-group, and AI-tool boundaries.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with a
generated synthetic color-bar timeline. Final probe result: 25 supported, 2
version/page-dependent Gallery/DRX export boundaries, 1 not-applicable DRX apply
path because no DRX could be produced in that run, and 0 errors. The disposable
project, generated media, and temp LUT exports were cleaned up.

## v2.10.0

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
[`docs/kernels/review-annotation-kernel.md`](docs/kernels/review-annotation-kernel.md) with the
scope matrix, field support, frame-space caveats, and live probe findings.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with a
generated synthetic timeline. Final probe result: 44 supported, 1 expected
unsupported invalid-color boundary, and 0 errors. The disposable project and
generated media were cleaned up after report generation.

## v2.9.0

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
[`docs/kernels/render-deliver-kernel.md`](docs/kernels/render-deliver-kernel.md) with
format/codec, settings, render job, and Quick Export boundaries.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with a
two-second generated synthetic timeline. Final probe result: 23 supported, 1
version/page-dependent `GetRenderSettings` readback boundary, and 0 errors. The
probe rendered one tiny synthetic output, then cleaned up the disposable project
and generated files.

## v2.8.0

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
[`docs/kernels/media-pool-ingest-kernel.md`](docs/kernels/media-pool-ingest-kernel.md) so
agents and users can inspect the supported, partial, unsupported, and
version/page-dependent ingest boundaries directly.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with
generated synthetic video, audio, still, image sequence, and non-media
fixtures. Final probe result: 56 supported, 1 expected unsupported non-media
text import, and 0 errors. The disposable project and generated media were
cleaned up after report generation.

## v2.7.0

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
[`docs/kernels/timeline-edit-kernel.md`](docs/kernels/timeline-edit-kernel.md), which records
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

## v2.6.0

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

## v2.5.0

Three new compound tools for *authoring and conversationally executing* Resolve extensions: Fusion Fuse plugins, DCTL color transforms, and Resolve-page Lua/Python scripts. Plus a documentation pass on six adjacent Resolve extension systems.

**New `fuse_plugin` tool**: generate, install, list, read, remove, and validate Fusion Fuse plugins (`.fuse`). **18 template kinds** spanning color (`color_matrix`, `per_pixel`, `channel_op`), geometric (`transform`, `spatial_warp`), text/shapes (`text_overlay`, `shape_generator`), source/temporal (`source_generator`, `time_displace`), filters (`builtin_blur`, `builtin_resize`, `variable_blur` SAT-based), modifiers (`modifier`, `point_modifier`), display shaders (`view_lut`, `dctl_kernel`), and reference (`controls_demo`, `notifychanged_demo`). Each generator produces ready-to-install Lua (or Lua + GLSL / Lua + DCTL) source that passes `luac -p` syntax checks across all option branches. **Live-verified in DaVinci Resolve Studio 20.3.2.9**: generated Fuses register on Resolve restart and instantiate via `comp:AddTool`; the `text_overlay` template was confirmed rendering glyphs into the viewer. The `view_lut` template supports `float`, `vec2`, `vec3_rgb`, and `vec4_rgba` shader parameter types. Includes a path-bug fix: corrected install path on macOS to `Fusion/Fuses/` (the SDK doc lists `Support/Fusion/Fuses/`, but Fusion's own `MapPath("Fuses:")` returns the path without `/Support/`).

**New `dctl` tool**: generate, install, list, read, remove, and validate DCTL color-transform files plus ACES IDT/ODT transforms. **8 template kinds** — `transform`, `transform_alpha` (Resolve 19.1+ alpha modes), `transition` (with `TRANSITION_PROGRESS`), `matrix` (3x3 color matrix), `kernel` (TODO stub), `lut_apply` (wraps an external `.cube` LUT via `DEFINE_LUT`/`APPLY_LUT`), `aces_idt`, `aces_odt`. UI-parameter syntax covers all six DCTL UI types (slider float/int, value box, checkbox, combo, color picker) with optional tooltips. Per-template `suggested_category` so callers know whether to install to the regular LUT directory or the separate ACES Transforms tree. Subdir support with strict path-traversal guards. Validator catches missing entry points, brace imbalance, and float literals missing the required `f` suffix. Regular DCTLs pick up via `project_settings(action='refresh_luts')`; ACES DCTLs require a Resolve restart.

**New `script_plugin` tool — conversational Lua/Python execution**: generate, install, and **execute** Resolve-page scripts that appear in the Workspace → Scripts menu. Two template kinds: `scaffold` (minimal stub) and `media_rules` (a comprehensive rules-and-variables DSL with sources, extract patterns, transforms, targets, actions, conditions, dry-run mode, external CSV/JSON data with exact/regex/fuzzy matching, and per-rule metadata — ~22k chars Lua engine and ~18k chars Python engine, both first-class). **Two new actions close the conversational loop**: `run_inline(source, language)` runs an ad-hoc Lua/Python snippet inside Resolve and streams stdout + return value back into the conversation; `execute(name, category, language)` runs an installed script the same way. Python uses subprocess with full stdout/stderr capture; Lua uses `fusion.RunScript()` against a temp file with completion-sentinel polling and `app:SetData()` bridge for return values (Resolve 20.x's `fusion.Execute()` is a no-op from the Python bridge — that quirk is encoded in the implementation). **Live-verified end-to-end** on Resolve Studio 20.3.2.9: Python `run_inline` returned project list and walked media pool; Lua `run_inline` enumerated `MapPath` symbols with stdout AND return value captured.

**`list_templates` action** on all three new tools enumerates available kinds.

**Resolve developer-package reference consolidation**: extension-system notes
were consolidated back into README/SKILL guidance, while dedicated authoring
docs remain in `docs/authoring/fuse-dctl-authoring.md` and
`docs/authoring/script-plugin-authoring.md`.

**Test coverage**: 185 offline tests across 7 modules (`test_fuse_dctl_authoring.py` and `test_script_plugin.py` both new in this release), all green in <2s. Includes hermetic round-trip tests with mocked install paths, DSL-coverage tests confirming every documented source/action/target/transform is in both Lua and Python engines, and Python subprocess execution tests with real captured stdout/stderr.

**Compound tool count: 27 → 30**. Granular tool count unchanged at 328.

## v2.4.1

Release process hardening — documenting the version bump, validation, tag, and GitHub Release checklist.

**Release checklist documented**: added `docs/process/release-process.md` with semantic version guidance, required version surfaces, validation requirements, tag/release commands, and release-note template.

**Live-test requirement clarified**: Resolve behavior changes must be validated live with disposable projects and synthetic media before release. Docs-only releases do not require a live Resolve run when no behavior changed.

## v2.4.0

Timeline source range extraction — adding a compound workflow helper for frame-pull and conform preparation.

**New `timeline.extract_source_frame_ranges` action**: `timeline(action="extract_source_frame_ranges")` scans every video clip on the current timeline and returns per-source frame ranges, clip occurrences, timeline positions, source offsets, applied handles, and timeline item IDs. Clip names prefer the basename from the Media Pool `File Path`, with audio extensions skipped by default.

**Handle-aware source ranges**: fixed handles default to 24 frames. Passing `handles=0` switches to gap-only auto handles, using neighboring timeline gaps up to `gap_max` frames. Returned `source_range_final` and `frame_ranges` endpoints are inclusive/inclusive for downstream extraction tools.

**Inclusive endpoint fix**: live validation caught and fixed the off-by-one where Resolve's exclusive source boundary was being returned as an inclusive final frame. A 48-frame synthetic clip with `handles=0` now returns `source_used_inclusive_end=47` and `source_range_final=[0, 47]`.

**Live Resolve validation**: verified against DaVinci Resolve Studio 20.3.2.9 in a disposable project with synthetic media. Added unit coverage in `tests/test_extract_source_frame_ranges.py` for zero-handle and fixed-handle ranges.

## v2.3.4

Marker API hardening for Issue #34 — making the compound marker tools match the parameter shapes agents and users naturally send.

**Marker parameter aliases fixed**: `timeline_markers`, `media_pool_item_markers`, and `timeline_item_markers` now accept `frame`, `frame_id`, and `frameId` consistently for add/get/update/delete operations. Marker lookup and delete paths also accept `customData` as an alias for `custom_data`.

**Timeline marker ergonomics improved**: `timeline_markers(action="add")` can now add at the current playhead when no frame/timecode is provided, and also accepts explicit `timecode` input. Optional marker fields now have sensible defaults (`color="Blue"`, `name` from note or `"Marker"`, `note=""`, `duration=1`).

**Resolve overload fallback**: marker creation first uses the documented six-argument `AddMarker(..., customData)` call, and falls back to the five-argument form when `customData` is empty and a Resolve build rejects the optional parameter.

**Live Resolve validation**: verified against DaVinci Resolve Studio 20.3.2.9 with `tests/live_marker_validation.py`. The harness creates a disposable project, imports synthetic media, inserts a visible timeline generator, and live-tests timeline, media-pool-item, and timeline-item marker add/get/update/delete alias paths. A `--keep-open` mode leaves a marked timeline open for visual inspection.

## v2.3.3

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

**New: API parity CI guard** at `scripts/audit_api_parity.py`. Parses `docs/reference/resolve_scripting_api.txt` and verifies (1) no `from api.X` broken imports remain, (2) every documented Resolve method appears somewhere in `src/`, (3) wrappers calling undocumented methods are flagged for review. Includes an allowlist for legitimate undocumented-but-real Resolve API surface (Fusion compositing API, UIManager methods like `OpenProjectSettings`/`LoadUILayout`/`SaveUILayout`, internal type-discrimination helpers like `TimelineItem.GetType`/`GetMediaType`). Run with `python3 scripts/audit_api_parity.py` — currently passes all three checks cleanly.

**Tool count: 328 granular tools** (was 354 before v2.3.2; net change since v2.3.1 is −26 broken/duplicate/undocumented tools removed and +4 missing tools added). 20 new unit tests against Resolve stubs covering the cloud settings builder, audio sync settings builder, and AppendToTimeline clipInfo builder. All 41 tests pass without a live Resolve connection.

**Live disposable Resolve validation**: every new and changed v2.3.3 granular tool was exercised against DaVinci Resolve Studio 20.3.2.9 in a disposable project with synthetic temp media via `tests/live_v233_validation.py`. 10/10 checks passed: `append_to_timeline` (simple + positioned + failure path), `auto_sync_audio` (settings dict + invalid input rejection), `import_media` image-sequence form, `timeline_create_compound_clip` (info dict forwarded — compound clip created with explicit name), `rename_color_group` (renamed a real color group), `render_with_quick_export` (params dict forwarded — Resolve's structured `{JobStatus, Error}` response confirms the dict reached it), and the compound-side `GetItemListInTrack` deprecated→supported fix.

## v2.3.2

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

## v2.3.1

- **Positioned `AppendToTimeline` via `clip_infos`** — `media_pool(action="append_to_timeline", params={"clip_infos": [...]})` now exposes the documented `MediaPool.AppendToTimeline([{clipInfo}, ...])` overload, accepting per-entry `clip_id`/`media_pool_item_id`, `start_frame`, `end_frame`, `record_frame`, `track_index`, and optional `media_type`. Each appended item returns its `timeline_item_id` for follow-up Fusion ops
- **Positioned append failure reporting** — the same call now returns `{"error": ...}` when Resolve fails to produce valid timeline items, including falsey `AppendToTimeline()` results and returned item handles without a timeline item id
- **Live disposable Resolve validation** — verified the fix against DaVinci Resolve Studio 20.3.2 with synthetic temp media in a disposable project: valid `clip_infos` append returned `success`, `count=1`, and `timeline_item_id`; invalid `clip_infos` calls returned errors

## v2.3.0

- **Resolve 20.2.2 API sync** — added the 12 scripting methods introduced across Resolve 20.0-20.2.2, with compatibility guards so older Resolve builds return clear "requires Resolve 20.x" errors instead of crashing
- **Resolve 20 live validation** — revalidated the new API surface against DaVinci Resolve Studio 20.3.2, bringing live-tested coverage to 331/336 methods (98.5%)
- **Official scripting docs refreshed** — `docs/reference/resolve_scripting_api.txt` now tracks the Resolve 20 scripting README bundled with the installed 20.3.2 developer package
- **AI skill reference updated** — merged PR #30's `docs/SKILL.md` and updated it for the Resolve 20 method count, granular server, version guards, and source media integrity guidance
- **Stale Resolve handle recovery** — both server modes now validate cached Resolve handles and reconnect cleanly after Resolve restarts or Project Manager transitions

## v2.2.0

- **Granular server modularized internally** — `src/resolve_mcp_server.py` is now a thin entrypoint, with the granular implementation split across `src/granular/resolve_control.py`, `project.py`, `timeline.py`, `timeline_item.py`, `media_pool.py`, `folder.py`, `media_pool_item.py`, `gallery.py`, `graph.py`, and `media_storage.py`
- **Installer now emits env blocks for every generated stdio config** — standard `.mcp.json`, VS Code `.vscode/mcp.json`, Zed `context_servers`, and manual snippets now include `RESOLVE_SCRIPT_API`, `RESOLVE_SCRIPT_LIB`, and `PYTHONPATH`
- **Windows Resolve 20.3 hardening** — on Windows, the installer also emits `PYTHONHOME` derived from the selected interpreter's base install so Resolve binds against the intended Python instead of a newer globally registered one
- **Windows stdio transport hardening** — server entrypoints now run FastMCP through strict LF-only stdio wrappers to avoid client disconnects caused by platform newline translation in Windows pipes
- **`set_cdl` accepts arrays cleanly** — both compound and granular servers now normalize JSON array, tuple, and numeric CDL values into Resolve's required string form like `"1.0 1.0 1.0"`
- **`fusion_comp` can target timeline item comps** — node graph actions can now operate on a clip's Fusion comp via `clip_id`, `timeline_item_id`, or `timeline_item`, and `bulk_set_inputs` applies scoped input changes across multiple timeline comps
- **`python src/server.py --full` now stays intact** — the compound entrypoint now correctly launches the granular server instead of importing it and exiting

## v2.1.0

- **New `fusion_comp` tool** — 20-action tool exposing the full Fusion composition node graph API. Add/delete/find nodes, wire connections, set/get parameters, manage keyframes, control undo grouping, set render ranges, and trigger renders — all on the currently active Fusion page composition
- **`timeline_item_fusion` cache actions** — added `get_cache_enabled` and `set_cache` actions for Fusion output cache control directly on timeline items
- **Fusion node graph reference** — docstring includes common tool IDs (Merge, TextPlus, Background, Transform, ColorCorrector, DeltaKeyer, etc.) for discoverability

## v2.0.9

- **Cross-platform sandbox path redirect** — `_resolve_safe_dir()` now handles macOS (`/var/folders`, `/private/var`), Linux (`/tmp`, `/var/tmp`), and Windows (`AppData\Local\Temp`) sandbox paths that Resolve can't write to. Redirects to `~/Documents/resolve-stills` instead of Desktop
- **Auto-cleanup for `grab_and_export`** — exported files are read into the response (DRX as inline text, images as base64) then deleted from disk automatically. Zero file accumulation. Pass `cleanup: false` to keep files on disk
- **Both servers in sync** — `server.py` and `resolve_mcp_server.py` now share the same version and both use `_resolve_safe_dir()` for all Resolve-facing temp paths (project export, LUT export, still export)

## v2.0.8

- **New `grab_and_export` action on `gallery_stills`** — combines `GrabStill()` + `ExportStills()` in a single atomic call, keeping the live GalleryStill reference for reliable export. Returns a file manifest with exported image + companion `.drx` grade file
- **Format fallback chain** — if the requested format fails, automatically retries with tif then dpx
- **macOS sandbox path redirect** — `/var/folders` and `/private/var` paths are redirected to `~/Desktop/resolve-stills` since Resolve's process can't write to sandboxed temp directories
- **Key finding documented** — `ExportStills` requires the Gallery panel to be visible on the Color page. All 9 supported formats (dpx, cin, tif, jpg, png, ppm, bmp, xpm, drx) produce a companion `.drx` grade file alongside the image

## v2.0.7

- **Security: path traversal protection for layout preset tools** — `export_layout_preset`, `import_layout_preset`, and `delete_layout_preset` now validate that resolved file paths stay within the expected Resolve presets directory, preventing path traversal via crafted preset names
- **Security: document destructive tool risk** — added Security Considerations section noting that `quit_app`/`restart_app` tools can terminate Resolve; MCP clients should require user confirmation before invoking

## v2.0.6

- **Fix color group operations crash** — `timeline_item_color` unpacked `_check()` as `(proj, _, _)` but `_check()` returns `(pm, proj, err)`, so `proj` got the ProjectManager instead of the Project, crashing `assign_color_group` and `remove_from_color_group`

## v2.0.5

- **Lazy connection recovery** — full server (`--full` mode) now auto-reconnects and auto-launches Resolve, matching the compound server behavior
- **Null guards on all chained API calls** — `GetProjectManager()`, `GetCurrentProject()`, `GetCurrentTimeline()` failures now return clear errors instead of `NoneType` crashes
- **Helper functions** — `get_resolve()`, `get_project_manager()`, `get_current_project()` replace 178 boilerplate blocks

## v2.0.4

- **Fix apply_grade_from_drx parameter** — renamed `mode` to `grade_mode` to match Resolve API; corrected documentation from replace/append to actual keyframe alignment modes (0=No keyframes, 1=Source Timecode aligned, 2=Start Frames aligned)
- **Backward compatible** — still accepts `mode` for existing clients, `grade_mode` takes precedence

## v2.0.3

- **Fix GetNodeGraph crash** — `GetNodeGraph(0)` returns `False` in Resolve; now calls without args unless `layer_index` is explicitly provided
- **Falsy node graph check** — guard checks `not g` instead of `g is None` to catch `False` returns

## v2.0.2

- **Antigravity support** — Google's agentic AI coding assistant added as 10th MCP client
- **Alphabetical client ordering** — MCP_CLIENTS list sorted for easier maintenance

## v2.0.1

- **26-tool compound server** — all 324 API methods grouped into 26 context-efficient tools (default)
- **Universal installer** — single `python install.py` for macOS/Windows/Linux, 10 MCP clients
- **Dedicated timeline_item actions** — retime/speed, transform, crop, composite, audio, keyframes with validation
- **Lazy Resolve connection** — server starts instantly, connects when first tool is called
- **Bug fixes** — CreateMagicMask param type, GetCurrentClipThumbnailImage args, Python 3.13+ warning
