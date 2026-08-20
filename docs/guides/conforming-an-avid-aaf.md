# Conforming a consolidated Avid AAF: what Resolve can and cannot do for you

You have an Avid picture turnover — an AAF plus consolidated media — and a folder
of camera originals. You want Resolve to relink the cut to those originals.

Three Resolve-native mechanisms look like they will do this. All three were
measured against one real 83-minute turnover (878 events, 882 timeline items,
multi-layer, consolidated media) on Resolve 19.1.3. **All three fail, and the one
that looks most convincing fails worst.**

This guide is about Resolve's own behaviour. It is reproducible by anyone with an
Avid AAF and a folder of camera originals.

## The short answer

| mechanism | what it does | verdict |
| --- | --- | --- |
| API `ImportTimelineFromFile` | `importSourceClips: true` creates **no timeline** at all. `importSourceClips: false` creates 882 items with **zero** media-pool items | unusable as a conform |
| **Reconform from Bins** (timecode-only) | **678 / 882 linked** — and the links are the **wrong takes** | silently wrong |
| **UI Import AAF + "Link to source camera files"** | **878 / 882 linked, only 144 correct — 734 wrong takes (84%)** | 🚨 **dangerous** |

The camera-file link is the option whose name promises exactly what you want. It
is the one to avoid.

## Why the camera-file link is the dangerous option

It links almost everything — 878 of 882 items — and **84% of those links are the
wrong take.** Four consecutive cuts pointed at the same wrong file. A head slate
linked to unrelated archival footage.

And then it **renders as a fully conformed timeline.** There is no offline media,
no red frames, no error, no warning. Every signal a conform is normally checked
against says the job is done. You have to compare against a picture reference,
frame by frame, to discover that most of the cut is showing the wrong moment.

A conform that is 16% correct and looks 100% correct is worse than one that
obviously fails, because the failure survives review.

## Why the matching goes wrong

Two reasons, and neither is a bug you can configure away.

**Name matching is impossible.** A consolidated Avid turnover names its clips
with instance names like `<something>.new.01` — names that belong to Avid's own
media database and match no file on disk. There is nothing to match on.

**Timecode alone is ambiguous.** Fall back to timecode and you get adjacent-take
drift: the matcher lands on a *neighbouring take from the same roll* — one
camera-roll index away from the right one. Those takes were often shot minutes
apart, overlap in timecode, and are visually similar enough to pass a glance.
That is the shape of the 678 Reconform-from-Bins links and the 734 wrong
camera-file links alike.

Adjacent takes are the worst possible failure mode: close enough to look
plausible, wrong enough to be unusable.

## What to do instead

**Conform against the consolidated media the AAF actually references, not against
camera originals.** The AAF's source references describe the consolidated
fragments; those match. Relinking to camera originals is a *second*, separate
problem — one that needs the source position and source timecode of each event,
not just its take name.

If you must reach the camera originals, you need per-event evidence beyond the
AAF's own clip names:

- the **physical source position and timecode** of each cut (`aaf_probe.py` emits
  `srcPos`, `srcTcFrame`, `srcTc`, `srcTcFps`, `srcTcDrop` per event — a
  fragment-relative source offset is not a position in the take, which is its own
  well-documented trap);
- the sequence **start timecode** (`startTimecode` / `startFrame`), because a cut
  built at Resolve's 01:00:00:00 default when the AAF starts at 00:59:50:00 is ten
  seconds out everywhere and only visible against a linked reference;
- an independent **picture reference** to verify against.

**Verify against a reference, always.** Whatever route you take, the only witness
that catches adjacent-take drift is a frame comparison against a reference render
or picture reference. Item counts, "linked" counts, and the absence of offline
media all agree with a conform that is 84% wrong. A witness derived from the same
state as the thing it is checking cannot contradict it.

## Related

- `docs/reference/api-limitations.md` — the scripting-API entries behind this,
  including `MediaPool.ImportTimelineFromFile` and the `AppendToTimeline`
  placement and durability limits you will hit if you build the timeline
  yourself.
- `docs/reference/api-limitations.md` → *Clip speed / retime ratio and speed
  ramps* — the same failure class in the Premiere XML route. Importing an FCP7
  XML that contains retimes through the scripting API places every retimed clip
  at `<in>`, which is the true source frame divided by the speed ratio. Lengths
  correct, links correct, wrong moment of the right file, no warning. If your
  turnover is a Premiere XML rather than an AAF, read that entry before trusting
  the conform.
- `docs/guides/headless-edit-loop.md` — which interchange formats relink at all
  when media has moved (DRT, OTIO and EDL do not).
</content>
