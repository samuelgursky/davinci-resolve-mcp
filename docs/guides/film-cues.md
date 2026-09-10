# Picture-to-score cue handoff

`timeline_markers(action="export_cue_sheet", params={})` returns a read-only
`film-cues/v1` JSON document for the current timeline. Use `{"color":"Blue"}`
to export only a scoring-marker colour. No project, media, or file is changed.

This fills the gap between the existing raw/review marker reports and a DAW:
picture-frame timing is explicit, independent of tempo and of the timeline's
displayed starting timecode. It is useful for becomingJim's sparse music and
sound-design cue spotting, and does not invent cues or make creative choices.

```json
{
  "schema": "film-cues/v1",
  "frame_rate": {"numerator": 24, "denominator": 1},
  "timeline": {"name": "Ch5", "start_frame": 86400, "start_timecode": "01:00:00:00"},
  "cues": [{
    "id": "marker:240", "name": "Music in", "note": "Cello",
    "color": "Blue", "custom_data": "B1-S02",
    "start_frame": 240, "duration_frames": 48,
    "start_seconds": 10.0, "duration_seconds": 2.0
  }]
}
```

## Timing contract

- Cue frames are integers relative to the first picture frame; an interval is
  `[start_frame, start_frame + duration_frames)`. A one-frame marker remains one
  frame; it does not automatically acquire the duration to the next marker.
- `timeline.start_frame` is absolute Resolve metadata. **Do not add it to cue
  positions** when placing cues against picture beginning at beat zero in Live.
- Seconds derive from integer frames and the exact rational frame rate. Resolve's
  common rounded NTSC rates are normalised, e.g. `23.976` to `24000/1001`.
- `start_timecode` is descriptive, including any drop-frame separator. Consumers
  need not parse timecode; this avoids confusing skipped timecode labels with
  skipped picture frames.
- Cue IDs identify positions within this timeline snapshot, not immutable shot
  identities across edits. Preserve `custom_data` for production shot/beat IDs.
- A DAW consumer must explicitly choose constant tempo or a tempo map and the
  arrangement offset. Current transport BPM alone does not describe automation.
- Malformed timings fail the export rather than rounding frames or returning a
  partial sheet. Unknown colours select zero cues; colours are case-insensitive.

The returned document can be passed to the companion Ableton MCP's film cue
planner/importer. Keep an explicit association with the picture version; this
format is not an automatic score reconform or a royalty cue sheet.

## Validation

```powershell
venv/Scripts/python.exe -m unittest tests.test_film_cues tests.test_marker_params tests.test_action_list_drift -q
venv/Scripts/python.exe tests/live_film_cues_validation.py
```

The live smoke uses the real MCP stdio client and current Resolve timeline,
asserts the cue count and timing, and verifies markers and playhead are unchanged.
