---
name: resolve-media-pool
description: Media pool ingest and organization in the DaVinci Resolve MCP. Apply when importing media, building multicam timelines, organizing/relinking clips, normalizing metadata, setting clip marks, or verifying/inventorying a card before ingest — live in a running Resolve OR offline. Routes to the live media_pool tools and the offline media front-end tool. For reading/analyzing footage content use resolve-media-analysis; for deliverable-side media QC use resolve-delivery.
---

# Resolve Media Pool / Ingest — Claude Code Skill

Thin router; depth stays in the kernel.

- **Live tool mechanics** — `docs/kernels/media-pool-ingest-kernel.md` (the
  `media_pool` ingest boundary) + `docs/guides/multicam-setup-guide.md`.
- **Offline media front-end** — `resolve-advanced/README.md` → the `media` tool.

## Two servers — verify offline, import live

| Job | Server | Tools |
|---|---|---|
| Import / organize / relink in a **running** Resolve | `davinci-resolve` (Python, live) | `media_pool` (`safe_import_media|sequence|folder`, `organize_clips`, `normalize_metadata`, `safe_relink|unlink`, `link_proxy_checked`, `set_clip_marks`, `setup_multicam_timeline`) |
| Verify / inventory / hash-seal a card with **no Resolve open** | `davinci-resolve-advanced` (Node) | `media` (needs ffmpeg + ffprobe on PATH) |

## Offline `media` actions

- `ingest_verify` — hash seal / verify / dupes-by-hash (chain of custody).
- `media_inventory` — fps / codec / colorspace / TC + card-gap report.
- `sync` — picture↔sound TC alignment + drift / MOS.
- `relink_manifest`, `rename_plan` (**refuses camera originals**) /
  `reel_normalize`, `turnover_package`, `project_hygiene`.

Rule of thumb: verify + inventory the card offline *before* importing, then import
and organize live.

## Boundaries & safety (AGENTS.md)

- Non-media files are not imported; the kernel never creates proxies, transcodes,
  or derivatives of source media.
- Native multicam clip creation/flattening is not in the public API — the setup
  helper preps a stacked timeline you convert in Resolve's UI (see the guide).
- **Never rename or derive camera originals** without explicit approval;
  `rename_plan` refuses them by design.
