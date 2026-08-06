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

## Show the gaps before cutting them (`edit_engine`)

- **`plan_dead_space_markers(timeline_name?, tightness?)`** — the review gate.
  Same calibrated detection as `plan_silence_ripple`, but it proposes **markers**
  instead of assembling a variant, so a human sees every gap before agreeing to
  lose it. **Use this whenever the ask is "mark the dead space so I can review
  and approve"** — that is a request for this verb, not for a tighten. Red =
  confident, Yellow = the gate only just cleared its separation floor. Nothing
  is written; pair the marker specs with `timeline_markers`.
- **`tightness`** on the dead-space planner: `generous` (default) | `balanced` |
  `tight`. Default is deliberately the loosest. A first assembly is supposed to
  be long — trimming a generous cut is fast and visible, while recovering
  material the machine already discarded is slow and invisible. Move to `tight`
  only when the editor asks for it.
- Guard bands are floored regardless of tightness: a removed gap always leaves
  frames before it (the outgoing word's decay) and after it (the incoming word's
  attack). `tight` removes *more gaps*, never *more speech*.

## Word-level editing and spoken search (`edit_engine`)

Silence-driven tightening cannot remove an audible "um" mid-phrase or a
stammered restart. These work on the words instead and are complementary to
`plan_silence_ripple`, not a replacement.

- **`plan_transcript_tighten(clip_ref)`** — fillers, false starts and long
  pauses, at word boundaries. Emits the same `keep_ranges` shape the variant
  assembler already takes, and **every removal states its reason**, so the plan
  can be argued with rather than only accepted. False starts are a flagged
  heuristic: tight repeats only, so "no, no, no" as emphasis survives.
- **`search_spoken_content(query, mode)`** — phrase / all_words / regex across
  every transcribed clip, returning timestamped hits with context plus
  `selects` (in/out with handles). A *lexical* axis; `find_similar` is the
  semantic-visual one. Use both — a shoot should be searchable either way.
  Deterministic order (clip name, then time), so an identical search gives an
  identical selects list.
- Needs `transcript_words`: run transcription, then strata backfill. Both
  actions say so rather than returning an empty plan.

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
