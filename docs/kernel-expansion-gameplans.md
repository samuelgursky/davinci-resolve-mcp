# Kernel Expansion Gameplans

This document is the expansion map for applying the timeline edit kernel
pattern to the rest of the DaVinci Resolve MCP surface.

The pattern is:

1. Identify the public Resolve API surface and the existing MCP wrappers.
2. Add a higher-level kernel where the raw API is too low-level for agents.
3. Build an exhaustive live probe with disposable projects and synthetic media.
4. Classify every probed surface as `supported`, `partially_supported`,
   `version_or_page_dependent`, `unsupported`, `not_applicable`, `read_only`,
   `write_only_unverifiable`, or `error`.
5. Add offline tests for parsers, result handling, validation, and report
   rendering.
6. Document the support map and public API limits.
7. Run the release checklist and ship one coherent kernel wave.

Source media integrity stays non-negotiable for every plan below. Live probes
must use generated synthetic media, disposable projects, and local temp
directories. They must not transcode, proxy, overwrite, or create derivatives
of user source media.

## Execution Order

Recommended release-sized waves:

| Order | Kernel | Why This Order |
| ---: | --- | --- |
| 1 | Media Pool / Ingest | Foundation for import, relink, metadata, conform, and analysis workflows. |
| 2 | Render / Deliver | High practical value and a bounded API surface with rich compatibility probing. |
| 3 | Markers / Review Annotation | Low risk, strong workflow payoff, and already partially live-validated. |
| 4 | Color / Grade | Large creative surface; best after media/timeline foundations are stable. |
| 5 | Fusion Composition | Deep graph behavior with many version/page quirks; needs focused probing. |
| 6 | Timeline Conform / Interchange | Builds on ingest, timeline, and media metadata kernels. |
| 7 | Audio / Fairlight | Mixed API support and page-dependent behavior; better after marker/media probes. |
| 8 | Project / Database / Archive | Operationally important, but touches user project libraries; must be extra careful. |
| 9 | Extension Authoring | Existing v2.5.0 tools are strong; expansion is mostly lifecycle/probe hardening. |

Each wave should be independently releasable. Do not bundle multiple kernels
into one release unless their live harnesses and docs are already complete.

## Shared Harness Shape

Each kernel should add these files or equivalents:

- `src/utils/<kernel>_probe.py` for report helpers, parsers, and reusable
  status classification.
- `src/utils/<kernel>_live_probe.py` for live Resolve probing.
- `tests/test_<kernel>_probe.py` for offline report/helper tests.
- One focused live validation script under `tests/live_<kernel>_validation.py`
  when behavior changes.
- `docs/<kernel>.md` for the supported/partial/unsupported boundary map.

Probe reports should include:

- Resolve product/version/platform/Python metadata.
- Disposable project name.
- Synthetic media paths, when media is generated.
- Per-surface records with `category`, `name`, `status`, `details`, and
  optional `evidence`.
- Counts by status.
- Markdown summary and JSON detail output.

Release validation should include:

```bash
venv/bin/python tests/test_import.py
venv/bin/python scripts/audit_api_parity.py
git diff --check
venv/bin/python -m unittest <focused offline suite>
python3.11 tests/live_<kernel>_validation.py
python3.11 tests/live_<kernel>_validation.py --output-dir /tmp/<kernel>-probe
```

## 1. Media Pool / Ingest Kernel

### Existing Surface

Compound tools involved:

- `media_storage`
- `media_pool`
- `folder`
- `media_pool_item`
- `media_pool_item_markers`

Relevant current actions include storage browsing, import to pool, folder
CRUD/move/delete, timeline creation from clips, append to timeline, relink,
unlink, metadata, third-party metadata, clip properties, clip color, proxy and
full-resolution media linking, audio transcription, audio mapping, clip mattes,
timeline mattes, mark in/out, markers, and flags.

### Kernel Goal

Create a safe ingest and organization layer that can answer:

