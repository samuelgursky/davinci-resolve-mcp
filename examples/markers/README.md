# Marker And Review Annotation Examples

These prompts use the review annotation kernel on `timeline_markers` plus the
raw marker tools for timeline items and media pool items.

## Probe Annotation Support

```text
Probe annotation support for the current timeline. Include timeline markers,
the current timeline item when available, media pool item annotations, marker
custom data support, flags, and clip color. Do not change anything.
```

Expected actions:

- `timeline_markers.annotation_capabilities`
- `timeline_markers.probe_annotations`
- `timeline_markers.annotation_boundary_report`

## Add A Current-Playhead Review Marker

```text
Add a blue timeline marker at the current playhead named "Review" with the note
"Check this moment". Use marker custom data starting with "mcp-demo:" so it can
be found or cleaned up later.
```

Expected actions:

- `timeline_markers.add`
- `timeline_markers.get_all`

## Normalize A Marker Payload Before Writing

```text
Normalize this marker payload before writing it: frame 120, color teal, name
"Client note", note "Confirm title safe", duration 24, custom_data
"mcp-demo:title-safe". Tell me if the color or frame input needs adjustment.
```

Expected actions:

- `timeline_markers.normalize_marker_payload`

## Copy Review Notes Between Scopes

```text
Copy the timeline marker with custom data "mcp-demo:title-safe" to the current
timeline item. Preserve the note, name, color, duration, and custom data when
the target scope supports them.
```

Expected actions:

- `timeline_markers.copy_annotations`
- `timeline_markers.probe_annotations`

## Export A Review Report

```text
Export a read-only review report for the current timeline, including marker
names, notes, colors, custom data, flags, clip color, and any scope limitations.
Do not delete or modify markers.
```

Expected actions:

- `timeline_markers.export_review_report`
- `timeline_markers.annotation_boundary_report`

## Safe Cleanup Prompt

```text
Find markers whose custom data starts with "mcp-demo:" and show me a dry-run
cleanup plan. Wait for approval before deleting anything.
```

Expected actions:

- `timeline_markers.get_by_custom_data`
- `timeline_markers.clear_annotations_by_scope`
