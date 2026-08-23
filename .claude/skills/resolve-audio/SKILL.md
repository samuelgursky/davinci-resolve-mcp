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

## Rough mix before anything else

If the ask is "make this sound balanced" rather than "route these buses", start with
`media_analysis mix_plan` (Python server, no Resolve needed). Give it the dialogue stems
and it derives the dialogue-normalisation gain, the music-bed level under it, and ducking
windows from the dialogue's own silence — then renders a premix and **measures it**, so
what you report is the loudness achieved rather than the gain arithmetic.

`dry_run` defaults to true: show the gains and the window count first. On a
full-programme standard (`ebu_r128`, `web`) a measured programme trim lands the whole mix
on target; on `ott_dialogue_gated` it deliberately does not trim, because dialogue is the
figure being graded. Flags (`loudness_off_target`, `true_peak_over`, `clipped`) come back
with remedies and are never auto-corrected — report them, do not paper over them.

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

## Live: loudness contracts and the silence gate

- **Named loudness standards** live with the delivery targets, not here:
  `render(action='list_loudness_standards')` → `web`, `podcast`, `ebu_r128`,
  `atsc_a85`, `ott_dialogue_gated`. Attach one to a delivery target and hand the
  emitted `loudness_target.target` to advanced `loudness_qc`. See the delivery
  skill for why dialogue-gated standards assert true peak only.
- **`plan_silence_ripple` calibrates its own gate.** Omit `threshold_db` and the
  threshold is measured from that clip's own dynamics (`astats` trough vs peak),
  per item, reported in `calibrations[]`. A fixed −30 dB under-detects on quiet
  location sound and over-cuts a noisy room.
- When trough and peak are not separated, no threshold distinguishes speech from
  room: the item is **kept whole** and the reason surfaced, rather than stripped
  against an unvalidated gate. A −30 dB default applied to a −33 dB programme
  reads as silent end to end and would remove the entire clip.
- Pass `threshold_db` explicitly to override; it is honoured untouched.

## Gotchas

- Timeline audio `SetProperty` (e.g. `Volume`) can return false for some
  generated item types; `AutoSyncAudio` depends on media + Resolve's sync engine.
- The public API does not expose Fairlight mix automation curves or plugin graphs
  — use `fairlight` for bus structure, not automation.
- **The whole-mix preset workaround is version-gated, and it is the only write
  path there is.** Per-parameter Fairlight control does not exist at any version;
  what exists is `GetFairlightPresets` + `ApplyFairlightPresetToCurrentTimeline`,
  which apply a saved mix wholesale. Both require **Resolve 20.2.2+** and are
  absent on 19.1.3 (confirmed live). So on an older build the per-parameter gap
  is the entire story and there is no workaround to offer — check with
  `resolve_control check_version_support` before proposing one, and say the build
  is too old rather than suggesting a call that will not be there.
- The **AI Audio Assistant** (one-click auto-mix) is not scriptable on any build
  — no method exists on `Resolve`, `Project`, `Timeline` or `TimelineItem`
  (issue #128). Presets cover the repeatable-template case, never the
  content-adaptive one.

Never modify/transcode/derive source media (AGENTS.md) — the offline `audio` ops
write NEW files to scratch, never over source.
