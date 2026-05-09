# Timeline And Edit Kernel Examples

These prompts use the `timeline`, `timeline_item`, conform/interchange, audio,
and render kernel actions. Use them in a disposable project or on explicitly
approved demo timelines.

## Inspect The Current Timeline

```text
Inspect the current timeline. Report timeline name, start/end frames, start
timecode, track counts, track names, current mark in/out, current video item,
and a compact list of items on video track 1. Do not mutate anything.
```

Expected actions:

- `timeline.get_current`
- `timeline.get_track_count`
- `timeline.get_items`
- `timeline_markers.get_current_video_item`

## Probe Edit Kernel Capabilities

```text
Report what the timeline edit kernel supports, partially supports, and does not
support in this Resolve build. Include duplicate, range copy, linked audio,
state-copy, transition, razor/split, and speed-ramp boundaries.
```

Expected actions:

- `timeline.edit_kernel_capabilities`
- `timeline.probe_edit_kernel_item`

## Duplicate Selected Clip With Linked Audio

```text
Duplicate the selected timeline clip to the track above, include linked audio
when Resolve exposes it, and report the source and duplicate timeline item IDs.
If selection cannot be resolved through the scripting bridge, tell me which item
IDs I should pass explicitly.
```

Expected actions:

- `timeline.get_items`
- `timeline.duplicate_clips`
- `timeline.probe_edit_kernel_item`

## Copy A Timeline Range

```text
Copy the marked timeline range to a destination starting 10 seconds after the
current playhead. Preserve linked audio and copy transform, crop, composite,
markers, flags, and clip color where supported. Dry-run first if required
inputs are missing.
```

Expected actions:

- `timeline.get_mark_in_out`
- `timeline.copy_range`
- `timeline.probe_edit_kernel_item`

## Conform And Interchange Report

```text
Inspect this timeline like an online editor. Detect gaps and overlaps, report
source frame ranges with 24-frame handles, detect missing media, and dry-run an
FCPXML export to a temp path. Summarize what is safe to trust and what is
version/page dependent.
```

Expected actions:

- `timeline.probe_timeline_structure`
- `timeline.detect_gaps_overlaps`
- `timeline.source_range_report`
- `timeline.detect_missing_media`
- `timeline.export_timeline_checked`
- `timeline.conform_boundary_report`

## Render Planning Without Rendering

```text
Build a render plan for ProRes 422 HQ or the closest available codec. Probe the
format/codec matrix, validate render settings, require a temp target, and queue
a job only if the settings validate. Do not start rendering without explicit
approval.
```

Expected actions:

- `render.render_capabilities`
- `render.probe_render_matrix`
- `render.validate_render_settings`
- `render.prepare_render_job`
- `render.export_render_boundary_report`
