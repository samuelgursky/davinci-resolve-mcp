---
name: resolve-rough-cut
description: Assembling a short-form social rough cut from raw behind-the-scenes or vlog footage in the DaVinci Resolve MCP. Apply when asked for a rough cut, first cut, assembly, or "make me a timeline" from a folder of footage — day-in-the-life, BTS, process, or product-shoot material destined for Reels, TikTok, or Shorts. Covers ingest, shot finding at scale, vertical timeline setup, and gapless assembly.
---

# Resolve Rough Cut — Claude Code Skill

Turns a folder of raw footage into an assembled, gapless timeline. **The
timeline is the deliverable, not a finished video.**

For editorial craft (why a cut works) see `docs/guides/editorial-decision-guide.md`.
For the analysis layer see the `resolve-media-analysis` skill. This skill is the
assembly recipe and the traps between them.

## The deliverable contract

Deliver an assembled timeline. Do **not** add titles, captions, text cards,
effects, transitions, music, or grading unless explicitly asked. Editors who ask
for a rough cut want shot selection and pacing; styling is theirs. Adding
graphics is work that gets thrown away — and see the Fusion trap below for why
it also silently fails.

Render an mp4 only to preview the cut, and say that is what it is.

## Workflow

1. **Probe before importing.** `ffprobe` every clip for `r_frame_rate`,
   `avg_frame_rate`, and `rotation`. Two things routinely differ from what the
   filenames and Resolve suggest — see Verified traps.
2. **For a series, add a timeline to the existing project — don't create a new
   one.** Check `project_manager list` first. One project per series keeps the
   bins, analysed clips and settings in one place; one per episode scatters
   them. Only create a project for a genuinely new series.

3. **On a NEW project, set BOTH frame rates before any timeline exists.**
   `timelineFrameRate` is locked once a timeline is created — set it via
   `project_manager safe_set_project_settings`. `timelinePlaybackFrameRate`
   cannot be set through the API at all, so **ask the user to set it in the UI
   now**, as a setup step:

   > Project Settings (gear, bottom-right) → Master Settings → Playback frame rate

   Do not defer this to the end or write it off as cosmetic; a mismatch has been
   reported to affect playback and output, not just the display. On an existing
   project, read both back and only raise it if they are wrong.
4. **Create a bin named for the episode, `media_pool set_current_folder` to it,
   THEN import.** That order is mandatory, not stylistic: `ImportMedia` has no
   destination parameter and always lands in the *current* folder, so importing
   first puts the clips wherever the current folder happens to be — see the
   `MediaPool.ImportMedia (current-folder destination only)` entry in the
   `api_truth` ledger. Restore the previous current folder afterwards if it
   matters. One bin per episode, not one shared dump — it keeps `analyze_bin`
   scoped and the Media Pool readable across a long series.
5. **Analyse** — `media_analysis analyze_bin`, `sampling_mode="adaptive_capped"`.
   Complete the `commit_vision` loop for every clip; leaving one in
   `pending_host_vision_analysis` is a failure, not a partial success (AGENTS.md).
6. **Find shots via contact sheets**, not one frame at a time:
   `python3 scripts/contact_sheet.py <clip_dir> <out_dir>` — see Shot finding.
7. **Assemble in one call** — `media_pool create_timeline_from_clips` with
   positioned `clip_infos`. Name the timeline for the episode.
8. **Verify** — `timeline detect_gaps_overlaps` must return zero of both, and
   check the total duration against the target.

## Shot finding at scale

`media_analysis` extracts frames at **full source resolution**. A 35-minute 4K
clip yields 80 frames at 2160x3840. Reading those individually to satisfy
`commit_vision` costs ~1,100 tokens each — a four-clip shoot exceeds 250 frames.

Tile them instead. `scripts/contact_sheet.py` burns frame index, timestamp and
`selection_reason` onto each tile, so per-frame findings stay reportable by
index. Roughly a 15x saving with no loss of coverage. It needs Pillow
(`pip install Pillow`) — the repo treats Pillow as optional elsewhere, but this
script hard-fails without it rather than silently producing nothing.

Ask for **short clips per subject** rather than 20-35 minute takes when the
shooter can choose. `adaptive_capped` tops out at 80 frames per clip, so a
35-minute take gets sampled only to about its first 16 minutes — the tail is
never seen.

**When footage arrives pre-culled** (the shooter has already thrown away the
unusable takes), scale the effort down: fewer frames per clip, fewer sheets, and
trust the selection rather than hunting for the good moments. The expensive part
of shot finding is separating usable from unusable, and that work is already
done. Don't re-litigate it.

## Verified traps

Each one silently produces a wrong result rather than an error.

**Every row states the build it was confirmed on.** A date alone is not
reproducible — the scripting API changes per patch release, so a trap confirmed
on one build is only a prior on another. Re-confirm before relying on a row
whose build is older than yours, and update the stamp when you do.

