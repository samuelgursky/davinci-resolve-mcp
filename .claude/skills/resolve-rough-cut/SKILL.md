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
4. **Import into a bin named for the episode**, then
   `media_pool set_current_folder` to it. One bin per episode, not one shared
   dump — it keeps `analyze_bin` scoped and the Media Pool readable across a
   long series.
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

Confirmed live against Resolve Studio, 2026-07-28. Each one silently produces a
wrong result rather than an error.

| Trap | Symptom | Fix |
|---|---|---|
| `clip_infos` `end_frame` is **exclusive** | 1-frame gap between every clip, and matching audio gaps | `end_frame = start_frame + duration` |
| `create_timeline_from_clips` needs the current folder | Bare `Failed to create timeline from clip_infos`, valid clip_ids | `media_pool set_current_folder` to the clips' bin first |
| Phone footage carries a `rotation` flag | Stored 3840x2160, displays 2160x3840 | Check `rotation` in ffprobe; Resolve honours it. **Do not reframe** — it is already vertical |
| Phone footage is **VFR** | `avg_frame_rate` differs per clip and from `r_frame_rate` | Match the timeline to what Resolve conforms to (its reported clip FPS), not to `r_frame_rate` |
| `timelinePlaybackFrameRate` is read-only | `set_setting` returns False for every value form, before and after a timeline exists | No API path. Ask the user to set it in Master Settings during setup (step 2), not at handover |
| A Fusion comp attached to a **media clip** via the API never renders | Every call succeeds and the whole graph reads back correctly — comp count 1, `MediaOut1.Input` wired, `StyledText` returning what you set — while the output is the untouched source | Don't build comps on clips. Fusion **titles** inserted as their own timeline clip DO render, and their `Text+` is settable via `fusion_comp set_text_plus` |

The last two rows are recorded in the `api_truth` ledger and
`docs/reference/api-limitations.md`; query them at runtime with
`resolve_control api_truth "fusion"`. The ledger is the canonical copy — this
table is the narrative version.

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
