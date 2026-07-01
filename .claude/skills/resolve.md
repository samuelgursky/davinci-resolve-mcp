---
name: resolve-mcp
description: Orientation and index for DaVinci Resolve MCP work — grading, editing, conforming, delivery, media analysis, and .drp/.drt/.drx file work, live in a running Resolve or offline with none open. Load this for a map of the domain skills, the live-vs-offline servers, and the cross-cutting safety rules. The per-domain skills (resolve-color / resolve-edit / resolve-conform / resolve-delivery / resolve-media-analysis) carry the depth and self-trigger on their own descriptions; use this as the map, or when a task spans several domains.
---

# DaVinci Resolve MCP — Index

Orientation for any Resolve MCP task. This is the **map, not the depth** — each
domain skill below carries its own routing and triggers on its own `description`.
Open the one that matches, or use this when a task spans several domains. This
skill does not auto-load the others; it points at them.

## Two servers — compute offline, apply live

- **Live** — `davinci-resolve` (Python): drives a *running* Resolve via the
  scripting API.
- **Advanced / offline** — `davinci-resolve-advanced` (Node): authors
  `.drp`/`.drt`/`.drx` files and patches the project DB with **no Resolve open**.

Rule of thumb: compute grades, QC, and conform math offline; apply the result
live. Node never drives Resolve.

## Domains

| Task | Skill | Kernel | Any-MCP-client prompt |
|---|---|---|---|
| Grading, looks, shot match, LUT/CDL/DRX | `resolve-color` | `color-grade-kernel.md` | `/color_grade_workflow` |
| Cutting, trimming, ranges, variants, changelist | `resolve-edit` | `timeline-edit-kernel.md` | `/timeline_edit_workflow` |
| Conform, relink, finishing QC, grade tracing | `resolve-conform` | `timeline-conform-interchange-kernel.md` | `/conform_workflow` |
| Render, deliverable QC, media/provenance | `resolve-delivery` | `render-deliver-kernel.md` | `/delivery_workflow` |
| Fusion comps (titles, MG, VFX) | `resolve-fusion` | `fusion-composition-kernel.md` | `/fusion_workflow` |
| Audio / Fairlight (tracks, buses, loudness) | `resolve-audio` | `audio-fairlight-kernel.md` | `/audio_workflow` |
| Media pool ingest / organize / multicam | `resolve-media-pool` | `media-pool-ingest-kernel.md` | `/media_pool_workflow` |
| Reading/analyzing source media | `resolve-media-analysis` | `media-analysis-guide.md` | `/analyze_media` |

## Less-common domains (no dedicated skill — go straight to the kernel/tool)

These have real coverage but low enough traffic that they route through this
index rather than their own skill:

- **Project lifecycle** — create/export/import/archive/restore projects,
  databases, settings, presets: `project_manager` compound tool →
  `docs/kernels/project-lifecycle-kernel.md`. Offline DB read/patch: advanced
  `project_read` / `project_db` (project CLOSED + quit/relaunch).
- **Review / annotations** — timeline markers, review reports, annotation
  copy/move/scope: `timeline_markers` → `docs/kernels/review-annotation-kernel.md`.
  Offline audit/lineage: advanced `provenance`.
- **Extension authoring** — install/remove Fuse/DCTL/Lua-Python plugins:
  `script_plugin` → `docs/kernels/extension-authoring-kernel.md`,
  `docs/authoring/`.
- **Pipeline (DB-as-truth)** — YAML-authored canonical project DB, staged runs
  with gates + provenance + drift: advanced `pipeline` tool →
  `resolve-advanced/README.md`.

## Cross-cutting rules (always)

- **Source media is sacred** (AGENTS.md): never modify, transcode, convert, proxy,
  relink, or derive source media unless explicitly asked. Outputs go to sidecars,
  scratch, or the analysis project root.
- **Frame-first color**: inspect Resolve-rendered frames before applying any
  grade/look/LUT/CDL/DRX, and preserve a recoverable grade version.
- **Guards refuse rather than fabricate** on the advanced server — read a
  "refused" message before retrying (usually wrong value space, log-encoded
  frames, missing media, or a missing optional dep; call the advanced
  `capabilities` tool).

## Deeper references

- `AGENTS.md` — canonical brief + the `## Domain Routing` index (all platforms).
- `docs/SKILL.md` — operating reference for both servers.
- `docs/kernels/` — per-action depth. `resolve-advanced/README.md` — offline catalog.
