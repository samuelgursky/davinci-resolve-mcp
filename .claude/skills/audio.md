---
name: resolve-audio
description: Audio and Fairlight work in the DaVinci Resolve MCP. Apply when setting audio properties, syncing audio, isolating voice, generating subtitles, planning Fairlight track/bus layouts, checking loudness, routing buses, or splitting/trimming/converting audio — live in a running Resolve OR offline. Routes to the live audio tools, the offline audio planning/bus-routing tools, and the Fairlight kernel.
---

# Resolve Audio / Fairlight — Claude Code Skill

Thin router; depth stays in the kernel.

- **Live tool mechanics** — `docs/kernels/audio-fairlight-kernel.md` (the
  `timeline` audio/Fairlight boundary).
- **Offline planning + bus routing** — `resolve-advanced/README.md` →
  `audio_plan`, `fairlight`, `audio`.

## Two servers — plan/measure offline, apply live

| Job | Server | Tools |
|---|---|---|
| Audio on a **running** timeline | `davinci-resolve` (Python, live) | `timeline` (`probe_audio_item|track`, `safe_set_audio_properties`, `safe_auto_sync_audio`, `voice_isolation_capabilities`, `subtitle_generation_probe`, `fairlight_boundary_report`) |
| Plan tracks / route buses / edit audio files with **no Resolve open** | `davinci-resolve-advanced` (Node) | `audio_plan`, `fairlight`, `audio` |

## Offline

- **`audio_plan`** (pure Node) — `list_templates`, `select_template`,
  `track_plan`, `analyze_coverage`, `check_loudness` (R128 −23 / ATSC −24 /
  streaming −14 targets). Plan the layout before building it live.
- **`fairlight`** — bus routing has **no scripting API**; it patches the
  `FLStudioModelBA` blob. `read_buses_from_blob` (offline); `read_buses_from_db`,
  `expand_buses`, `export_template`/`import_template`, `backup`, `restore` (DB
  path — needs `better-sqlite3`; project CLOSED + quit/relaunch like other DB
  patches).
- **`audio`** — offline ffmpeg: `split` (silence/TC/intervals), `trim`,
  `convert` (needs ffmpeg on PATH — GPL, not bundled). Align/loudness-measure not
  yet vendored.

## Gotchas

- Timeline audio `SetProperty` (e.g. `Volume`) can return false for some
  generated item types; `AutoSyncAudio` depends on media + Resolve's sync engine.
- The public API does not expose Fairlight mix automation curves or plugin graphs
  — use `fairlight` for bus structure, not automation.

Never modify/transcode/derive source media (AGENTS.md) — the offline `audio` ops
write NEW files to scratch, never over source.