| Trap | Confirmed on | Symptom | Fix |
|---|---|---|---|
| `clip_infos` `end_frame` is **exclusive** | Studio 21.0 | 1-frame gap between every clip, and matching audio gaps | `end_frame = start_frame + duration` |
| **Mixed-fps duration floor** — `start_frame`/`end_frame` are **SOURCE** frames | Studio 21.0 (MCP v2.71.1) | Source fps ≠ timeline fps (24.0 or 29.97 source in a 23.976 timeline) → Resolve **floors** the source→timeline conversion, so a range planned to fill an exact record slot lands one frame short | Plan durations in **timeline** frames: `floor(src_frames * timeline_fps / source_fps)`. If the floored duration misses the slot, extend `end_frame` by one source frame and re-check |
| `create_timeline_from_clips` needs the current folder | Studio 21.0 | Bare `Failed to create timeline from clip_infos`, valid clip_ids | `media_pool set_current_folder` to the clips' bin first |
| `ImportMedia` has no destination parameter | Studio 21.0 (MCP v2.71.1) | Clips land wherever the current folder happens to be; an unrecognized destination arg is silently ignored | `set_current_folder` **before** importing (step 4) |
| Phone footage carries a `rotation` flag | Studio 21.0 | Stored 3840x2160, displays 2160x3840 | Check `rotation` in ffprobe; Resolve honours it. **Do not reframe** — it is already vertical |
| Phone footage is **VFR** | Studio 21.0 | `avg_frame_rate` differs per clip and from `r_frame_rate` | Match the timeline to what Resolve conforms to (its reported clip FPS), not to `r_frame_rate` |
| `timelinePlaybackFrameRate` is read-only | Studio 21.0.2 | `set_setting` returns False for every value form, before and after a timeline exists | No API path. Ask the user to set it in Master Settings during setup (step 3), not at handover |
| An API-built Fusion comp on a **media clip** renders **only when MediaOut has a path from MediaIn** | Studio 19.1.3.7, corrected 2026-08-02 | A comp wired `MediaIn → Blur → MediaOut` **does** render. But a `MediaOut` fed by a tool with **no source** does not merely get bypassed — the render job comes back `Failed`. The earlier blanket claim that such comps "never render" was too broad | Wire the graph so `MediaOut` descends from `MediaIn`, and never leave a tool unrooted. For text over picture, insert a Fusion **title** as its own timeline clip and set its `Text+` via `fusion_comp set_text_plus` |

The mixed-fps, `ImportMedia`, playback-frame-rate and Fusion rows are recorded in
the `api_truth` ledger and `docs/reference/api-limitations.md`; query them at
runtime with `resolve_control api_truth "fusion"` (or `"timeline"`,
`"media-pool"`). **The ledger is the canonical copy — this table is the
narrative version**, so when the two disagree the ledger wins and this table is
the thing to correct.

⚠️ A **running** MCP process keeps executing the version it started with, so a
`git pull` does not update the ledger until it restarts. Check
`resolve_control get_version` → `mcp.version` before trusting an `api_truth`
miss: on MCP v2.70.4, `api_truth "DeleteClips"` returns zero facts that
v2.71.1 does carry.

On burning text over picture specifically: the title route above renders, but
the API cannot choose a destination track (issue #74 — `Insert*IntoTimeline`
takes no `trackIndex` and always lands on V1), so overlaying text onto an
existing clip's track is not reachable end-to-end. Treat text as a request for
the user's UI pass, not something to attempt and half-deliver.

Destructive ops auto-archive the timeline, so several edits leave
`*_archived_vNN` timelines behind. Clean them up before handing over.

## Assembly shape

Build `clip_infos` as a flat list — source `start_frame`/`end_frame` plus a
cumulative `record_frame`:

```python
shots = [(clip_id, start_sec, duration_sec), ...]
infos, record = [], 0
for clip_id, start, dur in shots:
    start_f, dur_f = round(start * fps), round(dur * fps)
    infos.append({
        "clip_id": clip_id,
        "start_frame": start_f,
        "end_frame": start_f + dur_f,   # exclusive
        "record_frame": record,
    })
    record += dur_f
```

Working in seconds and converting once keeps the shot list readable and makes
the exclusive-`end_frame` rule impossible to get wrong twice.

## Common mistakes

- Reframing vertical-flagged footage into a vertical timeline — double-rotating
  or cropping material that already fits.
- Setting the timeline frame rate after creating the timeline; it is ignored.
- Trusting `detect_gaps_overlaps` alone — also confirm total duration and
  inspect representative frames.
- Reporting a render as the deliverable when the timeline is what was asked for.

## Source-media safety (AGENTS.md)

Assembly references existing Media Pool items and never transcodes, proxies, or
relinks source media. Analysis frames, contact sheets, and preview renders are
scratch artifacts — write them to the analysis root or session scratch, never
beside the source, and never into git.