- What can Resolve import?
- What metadata can be read, written, restored, and trusted?
- Which clip properties are writable by media type?
- What can be relinked/unlinked without damaging source integrity?
- Which operations create new Media Pool objects versus mutating existing ones?
- Which operations require real file paths, folders, image sequences, or
  specific media types?

### Candidate Kernel Actions

- `ingest_capabilities`
- `probe_ingest_item`
- `probe_media_pool`
- `safe_import_media`
- `safe_import_sequence`
- `safe_import_folder`
- `organize_clips`
- `copy_metadata`
- `normalize_metadata`
- `probe_clip_properties`
- `safe_relink`
- `safe_unlink`
- `link_proxy_checked`
- `link_full_resolution_checked`
- `set_clip_marks`
- `clear_clip_marks`
- `copy_clip_annotations`
- `media_pool_boundary_report`

### Live Probe Plan

Create a disposable project and generate:

- A short video with audio.
- A still image.
- A numbered image sequence.
- A short audio-only file.
- A non-media text file for negative import boundaries.

Probe:

- `media_storage.get_volumes`, `get_subfolders`, `get_files`.
- `media_storage.import_to_pool` simple paths and itemInfo ranges.
- `media_pool.import_media` simple paths and sequence clipInfos.
- `media_pool.import_folder` when a folder contains supported and unsupported
  files.
- Folder creation, current-folder switching, subfolder listing, folder export,
  folder stale state.
- Media Pool selection APIs.
- Clip metadata read/write/restore for scalar and dict forms.
- Third-party metadata read/write/restore.
- Clip property full snapshots and candidate write keys by media type.
- Clip color set/clear.
- Mark in/out set/clear for media pool items.
- Marker/flag add/read/update/delete on media pool items.
- Relink/unlink against copied synthetic media paths only.
- Proxy/full-resolution link/unlink using generated disposable media only.
- Clip matte and timeline matte import/delete with generated matte images.
- Audio transcription and clear transcription only if Resolve returns quickly
  and the operation is available; otherwise classify as page/build dependent.
- Audio mapping readback for generated audio/video clips.

### Expected Boundaries

- Relink and replace operations are powerful and must be guarded to synthetic
  media in live tests.
- Proxy/full-resolution linking may persist paths but may not validate media
  compatibility deeply.
- Some metadata keys are read-only, silently ignored, or localized by Resolve.
- Image sequence import depends on project/media storage settings.
- Transcription may require Studio features, page state, or installed language
  components.

### Offline Tests

- Clip property diff/restore helper tests.
- Import result serialization for thin Resolve objects.
- Metadata normalization and round-trip comparison.
- Sequence file discovery and range validation.
- Source-media-integrity guard tests preventing writes outside temp fixtures.

### Docs

Add `docs/media-pool-ingest-kernel.md` with:

- Supported import forms.
- Metadata write/read support.
- Relink/proxy/full-resolution safety rules.
- Media Pool mutation matrix.
- Live probe result table.

### Execution Status

Implemented in v2.8.0. Final live probe on DaVinci Resolve Studio 20.3.2.9
classified 56 surfaces as `supported`, one expected non-media text import as
`unsupported`, and zero surfaces as `error`. See
`docs/media-pool-ingest-kernel.md`.

## 2. Render / Deliver Kernel

### Existing Surface

Compound tools involved:

- `render`
- `render_presets`
- `project_settings`
- `timeline`

Relevant current actions include render jobs, job status, render start/stop,
formats, codecs, current format/codec, render mode, resolutions, settings,
presets, quick export presets, quick export, render preset import/export, and
burn-in preset import/export.

### Kernel Goal

Create a render compatibility and job-safety layer that can answer:

- Which format/codec pairs are available on this machine?
- Which format/codec pairs accept which resolutions?
- Which render settings persist, coerce, or fail?
- Which quick export presets are available and what parameters are honored?
- Which render job lifecycle actions are safe and observable?

