# Native Resolve 21.1 transitions

`timeline_item("add_transition", {"options": {...}, ...})` and granular
`add_timeline_item_transition(options, track_type="video", track_index=1,
item_index=0)` call TimelineItem.AddTransition. This is an additional native
route; the existing offline project-file transition workflow remains available.

Required options are `type` (non-empty native transition name), `category`
(`simple`, `fusion`, `ofx`, `audio`), `position` (`start`, `end`) and `alignment`
(`left`, `center`, `right`). Optional `duration` is a positive integer in frames,
or null/omitted to request Resolve's automatic duration. Unknown keys and malformed
values are refused before writes. The wrapper does not guess which transition
names are installed, calculate source handles, or silently substitute an effect.

Example options:

```json
{"type":"Cross Dissolve","category":"simple","position":"end","alignment":"center","duration":24}
```

The result is `success: false` when the native API returns None/False. Otherwise
`transition` contains its actual id, name, start, end and duration. Actual values
come from the returned item, not the requested options. A created object is not
proof of a correct render; verify output for each effect and source configuration.

Native transitions appear in GetItemListInTrack on the measured build. Adding one
therefore changes subsequent item indexes. Re-query the track before selecting
another item. Track indexes remain 1-based and item indexes 0-based.

The method has a 21.1 floor and is registered as a destructive write and MEDIUM
risk in both classifier tables. Explicit compound dry-run requests are refused
before the handler because this action has no native dry-run implementation.
Granular tool annotations also identify a destructive, non-idempotent write.

## Contributor evidence and limits

Contributor-validated on macOS Studio **21.1.0.14**, using generated red/blue
six-second clips in a disposable 24 fps project. A 24-frame centered Cross
Dissolve with source handles returned start 59/end 83 around cut 71, without
moving either source clip. ProRes movie rendering completed. The rendered
boundary changed from red through a red/blue blend to blue. The same request
with zero outgoing/incoming handles returned failure and no transition.

The included scratch test exercises both community interfaces and creates render
jobs for independent movie inspection. Unit tests cover actual returned spans,
missing native methods, None/False failures, malformed options, optional duration,
write classification, and dry-run refusal. Audio transitions, Fusion/OFX effects,
other alignments, automatic duration and repeated insertion are not live-validated
by this contribution. Support for their documented options is pass-through.

`python tests/live_resolve211_transitions.py OUTPUT_DIR` requires a disposable
project named `Codex Native Transition Validation 20260909`, set to 640x360/24 fps,
with synthetic red.mov and blue.mov in its root bin. Generate each with FFmpeg:

```sh
ffmpeg -f lavfi -i 'color=c=red:s=640x360:r=24:d=6' \
  -c:v prores_ks -profile:v 0 -pix_fmt yuv422p10le red.mov
ffmpeg -f lavfi -i 'color=c=blue:s=640x360:r=24:d=6' \
  -c:v prores_ks -profile:v 0 -pix_fmt yuv422p10le blue.mov
```

It creates disposable timelines, renders movies and saves the scratch project.
Do not supply production media. Inspect frames 47, 65, 71, 77 and 95 in the
resulting movies: red before the overlap, progressively more blue through the
transition, then blue afterward. Also verify frame count and source-clip spans.
