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
| Wipes (EDL `W`-codes) | `transitions[].type: 'wipe'` (single soft-edge style — host-importer parity) | v2.138 |
| Transition styles | `transitions[].type: 'dip' \| 'additive' \| 'fade-to-color' \| 'smooth-cut' \| 'non-additive'` (XMEML effectids route automatically) | v2.140 |
| Audio cross-fades | `transitions[].trackType: 'audio'` | v2.116 |
| Constant retimes, forward | `cuts[].speed` (e.g. `0.5`) | v2.113 |
| Constant retimes, reverse | `cuts[].reverse` | v2.114 |
| Freeze frames | `cuts[].freeze` (holds source frame `srcIn`) | v2.134 |
| Speed ramps | `cuts[].ramp: [{durationFrames, speed}, …]` (linear segments only) | v2.139 |
| Audio placements, A1–A8 | `cuts[].audioOnly + track` | v2.115 |
| Built-in generators | `elements: [{type:'generator', generatorName}]` | v2.110 |
| Custom start timecode | `spec.startFrame` / `preserveStartTimecode` | v2.117 |
| Timeline markers | `spec.markers` (16 colors, notes, durations, customData) | v2.118 |
| Turnover markers | EDL `* LOC:` locators + OTIO markers → authored | v2.119 |
| TC-bearing sources (AAF route) | native clip capture (`MediaStartTime`), channel-leg merge | v2.120–2.122 |
| Subtitles | `spec.subtitles` / `spec.subtitlesSrt` (raw SRT) | v2.128 |
| Compound clips | survive `extract_from_drp` → `.drt` (inner containers kept, recursive) | v2.130 |
| Compound authoring | `spec.compounds` (multiple compose; nested edits render) | v2.131–2.132 |
| Nested compounds | `compounds[].compounds` (depth-2 through depth-4 playback render-verified) | v2.134–2.141 |
| Fusion titles | `elements: [{type:'title', text}]` — **21-gen hosts only** | v2.108 |

`assemble_from_interchange` drives the same engine from an EDL / OTIO /
FCP7-XML / AAF / **.prproj** (Premiere, read offline — no Premiere needed)
plus a `sourceMap` — all five formats are route-proven end-to-end
(parse → assemble → import → measured frames and RMS) — and
returns an honesty ledger
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

**Ramps are just more keyframes — but easing is a crasher.** The engine
honors intermediate keyframes in the same seconds-domain map (E63/E64:
a synthesized 50%→100% knee read back AND rendered with the exact predicted
frame cadence, srcIn baked into the first keyframe's Y, clip `In` at the cut
head). `cuts[].ramp` authors piecewise-constant segments. The keyframes'
`interp` field must stay **0**: an `interp=2` keyframe crashed Resolve
19.1.3 outright on import (app death, E65) — eased ramps are not authorable.

**Freezes are a third shape, not a flat retime.** A flat line in the retime's
frame domain reads back frozen but *renders moving* — the one divergence that
runs in the "working" direction. The real freeze (harvested from a live EDL
`M2 000.0` import, render-proven frozen by freezedetect) is a flat line in
**seconds**: `YMin = YMax = Y = frozen position` (source frame / fps),
`XMax = 60000` (a fixed sentinel, not the clip length), and the clip's `<In>`
left **empty**. `cuts[].freeze: true` authors exactly that; EDL `M2 000.0`
and zero-speed warps route to it through `assemble_from_interchange`.

**Gaps are legitimate.** Cuts need not abut: record gaps between placements
render as clean black (measured: cut 122.9 / gap 16 / white 234), so sparse
turnovers assemble without synthetic filler.

**Timeline origin.** Template timelines start at frame 86400
(01:00:00:00 @ 24fps). Clips placed before the origin are silently dropped
by Resolve on import — `startFrame` is timeline-absolute.

**Transition styles live in PrettyType — and the host XMEML importer is
inert.** Swapping `PrettyType` on the working dissolve skeleton renders the
named style (midpoint fingerprints: dip bottoms at pure black 16, additive
saturates at 233.8, fade-to-color plateaus dark at 77, smooth-cut blends at
179.9, non-additive holds the brighter side). Within `Cross Dissolve`, the
FieldsBlob style-id distinguishes dissolve from wipe. Resolve's OWN FCP7-XMEML
importer writes video `<transitionitem>`s that read back but render INERT on
19.1.3 (measured: both a plain Cross Dissolve and a Dip to Color played the
outgoing clip through the window) — so routing an XMEML turnover through
`assemble_from_interchange` produces transitions that render where the host
importer's do not.

**Dissolve geometry — spans follow the turnover, and the edge law.** A
transition's rendered span follows `<Start>`/`<Duration>`; `AlignmentType`
is cosmetic. The clip boundary must sit STRICTLY INSIDE the span — an
edge-aligned span (Start == the boundary) renders inert (measured), which is
why Resolve's own EDL importer moves the cut +dur/2 and centers. The bridge
reproduces per-format geometry exactly: EDL dissolves span [cut, cut+dur)
with the boundary shifted +dur/2 (CMX convention, host-importer parity —
render-verified: blend f48→f71 on a cut at 48); OTIO uses its explicit
in/out offsets; XMEML uses the transitionitem's own record span; spec-level
`transitions[].startFrame` overrides. Handles follow the actual span: the
incoming needs `srcIn ≥` the pre-cut portion, the outgoing needs tail media
for the post-cut portion. Off-center spans render (blend measured across an
uneven [cut-6, cut+18) span); everything unauthorable stays in
`droppedTransitions` with the reason.

## Verification checklist for a delivered .drt

1. `timeline.import_timeline_checked` — expect `linked == total` for media
   (generators legitimately count as offline). For `.drt`/`.drp` it also
   cross-checks the files items ACTUALLY link against the archive's
   `<MediaFilePath>` set and warns on a coarse-identity cross-link
   (`cross_link_warning`) — `linked == total` alone cannot see one.
2. Render a probe range; check frame luma at cut boundaries, dissolve
   midpoints (expect the blend average), and retime windows.
3. For audio: RMS per window (silence = -inf is a failed placement).
4. Never trust `created_new: false` — a same-named timeline already in the
   project is returned as "success" (internal-name-wins law).
5. Close the loop with `editorial.verify_roundtrip`: parse the original
   interchange and Resolve's own re-export of the imported timeline, and the
   verifier normalizes track labels, source naming, and per-source
   TC-absolute source frames (fitting the offsets, e.g. 86400 for a
   01:00:00:00 source) — `pass: true` means the authored timeline's export
   matches the turnover's intent event-for-event.

## References

- `docs/reference/api-limitations.md` — the measured laws in report form
- `resolve-advanced/vendor/drp-format/` — the codec layer (each module's
  header documents its measured ground truth)
- Guides: `conforming-an-avid-aaf.md` for the AAF ingest side