### Candidate Kernel Actions

- `render_capabilities`
- `probe_render_matrix`
- `probe_render_settings`
- `validate_render_settings`
- `safe_set_render_settings`
- `prepare_render_job`
- `render_job_lifecycle_probe`
- `quick_export_capabilities`
- `safe_quick_export`
- `export_render_boundary_report`

### Live Probe Plan

Create a disposable project and synthetic timeline, then probe:

- Render format list.
- Codec list for every format.
- Resolution list for every available format/codec pair.
- Current format/codec read/restore.
- Render mode read/write/restore.
- Render settings full snapshot.
- Candidate render setting writes with restore after each write.
- Load/list/save/delete temporary render preset.
- Add/delete render job.
- Add job then inspect status before rendering.
- Start/stop rendering only for a tiny synthetic timeline and a temp output
  directory.
- Quick export preset list.
- Quick export with `TargetDir`, `CustomName`, `VideoQuality`, and
  `EnableUpload=False`, using synthetic media only.
- Import/export render preset and burn-in preset only with generated temp
  preset files when possible; otherwise classify as unsupported or manual-only.

### Expected Boundaries

- Format/codec availability is platform, install, and license dependent.
- Some render settings are accepted but coerced.
- Some settings require the Deliver page or a current timeline.
- Quick Export may start rendering immediately and can be harder to isolate
  than render jobs.
- Upload-enabled quick export must be disabled in automated probes.

### Offline Tests

- Render matrix report rendering.
- Settings diff/restore classification.
- Render job result serialization.
- Format/codec/resolution normalization.
- Guard tests requiring temp output paths.

### Docs

Add `docs/render-deliver-kernel.md` with:

- Format/codec/resolution compatibility table.
- Settings support and coercion notes.
- Safe render job lifecycle.
- Quick Export boundaries.

## 3. Markers / Review Annotation Kernel

### Existing Surface

Compound tools involved:

- `timeline_markers`
- `timeline_item_markers`
- `media_pool_item_markers`
- `media_pool_item`
- `timeline_item`

Relevant current actions include marker add/get/update/delete, custom data
lookup, flag add/get/clear, clip color set/clear, and current-playhead marker
creation.

### Kernel Goal

Create a unified annotation layer across timeline, timeline item, and media
pool item scopes.

It should answer:

- Which marker fields persist at each scope?
- Which colors are accepted?
- Which frame/timecode aliases are accepted?
- How reliable is `custom_data` round-trip by scope?
- Can annotations be copied between scopes?
- Can a review report be exported without mutating media?

### Candidate Kernel Actions

- `annotation_capabilities`
- `probe_annotations`
- `normalize_marker_payload`
- `copy_annotations`
- `move_annotations`
- `sync_marker_custom_data`
- `clear_annotations_by_scope`
- `export_review_report`
- `annotation_boundary_report`

### Live Probe Plan

Create a disposable project with synthetic video and timeline, then probe:

- Timeline markers by frame, frame_id, frameId, and timecode.
- Timeline marker add at current playhead.
- Timeline marker custom data read/update/delete.
- Timeline item markers at video and audio item scopes.
- Media pool item markers.
- Marker durations, notes, names, and colors.
- All documented marker colors plus invalid color boundaries.
- Flags at media pool and timeline item scopes.
- Clip color set/clear at media pool and timeline item scopes.
- Copy marker payloads between media pool item, timeline item, and timeline
  scopes where frame coordinates can be mapped.

### Expected Boundaries

- Timeline marker frame IDs are timeline-frame based; media pool item markers
  are source-frame based.
- Current-playhead marker insertion depends on a current timeline and page
  state.
- Custom data behavior has Resolve overload quirks; fallback paths are needed.
- Clip color and flags are not the same data model as markers.

### Offline Tests

- Marker payload normalization.
- Frame/timecode mapping helpers.
- Custom-data alias handling.
- Review report JSON/Markdown rendering.
- Invalid color classification.

