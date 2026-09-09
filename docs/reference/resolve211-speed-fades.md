# Native Resolve 21.1 speed and fades

Compound `timeline_item` now accepts `set_speed` and `set_fades`, with an
`options` dictionary and the existing track/item locators. Granular mode exposes
`set_timeline_item_speed` and `set_timeline_item_fades` with the same dictionary.
These call native SetSpeed/SetFades, require callable methods and the 21.1 floor,
and return the native boolean as success. They do not replace legacy retime tools.

Speed options: Percentage (finite number; zero means freeze), PitchCorrection,
StretchKeyframesToFit and RippleTimeline (strict booleans). Native RippleTimeline
and StretchKeyframesToFit defaults are false. Omitted options are not synthesized.
No undocumented speed bounds are imposed; Resolve decides whether a finite speed
is supported for the target clip. Freeze, reverse, ripple and pitch behavior are
not claimed live-validated by this contribution.

Fade options: FadeIn and/or FadeOut, non-negative integer frame counts as defined
by the shipped FadeInfo stub. GetFades may return floats, so callers round-trip
integral readback values by explicitly converting to integers. Fractional setter
values are refused. Partial dictionaries are forwarded unchanged to Resolve.
Empty dictionaries, unknown keys and malformed types return errors before writes.

Example: `timeline_item("set_speed", {"options": {"Percentage": 50,
"RippleTimeline": false}, "track_type": "video", "track_index": 1,
"item_index": 0})`. For a one-second fade on a 24 fps clip, use
`{"options": {"FadeIn": 24, "FadeOut": 24}}` with `set_fades`.

## Contributor validation

Contributor-validated on macOS Studio **21.1.0.14** using synthetic media in a
disposable project. Both interfaces changed speed to 50% and fades to 24 frames
with matching native readback. Resolve-exported stills at timeline 2s after the
speed change matched the untreated source-at-1s export pixel-for-pixel, while
untreated timeline 2s differed. Fade start and final frame were black; the interior frame matched
the untreated frame exactly. This verifies these sampled video results, not an
entire rendered movie, audio pitch/volume, retimed keyframes, ripple edits or
other clip types. The native setters restore their original values after testing.

`tests/live_resolve211_speed_fades.py OUTPUT_DIR` enforces the named scratch
fixture before writes and exports the comparison frames. It requires a 24 fps,
zero-start timeline with one six-second synthetic test-pattern.mov video clip.
Do not run it on production media. Unit contracts cover both layers, native
failure, absent methods, invalid options, explicit false/zero and partial fields.

Synthetic fixture creation (outside Resolve, no source media involved):

```sh
ffmpeg -f lavfi -i 'testsrc2=size=640x360:rate=24:duration=6' \
  -f lavfi -i 'sine=frequency=440:sample_rate=48000:duration=6' \
  -c:v prores_ks -profile:v 0 -pix_fmt yuv422p10le -c:a pcm_s16le \
  test-pattern.mov
```

Create a disposable project named `Codex Speed Fades Validation 20260909`, set
640x360 and 24 fps, create a timeline starting at 00:00:00:00, and append this
clip once. The fixture name is deliberately explicit to make accidental writes
to an unrelated project fail. Compare decoded RGB pixels of the exported PNGs;
speed50_2s should equal baseline_1s, fade_2s should equal baseline_2s, and
fade_0s/fade_end should be black for each interface. The test exports stills;
it does not submit render jobs or establish whole-movie/audio acceptance.
