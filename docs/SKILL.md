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

---

## Two Server Modes

| Mode | Entry point | Tool count | Use when |
|---|---|---|---|
| Compound (default) | `src/server.py` | 27 tools | Most workflows — keeps context lean |
| Granular (full) | `src/server.py --full` | 354 tools | Power users needing one tool per API method |

This skill document covers the **compound server** (the default). Each compound
tool accepts an `action` string and an optional `params` object.

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
`apply_fairlight_preset(preset_name)`

---

### Media

**`media_storage`** — Browse mounted volumes and import files.

Key actions: `get_volumes`, `get_subfolders(path)`, `get_files(path)`,
`import_to_pool(items)` — `items` is a list of file path strings

**`media_pool`** — Full Media Pool management.

Key actions: `get_root_folder`, `get_current_folder`, `set_current_folder(path)`,
`add_subfolder(name)`, `create_timeline(name)`, `import_timeline(path, options?)`,
`import_media(paths)`, `delete_clips(clip_ids)`, `move_clips(clip_ids, target_path)`,
`get_selected`, `set_selected(clip_id)`, `export_metadata(path, clip_ids?)`

Note: `folder path` arguments use slash notation like `"Master/SubFolder"`.
`"Master"` or `"/"` refers to the root folder.

**`folder`** — Operations on a specific Media Pool folder.

Key actions: `get_clips(path?)`, `get_subfolders(path?)`, `export(path?, export_path)`,
`transcribe_audio(path?)`, `clear_transcription(path?)`

**`media_pool_item`** — Read/write clip metadata and properties. All actions
require a `clip_id` (the UUID returned by `GetUniqueId()`).

Key actions: `get_name`, `get_metadata(key?)`, `set_metadata(key, value)`,
`get_clip_property(key?)`, `set_clip_property(key, value)`, `get_clip_color`,
`set_clip_color(color)`, `link_proxy(proxy_path)`, `replace_clip(path)`,
`set_name(name)`, `link_full_resolution_media(path)`,
`replace_clip_preserve_sub_clip(path)`, `monitor_growing_file`,
`transcribe_audio`, `get_audio_mapping`, `get_mark_in_out`, `set_mark_in_out`

**`media_pool_item_markers`** — Markers and flags on clips in the Media Pool.
All actions require a `clip_id`.

Key actions: `add(frame, color, name, note, duration)`, `get_all`, `delete_by_color(color)`,
`delete_at_frame(frame)`, `add_flag(color)`, `get_flags`, `set_name(name)`

---

### Timelines

**`timeline`** — Timeline operations: tracks, clips, import/export, generators.

Key actions:
- `list` — all timelines in the project
- `get_current` — current timeline info
- `set_current(index)` — switch timeline by 1-based index
- `get_track_count(track_type)` — track_type: `"video"`, `"audio"`, `"subtitle"`
- `add_track(track_type, sub_type?)` / `delete_track(track_type, index)`
- `get_items(track_type, index)` — items on a track
- `delete_clips(clip_ids, ripple?)` — IDs are unique IDs from `get_items`
- `export(path, type, subtype?)` — type: `"AAF"`, `"EDL"`, `"FCPXML"`, `"DRT"`, etc.
- `insert_generator(name)`, `insert_title(name)`, `insert_fusion_title(name)`
- `get_mark_in_out`, `set_mark_in_out(mark_in, mark_out, type?)`
- `duplicate(name?)` — duplicate the current timeline
- `get_voice_isolation_state(track_index)` / `set_voice_isolation_state`

**`timeline_markers`** — Markers and playhead on the current timeline.

Key actions: `add(frame, color, name, note, duration)`, `get_all`,
`get_current_timecode`, `set_current_timecode(timecode)`,
`get_current_video_item`, `get_thumbnail`