### Docs

Add `docs/review-annotation-kernel.md` with:

- Scope matrix.
- Marker field persistence table.
- Custom-data guidance.
- Review report format.

## 4. Color / Grade Kernel

### Existing Surface

Compound tools involved:

- `timeline_item_color`
- `graph`
- `gallery`
- `gallery_stills`
- `color_group`
- `project_settings`

Relevant current actions include CDL, grade copy, grade versions, node graph
access, color groups, LUT export/apply, cache, stabilization, smart reframe,
magic mask, gallery albums, still import/export, DRX apply, ARRI CDL LUT
application, node LUT/cache/label/tools/enabled state, and reset grades.

### Kernel Goal

Create a safe grade inspection, copy, versioning, and boundary layer that can
answer:

- What grade state can be inspected?
- What grade state can be copied or applied?
- What is node-level versus clip-level versus group-level?
- What can be exported as LUT/DRX/still?
- Which AI color tools are callable and observable?

### Candidate Kernel Actions

- `grade_capabilities`
- `probe_grade_item`
- `probe_node_graph`
- `safe_copy_grade`
- `safe_apply_drx`
- `safe_export_lut`
- `grade_version_snapshot`
- `grade_version_restore`
- `color_group_capabilities`
- `gallery_capabilities`
- `grade_boundary_report`

### Live Probe Plan

Create a disposable project with synthetic color bars or test source, then
probe:

- Clip node count before/after basic operations.
- CDL set and readback through available APIs.
- DRX apply from a generated safe grade fixture.
- Grade copy from one synthetic timeline item to another.
- Local and remote version add/list/load/rename/delete.
- Clip color group create/assign/remove/delete.
- Pre-clip and post-clip group graph availability.
- Graph node label, LUT, cache mode, tools-in-node, enabled state.
- Timeline-level graph availability.
- Gallery album create/rename/current selection.
- Grab still, export still, label still, delete still.
- LUT export formats to temp paths.
- Stabilize/smart reframe/magic mask calls as availability probes only, with
  clear classification when analysis is asynchronous or not observable.

### Expected Boundaries

- Node graph internals are intentionally limited by Resolve's public API.
- DRX application replaces the full node graph; there is no append mode.
- Magic Mask and analysis operations can be asynchronous and page-dependent.
- Gallery still labels may not persist in every Resolve build.
- LUT export availability depends on current clip/page and destination path.

### Offline Tests

- Grade capability report rendering.
- Node graph source normalization.
- DRX path safety validation.
- Version lifecycle result normalization.
- Gallery still export metadata parsing.

### Docs

Add `docs/color-grade-kernel.md` with:

- Clip/group/timeline graph matrix.
- DRX/LUT/still workflow boundaries.
- Version workflow support map.
- AI color tool classification.

## 5. Fusion Composition Kernel

### Existing Surface

Compound tools involved:

- `fusion_comp`
- `timeline_item_fusion`
- `timeline`
- `script_plugin`
- `fuse_plugin`

Relevant current actions include add/delete/find tools, connect/disconnect,
input/output inspection, input setting, attrs, keyframes, comp import/export,
render, frame range, Fusion comp add/export/import/delete/load/rename/cache,
and Fuse authoring.

### Kernel Goal

Create a Fusion graph kernel that can answer:

- Which Fusion tools are available in the current Resolve build?
- Which inputs and outputs are visible and writable?
- Which tool attrs persist?
- Which comp import/export paths are reliable?
- Which graph operations require Fusion page focus?

### Candidate Kernel Actions

- `fusion_graph_capabilities`
- `probe_fusion_tool`
- `probe_fusion_comp`
- `safe_add_tool`
- `safe_connect_tools`
- `safe_set_inputs`
- `safe_keyframe_inputs`
- `safe_import_comp`
- `safe_export_comp`
- `fusion_boundary_report`

