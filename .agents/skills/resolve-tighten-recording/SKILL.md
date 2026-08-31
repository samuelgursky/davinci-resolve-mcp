---
name: resolve-tighten-recording
description: Tightening one long single-take recording — talking-head, screencast, tutorial, podcast video — by removing dead air in the DaVinci Resolve MCP. Apply when asked to tighten a recording, remove silences or dead air, cut the pauses out of a long take, or turn a raw one-take recording into a first cut. The subtractive counterpart to resolve-rough-cut, which selects shots from many clips; this skill removes time from one clip.
---

# Resolve Tighten Recording

Turns one long raw take into a tightened variant timeline. **The variant is the
deliverable; the original timeline is never touched.**

Everything below was measured live against Resolve Studio 21.0.1.11 / MCP
v2.80.1 on 2026-08-06, on a real 28.5-minute 30fps screen recording, unless a
different date is given.

## The deliverable contract

Deliver a tightened **variant** timeline, plan → review → confirm. Do not
grade, caption, or add anything; a tighten is pure subtraction. The variant
runs generous on purpose — recovering over-cut material is slow and invisible,
trimming further is fast and visible.

Two things always go back to the editor with the variant:

- **The largest lifts.** A lift is only *silence to the microphone*. Measured
  on real material (2026-07-31): a 29s lift was 70% silent on-screen
  demonstration — real content, cut because nobody spoke over it. Anything
  over ~15s deserves a human look before the variant is trusted.
- **What silence-driven tightening cannot hear** — see the last section.

## Workflow

1. **Lift the analysis caps for long media** —
   `media_analysis set_caps_preset {preset: "unlimited"}`. The standard preset
   carries a 90-second wall clock; multi-hour material dies on it. Restore
   `standard` when done (step 7).
2. **Transcribe** — `media_analysis start_batch_job` with
   `{clip_id, vision: false, transcription: {enabled: true, ...}}`, then
   `run_batch_job_slice {job_id}`. Two traps in one call pair:
   - **Batch jobs do not advance themselves.** `start_batch_job` returns a
     durable job in `queued` and nothing runs until a slice call drives it.
   - `run_batch_job_slice` **blocks until the slice completes** — budget
     roughly 4-7x realtime for local whisper (measured: 28.5min of Chinese
     speech in 5m14s via mlx_whisper) and run it from a background process,
     not the main conversation.

   Copy `clip_id` from `media_pool probe_media_pool` output. Never type it
   from memory: one transposed hex pair (measured 2026-06: `b9ab` → `9bab`)
   fails every downstream call in ways that look like engine bugs.
3. **Plan** — `edit_engine plan_tighten {timeline_name}`. Dry run; nothing
   moves. `min_pause_seconds` raises the bar when the default cuts too
   fine-grained. The plan persists on disk — planning and executing in
   different sessions is fine.
4. **Review with the editor**: lift count, estimated removed seconds, and the
   largest lifts (sorted by duration). This is the approval gate the whole
   tool sequence exists for — do not skip it because the numbers look
   reasonable.
5. **Execute** — `edit_engine execute_tighten {plan_id}` returns a
   `confirm_token` (TTL 300s); re-call with the token. Both calls in the
   **same MCP session** is verified; a token across a server restart is not —
   don't bet on it.
6. **Verify, in this order**:
   - `timeline detect_gaps_overlaps` on the variant → must be 0 / 0.
   - `readback.after.clip_count` in the execute response ≈ 2× the video
     keep-range count when audio is mirrored (113 video + 113 audio = 226
     measured). If it equals the *video* count alone, the variant is silent —
     stop and say so.
   - Spot-check placement with `timeline clip_where {track_type, track_index}`
     against the plan's keep ranges (coordinate rules below). `clip_where`
     reads the **current timeline only** — `set_current` to the variant first;
     it takes no `timeline_name` argument.
   - Total duration ≈ original − estimated_removed_seconds.
