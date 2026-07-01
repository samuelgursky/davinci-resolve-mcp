---
name: resolve-color
description: Color grading and look work in the DaVinci Resolve MCP. Apply when grading, correcting, matching shots, developing looks, or applying/modifying LUTs, CDLs, DRX grades, or copied grades — live in a running Resolve OR offline against .drx/.drp files. Routes to the live Python color tools, the offline advanced grading/QC catalog, and the project's color craft guidance.
---

# Resolve Color / Grade — Claude Code Skill

Bridges color *craft* to this repo's *tools*. This skill does not duplicate the
manuals — it tells you which one to open and the rules that cross both servers.

- **Craft / taste** — `docs/guides/color-decision-guide.md` (project-owned color
  guidance and API boundaries). The global `colorist` / `colorist-assistant`
  skills add colorist philosophy; use them for *how to see*, not tool mechanics.
- **Live tool mechanics** — `docs/kernels/color-grade-kernel.md` (the
  `timeline_item_color` boundary layer).
- **Offline grade compute** — `resolve-advanced/README.md` → the `drx` grading/QC
  catalog (the "Advanced (offline) server" section of the color kernel).

## Two servers, one grade

| Job | Server | Tools |
|---|---|---|
| Drive a **running** Resolve | `davinci-resolve` (Python, live) | `timeline_item_color`, `graph`, `gallery_stills`, `color_group` |
| Compute a grade **offline** from frames, or read/write `.drx`/`.drp` grades with **no Resolve open** | `davinci-resolve-advanced` (Node) | `drx`, `drp`, `project_db`, `provenance` |

**Division of labor:** the advanced server *computes* a grade and writes an
apply-ready `.drx`; **applying** it is the live server's job
(`timeline_item_color.safe_apply_drx`). Node never drives Resolve.

## The frame-first rule (non-negotiable — see AGENTS.md)

Before applying any grade, look, shot match, LUT, CDL, DRX, or copied grade to a
real timeline, **inspect representative Resolve-rendered frames** (thumbnails,
contact sheets, Gallery stills, marker frames, or a scratch-only visual report).
Compare bypass/current/after at matched timecodes when the API allows, and
restore the prior version/node state after any temporary bypass. Never grade
from metadata, graph availability, or a style label alone unless the user
explicitly asks for a blind/global pass. Preserve a recoverable grade version and
report which frames informed the change. Frames extracted for offline compute go
to scratch/analysis locations only — **never touch source media** (AGENTS.md).

## Offline grading / QC catalog (`drx` actions)

Frame-stats → arithmetic → `.drx`. All local, deterministic, guarded (they
**refuse** to fabricate a match rather than emit a silent no-op). Extraction and
apply are the caller's job. Pick by intent:

- **Match toward a reference still** — `match_to_reference` (affine mean/std,
  skin-line gated, luma-preserving).
- **Within-camera drift** — `level_clips` (exposure/WB to a group hero).
- **Cross-camera skin cohesion** — `skin_match` (skin-gated; throws on
  log/wrong-space frames).
- **B-roll cohesion** — `shot_match` (gray-world neutralize or hero match).
- **Known-neutral patch / gray card** — `white_balance_match`.
- **Black/white points to a hero** — `contrast_normalize`.
- **Saturation cohesion** — `saturation_match`. **Shadow cast** — `black_balance`.
- **Import ASC CDL** (`.cc`/`.ccc`/`.cdl`) — `cdl_io`. **Copy a Body look** —
  `grade_transfer`. **Attach a `.cube` LUT to a node** — `lut_apply`.
- **Season/host look** — `author_look` / `carry_look`.
- **Read frames** — `scope_read` (parade/vectorscope/black-balance/clip%),
  `intent_tags` (low_key / motivated_warm, to exclude from neutralize),
  `gamut_legal` (broadcast-legal, measurement only).
- **Verify** — `verify_grade` (intended vs applied → landed/drifted/missing).

## Cross-server gotchas that bite

- **Grade value space.** `drx` `generate`/`merge` default to `space:'ui'`
  (Resolve PANEL units; saturation 0–100, neutral 50). Pass `space:'drx'` only
  for raw internal floats. Decoded values are ground truth only for the
  calibrated set — check the `valueFidelity` marker
  (`resolve-advanced/vendor/drx-parameters/CALIBRATION-STATUS.md`).
- **Hue-axis curves.** Naive `[0,1]` point lists are auto-canonicalized into the
  verified bezier cage. If a result carries a `warnings` array, the curve went
  through raw and will render **FLAT** — surface it, do not ship silently.
- **Apply targeting.** `safe_apply_drx` defaults to video track 1 / item 0 —
  **always pass `track_type`/`track_index`/`item_index` explicitly**, and grab a
  still/`.drx` backup first (it does not snapshot). `ApplyGradeFromDRX` *replaces*
  the graph — no append mode.
- **Relayout ("Cleanup Node Graph," no UI API).** Single clip, live: grab still →
  `drx(action="relayout")` → `graph.reset_all_grades` → `safe_apply_drx` with
  explicit indices (a same-structure apply keeps the OLD layout — the reset is
  required). Whole project, offline: `project_db(action="relayout_node_graphs")`.
- **Guards are load-bearing.** A thrown "refused" error usually means wrong input
  space, log-encoded frames, or missing media — read it before retrying. The
  grading catalog needs `sharp`; call the advanced `capabilities` tool for live
  status + install hints.