### Live Probe Plan

Create a disposable project with a synthetic timeline item and Fusion comp,
then probe:

- Timeline item comp add/list/load/rename/export/import/delete.
- Fusion page current comp behavior.
- Add common tools: `Background`, `TextPlus`, `Merge`, `Transform`, `Blur`,
  `ColorCorrector`, `RectangleMask`, `EllipseMask`, `MediaIn`, `MediaOut`.
- Tool input/output listing.
- Safe input writes and restore for scalar/color/text inputs.
- Tool attrs read/write where safe.
- Connections and disconnections.
- Keyframe add/read/delete for safe inputs.
- Comp frame range and render behavior.
- Bulk set inputs result handling.
- Import/export `.comp` fixtures to temp paths.

### Expected Boundaries

- Fusion API behavior can differ between page current comp and timeline item
  comp contexts.
- Tool availability depends on Resolve/Fusion build.
- Some inputs are write-only or accept values without reliable readback.
- Rendering a Fusion comp may require valid MediaOut and page state.

### Offline Tests

- Fusion target normalization.
- Tool IO serialization.
- Input value comparison and readback classification.
- `.comp` import/export path guards.
- Bulk operation report tests.

### Docs

Add `docs/fusion-composition-kernel.md` with:

- Tool availability matrix.
- Input/output write/read support map.
- Page-state boundaries.
- Import/export lifecycle.

## 6. Timeline Conform / Interchange Kernel

### Existing Surface

Compound tools involved:

- `timeline`
- `media_pool`
- `media_pool_item`
- `project_settings`

Relevant current actions include timeline import/export, source frame range
extraction, import timeline, create timeline from clips, append to timeline,
relink/unlink, metadata, mark in/out, and current timeline settings.

### Kernel Goal

Create a conform and interchange layer that can answer:

- Which timeline interchange formats import/export successfully?
- What survives an export/import round trip?
- How do source frame ranges map to media pool items?
- Can the MCP detect gaps, overlaps, missing media, and relink risk?

### Candidate Kernel Actions

- `conform_capabilities`
- `probe_interchange_roundtrip`
- `export_timeline_checked`
- `import_timeline_checked`
- `compare_timelines`
- `detect_gaps_overlaps`
- `detect_missing_media`
- `build_relink_plan`
- `source_range_report`
- `conform_boundary_report`

### Live Probe Plan

Create a disposable project with multiple synthetic clips and timelines, then
probe:

- Timeline export formats: FCPXML, EDL, DRT, and AAF where available.
- Timeline import of exported artifacts into a new disposable project/timeline.
- Round-trip timeline item count, names, start/end, source start/end, track
  placement, markers, and basic clip properties.
- Source range extraction with fixed handles and gap-only handles.
- Gap and overlap detection across video/audio tracks.
- Missing-media detection after unlinking synthetic media only.
- Relink planning and relink execution against copied synthetic media only.

### Expected Boundaries

- AAF/FCPXML/EDL support varies by Resolve version and timeline contents.
- Round trips may lose effects, transitions, generators, Fusion comps, grades,
  or markers.
- Relink operations are safe only against generated or explicitly approved
  paths.
- Some interchange exports require a current timeline and specific page state.

### Offline Tests

- Timeline comparison diff model.
- Gap/overlap detector.
- Source range report helpers.
- Interchange result classification.
- Relink plan safety checks.

### Docs

Add `docs/timeline-conform-interchange-kernel.md` with:

- Format support matrix.
- Round-trip survival table.
- Relink safety rules.
- Conform risk report schema.

## 7. Audio / Fairlight Kernel

### Existing Surface

Compound tools involved:

- `timeline`
- `timeline_item`
- `media_pool`
- `media_pool_item`
- `folder`
- `timeline_ai`
- `project_settings`
- `resolve_control`

