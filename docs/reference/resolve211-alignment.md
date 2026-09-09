# Native Resolve 21.1 timeline alignment

Compound `timeline auto_align_clips` and granular `auto_align_timeline_clips`
accept `item_ids` (timeline item unique IDs, not media-pool IDs) and optional
`options`. All IDs must resolve in the current timeline's video/audio tracks;
missing or duplicate IDs are refused before writes. The requested order and
selection are preserved. This command does not implicitly add linked items.

**Include both video and linked audio IDs when synchronizing camera clips.**
Contributor observation on 21.1.0.14: waveform alignment of the video items alone
returned false; audio-only selection moved the audio while linked video stayed
put. Explicitly selecting all video/audio items aligned the complete fixture.
Do not assume that selecting one half of a linked pair moves the other half.

Options follow AutoAlignOptions: SyncUsing accepts
AUTO_ALIGN_CLIPS_USING_TIMECODE or AUTO_ALIGN_CLIPS_USING_WAVEFORM; UseTrack
accepts a native track number or AUTO_ALIGN_CLIPS_WAVEFORM_TRACK_MIX /
AUTO_ALIGN_CLIPS_WAVEFORM_TRACK_AUTOMATIC. Constant names resolve against the
live Resolve object; integral numeric native values are also accepted. Omitted
options stay omitted, using native defaults. Unknown keys, invalid named
constants and malformed types are rejected. Native false stays success:false.

The callable method and 21.1 floor are checked. The compound action is registered
as a destructive MEDIUM-risk write in both classifier tables. Explicit dry-run
requests are refused before mutation. Granular annotations mark a destructive,
non-idempotent write.

## Contributor validation and limits

Contributor-validated on macOS Studio 21.1.0.14, using synthetic speech and color
cards in a disposable 640x360/24 fps project. The two sources contain the same
speech but source timecodes differ by one second.

- Timecode fixture: deliberately placed at frames0/48, both wrappers moved the
  selected video/audio to frames0/24, matching source timecodes.
- Waveform fixture with MIX: deliberately placed at frames0/24, both wrappers
  moved all selected video/audio to frame0, matching identical speech content.
- For each mode, both wrappers' complete decoded ProRes video and PCM audio
  matched an independently positioned manual reference exactly. This is full
  rendered video/audio comparison, not just position readback.

Other audio track selections, dissimilar microphones, drift, variable frame rates,
long-form recordings and partly overlapping selections are not established by
this fixture. A failed chirp/video-only probe is not proof of a native bug.
Smart Switch is a separate operation and remains follow-up work.

`tests/live_resolve211_alignment.py OUTPUT_DIR` requires the disposable project
Codex Alignment Validation 20260909, with speech-red.mov and speech-blue.mov in
its root bin. Both are 24 fps color-card movies using the same synthetic spoken
recording; red timecode00:00:00:00 and blue timecode00:00:01:00. It creates manual,
compound and granular timelines for each mode, renders six movies and saves the
scratch project. Never substitute production media. Compare each mode's full
decoded video and audio against its manual reference. The helper tests also pin
ID ordering, malformed/missing input refusal, native failure and write gates.
