---
name: resolve-conform
description: Conforming, relinking, and finishing prep in the DaVinci Resolve MCP. Apply when importing/relinking editorial, checking a conform against a reference, repairing reversed/retimed subclips, tracing grades across a re-conform, building relink plans, or QCing a conformed timeline frame-by-frame — live in a running Resolve OR offline against .drt/.drp files and the project DB. Routes to the live conform tools, the offline conform QC engine, and the online-editor craft skill.
---

# Resolve Conform / Interchange — Claude Code Skill

Bridges online-editing / finishing *craft* to this repo's *tools*.

- **Craft / finishing** — the global `online-editor` skill (conform, relink,
  finishing philosophy in Resolve and Flame). Use for *how a finishing editor
  thinks*, not tool mechanics.
- **Live tool mechanics** — `docs/kernels/timeline-conform-interchange-kernel.md`
  (the `timeline` conform/interchange boundary).
- **Offline conform engine** — `resolve-advanced/README.md` → `conform`,
  `color_trace`, `offline_ref`, `editorial`, `drt`, `project_db`.

## Two servers

| Job | Server | Tools |
|---|---|---|
| Import / relink / compare a **running** conform | `davinci-resolve` (Python, live) | `timeline` (conform actions), `media_pool` (`safe_relink`, `safe_import_sequence`) |
| Conform QC math, reverse-clip repair, lineage, grade tracing, `.drt`/`.drp`/DB edits with **no Resolve open** | `davinci-resolve-advanced` (Node) | `conform`, `color_trace`, `offline_ref`, `editorial`, `drt`, `project_db` |

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
  red/yellow/cyan verdicts), the standard finishing QC.
- **Reference-render compare** — build a `REF_OFFLINE` verdict when a burn-in-free
  reference exists.

## Carrying grades across a re-conform

`color_trace` matches clips across projects → a **trace plan** for carrying grades
through a re-conform (pairs with the `resolve-color` skill's `drx grade_transfer`).
For "what changed between cuts," use `editorial.turnover_changelist`
(see `resolve-edit`).

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