Relevant current actions include track voice isolation, item voice isolation,
audio property get/set, source audio mapping, media pool audio mapping,
auto-sync audio, transcription, subtitles, Fairlight presets, audio insert,
track enable/lock/name, and page control.

### Kernel Goal

Create an audio state and analysis boundary layer that can answer:

- Which audio properties are readable/writable on clip items?
- Which voice isolation APIs work at track versus item scope?
- What audio channel mapping can be read or changed?
- Which transcription/subtitle operations are available and observable?
- Which Fairlight presets can be listed/applied?

### Candidate Kernel Actions

- `audio_capabilities`
- `probe_audio_item`
- `probe_audio_track`
- `safe_set_audio_properties`
- `voice_isolation_capabilities`
- `audio_mapping_report`
- `safe_auto_sync_audio`
- `transcription_capabilities`
- `subtitle_generation_probe`
- `fairlight_boundary_report`

### Live Probe Plan

Create disposable synthetic audio/video clips, then probe:

- Timeline audio track count/add/delete/name/lock/enable.
- Clip audio property snapshot and candidate writes/restores.
- Timeline item source audio mapping readback.
- Media pool item audio mapping readback.
- Track-level voice isolation get/set/restore.
- Item-level voice isolation get/set/restore.
- Auto-sync audio on generated video/audio pair.
- Media pool item transcription and clear transcription.
- Folder transcription and clear transcription.
- Timeline subtitle creation from generated audio only.
- Fairlight preset list and apply only against a disposable project.
- Project audio insert with generated audio only.

### Expected Boundaries

- Voice isolation is version/license/page dependent.
- Transcription and subtitle creation may require AI components and can be
  asynchronous.
- Auto-sync audio depends on generated media content and channel layout.
- Audio property writes often return false or are item-type dependent.

### Offline Tests

- Voice isolation state normalization.
- Audio property copy/restore classification.
- Audio mapping parser.
- Auto-sync settings builder.
- Transcription/subtitle result report tests.

### Docs

Add `docs/audio-fairlight-kernel.md` with:

- Track/item audio state matrix.
- Voice isolation support map.
- Transcription/subtitle boundaries.
- Auto-sync requirements.

## 8. Project / Database / Archive Kernel

### Existing Surface

Compound tools involved:

- `project_manager`
- `project_manager_folders`
- `project_manager_database`
- `project_manager_cloud`
- `project_settings`
- `layout_presets`
- `render_presets`
- `resolve_control`

Relevant current actions include project CRUD/load/save/close/delete,
import/export/archive/restore, project folders, database list/switch, cloud
project operations, settings, presets, gallery access, burn-in presets, layout
presets, render preset import/export, and app-level page/version/keyframe mode.

### Kernel Goal

Create an operational safety layer for project lifecycle automation.

It should answer:

- Which project operations are safe and reversible in disposable contexts?
- Which settings can be read/written/restored?
- Which presets can be imported/exported/listed reliably?
- What happens to current project state during database or folder changes?
- Which operations are cloud-only or require external infrastructure?

### Candidate Kernel Actions

- `project_capabilities`
- `probe_project_lifecycle`
- `probe_project_settings`
- `safe_project_create`
- `safe_project_archive`
- `safe_project_restore`
- `project_settings_snapshot`
- `project_settings_restore`
- `database_capabilities`
- `preset_lifecycle_probe`
- `project_boundary_report`

### Live Probe Plan

Use disposable project names with `_mcp_` prefixes only, then probe:

- Project create/save/load/close/delete.
- Project export/import to temp DRP path.
- Archive/restore with `src_media=False`, `render_cache=False`,
  `proxy_media=False`.
- Project folder create/open/goto/delete.
- Current database list/get; do not switch databases unless explicitly allowed.
- Project settings full snapshot and candidate setting write/restore.
- Preset list/set for project presets.
- Layout preset save/load/update/export/import/delete with temp names.
- Render preset import/export and burn-in preset import/export with temp files.
- Keyframe mode get/set/restore.
- Page open/get across all pages.
- Cloud project actions as shape/guard probes unless cloud infrastructure is
  available; never create cloud projects during default live validation.

