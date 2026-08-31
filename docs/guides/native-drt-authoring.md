# Native DRT Authoring — offline timelines that import AND render

The `drt` tool in the advanced server (`drt.assemble`,
`drt.assemble_from_interchange`) writes a **native-schema `.drt`** — a real
Resolve project archive that `ImportTimelineFromFile` accepts — entirely
offline. Unlike XML/AAF/OTIO interchange (which lands offline and needs a
relink), a correctly assembled `.drt` arrives **linked and rendering**,
because it carries native media-pool descriptors captured from a live Resolve.

Everything below was measured live on Studio 19.1.3.7 and render-verified
(frame luma via ffmpeg signalstats; audio via rendered RMS). Version numbers
mark the release where each capability shipped.

## The core doctrine: readback is blind, render is truth

The recurring bug class of this entire subsystem: a structure that imports
fine, **reads back fine through every API**, and renders black or silent.
Structural readback cannot detect any of these:

- media clips without native pool descriptors (black)
- Fusion title comps whose bytes were edited offline (black — see below)
- audio clips cloned from a donor with the donor's identity (silent)
- audio tracks added by cloning (silent — no Fairlight strip)
- a timemap in the wrong generation's encoding (plays at 100%, no warning)

Always verify with a render: video by frame luma, audio by RMS in the target
window. `render.verify_output` covers the container-level checks.

## Prerequisites

- **Per media file, once**: `media_pool.capture_media_template` (Python
  server, live Resolve required once). It caches the file's native pool
  `<Element>` + MediaRef under `~/.config/davinci-resolve-mcp/media-templates/`.
  After that, all assembly for that file is fully offline.
- Pass `targetAppVersion` (e.g. `"19.1.3"`) when the importing host is
  pre-21: it selects the r19-generation templates and version stamps.

## What you can author (all render-verified on 19.1.3)

| Capability | Spec surface | Since |
|---|---|---|
| Media cuts, multi-source | `media: [{mediaFilePath, spec, cuts}]` | v2.106–2.107 |
| Multi-track video (V2+ stacking) | `cuts[].track` (video-only above V1) | v2.112 |
| Cross-dissolves | `transitions: [{track, atFrame, durationFrames}]` | v2.111 |
| Audio cross-fades | `transitions[].trackType: 'audio'` | v2.116 |
| Constant retimes, forward | `cuts[].speed` (e.g. `0.5`) | v2.113 |
| Constant retimes, reverse | `cuts[].reverse` | v2.114 |
| Audio placements, A1–A8 | `cuts[].audioOnly + track` | v2.115 |
| Built-in generators | `elements: [{type:'generator', generatorName}]` | v2.110 |
| Custom start timecode | `spec.startFrame` / `preserveStartTimecode` | v2.117 |
| Timeline markers | `spec.markers` (16 colors, notes, durations, customData) | v2.118 |
| Turnover markers | EDL `* LOC:` locators + OTIO markers → authored | v2.119 |
| TC-bearing sources (AAF route) | native clip capture (`MediaStartTime`), channel-leg merge | v2.120–2.122 |
| Fusion titles | `elements: [{type:'title', text}]` — **21-gen hosts only** | v2.108 |

`assemble_from_interchange` drives the same engine from an EDL / OTIO /
FCP7-XML / AAF plus a `sourceMap`, and returns an honesty ledger
(`authoredTransitions`, `droppedTransitions` with reasons, `authoredRetimes`,
`flattenedRetimes`, `authoredAudioEvents`, `upperTrackCutsVideoOnly`).

## The laws (why the constraints are what they are)

**Fusion comp cache law (titles).** On 19.x, an imported Fusion comp renders
only via the machine's disk cache, keyed to the comp blob's *exact
compressed bytes*. Any offline byte change — even an identity recompression —
misses the cache and renders black; live Fusion render of imported comps
produces no frames on 19. Therefore offline title *text* cannot be authored
for pre-21 hosts. The working flow: assemble everything else offline, then
set title text post-import with `timeline.set_title_text` (live-verified on
19.1.3). Generators are exempt — plain `Sm2TiGenerator`, no comp — and
render everywhere (Solid Color, SMPTE Color Bar, Grey Scale verified).

**Fairlight strip law (audio).** Audio tracks cannot be grown offline: the
per-timeline Fairlight model (`FLStudioModelBA` in the pool's
`Sm2Sequence.FieldsBlob`) holds one mixer strip per audio track, and a
cloned track without a strip is mute. The r19 media template is captured
with **8 mono audio tracks** (strips included); audio placements beyond
track 8 refuse with instructions to re-capture a bigger template. Explicit
`audioOnly` cuts suppress the A1 convenience mirror (which otherwise
mirrors track-1 video cuts).

**Timemap generation split (retimes).** `Sm2TimeMap` keyframes are protobuf
points on 21 but keyed-dicts on 19, and 19 *silently ignores* the protobuf
form (clip plays 100%). The r19 keyed encoder is byte-exact against
Resolve's own output. The map spans the whole source stretched by 1/speed;
the clip's `<In>`/`<Duration>` window into it in record-domain frames.
Reverse is the same map with the Y endpoints swapped, and `In` then measures
from the source end.

**Timeline origin.** Template timelines start at frame 86400
(01:00:00:00 @ 24fps). Clips placed before the origin are silently dropped
by Resolve on import — `startFrame` is timeline-absolute.

**Dissolve geometry.** A transition is authored only when the predecessor
ends exactly at the cut and both sides have handle media for the centered
span (incoming `srcIn ≥ dur/2`; outgoing `srcIn + dur + dur/2 ≤ frameCount`).
Everything else stays in `droppedTransitions` with the reason.

## Verification checklist for a delivered .drt

1. `timeline.import_timeline_checked` — expect `linked == total` for media
   (generators legitimately count as offline).
2. Render a probe range; check frame luma at cut boundaries, dissolve
   midpoints (expect the blend average), and retime windows.
3. For audio: RMS per window (silence = -inf is a failed placement).
4. Never trust `created_new: false` — a same-named timeline already in the
   project is returned as "success" (internal-name-wins law).

## References

- `docs/reference/api-limitations.md` — the measured laws in report form
- `resolve-advanced/vendor/drp-format/` — the codec layer (each module's
  header documents its measured ground truth)
- Guides: `conforming-an-avid-aaf.md` for the AAF ingest side
