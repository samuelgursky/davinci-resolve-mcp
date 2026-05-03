# DaVinci Resolve MCP Server

[![Version](https://img.shields.io/badge/version-2.3.3-blue.svg)](https://github.com/samuelgursky/davinci-resolve-mcp/releases)
[![API Coverage](https://img.shields.io/badge/API%20Coverage-100%25-brightgreen.svg)](#api-coverage)
[![Tools](https://img.shields.io/badge/MCP%20Tools-27%20(337%20full)-blue.svg)](#server-modes)
[![Tested](https://img.shields.io/badge/Live%20Tested-98.5%25-green.svg)](#test-results)
[![DaVinci Resolve](https://img.shields.io/badge/DaVinci%20Resolve-18.5+-darkred.svg)](https://www.blackmagicdesign.com/products/davinciresolve)
[![Python](https://img.shields.io/badge/python-3.10--3.12-green.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://opensource.org/licenses/MIT)

A Model Context Protocol (MCP) server providing **complete coverage** of the DaVinci Resolve Scripting API. Connect AI assistants (Claude, Cursor, Windsurf) to DaVinci Resolve and control every aspect of your post-production workflow through natural language.

### What's New in v2.3.3

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

**Removed 4 undocumented cloud method wrappers** (same v2.3.2 cleanup pattern):
- `get_cloud_projects` resource → `GetCloudProjectList` not in API docs
- `export_project_to_cloud_tool` → `ExportToCloud`/`ExportProjectToCloud` not in API docs
- `add_user_to_cloud_project_tool` → `AddUserToCloudProject` not in API docs
- `remove_user_from_cloud_project_tool` → `RemoveUserFromCloudProject` not in API docs

**Deprecated method call fixed**: `timeline(action="get_items_in_track")` was calling the deprecated `tl.GetItemsInTrack()` form (docs line 989, marked deprecated) instead of the supported `tl.GetItemListInTrack()` (line 350). Every other call site already used the correct form.

**New: API parity CI guard** at `scripts/audit_api_parity.py`. Parses `docs/resolve_scripting_api.txt` and verifies (1) no `from api.X` broken imports remain, (2) every documented Resolve method appears somewhere in `src/`, (3) wrappers calling undocumented methods are flagged for review. Run with `python3 scripts/audit_api_parity.py`. Designed to catch the v2.3.2 broken-import and v2.3.2/v2.3.3 undocumented-wrapper bug classes in CI.

**Tool count: 337 granular tools** (337 = 336 + 4 added − 3 tools removed; 1 resource also removed). 20 new unit tests against Resolve stubs covering the cloud settings builder, audio sync settings builder, and AppendToTimeline clipInfo builder. All 41 tests pass without a live Resolve connection.

**Tracking for follow-up (v2.3.4)**: parity-check advisory flags ~14 wrappers in `src/granular/gallery.py`, `src/granular/project.py`, and `src/granular/timeline_item.py` that call methods (e.g., `Gallery.GetAlbums`, `DeleteOptimizedMedia`, `GenerateOptimizedMedia`, `SetClipSelection`, `TimelineItem.GetMediaType`) that do not appear in the official scripting API docs. These need investigation to determine whether they should be replaced with documented equivalents or removed.

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
- **AI skill reference updated** — merged PR #30's `docs/SKILL.md` and updated it for the Resolve 20 method count, 354-tool granular server, version guards, and source media integrity guidance
- **Stale Resolve handle recovery** — both server modes now validate cached Resolve handles and reconnect cleanly after Resolve restarts or Project Manager transitions

### v2.2.0

- **Granular server modularized internally** — `src/resolve_mcp_server.py` is now a thin entrypoint, with the 354-tool implementation split across `src/granular/resolve_control.py`, `project.py`, `timeline.py`, `timeline_item.py`, `media_pool.py`, `folder.py`, `media_pool_item.py`, `gallery.py`, `graph.py`, and `media_storage.py`
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
| MCP Tools | **27** compound (default) / **337** granular |
| API Methods Covered | **336/336** (100%) |
| Methods Live Tested | **331/336** (98.5%) |
| Live Test Pass Rate | **331/331** (100%) |
| API Object Classes | 13 |
| Tested Against | DaVinci Resolve 19.1.3 Studio + Resolve 20.3.2 Studio |
| Compatibility Note | Resolve 19.1.3 remains the compatibility baseline; Resolve 20.x scripting calls are additive, version-guarded, and live-tested on 20.3.2; Resolve 21 beta APIs are intentionally deferred until stable |

## API Coverage

Every non-deprecated method in the DaVinci Resolve Scripting API is covered. The default compound server exposes **27 tools** that group related operations by action parameter, keeping LLM context windows lean. The full granular server provides **337 individual tools** for power users. Both modes cover all 13 API object classes:

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
| **Compound** (default) | `src/server.py` | 27 | Most users — fast, clean, low context usage |
| **Full** | `src/resolve_mcp_server.py` | 354 | Power users who want one tool per API method |

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
python src/server.py --full    # Launch full 354-tool server
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
│   ├── server.py                # Compound MCP server — 27 tools (default)
│   ├── resolve_mcp_server.py    # Thin full-server entrypoint — 354 tools
│   ├── granular/                # Modular full-server implementation
│   └── utils/                   # Platform detection, Resolve connection helpers
├── tests/                       # 5-phase live API test suite + Resolve 20 delta (331/331 pass)
├── docs/
│   └── resolve_scripting_api.txt # Official Resolve Scripting API reference
└── examples/                    # Getting started, markers, media, timeline examples
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
