# Multicam Setup Helper Guide

The multicam setup helper prepares source-safe Resolve timelines for multicam
workflows. It is a workflow helper, not a native multicam API wrapper: DaVinci
Resolve's public scripting API does not expose creating native multicam clips,
switching multicam angles, or flattening multicam edits.

The current Resolve UI workflow is documented in the installed DaVinci Resolve
20 Manual, Edit > Chapter 42, "Multicam Editing." In Resolve, native multicam
creation and "Convert Compound Clips (Timelines) to Multicam Clips" are Media
Pool context-menu operations.

## What The Helper Does

`media_pool(action="setup_multicam_timeline")` creates a new prep timeline that
references existing Media Pool clips:

- One camera angle per video track.
- Optional matching audio tracks.
- Track names from angle names or clip names.
- Exact `AppendToTimeline([{clipInfo}])` placement with source ranges and
  record frames.
- Dry-run planning before touching Resolve project state.

The helper never modifies, transcodes, proxies, renders, relinks, replaces, or
creates derivatives of source media.

## What It Does Not Do

- It does not create a native multicam clip.
- It does not run Resolve's "Create Multicam Clip Using Selected Clips" dialog.
- It does not switch angles in an edited multicam clip.
- It does not flatten multicam clips.
- It does not perform waveform/audio correlation internally. Use
  `media_analysis(action="detect_sync_events")` as a separate read-only analysis
  layer when 2-pops or slate claps should feed this helper.

## Sync Modes

`stack_start`
: Places every angle at the same record frame. Use this when clips are already
  trimmed to the same sync point or you want a simple visual stack.

`source_timecode`
: Reads each angle's `source_timecode` parameter or Resolve clip Start TC
  metadata and computes offsets from `timeline_start_timecode`. Use this for
  jam-synced cameras or externally prepared timecode metadata.

`record_frame`
: Uses explicit per-angle `record_frame` values. Use this for manual sync,
  external alignment tools, or future FFmpeg/ffprobe audio-analysis results.

## Minimal Example

```json
{
  "action": "setup_multicam_timeline",
  "params": {
    "name": "Interview Multicam Prep",
    "clip_ids": ["clip-a-id", "clip-b-id"],
    "sync_mode": "stack_start",
    "include_audio": true,
    "dry_run": true
  }
}
```

Run the same call with `dry_run=false` or omit `dry_run` to create the timeline.

## Timecode Example

```json
{
  "action": "setup_multicam_timeline",
  "params": {
    "name": "Concert Multicam Prep",
    "sync_mode": "source_timecode",
    "timeline_start_timecode": "01:00:00:00",
    "start_timecode": "01:00:00:00",
    "include_audio": true,
    "angles": [
      {
        "clip_id": "cam-a-id",
        "angle_name": "Camera A",
        "source_timecode": "01:00:03:12"
      },
      {
        "clip_id": "cam-b-id",
        "angle_name": "Camera B",
        "source_timecode": "01:00:06:04"
      }
    ]
  }
}
```

The helper also accepts `start_frame`, `end_frame`, `duration_frames`,
`record_offset`, `track_index`, and `audio_track_index` per angle for more
explicit control.

## After The Timeline Is Created

1. Open the setup timeline and verify sync by scrubbing visible action, slate,
   clap, or reference audio.
2. Duplicate the setup timeline if you want a preserved editable source, because
   Resolve's conversion to multicam is one-way.
3. In the Media Pool, right-click the setup timeline.
4. Choose "Convert Compound Clips (Timelines) to Multicam Clips."
5. Edit the created native multicam clip into the working timeline.
6. Use Resolve's Multicam viewer, keyboard shortcuts, angle switching, and
   optional flattening tools for the edit.

## Agent Workflow

When asked to prepare multicam:

1. Gather clip IDs with `media_pool(action="probe_media_pool")` or
   `media_pool(action="get_selected")`.
2. Prefer a `dry_run` call first.
3. Explain which sync mode is being used and what evidence supports it.
4. Create the setup timeline only after the plan is coherent.
5. Report the resulting timeline name/id and remind the user that native
   conversion is a Resolve UI step.

For audio-derived alignment, first run a separate source-safe analysis pass
against source paths with `media_analysis(action="detect_sync_events")`. Use
the returned `alignment.suggestions[].suggested_record_offset_frames` values as
per-angle `record_offset` values, then call this helper with
`sync_mode="record_frame"`.

If sync markers would help the user verify the setup, show the returned marker
suggestions and ask first. Only after approval, call
`media_analysis(action="add_sync_event_markers", params={"confirm": true, ...})`
to write Media Pool item markers.

Do not install FFmpeg automatically. If `ffmpeg` or `ffprobe` is missing, report
that the optional audio-analysis layer is unavailable and suggest installing
FFmpeg before retrying that feature.
