# Resolve 21.1 read-only discovery

Twelve readers expose native 21.1 data in both compound and granular modes.
They do not load presets, alter timeline settings, create render jobs, change
clips or perform normalization. Calls require a callable native method; older
builds without it return an explicit method/version error.

| Compound tool/action | Granular tool | Result |
|---|---|---|
| resolve_control is_studio | is_resolve_studio | is_studio boolean |
| resolve_control get_keyboard_presets | get_keyboard_presets | presets list |
| resolve_control get_current_keyboard_preset | get_current_keyboard_preset | active preset name |
| project_settings get_project_settings_presets | get_project_settings_presets | preset records with Name, Width, Height |
| render get_audio_formats | get_audio_render_formats | format descriptions mapped to extensions |
| render get_audio_codecs | get_audio_render_codecs | codec descriptions mapped to native codec identifiers |
| timeline get_normalize_audio_modes | get_normalize_audio_modes | native normalization-mode names |
| timeline get_output_blanking | get_timeline_output_blanking | blanking dictionary |
| timeline_item get_speed | get_timeline_item_speed | native speed options |
| timeline_item get_fades | get_timeline_item_fades | FadeIn/FadeOut frame durations |
| timeline_item get_output_blanking | get_timeline_item_output_blanking | blanking dictionary; empty when inherited |
| timeline_item get_use_timeline_for_output_blanking | get_timeline_item_use_timeline_for_output_blanking | use_timeline boolean |

For audio codecs, `format` is a file extension from the audio formats reader,
for example `wav`, not the display label `Wave`. Empty and non-string inputs
are refused before making the native call.

Clip readers accept `track_type` (`video` or `audio`), a 1-based `track_index`
and a 0-based `item_index`; defaults are video, 1, 0. Granular readers refuse
negative item indexes and invalid track types/indexes before lookup. These are
the existing compound item-location conventions.

The payload is passed through without coercing false, empty lists/dictionaries
or fractional frame durations. Empty clip blanking is valid when inheritance
is enabled. The four blanking values are native pixel coordinates; do not
reinterpret them as four independent margin widths. The speed reader returns
the native options rather than trying to derive speed from source/timeline
frame spans.

## Validation and limits

Contributed live measurement on macOS **DaVinci Resolve Studio 21.1.0.14**,
September 9, 2026: all twelve readers returned matching domain payloads through
both interfaces. Compound `_operation` instrumentation is separate from that
domain payload. No project/preset/clip mutation was invoked.

```sh
python -m unittest tests.test_resolve211_read_controls
python tests/live_resolve211_read_controls.py
```

The live script requires an existing project and timeline with a normal video
clip on video track 1. Its receipt omits project, clip and preset names.
Offline contracts exercise all readers, absent methods, preserved false/empty
values, required argument forwarding, and invalid granular item locators.

This is not a claim of full 21.1 API coverage, or a promise that corresponding
setters/multicam/transitions/normalization are implemented. The generic
GetProjectLastModifiedTime reader was intentionally deferred after the native
API returned None for several existing projects on the test installation.
That observation needs investigation rather than an advertised timestamp.
