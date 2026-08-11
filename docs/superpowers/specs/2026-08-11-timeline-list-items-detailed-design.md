# Timeline Detailed Item Inventory Design

## Goal

Add a generic compound-server timeline action, `list_items_detailed`, that
returns the complete item inventory needed by automation workflows in one
call. The initial consumer is the `ig-post` workflow, which currently performs
separate calls for track enumeration, enabled state, item lists, source ranges,
Media Pool identity, file paths, and online state.

The action must remain useful to other editing, grading, conform, and delivery
workflows. No Instagram-specific policy belongs in the MCP action.

## Public API

Call shape:

```json
{
  "action": "list_items_detailed",
  "params": {
    "track_types": ["video"],
    "enabled_only": true
  }
}
```

Parameters:

- `track_types` is optional and defaults to `["video"]`. It must be a
  non-empty list containing unique values from `video`, `audio`, and
  `subtitle`.
- `enabled_only` is optional and defaults to `true`. When true, items on
  tracks confirmed disabled are omitted.

Successful responses have this shape:

```json
{
  "success": true,
  "count": 1,
  "track_types": ["video"],
  "enabled_only": true,
  "tracks": [
    {
      "track_type": "video",
      "track_index": 1,
      "enabled": true,
      "item_count": 1,
      "included_item_count": 1
    }
  ],
  "items": [
    {
      "track_type": "video",
      "track_index": 1,
      "item_index": 0,
      "timeline_item_id": "timeline-item-id",
      "name": "clip.mov",
      "start": 86400,
      "end": 86520,
      "duration": 120,
      "source_start": 24,
      "source_end": 144,
      "media_pool_item_id": "media-pool-item-id",
      "media_pool_item_name": "clip.mov",
      "file_path": "D:/media/clip.mov",
      "online_status": "Online"
    }
  ],
  "warnings": []
}
```

`track_index` is one-based because it addresses Resolve tracks. `item_index`
is zero-based within that track because downstream timeline-item actions use
that selector.

## Enumeration and safety behavior

The action obtains each requested track count from the current timeline and
enumerates tracks in the caller's `track_types` order, then ascending track
index. Items retain Resolve's order within each track. The flattened `items`
array therefore has deterministic ordering.

For each track, the action reads enabled state before deciding whether to list
its items. A track confirmed disabled is represented in `tracks`. When
`enabled_only` is true, its `included_item_count` is zero and its items are not
added to the flattened list. When `enabled_only` is false, disabled-track items
are included normally.

If enabled state raises or cannot be interpreted, `enabled` is `null`, a
structured warning identifies the track, and the action includes its items.
Unknown state must never cause potentially renderable media to be silently
omitted.

An empty requested inventory is a successful read with `count: 0`. Deciding
that an empty timeline is invalid remains workflow policy for callers such as
`ig-post`.

## Item details

The implementation reuses `_timeline_item_summary` for timeline identity,
track identity, timeline range, source range, and Media Pool identity. It adds
the zero-based `item_index` from enumeration.

When a timeline item has a Media Pool item, the action reuses
`_media_pool_item_summary` to read the source file path, then reads the `Online
Status` clip property. Missing Media Pool items or unavailable properties are
represented as `null`; they do not fail the entire inventory. This lets callers
distinguish an offline or generator item from a transport or validation error.

## Errors

The action uses the server's structured error envelope for invalid parameters
and continues to rely on the timeline dispatcher for connection, project, and
current-timeline errors.

Invalid cases include:

- `track_types` is not a list.
- `track_types` is empty.
- A track type is not `video`, `audio`, or `subtitle`.
- A track type appears more than once.
- `enabled_only` is not a boolean.

Per-track enabled-state failures are warnings rather than top-level errors, as
described above. Unexpected failures while obtaining a track count or item list
remain top-level errors because the inventory would be materially incomplete.

## Compatibility and exposure

Existing `get_items` and `get_items_in_track` behavior remains unchanged. The
new action is added to the compound timeline action inventory, dispatcher,
docstring, unknown-action list, and pull-on-demand action help metadata. No new
granular MCP tool is introduced.

## Testing

Focused unit tests will exercise the public timeline dispatcher with Resolve
test doubles and verify:

1. Defaults enumerate enabled video tracks and return detailed media fields.
2. Multiple enabled video tracks preserve track-local zero-based item indices.
3. Disabled tracks are reported but omitted by default.
4. `enabled_only=false` includes disabled-track items.
5. Requested video, audio, and subtitle tracks are enumerated deterministically.
6. An enabled-state exception produces a warning and includes the track.
7. Items without Media Pool objects return null media fields.
8. Empty timelines return a successful empty inventory.
9. Every invalid parameter case returns a structured validation error.

The focused tests must be observed failing before production changes are made.
After implementation, the focused tests and the repository's relevant timeline
and action-help test suites must pass.

## Out of scope

- Applying grades, DRX files, or CDLs.
- Creating projects or timelines.
- Rendering or deliverable QC.
- Persisting workflow manifests.
- Instagram-specific defaults beyond the generic video-first API defaults.