### Expected Boundaries

- Database switching closes projects and can disrupt user state.
- Archive/restore can touch large media unless media/cache/proxy flags are
  forced false in probes.
- Cloud actions require account/project-library infrastructure.
- Some project settings are accepted as strings only, coerce values, or require
  timeline/project restart to observe.

### Offline Tests

- Disposable project name guards.
- Settings snapshot/diff/restore helpers.
- Archive option safety validation.
- Database-operation dry-run guards.
- Preset import/export result normalization.

### Docs

Add `docs/project-lifecycle-kernel.md` with:

- Project lifecycle matrix.
- Database/cloud safety rules.
- Settings persistence map.
- Preset lifecycle support.

## 9. Extension Authoring Kernel

### Existing Surface

Compound tools involved:

- `fuse_plugin`
- `dctl`
- `script_plugin`
- `project_settings`
- `resolve_control`

Relevant current actions include path/list/install/remove/read/validate/template
for Fuses and DCTLs, ACES transform installs, script plugin category handling,
inline script execution, installed script execution, and LUT refresh.

### Kernel Goal

Turn the existing authoring tools into a lifecycle-aware extension kernel that
can answer:

- What installs live versus requiring a Resolve restart?
- Which generated templates register and instantiate?
- Which DCTLs appear in LUT/DCTL contexts after refresh?
- Which script categories appear on which pages?
- Which execution modes capture stdout/stderr/return values reliably?

### Candidate Kernel Actions

- `extension_capabilities`
- `probe_fuse_lifecycle`
- `probe_dctl_lifecycle`
- `probe_script_lifecycle`
- `safe_install_extension`
- `safe_remove_extension`
- `refresh_or_restart_required`
- `extension_boundary_report`

### Live Probe Plan

Use only MCP-marked generated files in temp or Resolve user plugin paths, then
probe:

- Fuse path/list/install/read/validate/remove for a generated harmless Fuse.
- Existing Fuse edit/read/remove behavior.
- DCTL path/list/install/read/validate/remove for regular LUT-category DCTLs.
- `project_settings.refresh_luts` visibility after install.
- ACES IDT/ODT install path behavior and classify restart-required without
  forcing a restart by default.
- Script categories, install/read/list/remove for Lua and Python.
- `script_plugin.run_inline` Python stdout/stderr/result capture.
- `script_plugin.run_inline` Lua stdout/result capture.
- Installed script `execute` for Python and Lua.
- Template generation/validation for every template kind.

### Expected Boundaries

- New Fuses require Resolve restart to register.
- ACES DCTLs require Resolve restart and are not picked up by LUT refresh.
- Lua execution return capture depends on Resolve/Fusion bridge behavior.
- Installing generated files writes into Resolve plugin/script directories and
  must be strictly MCP-marked for cleanup.

### Offline Tests

- Template coverage for every Fuse, DCTL, and script kind.
- Path traversal guards.
- MCP marker enforcement for remove/list.
- Restart/refresh classification helpers.
- Inline execution result parser tests.

### Docs

Add or expand:

- `docs/fuse-dctl-authoring.md`
- `docs/script-plugin-authoring.md`
- `docs/extension-authoring-kernel.md`

Include lifecycle tables for refresh-required, restart-required, live-editable,
and removable surfaces.

## Cross-Kernel Tracking

Each kernel should maintain a checklist in its boundary doc:

- Gameplan complete.
- Offline helpers implemented.
- Live harness implemented.
- Live validation passed with synthetic media.
- Probe report has zero `error` records or documented expected errors.
- Supported/partial/unsupported/version-dependent map documented.
- README and `docs/SKILL.md` updated.
- Release checklist completed.

Do not mark a kernel complete until every checklist item is backed by command
output or live probe evidence.
