---
name: resolve-conform
description: Conforming, relinking, and finishing prep in the DaVinci Resolve MCP. Apply when importing/relinking editorial, checking a conform against a reference, repairing reversed/retimed subclips, tracing grades across a re-conform, building relink plans, or QCing a conformed timeline frame-by-frame — live in a running Resolve OR offline against .drt/.drp files and the project DB. Routes to the live conform tools, the offline conform QC engine, and the online-editor craft skill.
---

# Resolve Conform / Interchange
Bridges online-editing / finishing *craft* to this repo's *tools*.

- **Craft / finishing** — the global `online-editor` skill (conform, relink,
  finishing philosophy in Resolve and Flame). Use for *how a finishing editor
  thinks*, not tool mechanics.
- **Live tool mechanics** — `docs/kernels/timeline-conform-interchange-kernel.md`
  (the `timeline` conform/interchange boundary).
- **Offline conform engine** — `resolve-advanced/README.md` → `conform`,
  `color_trace`, `offline_ref`, `editorial`, `drt`, `project_db`.

## No Resolve? The work does not have to stop

`timeline author_offline` writes an importable timeline (`drt` / `otio` / `edl`) from a
file-path clip plan without any connection, and every not-connected error now carries an
`offline_alternative` block pointing at it.

Say plainly what happened: the live operation failed and a file was written — the
timeline is not in a project until someone imports it. Read the warnings back too.
`media_tc_origin_assumed` is the one that matters: OTIO source frames are
timecode-absolute, and an event without `media_start_tc_frame` imports as an *empty*
timeline with no error at all.

Default to `drt` (Resolve-native, project version 17 / Resolve 21.0 — older builds need
`drt downgrade`). Pick `otio` when the plan carries retimes; a `.drt` flattens them.

## Two servers

| Job | Server | Tools |
|---|---|---|
| Import / relink / compare a **running** conform | `davinci-resolve` (Python, live) | `timeline` (conform actions), `media_pool` (`safe_relink`, `safe_import_sequence`) |
| Conform QC math, reverse-clip repair, lineage, grade tracing, `.drt`/`.drp`/DB edits with **no Resolve open** | `davinci-resolve-advanced` (Node) | `conform`, `color_trace`, `offline_ref`, `editorial`, `drt`, `project_db` |

## What this build cannot do (check before you offer it)

The scripting API changes per **patch** release, so "Resolve 21" is not a usable
label. Read `resolve_control get_version` → `build.unavailable_on_this_build`
before offering a gated surface; `check_version_support` asks about one named
symbol. Gated on the relink/media side this domain leans on:

| Surface | Needs | If absent |
|---|---|---|
| `MediaPoolItem.LinkProxyMedia` | 17.0 | No script-side proxy attach |
| `MediaPoolItem.LinkFullResolutionMedia` | 20.0 | Cannot swap proxies back to full-res from a script |
| `MediaPoolItem.ReplaceClipPreserveSubClip` | 20.0 | Replacing a clip loses sub-clip boundaries; relink by path instead |
| `MediaPoolItem.MonitorGrowingFile` | 20.0 | No growing-file support during ingest |
| `MediaPoolItem.GetTimeline` | 21.0.4 | Cannot ask a clip which timelines use it; walk timelines and collect their items instead |

An empty `unavailable_on_this_build` means **nothing recorded is missing**, not
that everything exists — most of the API has never been version-bisected. A
symbol with no gate returns `unknown`, which means probe it. Probe with
`name in dir(obj)`, never bare `hasattr`: on a Resolve object `hasattr` returns
`True` for every name, real or invented, so it can only say yes.

The offline `conform` / `drt` / `project_db` routes are **not** gated this way —
they operate on files, so a missing live surface is a reason to reach for them,
not a dead end.

## Live conform essentials

- Inspect before touching: `probe_timeline_structure`, `detect_gaps_overlaps`,
  `source_range_report`, `conform_boundary_report`.
- Interchange: `export_timeline_checked` / `import_timeline_checked` (temp-guarded).
  **`drt` is the only lossless project-native round-trip**; EDL/FCPXML drop
  Resolve-specific relationships.
