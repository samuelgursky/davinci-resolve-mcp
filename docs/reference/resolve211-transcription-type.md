# Resolve 21.1 transcription and timeline-item type reads

Resolve 21.1 added `MediaPoolItem.GetTranscription` and
`TimelineItem.GetType`. The compound server already preferred the full native
transcription over the older truncated clip-property preview. This change adds
the missing granular transcription tool plus direct type reads in both server
modes.

## Live acceptance

Tested on Resolve Studio 21.1.0.14 using a disposable project and a 14-second
synthetic spoken-camera clip. Native `TranscribeAudio(False, False)` completed
with status `Transcribed`. The official API, compound
`media_pool_item.get_transcription`, and granular
`get_media_pool_item_transcription` returned the same English transcription:
one segment with 19 timed words. Nested-clip transcription was disabled.

The clip was also placed on a timeline. Native `TimelineItem.GetType`, compound
`timeline_item.get_type`, and granular `get_timeline_item_type` all returned the
lowercase string `video`.

The reusable harness is `tests/live_resolve211_read_completion.py`; structured
evidence is in
`docs/reference/evidence/resolve211-transcription-type.json`.

## Scope

This validates a non-nested English transcription on one video-plus-audio item
and the `video` timeline-item type. It does not establish nested-clip behavior,
speaker labels, other languages, audio-only items, titles, generators,
transitions, subtitles, multicam items, or every possible native type string.

## Re-run on v4.6.3, 2026-09-15

Rebuilt from `main` at v4.6.3 and re-measured on Studio 21.1.0.14 in a local disposable project. Native `GetTranscription`, compound `media_pool_item get_transcription` and granular `get_media_pool_item_transcription` agreed exactly: one English segment, 19 timed words. Native `GetType`, compound `timeline_item get_type` and granular `get_timeline_item_type` all returned `video`. `Transcription Status` reads empty while transcription is still processing and `Transcribed` once it is done.