Note: `get_thumbnail` returns raw pixel data from `GetCurrentClipThumbnailImage()`.
The dictionary includes `data` (raw bytes as a Python bytes-like object),
`format`, `width`, `height`, `noOfComponents`, and `depth`. This reflects the
current frame as rendered by Resolve — including any color grading or effects
applied — which is different from reading the source file directly.

**`timeline_ai`** — AI/ML analysis on the current timeline.

Key actions: `create_subtitles(settings?)`, `detect_scene_cuts`,
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
- `get_comp_info`, `set_frame_range(start, end)`, `render`
- `start_undo(name?)` / `end_undo(keep?)`
- `bulk_set_inputs(ops)` — batch set inputs across multiple timeline item comps in
  one call; each op requires timeline scope plus `tool_name`, `input_name`, `value`

---

### Render

**`render`** — Render pipeline: jobs, presets, formats, codecs.

Key actions: `add_job`, `list_jobs`, `delete_job(job_id)`, `delete_all_jobs`,
`start(job_ids?, interactive?)`, `stop`, `is_rendering`, `get_formats`,
`get_codecs(format)`, `set_format_and_codec(format, codec)`,
`get_resolutions(format, codec)`, `set_settings(settings)`,
`list_presets`, `load_preset(name)`, `save_preset(name)`,
`quick_export_presets`, `quick_export(preset, params?)`

---

## Common Workflows

### 1. Connect and verify

```
resolve_control(action="launch")
resolve_control(action="get_version")
resolve_control(action="get_page")
```

Always call `launch` first in a new session. It is safe to call when Resolve is
already running.

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
```

### 4. Inspect and annotate timeline items

```
timeline(action="get_items", params={"track_type": "video", "index": 1})
timeline_item(action="get_name", params={"track_type": "video", "track_index": 1, "item_index": 0})
timeline_item(action="get_property", params={"track_type": "video", "track_index": 1, "item_index": 0})
timeline_item_markers(action="add", params={"frame": 100, "color": "Blue", "name": "Review", "note": "Check this", "duration": 1, "track_type": "video", "track_index": 1, "item_index": 0})
```

### 5. Color grading

```
resolve_control(action="open_page", params={"page": "color"})
timeline_item_color(action="set_cdl", params={"cdl": {"NodeIndex": 1, "Slope": [1.1, 1.0, 0.9], "Offset": [0.0, 0.0, 0.0], "Power": [1.0, 1.0, 1.0], "Saturation": 1.0}, "track_type": "video", "track_index": 1, "item_index": 0})
timeline_item_color(action="add_version", params={"name": "Grade v2", "track_type": "video", "track_index": 1, "item_index": 0})
```

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
```

### 8. Add and start a render job

```
render(action="get_formats")
render(action="set_format_and_codec", params={"format": "QuickTime", "codec": "H.265 Master"})
render(action="add_job")
render(action="list_jobs")
render(action="start")
render(action="is_rendering")
```

### 9. Apply a Fusion effect to a timeline item

```
timeline_item_fusion(action="add_comp", params={"track_type": "video", "track_index": 1, "item_index": 0})
fusion_comp(action="add_tool", params={"tool_type": "Glow", "timeline_item": {"track_type": "video", "track_index": 1, "item_index": 0}})
fusion_comp(action="set_input", params={"tool_name": "Glow1", "input_name": "Gain", "value": 0.8, "timeline_item": {"track_type": "video", "track_index": 1, "item_index": 0}})
```

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
`docs/resolve_scripting_api.txt` for the specific method.

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

**Python version** — Resolve's scripting library works best with Python 3.10–3.12.
Python 3.13+ may cause `scriptapp("Resolve")` to return `None` due to ABI
incompatibilities.

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

**`timeline_markers(action="get_thumbnail")`** — Returns the thumbnail image at
the current playhead position. The response is a dictionary with keys `data`
(raw pixel bytes), `format`, `width`, `height`, `noOfComponents`, and `depth`.
This is the fastest way to get a frame preview, but the raw `data` field requires
client-side decoding.

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

The full API reference is in `docs/resolve_scripting_api.txt`.