7. **Clean up** — restore `set_caps_preset {preset: "standard"}`,
   `project_manager save`, and list timelines: `execute_tighten` archives the
   source timeline once (`_versioning.archived: true`, by design), so a
   `*_archived_vNN` appears. Surface it; deleting is the editor's call.

## Coordinate rules — the trap that assembles the wrong content

The plan and the execute response describe ranges in **different coordinate
systems**, and both look like plausible frame pairs:

| Field | Coordinate system | Verified |
|---|---|---|
| plan `keep_ranges` `start_frame`/`end_frame` | **Source** frames, `end_frame` exclusive (duration = end − start) | frame-exact against `clip_where` readback |
| `structural_diff.added` `in_frame`/`out_frame` | **Record** (timeline) frames of the variant | matches variant item record spans, not source spans |
| variant record positions | cumulative sum of keep-range durations | `record[i] = Σ(end−start)(j<i)`, frame-exact |

Feeding `structural_diff.added` numbers anywhere a source range is expected
places every clip at the wrong moment of the right file — cut lengths stay
correct, nothing errors, and the timeline renders. When any endpoint semantics
are in doubt, place **one** range, read it back with `clip_where`, verify
position + duration + source span, then batch the rest.

## Multi-layer recordings

A camera track stacked over a screen-capture track (V1 + V2, same session) is
common for tutorials. `execute_tighten` assembles only the **analyzed**
source; the other layer is dropped from the variant, silently. To rebuild it:

1. Establish the constant offset between the two layers — and verify it by
   **audio cross-correlation** between the two source files (extract matching
   windows with ffmpeg, correlate; residual under 50ms passes). Eyeballing
   waveforms does not survive a 20-minute assembly.
2. Take the plan's `keep_ranges` (source frames), add the offset, and append
   with `media_pool append_to_timeline` clip_infos:
   `{clip_id, start_frame, end_frame, record_frame, record_frame_mode:
   "absolute", track_index: 2, media_type: 1}` (`media_type: 1` = video only;
   keep the analyzed layer's audio).
3. Verify counts and first/middle/last placements before trusting it.

Multicam compound clips do not reach the transcription engine at all — a
tighten on multicam material silently skips it. Keep plain stacked tracks and
use the recipe above instead.

## What silence-driven tightening cannot hear

`plan_tighten` measures the microphone, not the meaning. Three classes
survive every threshold, and each needs a different instrument:

- **Audible fillers and tight restarts** — `plan_transcript_tighten` covers
  these at word level (fillers, immediate ≤4-word restarts under 0.6s,
  collapsible pauses) and emits the same `keep_ranges` shape. Note its filler
  set is English hesitation words; other languages pass through unflagged.
- **Real retakes** — a sentence re-read seconds later, or reworded. Out of
  scope for the heuristics by design ("a real re-take and a human should
  choose"). This is an editor pass over the transcript, not a tool call.
- **Retakes whisper never even reports** — an immediate re-read is often
  emitted once, with the pause and second take absorbed into one word's
  duration (issue #125). Neither the transcript nor any silence threshold can
  see these; on measured material they were the majority of what a human
  still had to cut by hand. Treat word timestamps near suspected retakes as
  soft.

Report all three as known limits when handing over the variant, instead of
letting the tightened timeline imply "everything removable was removed".

## Common mistakes

- Trusting `detect_gaps_overlaps` alone — it proves the assembly is gapless,
  not that the right frames were kept. Duration check and spot placement
  reads are part of verification, not extras.
- Verifying audio by "the response said success" — count the variant's audio
  items.
- Renaming the variant with a default name kept. Name it for the action
  (`tightened`, `dead-air pass`, a version tag) so a project with several
  passes stays readable.
- Cutting fine pauses on instructional material. A pause while the presenter
  operates the screen is pacing, not dead air — raise `min_pause_seconds`
  and review the big lifts instead.
- Leaving the caps preset on `unlimited` after the run.

## Source-media safety (AGENTS.md)

The tighten pipeline reads source media and writes analysis artifacts to the
analysis root only. The variant references existing Media Pool items — no
transcode, no proxy, no relink, and the original timeline is archived by the
tool, never mutated.