- **XML import via the scripting API goes _offline_** (missing-media/generators
  abort the import). Use `import_timeline_checked` with media **sanitize**
  (FCP7/FCPXML) so the API imports with links intact, then exact-path relink.
  A running MCP server must be restarted to pick up the sanitize fix.
- Missing media: `detect_missing_media` → `build_relink_plan` (read-only, bounded;
  skips broad scans when the source volume is unmounted) → execute only via
  `media_pool.safe_relink` with approved paths.

## Offline conform engine (`conform` actions)

The offline engine QCs a conform with **frame-oracle math, not filename
matching** — it catches a clip that relinked to the wrong-but-similarly-named
source. It also does:

- **Reverse/retimed subclip repair** — reversed `source_start` =
  `masterFrames − 1 − endoffset` (live-validated); DB-level repair.
- **Sequence lineage store + diff** — hashed timeline snapshots, diff, rollback.
- **Per-cut frame QC** — oracle-frame vs reference-render compare (scale-corrected;
  red/yellow/cyan verdicts), the standard finishing QC. Each cut is judged at the
  first frame CLEAR of its transition windows (inside one the reference is a blend,
  or black for a fade); Resolve's own FCP7 export ingests with `-1` edges resolved
  to junctions and its absent `pproTicksIn` tolerated (`<in>` is the source frame).
- **Reference-render compare** — build a `REF_OFFLINE` verdict when a burn-in-free
  reference exists.

## Carrying grades across a re-conform

Native ColorTrace keys on timecode/name/order inside one project and gives up on
renames, reorders, retimes and stringouts. The MCP path is two calls:

1. **Advanced server, no Resolve needed** — `color_trace plan` with
   `sourceProjectName`/`sourceTimeline` (graded) and `targetProjectName`/`targetTimeline`
   (the new cut), plus `emitDir` under the system temp dir. It matches on media
   identity (pool id / file path / reel / file name + source-range overlap — a
   stringout's graded sections resolve by overlap) and only falls back to names.
   Read `summary.byMethod`, `ambiguous`, and each match's `confidence`; it writes a
   lossless `.drx` per graded match and returns `planPath`.
2. **Live server** — open the target project and timeline, then
   `timeline_item_color apply_trace_plan` with `plan_path` and `dry_run: true` to
   get the resolution table (every entry is `apply` or `skip` + reason). Re-call
   without `dry_run` for a confirm_token, then with it to apply. `version_name`
   adds a local version per clip first so the previous grade survives; the
   timeline is archived to the Archive bin before anything is replaced.

Say plainly what did not resolve: `live_item_not_found`, `ambiguous_live_item`
and `below_min_confidence` entries are reported, never guessed. For a single look,
the `resolve-color` skill's `drx grade_transfer` is the lighter tool. For "what
changed between cuts," use `editorial.turnover_changelist` (see `resolve-edit`).

## Offline-reference clips

Offline-ref clips have **no scripting API** but do live inside `.drp`/`.drt` as
`<OfflineClip>` entries — patch via `offline_ref` (plain-XML/DB path), not the
live server.

## Gotchas that bite

- **`.drt` version.** For DaVinci Resolve 19.1.3, set `DbPrjVer` 17 → 16 when
  authoring a `.drt` or the import can fail.
- **`project_db` patches** require the project **CLOSED** in Resolve plus
  `iConfirmProjectClosed:true`; every write auto-backs-up and read-back verifies.
  Resolve caches open projects in memory — after patching, **fully QUIT and
  relaunch** Resolve or the change is invisible.
- **AAF** is an honest refuse in `editorial.parse_interchange`, not a silent
  empty result.
- Optional native deps gate some actions (`better-sqlite3` for lineage/reverse/DB,
  `sharp`/ffmpeg for frame compare) — call the advanced `capabilities` tool.

## Source-media safety (AGENTS.md)

Relink plans are read-only until you execute them; never relink, replace, or
create derivatives of source media without explicit approval. Preserve the chain
from camera original to final delivery.
