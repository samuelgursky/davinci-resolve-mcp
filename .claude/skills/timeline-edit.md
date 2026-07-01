---
name: resolve-edit
description: Editing, cutting, trimming, pacing, and timeline restructuring in the DaVinci Resolve MCP. Apply when duplicating/moving clips, copying ranges, building variants, tightening or restructuring a cut, editing selects, or generating an editorial changelist/turnover — live in a running Resolve OR offline against .drt timeline files. Routes to the live edit tools, the offline editorial tools, and the project's editorial craft guidance.
---

# Resolve Timeline Edit — Claude Code Skill

Bridges editorial *craft* to this repo's *tools*. Open the right manual; don't
re-derive it here.

- **Craft / story** — `docs/guides/editorial-decision-guide.md`. The global
  `editor` / `assistant-editor` skills add editorial philosophy and cutting-room
  practice; use them for *why to cut*, not tool mechanics.
- **Live tool mechanics** — `docs/kernels/timeline-edit-kernel.md` (the `timeline`
  edit-kernel boundary: duplicate/copy/move, range ops, item-state copy).
- **Offline timeline / changelist** — `resolve-advanced/README.md` → `drt`
  (timeline file authoring) and `editorial` (interchange + turnover).

## Two servers

| Job | Server | Tools |
|---|---|---|
| Restructure a **running** timeline | `davinci-resolve` (Python, live) | `timeline` (edit kernel), `timeline_item`, `edit_engine`, `timeline_markers` |
| Author/diff a `.drt` **file**, or parse/compare editorial interchange with **no Resolve open** | `davinci-resolve-advanced` (Node) | `drt`, `editorial` |

## Live edit-kernel essentials

- Duplicate/relocate: `duplicate_clips` (modes `same_time`/`offset`/
  `at_playhead`/`track_above`/`after_source`/`next_gap`), `copy_clips` (alias),
  `move_clips` (duplicate-then-delete). `include_linked=True` carries linked audio.
- Ranges: `copy_range`, `duplicate_range`, `overwrite_range`, `lift_range`.
  **No public razor/split** — partial overlaps in `lift_range` are blocked unless
  `allow_partial_item_delete=True` (whole-item delete, not a trim).
- Item state copy: `copy_properties` (transform/crop/composite/audio/retime/
  markers/flags/grades/takes/keyframes …); scope with a group list.
- `edit_engine` drives higher-level selects/tighten/swap flows
  (plan → confirm → execute); tighten variants can carry audio via `keep_ranges`
  mirror / `include_audio`.

## Offline editorial (`editorial` actions)

- `parse_interchange` — EDL / OTIO / XMEML (AAF = an honest refuse, not a fake).
- `turnover_changelist` — moved / retimed / replaced / new / gone between two
  cuts, with timing silent-lie guards (it flags what it cannot verify).
- `conform_manifest`, `marker_roundtrip`.

Use these to answer "what changed between v3 and v4" or to hand a conform an
accurate change list **without** opening either timeline in Resolve. For carrying
a *conform* across a re-edit, see the `resolve-conform` skill.

## Source-media safety (AGENTS.md)

Edit operations reference existing Media Pool items — they never transcode,
render, proxy, or create derivatives of source media. Keep it that way. Treat
generated probe reports as local scratch artifacts, not committed files.
