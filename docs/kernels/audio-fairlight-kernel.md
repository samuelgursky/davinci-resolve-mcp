# Audio / Fairlight Kernel

The Audio / Fairlight kernel expands `timeline` into a safer audio-state,
mapping, voice isolation, auto-sync, transcription, subtitle, and Fairlight
boundary layer.

Live validation was run against DaVinci Resolve Studio 20.3.2.9 with a
disposable `_mcp_audio_fairlight_probe_*` project and generated synthetic video
plus audio-only media. Final release probe counts:

| Status | Count |
| --- | ---: |
| `supported` | 13 |
| `partially_supported` | 3 |
| `unsupported` | 0 |
| `version_or_page_dependent` | 0 |
| `not_applicable` | 0 |
| `error` | 0 |

The partially supported results were generated-item `Volume` property writes,
`AutoSyncAudio` execution, and `InsertAudioToCurrentTrackAtPlayhead`; all
returned false in the release probe while their guarded planning/probe layers
worked.

## Added Actions

All kernel actions are exposed through `timeline`.

| Action | Purpose |
| --- | --- |
| `audio_capabilities` | Return track, item, media pool, timeline AI, Fairlight, and known boundary support. |
| `probe_audio_track` | Snapshot audio track subtype, name, lock/enable state, and track voice isolation state. |
| `probe_audio_item` | Snapshot audio item properties, source audio mapping, voice isolation, and method availability. |
| `safe_set_audio_properties` | Validate audio property keys, write with readback, and restore original values by default. |
| `voice_isolation_capabilities` | Report track-level and item-level voice isolation availability and state. |
| `audio_mapping_report` | Report timeline item source audio mappings and MediaPoolItem audio mappings. |
| `safe_auto_sync_audio` | Validate clip selection and normalize Resolve audio-sync constants; dry-run by default. |
| `transcription_capabilities` | Report clip and folder transcription method availability without mutating by default. |
| `subtitle_generation_probe` | Dry-run subtitle generation by default; requires `allow_generate=True` to call Resolve. |
| `fairlight_boundary_report` | Return capabilities, track/item probes, mappings, transcription state, presets, and project methods. |

## Supported Findings

- Audio track subtype, name, lock, enable, and voice isolation state probing
  worked.
- Audio item source audio mapping and MediaPoolItem audio mapping readback
  worked on generated media.
- Guarded audio property dry-run worked.
- Voice isolation capability reporting worked for track and item scopes.
- Auto-sync dry-run produced a normalized Resolve-constant settings payload.
- MediaPoolItem transcription and clear-transcription both returned true on the
  generated video clip.
- Subtitle generation from the generated timeline returned true.
- Fairlight preset listing and the full boundary report worked.

## Boundaries

- Timeline item audio properties may be readable as `None` and can reject writes
  for some generated item types. The release probe saw `Volume` write and
  restore return false.
- `AutoSyncAudio` depends on media content and Resolve's sync engine. The
  guarded call normalized waveform/channel settings but Resolve returned false
  for the generated video/audio pair.
- `InsertAudioToCurrentTrackAtPlayhead` can return false depending on current
  track, page, and insertion state even with a valid generated audio path.
- Transcription and subtitle APIs can be asynchronous, language-component
  dependent, and license/build dependent even when they return true quickly.
- The public API does not expose full Fairlight mix automation curves or plugin
  parameter graphs.

## Live Probe

Run the live boundary probe with:

```bash
python3.11 tests/live_audio_fairlight_validation.py --output-dir /tmp/audio-fairlight-probe
```

The harness creates a disposable project, generates synthetic video and
audio-only media, probes track/item audio state, source/audio mappings,
voice-isolation state, guarded property writes, auto-sync, transcription,
subtitle generation, Fairlight preset listing, audio insertion, writes JSON and
Markdown reports, deletes the project, and removes generated media.

Use `--keep-open` only when you intentionally want to inspect the disposable
project by hand.
