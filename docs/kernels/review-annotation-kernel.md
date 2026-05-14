# Review Annotation Kernel

The Review Annotation kernel expands `timeline_markers` into a scope-aware
annotation layer for timeline markers, timeline item markers, media pool item
markers, flags, clip colors, and read-only review reports.

Live validation was run against DaVinci Resolve Studio 20.3.2.9 with a
disposable `_mcp_review_annotation_probe_*` project and generated synthetic
video/audio media. Final release probe counts:

| Status | Count |
| --- | ---: |
| `supported` | 44 |
| `unsupported` | 1 |
| `partially_supported` | 0 |
| `version_or_page_dependent` | 0 |
| `error` | 0 |

The single `unsupported` result is the expected invalid marker color boundary
for `color="Invisible"`.

## Added Actions

All actions are exposed through `timeline_markers`.

| Action | Purpose |
| --- | --- |
| `annotation_capabilities` | Return supported scopes, colors, aliases, and known boundaries. |
| `probe_annotations` | Snapshot markers, flags, clip color, ids, and names for one scope or the current timeline context. |
| `normalize_marker_payload` | Normalize frame aliases, timecode, color, name/label, note/comment, duration, and custom data aliases. |
| `copy_annotations` | Copy markers between annotation scopes, optionally carrying flags and clip color. |
| `move_annotations` | Copy markers, then clear source markers when the source exposes marker deletion. |
| `sync_marker_custom_data` | Update marker custom data for timeline, timeline item, or media pool item scope. |
| `clear_annotations_by_scope` | Clear markers by color/custom data and optionally clear flags and clip color. |
| `export_review_report` | Return a read-only annotation report with optional capability metadata. |
| `annotation_boundary_report` | Return capabilities plus a live annotation snapshot. |

## Scope Matrix

| Scope | Markers | Custom Data | Flags | Clip Color | Frame Space |
| --- | --- | --- | --- | --- | --- |
| `timeline` | Supported | Supported | Not exposed | Not exposed | Timeline frame id or timeline timecode. |
| `timeline_item` | Supported | Supported | Supported | Supported | Timeline item marker frames. |
| `media_pool_item` | Supported | Supported | Supported | Supported | Source/media pool item frames. |

## Marker Payloads

The kernel accepts these frame inputs:

- `frame`
- `frame_id`
- `frameId`
- `frame_num`
- `frameNum`
- `timecode`
- `tc`

The kernel accepts `custom_data` and `customData`, plus `label` as an alias for
`name` and `comment` as an alias for `note`.

Validated marker colors:

`Blue`, `Cyan`, `Green`, `Yellow`, `Red`, `Pink`, `Purple`, `Fuchsia`, `Rose`,
`Lavender`, `Sky`, `Mint`, `Lemon`, `Sand`, `Cocoa`, `Cream`.

## Supported Findings

- Timeline marker add/get/update/custom-data readback works with frame,
  `frame_id`, `frameId`, explicit timecode, and current-playhead insertion.
- All documented marker colors were accepted in the live Resolve build.
- Timeline item markers support marker copy and custom data updates.
- Timeline item flags and clip color support add/read/set/clear.
- Media pool item markers, flags, and clip color support add/set/read/clear
  through the existing MCP wrappers and the new copy/move kernel helpers.
- `copy_annotations` successfully copied 21 timeline markers to a timeline
  item in the live probe.
- `move_annotations` successfully copied a media pool item marker to the
  timeline and cleared the source marker.
- `clear_annotations_by_scope` supports Resolve's `"All"` color sentinel for
  marker cleanup on timeline and timeline item scopes.
- `export_review_report` and `annotation_boundary_report` are read-only
  summaries over current annotation state.

## Boundaries

- Timeline, timeline item, and media pool item frame spaces are not equivalent.
  `copy_annotations` uses direct frame numbers; callers must map frames when
  moving between source, item-local, and timeline coordinate systems.
- Current-playhead marker insertion depends on a current timeline and readable
  current timecode.
- `probe_annotations` only includes timeline item and media pool item scopes
  when Resolve can resolve a current video item at the playhead.
- Flags and clip colors are review metadata, but they are not marker records.
  They are copied only when both source and target expose compatible methods.
- Invalid marker colors are rejected before calling Resolve.

## Live Probe

Run the live boundary probe with:

```bash
python3.11 tests/live_review_annotation_validation.py --output-dir /tmp/review-annotation-probe
```

The harness creates a disposable project, generates a short synthetic video
with audio, imports it, creates a timeline, probes annotation operations, writes
JSON and Markdown reports, deletes the project, and removes generated media.

Use `--keep-open` only when you intentionally want to inspect the disposable
project by hand.
