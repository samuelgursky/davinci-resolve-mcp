# Changelog

Release history for the DaVinci Resolve MCP Server. The latest release is summarized in the root README; older entries live here to keep the README focused.

## What's New in v2.196.0 — E144: Resolve's own retimes decode; a flat map is a freeze

### Fixed

- **Resolve's own retimes decode.** Every retime Resolve 19.1.3.7 makes
  itself — an XMEML import, a UI speed change, an EDL `M2` freeze, a speed
  ramp — writes `KeyframesBA` in the keyed-dict form (keyframes
  `{interp,YOut,YIn,Y,XOut,XIn,X}` under keys `0`, `1`, …), which the DRP
  time-map reader rejected ("unsupported wire type 7"), so E140 called them
  unknown. The reader now decodes both forms; keyframe 0 at X=0 is the
  origin and its Y the source second the map starts on (4.0 s on a real ramp
  harvest). Verbatim harvest blobs: a 50% constant reads 50, a ramp reads
  its two segments (0.5 then 2.0) with the right source window, both freezes
  read the second they hold.
- **A source window is the map, evaluated.** A DRT event's `srcIn`/`srcOut`
  now come from evaluating the piecewise-linear map at `In` and `In +
  duration` (origin included), which makes ramps, reverses and rebased maps
  come out right without special cases.
- **A flat map over the 60000 sentinel is a freeze even with a source-in.**
  The E66 harvest (an XMEML import of a plain 100% clip) came back with a
  flat map at Y=0 and `In` 24, and its render is static at the source's frame
  0: inter-frame change 0.02 against 0.42 in the source. Resolve's XMEML
  importer froze the clip silently; the event now says frozen at frame 0 and
  keeps the ignored `In` as `recordDomainIn`. (The first draft of this fix
  called that map a harmless identity because it fit the prose; the render
  said otherwise.)

### Measured (filed in api-limitations)

- The keyed-dict keyframe form on Resolve-made retimes, and the freeze
  law with a present `<In>`.

## What's New in v2.195.0 — E143: a retimed DRT clip's source-in is record-domain

### Fixed

- **A retimed DRT clip's source-in is record-domain.** On a keyed
  `Sm2TimeMap` Resolve's `<In>` indexes the source stretched by 1/speed (the
  DRP library measured this live and writes `In = srcIn / speed` for exactly
  that reason), so the first source frame a retimed clip shows is `In × speed`,
  not `In`. E140 read `In` as a source frame, wrong by `(1/speed − 1) × In`:
  10,537 frames on a real 80% clip. The DRT event now carries `srcIn = In ×
  speed` (reverse: measured from the source tail), `srcOut` following at that
  speed, and the raw value as `recordDomainIn`.
- **Which meant a wrong "match".** Against the Premiere pix-lock, the hand
  conform's four 80% layers had read as unchanged because its `In` values
  equalled Premiere's source frames numerically — the very mistake: typing a
  source frame straight into `In` of an 80% clip shows a frame 20% of `In`
  earlier. Read correctly: the bridge-authored timeline (`In` 52682) matches
  Premiere frame for frame on all four layers, and the hand conform (`In`
  42145) shows source 33715 — 8,430 frames early — which the changelist now
  reports as four trims. The media volume was offline in this session, so the
  render witness for those four layers is owed; the law itself stands on the
  DRP library's live measurement.

### Measured (filed in api-limitations)

- The record-domain `<In>` law on retimed clips, with both real timelines as
  witnesses.

## What's New in v2.194.0 — E142: a cut re-aligned inside a dissolve is the same picture

### Added

- **A cut re-aligned inside an unchanged dissolve is the same picture.**
  Premiere keeps a fractional dissolve alignment (its cut sat 12 frames into a
  46-frame span); Resolve's conform re-centres it (23). The dissolve covers
  the same record frames from the same media either way, but the changelist
  read each one as a `moved` incoming plus a `trimmed` outgoing. When a
  transition's span is unchanged and the cut inside it moved with the
  incoming's source-in and the outgoing's source-out sliding by the same
  delta (scaled by the clip's speed for a retimed clip, read through a TC
  rebase), the pair folds into ONE `junction_realigned` — a consequence, not
  an edit — both sides count as retained, and the junction diff no longer
  reports the pre-roll change as a second fact. A dissolve whose span moved,
  or a cut whose source did not slide with it, stays a real move.
- **Two labels of one transition family are a relabel.** `Cross Dissolve
  (Legacy)` in Premiere and `Cross Dissolve` in Resolve are the same effect;
  they now land in `transitionRelabels` instead of `transition_changed`. A
  different family (a push, a wipe) is still a type change.
- **Shape `equivalent`.** A diff whose only changes are consequences (junctions
  re-aligned, labels) now says so, with a note, instead of `edit`.

On the real reel (Premiere REEL_02 pix-lock vs the Resolve conform): 206 of
228 cuts retained (189 before), 9 junctions re-aligned, 10 relabels, one real
move (a dissolve whose span moved), one real transition change, 19 trims on
the eye-matched files, the second mix track, the reversed tail leader and
frozen black — symmetric in both directions.

## What's New in v2.193.0 — E141: relink-aware changelist

### Added

- **`turnover_changelist` is relink-aware.** A real offline→online turnover
  (the Premiere REEL_02 pix-lock against the Resolve conform of the same reel)
  paired 15 of 228 cuts: the offline media was named `… 4K-2K … .mov`
  (proxies) where the online cut used `… 4K … .mov` (masters) and `.mp4`
  became `.mov`, so 203 identical cuts read as `replaced`. Now `sourceAliases`
  (`{from,to}` exact or `{pattern,replace}` regex) rename old sources before
  pairing, and a systematic rename is INFERRED from unpaired cuts that share
  a record window — adopted only when one-to-one both ways and either
  recurring or clearly the same name (LCS similarity ≥ 0.6), so a different
  shot dropped into the same window stays `replaced`. The result reports
  every alias with its cut count, similarity and whether it was inferred.
- **A per-source timecode rebase is not N trims.** Masters carry a different
  timecode base than the proxies: the same cuts read as `trimmed` by one
  constant shift. When one shift is a source's dominant story (≥2 cuts and
  more than half of its differing cuts) the compare reads old through it and
  reports it in `sourceTcOffsets`; a cut that still differs is a real trim on
  top of the rebase, with the pre-rebase window kept in its deltas. A source
  whose cuts each shift by a different amount (an eye-matched re-conform onto
  other media) stays trims — measured: two of seven cuts sharing a shift is a
  coincidence, not a base.
- **Premiere synthetic items name themselves.** A Universal Counting Leader
  or Black Video has no file: its `Media` writes a bare numeric id as the
  path and the human name in `<Title>`. They now read by title and carry
  `generatorName`, so they pair with the online cut's generators by name
  instead of reporting a numeric id replaced.

On the real reel: 189 of 228 cuts retained (was 15), 16 aliases inferred, one
source rebased by 47745 frames, symmetric in both directions; what remains is
the conform's own story — 27 trims, 10 junctions moved inside dissolves, the
online reel's second mix track, its reversed tail leader and frozen black.

## What's New in v2.192.0 — E140: a .drt retime decodes to its speed

### Added

- **A `.drt` retime decodes to its speed.** The keyed `MediaTimemapBA`
  (`Sm2TimeMap`) that E139 could only flag now reads through the DRP library's
  `decodeTimemap`, the same reader the `.drp` side uses: the keyframe slope is
  the speed ratio, `XMax 60000` with a zero slope is the freeze sentinel, a
  negative slope is a reverse. The parser's `timemap` becomes an object
  (`kind` linear | linear-multi | constant | variable | freeze | unknown,
  `speed`, `reverse`, durations, ramp `segments`), and a DRT event carries
  `speed` in the percent every other parser speaks with `srcOut` following the
  record window at that speed; a freeze is the zero-speed in==out event; a map
  the decoder cannot read stays `speed`/`srcOut` null + `retimeUnknown`, never
  a faked 100%. Measured on the real REEL_02 export: all four retimed clips
  read 80, and their `srcOut` lands frame for frame on what Premiere wrote for
  the same cuts (42423, 41949, 42178, 42178); the Black Video generator reads
  as a freeze; the tail leader reads as a reverse; nothing is left unknown.

### Measured (filed in api-limitations)

- A 19.1.3.7 EXPORT_DRT writes `KeyframesBA` in the protobuf point form, not
  the keyed-dict form its XMEML retime import writes; both decode.

## What's New in v2.191.0 — E139: a .drt timeline walks into events; two Resolve versions diff

### Added

- **A `.drt`/`.drp` timeline walks into normalized events, so two Resolve
  timeline VERSIONS diff.** `parse_interchange {format:'drt', content: PATH}`
  (optional `timeline` = pool name or index) returns the same event shape as
  every other format, with sequence-relative record positions plus the
  timeline's `fps`, `startFrame` and `startTimecode` read from the pool
  sequence. Measured on a real 19.1.3.7 export of a 229-clip reel: 230 events
  on V–V4 and A–A2, 11 dissolves attached with their witnessed alignment, the
  4 retimed clips flagged, and v19 vs v20 of that reel reads `identical, 229
  of 229 retained` through `turnover_changelist`.
- **The DRT parser reads the fields it used to skip.** Per clip: `in` (the
  source in-point — EMPTY on a real export's audio clips, reported `null`, and
  `srcInAbsent` on the event, never a silent 0), `mediaStartTime`,
  `mediaFrameRate` (decoded from Resolve's little-endian double blob) and
  `timemap` (`linear` vs a keyed `curve`; a curve is a retime this reader does
  not decode, so the event carries `speed: null`, `srcOut: null` and
  `retimeUnknown` instead of a faked 100%). Per track: `transitions`
  (`Sm2TiTransition` span, type, `alignmentType` → `alignment`: 2 centres on
  the cut, 3 ends at it, witnessed on all 11 real dissolves). Per timeline:
  `frameRate`, `startFrame`, `startTimecode` and `resolution` now fill from the
  pool `Sm2Sequence` (`FrameRate` LE double, `MediaExtents` seconds,
  `Resolution` BE uint64 pair) when the container carries none — a real export
  used to report them all `null`.

### Measured (filed in api-limitations)

- The EXPORT_DRT clip, transition and pool-sequence field encodings.

## What's New in v2.190.0 — E138: the changelist names its shape; pairing is closest-first globally

### Added

- **`turnover_changelist` leads with a SHAPE verdict.** A real Premiere
  auto-save of a locked reel kept 3 of its 335 cuts, byte-identical at their
  record positions, and deleted the rest: a patch/selects reel of the same
  cut. Per-event kinds read that as 332 `gone`. The result now names the
  relationship first: `identical` | `subset` (new keeps some of old's cuts
  unchanged in place and nothing else) | `superset` (the reverse) | `edit`,
  with `retained`, `oldCuts`, `newCuts`, and for subset/superset `sparse`,
  the `retainedWindows`, and a plain-language `note`. A transition that
  vanished or appeared with the cuts it joins counts as a consequence, not an
  edit. `gone`/`new` changes carry their record OUT so a dropped junction can
  be attributed to them.

### Fixed

- **Event pairing was first-come, not closest-first.** Walking new cuts in
  order let the first new instance of a source consume an old instance 6,000
  frames away while the old instance at its own position went unpaired, so
  the same two reels compared as `subset` one way and `moved + 332 new` the
  other. Every same-signature (old, new) pair now sorts by record distance
  and is taken once; the diff is symmetric under swapping old and new. On
  the real reels: `subset 3 of 335` forward, `superset 3 of 335` back.
  Sweep across every sequence the two auto-saves share: 739 compared, 738
  `identical`, 1 `subset`, 0 asymmetric in either shape or counts.

## What's New in v2.189.0 — E136: Premiere markers belong to their sequence and read their real fields

### Fixed

- **Every project marker landed on every sequence, at frame 0, unnamed.**
  The marker walk returned every `Marker` object in the project for each
  sequence and read fields the real shape does not carry: on a real Premiere
  2025 turnover that was 1,228 bogus markers per sequence. A sequence's
  markers are its own — `Sequence.MarkerOwner.Markers` → a markers container
  → `<Marker>` pairs → marker objects whose payload is a `DVAMarker` JSON
  blob (`mStartTime.ticks`, `mName`, `mComment`, `mType`, `mEndTime`). They
  now read from that blob (ticks to frames, duration from an end time),
  sorted by frame; the legacy field shape still reads when a sequence owns
  it; a sequence without a marker owner reports none. On the turnover: 188
  markers across 66 sequences, where every sequence used to show 1,228.

### Measured (filed in api-limitations)

- The Premiere 2025 marker ownership chain and the `DVAMarker` JSON payload.

## What's New in v2.188.0 — E135: Premiere tracks are lanes; nested blocks first-fit; an audio lane ceiling

### Fixed

- **Every Premiere track was labelled `V` or `A`.** Multi-track sequences
  collapsed onto one lane: on a real Premiere 2025 reels project 687 of 741
  sequences had cuts overlapping on the same lane (4,631 pairs), which the
  bridge refuses. Tracks now number per kind in track order (`V`, `V2` … /
  `A`, `A2` …) across track groups and the legacy lists, and clip events,
  fade legs and transitions carry the lane.
- **Nested sequences expand in a second pass, first-fit.** Two nested
  sequences stacked on different parent lanes each bring their own inner
  lanes, and a fixed lane offset collided on 7,615 pairs. A nested block now
  expands after every parent lane is known and shifts up by the smallest
  offset at which none of its cuts overlap what the parent or an earlier
  block holds (`laneShift` records it). On the reels project the only
  "overlaps" left are zero-length fade carriers — none real.
- **An audio lane ceiling in the bridge.** Flattened nested sequences can
  stack audio lanes to A40 (3,586 events above lane 16 on that project, in
  30 sequences); Resolve authors A1–A16. Events above 16 now drop with a
  reason in `audioLanesBeyondCeiling` instead of authoring blind.

## What's New in v2.187.0 — E134: real Premiere transitions attach, with their real type

### Fixed

- **Real Premiere transitions were invisible.** A Premiere 2025 track keeps
  its transitions in a separate `TransitionItems` list, not among
  `ClipItems` (measured on the reel: two video `Cross Dissolve (Legacy)`
  items and one audio `Constant Power` fade-in, none of which reached the
  parser). Each carries its span under `TransitionTrackItem.TrackItem`, an
  `Alignment`, `HasIncomingClip` / `HasOutgoingClip` (false = a fade from or
  to black or silence) and a `DisplayName`. The walk now reads
  `TransitionItems` alongside `ClipItems`; transitions attach to the
  incoming clip whose record-in falls inside the span and carry the real
  `DisplayName` as their type, so the bridge routes dissolves and audio
  cross-fades by name; a transition with no outgoing clip synthesizes the
  black/silence leg as before. The synthetic real-shape fixture pins a
  `TransitionItems` dissolve attaching at its explicit span.

### Measured (filed in api-limitations)

- The Premiere 2025 transition item shape and its fade flags.

## What's New in v2.186.0 — E133: Premiere nested sequences flatten into the reel

### Fixed

- **A nested sequence used as a clip was an unmapped reel.** In a real
  Premiere 2025 reels project, 3,607 items reference another sequence
  (`Clip.Source` → `VideoSequenceSource` / `AudioSequenceSource` →
  `SequenceSource.Sequence`), and the parser emitted the nested sequence's
  name as a source the bridge could not map. Those items now flatten: the
  nested sequence walks with its own cursor, its cuts of the same track kind
  translate through the clip's in-point window into the parent's record
  span (source frames trimmed at each cut's play rate), each tagged
  `fromCompound` — the OTIO Stack (E120) and AAF nested-composition (E125)
  flatten for Premiere. Depth and cycle guards keep a self-referencing
  sequence as a named `compound` hole. Measured on the reels project:
  13,711 events flatten, none remain as sequence-named sources. The real
  shape is pinned in the synthetic fixture.

## What's New in v2.185.0 — E132: real Premiere projects parse — 739 sequences where there were zero

### Fixed

- **A real `.prproj` listed no sequences and walked no events.** Measured on
  a real 130 MB Premiere 2025 colour turnover (project Version 45): objects
  live in two id spaces — numeric `ObjectID`/`ObjectRef` and uuid
  `ObjectUID`/`ObjectURef` — and every sequence, project item, master clip,
  medium and clip track is uuid-defined; sequences list their tracks through
  `TrackGroups` → track groups → `Tracks`; an item's record span sits under
  `ClipTrackItem.TrackItem` and its source behind `SubClip` → `VideoClip`
  (in/out points, source) → media source → `Media` (path); a zero is written
  as absence; names are direct `<Name>` children. The parser keyed
  `ObjectID` only, followed `ObjectRef` only, and knew only the synthetic
  shape — 0 of 739 sequences listed. Both shapes now walk: the turnover
  lists all 739 sequences by name and its reel walks 335 events with no
  unknown source or position (the counting leader lands at frame 0). The
  real shape is pinned as a synthetic fixture.

### Measured (filed in api-limitations)

- The Premiere 2025 `.prproj` object graph, both id spaces, the track-group
  chain, the clip source chain, and the omitted-zero law.

## What's New in v2.184.0 — E131: a nested Stack's audio tracks flatten onto the parent audio lanes

### Verified

- A compound's inner Audio tracks flatten onto the parent's audio lanes
  (`A`, `A2` …) tagged `fromCompound`, and the bridge places them on those
  lanes — three audio placements across two lanes, none dropped. Pinned as a
  test; the flatten from E120 already did this.

## What's New in v2.183.0 — E129/E130: `import_from_drp` names from the pool, imports timelines, keeps compounds

### Fixed

- **`timeline.import_from_drp` named containers after their first clip.**
  Resolve's own compound-timeline export listed as "cut_src.mp4" /
  "white_src.mp4", "by name" could not find the real timeline, and the
  default (all containers) imported the inner compound containers as
  separate, hollow timelines. The lister now names each container from the
  pool (`Sm2MpTimelineClip` / `Sm2MpCompoundClip` embed the `Sm2Sequence`
  the container's `<Sequence>` names) and reports `kind`; the default
  imports every TIMELINE; explicit names and indexes are unchanged (E129).
- **The Python extractor dropped a timeline's compound containers.** A
  compound is a pool `Sm2MpCompoundClip` whose embedded sequence lives in
  its own container (the E45 law `drt.extract_from_drp` already honours), so
  a timeline with compounds imported with hollow compounds. The extractor now
  keeps them recursively (MediaRefs → compound pool elements → embedded
  sequence ids → containers) and `metadata.json` lists `keptSeqContainers`.
  Verified on the fixture: E57_NESTED keeps E57_OUT and E57_IN; E57_OUT keeps
  E57_IN; the bundled template keeps its one container (E130). The
  bundled template's sequence now lists as `MediaTemplate` on this route
  too, where it used to read as its clip `sample.mp4`.

## What's New in v2.182.0 — E128: `extract_from_drp` defaults to the pool's timeline, not the first-sorted compound

### Fixed

- **The default extraction picked an inner compound.** `extract_from_drp`
  used index 0 by default, and SeqContainers list name-sorted by DbId; on
  Resolve's own export of a compound timeline (the E127 fixture) index 0 was
  the inner compound E57_IN, so the default emitted a hollow inner container
  instead of the timeline. The default is now the first container the pool
  kinds as a timeline (index 0 only when the export carries no pool kinds);
  `timelineName` picks a container by its pool name; an explicit
  `timelineIndex` still means exactly that container. The result reports
  `pickedBy`, the container's name and kind, and every container kept (a
  timeline keeps its compounds recursively). Verified on the fixture: the
  default yields E57_NESTED with E57_OUT and E57_IN kept; `timelineName`
  E57_OUT yields E57_OUT + E57_IN; index 0 yields E57_IN alone.

## What's New in v2.181.0 — E127: DRT timelines get their real names, and compounds their kind

### Fixed

- **`drt.parse` / `list_sequences` named a timeline after its first clip.**
  A SeqContainer XML carries no timeline name — its first `<Name>` is the
  first clip's — so Resolve's DRT export of a compound timeline listed
  "cut_src.mp4" and "white_src.mp4" as sequences (measured on 19.1.3.7; the
  export is a permanent fixture). The pool folder's `Sm2MpTimelineClip` and
  `Sm2MpCompoundClip` embed the `Sm2Sequence` each container's `<Sequence>`
  names; the parser now takes names and `kind` (`timeline` | `compound`) from
  there, tags a media-less clip named after a compound as `compound`, and
  `list_sequences` reports `kind` and `nestedIn` so a picker can demote the
  compound containers (E57_IN nested in E57_OUT, nested in E57_NESTED). The
  bundled media template's sequence now lists by its real name,
  `MediaTemplate`, where it used to read as its clip `sample.mp4`.

## What's New in v2.180.0 — E126: the sequence picker knows a nested composition from a turnover

### Added

- **`list_sequences` flags nested AAF compositions.** An Avid nested sequence
  (a composition another composition uses as a clip) listed as a peer of the
  timeline that uses it, so a "which sequence?" picker offered the inner
  composition as a turnover of its own. Each AAF sequence now reports
  `nests` (the compositions it flattens) and `nestedIn` (the sequences that
  use it); nested compositions still list — their cuts also arrive flattened
  inside the parent (E125) — but a picker can demote them.

## What's New in v2.179.0 — E125: an Avid nested sequence used as a clip flattens into the parent

### Fixed

- **A nested sequence in an AAF turnover was an unmapped reel.** A
  SourceClip that references a NAMED CompositionMob is an Avid nested
  timeline used as a clip; the walker's reference chase stopped at the first
  named mob and emitted the composition's name as a source reel while its own
  cuts sat in the same AAF. The walk now descends into the named
  composition's editorial slot and translates its cuts through the
  reference's window (source trimmed at each cut's play rate), tagging
  `fromCompound` — the OTIO Stack flatten (E120) for AAF. Unnamed
  intermediate compositions (subclips, group clips) keep the reference
  chase. Render-verified on 19.1.3.7: the flattened turnover conforms and
  plays the nested sequence's white insert exactly where the parent used it
  (234 across its 24 frames, picture either side).

## What's New in v2.178.0 — E124: the manifest and the changelist know a compound when they see one

### Fixed

- **`conform_manifest` names a compound clipitem.** Resolve's XML writer
  collapses a compound to one media-less item (E121); the manifest failed it
  as "no resolved path". It now fails by NAME with the remedy — map the
  compound's name to a flattened media file, or turn over as OTIO, where
  nested Stacks flatten (E120) — and resolves like any source once mapped.
- **`turnover_changelist` reports a compound collapse once.** The same
  compound seen flattened in one cut (OTIO) and collapsed in the other
  (XML) read as a replacement plus a gone cut. It is now
  `compound_collapsed` / `compound_expanded` (name, track, positions,
  inner cut count) and its cuts leave the pairing; a collapsed compound of
  another name over those cuts stays a real replacement.

## What's New in v2.177.0 — E123: round-trip QC is compound-aware; flattening keeps the junctions

### Added

- **`verify_roundtrip` understands the two writers' compound forms.**
  Resolve's OTIO writer flattens a compound's inner cuts (E120) while its
  FCP7 writer collapses the compound to one media-less clipitem (E121), so
  verifying flattened input cuts against an XML re-export read as count and
  source drift. An exported compound whose span covers input cuts flattened
  FROM that same compound now leaves the pairwise compare and is reported
  in `compoundsCollapsedInExport` (name, track, span, inner cut count). A
  collapsed compound over cuts that did not come from it stays drift.

### Verified

- Flattening keeps the junctions: an inner dissolve inside a nested Stack
  and a transition INTO the compound both author at their flattened
  positions — the bridge places both and drops none.

## What's New in v2.176.0 — E122: frame QC never scores a compound clip as a false red

### Fixed

- **A flattened compound cut read as a conform error in frame QC.** The
  lineage ingest of Resolve's FCP7 export read a compound's media-less
  clipitem as a source named after the compound with an oracle frame of 0;
  the sampler would then look for a source that does not exist and score
  the cut WRONG. The geometry parser now flags a clipitem whose `<file>`
  carries an explicitly empty `<pathurl>` as a compound, the lineage store
  keeps `is_compound` (pre-E122 sidecars migrate in place), and `qc` never
  samples such a cut: it reports `UNREADABLE` / review with a note naming
  the compound and pointing at the OTIO export, where compounds keep their
  inner content and flatten (E120). Picture cuts around it are judged as
  before.

## What's New in v2.175.0 — E121: a flattened XML compound is a named hole, not a refusal

### Fixed

- **An XML turnover with a compound clip refused to conform.** Resolve's FCP7
  writer flattens a compound to ONE clipitem whose `<file>` carries an
  explicitly empty `<pathurl>` and no inner content (measured on 19.1.3.7);
  read as a source reel, `assemble_from_interchange` refused the whole
  turnover as an unmapped reel. The walker now tags such clipitems
  `compound`, and the bridge drops them with a reason in
  `unresolvedCompounds` (name, track, record span) while the rest of the cut
  conforms — unless the sourceMap maps the compound's name to a flattened
  media file, in which case it authors like any clip. The reason points at
  the OTIO export, where compounds keep their inner content and flatten
  (E120).
- `timeline.get_items` help notes that `generator` also covers Fusion titles
  (Text+ enumerates with no media and no properties, like a generator).

## What's New in v2.174.0 — E120: compound clips in Resolve's OTIO exports flatten instead of vanishing

### Fixed

- **A compound clip in an OTIO turnover was silently dropped.** Resolve's
  OTIO writer nests a compound as a `Stack` inside the track — its
  `source_range` is the trim window into the compound, and nested compounds
  nest Stacks recursively (measured on 19.1.3.7 from a depth-2 timeline).
  `parseOTIO` skipped the Stack, so a 96-frame timeline parsed as 48 with no
  error. Nested Stacks now flatten into the parent's record time through
  their trim window (source frames trimmed at each clip's own play rate,
  inner upper tracks landing on the next lanes), each flattened cut tagged
  `fromCompound`, and the bridge's ledger names them
  (`flattenedCompounds`, `flattenedCompoundEvents`). Render-verified: the
  flattened conform of Resolve's own export is luma-identical to the
  original compound render at every sampled frame (three picture regions
  at 123–125, the 24-frame white insert at 234).

### Measured (filed in api-limitations)

- `EXPORT_FCP_7_XML` flattens a compound to a single media-less clipitem
  named after it, with no inner content; `EXPORT_OTIO` keeps the nesting.

## What's New in v2.173.0 — E118: Resolve's own OTIO exports re-conform

### Fixed

- **A Resolve OTIO export with generators could not conform.** Resolve's
  OTIO writer emits a Solid Color as a `Clip` with a NULL `media_reference`
  named after the generator (E117), which the parser read as a source reel —
  `assemble_from_interchange` refused the turnover ("unmapped source reel:
  Solid Color"). Generator clips — a null or `MissingReference` with a
  generator name, or a proper OTIO `GeneratorReference` — now walk as BL legs
  carrying `generatorName` (and the colour when a `GeneratorReference`
  declares one), so the bridge authors generators. Render-verified on
  19.1.3.7: the E110 fade-to-white conform, re-exported as OTIO and
  re-conformed, plays its clip → generator fade 124 → 96 → 68 → 41 → 18 → 16
  and holds 16 — black, because the OTIO writer carries no colour (E117),
  which `verify_roundtrip` reports as `generatorColourNotInExport`.

## What's New in v2.172.0 — E117: colour QC knows which writers are colour-blind

### Fixed

- **`verify_roundtrip` no longer fails a colour compare against a re-export
  that cannot carry colour.** Measured on 19.1.3.7: Resolve's OTIO writer
  emits a Solid Color as a `Clip` with a null `media_reference` and empty
  `Resolve_OTIO` metadata — no colour anywhere (its FCP7 XML writer echoes
  the colour as `input_1`). Pass `exportedFormat` (otio|edl|xml|drt): a
  colour-blind export reports `generatorColourNotInExport` (like
  `markersNotInExport`) instead of `generator-colour` failures; an XML
  export keeps the strict compare. Without the format the compare stays
  strict. Resolve's OTIO export is a permanent fixture.

### Measured (filed in api-limitations)

- `EXPORT_OTIO` writes generators as media-less clips named after the
  generator with no parameters; `Cross Dissolve` transitions carry a
  `transitionCustomCurvesKeyframes` 0→1 curve in `Resolve_OTIO` metadata.

## What's New in v2.171.0 — E114: audio-lane `-1` edges take their own lane's junctions

### Fixed

- **XMEML audio cross-fades lost 12 source frames on the incoming clip.**
  Resolve's FCP7 writer emits an audio cross-fade as a transitionitem on the
  audio track with `-1` clip edges exactly like video (measured on 19.1.3.7
  from the E109 AAF conform; its OTIO writer emits the same cross-fade as a
  `Custom_Transition` with 12/12 offsets). The E108 audio walk attached the
  transition but never computed that lane's junction list, so the incoming
  clip's `<in>` (the source at the OVERLAP start) lost its junction offset and
  `verify_roundtrip` failed the AAF → conform → import → XML loop with a
  12-frame audio `source-frames` drift. Each lane now resolves against its
  own transitionitems; the loop verifies `pass: true` through both writers.
- **v2.170.0's `kind` classifier was wrong for generators and subtitles.**
  Measured on 19.1.3.7 (E115): a Solid Color generator and a subtitle item
  return no MediaPoolItem and `None` from GetProperty() — exactly like a
  transition — so the "no media, empty properties" rule labelled both
  `transition`. The discriminator is now GEOMETRY: a transition straddles a
  cut (one neighbour ends inside its span, another starts inside it), a
  generator owns its span, subtitle tracks report `subtitle`, and known
  transition names short-circuit. Verified against Resolve's own enumeration
  of the E107 fades timeline (generator, dissolve, clip, dissolve, clip,
  dissolve, generator).
- **v2.170.0 also shipped with two red Python tests** — an item-shape
  assertion in the `get_items` selector test that did not expect the new
  `kind` field. The expectation is updated.

## What's New in v2.170.0 — E113: `get_items` knows a transition from a clip

### Added

- **`timeline.get_items` reports `kind`** — `clip`, `transition`, or
  `generator`. `GetItemListInTrack` lists transitions as items, and a video
  Cross Dissolve enumerates by name; an AUDIO cross-fade enumerates with an
  EMPTY name (measured on 19.1.3.7 on an assembled AAF turnover: 24 frames,
  centered on the cut, between the two dialog clips), so the name can never
  be the discriminator. A transition has no MediaPoolItem and an empty
  property dict; a Solid Color generator has no media but transform keys;
  everything else is a clip. An API surprise on the probe never demotes a
  clip.

### Measured (filed in api-limitations)

- The transition entry now records the nameless audio form and the
  media-pool/property discriminator, measured on both kinds.

## What's New in v2.169.0 — E112: round-trip QC is colour-aware

`verify_roundtrip` merged every generator leg out of the compare as "black",
so a fade-to-white that came back black — or a colour matte that lost its
colour — passed QC on geometry alone.

### Added

- **`verify_roundtrip` compares generator colours.** An input leg carrying a
  fill colour must come back on the same track over its span with the same
  colour (±1/255), else `generator-colour` fails; `generatorColours` reports
  the compare. Black-only turnovers compare nothing and stay silent.

### Fixed

- **Resolve's own re-export of an authored colour reads back.** The FCP7
  writer emits a Solid Color's colour as the FxPlug parameter `input_1`
  (not Premiere's `fillcolor`); the walker now reads any RGB-valued
  generator parameter. Live loop closed on 19.1.3.7: the E110 fade-to-white
  turnover conformed, imported, rendered, re-exported, and verified
  `pass: true` with both colours (white, and 128/64/191) compared — the
  writer echoing the authored `EffectFiltersBA` is a second witness to the
  blob layout. A black-for-white export fails as `generator-colour`.

### Measured (filed in api-limitations)

- The XML importer ignores a `Dip to Color Dissolve`'s colour parameter:
  white and red imported as byte-identical default blobs and rendered inert.
  The dip colour stays GUI-only on 19.1.3.7 (E111).

## What's New in v2.168.0 — E110: Solid Color has a colour — fade-to-white and colour mattes author

The one thing the black-leg machinery could not do was be anything but
black: the Solid Color generator's colour lives in an `EffectFiltersBA` blob
nobody had ground truth for, and Resolve 19 exposes the colour only in its
UI. Resolve's own FCP7 XML importer turned out to be the capture route.

### Added

- **`drt.assemble` generator elements take `color`** (`{r,g,b[,a]}` as 0..1
  floats or 0..255 ints): `placeGenerator` authors the 55-byte
  `EffectFiltersBA` byte-for-byte as Resolve's writer emits it (header, fixed
  prefix, flag, big-endian uint16 ARGB, pad, a second black record).
  `solidColorEffectBlob` / `decodeSolidColorEffectBlob` are exported.
- **XMEML generatoritem `fillcolor` carries through** `parse_interchange`
  (Premiere Color Matte and Resolve's own export alike) as `color` on the BL
  leg, and the bridge authors the coloured generator — so a turnover's
  fade-to-white or colour matte conforms instead of turning black.

### Measured (filed in api-limitations)

- Resolve's FCP7 importer honours `fillcolor`: red and blue generators
  rendered Y81 U90 V240 and Y41 U240 V110 (BT.601 limited-range exact) and
  `EXPORT_FCP_7_XML` writes the colour back. Render-verified end to end from
  an offline-authored `.drt`: a clip → white fade climbs 124 → 154 → 182 →
  209 → 232 → 234 across its 24-frame window, the white plateau reads
  234/128/128, and a custom (128, 64, 191) matte lands at Y100 U174 V147
  against a BT.601 expectation of 99.8 / 174.3 / 147.0.

## What's New in v2.167.0 — E109: flat AAF sound slots keep their lanes; AAF audio cross-fades render

An Avid turnover carries dialog, music and effects as SEPARATE flat sound
MobSlots. The AAF walker labelled every flat slot `A` (only `NestedScope`
layers were numbered), so a dialog lane and a music bed collided on A1 and
the bridge refused the whole turnover ("audio events overlap on audio track
1 — one track cannot hold both"). The sound `Transition` between the dialog
clips parsed fine; the lane collapse was the block.

### Fixed

- **Flat AAF slots number per media kind in slot order** (`A`, `A2`, `A3` …
  / `V`, `V2` …). The first slot of a kind keeps the bare letter; `NestedScope`
  layers keep their own layer numbering. Render-measured on 19.1.3.7: an AAF
  with a dialog lane (−21 dBFS tone → 24f `MonoAudioDissolve` → −41 dBFS
  tone) over a quiet music bed on its own slot conforms, imports, and renders
  the cross-fade −26.0 → −29.3 → −32.5 → −37.5 → −41.6 dBFS across exactly its
  window, with the second lane audibly present (−41.6 vs −47.1 for one lane).
- **Channel legs still place once.** Resolve's own AAF export writes one slot
  per audio channel with identical legs; the bridge's merge (and
  `verify_roundtrip`'s dedupe) now key on source/range rather than the lane,
  so channel legs of one clip merge while a different bed on its own lane
  never does.

## What's New in v2.166.0 — E108: XMEML audio cross-fades conform and render

The XMEML walker only looked at `<transitionitem>`s on VIDEO tracks, so an
audio cross-fade vanished at parse and never reached the bridge that
authors them (OTIO carried its audio Transition all along). Every audio
track also walked as `A`, collapsing multi-track audio onto one lane where
OTIO and AAF number `A`, `A2`, `A3` …

### Fixed

- **XMEML audio-track transitionitems attach** to the incoming audio event
  exactly as video's do (one shared attach pass), and the bridge authors the
  cross-fade. Render-measured on 19.1.3.7 against a control timeline: a 24f
  `Cross Fade (+3dB)` from a −21 dBFS tone to a −41 dBFS tone ramps
  −27.1 → −30.6 → −34.2 → −40.2 → −47.1 dBFS across the window in 0.25 s
  RMS steps where the control steps hard at the cut.
- **XMEML audio tracks number like OTIO/AAF** (`A`, `A2`, …), so the
  bridge places each lane on its own audio track instead of stacking
  everything on A1.
- **`media_pool.capture_media_template` saves the current project before
  switching to its scratch project.** `CreateProject` replaces the current
  project, and an unsaved one is simply gone afterwards — the restore cannot
  `LoadProject` a name that existed only in memory (measured: a freshly
  created project with two imported timelines vanished, and Resolve fell
  back to a transient "Untitled Project"). A failed save refuses the capture.

### Measured (filed in api-limitations)

- `ProjectManager.CreateProject` while an UNSAVED project is current
  discards that project without error.

## What's New in v2.165.0 — E107: frame QC reads Resolve's own XML and samples clear of transitions

The lineage store's `ingest_xml` was measured against a verbatim
`EXPORT_FCP_7_XML` of a fade-in → clip → centered dissolve → clip → fade-out
timeline (rendered and luma-verified: 18→123 over the fade-in, a blend over
96–119, 230→21 over the fade-out). Every transition-adjacent cut landed at
record `-1` with no oracle frame — the reference sampled at frame 0 read
black and the conform side could not be sampled at all, so each read as a
false yellow turnover. Two laws of Resolve's writer explain it.

### Fixed

- **`-1` clip edges resolve to junctions in the lineage ingest** (the E105
  law the editorial parser already knew), and with a record-order cursor:
  under three centered transitions two equal-length clips both carry
  `-1/-1` edges, and the first junction pair that fits placed BOTH clips at
  the same position — in the editorial parser too. Both parsers now walk
  clips with a cursor; the verbatim export is a permanent fixture.
- **Resolve writes no `pproTicksIn`.** The oracle insisted on Premiere ticks
  and derived no source frame for any cut of a Resolve export. When ticks
  are absent, `<in>` (record-aligned by the `-1` resolution) is the oracle
  frame; the ingest reports `ticksAbsent`, `resolvedEdges`, `unresolvedEdges`.
- **Frame QC samples clear of transition windows.** Each cut records the
  windows its edges sit in (`cuts.transition`, plus `cuts.speed`; existing
  sidecars migrate in place) and `qc` compares the first frame past the
  incoming window and before the outgoing one, advancing the source frame
  at the cut's speed (reverse walks backward). Measured on the render:
  structure 0.982 at the dissolve junction → 0.999 clear of it; the result
  carries `sample_note` saying where it looked, and a cut swallowed whole by
  its windows samples its midpoint and says so.

### Measured (filed in api-limitations)

- `EXPORT_FCP_7_XML` writes no `pproTicksIn`/`pproTicksOut`, `-1` on every
  transition-adjacent edge (junction), `center` alignment for every
  centered-authored dissolve and fade, and Solid Color generatoritems for
  black legs. A flat/untextured frame (a white card) is `UNREADABLE` to the
  brightness-robust classifier — an honest review, not a false verdict.

## What's New in v2.164.0 — E106: the changelist sees junctions

`editorial.turnover_changelist` diffed clips and was blind to everything
that happens *between* them. Measured on a faded, dissolved, retimed EDL
pair: a 24→12-frame dissolve change reported nothing, both dropped fades
read as "BL gone", and the zero-length CMX carrier line of a dissolve's
outgoing side read as "B002 gone". The timing guards paired first-row-wins,
so an identical cut with one A2 leg dropped flagged a FALSE flattened
retime and never flagged the audio drop (`track === 'A'` missed `A2`).

### Fixed

- **The changelist diffs junctions.** `transition_added` /
  `transition_dropped` / `transition_changed` entries name the outgoing and
  incoming sources, classify fade in/out vs dissolve, and carry the span and
  duration/type/pre-roll deltas — a dissolve reshaped from centered to
  start-at-cut is a change even when both clips stayed put. Spans derive
  exactly as the bridge places them (CMX start-at-cut, OTIO `in_offset`,
  XMEML/PrProj `recStart`, AAF overlap start).
- **Carrier lines and fade legs never read as sources.** Zero-length events
  (CMX outgoing marker lines, the synthesized BL fade slugs) and the black
  legs a transition references fold into the junction diff; the changelist
  reports how many in `carriersFolded`. A cut diffed against itself is
  silent on every axis.
- **`timingGuards` pairs instance-to-instance.** Same track+source, closest
  record position, consumed once — the pairing the changelist already used —
  so a source cut twice at two speeds no longer cross-compares. Flags carry
  `recIn`. Dropped-audio detection reads any `A`-track (`A`, `A2`, …), and a
  lost fade or dissolve is now a timing lie (`transition_dropped`).

### Added

- `editorial.mjs` exports `transitionSpan(event)` and
  `listTransitions(events)` — the junction model shared by the changelist
  and the guards.

## What's New in v2.163.0 — E105: QC through every export format

One faded, dissolved, retimed conform exported from Resolve three ways — OTIO,
FCP7 XML, and CMX EDL — and pushed through `editorial.verify_roundtrip`. All
three now close `pass: true`; getting there measured four laws of Resolve's own
writers and fixed the parsers to match.

### Fixed

- **Every FCP7-XML retime read as a FREEZE**: Resolve's timeremap effect
  writes `speed` 50 followed by `variablespeed` 0, and a loose `/speed/`
  parameter match let the second overwrite the first. Exact parameter
  matching now, with the `reverse` flag read alongside.
- **FCP7 `-1` clip edges** (transition-adjacent) are resolved to the
  transition's junction — the span center for `center` alignment — with the
  clip's `in` advanced by the overlap offset so source stays record-aligned;
  `out - in` is the record duration even under a retime. Solid Color
  `generatoritem`s walk as black legs, and fade transitions attach to the
  picture rather than the black.
- **CMX EDL exports name every file source reel `AX`** with the real names in
  `* FROM/TO CLIP NAME` comments; `parseEDL` now applies them (TO = incoming,
  FROM = outgoing of a dissolve pair), keeping specific reels intact.
- **`timeline.export_timeline_checked` refuses unresolved export constants
  loudly.** A made-up `EXPORT_CMX_3600` reached `Timeline.Export` as a string
  and came back as a bare `success: false`; the real constant is `EXPORT_EDL`,
  and the refusal now lists the vocabulary.

### Added

- `verify_roundtrip` reports `audioNotInExport` when the export carries no
  audio at all (Resolve's EDL writer is video-only — measured) instead of
  failing, mirroring `markersNotInExport`.

### Measured (filed in api-limitations)

- `EXPORT_EDL` is video-only, writes reel `AX` + clip-name comments, places
  dissolve junctions at the CMX start-at-cut position, and writes the BL
  fades its own importer drops.

## What's New in v2.162.0 — freeze parity: Avid 0% motion effects are freezes

### Fixed

- **An Avid freeze frame silently read as a 100% clip.** A motion effect at
  0% (`PARAM_SPEED_RATIO_U 0.0`, or a flat speed map at 0) fell into the AAF
  walker's "no play rate recoverable" branch, and the freeze vanished. An
  explicit zero now reports `speed: 0, freeze: true`, and the bridge authors
  the real freeze — completing freeze parity across all five ingest formats
  (EDL `M2 000.0`, OTIO `FreezeFrame`, XMEML `timeremap` 0, PrProj
  `InPoint == OutPoint`, and now AAF).

## What's New in v2.161.0 — OTIO freeze frames close the loop

### Fixed

- **OTIO `FreezeFrame` effects were silently lost at parse**: the reader only
  looked at `time_scalar`, which FreezeFrame writers commonly omit, so a
  turnover freeze read as a plain 100% clip. The schema itself now means
  speed 0, and the bridge authors the real freeze `Sm2TimeMap`.

### Added

- The OTIO writer emits `FreezeFrame.1` (time_scalar 0) for zero-speed
  events — OTIO's own schema for it, readable by both conventions.

### Measured

- **Resolve's `EXPORT_OTIO` writes an authored freeze back as
  `FreezeFrame.1` with `time_scalar: 0`** — the freeze round-trips
  losslessly, and `verify_roundtrip` now catches a freeze flattened to 100%
  as retime drift.

## What's New in v2.160.0 — write-side span fidelity; the flat DRT target stops lying about black

### Fixed

- **`eventsToOTIO` forced every transition to centered**, so a start-at-cut
  fade-in re-written to OTIO demanded incoming pre-roll the source never
  needed — and the round-trip dropped the fade as handle starvation. The
  writer now carries the source event's actual alignment (start-at-cut,
  `inOffset`, or derived from `recStart`).
- **The flat DRT target omitted nothing and authored a bogus `BL` offline
  clip** for black legs. BL legs are now omitted — an empty track region
  renders the same black without the media-offline lie — and the `drt`
  result reports `blackLegsOmitted`.

## What's New in v2.159.0 — the EDL writer learns transitions

### Fixed

- **`convert_to_interchange`'s EDL target silently dropped every
  transition** (the OTIO target carried them since day one). The writer now
  emits the CMX pairs — a zero-length outgoing marker line plus the `D` line
  with its duration — with the `BL` reel on the black side of fades, and a
  zero-length fade-out carrier receives the fade's record extent per the
  CMX convention. Round-trip proven: written EDLs parse back to fully
  authored specs (dissolves, fade-in, fade-out; nothing dropped). Reel
  names are basename-stripped before sanitizing, so path-style sources
  produce clean reels.

## What's New in v2.158.0 — E100: the kitchen-sink certification

### Verified (one turnover, everything at once)

- A single OTIO turnover carrying a fade-in, a V2 stack, a centered
  dissolve, a 50% retime, a retime-adjacent fade-out, two audio legs, two
  track markers, and a clip marker conformed, imported, and **rendered
  correct in all 32 measured windows** — including the previously unmeasured
  interactions (the boundary shift extending a retimed cut into its
  fade-out; an upper-track stack compositing over the fade region). The
  round-trip QC closed `pass: true` against Resolve's own re-export, and
  the fixture is now a permanent offline test.

### Fixed

- `verify_roundtrip` compares sources by **basename**: an OTIO turnover
  names sources by `target_url` path while Resolve's re-export uses the file
  basename — the same file read as six spurious source mismatches.

### Measured

- **Fairlight level law**: the template's A1 strip plays at source level
  while the added mono strips (A2–A16) play 3 dB down per channel (center
  pan law). Both render; it is mixer semantics, not a placement failure.

## What's New in v2.157.0 — the conform manifest learns fades too

### Fixed

- **`editorial.conform_manifest` failed every conformable fade EDL**: BL
  legs failed `source_resolved` ("no resolved path") and the fade-in failed
  `handles` — but BL is the EDL's built-in black (it conforms as a Solid
  Color generator, no source needed), and a fade from black needs no handle
  media at all (the boundary shift trims the picture head inside its own
  material). A fade-out's real requirement — outgoing tail on the PICTURE
  source — now lands on the right source: a starved tail still fails,
  named precisely.

## What's New in v2.156.1 — docs catch up with the fade + QC arc

### Documentation

- `docs/guides/native-drt-authoring.md` learns the v2.148–2.156 arc: the
  A1–A16 audio ceiling, the fade capability row and the fade/AAF-overlap
  laws, the `blackLegs` ledger field, and the full `verify_roundtrip`
  surface (markers, fades, retimes, audio) in the delivery checklist.
- The Native .drt Authoring and Headless Edit Loop guides are now linked
  from both READMEs' guide tables — both were orphaned.

## What's New in v2.156.0 — the QC loop learns audio; the verify surface is complete

### Added

- **`editorial.verify_roundtrip` is audio-aware.** Declared audio events
  compare pairwise through the same machinery as video — record, source,
  retime, and fade-window excusal — with audio mismatches tagged
  `trackType: 'audio'`, AAF channel legs deduped, and BL/silence legs merged
  out. A video-only turnover whose re-export carries audio (the A1
  convenience mirror this bridge authors) reports `audio.compared: false`
  informationally instead of failing. Live loop verified: an explicit A2 leg
  round-trips through `EXPORT_OTIO` at exact geometry.
- With markers (v2.147), fades (v2.153), retimes (v2.154), and now audio,
  the round-trip QC surface covers every structure the conform bridge
  authors.

## What's New in v2.155.0 — Premiere transitions land properly: centered spans and fades

### Fixed

- **Every centered Premiere transition was silently dropped**: the .prproj
  reader attached transitions only to clips starting exactly at the span
  start — the CMX start-at-cut shape — so a transition centered on its cut
  (Premiere's default) matched nothing and vanished. The incoming clip is
  now found anywhere inside the span, and `recStart` carries Premiere's
  explicit record span to the bridge so the editor's actual alignment is
  reproduced.

### Added

- **.prproj fades**: an edge span with a missing neighbor synthesizes BL
  legs through the same black machinery as EDL/OTIO/XMEML/AAF — all five
  ingest formats now author fades. Audio transition candidates honor
  `recStart` too. The emitted spec shapes are the render-verified classes
  from v2.150–152.

## What's New in v2.154.0 — the QC loop learns retimes

### Added

- **`editorial.verify_roundtrip` is retime-aware.** A conform that lost its
  retime is a wrong timeline that record/source geometry alone cannot catch
  — the record extent is unchanged, only the playback rate. Speed and
  reverse now compare pairwise (`kind: 'retime'` on drift).

### Measured (good news, for once)

- **`EXPORT_OTIO` carries an authored `Sm2TimeMap` back as
  `LinearTimeWarp`**: a 50% M2 retime conformed offline reads back out of
  Resolve's OTIO export as `time_scalar: 0.5`. The retime loop closes
  losslessly through OTIO — live loop verified both ways (pass on the true
  export, `retime` drift on a speed-stripped one).

## What's New in v2.153.0 — the QC loop learns fades

### Added

- **`editorial.verify_roundtrip` is fade-aware.** A correct fade conform
  used to fail QC three ways: the re-export's Solid Color legs mismatched
  the EDL's BL reels, the leg counts differed, and the fade boundary-shift
  moved picture edges by half the transition. Now BL/Solid-Color legs
  canonicalize to BLACK and drop out of the pairwise compare (counted in
  `blackSegments`), picture edges inside an input junction's fade window are
  excused into `fadeReshapedBoundaries` — reported, never silently absorbed
  — and the per-source TC offset is fitted net of the record shift so a
  source cut both plain and faded doesn't read as source-frames drift.
  Live loop verified: EDL fades → conform → import → OTIO re-export →
  `pass: true` with the reshape named. Beyond-window shifts and shifts at
  junction-free edges still fail as real record drift.

## What's New in v2.152.0 — AAF dissolves conform at last, and AAF fades join the family

### Fixed

- **No AAF dissolve could ever conform through `assemble_from_interchange`**:
  an AAF Transition consumes record time, so the walker (correctly) emits the
  incoming clip overlapping the outgoing — and the bridge's overlap gate
  threw on exactly that shape. A reconciliation pre-pass now trims the
  outgoing's tail to the overlap start; the boundary shift then re-extends it
  to the cut point, which is the AAF notional-cut (`CutPoint`) semantics
  exactly. Render-verified: the dissolve blends through the 181.8 midpoint
  fingerprint.

### Added

- **AAF fades**: the walker synthesizes BL pseudo-events at filler-adjacent
  and sequence-edge Transitions, completing fade parity across all four
  formats (EDL v2.150, OTIO/XMEML v2.151, AAF now). The head-transition
  "clamp" case is reinterpreted as what it is — a fade-in from black.
  Full triple render-verified: fade-in 18→123, dissolve-to-white through the
  midpoint, fade-out 230→21.
- A pyaaf2-authored AAF fixture test exercises the real walker end to end
  (no stubs), skipped only where pyaaf2 is unavailable.

## What's New in v2.151.0 — fade parity: OTIO and XMEML fades author too

### Added

- **OTIO and XMEML fades route through the black machinery** shipped for EDL
  BL legs in v2.150.0. OTIO: a Transition adjacent to a Gap (or the track
  edge) is a fade — gap-then-Transition-then-Clip fades in, Transition-then-
  Gap (or Transition as the last child) fades out. XMEML: an edge
  transitionitem whose span has no outgoing clip fades in, no incoming clip
  fades out. All synthesize BL pseudo-events; the bridge materializes a
  zero-length black leg to cover its side of the span whenever the boundary
  shift alone won't grow it (empty track renders black, so the growth is
  render-neutral). Live OTIO render: fade-in luma ramps 18→123, the centered
  fade-out 124→18 — identical geometry from all three parsers.

## What's New in v2.150.0 — fades conform: BL legs author, and Resolve's own EDL importer drops them

### Added

- **EDL fades author end-to-end** in `drt.assemble_from_interchange`: BL
  (black) legs become Solid Color generator elements and the fades real
  clip-to-generator dissolves. A CMX fade-in's zero-length BL slug grows
  through the boundary-shift machinery (single-sided transitions refuse to
  import — measured); the picture trims its head with source staying
  record-aligned. Render-proven: luma ramps 18→123 across a 24-frame
  fade-in and 123→16 across the fade-out, with the black tail holding.
  Audio BL fades (to silence) drop with a stated reason — there is no
  silence source to cross-fade against.
- Generator elements now insert into the track in **chronological item
  order** (junction detection reads listed adjacency), and an edge-aligned
  span whose leg is shorter than its boundary shift drops with a reason
  instead of authoring a broken geometry.

### Measured (new Resolve bug, filed in api-limitations)

- **Resolve's own EDL importer silently drops BL dissolves**: the fade-in
  vanishes wholesale (frame 0 renders full-bright) and a fade-out leaves a
  hard cut into the Solid Color generator it creates for the BL slug. A
  single-sided transition element refuses to import entirely.

## What's New in v2.149.0 — subtitle render truth: ExportSubtitle lies on 19.x

### Measured (new Resolve bug, filed in api-limitations)

- **`SetRenderSettings` subtitle keys are accepted-and-inert on 19.x**: with
  authored subtitle cues readback-verified and the track enabled,
  `ExportSubtitle: true` + every `SubtitleFormat` mode (`BurnIn`,
  `SeparateFile`, `EmbeddedCaptions`) returns True — and the renders carry no
  burned-in pixels, no sidecar file, and no caption stream. The keys are
  documented in the Resolve 21 API reference. Quirk: `ExportSubtitle` alone
  returns False; the pair returns True.

### Added

- **`render.set_settings` warns on pre-21 hosts** when the subtitle-delivery
  keys are set, naming the measured inertness and the verification steps —
  the accepted-then-ignored warning pattern that already covers
  `AddFrameHandles` under `UseFullExtents`.

## What's New in v2.148.0 — the audio ceiling doubles: A1–A16

### Changed

- **Offline audio placement now reaches A16** (was A8). The r19 media
  template was re-captured live with 16 mono audio tracks — valid Fairlight
  strips included, because a cloned track without a strip renders silent
  (the measured strip law). A9 and A16 placements render-verified on
  Studio 19.1.3.7 at the same -24.1 dB mono-strip level as A1, with the
  gaps digitally silent at the sample level. `drt.assemble` cuts refuse
  at A17 with the re-capture guidance.

## What's New in v2.147.0 — the round-trip QC loop learns markers

### Added

- **`editorial.verify_roundtrip` is marker-aware**: timeline markers compare
  through the loop (min-anchored frames within tolerance, names when both
  sides carry them). A re-export with NO markers while the turnover has them
  raises the `markersNotInExport` honesty flag without failing the pass — a
  missing exporter capability is not a conform drift.

### Measured (new Resolve bug, filed in api-limitations)

- **`EXPORT_OTIO` drops timeline markers wholesale**: two markers readable
  through the marker API, zero in the exported .otio — while Resolve's own
  OTIO *importer* reads Marker objects fine. Marker-fidelity checks must go
  through the marker API, never an OTIO re-export.

## What's New in v2.146.0 — bins, and the folder registry law

### Added

- **`assemble_project` `timelines[].folder`** — place reels in named Master
  bins (entries sharing a name share the bin; media stays in Master).
  Live-proven: a Reels bin holding both timeline clips, both timelines
  materialized, and a binned reel rendering its exact content.

### Measured (the folder registry law)

- **The parent folder's FieldsBlob is the subfolder registry.** Media and
  timeline children are discovered by scan; subfolders are NOT — an
  unregistered bin directory imports as nothing and silently takes its
  clips' timelines with it. The registry's inner format is byte-verified
  against the template harvest (a keyed child-id dict in a protobuf wrapper,
  zstd-framed). Natively created Resolve projects carry an EMPTY folder blob
  when binless — the assembly templates now match that convention
  (render-verified as a no-op).

## What's New in v2.145.2 — launcher metadata before dependencies

### Fixed

- **`davinci-resolve-advanced-mcp --help`/`--version` now work in fresh
  source checkouts** (before `npm install`) — adapted from
  [PR #178](https://github.com/samuelgursky/davinci-resolve-mcp/pull/178) by
  @Rohitkanithi: metadata flags are handled before the stdio server import
  (and before the Node-floor refusal — help is harmless on any Node), where
  previously even `--help` died with `ERR_MODULE_NOT_FOUND`.
- **The installer banner's tool counts were stale** (32/329 vs the real
  36/353) — fixed and wired into the `test_doc_tool_counts` drift guard so
  the banner can never drift independently again.

## What's New in v2.145.1 — bridge config override, honored end to end

### Fixed

- **The free-edition bridge installer now honors
  `DAVINCI_RESOLVE_BRIDGE_CONFIG`** — adapted from
  [PR #177](https://github.com/samuelgursky/davinci-resolve-mcp/pull/177) by
  @altiss. The bridge client already resolved the override, but the installer
  always wrote and embedded the fixed default path, so a client configured
  with an override could look in one place while the in-app bridge was
  installed with another — both sides "successfully" installed yet never
  sharing a token. The installer resolves the effective path at call time
  with the client's exact semantics (env wins, `~` expands, default
  otherwise) across create, report, runtime copy, and launcher embed. One
  correction on top of the PR: the step-4 probe guidance keeps pointing at
  the FIXED default directory — the probe runs inside Resolve, which never
  inherits the shell's environment, so it always writes there.

## What's New in v2.145.0 — whole projects, assembled offline

### Added

- **`drt.assemble_project`: multi-timeline .drp archives** — two or more
  full assemble specs merge into one project file (reel-per-timeline conform
  packages). Import as a project (`safe_project_import`); pull singles with
  `extract_from_drp`. Live-proven: a two-reel .drp imported with both
  timelines materialized and the second reel rendering its exact content.

### The five merge laws (each found by a failed import)

1. Template-fixed cluster identities collide — the pool clip, its version
   table, container, sequence and track ids must remap; media pool element
   ids are the deliberate exception (fixed by capture, so identical sources
   dedup and MediaRefs keep pointing at the survivor).
2. Keyed FieldsBlobs carry uuids as UTF-16 (`ActiveVer`, `SeqRef`) —
   invisible to plaintext remaps; patched through the keyed codec.
3. `project.xml`'s `<TimelineHandleVec>` is THE timeline registry: a pool
   clip absent from it imports as pool furniture and never materializes.
4. Folder children live INSIDE `<MediaVec>` — an element appended after its
   close parses fine and is silently invisible.
5. Media pool tags are `Sm2MpVideoClip`/`Sm2MpAudioClip`, not `Sm2MpMedia`
   — an over-narrow tag set let media ids into the remap and every
   `MediaRef` in the merged reel dangled (whole reel offline).

## What's New in v2.144.0 — turnover clip markers ride the items

### Added

- **OTIO clip markers and FCP7-XMEML clipitem `<marker>`s route to ITEM
  markers** on their cuts through `assemble_from_interchange` (frames
  clip-relative, colors mapped, notes preserved; markers on trimmed-away
  material drop rather than refuse). Track-level markers still author as
  timeline markers. Built on v2.143's `Sm2TiItemLockableBlob` authoring —
  the only .drt carrier for clip markers, since Resolve's own exporter
  drops them.

## What's New in v2.143.0 — item markers, and two refinements

### Added

- **Item-level markers (clip locators) authored offline** — `cuts[].markers`
  (frames item-relative), on video AND explicit-audio items. Found by a raw
  byte-hunt in a live Project.db: item markers ride an
  `Sm2TiItemLockableBlob` in `project.xml`'s LocableBlobSet — the same wire
  codec as timeline markers with the clip's DbId as owner. The kicker, filed
  as a new Resolve bug in api-limitations: **Resolve's own EXPORT_DRT drops
  item-marker blobs entirely** (even after SaveProject), while
  `ImportTimelineFromFile` accepts an authored one — this authoring path is
  the only way a .drt carries clip markers. Live-verified readback on video
  and A3 audio items through the tool layer.
- **AAF `CutPoint` honored** — when an AAF transition names where the
  notional cut sits within the overlap, the boundary shift lands there
  (clamped strictly inside the span per the edge law) instead of centering.

### Changed

- **`fade-to-color` demoted from the transition style set** — on the
  dissolve skeleton it is duration/direction-erratic (a 24f junction
  rendered a ~77 plateau; a 48f one rendered a single black frame then a
  hard cut), and its real parameter blob is unharvestable while the XMEML
  importer stays inert. Turnover Fade-To-Colors now map to `dip`, which is
  duration-stable (clean symmetric valley measured at both 24f and 48f).

## What's New in v2.142.1 — the AAF leg joins the span fix

### Fixed

- **AAF dissolves were misaligned by half their duration**: the AAF walker
  rewinds the incoming clip to the overlap START (the Edit Protocol
  subtraction), so the parsed junction is the overlap's first frame — and the
  old centered placement put half the blend before the overlap even began.
  AAF transitions now carry `alignment: 'start'` through the same
  render-proven span machinery as EDL (v2.142.0): span `[overlapStart,
  overlapStart+dur)`, boundary shifted to the middle — which lands the
  notional cut exactly at the AAF CutPoint default (centered in the overlap).

## What's New in v2.142.0 — transition span fidelity, and the edge law

### Changed (conform fidelity)

- **Transition spans now follow the turnover's actual geometry** instead of
  always centering: EDL dissolves/wipes span `[cut, cut+dur)` (the CMX
  convention), OTIO transitions use their explicit in/out offsets, XMEML
  transitionitems use their own record span, and spec-level
  `transitions[].startFrame` overrides. Handle requirements follow the real
  span — a start-at-cut EDL dissolve needs NO incoming handle and a
  full-duration outgoing tail. Render-verified: the authored EDL dissolve
  blends exactly `[cut, cut+24)` (pure outgoing through cut−1, linear blend,
  midpoint 182), matching Resolve's own EDL importer frame-for-frame.

### Measured (the edge law)

- A transition's rendered span follows `<Start>`/`<Duration>`
  (`AlignmentType` is cosmetic), **but the clip boundary must sit strictly
  inside the span** — an edge-aligned span (Start == the boundary) renders
  inert. That is why Resolve's own EDL importer moves the cut +dur/2 and
  centers; the bridge now reproduces exactly that cut-reshaping. Off-center
  spans render fine (an uneven `[cut−6, cut+18)` span blended linearly
  across its full width).

## What's New in v2.141.0 — OTIO transitions, depth-4, and honest gaps

### Added

- **OTIO `Transition` children parse and author** — they occupy no record
  time (the AAF overlap convention), attach to the incoming clip, and route
  through the same style table as XMEML effectids (`SMPTE_Dissolve` → plain
  dissolve; wipe-named types → the wipe). A Gap breaks the junction.

### Measured

- **Depth-4 nested compounds render** (234 through four levels via the spec
  route) — nesting depth is effectively unbounded on 19.1.3.
- **Record gaps render clean black** (cut 122.9 / gap 16.0 / white 234) —
  sparse turnovers assemble without synthetic filler.

## What's New in v2.140.0 — the transition style registry

### Added

- **Five more transition styles authored offline** — `transitions[].type:
  'dip' | 'additive' | 'fade-to-color' | 'smooth-cut' | 'non-additive'`
  (joining `dissolve` and `wipe`). The registry cracked in one probe:
  `PrettyType` is the style selector — swapped onto the render-verified
  dissolve skeleton, every style renders, each with its own midpoint
  fingerprint on 19.1.3.7 (dip bottoms at pure black 16, additive saturates
  at 233.8, fade-to-color plateaus dark at 77, smooth-cut blends at 179.9,
  non-additive holds the brighter side past the cut). Unknown styles refuse
  (unvetted strings are the measured crasher class).
- **XMEML `<transitionitem>` parsing** — dissolve-family effectids and wipe
  names route to their styles automatically through
  `assemble_from_interchange`; unrecognized effects fall back to a plain
  dissolve rather than dropping (a blend at the right junction beats a hard
  cut).

### Measured and closed (new Resolve bug, filed in api-limitations)

- **Resolve's own FCP7-XMEML importer writes video transitions that render
  INERT** on 19.1.3: the transitionitem lands as a real element that reads
  back through every API, but the outgoing clip plays through the window and
  hard-cuts at its end — measured with both a plain Cross Dissolve and a Dip
  to Color (E66, importSourceClips both ways). EDL-imported transitions
  render fine; the defect is the XMEML path's element construction. Routing
  the same XMEML through `assemble_from_interchange` authors transitions
  that render (E69: the same dip turnover produced the exact 16.0 black
  valley through our route). `docs/reference/api-limitations.md` carries the
  new `bug` entry.

## What's New in v2.139.0 — speed ramps, and the easing crash law

### Added

- **Variable-speed ramps authored offline** (`cuts[].ramp:
  [{durationFrames, speed}, …]` — two or more linear segments from the cut
  head, `srcIn` honored). No harvest was needed: the engine honors
  intermediate keyframes in the same seconds-domain keyed `Sm2TimeMap` the
  constant retimes use. E63/E64 proof on 19.1.3.7: a 50%→100% knee read back
  the exact source window AND rendered the predicted frame cadence (11/23
  doubled frames in the half-speed window, none at full speed; the 2×
  segment moved at 4.3× the 0.5× segment's per-frame motion), with `srcIn`
  landing on the right source frame by luma.

### Measured and closed

- **Eased ramps are a crasher, not a boundary.** A keyframe with
  `interp = 2` crashed Resolve outright on import (E65 — app death, headless
  recovery per doctrine). The builders hardcode `interp = 0`, the test suite
  asserts it, and the guide records the law: linear segments are the
  authorable envelope on 19.1.3.

## What's New in v2.138.0 — wipes join the conform

### Added

- **Wipe transitions authored offline** (`transitions[].type: 'wipe'`;
  EDL `W`-codes route to it automatically through
  `assemble_from_interchange`). Harvested from a live 19.1.3.7 EDL W-code
  import (E61): Resolve stores a wipe as the same Cross Dissolve element
  whose FieldsBlob zlib payload zeroes the style-id field the dissolve
  fills — and its own importer maps EVERY W-code (W001/W002/W005 measured
  identical) to one soft-edge wipe style, so a single style is full parity
  with the host importer. Render-proven both directions: the live wipe's
  midpoint splits spatially (157.2/206.3 left/right vs the dissolve's
  uniform 181.6), the element survives the .drt round-trip bit-exact, and
  the offline-authored wipe through the full EDL → assemble → import →
  render route reproduces the split (158.1/205.0). Audio wipes refuse
  (junctions cross-fade).

## What's New in v2.137.0 — the sweep reaches the database tier

### Fixed

- **Fairlight DB row selection** (adapted the v2.133 container-pin lesson to
  the vendor layer): `readFromDatabase` took the FIRST `Sm2Sequence` row — in
  any project holding a compound clip that can be a compound's embedded
  sequence with no `FLStudioModelBA`, so bus reads failed while the model sat
  in the next row (measured live). Worse, `applyTemplate` wrote its new blob
  into EVERY blob-bearing sequence row, clobbering compound `SeqRef` links
  project-wide. Reads now pick the model-bearing row; writes scope to exactly
  that `Sm2Sequence_id` and refuse ambiguous multi-timeline projects without
  an explicit target. `read_buses_from_db` also stops dumping the ~430KB
  decompressed model into the tool response.
- **`provenance.cdl_diff` silently identity-defaulted array-shaped CDLs**:
  `[r,g,b]` slope/offset/power (the common interchange form) read as unity
  through the `{r,g,b}` accessor, so two different grades diffed as
  saturation-only (measured). Both shapes are accepted now; unrecognizable
  shapes refuse loudly.
- **Node-floor enforcement**: the advanced server refuses to start below
  Node 20.9 with the exact fix named (measured live: a client config's node
  resolved to an nvm v18, where pure-JS tools limp and better-sqlite3 dies
  with a cryptic ABI mismatch). `install.py` now writes an absolute,
  version-checked node path into client configs, and the better-sqlite3
  loader distinguishes "not installed" from "built for a different Node".
- **Windows UTF-8, rounds two and three** — adapted from
  [PR #175](https://github.com/samuelgursky/davinci-resolve-mcp/pull/175) and
  [PR #176](https://github.com/samuelgursky/davinci-resolve-mcp/pull/176) by
  @Chosen-3: the six unencoded call sites in `src/` (brain-edits registry,
  page lock) and `install.py`'s client-config `read_json`/`write_json`. The
  UTF-8 discipline guard now covers `src/` and `install.py` too.

### Verified through the MCP tool layer (E60)

`project_read` (introspect/report/audit/timeline_clips), `offline_ref.list_in_project`,
`color_trace.plan` (6/6 exact-name matches), and both fairlight bus readers,
all against a live scratch project database.

## What's New in v2.136.1 — the changelog catches up

### Fixed

- **README badges and this changelog had silently frozen at v2.108.0** while
  28 releases shipped with notes only on GitHub Releases. All entries
  v2.109.0-v2.136.0 are now ported here verbatim, both README badges (and the
  zh-CN correspondence line) track the released version again, and a new
  drift guard (`tests/test_release_surface_drift.py`) fails the suite if any
  of these surfaces lag a version bump — the release-process mandate is now
  enforceable instead of aspirational.
- **Windows `UnicodeDecodeError` in tests/scripts** — adapted from
  [PR #174](https://github.com/samuelgursky/davinci-resolve-mcp/pull/174) by
  @Chosen-3: 151 `open()`/`read_text()`/`write_text()` call sites across 47
  files gained `encoding="utf-8"` (locale-encoding fallback crashes on
  cp1252 the moment a read target holds non-ASCII bytes; binary-mode and
  `PIL.Image.open` sites correctly exempt). A companion AST guard
  (`tests/test_utf8_encoding_discipline.py`) keeps new unencoded text-mode
  calls out of `tests/` and `scripts/` — its first catch was this repo's own
  day-old sync script.

## What's New in v2.136.0 — portable agent assets

Adapted from [PR #173](https://github.com/samuelgursky/davinci-resolve-mcp/pull/173) by @jin386 — the portable `.agents/` layout lands, with the review findings folded in rather than waiting on a revision round.

### What's new

- **`.agents/` is the host-neutral canonical layer**: `.agents/skills` (the skill corpus, now what the `knowledge` MCP tool serves and what Codex reads directly), `.agents/roles` (reviewer bodies), `.agents/hooks` (canonical guard logic with a shared `hook_runtime`).
- **Codex support as contributed**: `.codex/hooks.json` wiring, hook shims, and native agent TOMLs, plus the cross-host portability test suite.
- **Claude Code loses nothing**: `.claude/skills` adapters are content-complete, byte-identical copies — never pointer stubs — so the rich "Apply when…" trigger descriptions, named craft-skill references, and `user-invocable` flags survive verbatim (Claude routes on the frontmatter at selection time). `.claude/agents` keep their frontmatter, including the deliberate `model: opus` pins. `CLAUDE.md` stays intentionally short.
- **Safety kept narrow**: `source_media_guard`'s scratch-exemption prefixes remain `claude-`/`codex-` only — the proposed `agent-` prefix would have exempted any real `agent-*` directory from the source-media deny.
- **Drift cannot land**: `scripts/agent-rules/sync_portable_assets.py` (+`--check`) restores the invariant from either edit point, and `tests/test_portable_asset_parity.py` fails the suite on divergence, missing adapters (the "new skill silently never loads" failure mode), lost frontmatter pins, or widened scratch prefixes.

Suites: Node 853, Python 3123 + 845 subtests (portability + parity families added).

## What's New in v2.135.0 — audio.trim never trimmed

The E59 protocol-layer sweep — the v2.133.0 smoke-test harness pointed at the *other* 16 advanced tools — found one real silent lie and confirmed the rest of the surface healthy.

### Fixed

**`audio.trim` never trimmed.** Two stacked failures, both invisible to success-shaped output: the non-strict schema silently stripped mistyped window keys (so `{start, duration}` copied the whole file and reported success), and the tool's own advertised `durationFrames` was never in the vendored module's vocabulary (`{startTime, endTime, duration}` in seconds) — even a correct call returned the full file as a "trim". Schemas across the audio tool are now `.strict()` (unknown keys refuse; extra ffmpeg knobs belong in `opts`), `durationFrames` is required (a windowless trim is a no-op copy wearing a trim's name — use `convert`), and a new optional `fps` (default 24) converts it to seconds. Live-verified through the MCP layer: `durationFrames: 24` → exactly 1.000 s of output.

### Swept clean

All 18 dispatchers refuse unknown actions with structured errors; offline happy paths verified for drp, drx, fusion, audio_plan, pipeline, editorial, conform, media, deliverable, and capabilities.

Suites: Node 853, Python 3111 + 799 subtests.

## What's New in v2.134.1 — the nesting envelope extends

A follow-up measurement to v2.134.0: depth-3 nesting also renders (E58 — a compound inside a compound inside a compound, triple-nested white measured at 234 through the full spec → import → render route on 19.1.3.7). The SequenceSetup fix generalizes; nesting depth is no longer the boundary. Tool doc, guide, and code comments updated from "deeper unverified" to the measured envelope. Suites: Node 852, Python 3111+799.

## What's New in v2.134.0 — freeze frames and nested compounds

Two measured boundaries — both previously closed as "not authorable" — reopened with new harvest angles and closed for real, each render-proven on Studio 19.1.3.7.

### Freeze frames: authored offline (`cuts[].freeze`)

The old finding said no harvest path existed. One did: Resolve's EDL importer honors `M2 <reel> 000.0` motion memos, giving the first real frozen clip whose bytes could be read (E55: reads back source N..N **and** renders frozen — freezedetect-proven, the direction the earlier synthetic always failed in). The real `Sm2TimeMap` is flat in **seconds**, not frames: `YMin = YMax = Y = frozenFrame/fps`, `XMax = 60000` (a sentinel domain), and the clip's `<In>` stays empty. `buildFreezeTimemapKeyed` reproduces the harvest byte-exactly; `cuts[].freeze: true` (or `speed: 0`) authors it, and `assemble_from_interchange` now **authors** zero-speed events (EDL M2 freezes, zero-speed warps) instead of flattening them with a reason. Proof: an offline-authored freeze at a *different* source frame holds luma 125.09 for exactly 2.000 s, then the following cut resumes motion.

### Nested compounds: depth-2 black solved (`compounds[].compounds`)

`Timeline.CreateCompoundClip` works on 19.1.3, so a real doubly nested compound was made live and its archive diffed against the synthetic one that rendered black. Exactly one delta mattered: a Resolve-made compound's embedded pool `Sm2Sequence` FieldsBlob carries a **`SequenceSetup`** key (a 347-byte constant project-format blob) the donor template lacked. With it added, doubly nested synthetic content renders — bisect confirmed `SequenceSetup` alone flips it (E56), and the full tool-layer route proves it end to end (E57: white 234 through two nesting levels with flanking cuts intact). `spec.compounds` now nests recursively; depth-2 playback is render-verified, deeper composes structurally but is unverified.

### Verification

- Node (vendor + server): 852 passed (5 new tests incl. a byte-exact freeze-harvest fixture and a SequenceSetup template guard)
- Python: 3111 passed + 799 subtests
- Live: E55 harvests, E56 freeze + depth-2 bisect renders, E57 nested-spec render — all measured by frame luma / freezedetect

## What's New in v2.133.0 — the tool layer meets its own surface

The first end-to-end pass of the entire v2.106–v2.132 native-DRT authoring surface **through the MCP protocol layer** (every earlier proof drove the modules directly). A kitchen-sink spec — media cuts, cross-dissolve, 0.5x retime, V2 stacking, explicit audio placement, a compound clip, markers, and SRT subtitles in ONE assemble — was authored offline, imported, read back, and render-verified on Studio 19.1.3.7 (frame luma 122.9 / 181.6 mid-dissolve / 234 / 125.8 retime / 125.5 compound-inner; tone at the mono-strip -24.1 dB, then silence). The smoke test caught three real defects; all are fixed and regression-tested.

### Fixed

- **Subtitles (and marker ownership) vanished when compounds were in the spec.** Both placement steps ran after compound insertion but still targeted the first name-sorted `SeqContainer` — and a compound's inner container matches that pattern. Measured live: the imported timeline had no subtitle track; the cues sat inside the compound. The parent container id is now pinned once, before any compound exists, and threaded through subtitle placement and the marker blob's owner.
- **`editorial.verify_roundtrip` could not close an EDL loop.** The zero-duration outgoing dissolve leg was paired as a real event (count mismatch), and EDL reel names (`CUTSRC`) had no way to match the re-export's file basenames (`cut_src`). Zero-length events are dropped, and a new `sourceMap` parameter — the same map that drove the assemble — derives the reel→basename aliases. EDL → assemble → import → OTIO-export → verify now passes with fitted per-source offsets.
- **`assemble_from_interchange` result note contradicted itself**, appending the stale pre-v2.111 "transitions become cuts" text after the authored-ledger sentence.
- **Headless recovery (#172):** a `-nogui` boot that never becomes scriptable still holds the one-per-machine singleton, wedging the GUI too. `resolve_headless.py start` now kills the instance it spawned when its readiness check fails; `stop --force` escalates TERM→KILL for an unanswering instance (unclean — expect project locks and a slow next boot); the headless-edit-loop guide names the precondition and a 30-second preflight.

### Verification

- Python: 3111 passed + 799 subtests (6 new recovery-path tests)
- Node (vendor + server): 847 passed (2 new regression tests)
- Live: kitchen-sink render probe + EDL round-trip pass on 19.1.3.7

## What's New in v2.132.1 — the nesting boundary

Knowledge release. **Depth-2 compound nesting renders black**: a compound placed inside another compound's inner container composes structurally — imports fully linked, reads back — but the doubly nested content renders black (the readback-blind class again). Depth-1, multiple parallel compounds per archive, remains the render-verified envelope; the tool doc now states the boundary.

Also corrected during cleanup: the crash-window "phantom projects" never existed — a project created moments before a Resolve crash dies with the instance (no DB row, no folder), and `DeleteProject` returning `False` afterwards means *nothing to delete*. Lesson recorded: re-list after a crash before diagnosing project state.

Suites: Node 845 pass / 0 fail; Python 3105 passed + 799 subtests.

## What's New in v2.132.0 — multiple compounds compose

### The one-per-archive restriction falls

Three separate dangling references each hard-crash Resolve's importer — mapped one crash at a time, then confirmed with an all-encodings reference sweep:

1. the pool element's `<MpFolder>` (v2.131)
2. the embedded sequence blob's keyed **`SeqRef`** — it names the inner *container's* uuid, patched through the keyed-dict codec
3. the embedded sequence's **`<Parent>`** — pointing back at the compound's own pool id

With all three rewired, every cluster identity freshens safely and **multiple compounds compose in one archive**. Also fixed en route: container listing is name-sorted, so an inner container could alphabetically precede the parent and swallow the next compound's item — the parent is now pinned explicitly.

**Render proof:** parent cut 124.5 → CMP_A's inner white 234 → CMP_B's inner cut 125.3 — two offline-authored nested timelines playing back to back on 19.1.3.

Suites: Node 845 pass / 0 fail; Python 3105 passed + 799 subtests.

## What's New in v2.131.0 — compound clips authored offline

### Nested timelines, fully offline

`drt.assemble` gains `spec.compounds`: author a compound clip — a nested timeline with its own inner edit — entirely offline, and it **renders** after import.

**Render proof (fresh project, 19.1.3):** parent cut (124.5) → the compound's inner cut at source offset 96 (125.3) → the compound's inner white (234). An offline-authored nested edit, playing.

**Two crash laws paid for the summit** (Resolve died twice mapping them):
- The compound cluster's identities ride **verbatim** — the embedded `Sm2Sequence` FieldsBlob encodes them, and freshening the XML ids around the unchanged blob crashes the importer outright. Hence: one compound per archive for now.
- A dangling `<MpFolder>` reference in the pool element also crashes the importer — it's rewired to the target pool's folder.

Inner content uses the ordinary cuts machinery on the inner container (origin frame 0), cloning the sources' captured native clips — `cut-media` now supports donor-less tracks when every cut carries one.

Suites: Node 845 pass / 0 fail; Python 3105 passed + 799 subtests.

## What's New in v2.130.0 — compound clips survive extraction

### The hollow-compound bug

A compound clip in a `.drp` is a pool `Sm2MpCompoundClip` embedding a full `Sm2Sequence` — whose actual tracks live in their **own SeqContainer**. The extraction recipe kept only the target timeline's container, so any timeline containing a compound extracted into a `.drt` whose compound imported, read back… and was **hollow**.

`extract_from_drp` now walks the kept container's `MediaRef`s → compound pool elements → embedded sequence ids → keeps the inner containers too, recursively (compounds nest).

**Live proof:** the fixed extraction imports 3/3 linked with the compound intact, and the archive **renders the compound's inner content** (cut 125.3 → white 234, audio −21.1 dB) — compound clips fully survive the `.drt` route on 19.1.3.

Also banked: the full `.drp` anatomy of compounds (embedded sequence identity, Fairlight blob, the hidden `000_Archive` pool location, the generic item blob) — the map for offline compound *authoring* later.

Suites: Node 844 pass / 0 fail; Python 3105 passed + 799 subtests.

## What's New in v2.129.0 — sidecar SRT in the conform route

Turnover packages usually ship a sidecar `.srt` next to the edit. `assemble_from_interchange` now takes `subtitlesSrtPath` and authors the cues onto the subtitle track in the same call — EDL/OTIO/AAF/XML/prproj in, picture + audio + subtitles out.

Suites: Node 843 pass / 0 fail; Python 3105 passed + 799 subtests.

## What's New in v2.128.0 — subtitles authored; track matrix complete

### The last track type falls

Subtitles turn out to be the **simplest item in the whole schema**: a plain `Sm2TiGenerator` with `PrettyType Subtitle` and the cue text in `<Name>` — no blobs at all, on a Type-2 track. No Fusion comp means the byte-keyed cache law doesn't apply, and the payload is API-visible after import.

`drt.assemble` gains `spec.subtitles` (frame-addressed cues) and `spec.subtitlesSrt` (**raw SRT in, cues out** — composes with `spec.startFrame`). Overlapping cues refuse; the track vec is synthesized from the harvested shape.

**Live proof:** SRT cues plus a spec-level cue import and read back at exact frames with their text. One measured caveat, documented: Resolve reads angle-bracket runs in cue text as SRT formatting markup and strips unknown tags from display (standard subtitle semantics — the authored XML carries them escaped and intact).

With this, the native authoring matrix covers **every track type**: video (cuts, stacking, dissolves, retimes), audio (placements, crossfades), and subtitles — plus markers, start TC, generators, and five interchange formats in.

Suites: Node 842 pass / 0 fail; Python 3105 passed + 799 subtests.

## What's New in v2.127.1 — audio ignores timemaps (measured)

Knowledge release closing the audio-retime question: a 50% keyed `Sm2TimeMap` on an imported **audio** clip *reads back* retimed (source 0..48 over 96 record frames) but **renders at 100%** — pitch and spectrum identical to the 1× reference. The audio engine ignores clip timemaps entirely while readback honors them: the readback/render divergence class, audio edition. Audio retimes remain honestly skipped, with the ledger reason now carrying the measurement.

Suites: Node 841 pass / 0 fail; Python 3105 passed + 799 subtests.

## What's New in v2.127.0 — sequence picker and reel aliasing

Two conform-ergonomics upgrades surfaced by real turnover shapes:

- **Multi-sequence containers**: `assemble_from_interchange` gains `sequenceName` / `sequenceIndex` for AAF and `.prproj`. When exactly one sequence carries events it auto-picks; when several do, it refuses and lists them (`index:name`) instead of flattening into an overlap refusal.
- **Reel aliasing**: sources now group **by file**, not by reel — multiple reels mapped to one `mediaFilePath` (Avid mob vs tape names, re-linked dailies) merge into a single source with combined cuts, instead of demanding a captured template per reel name.

Suites: Node 841 pass / 0 fail; Python 3105 passed + 799 subtests.

## What's New in v2.126.0 — AAF route fixed at the tool layer; harness parity

### The last gap in the AAF story

Two closures:

**A since-birth bug, fixed.** `assemble_from_interchange` with `format: 'aaf'` fell through to the sync parser — which throws for AAF — so the tool-layer AAF route had *never* worked (every earlier proof called the parser library directly). The handler now awaits the async `parseAAF`, and `aaf.mjs` falls back to the repo venv's Python (where `pyaaf2` lives), so the route works with zero environment setup. A stubbed regression test pins it.

**Harness parity.** The shipped `capture_media_template` ran live for both fixture sources — capturing `mediaStartTime` 3600 and the native clip elements through the real code path — and the tool-handler route produced renders **identical** to the hand-verified E36 run (126.376 / 95.965 / 95.964 / 126.373, audio −21.08 dB). Nothing hand-rolled remains in the chain.

Suites: Node 840 pass / 0 fail; Python 3105 passed + 799 subtests.

## What's New in v2.125.0 — the round-trip QC loop closes

### Prove the conform, don't trust it

New `editorial.verify_roundtrip`: parse the original turnover, parse Resolve's own re-export of the timeline you authored from it, and get a verdict — normalized for the three conventions that otherwise drown the diff in noise:

- track labels (`V` ≡ `V1`)
- source naming (AAF mob name vs file basename, extension-stripped)
- source frames (Resolve's OTIO export is **timecode-absolute** — a constant per-source offset is fitted, reported, and enforced)

**Live proof:** rich AAF → `assemble_from_interchange` → import → Resolve's own OTIO export → `pass: true`, 4 pairs, `srcOffsets` = 86400 for both sources — exactly their 01:00:00:00 TC bases. The record geometry survives the entire loop to the frame.

Real drift still trips it: a 5-frame source slip or a 2-frame record slip returns `pass: false` with the mismatch kind and location.

Suites: Node 839 pass / 0 fail; Python 3105 passed + 799 subtests.

## What's New in v2.124.0 — the Premiere leg; five formats proven

### .prproj in, frames out — no Premiere required

`assemble_from_interchange` gains `format: 'prproj'`: the Premiere project is read **offline** (gunzip + object-graph walk), converted through the same authoring bridge, and lands as a linked, rendering `.drt`.

**Live proof through the actual tool handler:** a schema-faithful synthetic `.prproj` (two sources on V1 + an audio event) → `.drt` → import (3/3 linked, fresh project) → render: 122.99 / 234, audio −21.1 dB.

That makes **all five interchange formats route-proven end-to-end**: EDL, OTIO, AAF, FCP7 XML, and `.prproj` — parse → assemble → import → measured frames and RMS.

Also: the result note that still claimed "retimes are flattened and transitions become cuts" (stale since v2.111/v2.113) now states the authored-ledger truth.

Suites: Node 837 pass / 0 fail; Python 3105 passed + 799 subtests.

## What's New in v2.123.0 — four formats proven; cross-link guard

### Route coverage complete

**All four interchange formats — EDL, OTIO, AAF, and FCP7 XML — are now route-proven end-to-end**: parse → `assemble_from_interchange` → `.drt` → import → measured frames and RMS. The XMEML leg (E37): two sources cut on V1 (122.99 / 234) with an explicit A1 audio event continuing at −21.1 dB under the second cut.

**And the guard the merge law demands:** `import_timeline_checked` now cross-checks `.drt`/`.drp` imports — the archive's `<MediaFilePath>` set vs the files the imported items *actually* link to. A missing expected file returns `cross_link_warning` with the full `{expected, actual, missing}` comparison. This catches the coarse-identity cross-link that `linked == total` is provably blind to (the wrongly-linked items read back fully linked, wrong clip name and all).

Suites: Node 836 pass / 0 fail; Python 3105 passed + 799 subtests.

## What's New in v2.122.0 — the AAF route, coast to coast

### AAF in, frames out

The full route is proven: a rich Resolve-exported AAF → `assemble_from_interchange` → `.drt` → import → render, **every window frame-accurate** (Studio 19.1.3.7, headless):

| Window | Expected | Measured |
|---|---|---|
| V1 rt_source_1 | ~126 | 126.4 |
| V2 rt_source_2 stacked over V1 | ~96 | **95.97** |
| V1's rt_source_2 cut | ~96 | **95.96** |
| V1 rt_source_1 tail | ~126 | 126.4 |
| Audio (both source windows) | tone | −21 dB |

Channel-leg merge, V2 stacking, and TC-bearing sources (embedded 01:00:00:00 via `MediaStartTime`) verified in one render. The v2.120 native-donor clone path is now **render-verified**.

**New law (`api_truth`):** `ImportTimelineFromFile` merges pool media by a *coarse* identity across imports — two different files (different names and sizes, mtimes 1 s apart) carried identity blobs byte-identical except uuids, and in a non-empty project the second file's clips silently played the first file's picture. Fresh projects materialize both correctly; verify per-item paths (or render probes) after importing into non-empty projects.

Also recorded: the modal-wedge failure mode and its recovery (force-kill + headless relaunch; headless is *not* modal-immune — a would-be dialog hangs the call; a hard-wedged render has no API exit).

Suites: Node 836 pass / 0 fail; Python 3101 passed + 799 subtests.

## What's New in v2.121.0 — one marker codec everywhere

Offline consolidation release (live validation is paused on a stuck Resolve dialog — see v2.120.0). All marker paths now share the single measured codec:

- `seq-container-builder` encodes lockable-blob markers with `timeline-markers-blob` (byte-exact vs a live Resolve export) instead of the deprecated simplified encoder
- `editorial.marker_roundtrip` adds a **binary** round-trip through the real codec, with provenance riding in `customData` — the result gains `blobRoundTrip`
- `parseOTIO` picks up **track-level** markers (record-time `marked_range`) alongside clip-level ones

Suites: Node 836 pass / 0 fail; Python 3101 passed + 799 subtests.

## What's New in v2.120.0 — AAF channel-leg merge; native-donor path staged

### The AAF leg, part one

Driving a real Resolve-exported AAF through `assemble_from_interchange` surfaced two truths and staged one architecture change:

- **AAF duplicates audio per channel.** Every A-track event in a rich Resolve 19 export arrives twice (one per channel leg). The bridge now merges identical legs instead of refusing them as a same-track overlap (`report.audioChannelLegsMerged`, tested); skipped-audio accounting corrected.
- **Embedded source timecode matters.** A `.mov` with embedded 01:00:00:00 fails the render with *"Full resolution media not found at 01:00:00:00"* — the native clip stores `<MediaStartTime>` in seconds where the template donor has 0. `capture_media_template` now harvests `mediaStartTime` plus the source's native timeline-clip elements.
- **Native-donor clone path (staged, live-unverified).** `cut-media` can clone the source's own captured clip (per track type, wrapper kept). Only caches carrying the new fields reach it — every existing capture keeps the proven donor path. Live verification is pending: a stuck Resolve modal (import-failure dialog) wedged the session mid-expedition — after it, even previously-proven files refused to import, so every later measurement was of the wedge, not the code. The resume plan is recorded.

Suites: Node 835 pass / 0 fail; Python 3101 passed + 799 subtests.

## What's New in v2.119.0 — turnover markers ride the conform

### Locators survive the trip

Editorial marks up a cut; the conform should keep those marks. Now it does: **EDL `* LOC:` locators** (the Avid convention) and **OTIO `Marker` objects** parse into the normalized event stream and come out the other end as real timeline markers in the assembled `.drt` — names, colors, exact frames.

**Full-route proof:** an EDL with two `LOC` lines imports as a timeline whose markers read back at exactly frames 24 and 60 with their names and mapped colors (Red / Green) through the marker API.

### Changes
- `parseEDL`: `* LOC:` lines → `track: 'MARKER'` pseudo-events (never miscounted as skipped audio)
- `parseOTIO`: clip markers → record-position MARKER events
- `eventsToAssembleSpec`: authors `spec.markers`; interchange colors map onto the measured 16-color Resolve palette (MAGENTA→Fuchsia, ORANGE→Sand, WHITE→Cream, BLACK→Cocoa; unknown→Blue); `report.authoredMarkers`
- 2 new bridge tests

Suites after last edit: Node 834 pass / 0 fail; Python 3101 passed + 799 subtests.

## What's New in v2.118.0 — timeline markers authored offline

### Markers ride the .drt now

`drt.assemble` gains `spec.markers` — timeline markers with all 16 colors, names, notes, durations, and `customData`, authored fully offline and verified by API readback after import.

**The decode:** markers live in `project.xml` as a `Sm2SequenceLockableBlob` (owner = the timeline's `Sm2Sequence` DbId) wrapping a zstd-framed protobuf. Resolve itself emits **raw-block zstd** for small payloads and accepts it on import — so the codec needs no zstd library. The new `timeline-markers-blob.js` encoder is **byte-exact** against Resolve 19.1.3.7's own export (fixture checked in).

**The correction:** the legacy `marker-encoder.js` color map was wrong (Yellow is 16, not 8; Purple is 128, not 131072) and its output never matched a real export — now deprecated with a pointer. The full 16-color bit map was harvested live, one marker per color.

**Proof:** offline-authored markers (Red with note + duration 12; Mint with `customData`) read back perfectly through the marker API after import.

Suites after last edit: Node 832 pass / 0 fail; Python 3101 passed + 799 subtests.

## What's New in v2.117.0 — start-timecode fidelity

### The conform emulator keeps the real start TC

AAF/EDL turnovers rarely start at 01:00:00:00 — and until now the assembled timeline silently did. `assemble_from_interchange` gains `preserveStartTimecode: true`: the timeline starts at the turnover's **real first record frame** (the long-standing AAF rule "build at THAT start" — now automated).

**The discovery:** a timeline's start timecode lives in exactly one non-cosmetic place in a `.drp`/`.drt` — the pool `Sm2MpTimelineClip`'s `MediaExtents` blob, 16 bytes of LE doubles `[startSeconds, durationSeconds]`. Patch it offline, keep clips at absolute frames ≥ the new origin, and the import lands at the new start TC and renders.

**Proof:** offline patch to 02:00:00:00 → readback `02:00:00:00`, live frame; full route: a 00:59:52:00 EDL → timeline at 00:59:52:00 (86208–86304) with both sources rendering correctly.

### Changes
- `drt.assemble`: `spec.startFrame` (frames @24; before-origin cuts still refuse, against the new origin)
- `assemble_from_interchange`: `preserveStartTimecode`
- `api_truth` MediaExtents entry; 2 new tests

Suites after last edit: Node 830 pass / 0 fail; Python 3101 passed + 799 subtests.

## What's New in v2.116.2 — flat-target wording routed to assemble

Doc-clarity release from a post-release drift review (which found everything else clean — generated files, tool counts, api-limitations, version stamps). `convert_to_interchange`'s flat DRT target still flattens retimes by design, but the claim "the DRT clip schema has no per-clip speed field" read misleadingly now that `drt.assemble` authors retimes via `Sm2TimeMap` (v2.113+). The tool description and `resolve-advanced/README.md` now name the flat target explicitly and route to `drt.assemble_from_interchange` for authored retimes, dissolves, multi-track video, and audio.

Suites: Node 828 pass / 0 fail; Python 3101 passed + 799 subtests.

## What's New in v2.116.1 — the flat-timemap divergence

Knowledge release. Freeze-frame probe: a **flat** keyed `Sm2TimeMap` (both keyframes at the same source Y) is the one timemap shape where readback and render *disagree in the trusting direction* — the imported item reads back frozen (source 96..96) but **renders moving** (48/48 unique frames). Freezes therefore stay in `flattenedRetimes` with the reason rather than being authored as flat maps. Recorded in `api_truth` (the readback-blind class now has a member that lies in both directions).

Suites: Node 828 pass / 0 fail; Python 3101 passed + 799 subtests.

## What's New in v2.116.0 — audio cross-fades authored

### The conform emulator learns audio cross-fades

An audio dissolve in interchange now becomes a **real, rendering cross-fade** in the assembled `.drt`.

**The harvest:** Resolve has no API for transitions, so we let it author one — an FCP7 `KGAudioTransCrossFade` imported via XMEML lands as an audio `Sm2TiTransition` (PrettyType "Final Cut Pro 7", which is what Resolve itself stores — and renders). That element is now a bundled template.

**Render proof:** the offline-authored crossfade's highpass-RMS **ramps** through the junction (−27.6 → −25.6 → −23.0 → −21.9 dB), identical in shape to a Resolve-authored control; a butt cut steps.

### Changes
- `placeTransition` `trackType: 'audio'`; `drt.assemble` `transitions[].trackType`
- `eventsToAssembleSpec`: audio dissolves authored under the same abut/handle geometry; drops carry `trackType: 'audio'` and the reason
- XMEML gotcha recorded: an `<audio><channelcount>` block inside a *file definition* aborts the whole import silently
- 2 new bridge tests; template wrapper guard extended

Suites after last edit: Node 828 pass / 0 fail; Python 3101 passed + 799 subtests.

## What's New in v2.115.1 — native DRT authoring guide

Documentation release: [docs/guides/native-drt-authoring.md](https://github.com/samuelgursky/davinci-resolve-mcp/blob/main/docs/guides/native-drt-authoring.md) consolidates the offline-authoring subsystem (v2.105–v2.115) — every capability with its spec surface, the four measured laws (Fusion comp byte-keyed cache, Fairlight strip, Sm2TimeMap generation split, timeline origin), the readback-is-blind verification doctrine, and a delivery checklist. AGENTS.md links it from the Conform/Interchange workflow row; per-IDE agent rules regenerated.

Suites: Node 826 pass / 0 fail; Python 3101 passed + 799 subtests.

## What's New in v2.115.0 — audio authored: the Fairlight strip law

### The conform emulator learns audio

A-track events in interchange now come out the other end as **real, playing audio clips** — the last big honesty-ledger item (`audioEventsSkipped`) falls.

**The law (measured by elimination):** audio tracks cannot be grown offline. The per-timeline Fairlight model (`FLStudioModelBA`, inside the media pool's `Sm2Sequence.FieldsBlob`) holds one mixer strip per audio track — a cloned track imports fine, reads back fine, and renders **silent**. We made the clip byte-identical to a live-authored one, the track byte-identical (`SubType` is the channel-format code — 1=mono — not an ordinal), shared the pool entry with a playing A1 clip: still silent. Only a template *captured* with the tracks plays. Audio aliveness is readback-blind — verify by rendered RMS.

**The fix is the capture-once pattern again:** the r19 media template was re-captured live with **8 mono audio tracks** (valid strips ride along). `audioOnly` cuts land on A1–A8 and render at native level; placements beyond the ceiling refuse with instructions.

**Full-route proof:** OTIO with V + two audio tracks → `.drt` → import → render: A1 tone −21.09 dB, A2 tone −24.08 dB (exactly the native control), video alive throughout.

### Changes
- `drt.assemble`: `cuts[].audioOnly` + `track` (1–8); explicit audio suppresses the A1 convenience mirror; audio clones carry their own source identity (donor-identity clones were part of the silence)
- `eventsToAssembleSpec`: A-track events authored with per-track overlap checks; audio retimes skipped with reason; OTIO/EDL audio tracks numbered (`A`, `A2`, …)
- `api_truth`: Fairlight-strip entry (silent-failure class); 3 new tests

Suites after last edit: Node 826 pass / 0 fail; Python 3101 passed + 796 subtests.

## What's New in v2.114.0 — reverse retimes authored

### The last flattened retime falls

Reversed clips in interchange (OTIO negative `time_scalar`, XMEML/EDL reverse) are now **authored** into the assembled .drt — `flattenedRetimes` only holds zero-speed freezes.

**The shape:** reverse is the same r19 keyed `Sm2TimeMap` with the Y endpoints swapped — kf0=(0, YMax), kf1=(XMax, 0), a descending line. The encoder is **byte-exact** against Resolve 19.1.3.7's own −100% retime export.

**The In rule (measured):** for a reversed clip, `<In>` measures from the source **end**: `(sourceFrames − srcIn − dur×speed)/speed`. Offline proof: a reversed srcIn-24 dur-48 cut reads back source 71→23 — exactly the prediction — and renders 48 live frames.

### Changes
- `drt.assemble`: `cuts[].reverse` (composable with `cuts[].speed`)
- `eventsToAssembleSpec`: reverse authored; ledger reasons updated
- `api_truth` timemap entry extended with the reverse shape + In-from-end rule

Suites after last edit: Node 823 pass / 0 fail; Python 3101 passed + 796 subtests.

## What's New in v2.113.0 — retimes authored: the r19 Sm2TimeMap

### The conform emulator learns speed

A 50% `LinearTimeWarp` in OTIO now comes out the other end as a **real retime** in the imported timeline — not a flattened 100% clip.

**The discovery:** `Sm2TimeMap` keyframes are generation-split. Resolve 21 stores protobuf points; Resolve 19 stores a keyed-dict of keyed-dict keyframes — and **19 silently ignores the protobuf form on import** (the clip reads back at 100%, no warning). The new `buildConstantSpeedTimemapKeyed` encoder emits the r19 form and is **byte-exact** against a timemap authored by Resolve 19.1.3.7 itself.

**Full-route proof:** OTIO `time_scalar: 0.5` → `assemble_from_interchange` → import → the item reads source 96..120 over 48 record frames (50% at source offset 96, the exact interchange intent) and renders live.

### Semantics measured
- The timemap spans the **whole source** stretched by 1/speed; the clip's `<In>`/`<Duration>` window into it in **record-domain** frames (`srcIn` converts by `/speed`)
- Retimed cuts are video-only on A1 (audio would need its own timemap + pitch handling — stated in the ledger, not silent)
- Reverse still flattens, with the reason; `report.authoredRetimes` joins the ledger

### Changes
- `drt.assemble`: `cuts[].speed` (forward constant, e.g. 0.5)
- `eventsToAssembleSpec`: forward speeds authored, reverse flattened with reason
- `api_truth`: generation-split entry (silent-failure class); harvest fixture + byte-exactness unit test

Suites after last edit: Node 822 pass / 0 fail; Python 3101 passed + 796 subtests.

## What's New in v2.112.0 — multi-track video authoring

### The conform emulator goes multi-track

Two-video-track interchange (OTIO/XMEML) now assembles into a .drt with real V2+ stacking — and it renders.

**Render proof (Studio 19.1.3.7):** two-track OTIO → `assemble_from_interchange` → import (3/3 linked) → render: V1 testsrc at 122.8/125.5 with the V2 white insert covering the middle at exactly **234**.

### Changes
- `cutSourceIntoClips`: cuts gain `track` (1-based); missing video tracks grown as empty clones; track>1 cuts are **video-only** (their audio would overlap A1 — stated, not silent)
- OTIO/XMEML parsers number video tracks `V, V2, V3, …`; EDL stays single-V
- `eventsToAssembleSpec`: overlap judged **per video track** (V2 over V1 is legitimate geometry); dissolves match predecessors on their own track; ledger gains `upperTrackCutsVideoOnly`
- 2 new Node tests: V2 cut mapping, per-track overlap refusal naming the track

Suites after last edit: Node 820 pass / 0 fail; Python 3101 passed + 796 subtests.

## What's New in v2.111.0 — dissolves authored coast-to-coast

### The conform emulator learns dissolves

An EDL `D`-event now comes out the other end as a **real, rendering Cross Dissolve** — not a cut.

**Render proof (Studio 19.1.3.7):** an offline-authored `Sm2TiTransition` over transplanted cross-source media blends exactly through the cut — outgoing testsrc 123.9 → 130.8 → **181.6 at mid-dissolve** (predicted (124+234)/2 = 179) → 223.2 → incoming white 234. Transitions carry no Fusion comp, so the byte-keyed comp-cache law (v2.109.0/v2.110.0) does not apply: the harvested transition renders live on 19.

### Changes
- `eventsToAssembleSpec` **authors** a cross-dissolve when the predecessor ends exactly at the cut and both sides have handle media for the centered span; every non-authorable dissolve stays in `droppedTransitions` **with the reason** (no abutting predecessor / insufficient handles, side named). The report gains `authoredTransitions`.
- Full route re-proven live: EDL `D 024` → `drt.assemble_from_interchange` → `.drt` → `timeline.import_timeline_checked` → render → 181.6 mid-blend.
- `drt` tool doc updated: transitions no longer "become cuts".
- 4 new Node tests cover the authored / no-incoming-handle / no-outgoing-tail / record-gap branches.

Suites after last edit: Node 818 pass / 0 fail; Python 3101 passed + 796 subtests.

## What's New in v2.110.0 — offline generators render on 19; cache law scoped to titles

### Element expedition, part two — generators are exempt

v2.109.0 mapped the law: imported Fusion comps on Resolve 19.x render only via the machine's byte-keyed Fusion disk cache. This release proves the carve-out: **built-in generators are plain `Sm2TiGenerator` clips with no Fusion comp, and they render live from a fully offline-authored .drt** — measured on Studio 19.1.3.7 over transplanted white media (YAVG 234):

| Element | YAVG | Verdict |
|---|---|---|
| Solid Color on V2 | 16.0 | alive — covers the white |
| half-coverage control | 16 / 234 in one render | discrimination clean |
| `PrettyType` → SMPTE Color Bar | 104.9 | bars render |
| `PrettyType` → Grey Scale | 125.1 | ramp renders |

So offline element authoring on pre-21 is real for generators (slates, leaders, bars, solids) — only Fusion **titles** remain cache-bound, with the live `timeline.set_title_text` post-import flow as the working alternative.

### Changes
- `drt.assemble`: `elementsWarning` now fires **only for title elements** on pre-21 targets and documents verified generator kinds; spec doc lists `generatorName` options
- `api_truth`: generator exemption added to the byte-keyed cache-law entry; `api-limitations.md` regenerated
- **Version stamps unified**: v2.109.0's bump missed `install.py` and `src/granular/common.py` — the CI smoke test correctly **blocked** that npm publish (2.109.0 never reached npm). All four stamps now move together, enforced by `test_npm_package_metadata`
- New Node test: generator kind selection lands in the sequence XML; warning gate is title-only

Suites after last edit: Node 814 pass / 0 fail; Python 3101 passed + 796 subtests.

## What's New in v2.109.0 — element render law: byte-keyed Fusion cache on 19.x

### Element transplant expedition — verdict

**The law (measured on Studio 19.1.3.7):** a Fusion comp arriving via timeline import renders on Resolve 19.x **only** when the machine's Fusion disk cache holds frames keyed to the comp blob's *exact compressed bytes*. An identity recompression — byte-identical Lua, different zlib bytes, framing verified consistent — imported and read back perfectly but rendered black, while the untouched harvest rendered its cached frames. The live-render fallback for imported comps produces no frames on 19; Resolve 21-generation hosts render imported comps live (where the title/generator primitives were originally proven).

**Consequence:** offline text patching of Fusion comps for a 19.x host is impossible *by design* — no valid re-encoding can hit the byte-keyed cache.

**The working pre-21 flow:** `drt.assemble` media offline (native-descriptor transplant renders everywhere), then set title text **post-import** with `timeline.set_title_text` (its Fusion-comp write path is live-verified on 19.1.3).

### Changes
- `composition-text`: wrong plaintext dual-mode branch reverted (both generations share identical nested framing); law documented at `rewriteInner`
- r19 title/generator snippets `<Element>`-wrapped (raw clips concatenated into Items made render jobs fail with no status); guard test added
- `snippetPathFor(templateVersion)` selects r19 snippets for pre-21 targets; `drt.assemble` `elementsWarning` now states the law and the working flow
- `api_truth`: new entry *Imported Fusion comps render via byte-keyed disk cache on 19.x*; `api-limitations.md` regenerated

Suites: Node 813 pass / 0 fail; Python 3101 passed + 796 subtests.

## What's New in v2.108.0

**The conform emulator, coast to coast.** An interchange file goes in; an
importable, RENDERING native .drt comes out — one call.

### Added

- **`drt.assemble_from_interchange`**: EDL/OTIO/XML/AAF + a sourceMap
  (reel → {mediaFilePath, spec}) → parse → frame-convert → multi-source
  assemble with native-descriptor transplant → stamped .drt. The
  events→spec bridge (`eventsToAssembleSpec`) anchors the earliest video
  event at the timeline origin, converts nominal-base event frames to the
  24fps template timeline (round(frames × 24 / nominalFps) — butt cuts stay
  gapless through the conversion, verified at 29.97), groups cuts per
  source, refuses overlapping record ranges and unmapped reels loudly, and
  returns an honesty ledger: flattened retimes (the clip schema has no
  per-clip speed), transitions treated as cuts, audio events skipped (cuts
  carry their own linked A1).

Live-proofed on Studio 19.1.3.7 with the full route: a three-event EDL
cutting between two sources (with an M2 retime line) assembled, imported
6/6 linked with exact source in-points, and rendered each event's OWN
pixels — YAVG 125.6 / 234 / 125.5 — with a full-range render verifying at
duration ratio 1.0 and the retime present in the ledger.

### Scoped honestly

Title/generator elements on a pre-21 host are NOT render-verified: the
harvested snippets are Resolve-21 structures that import and read back
correctly but render black on 19.1.3 (measured), and the r19 snippet
harvest is incomplete (the generator's Sm2TiCompositionTable dependency,
the title's per-generation comp-blob layout) — with the partial harvest,
render jobs fail outright, which is worse. Snippet selection stays on the
R21 structures, `drt.assemble` warns when elements target a pre-21 host,
and the harvested r19 snippets ship in the templates directory for the
element-transplant expedition. Media cuts render everywhere the transplant
path covers.

## What's New in v2.107.0

**Multi-source media authoring.** `drt.assemble`'s media support grows from
one source to many: `media` accepts an array of `{mediaFilePath, spec, cuts}`
sources, each cut landing on the shared V1/A1 with its own source's
transplanted native descriptors. New plumbing: `insertMediaElement` appends
additional native pool elements into MpFolder's MediaVec (folder-parent id
adopted), and `cutSourceIntoClips` accepts a per-cut `mediaRef` so each clone
points at ITS source. Multi-source strictly requires a captured native
template for every source (the render-verified transplant path); the refusal
names `media_pool.capture_media_template` per missing file — a repoint
fallback that renders black across N sources would be a trap, not a feature.

Live-verified end to end on Studio 19.1.3.7 with luma fingerprints: a
timeline interleaving cuts from two sources (testsrc + solid white) imported
6/6 linked and rendered each cut's OWN pixels — YAVG 125.6 / 234 / 125.5
across the three cuts, matching each source's signature exactly.

## What's New in v2.106.0

**Media clips in native DRT authoring — cut real footage into an importable,
RENDERING timeline.** The deepest silent-failure class this repo has hit, run
to ground and shipped, live-verified at every step on Studio 19.1.3.7.

### The discovery chain

Adding media cuts to drt.assemble surfaced three buried traps in sequence.
First: repointing the bundled media template at a new file left the pool
entry's compressed identity blobs describing the ORIGINAL capture source —
and when that file still exists on the machine, Resolve silently links IT
(observed: authored timelines linked a client clip while every visible field
said the right path). Second: after teaching the Clip identity blobs the new
path (their layout: dir, filename, ctime-format mtime string, codec tag,
uuid, mtime-in-MICROSECONDS — a field first misread as file size), imports
read back perfectly and still failed to render: "Full resolution media not
found". Third: the render engine validates the pool entry's DEEP descriptors
(Radiometry, keyed-dict FieldsBlobs, stream data) that offline code cannot
synthesize. Structural readback cannot see any of this — only rendering can.

### The architecture that works

- **`media_pool.capture_media_template(media_path)`** (live, once per file):
  builds a disposable project around the file, lets Resolve describe it
  natively, caches the pool media element + MediaRef id under
  ~/.config/davinci-resolve-mcp/media-templates/, and switches your project
  back.
- **`drt.assemble` grows media support**: `media: {mediaFilePath, spec,
  cuts: [{startFrame, durationFrames, srcIn}]}` cuts ONE source into N
  placements (new cut-media vendor primitive: donor clip cloned with fresh
  DbIds and per-cut geometry on video + audio tracks; placement guards refuse
  cuts before the timeline origin and reads past the media's end). At build
  time the cached native element is TRANSPLANTED and MediaRefs rewired —
  rendered output then matches a natively built timeline exactly (YAVG
  125.6/123.2 across cuts vs 123.2 native control). Without a cache the
  result carries mediaDescriptor: 'repoint-fallback' and a warning naming
  the capture action.
- **Version-matched templates**: a Resolve-21 template stamped down to 19
  imports and reads back perfectly — and renders BLACK (the stamp clears the
  gate, not the blob semantics). Both template generations now ship ('21'
  original, '19' captured from 19.1.3.7); drt.assemble picks by
  targetAppVersion.

### Fixed

- `render.verify_output` never verifies a job whose JobStatus is not
  Complete (a Failed job's stub passed the duration-ratio check during this
  hunt).
- The repoint fallback's Clip identity blobs are now written with the
  measured field semantics (mtime-µs, ctime string, dropped stale fields).

All of it is an api_truth entry: imported media renders only with NATIVE
pool descriptors; render-verify authored timelines, because structural
readback cannot see this class.

## What's New in v2.105.0

**Native-schema DRT authoring — the parked "project, not a lap" — shipped.**
Tool-authored .drt files that Resolve's ImportTimelineFromFile actually
accepts, live-verified end to end on Studio 19.1.3.7.

The door was already half-open: the repo's template-splice engine
(assembleTimeline + the real Resolve-21 empty-project capture) authors
native-schema .drp archives, and the final bisection showed a .drt IS a .drp
that ImportTimelineFromFile accepts. What stood between them was the version
gate (the template stamps DbPrjVer 17; a 19.1.3 host wants 14) and a set of
extraction traps nobody had mapped.

### Added

- **`drt.assemble`** — spec → importable native-schema .drt (titles,
  generators, transitions), with `targetAppVersion` stamping for pre-21
  hosts. Live-verified: assembled archives import with every element intact.
- **`drt.extract_from_drp` rebuilt on the measured recipe**: keep
  project.xml + MediaPool + the SeqContainer at its ORIGINAL uuid path, drop
  Gallery, and remove other timelines' Sm2MpTimelineClip blocks (matched via
  the kept container's track Sequence DbIds) so they don't arrive as ghost
  empty timelines. The Python extractor behind `timeline.import_from_drp`
  implements the same recipe. Live-verified: single-timeline extracts from a
  two-timeline project import cleanly, one timeline, clips intact.

### The .drt import contract, fully mapped (api_truth rewritten)

A whole saved-project export renamed .drt imports, clips intact.
Requirements: project.xml; MpFolder.xml (it holds the Sm2Sequence/Sm2Timeline
objects); the SeqContainer's ORIGINAL uuid path — renaming it "succeeds"
with an EMPTY timeline, no error, the nastiest variant; version stamps at or
below the host; native blob schema; and a SAVED source project —
ExportProject snapshots the saved DB state, so an unsaved timeline exports
empty tracks (the trap that produced v2.104.7's "necessary but not
sufficient" verdict, now corrected). Every Sm2MpTimelineClip block imports
as a timeline; extras arrive as ghosts unless removed.

### Fixed in passing

- **project_db lookups can no longer hang on an unresponsive library root.**
  Mid-session, macOS rendered the Lite sandbox container path unresponsive at
  the filesystem level (`ls` itself hung) — which froze the Node test suite
  and would have frozen every projectName lookup. Roots are now probed with a
  deadline (`responsiveRoots`); unresponsive ones are skipped and NAMED in
  the not-found error. The root-walking tests are hermetic now — suites must
  not depend on machine paths that an OS can wedge.
- The flat-authored-shape refusal in import_timeline_checked now points at
  `drt.assemble` as the importable authoring route.

## What's New in v2.104.10

Stones turned on the live-validation backlog, on Studio 19.1.3.7.

**AAF live import, validated at last** (marked "NOT live-validated" since
2026-07-06): an EXPORT_AAF/EXPORT_AAF_NEW round trip imports cleanly with
importSourceClips=false, lands fully offline (the documented turnover shape),
and preserves the start timecode. The naming matrix across import formats is
now complete and in api_truth — FCP7 XML ignores timelineName (internal name
wins, the #171 trap); AAF honours timelineName when given, else its internal
name; OTIO honours timelineName; .drt names the timeline after the file. Only
FCP7 exhibits the returned-existing trap. The AAF post-import relink leg was
exercised too: under importSourceClips=false it correctly reports "no Media
Pool Items to relink" — the API relinks pool items, and none exist on that
path — so its precondition is now stated instead of assumed.

**safe_quick_export verifies its output.** RenderWithQuickExport's status
dict was the last render surface trusted without a file check: a success
status that wrote nothing read as an export. The files that actually landed
in TargetDir are now listed with size and ffprobe duration, and a success
status with no new file flips to an error.

**Housekeeping:** the delete-locked scratch project from the v2.104.7 session
is gone — the pre-restart DeleteProject had returned False while actually
succeeding, the documented DeleteProject lie caught in the wild. A clean
Resolve quit/relaunch verified the wedge entry's other half: Quit() works
when no orphaned render holds the pipeline.

## What's New in v2.104.9

**The NTSC coverage gap, closed.** The conform fixtures were integer-rate
only — which is how parseEDL ran exact-rate timecode math against a
nominal-rate writer for years (fixed in v2.104.6, convention measured against
Resolve's own GetStartFrame). New fixtures now exercise the pipeline at
29.97: a broadcast-start EDL parses to nominal frames (an NDF minute is 1800
frames, butt cuts stay gapless), the EDL write→parse round trip is
frame-identical, media-inventory's tc↔frames round trip is the identity at
all three NTSC rates, and drop-frame pins to the canonical values
(01:00:00;00 → 107892 — the number that haunted the #168 saga, now living
where it belongs). Cross-language pin tests assert the Python converters
(_timecode_to_frame_id, multicam) and the Node converters agree on the same
canonical values, so a change that moves one side fails the other side's
suite.

**Python dependency stack: audited to zero.** pip-audit over the dev venv
found and cleared advisories in urllib3, requests, python-multipart,
setuptools, starlette (0.52 → 1.6 — the MCP SDK tolerated the major, full
suite green), pyjwt, pydantic-settings, pygments, pillow, idna, msgpack,
cryptography, pip itself, and torch 2.13 (with the matching torchvision).
Also found: the venv's mcp SDK was at 1.27.0, BELOW the repo's own >=1.29
floor, and carrying a CVE — now 1.29.1. Both stacks (npm and pip) report
zero known vulnerabilities, with clean resolver constraints.

## What's New in v2.104.8

More laps: the aggregation class swept to completion, and the dependency
stack brought to zero known vulnerabilities.

**Four more envelope lies fixed.** An AST sweep for per-op result lists under
success-shaped envelopes (the class import_from_drp exposed) found four bulk
tools whose top level ignored their rows: `bulk_set_title_text`,
`fusion_comp.bulk_set_expressions`, and `bulk_set_inputs` returned bare
{results, op_count} — all-failed and all-succeeded calls indistinguishable
without reading every row — and `fusion_comp.add_mask` hard-coded
success:true over failable input writes, so a mask whose every parameter
failed to apply read as configured while sitting default-shaped on the clip.
All four now report success/succeeded/failed with partial warnings, through
one shared summarizer. Also swept and clean: flow-prescribing remediation
texts (every named action exists), absolute-belief comments in tests and
source, and the Python tree for further aggregation suspects (the remaining
hits are read-only listers).

**Dependency stack: 15 advisories to zero.** `npm audit fix` cleared the
non-breaking set (hono, fast-xml-parser, fast-uri, ip-address, js-yaml and
friends); adm-zip moved to 0.6.0; the `uuid` dependency is GONE (three call
sites now use Node's built-in crypto.randomUUID); and sharp moved to 0.35.4,
which clears four libvips CVEs in the image-decode paths that media QC feeds
untrusted files into.

**Node floor: >=20.9 (warn-don't-block).** sharp 0.35 requires Node 20.9+,
and Node 18 has been end-of-life since April 2025 — on an 18.20 interpreter
npm silently produced a BROKEN install (engines-skipped platform binding,
"up to date", no sharp module, 57 tests gone from the count). Both
package.json engines now say >=20.9, which warns older interpreters without
blocking, matching the Python floor policy. CI publishes on Node 24; the
full Node suite runs green on 20.19 (823 tests, sharp included).

## What's New in v2.104.7

The DRT import thread, chased to ground by live bisection on Studio 19.1.3.7
— and the tool had been giving instructions that could not work.

**What a .drt import actually requires, measured.** A real Resolve export
re-imports; the same archive minus ONLY project.xml is refused; removing
MpFolder.xml or renaming the SeqContainer path changes nothing. Tool-authored
DRTs fail on two counts: they omit project.xml AND use a flat template
container schema (<StartFrame>/<StartTC> elements) that Resolve never wrote —
its native containers are blob-based Sm2TiTrack/Sm2TiVideoClip structures.
Worse: a refused .drt import can raise a modal error dialog that BLOCKS the
scripting call indefinitely (observed live — the call neither returns nor
times out until a human dismisses the dialog), and .drt import names the
timeline after the FILE, not the container's internal name — a third naming
authority beside FCP7 (internal name) and OTIO (timelineName option). All of
it is now a submit-tagged api_truth entry.

### Fixed

- `import_timeline_checked` refuses tool-authored .drt/.drp BEFORE calling
  Resolve — the shape is detectable from the zip alone, and refusing early is
  what prevents the scripting-blocking dialog. The error names the actual
  cause and points at routes that work (OTIO authoring; Resolve's own .drt
  exports) instead of the old media/sanitize misdiagnosis.
- `import_from_drp` no longer reports success:true when every selected
  timeline failed to import (the discarded-outcome aggregation class); a
  partial import is labeled partial with a warning.
- Both extractors (`import_from_drp`'s and `drt.extract_from_drp`) now carry
  the source archive's project.xml into the extracted .drt — measured as
  necessary. NOT yet sufficient: a .drp-sourced native container repacked
  with its project.xml was still refused on 19.1.3.7, so extraction-based
  import remains unreliable on this build and is documented as such.

### Documented

- The .prproj refusal and offline-authoring guidance no longer tell users to
  author a 'drt' and import it — that instruction could never work; they
  point at 'otio'/'edl'. The drt tool and drt-builder docstrings state the
  authored template's actual role (offline/DB workflows, injection, parsing)
  and that real-Resolve exports are the only known-importable .drt files.

## What's New in v2.104.6

**A correction to the v2.104.2 StartFrame fix — measured against Resolve
itself.** SMPTE non-drop timecode counts NOMINAL frames: the fields multiply
by the integer base (30 for 29.97, 24 for 23.976), not the exact rate.
Measured live on Studio 19.1.3.7: a 29.97 timeline at 01:00:00:00 reads
GetStartFrame 108000 = 3600 x 30, and a 23.976 one reads 86400 = 3600 x 24.
Issue #168's reporter expected round(3600 x 30000/1001) = 107892 — they said
plainly they had patched defensively without verifying Resolve — and the
v2.104.2 fix shipped that expectation. Both the original fractional product
and the rounded 107892 were wrong; the Python converters (which always used
nominal) and the Node converters now agree.

Three Node converters move to nominal-base counting, with drop-frame
handling (semicolon timecodes) matching the Python formula:

- `drt.author`'s SeqContainer StartFrame (01:00:00:00 at 29.97 now writes
  108000; at 23.976, 86400)
- `editorial.tcToFrames` — the exact-rate product undercounted NTSC
  timecode by 0.1% (108 frames per hour), which touched every EDL/AAF
  source/record conversion at 29.97
- `media-inventory.tcToFrames` — whose own framesToTc was already nominal,
  so the tc->frames->tc round trip was asymmetric at NTSC rates until now

The conform fixtures are integer-rate, which is how the exact-rate
convention survived: nothing in the suite exercised an NTSC timecode
conversion end to end. Regression tests now pin the measured nominal values
and a drop-frame case.

## What's New in v2.104.5

The recent bug classes, generalized into guards — and the sweeps found the
kwarg bug a second time.

**PR #165's bug existed twice.** The positional-only bridge rule was guarded
for src/server.py alone; sweeping ALL of src/ found
`StartRendering(isInteractiveMode=...)` again in the render-deliver probe
catalogue. Fixed, and the guard is rebuilt properly: it parses the Resolve
method names out of the shipped API reference and flags keyword arguments on
exactly those calls across the whole tree — which is what separates
StartRendering from Popen without drowning in stdlib false positives.

**Closing a project mid-render is now unreachable through this server.** The
wedge documented in v2.104.0 (orphaned render, stuck IsRenderingInProgress,
0% jobs, refused Quit) could still be triggered via project_manager.close or
a disposable-project delete. `close` now refuses while a render is in
progress — with the wedge named in the remediation — and accepts
stop_render=true to stop, wait for the flag to clear, and close.
delete_project_safely auto-stops first (deleting kills the render anyway;
stopping is strictly better) and refuses when the flag will not clear, which
is the already-wedged state where no delete ends well. Live-verified both
paths on Studio 19.1.3.7: mid-render close refused, stop_render=true stopped
and closed cleanly, no wedge.

**Audits that came back clean, on the record:** the remaining default-ON
analysis gates (marker plan is built unconditionally, vision is default-OFF
behind a capability gate) cannot reproduce the cache-poisoning shape, and the
Python tree carries no numeric-keyed hex tables of the kind that rotted in
the Node encoders.

PR #166's discarded-return guard fired on this release's own
StopRendering call — third catch in three releases; the allowlist entry
records that the helper verifies by polling the flag, stronger than the None
the API returns.

## What's New in v2.104.4

Hardening pass over the classes the v2.104.2 batch exposed, live-verified on
Studio 19.1.3.7.

**set_title_text works on builds where SetProperty cannot.** On Studio 19.1.3
a Text+ item rejects every title property key, so set_title_text failed while
the item's Fusion comp accepted the same text all along. The setter now falls
back to writing StyledText on the TextPlus tool — deliberately UNLOCKED, per
the comp-lock render bug — and reports success only after reading the input
back. Live-verified end to end: set via fallback, read via get_title_text,
and a rendered frame confirms the text reaches the output (mean luma above
black). bulk_set_title_text inherits the fallback. PR #166's discarded-return
guard caught the fallback's bare SetInput during development — the allowlist
entry records that the write is verified by readback, which is stronger than
the bool Fusion doesn't return.

**verify_output no longer flags deliberate short renders.** A single-frame
capture tripped the mark-range-collapse warning, because the checker cannot
distinguish a caller-chosen short range from a Resolve-rewritten one. Passing
expected_frames / expected_duration_seconds matching the mark range now
suppresses the collapse warning; an unstated short range still warns.

**#171's scope measured: the internal-name override is FCP7-specific.** An
OTIO export re-imported under a new timelineName creates a new timeline
(measured 19.1.3.7), so the api_truth entry now says the override is an FCP7
XML behavior, not a general import rule.

**One more #167-class constant found and removed.** effect-encoder's exported
"common double values" hex table — consumed by nothing — carried a '0.9'
entry that decoded to 0.8. Deleted; the sweep found the remaining converters
(editorial, media-inventory, the Python timecode helpers) already round
correctly.

## What's New in v2.104.3

Documentation follow-through on the v2.104.2 batch.

- The FCP7 internal-sequence-name-overrides-timelineName behavior (#171) is now
  a submit-tagged api_truth entry, so it feeds the Blackmagic-facing
  limitations report alongside the fix that works around it.
- `project_db.list_subtitle_styles`'s styled:false note now states that the
  "must be styled once in the UI" precondition covers the scripted
  `ImportMedia(srt)` + `AppendToTimeline` route too (confirmed by the #169
  reporter on Studio 21.0.4.5), not only tracks added empty in the UI.

## What's New in v2.104.2

A contributor batch: two merged PRs, one PR converted into its fix, and four
sharp issues from @andytsai821201-spec — all live- or repro-verified.

**Merged.** PR #166 by @matoberuc-afk routes SetCurrentTimeline and 28 other
discarded Resolve mutator returns through a checked helper — a refused
timeline switch now errors instead of silently sending the next edit to
whatever timeline was current. PR #170 by @FerroQuant makes the doctor and
installer probes bridge-first and hard-exits probe children after native
Fusion imports, extending PR #108's fusionscript-teardown rule to the
remaining short-lived probes.

**Fixed (from PR #165 by @Douglas4000).** `timeline_frame capture` died on the
free-edition bridge with "unexpected keyword argument 'isInteractiveMode'":
the bridge proxies Resolve calls positionally, and the single-frame render
used a keyword. The call is positional now, and the bridge proxy raises a
TypeError that names the rule instead of the bare stack trace.

**Fixed (#167).** `drt.author`'s hand-typed frame-rate hex table was wrong in
three of eight entries: 23.976 stored 30000/1001 (a different, plausible
rate), 29.97 stored 29.9739, and 59.94 stored 0.9367 — while validate stayed
green. The table is gone; rounded NTSC decimals snap to their exact rationals
and everything encodes through writeDoubleLE.

**Fixed (#168).** `drt.author` wrote fractional `<StartFrame>` values at
fractional rates (01:00:00:00 at 30000/1001 → 107892.107…) and ignored the
spec's `startFrame` field entirely. Frame indexes now round, and an explicit
startFrame wins over the timecode.

**Fixed (#169).** `project_db` by projectName never searched
`Resolve Project Library/Resolve Projects` — the root a stock modern Studio
install actually uses (this repo's own 19.1.3 machine uses the old
`Resolve Disk Database` name, so both are real). Both Studio roots and the
sandboxed free-edition root are searched and deduped.

**Fixed (#171).** Resolve honours the sequence name INSIDE an FCP7 XML over
the `timelineName` import option, so an iterating export→edit→import loop
with a stale internal name "succeeded" while returning the same existing
timeline forever. `import_timeline_checked` now rewrites the XML's internal
sequence name to the requested timelineName before importing (surgical text
replacement on a temp copy — DOCTYPE and clip names survive byte-for-byte),
and a format it cannot rewrite that still returns an existing timeline errors
instead of reporting success. Live-verified on Studio 19.1.3.7 with the
reporter's exact step sequence. The headless-edit-loop guide documents the
internal-name rule for raw-API callers.

## What's New in v2.104.1

**The job metadata lies too — verify_output now cross-checks the timeline.**
Finishing v2.104.0's pending live validation exposed a hole in the new
`render.verify_output`: in the issue #164 case (content before the timeline
start) Resolve rewrites the render job's own MarkIn/MarkOut down to the
collapsed extent. Measured live on Studio 19.1.3.7: 96 frames of content
placed before the start turned an explicit 96-frame mark range into a 1-frame
job — Complete at 100%, a 1-frame black stub, and a clean duration ratio,
because the expected duration was computed from the job's own lying range.

The only truthful readback in that state is the timeline items themselves,
which report their real positions. `verify_output` now finds the job's
timeline and cross-checks it: video items starting before the timeline's
start frame warn (the #164 signature by direct evidence), and a mark range
under half the items' extent warns (the collapse signature). Callers can also
pass `expected_frames` or `expected_duration_seconds` outright. Live-verified
both ways on 19.1.3.7: the healthy render verifies clean, the stub now fails
with both warnings.

### Fixed

- `render.verify_output` no longer trusts the job's MarkIn/MarkOut as the
  expected duration — the #164 stub previously verified clean at ratio 1.0.

### Changed

- The api_truth recordFrame entry now documents the mark-range rewrite and
  the item-readback discriminator; the Blackmagic-facing report regenerated.

## What's New in v2.104.0

The read/write symmetry audit's worklist, worked. PR #162's AST rewrite left
eight `set_` actions with no readback; live probing on Studio 19.1.3.7 sorted
them into four the API supports and four it simply cannot — and turned up a
render-pipeline failure mode along the way.

### Added

- `media_pool.get_clip_marks` — read mark in/out for a set of media-pool clips,
  the read twin of `set_clip_marks` (live-verified round trip: set 12/60, read
  12/60).
- `timeline.get_clips_linked` — per-item link readback via
  `TimelineItem.GetLinkedItems` (live-verified: a video item returns its audio
  twin).
- `timeline.get_title_text` — the read twin of `set_title_text`. Resolves the
  same heuristic title-property keys as the setter, and falls back to reading
  `StyledText` off the TextPlus tool in the item's Fusion comp — on Studio
  19.1.3 the property route exposes no title keys at all (the setter fails
  there too), while the comp route reads and writes fine.
- `media_pool_item_markers.get_name` — the markers group carried `set_name`
  with no read twin.
- `render.verify_output(job_id)` — checks the actual output file against the
  job's own mark range: existence, size, ffprobe duration, and a
  duration-ratio warning when a Complete job produced a near-empty stub (the
  issue #164 signature: content the render engine never visited). Verify
  before deleting the job — deleted jobs carry no TargetDir to check.

### Documented (api_truth, Blackmagic-facing report regenerated)

Four readbacks the API cannot express, each now a submit-tagged entry:
`SetCDL` (no GetCDL anywhere — read grades via DRX decode instead),
`SetNodeEnabled` (no GetNodeEnabled), `SetKeyframeInterpolation` (nothing
returns interpolation; the whole keyframe family is absent on 19.1.3), and
`SetHighPriority` (no getter, irreversible per session). The symmetry report's
high-signal gap list is now exactly these four.

And one render-pipeline bug found the hard way: **deleting or closing a
project while its render job is running wedges Resolve** — the orphaned
render's `IsRenderingInProgress` sticks True on every subsequent project,
`StopRendering` does not clear it, new render jobs sit at 0% forever, then
`StartRendering` starts returning False and `Resolve.Quit()` is refused
behind a quit-confirm dialog. Reproduced live on Studio 19.1.3.7. Poll
`GetRenderJobStatus` for completion, never `IsRenderingInProgress`, and never
close a project mid-render.

### Version ledger

`MediaPoolItem.GetMarkInOut` and `TimelineItem.GetLinkedItems` enter the
evidence gates as measured-present on 19.1.3.7 (introduction versions
unbisected; the floors err toward refusing on older builds).

## What's New in v2.103.5

Two fixes that fell out of auditing the code around this week's releases — the
same failure classes as #161 and #164, found one tier up from where each was
originally fixed.

**Cache reuse was permanently poisoned on most real installs.** The v2.103.3
transcription fix taught batch jobs that a declined transcription is not a clip
failure — but the cache layer had the same default-ON blindness.
`_report_missing_layers` counted any non-success transcript as a missing layer,
and the capability gate only screens for a missing backend, not for the stock
configuration: Whisper installed, `allow_model_download` unset. On such a
machine every analysis writes a declined "skipped" transcript, every cached
report carries `missing_layers: ['transcription']`, and `find_reusable_report`
returns `reusable: False` — forever. Every analyze call silently re-ran full
analysis (frame extraction included) and produced the same skipped transcript
again. An unfixable loop, reproduced end-to-end before the fix and green after.

A transcript-less report is now a missing layer only when a re-run could supply
the transcript: the cached payload shows a real attempt that failed (a timeout
retry may succeed), or the current options would now actually run a backend
(mock or HTTP backends, or `allow_model_download=true`). Because the check is
recomputed per request, flipping `allow_model_download` on later correctly
refuses reuse and finally produces the transcript.

**Absolute recordFrames below the timeline start are now refused.** Issue #164
documented that `recordFrame` counts from Resolve's global frame zero and that
content placed before the timeline start reads back correctly while rendering
as ~0 frames. The wrapper's `record_frame_mode='relative'` default shields
callers — but `record_frame_mode='absolute'` passed any value straight through,
so an absolute-mode caller with relative-style values reproduced the silent
stub through this server's own tools. `_normalize_record_frame` (both the
compound and granular copies) now rejects an absolute value below the
timeline's start frame with an error naming the convention; internal
absolute-mode flows (`ripple_insert` cursors) derive their frames from
timeline reads and cannot trip it. The Resolve UI cannot place content there,
so no legitimate call is lost.

### Fixed

- A declined transcription (no `allow_model_download` opt-in, unavailable or
  not-implemented backend) no longer marks cached analysis reports
  incomplete, so report reuse works on default installs again. Opting into
  model downloads later invalidates reuse and produces the transcript.
- `record_frame_mode='absolute'` values below the timeline start frame are
  refused with a remediation instead of silently placing content the render
  engine never visits (#164).

## What's New in v2.103.4

**A frame-numbering trap, documented where agents will look it up.** Issue #164
by @jonathandahl-cmyk arrived as a detailed report that `AppendToTimeline`'s
`trackIndex`/`recordFrame` corrupt a timeline — every readback correct, render
produces a ~6KB stub. Their own same-day correction found the real cause, and it
is simpler and nastier: **`recordFrame` is timeline-absolute.** It counts from
Resolve's global frame zero, so `recordFrame=0` on a default `01:00:00:00`
timeline places the clip at frame 0 — an hour before the timeline's own start at
86400. The items genuinely exist and are internally consistent, so
`AppendToTimeline` returns them, every `Get*` reads back the expected values,
and the render engine — which only walks the timeline's own start→end range —
reports `JobStatus: Complete` at 100% while writing a near-empty stub.

The assumption was easy to make because Resolve uses both conventions side by
side: marker `frameId`s *are* timeline-relative (frame 0 == first frame), while
`recordFrame` and `TimelineItem.GetStart()`/`GetEnd()` are absolute.

This server's own callers were never exposed: `media_pool.append_to_timeline`
has defaulted to `record_frame_mode="relative"` — adding `GetStartFrame()` for
you — since v2.17.1, which live-validated the exact arithmetic (relative 12 →
86412; absolute preserved 86484). What was missing was the catalog entry: the
API-truth table had five `AppendToTimeline` entries (the half-open `endFrame`
bound, occupied-span null-ids, mixed-fps duration floors…) but never the
absolute origin, which fails more silently than any of them. It now records the
convention, the render-lies-too behavior, why the wrapper default exists, and
that `JobStatus: Complete` is not proof a render produced frames.

### Changed

- `src/utils/api_truth.py` gains
  `MediaPool.AppendToTimeline clipInfo recordFrame (timeline-absolute origin)`
  (#164). Internal entry — an undocumented convention, not a Resolve defect —
  so the Blackmagic-facing limitations report is unchanged.

## What's New in v2.103.3

**A batch transcription fix that would have failed every clip.** Issue #160 by
@techsolvehq-source was real and precisely reported: a Whisper transcription that
hit the 90s wall-clock cap already returned `success: False`, but
`execute_plan_async` then hard-set `clip_result["success"] = True`, so the batch
job counted the clip as succeeded, closed as `completed`, and left `last_error`
unset. PR #161 by @Steve0x2a fixed that by giving transcription the failure
annotation vision already had.

The gate it landed with keyed on `success` alone, and that is where it went wrong.
Transcription is enabled by default, and `allow_model_download` is off by default,
so `_transcribe` returns `success: False, status: "skipped"` on a stock install —
no Whisper backend, or one the user has not opted into model downloads for. Every
clip of every batch would have been marked failed and no batch job could have
reached `completed`. Vision can treat every non-success as a failure because
vision defaults to *disabled*; transcription cannot.

So the failure class is now drawn by status rather than by `success`: skipped,
disabled, and not_implemented mean the backend never ran, while timeouts, caps
refusals, and backend errors are real failures. The original timeout bug stays
fixed.

**Antigravity's config path, settled without picking a winner.** Issue #159 by
@KMiNT21 reports `~/.gemini/config/mcp_config.json`; commit 85afe82 wrote
`~/.gemini/antigravity/mcp_config.json`. Neither is verifiable from macOS, and
swapping one unverifiable path for another is a coin flip that breaks it for
whichever contributor was right — this repo has already been bitten by a
documented-but-decoy config path (Claude Desktop MSIX, issue #93). The installer
now probes: `~/.gemini/config/` first, because the installer has never written
there, so that file existing is evidence something else created it. It looks for
the file rather than the directory, since `~/.gemini/antigravity/` holds runtime
state on every install.

### Fixed

- A transcription backend that is unavailable, disabled, or not implemented no
  longer marks a batch clip failed. `transcription_attempt_failed` in
  `src/utils/media_analysis.py` screens the "never ran" statuses out of the
  failure class; timeouts, caps refusals, and backend errors stay in it.
- Whisper wall-clock timeouts are reported as failed batch clips instead of
  silently succeeding (#160, PR #161 by @Steve0x2a).
- `install.py` resolves Antigravity's MCP config path from what is on disk
  instead of a hard-coded guess (#159).
- `scripts/gen_api_limitations.py --help` prints usage instead of silently
  overwriting the generated report (PR #163 by @diesdaas).

### Changed

- The read/write symmetry audit resolves `_unknown(action, ...)` groups through
  the AST rather than a regex, so action lists expressed as named, starred,
  annotated, or concatenated module constants are now scanned. This surfaced a
  genuine readback gap (`set_clip_marks`) the regex was missing, and known
  readback aliases such as `get_cache_enabled` and `mcp_update_status` no longer
  register as false gaps (PR #162 by @diesdaas).
- `scripts/audit_readwrite_symmetry.py` writes `docs/reference/readwrite-symmetry.md`
  by default and gains `--check` and `--stdout`, matching the
  `gen_api_limitations.py` convention. The report is pinned to `src/server.py` by
  a drift guard, so it needed a regeneration path: the check now runs in the
  release checklist, and both the script and the failing test name the command
  that clears it.

## What's New in v2.103.2

**A Windows setup that failed with nothing to read.** Reported in issue #158 by
@KMiNT21 on a machine carrying both Python 3.12 and 3.13: `npx davinci-resolve-mcp`
exited without a traceback, a log line, or an error. Three defects compounded.

The first is the one that mattered. The npm launcher tested for the Windows `py`
launcher with `py --version`, and that result gated the entire `py -3.12 / -3.11 /
-3.10` candidate list. `py` does not accept `--version` on every build — it exits
101 on the ones it does not — so on those machines the probe reported no launcher,
every version-pinned candidate was discarded, and selection fell through to bare
`python`: the 3.13 that the candidate ordering exists specifically to avoid. The
3.13 protections added in v2.26.1 were not wrong; they were being skipped past.

The fix removes the probe rather than correcting its flag. `checkPython()` already
validates each candidate by running it, so a machine without `py` costs one failed
spawn. A probe that can produce a false negative earns its place only if something
downstream cannot do without it, and nothing here needed it.

### Fixed

- `bin/davinci-resolve-mcp.mjs` no longer gates the `py -3.x` candidates behind a
  `py --version` probe.
- An access-violation exit is now explained instead of propagated bare. Windows
  reports `STATUS_ACCESS_VIOLATION` as an exit code (`3221225477`, or `-1073741819`
  read signed), not as a signal — the interpreter dies inside the native library
  with no chance to print. Both the launcher and `install.py`'s connection probe now
  name the code, say why there is no traceback, and give the remedy. Previously the
  probe could only report `Process exited with code 3221225477`.
- `scripts/doctor.py` consults the runtime discovery helpers when every candidate
  path misses, so Resolve installed off the conventional root (the reporter had it
  on `D:`) is found rather than reported as four FAILs on a machine `install.py` had
  just configured correctly. Same shape as issue #106.
- `scripts/doctor.py` no longer reports a client config as `missing` because of path
  escaping. A Windows path written into JSON comes back with doubled separators, and
  the literal substring test could never match it — a false negative in the tool
  whose job is to say whether setup worked.

### Not changed

Python 3.13 is still permitted. The policy set in v2.26.1 is a 3.10 floor with no
cap — warn, do not block — and issue #158 proposed enforcing 3.10-3.12 on Windows.
The candidate ordering already prefers the lower-risk interpreters; the bug was that
ordering being bypassed, which is now fixed.

### Coverage and its limits

`tests/test_windows_python_crash.py` pins the launcher's candidate shape and the
crash-code translation; `tests/test_doctor_paths.py` gains the discovery and
path-escaping cases. All were confirmed to fail against the unfixed code.

What is **not** covered, and is not coverable from macOS: whether `py --version`
actually fails on any given Windows build. That claim comes from the reporter. The
fix does not rest on it — it removes the probe rather than correcting it, so the
code no longer has an opinion either way. The access-violation paths are likewise
tested by injecting the exit code, not by producing a real crash.

## What's New in v2.103.1

**A loudness measurement could silently become a single frame's reading.**
`media_analysis`'s EBU R128 parser took the last match for `I:`, `LRA:` and `Peak:`
across the whole of ffmpeg's stderr. `ebur128` prints a progress line per frame carrying
those same fields, so that read was correct only because the `Summary:` block happens to
print last. Nothing enforces that ordering, and when it does not hold the numbers still
parse — a delivery-grade figure is quietly replaced by one frame's, with no error to
notice.

### Fixed

- `media_analysis._parse_loudness` now reads the summary block and nothing else.
- Both callers share one parser, `src/utils/loudness_parse.py`. The regexes were
  duplicated so `mix_plan` stayed importable without the analysis engine; that argument
  covers the engine, not the parsing rule, and a rule that has to be right in two places
  is one that eventually is not.
- Absent a summary the result is `None`, not a best guess. "No measurement" and
  "one frame's measurement" are different answers, and only one is safe to deliver on.

### How the block is bounded

Two independent guards, because each rests on a different assumption about ffmpeg's
output and either can outlive the other:

1. **Block bounding** — seek the last `Summary:`, then take lines until the next ffmpeg
   log line. The summary body is indented plain text while every log line carries a
   `[component @ address]` prefix, so the block ends at `[out#0/null …]`, at a trailing
   progress line, and at anything else appended after it.
2. **`TARGET:` filtering** — the field on every progress line and on nothing in the
   summary. This is what still holds if a progress line ever arrives without the
   bracketed prefix, and it is what makes the no-summary path return `None`.

### Validation

- Offline suite: 2980 passed, 1 skipped, 725 subtests, 0 failures (was 2959/719).
- Verified against real ffmpeg output, not only fixtures: a live `ebur128` run is parsed
  and the block asserted to end before ffmpeg's own trailer.
- Four deliberate mutations — no scoping, locating the summary without bounding the
  block, bounding it without the `TARGET:` filter, and falling back to the raw stream
  when no summary printed — were each caught. The third initially survived, and the test
  isolating that guard was added until it failed.
- No Resolve behavior changed; live test not required.

## What's New in v2.103.0

**An unreachable Resolve no longer ends the work.** The interchange authoring that can
write an importable timeline has been in this repository the whole time, one process
away, while a connection failure stopped everything. This routes to it.

### Added

- **`timeline author_offline`** — write an importable timeline from a file-path clip plan
  with no Resolve connection. Served **above** the connection check, because it exists
  for the case where there is none. Targets in preference order:
  - **`drt`** (default) — Resolve-native, carries track structure. Stamped at project
    version 17 (Resolve 21.0); older builds need the advanced server's
    `drt(action='downgrade')`. Verified map: 18.0.4 -> 11, 19.1.x -> 14, 21.0 -> 17.
  - **`otio`** — round-trips through this repo's own parser and carries gaps, per-clip
    speed, and transitions. The target to pick when the plan has retimes.
  - **`edl`** — CMX3600: video cuts and M2 speed, nothing else.
- **`timeline offline_fallback_capabilities`** — whether authoring is available here, and
  why not if it is not.
- **`offline_alternative` on every not-connected error** — naming what could be produced.

### It is an offer, never a substitute

A caller who asked to build a timeline *in Resolve* has not succeeded because a file was
written somewhere. The connection error stays an error, the block says outright that
authoring does not complete what failed, and nothing is authored unless it is asked for.
A test asserts both halves, because an offer that reads as success is worse than no offer.

### Two silent failures, now named

- `media_tc_origin_assumed` — OTIO source frames are **timecode-absolute**. An event with
  no media timecode origin imports as an *empty* timeline: the file opens, nothing
  appears, and no error is raised. Every event that had to assume an origin is named,
  with the fix (`media_start_tc_frame` per clip).
- `retimes_flattened` — a `.drt` carries no per-clip speed field, so retimes flatten to
  100% forward. Every event that lost one is named, with OTIO as the target that keeps it.

### Fixed

`_check()` emitted its own flat `NOT_CONNECTED` error asserting Resolve might not be
running and pointing every reader at a Studio-only preference — the same three wrong
claims `_not_connected_error` was written to stop making in v2.63, still being made here
because two producers of one error had drifted apart. It now delegates, so the message
distinguishes "not running" from "running but refusing scripting" from "the bridge is
enabled and silent", and free-edition users stop being sent to check a Studio install.

### Design notes

- **Frame numbers are at the timeline rate and `end_frame` is EXCLUSIVE**, matching
  `AppendToTimeline`'s half-open range. The two shapes disagreeing would be a one-frame
  error on every clip — exactly the kind that survives review.
- **Authoring runs in Node** against `resolve-advanced/server/author-interchange.mjs`
  rather than a second Python writer. Two writers to keep in agreement means the one that
  drifts is always the copy nobody runs. Without Node it refuses and says why.

### Validation

- Offline suite: 2959 passed, 1 skipped, 719 subtests, 0 failures.
- All three targets authored and read back: OTIO parsed as a Timeline document with
  timecode-absolute source ranges, DRT and EDL written and inspected.
- Three deliberate mutations (swallowing the media-origin warning, treating `end_frame`
  as inclusive, and marking the connection error as a success) were each caught.
- No Resolve behavior changed by the authoring path itself; live import validation of an
  authored file is **not** included in this release.

## What's New in v2.102.0

**A rough mix that reports what it achieved, not what it intended.** The pieces were
already here — `media_analysis` measures EBU R128 loudness and detects silence,
`delivery_targets` holds the standards, `loudness_qc` grades a finished file. What was
missing is the step between measuring and grading: deciding the gains.

### Added

- **`media_analysis mix_plan`** — dialogue-normalisation gain, a music-bed level relative
  to it, and ducking windows derived from silence detection **on the dialogue stem**, so
  the bed follows the words rather than a hand-placed envelope. `dry_run` defaults to
  true and renders nothing.
  - **The achieved loudness is measured, not derived.** The premix is rendered, then
    re-measured; `achieved` carries integrated LUFS, true peak, loudness range, and the
    delta from target. A plan that hits its target on paper and clips on true peak is a
    failed plan, and only the measurement tells you which one you have.
  - **Dialogue-anchored, then programme-trimmed.** Anchoring dialogue at target is right
    for a dialogue-gated standard and wrong for a full-programme one the moment a bed is
    added. For non-dialogue-gated standards one measured trim is applied to everything
    equally — preserving the dialogue-to-bed relationship — and reported as
    `program_normalize.trim_db`. It never runs on a dialogue-gated standard, where
    dialogue is the figure being graded.
  - **Nothing else is corrected.** `loudness_off_target`, `true_peak_over`, and `clipped`
    come back as flags with remedies, never as a quietly normalised file.
  - Standards come from `delivery_targets` (`web`, `podcast`, `ebu_r128`, `atsc_a85`,
    `ott_dialogue_gated`) — the table the delivery tools already grade against, not a
    second copy.
- **`media_analysis measure_loudness`** — integrated LUFS, loudness range, and true peak
  per file.
- **`media_analysis mix_plan_capabilities`** — dependency state, known standards, and the
  defaults, including the music-bed offset, which is the number most likely to be argued
  with and so is named rather than buried.

### Fixed while building it

The new loudness parser reads the `Summary:` block **and** drops ebur128's per-frame
progress lines, which carry their own `I:` and `LRA:` fields. A plain last-match-wins
parse is correct only because ffmpeg happens to print the summary last, and scoping to
the summary alone still swallows a progress line printed after it. Both steps are needed;
a test with a trailing progress line pins it.

### Scope

A rough mix: gain staging, a bed, and ducking. No EQ, compression, de-essing, or
limiting, and the module says so in its capabilities rather than leaving it implied.

### Validation

- Offline suite: 2924 passed, 1 skipped, 711 subtests, 0 failures.
- End-to-end through real ffmpeg on generated tones: target hit from measurement, the
  programme trim landing a hot bed on R128, a dialogue-gated standard refusing the trim,
  and clipping reported rather than normalised away.
- Three deliberate mutations (silent peak normalisation, trimming a dialogue-gated
  standard, and dropping the parser scoping) were each caught. The parser mutation was
  caught only after the test was strengthened — the first version of it passed against
  both the fix and its absence.
- No Resolve behavior changed; live test not required.

## What's New in v2.101.0

**A grade can now reject itself.** `assess_grade` has measured grade damage since
v2.68.0 — banding in a sky, highlight levels collapsing, shadow grain amplified into
noise — and every flag it raises carries a remedy. Nothing consumed that report. The
measurement existed; the loop did not, so the remedy "reduce the strength" was advice an
agent had no way to act on.

### Added

- **`media_analysis grade_loop`** — the retry ladder. Applies a look LUT, measures the
  real decoded frame, and on any flag retries with the same look attenuated toward
  identity (strength x 0.8 per rung, floored at 0.5, three tries by default). The first
  strength that clears every sampled frame wins.
  - **A flagged result is never reported acceptable.** An exhausted ladder returns
    `needs_human` with the best attempt and its remaining flags — never a quiet success
    at a strength that still bands.
  - **Every sampled frame must pass.** `times=[...]` samples several timestamps and the
    report names the one that failed; a grade clean on the frame you happened to check
    is not a grade that passed.
  - **The best attempt is the gentlest.** When nothing converges, attempts rank by flag
    count with ties broken by the smallest colour shift — equal damage means taking the
    one a human has less to undo.
  - **It does not touch the project.** The result is an apply manifest with
    `safe_to_apply`, and a flagged result carries the reason it is blocked.
  - `dry_run` defaults to true and reports the ffmpeg decode budget before anyone
    commits to it. `cost_tier` defaults to `numeric`, because escalating every rung to
    vision would spend host turns on attempts that exist to be rejected.
- **`media_analysis grade_loop_capabilities`** — dependency state, ladder constants, and
  an explicit statement of which modes exist.
- **`src/utils/cube_lut.py`** — read, write, and attenuate 3D `.cube` LUTs. Attenuation
  is a blend toward identity, the same operation a LUT mix control performs. Exact at
  both endpoints: strength 1.0 returns the table unchanged and 0.0 returns true
  identity. 1D LUTs are refused by name, and attenuation on a non-unit
  `DOMAIN_MIN`/`DOMAIN_MAX` is refused because identity is only identity on 0..1.

### Not built, and said so

The in-loop **live** mode — apply in Resolve, render a frame, assess, repeat — is not
implemented. It needs a single-frame render per rung, and shipping it unvalidated would
put a "verified live" claim behind something no runnable command has produced.
`grade_loop_capabilities()` says this in the response rather than only in the docs. The
offline LUT ladder is complete and validated.

### Documentation

- `docs/guides/color-decision-guide.md` — a new "Rejecting Your Own Grade" section on
  when measurement beats eyeballing a compressed preview.
- `docs/kernels/color-grade-kernel.md` — the numeric grade-QC actions and their
  display-referred-only contract.

### Validation

- Offline suite: 2889 passed, 1 skipped, 711 subtests, 0 failures.
- End-to-end through real ffmpeg on generated media: a look that converges only after
  backing off, and one that never converges and says so.
- Two deliberate mutations — `acceptable` hard-coded true, and a rung passing on its
  first clean frame — were each caught by the new tests.
- No Resolve behavior changed; live test not required. A test asserts no Resolve
  connection is attempted.

## What's New in v2.100.0

**The craft guidance is now readable by any MCP client.** This repository carries a
real body of editorial, colour, and audio guidance — how to tighten a take without
cutting the breath out of it, what frames to look at before applying a grade, which
API calls silently lie. It lived in `.claude/skills/`, `docs/guides/`, and
`docs/kernels/`, and it was reachable only by an agent with this checkout on disk.

Over MCP there is no checkout. A skill that says "open
`docs/guides/color-decision-guide.md`" is a dead end on Codex, Cursor, or a bare SDK
loop: the pointer resolves to nothing, and the agent operates the tools without ever
seeing the reasoning that makes the operation correct.

### Added

- **`knowledge` tool** (36th compound tool) — the corpus served as prose, with no
  Resolve connection involved:
  - `topics(category?)` — the index: id, summary, size, sections, related topics.
    35 topics across `workflow`, `guide`, `kernel`, `reference`, and `repo`.
  - `get(topic, section?, inline?)` — resolved prose. Natural aliases (`"tighten"`,
    `"dead air"`, `"grading"`) resolve to real topics, and referenced guides and
    kernels arrive **inlined**, so what comes back is the manual rather than a path
    to it. `section` returns one heading's subtree.
  - `search(query, limit?)` — ranked topics with excerpts.
  - `capabilities()` — topic counts by category and the corpus directories.
- **`knowledge://topics` MCP resource** — the same index, so hosts that consume
  resources can see what guidance exists without spending a turn on it.
- `setup(action="schema")` now names the guidance, because an agent's orientation
  call is where it will actually be noticed.

### Design notes

- **Inlining stops at one level.** Following references transitively would turn a
  150-line answer into the whole `docs/` tree.
- **Oversized references are summarised, not truncated.** Over the inline budget an
  agent gets the title, summary, section list, and the topic id to fetch — a
  truncated prefix is the first N lines, which is rarely the part that answers the
  question.
- **`reference` topics are terminal.** The 2250-line operating reference and the
  generated API ledgers cross-link each other freely; inlining from them doubles a
  document that was already complete.
- **An unknown section is an error that lists the real ones**, never a quiet return
  of the whole document.
- **Search matches whole words.** Substring counting ranked `resolve-audio` top for
  "dead air", because "air" is inside "F-air-light". Body hits are also normalised by
  document length, so the longest document cannot win on mass alone.

### Guarded against drift

A test asserts every skill, guide, and kernel in the corpus reaches the index, and
that every alias points at a topic that exists. Knowledge added to this repository
later cannot go silently unserved — the failure mode a hand-kept list has every time.

### Validation

- Offline suite: 2849 passed, 1 skipped, 711 subtests, 0 failures.
- Three deliberate mutations (substring search, inlining disabled, unknown section
  returning the whole document) were each caught by the new tests.
- No Resolve behavior changed; live test not required. A test asserts the tool never
  reaches for a Resolve connection.

## What's New in v2.99.3

**Fusion authoring now works on the free edition.** v2.99.2 documented that
`fusion_comp add_tool` could not run there, because the in-app bridge reported
`GetAttrs`/`SetAttrs` as absent on a Fusion tool and `add_tool` calls `GetAttrs`
to build its return value — which took every server-authored Fusion graph with
it. Investigating the fallback found the premise was wrong: **those methods are
present and work.** Invoked directly on free 21.0.3.7, `GetAttrs` returned
`{TOOLS_Name: "Blur1", TOOLS_RegID: "Blur"}` and `SetAttrs` renamed the tool.

The fault was our capability check.

### The API truth underneath

`dir()` on a live Fusion Tool returns 38 names — with `Composition` listed
**twice** — and omits `GetAttrs`/`SetAttrs`. Resolve fabricates a callable for
*any* attribute name, so `dir()` is the only evidence of absence that exists,
which makes an omitted name unrecoverable by probing. The bridge's strict proxy
took that omission as authoritative and answered "has no attribute 'GetAttrs' in
this Resolve build" for a method that was right there.

Resolve's own API objects enumerate correctly — Timeline 60, TimelineItem 88,
Composition 92 — so this is specific to Fusion Tools.

### Fixed

- The bridge client now carries a **curated exception**: names that are
  documented Fusion methods but absent from the enumeration resolve normally,
  and only on an object whose own method list positively identifies it as a
  Fusion object (`ConnectInput`/`FindMainInput`/`GetControlPageNames` on a Tool,
  `AddTool`/`FindTool`/`GetToolList` on a Composition).

  This is deliberately not a global relaxation. Dropping the scoping fails five
  existing tests, including the ones that keep
  `getattr(item, "CreateMagicMask", None)` honest — capability detection on
  Resolve API objects answers exactly as before.

- `fusion_comp add_tool` needed **no change**. The fallback proposed in v2.99.2
  would have papered over a client bug while leaving every other unenumerated
  Fusion method broken.

### Live validation

Free DaVinci Resolve 21.0.3.7, whole graph through the server including a custom
tool name (which requires `SetAttrs`):

```
add_tool   -> {'tool_name': 'FreeBlur', 'tool_type': 'Blur'}
connect    -> {'success': True}
connect    -> {'success': True}
set_input  -> {'success': True}
render     -> PSNR 23.32 dB vs baseline — RENDERED
```

## What's New in v2.99.2

> **Cause corrected in v2.99.3.** The "`fusion_comp add_tool` cannot run on the
> free edition" note below has the wrong cause: `GetAttrs`/`SetAttrs` are present
> on a Fusion tool and work when called — the bridge client reported them absent
> because `dir()` on a Fusion Tool omits them. `add_tool` needed no change.

**The Fusion comp-lock question is closed on Resolve 21.** The v2.98.5–v2.98.8
work isolated the bug on Studio 19.1.3.7 only, and the open caveat was whether
the "renders on 19.1.3.7, ignored on 21.0.4.5" split reported in
[#156](https://github.com/samuelgursky/davinci-resolve-mcp/pull/156) had a
version component on top of it. It does not.

Measured on **DaVinci Resolve 21.0.3.7**, driven through the in-app bridge: the
same wired `MediaIn -> Blur(XBlurSize 20) -> MediaOut` comp, with the value
written through the fixed `fusion_comp set_input`, **renders** — PSNR 24.38 dB
against the no-comp baseline, file shrinking 2,017,973 → 727,261 bytes. That is
the *same* PSNR figure measured on 19.1.3.7 from the same source and blur.

So the split was the `Composition.Lock` bug on both sides, and "a wired comp
renders" now holds across both Resolve generations tested. The `AddFusionComp`
entry in `api_truth` records it.

**Caveat, stated because it matters:** the 21 confirmation is a **free-edition
21.0.3.7**, not the Studio 21.0.4.5 the original report used — no Studio 21 was
available. The graph was also wired with raw proxy calls rather than
`fusion_comp add_tool`, for the reason below; the value write, which is the step
that carried the bug, did go through the real server path.

### Documented

- **`fusion_comp add_tool` cannot run on the free edition.** The in-app bridge's
  proxy exposes `SetInput`/`GetInput`/`ConnectInput`/`FindMainInput` on a Fusion
  tool but not `GetAttrs`/`SetAttrs`, and `add_tool` calls `GetAttrs()`
  unconditionally to build its return value. Comp-level calls all work, so a
  graph can still be wired with raw `comp.AddTool`/`ConnectInput` and driven
  with `fusion_comp` for value writes. New `api_truth` entry; making `add_tool`
  tolerate a missing `GetAttrs` would restore the action there.

## What's New in v2.99.1

**`bulk_set_item_properties` could not set a clip colour on its own.** Reported
and fixed in [#157](https://github.com/samuelgursky/davinci-resolve-mcp/pull/157)
by @matoberuc-afk.

The action documents `clip_color` and `enabled` as per-op keys and has code to
apply both — but that code was unreachable for the op shape that needs it most.
The payload is built by `_merge_property_groups`, which merges only
`properties`/`transform`/`crop`/`composite`/`audio` and the duplicate-keyframe
keys. `clip_color` and `enabled` are not `SetProperty` keys, so they never landed
in that dict, and the `if not properties: continue` guard above returned early —
leaving the `clip_color` branch twenty-five lines below dead on exactly the ops
that carry no transform. Colour triage in one round trip is the main reason to
call a *bulk* setter, and it was the one shape that could not work.

### Fixed

- **A colour-only or enabled-only op is now accepted** and applied.
- **A colour-only op could not fail.** Per-op success was
  `all(row.get("success") for row in ...properties.values())`, and `all([])` is
  `True` — with no property rows the op passed regardless of what `SetClipColor`
  returned. Every branch that runs now votes.
- **The bulk path trusted the bare bool.** It called `item.SetClipColor` directly,
  bypassing `_set_clip_color_checked` — the helper added for
  [#124](https://github.com/samuelgursky/davinci-resolve-mcp/issues/124) that the
  single-item path already used, because that bool lies twice: a name outside the
  16-name Edit-page palette is refused with a bare `False`, and a generator or
  title takes the call, returns `True`, and drops the colour. A failure now
  carries `clip_color_detail`.
- `dry_run` reports `would_set_clip_color` / `would_set_enabled`, and the
  `action_help` example shows the triage shape instead of a `properties`
  dict with a `ClipColor` key that was never a valid `SetProperty` target.

### Live validation

Studio 19.1.3.7: three colour-only ops in one call, live readback
`['Apricot', 'Chocolate', 'Purple']` on the timeline items; a refused colour
returns `success: false` instead of passing on the empty-list vote.

## What's New in v2.99.0

**`timeline.ripple_insert`, and a verified-delete gate on `move_clips`.**
Contributed in [#156](https://github.com/samuelgursky/davinci-resolve-mcp/pull/156)
by @handst97, driven by a real data-loss incident: a session used `move_clips`
with a record offset smaller than the item duration to "open a gap",
`AppendToTimeline` returned items whose ids could not be read, the code counted
them as successful duplicates, and the delete phase removed 26 source clips.

### Added

- **`timeline.ripple_insert`** — insert media-pool source ranges at a record
  point and shift all later video/audio items right. There is no ripple-insert
  primitive in the scripting API, and duplicate-then-delete corrupts the timeline
  when the shift is smaller than an item. This plans a rebuild instead: capture
  every tail item's pool media and source trim, delete the tail (verified),
  re-append it shifted, then place the inserts into the opened gap — **tail
  first, so the worst mid-failure state is a gap, never lost content**. Dry-run
  by default, with straddler / blocker / locked-track / subtitle detection;
  executing is confirm-token gated and archives the timeline first. Shifted items
  are re-created from pool media with transform/crop/composite/retime re-applied;
  grades, keyframes, transitions and link state are NOT preserved (the archive
  keeps them).

### Fixed

- **`move_clips` no longer deletes a source it could not verify.** Each duplicate
  now carries `duplicate_verified` — a live item or a real id recovered from the
  timeline — and sources are deleted only when every duplicate, primary and
  linked, verified. Null-id appends keep the source with an explicit warning.
- **`safe_set_cdl` / `apply_look_to_items` preflight the node.** `NodeIndex` is
  1-based and there is no `GetCDL`, so a bare `False` was undiagnosable; the node
  count is now read before `SetCDL` and a failure comes back with a structured
  reason and a clip-type-aware diagnosis.
- **Magic Mask reports the human step instead of a bare false.** Magic Mask v2
  isolates via operator clicks and the API cannot place them, so `CreateMagicMask`
  on a fresh item can only return `False`. It now returns `needs_hitl` with the
  exact Color-page steps, and the mode aliases (`'Forward'` → `'F'`) are
  normalized — the granular `ti_create_magic_mask` defaulted to a spelling
  Resolve rejects.

### Fixed in review

Three defects found reviewing #156, each with a test that fails without the fix:

- **A dry-run plan archived a timeline version.** `ripple_insert` is the only
  destructive action whose *default* call mutates nothing, and the pending-confirm
  skip only fires while the confirm-token preference is on — so with it off,
  routine planning calls littered the version chain.
- **Asymmetric per-track insert durations left an unreported gap.** Every track
  shifts by the longest inserted run, so a shorter insert leaves a hole the
  readback structurally cannot see — it only checks the positions it placed. The
  plan and the result now carry `gap_frames_by_track` and a warning.
- **Subtitle straddlers passed the feasibility check.** Video and audio
  straddlers already refuse the plan; a subtitle across the insert point stayed
  put while the picture under it moved.

### Live validation

Verified on Studio 19.1.3.7 via `tests/live_ripple_insert_validation.py`:
dry-run plan exact (insert@86448, shift 24, tail 2, no straddlers), confirm-token
round-trip, post-insert layout `[(86400,48),(86448,24),(86472,48),(86520,48)]`,
`readback.missing=[]`, and ZoomX/Y=0.5 surviving the shift with
`property_restore_failures=0`.

### A note on the Fusion measurement in #156

The PR proposed recording that whether an API-created Fusion comp renders is
Resolve-version-dependent, from a 21.0.4 run where a wired comp delivered a render
bit-identical to the baseline. That reading does not survive: those comps were
built and set through this server, and the v2.98.5 comp-lock bug produced exactly
that symptom on any build. Running the PR's own phase-2 harness unchanged against
the fixed code now reports **RENDERED** (Blur 24.38 dB, Transform 7.95 dB) where
it previously reported IGNORED. The `AddFusionComp` entry records the 21.0.4
observation as independent evidence that the lock bug is not specific to
19.1.3.7 — the one thing this machine cannot test.

## What's New in v2.98.8

**The comp-lock mechanism, settled — and the v2.98.6 scope correction was itself
wrong.** Chasing why `add_fusion_mask` and `set_text_plus` escaped the bug found
that they don't. Their test cases were priming the comp and could not have
failed.

### The mechanism

| | |
| --- | --- |
| **Precondition** | The comp's graph was built through lock-wrapped `AddTool`/`ConnectInput`. The same locked write against a graph wired by plain attribute assignment renders normally. |
| **Trigger** | The locked write is the **first value write to that comp** since the build. |
| **Primes it away** | **Any** unlocked value write anywhere in the comp — even writing a *default* value to an *unrelated* tool. Also `StartUndo`/`EndUndo` around the write. |
| **Does not** | A structural `ConnectInput` inside the same lock; a `GetInput` readback after `Unlock`. |

Priming is why every raw-API attempt to reproduce the bug kept coming back green,
and why a control that was supposed to fail didn't.

### The corrected scope

| path | locked write |
| --- | --- |
| `set_input` | **suppressed** |
| `safe_set_inputs` | **suppressed** |
| `set_text_plus` | **suppressed** |
| `add_fusion_mask` | **suppressed** |
| `bulk_set_inputs` | escapes — wrapped in `StartUndo`/`EndUndo` |
| `bulk_set_expressions` | escapes — wrapped in `StartUndo`/`EndUndo` |

So **four of six** paths were genuinely broken, not two. v2.98.5's original
"all six were the same bug" was closer to right than v2.98.6's correction of it;
the two real escapes are explained by their undo wrapper.

### Fixed in the tests

`tests/live_fusion_value_write_validation.py` had two cases that could not fail.
Both set up their graph with plain `SetInput` calls — a text `Size`, a blur
amount — before the call under test, which primed the comp. Removing that:

- the `set_text_plus` case now builds its rooted graph and writes **nothing**
  before the call, leaving the Text+ at its default size;
- the `add_fusion_mask` case composites a **Background** rather than making a
  Blur visible, because a Background is visible at its defaults and needs no
  setup write.

Both now report `PSNR inf -> IGNORED at render` with the lock reintroduced, and
13–17 dB APPLIED without it. The header carries a standing rule: a case in that
file must perform no value write of any kind before the call it is testing.

No production code changed. The v2.98.5 fix has been correct throughout; this is
the third and final correction to the *description* of what it fixed.

## What's New in v2.98.7

**Identifying the mechanism behind the Fusion comp-lock bug — and correcting the
root cause, again.** v2.98.6 recorded that four of the six locked call paths did
not reproduce the bug and that the rescuing mechanism was unknown. Isolating it
turned up something more important: the root cause stated in v2.98.5 and v2.98.6
was incomplete.

### The precondition nobody had noticed

A lock around a value write is **necessary but not sufficient**. The suppression
only reproduces on a comp whose graph was **built through lock-wrapped
`AddTool`/`ConnectInput` calls**. The identical locked write against a graph
wired by plain attribute assignment renders normally.

That is why every raw-API attempt to reproduce the bug came back green — a
control that was supposed to fail, didn't, which is what exposed the gap. Holding
the write constant and varying only how the graph was built:

| graph built via | value written via | render |
| --- | --- | --- |
| MCP `add_tool`/`connect` | MCP, locked | **suppressed** |
| raw attribute assignment | MCP, locked | rendered |
| MCP `add_tool`/`connect` | raw, locked | **suppressed** |
| raw attribute assignment | raw, locked | rendered |

### What rescues it

Given that precondition, with the locked write in place:

| after the locked write | render |
| --- | --- |
| nothing | **suppressed** |
| a subsequent **unlocked** value write | rescued |
| `StartUndo` / `EndUndo` around the write | rescued |
| a structural `ConnectInput` inside the lock | **suppressed** |
| a `GetInput` readback after `Unlock` | **suppressed** |

So `bulk_set_inputs` and `bulk_set_expressions` escape the bug because both wrap
their write in `StartUndo`/`EndUndo`. **That answers the open question from
v2.98.6 for two of the four.** `add_fusion_mask` and `set_text_plus` still escape
for reasons not identified — but the two obvious candidates, a structural call in
the same lock and a readback, were tested and ruled out.

### Nothing changed in the fix

The v2.98.5 change stands and remains verified: removing the lock from the value
write is what makes these paths render, and the live harness still fails without
it. What changed is the explanation, in `api_truth` and the harness docs.

### Added

- `tests/live_fusion_lock_mechanism_probe.py` — the isolation experiment itself,
  kept runnable rather than written up and thrown away, so the result can be
  re-checked on another Resolve build instead of taken on trust. It is not a
  pass/fail test; it prints the five-case matrix above.

## What's New in v2.98.6

> **Corrected in v2.98.8.** The table below says four of six paths escape the
> bug. Two of those four — `set_text_plus` and `add_fusion_mask` — do not; their
> test cases primed the comp with setup writes and could not fail. Only
> `bulk_set_inputs` and `bulk_set_expressions` genuinely escape.

**Correcting the scope of the v2.98.5 Fusion fix, and covering all six paths
with a render.** v2.98.5 removed a `Comp.Lock()` from six Fusion value writes and
described all six as the same bug. Only two of them were proven with a render at
the time; the other four were changed by inference. Extending the live harness to
cover the remaining four showed that inference was too broad.

Every site was mutation-checked by reintroducing the lock and re-rendering on
Studio 19.1.3.7:

| call path | with the lock back |
| --- | --- |
| `set_input` | **PSNR inf — suppressed** |
| `safe_set_inputs` | **PSNR inf — suppressed** |
| `bulk_set_inputs` | unchanged, still rendered |
| `bulk_set_expressions` | unchanged, still rendered |
| `add_fusion_mask` | unchanged, still rendered |
| `set_text_plus` | unchanged, still rendered |

The two that break are the two where the locked write is the only thing the call
does. The four that survive each do something else in the same call that appears
to invalidate the graph anyway — `bulk_set_inputs` and `bulk_set_expressions`
wrap the write in `StartUndo`/`EndUndo`, `add_fusion_mask` performs an `AddTool`,
and `set_text_plus` writes a string rather than a number. **Which of those is the
rescuing mechanism is not established** — only that the four do not reproduce.

No code changed back. Removing the lock from a single write buys nothing and
costs nothing, and treating the four as merely unexplained rather than proven
safe is the conservative reading. What changed is the claim: `api_truth`,
`docs/SKILL.md` and the AST guard's failure message now state the measured scope
instead of "any value write".

If you read the v2.98.5 notes and concluded every Fusion parameter this server
ever wrote was ignored at render, that was overstated — it was true for
`set_input` and `safe_set_inputs`.

### Tests

`tests/live_fusion_value_write_validation.py` grows from two cases to six,
covering every site the fix touched:

```
set_input: PSNR 24.375987 -> APPLIED at render
safe_set_inputs: PSNR 24.375987 -> APPLIED at render
set_text_plus: PSNR 13.33844 -> APPLIED at render
bulk_set_expressions: PSNR 24.375987 -> APPLIED at render
bulk_set_inputs: PSNR 24.375987 -> APPLIED at render
add_fusion_mask: PSNR 30.369794 -> APPLIED at render
```

The `set_text_plus` case builds a rooted `MediaIn -> Merge -> MediaOut` graph
with the Text+ in the foreground — a comp whose MediaOut is fed only by a Text+
is bypassed at render for an unrelated reason and would have failed for the
wrong cause. The `add_fusion_mask` case cannot use a baseline/after comparison,
because a default-sized mask still changes the render; it builds the same graph
twice, once with a default mask and once with an explicitly tiny one, and
requires the two renders to differ.

Four of the six cases do not discriminate the lock. They are kept because they
still prove the write reaches the render — the property that matters, and the
one no readback can check.

## What's New in v2.98.5

> **Scope corrected in v2.98.6.** Six sites had the lock removed, but only
> `set_input` and `safe_set_inputs` were ever verified to suppress the render.
> The other four were changed by inference, and mutation-checking each of them
> afterwards showed the lock does not break them. No code changed back; only the
> claim did. See the v2.98.6 entry above for the per-site measurement.

**Every Fusion parameter this server wrote was ignored at render.** A value
write (`SetInput` / `SetExpression`) wrapped in `Comp.Lock()`/`Unlock()` is
stored in the graph and reads back correctly — `GetInput` returns it, and so
did this server's own `get_input` — while the delivered render ignores it
completely. Found on 2026-08-21 while re-running a Fusion isolation on Studio
19.1.3.7 to settle a conflicting measurement reported in
[#156](https://github.com/samuelgursky/davinci-resolve-mcp/pull/156).

Measured on Studio 19.1.3.7 with `MediaIn -> Blur(XBlurSize 20) -> MediaOut` on
a media-backed clip, rendering the same 48 frames to H.264 each time:

| value written via | render vs no-comp baseline |
| --- | --- |
| `fusion_comp set_input` (write inside `Comp.Lock()`) | PSNR **inf** — bit-identical, ignored |
| the same write, lock removed | PSNR **24.38 dB**, 2.0 MB → 727 KB |
| raw `tool.XBlurSize = 20.0` | PSNR **24.38 dB** |
| raw `tool.SetInput("XBlurSize", 20)` | PSNR **24.38 dB** |

The variable was isolated against the comp handle (`AddFusionComp`,
`GetFusionCompByIndex` and `GetFusionCompByName` all render), the node name, and
the write form. Only the lock around the write decides it. **Structural** edits
are unaffected — `AddTool` and `ConnectInput` inside a lock render normally — so
this is not "Lock is unsafe"; the lock suppresses the parameter-change
invalidation that a value write depends on.

### Fixed

- **Six value-write sites no longer hold a comp lock across the write:**
  `fusion_comp set_input`, `fusion_comp safe_set_inputs`, `bulk_set_inputs`,
  `bulk_set_expressions`, the Text+ writer behind `set_text`, and
  `add_mask` — where the lock spanned `AddTool` *and* every input write, so a
  mask was created at default size and position and every parameter the caller
  passed did nothing. Structural work keeps its lock; in `add_mask` the lock now
  closes after the node is created and renamed.

### Why this went unnoticed

Every readback the API offers agreed with the value that was written. This is
the failure mode the repo's own guidance describes — prove a Fusion or grade
claim with a rendered frame, never with readback — except the cause was ours,
not Resolve's. It also explains an unknown share of past "the comp was ignored"
reports, which look identical from the API side.

### Tests

- `tests/live_fusion_value_write_validation.py` — renders a baseline, writes a
  blur size through the compound tool, renders again, and asserts PSNR actually
  moved. Disposable project, synthetic media, restores the previous project.
- `tests/test_fusion_value_write_lock.py` — AST guard failing any value write
  that sits inside a `Comp.Lock()`/`Unlock()` region, with a self-check that the
  guard can still see a known-bad shape.

Both were mutation-checked against the pre-fix code: reintroducing the lock in
`set_input` makes the live harness report `PSNR inf -> IGNORED at render` and
fails the offline guard.

- `api_truth`: new `Composition.Lock` entry; the `AddFusionComp` entry records
  that its 2026-08-02 rooted-comp result **reproduced** on 19.1.3.7 (PSNR 24.38 dB).

## What's New in v2.98.4

**Setup reported success over an install that could never work.** Reported and
fixed in [#154](https://github.com/samuelgursky/davinci-resolve-mcp/pull/154) by
@DadManBlues, from a DaVinci Resolve Studio 21.0.4 install on `F:\Blackmagic
Design\DaVinci Resolve` (Windows 11). The chain: `RESOLVE_PATHS["Windows"]["lib"]`
held a single hardcoded `C:\Program Files\...` candidate, so `find_resolve_paths()`
returned `lib_path=None`; `build_server_env()` wrote that out as
`"RESOLVE_SCRIPT_LIB": ""`, which reads as configured in the config file but is
falsy to the loader, so it fell back to the same missing path; the connection
check then failed with `DLL load failed` in the middle of the output, and the
installer's last line said `Setup complete!`. Every tool afterwards failed with
`SCRIPTING_UNAVAILABLE`, whose remediation pointed at the Resolve edition and the
External-scripting preference — both already correct.

### Fixed

- **Resolve is now found outside the default install location.**
  `resolve_runtime.running_resolve_lib()` derives the scripting library from the
  running Resolve's own image path, which needs no guessing on any platform, and
  `platform.discover_scripting_lib()` covers cold installs: `%PROGRAMFILES%` /
  `%PROGRAMW6432%` / `%PROGRAMFILES(X86)%` plus the existing drive letters on
  Windows (two fixed paths each, no directory walk), both bundle locations on
  macOS — the App Store build installs to `/Applications/DaVinci Resolve.app`
  rather than `/Applications/DaVinci Resolve/DaVinci Resolve.app`, the same class
  of miss — and the `/opt/resolve` layouts on Linux. Discovery runs only when the
  platform default is absent and no usable env override exists, and the default
  is kept when discovery finds nothing, so the error message still names the
  location people expect.
- **Empty environment values are omitted rather than written.**
  `build_server_env()` no longer emits `"RESOLVE_SCRIPT_LIB": ""`.
- **A failed verification is no longer reported as success.** The `Library: Not
  found (optional — API path is sufficient)` line was wrong and is corrected; a
  DLL-load failure is diagnosed explicitly, naming the current
  `RESOLVE_SCRIPT_LIB`, before the Python 3.13+ ABI theory; and setup ends in
  `Setup incomplete — the scripting API did not load.`, still listing any configs
  it wrote and marking them non-functional.

### Fixed in follow-up review

- **The no-clients branch still printed `Environment ready!`** over a failed
  verification, and **`main()` returned `None` either way**, so
  `npx davinci-resolve-mcp setup` in a script or CI saw exit status 0 over a dead
  install — the same lie as `Setup complete!`, one block further down. The
  summary line and the exit status now agree.
- **Two bare `except Exception` fallbacks narrowed to `ImportError`.** A defect
  raised inside `running_resolve_lib()` or `discover_scripting_lib()` would have
  been laundered into "nothing found" and the caller would have gone on to report
  the platform default — this repo's recurring silent-fallback bug class.
- **`_windows_lib_candidates` docstring corrected.** It claimed only fixed drives
  are probed (there is no `GetDriveTypeW` check, so a connected network drive is
  probed too) and that it runs on every connection attempt (`get_resolve_paths()`
  is import-time, so the real cost is one `ps`/`wmic` spawn at server startup, and
  only when the default is already missing).

### Tests

`tests/test_scripting_lib_discovery.py` (21 cases): library derivation on Windows
and macOS layouts, WMIC-quoted command lines, the three `None` paths, the
per-platform candidate lists, override-beats-discovery precedence, the surviving
platform default, the omitted empty key, both reporting behaviours, and the exit
status in all three of its states. The `GetResolvePathsDiscoveryTests` cases force
the platform default absent — without that they check nothing on a machine where
Resolve *is* at the default path, and on macOS they fail outright; neither the
Linux CI box nor the Windows machine that prompted the fix shows it, because on
both the default is already missing for real.

## What's New in v2.98.3

**`fusion_comp` could never delete a Fusion keyframe.** Reported in
[#155](https://github.com/samuelgursky/davinci-resolve-mcp/issues/155) by
@Andrei-59, with the root cause already identified: the handler called a method
that does not exist. The diagnosis was correct, and the suggested replacement is
confirmed here against a live build.

### Fixed

- **`delete_keyframe` called `RemoveKeyFrame()` on a Fusion Input.** No such
  method exists there. Keyframes do not live on the Input — they live on the
  spline modifier connected to it, which is what `add_keyframe` attaches via
  `AddModifier(input_name, "BezierSpline")`. The action now reaches that spline
  through `inp.GetConnectedOutput().GetTool()` and calls `DeleteKeyFrames(time)`
  on it. Introduced with the tool in v2.1.0 and broken for every input, every
  frame, and every tool since; there is no version of the server in which it
  worked.

- **The failure surfaced as `'NoneType' object is not callable`.** The
  fusionscript bridge resolves an unknown attribute to `None` instead of raising
  `AttributeError`, so the bad lookup succeeded silently and only died at the
  callsite — an error naming neither the method nor the object. Every branch of
  the action now returns the normal error envelope: `FUSION_INPUT_NOT_ANIMATED`
  when the input has no modifier, `FUSION_KEYFRAME_NOT_FOUND` when nothing is
  keyed at that frame (the frame list is included in `state`),
  `FUSION_DELETE_KEYFRAMES_UNSUPPORTED` when the modifier has no removal method,
  and `INVALID_FRAME` for a non-numeric `time`. The existing `_has_method` guard
  — which exists precisely for this silent-`None` class — is applied before the
  call rather than after it.

- **Success is verified by readback, not by the return value.** Live testing
  showed `DeleteKeyFrames()` returns `None` whether or not it removed anything,
  so trusting the return would have reported failure on every successful
  delete — and trusting the absence of an exception would have reported success
  on every silent no-op. The handler re-reads the keyframe list and returns
  `FUSION_DELETE_KEYFRAME_NOOP` if the frame is still there. On success it
  returns `{success, time, remaining_keyframes}`.

### Testing

- `tests/test_fusion_comp_targeting.py` gains eleven `delete_keyframe` cases,
  including a regression test that models the bridge's silent-`None` attribute
  lookup and asserts the handler never reaches for `RemoveKeyFrame` on the
  Input. The action previously had no test coverage at all.
- `tests/live_fusion_delete_keyframe_validation.py` is a new self-contained live
  harness: it creates a scratch project, inserts a Fusion composition clip (no
  media needed), and reports which keyframe methods the Input and the spline
  actually expose before asserting the delete.

### Verified live

Validated on **DaVinci Resolve Studio 19.1.3.7** (macOS). `RemoveKeyFrame`
confirmed absent on the Input and resolving to `None`; `DeleteKeyFrames`
confirmed present on the `BezierSpline` and confirmed to remove the key. The
reporter's exact reproduction — `add_keyframe` then `delete_keyframe` on the
same tool/input/frame — was run end-to-end through the patched handler and
succeeds. Not re-verified on Studio 21.0.4.5, the reporter's build.

## What's New in v2.98.2

**A tool installed next to the server was invisible to it.** Reported in
[#153](https://github.com/samuelgursky/davinci-resolve-mcp/issues/153) by
@7daysdedicated as an encoding fault in the whisper probe. The probe turned out
not to be the cause, and the encoding fault turned out to be real somewhere
else, so both are fixed here.

### Fixed

- **The server's own virtualenv was not searched for command-line tools.**
  `pip install openai-whisper` writes a `whisper` executable into
  `venv/Scripts` on Windows and `venv/bin` elsewhere, and that directory is on
  PATH only while the environment is *activated* — which nothing does, since the
  client launches `venv/python server.py` directly. So `shutil.which("whisper")`
  returned None and `capabilities` reported `whisper_cli.available: false` for a
  tool sitting beside the interpreter looking for it, with nothing in the
  response to say why. The interpreter's script directory now leads the PATH
  augmentation that already covered Homebrew and `/usr/local`. Not
  Windows-specific: the same gap existed on macOS and Linux.

- **Text-mode reads of a child process decoded with the locale codec.** Nineteen
  `subprocess.run(..., text=True)` calls across the server, panel, and utils had
  no `encoding=`, so Python used the platform locale — cp1252 on a default
  Windows install, a codec with no mapping for most of what a media tool prints.
  A clip name in Japanese from the advanced-server bridge, a localized WMIC
  banner, or a user script's output was then a `UnicodeDecodeError` raised
  inside a call whose job was to answer a yes/no question. All nineteen now read
  UTF-8 with `errors="replace"`, so the answer can be wrong in the last
  character but never an exception. The WMIC read matters most: it feeds the
  second-instance guard fixed in v2.97.6, and it must fail to "cannot tell".

- **Child Python processes are handed `PYTHONIOENCODING=utf-8`.** A script run
  through `resolve_control` writes into a pipe, where Python picks the locale
  codepage rather than the console's, so printing a non-Latin-1 character killed
  the script with `UnicodeEncodeError` — and the failure read as the script's
  fault rather than the pipe's. The transcription path already did this; the
  script-runner did not.

### Added

- **`tests.test_child_process_text_encoding`** — a static walk over `src/` that
  fails on any text-mode child read without an explicit `encoding=`. Static
  because the exception needs a non-UTF-8 locale to reproduce and no machine in
  this suite has one: the missing argument is visible in the source, the
  `UnicodeDecodeError` is only visible in Tokyo. The walk carries a test that it
  can still see an offender, since a guard that quietly matches nothing passes
  forever. Also covers the venv script directory being on PATH, first, and
  idempotently.

### Note on the report

The diagnosis in #153 named `whisper --help` as the probe. That string is
display text in the install-guidance table and is never executed — detection is
`shutil.which("whisper")` — and the transcription path already decoded UTF-8 and
already set `PYTHONIOENCODING`. The cause was the PATH gap the report mentioned
last, in passing, as an aside about `pip`. Worth stating plainly, because the
reporter's `whisper.cmd` workaround set the encoding *and* put a `whisper` on
PATH, and only the second half was doing the work.

### Changed

- `docs/install.md` says which environment optional packages have to be
  installed into, which is the part that was undocumented.

## What's New in v2.98.1

**The Bash guard could be walked past with a newline.** Reported and fixed in
[#152](https://github.com/samuelgursky/davinci-resolve-mcp/pull/152) by
@fitfam, who found both holes by executing payloads against the hook rather
than reading it.

### Fixed

- **`split_commands()` did not split on newlines.** It knew `&&`, `||`, `;` and
  `|`, so a multi-line block was a single segment: `argv0` came from the first
  line, and a non-mutating first line returned before anything under it was
  looked at. `mkdir -p footage/_superseded` then a newline then
  `mv footage/clip.mp4 footage/_superseded/` passed, while the same two commands
  joined by `;` denied. Either answer is defensible on its own; giving two
  different answers to what a shell treats as the same command is what made the
  guard trainable around.

- **The ffmpeg branch exempted an output that equalled an input.** The output
  operand was dropped when it matched a `-i` value — which is exactly
  `ffmpeg -i master.mp4 master.mp4`, the in-place overwrite the hook's own deny
  message calls unrecoverable. Independent of the first hole: the single-line
  form was allowed too.

### Changed

- The trailing operand is no longer read as an output when it is the value of a
  `-i` immediately before it. `ffmpeg -i master.mov` prints stream info and
  writes nothing, and denying a read is how a guard teaches an agent to route
  around it. `ffmpeg -i x.mp4 x.mp4` still denies — the token there is not
  preceded by `-i`.

### Added

- **`tests.test_source_media_guard`** — the hook had no tests, which is why two
  holes in it needed a payload matrix to find. It runs the hook the way the
  harness does, a PreToolUse payload on stdin and a decision on stdout, and
  fails on exactly the four rows this release fixes. The newline/`;` pair is
  asserted as a pair: not that either answer is right, but that the guard cannot
  give two.

### Note

- Splitting on newlines means multi-line text carried *inside* a command — a
  heredoc body, a commit message — is now read as commands too, so text that
  merely quotes `rm camera.mov` is denied. That is the right way round for a
  tripwire; write the text to a file first. #152 was itself blocked this way on
  its first attempt, by the fix it was proposing.

## What's New in v2.98.0

**The control panel could be driven by any web page you visited.** Reported
privately, with the chain worked out end to end. Fixed here; the transport
state file and panel pidfile move out of shared locations at the same time.

### Security

- **`GET /api/mcp/status` handed out the networked-transport bearer token to
  anyone who could reach the port.** It was the one privileged route with no
  loopback check, and its payload included the token that authenticates the
  `--transport streamable-http` MCP instance — i.e. full Resolve control.
- **No Host or Origin check, and POST bodies of any Content-Type were parsed.**
  A page on any site could POST to the panel (CSRF), and a DNS-rebinding page
  could read its responses. Chained: visit a page → it starts the networked
  transport via `/api/mcp/transport/start` → reads the token from
  `/api/mcp/status` → owns the MCP toolset.
- **The bind address was a tool parameter.** `open_control_panel(host=...)`
  passed straight through, so a prompt could put the unauthenticated panel on
  `0.0.0.0`.

  What changed:

  - **Per-launch bearer token on every route except the static shell at `/`.**
    `open_control_panel` mints `secrets.token_urlsafe(32)`, passes it to the
    child through the environment (not argv, which `ps` shows to every local
    user), records it 0600, and returns the URL with the token in the
    **fragment** (`http://127.0.0.1:8765/#token=…`) — browsers never send
    fragments, so it stays out of request lines and logs. The panel JS keeps
    it in `localStorage`, sends `Authorization: Bearer …` on every fetch, and
    exchanges it once (`POST /api/session`) for an `HttpOnly; SameSite=Strict`
    cookie so thumbnail `<img>` loads work. A bare `http://127.0.0.1:8765` now
    shows a "Control panel locked" screen pointing back to `open_control_panel`.
  - **A single gate at the top of `do_GET`/`do_POST`:** `Host` must be a
    loopback host (defeats DNS rebinding); `Origin`, when present, must be a
    loopback origin (defeats CSRF); `POST` must be
    `Content-Type: application/json` (a cross-site form cannot send it, and a
    cross-site `fetch()` with it needs a CORS preflight the panel never
    answers). Each check fails closed with 403/415 before any route runs.
  - **`host` is no longer an AI knob.** `open_control_panel` refuses anything
    but `127.0.0.1` / `localhost` / `::1` with no override, and
    `src.analysis_dashboard --host` does the same at argparse — matching the
    free-edition bridge, which already threw on non-loopback.
  - **Secrets on disk are private.** The transport state file
    (`mcp_transport.json`, holds the transport token) leaves
    `tempfile.gettempdir()`, and the panel pidfile (now holds the panel token)
    leaves `~/Documents`; both live under `~/.davinci-resolve-mcp/` (0700),
    written 0600 via the new `src/utils/private_state.py`, with a best-effort
    `icacls` restriction on Windows. `DAVINCI_RESOLVE_MCP_STATE_DIR` overrides
    the directory.
  - **The launcher still recognises a panel it has no token for.** A panel
    that survived an MCP restart from before this scheme answers 401 with a
    self-identifying body; `open_control_panel` reports it as `stale_running`
    (nobody can log in to it) with the `force_restart=true` remediation
    instead of handing out an unusable URL.

  `SECURITY.md` previously said the server "does not expose a network
  listener"; it now describes both opt-in local HTTP surfaces (panel and
  networked transport) and their posture. Kept as-is: the default port stays
  8765 (with Host/Origin/token in place its guessability is not the barrier)
  and the transport token is still shown in the panel's MCP card, now behind
  the panel's own auth.

### Added

- `tests.test_control_panel_auth` boots the real `Handler` on an ephemeral
  port and asserts each guard over HTTP: `/api/mcp/status` 401 without the
  token and no transport secret in the 401 body; non-loopback `Host` rejected
  even with a valid token; `localhost` / `[::1]` / bare `127.0.0.1` accepted;
  cross-site `Origin` rejected; non-JSON POST → 415; no CORS preflight answer;
  cookie issued only via bearer, `HttpOnly` + `SameSite=Strict`, then
  sufficient on its own; wrong token / wrong cookie → 401; the static shell
  never contains the token. Plus the launcher's 401-probe recognition, the
  `host=0.0.0.0` refusal, and 0600 on the private state files.
  `tests.test_open_control_panel` gains the token-unknown → `stale_running`
  case and asserts the issued URL is the token-bearing one.

## What's New in v2.97.7

**`grab_and_export` deleted files it never created.** Reported in
[#151](https://github.com/samuelgursky/davinci-resolve-mcp/issues/151).

### Fixed

- **The cleanup step removed a directory diff, not the export.** It listed the
  caller's folder before the export and again after, and treated the difference
  as "what this call produced" — so anything that appeared in that window was
  attributed to the call, inlined into the response, and deleted: a background
  render, a file copy, a cloud sync, or a second `grab_and_export`. It then
  finished with `os.rmdir(folder_path)`, removing a directory the caller had
  chosen and this server had not created.

  `_resolve_safe_dir` made the overlap concrete rather than theoretical. Every
  sandbox/temp path is redirected to one shared `~/Documents/resolve-stills`,
  which is also the folder the documented `/tmp/...` examples land in, so two
  calls aimed at different temp folders arrived in the same place and each swept
  up the other's output.

  The export now goes to a private staging directory created inside
  `folder_path` for that one call, so what it produced is known by construction
  instead of inferred. Cleanup removes that directory and nothing else;
  `folder_path` is removed only when this call created it and left it empty. A
  folder the caller already had is theirs, empty or not. With `cleanup: false`
  the files move up into `folder_path` under a non-colliding name rather than
  overwriting a still already sitting there — Resolve numbers stills per export,
  so a second call collides with the first by default.

  Deletion is now confined to one helper that refuses any path it did not name,
  which is the property that was missing: the old code path could be handed the
  caller's folder and delete its contents.

  The inlining half matters too. A file that was never ours was read into the
  response, so an unrelated document sitting in the export folder could reach an
  assistant's context. Only staged files are read now.

  Live-verified after release on Studio 19.1.3.7 (macOS, Color page, Gallery
  panel open): Resolve's `ExportStills` writes into the staging subdirectory — a
  257 KB JPEG and its 28 KB `.drx` came back inlined — a bystander file in the
  same folder survived untouched, the folder itself was kept, and
  `cleanup: false` moved both files up into it. That subdirectory write was the
  one claim the offline fixtures could not make.

### Added

- `tests.test_gallery_still_export_cleanup` runs the action against a real temp
  filesystem with a fake album that writes the way Resolve does, because the
  defect was in what the filesystem looked like afterwards, not in any return
  value: a bystander file written *during* the export must survive and must not
  appear inlined; a pre-existing folder must not be removed; a folder the call
  created must still be cleaned up; `cleanup: false` must not overwrite; and no
  staging directory may survive any exit path, including the two early error
  returns. All fail on 2.97.6.

## What's New in v2.97.6

**On Windows the server could not see the Resolve it was driving.** Reported in
[#150](https://github.com/samuelgursky/davinci-resolve-mcp/issues/150) with the
root cause traced, the fix proposed, and a case table — all of it correct.

### Fixed

- **`runtime_mode` reported `running: false, instances: 0` on every stock
  Windows install.** WMIC wraps a command line in double quotes when the
  executable path contains spaces, which the default install path always does
  (`"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe"`). The
  line therefore *ends* with `"`, and `_is_resolve_command()` required it to end
  with `Resolve.exe`. The trailing-flag stripper above the test did not help: it
  removes ` -flag` tokens and leaves the closing quote as the final character.
  A leading quote is now read for what it is — the executable is what sits
  inside the first quoted span, and everything after the closing quote is
  arguments. That also tightens rejection: `"…\cmd.exe" /c start … Resolve.exe`
  is a launcher, not an instance.

  The reading was the visible half. The consequential half is that
  `get_resolve()` asks this same question before auto-launching, precisely so a
  failed connect to a live Resolve does not open a second application — the
  guard whose comment records being "reported three times before it was
  traced". On Windows its input was a permanent `False`, so the path it exists
  to block was open: connect fails (modal dialog, mid-launch, scripting toggled
  off) → "nothing is running" → launch a second Resolve. `_not_connected_error()`
  reads the same signal, so a Windows user whose Resolve *was* running got the
  "not running, auto-launch failed, check your Studio install" text instead of
  the preference or bridge fix that actually applied. `headless` was
  unreachable too — it is only computed once something is found running, so
  `-nogui` instances were indistinguishable on Windows.

- **A successful install ended in a traceback under a redirected stdout.** The
  installer prints box-drawing and check-mark glyphs. A Windows console carries
  them, but redirecting stdout falls back to the locale code page — cp1252 by
  default — and `print(f"  {'─' * 50}")` in the summary raised
  `UnicodeEncodeError` after every client had already been configured, so a
  working run looked like a failed one
  (`npx davinci-resolve-mcp setup --clients manual 2>&1 | tail`). Streams that
  cannot encode those glyphs are now reconfigured to UTF-8 with
  `errors="replace"`; a console that can already carry them is left alone
  rather than re-encoded underneath the user.

### Added

- `tests.test_headless_runtime` covers the quoted Windows command line —
  bare, trailing-whitespace (what WMIC actually prints), and `-nogui` — plus
  the quoted-launcher line that must still be rejected, so the fix cannot
  become a substring test by another route. `tests.test_cdl_and_install_config`
  gains `ConsoleEncodingTests`, including a child interpreter run with
  `PYTHONIOENCODING=cp1252` and a piped stdout: the exact shape of the reported
  failure. Both suites fail on the pre-fix code.

## What's New in v2.97.5

**`npm ci` was failing outright, and nothing in the release path noticed.**
No server behavior changed; this is packaging and release-process hardening.

### Fixed

- **`package-lock.json` was seven releases stale.** It still carried
  `2.90.0`, and — the part that actually broke things — two
  `optionalDependencies` added since then, `js-yaml` and `pg`, were never
  locked. `npm ci` refuses to install at all when the lockfile and
  `package.json` disagree, so every reproducible install path failed with
  `EUSAGE — Missing: js-yaml@4.3.1 from lock file` (plus `pg` and its nine
  transitive deps). CI, fresh contributor clones, and container builds all hit
  it. `npm install` and `npm publish` resolve independently of the lockfile
  and stayed green throughout, which is why it survived seven releases.
  Regenerated with `npm install --package-lock-only`; `npm ci` now installs
  175 packages clean.

### Added

- **`tests.test_import::test_package_lock_in_sync`** — asserts both version
  fields in the lockfile match `package.json`, and that the root
  `dependencies` / `devDependencies` / `optionalDependencies` blocks match
  exactly. The second half is the one that matters: the version fields being
  right is not evidence `npm ci` works, and dependency drift is what actually
  breaks it. Verified to fail on each drift mode independently.

### Changed

- `docs/process/release-process.md` lists `package-lock.json` under "Files To
  Update" with the regeneration command, and Required Validation now
  regenerates the lockfile before `test_import` reads it. The lockfile was
  never on the checklist, which is why the drift was never a step anyone
  skipped — it was a step that did not exist.

## What's New in v2.97.4

**Drift is caught at the edit, not at publish time.** Tooling and docs only —
no server behavior changed, and no Resolve live run was required or performed.

### Added

- **Two opt-in `PostToolUse` hooks** in `.claude/hooks/`. Like the two existing
  `PreToolUse` guards, they ship as scripts and are **not** wired up by default;
  opt in via your own gitignored `.claude/settings.local.json` (the block is in
  [docs/README.md](docs/README.md)).
  - `agent_rules_drift_check.py` runs `node scripts/agent-rules/generate.mjs
    --check` after an edit to anything the generator actually reads
    (`docs/SKILL.md`, `docs/kernels/README.md`, `resolve-advanced/README.md`,
    and `generate.mjs` itself, which carries the DOMAINS manifest inline) or to
    `AGENTS.md`, which it writes. It separates the generator's two exit-1
    paths: real staleness always prints `N agent-rule file(s) are stale`, a
    throw never does — and telling a session to regenerate when the generator
    is the thing that crashed sends it in a circle. Watching outputs but not
    inputs was the original bug: bumping the compound tool count in
    `docs/SKILL.md` left five generated files stale and the hook said nothing.
    **A new generator input has to be added to `SOURCE_PATHS` or the hook goes
    silent on exactly the edit it exists for.**
  - `run_matching_test.py` runs the matching `tests/test_<module>.py` after an
    edit under `src/`, resolving the project venv (`venv/bin/python`) before
    `python3` so `pytest` is importable rather than reporting a false failure.
    A fast partial net, not coverage: 72 of the 126 modules under `src/` follow
    the convention, densely in `src/utils/` and not at all for `src/server.py`,
    `src/granular/common.py`, or `src/control_panel.py`. Silence means "no
    matching test file", not "this edit is fine".
- **`drift-guard-reviewer` subagent** (`.claude/agents/`) — runs the drift-guard
  test family plus the adjacent checks `npm-publish.yml` runs before every
  publish, on demand and in its own context. It reports what is stale and which
  regeneration command fixes it; it does not fix anything.
- **`release-check` skill** (`/release-check`) — a thin wrapper that reads and
  follows [docs/process/release-process.md](docs/process/release-process.md)
  from disk. It deliberately does not restate the checklist: a second copy can
  drift from the original, which `CLAUDE.md` prohibits.

### Changed

- `docs/README.md` documents all four hooks, all three subagents, and the new
  skill in place, including the opt-in JSON block.

Contributed by [@Grimthereapper](https://github.com/Grimthereapper) in
[#149](https://github.com/samuelgursky/davinci-resolve-mcp/pull/149).

## What's New in v2.97.3

**`source_end` no longer has the start timecode baked into it.** Reported by
[@TheUnlockr](https://github.com/TheUnlockr) in
[#147](https://github.com/samuelgursky/davinci-resolve-mcp/issues/147) against
Studio 21.0.4.5, and confirmed live here on 19.1.3.7.

### Fixed

- **The two source frame fields did not share an origin.** `source_start` comes
  from `GetSourceStartFrame`, which is file-relative. `source_end` came from
  `round(GetSourceEndTime x fps)` — and both second-readers answer in the media's
  TIMECODE space, so on any clip with a non-zero start TC the whole start
  timecode landed in `source_end`. On the reporter's Canon MP4 starting at
  04:18:37;25 that produced `source_end` 468800 on a clip 10650 frames long. The
  two fields could not be differenced, and anything sizing a pull from them —
  `extract_source_frame_ranges`, `create_variant_from_ranges`, conform and
  consolidation — was working from a number ~44x the clip's length.
- `source_end` is now the SPAN between the two second-readers, anchored on
  `source_start`. The offset cancels in the difference, so the result is
  file-relative under either convention and needs no timecode parsing, no `Start
  TC` property read, and no drop-frame arithmetic. On media starting at
  00:00:00:00 the correction is exactly zero, so nothing moves there.
- **The `_seconds` pair is rebased to match.** `source_start_seconds` used to
  disagree with `source_start / source_fps` on any camera clip, despite being
  documented as seconds into the source file. All four `source_*` fields are now
  file-relative and say so.

### Why the existing suite could not catch it

The v2.93.0 work that introduced this was live-validated — but with synthetic
media, which starts at 00:00:00:00. That makes the offset exactly zero, so a
timecode-absolute reader is indistinguishable from a file-relative one in
precisely that setup. The new harness closes the gap by generating synthetic
media that *carries* a timecode.

### Added

- `tests/live_source_timecode_validation.py` — a controlled pair: two clips from
  the same generator, identical except that one carries `-timecode 04:18:37;25`,
  both cut into a timeline at a different rate. Any difference in the reported
  fields is attributable to the timecode and nothing else. 17/17 checks pass on
  Studio 19.1.3.7.
- Six unit tests in `tests/test_source_frame_rate.py` pinning the reporter's
  measured numbers, including that zero-TC media is untouched.

### Documentation

- The `GetSourceStartFrame` api_truth entry claimed the v2.93.0 product was "a
  SOURCE frame by construction". That holds only for media starting at
  00:00:00:00; the entry now says so, records the live confirmation, and carries
  the rate-conversion caveat below.

### Validation

- Live on **DaVinci Resolve Studio 19.1.3.7** (not the 21.0.4.5 of the report):
  on the timecoded copy `GetSourceStartTime` read 15527.812 s where the
  file-relative answer is 10.010 s while `GetSourceStartFrame` read 300 — the two
  readers in different spaces on the same edit point. The pre-fix formula gave
  465461 on a 1799-frame clip. After the fix the timecoded copy reports exactly
  what the zero-TC control reports, for every range tried.
- One caveat the harness deliberately does *not* assert: `source_end` is not the
  `endFrame` you sent when the rates differ. The record duration quantizes to
  whole timeline frames, so a 93-source-frame request at 29.97 into a 24 fps
  timeline consumes ~92.4 and *both* copies report 392. That is rate conversion,
  not a timecode error.

## What's New in v2.97.2

**The panel's inventory snapshot survives a large project.** Follow-up to the
v2.97.1 fix: now that `inventory_limit` actually reaches the panel, the cache it
feeds has to cope with what arrives.

### Fixed

- **The localStorage snapshot silently stopped working above ~5MB.** The panel
  caches the last inventory so reopening it paints the previous view instantly
  instead of "connection pending". That write was unbounded — and with
  `inventory_limit` reaching 10000 clips, each carrying a file path, bin path,
  status reasons, and the analysis overlay, it overruns the per-origin quota. The
  write then threw, was caught, logged a `console.warn` no one reads, and the
  instant-paint feature quietly did nothing on exactly the big projects where a
  slow first fetch makes it worth having. The snapshot is now capped at 750
  clips; on a quota failure the panel prunes cached inventories (including
  snapshots for projects the user has moved on from) and retries once, and if
  that still fails it removes its own key so a snapshot cannot outlive the walk
  it described.
- **A truncated snapshot no longer reads as a complete inventory.** A capped
  snapshot carries `snapshot_partial` and the true clip count, and both surfaces
  that show a number say so — the header reads `(cached preview of 3015)` and the
  poll status reads `cached first 750 of 3015`. Capping the cache without this
  would have re-created the v2.97.1 bug one layer down: a number presented as the
  inventory that isn't.

### Added

- `tests/test_dashboard_inventory_snapshot.py` — guards that the inventory fetch
  sends no `limit` of its own (the v2.97.1 regression), that the snapshot stays
  capped, and that a partial snapshot declares itself.

## What's New in v2.97.1

**The control panel honors `media_analysis.inventory_limit` again.** Thanks to
[@albertfdp](https://github.com/albertfdp) for finding and fixing this
([#148](https://github.com/samuelgursky/davinci-resolve-mcp/pull/148)).

### Fixed

- **A configurable preference the panel could never reach.** `/api/resolve/media`
  falls back to the `media_analysis.inventory_limit` preference (1–10000,
  default 500) when the request carries no `limit`, and the Preferences pane has
  always let you set it. But `refreshResolveMedia()` — the panel's only caller of
  that endpoint, used for the first load, the manual refresh button, and the
  background poll alike — hardcoded `?limit=500`, so the query param won every
  time and the preference was inert. On a 3015-clip project the Overview panel
  showed the first 500 clips and rendered real Media Pool bins as empty. The
  fetch no longer sends `limit`; the server-side preference applies. Verified
  against a live 3015-clip project: 3015 clips across 32 bins after the fix.

This is the silent-lie class again — a setting that round-trips through the
preferences store, reports itself as saved, and changes nothing observable.

## What's New in v2.97.0

**`timeline_frame(action="capture")` now renders the frame.** v2.96.0 shipped it
reading Resolve's thumbnail API; live validation on Studio 19.1.3.7 showed that
API cannot do the job, so the default route changed. Callers using `preview` or
`full` keep working and now get a frame-accurate image.

### Measured — the thumbnail API is per-CLIP, not per-frame

`GetCurrentClipThumbnailImage` returns the same image for every frame of a clip.
Seeking to 00:00, 01:00, 02:00 and 04:00 within one clip returned
**byte-identical data every time**; the image changed only when the playhead
crossed a clip boundary. Two further conditions make it fail silently:

- It returns `None` whenever Resolve is **not the frontmost application**, at any
  delay, even on the Color page with a clip under the playhead.
- The first read after a page switch or a playhead move can be empty while the
  viewer catches up, so a single failed read proves nothing.

None of this is distinguishable from "no frame here."

### Measured — `ExportStills` needs the Gallery panel open

It returns a bare `False`, writing nothing, unless the Gallery panel is visible
on the Color page — across png/jpg/tif/dpx, three destination folders, settle
delays of 0.5s/1.5s/3.0s, with Resolve frontmost. `GrabStill` succeeds; only the
export fails. No scripting call can open that panel.

### So `capture` renders one frame

`MarkIn == MarkOut` on a still-image render. Frame-exact, full resolution, well
under a second, and it needs no GUI panel and no foreground window. Verified
live: three timecodes produced three different images, and the rendered burn-in
matched the requested frame.

`quality` is now `frame` (default), `preview` (same render bounded to 1280px),
`thumbnail` (the instant per-clip image), and `still` (Gallery still). `full` and
`preview` from the original issue schema both map to the render.

**The cost, stated rather than hidden:** render settings are project-level.
Format and codec are snapshotted and restored, the render job is deleted, and
the Deliver page and playhead that rendering pulls Resolve onto are put back —
but `TargetDir`, `CustomName` and the mark range cannot be read back on builds
without `GetRenderSettings`, so they are reset to the full timeline rather than
truly restored. `quality="thumbnail"` remains for callers who need a strictly
side-effect-free read and can live with per-clip granularity. A capture also
refuses while another render is running.

### Corrected — docs that claimed per-frame accuracy

`docs/SKILL.md` said `get_thumbnail` "reflects the current frame as rendered by
Resolve." It reflects the clip. `timeline(action="thumbnail_contact_sheet")`
samples the same API, so it is a shot inventory, not frame evidence; both are
now described accurately. Both API findings are recorded in `api_truth` and
regenerated into `docs/reference/api-limitations.md`.

### Fixed — thumbnail reads poll instead of trusting one call

`timeline_markers(action="get_thumbnail")` and `get_thumbnail_image` now hold the
Color page, poll for the viewer to catch up, and name the foreground requirement
when the read stays empty.

## What's New in v2.96.0

New tool **`timeline_frame`** — the assistant can look at what Resolve is
rendering instead of inferring it from metadata. Closes
[#146](https://github.com/samuelgursky/davinci-resolve-mcp/issues/146).

### `timeline_frame(action="capture")`

Returns the timeline frame as MCP image content — grade, Fusion, titles,
transitions, as composited. (For the raw camera file, `media_analysis(action=
"extract_frames")` is still the right call.)

- `timecode` / `frame` — capture anywhere, not just the playhead. Accepts
  absolute (`01:00:15:12`) or elapsed (`00:00:15:12`) timecode, matching the
  marker-parameter contract.
- `quality` — `preview` (Resolve's thumbnail; fast, writes nothing) or `full`
  (full resolution via a Gallery still, removed again afterwards).
- `max_width` — bound the context cost. Preview downscales in-process with an
  area average; `full` rescales with ffmpeg, and **fails rather than silently
  returning a full-size frame** when ffmpeg is missing.
- `format` — `png` (default), `jpg`, or `tif` on the `full` path.
- `timeline_name` — capture from another timeline; it is made current for the
  read and the original restored after.

A capture is a read: the Color page, playhead, current timeline, and Gallery all
come back as the caller left them.

### Why a separate tool rather than an action on `timeline`

FastMCP derives an output schema from a tool's return annotation and validates
returns against it, so a `-> Dict[str, Any]` tool cannot return image content.
`timeline_frame` is annotated `-> Any` for that reason — the same reason
`timeline_markers` already was. The issue asked for a top-level tool, and the
schema constraint independently forces one.

### Fixed — thumbnail reads no longer misreport a page problem as a missing frame

`GetCurrentClipThumbnailImage` returns `None` on every page except Color, with
nothing to distinguish that from "no frame here."
`timeline_markers(action="get_thumbnail")` and `get_thumbnail_image` called it
bare, so off the Color page they reported a missing thumbnail. Both now hold the
Color page for the read and restore the previous page — the mitigation
`thumbnail_contact_sheet` already used. When the switch genuinely cannot happen
(headless, page locked), the error names the Color-page requirement instead.

`get_thumbnail_image` now shares the `timeline_frame` capture path, so it picks
up the fix; its contract is unchanged.

### Fixed — the installer configures Codex CLI

The installer claimed Codex support but never wrote its config, so a successful
install left no `davinci-resolve` entry in `~/.codex/config.toml` — everything
else (venv, Resolve paths, bridge, server) was in place and only the
registration was missing. Codex keys MCP servers under a TOML
`[mcp_servers.<name>]` table, and the installer only knew how to write JSON.
Closes [#39](https://github.com/samuelgursky/davinci-resolve-mcp/issues/39).

`codex` is now a selectable client (included in `--clients all`), writing
`$CODEX_HOME/config.toml` (default `~/.codex/config.toml`), and `--manual`
prints a ready-to-paste TOML block.

The merge is a text splice, not a parse-and-rewrite, so comments and hand
formatting survive; an existing `[mcp_servers.davinci-resolve]` table has its
`command`/`args`/`env` replaced in place. Sub-tables of that entry are kept:
hand-written Codex configs put per-tool approval modes in
`[mcp_servers.davinci-resolve.tools.<tool>]`, and an installer that dropped them
would quietly widen what the agent may do without asking. An
`[mcp_servers.davinci-resolve.env]` sub-table is regenerated in that same shape
rather than replaced with an inline `env` — TOML rejects a file that spells one
key both ways.

Paths are escaped as TOML basic strings (Windows backslashes would otherwise
corrupt the file). The installer refuses to touch a config that is already
invalid TOML, one that defines the server as an inline key it cannot safely
rewrite, or a merge result that would not parse — the same
never-wipe-a-user-config policy the JSON clients follow. Writes are backed up to
`config.toml.backup` first.

## What's New in v2.95.3

Closes the retime entry's explicit `UNTESTED` warning: **reverse and
variable-speed ramps both work**, and fixes two decoder bugs found proving it.

### Measured — reverse lands through both import routes

On Studio 21.0.4.5. OTIO with a negative `time_scalar` (-1) placed a clip reading
`GetSourceStartFrame` 95 → `GetSourceEndFrame` 46; EDL with a negative `M2` rate
(-24.0 at 24fps) read 48 → 0. **The API does expose direction** — a reversed clip
reports source start GREATER than source end, i.e. a negative span.

### Measured — variable-speed ramps survive Resolve intact

They cannot be expressed in OTIO (`LinearTimeWarp` is a single `time_scalar`,
constant by construction), but they can be authored offline. A `Sm2TimeMap` built
with `media-timemap.buildTimemap` carrying two segments — 0–2s record at 0.5×,
2–4s at 2.0× — was patched into a clip's `MediaTimemapBA`, imported, and
**re-exported by Resolve with the segments unchanged**. Confirmed independently
from the API side: the clip read source `0..120` over a 96-frame record, and
2s@0.5× (24 source frames) + 2s@2.0× (96) is exactly 120.

### Fixed — the timemap decoder reported a reverse as speed 0

Two real bugs in `media-timemap.js`, both exposed by the first reversed map it
ever saw:

- **Fixed-offset keyframe reads.** Each point omits whichever of
  `recordSec`/`sourceSec` is zero (protobuf default-omission), so
  `readDoubleLE(1)`/`readDoubleLE(10)` threw *"offset out of range"* on every
  reversed map. Forward maps only decoded because both values happened to be
  non-zero.
- **A hardcoded (0,0) origin.** A reversed clip starts at the far end of the
  source, and Resolve encodes that starting offset as a **top-level protobuf
  field 2** double. Assuming (0,0) made a reverse decode as **speed 0** — a
  plausible wrong number, which is worse than a crash. It now decodes as −1.

### Trap worth naming

`buildTimemap` returns a **Buffer**. Writing it into the XML without
`.toString('hex')` embeds mojibake, and the failure is silent: the clip imports
cleanly and reads `0..0` — indistinguishable from the degenerate-map signature
the ledger describes for xmeml imports, so it looks like Resolve rejected the
retime when it is a caller bug. It cost real time here before being caught.

## What's New in v2.95.2

Adds the live round-trip harness the offline `.drp` tier never had — the absence
of which is why three unbacked "verified live" claims survived in its README, one
reaching a shipped `api_truth` recommendation before being caught.

### Added — `tests/live_drp_roundtrip_verification.py`

Authors a `.drp` per primitive, imports it into a running Resolve, asserts intent
against structural readback, **and exports the composited frame to assert the
item is actually visible on screen.**

That last assertion is the whole point. `place_fusion_title` satisfies every
structural check — right track, frame, duration, `PrettyType`, and correctly
encoded text — while rendering nothing, so a harness that only diffed
`GetStart()`/`GetDuration()` would have called it green. Visibility is measured
with `Project.ExportCurrentFrameAsStill` plus a luma pass: an inert item yields
`max=0` across the entire frame, a real one does not (the live control returns
`max=255` with ~16k bright pixels).

**Known-broken cases are declared, not skipped.** `place_fusion_title` is
recorded as `KNOWN BROKEN`; if it starts working the harness reports `UNEXPECTED
PASS` and fails, forcing the docs that describe it to be updated.

Current state on Studio 21.0.4.5: **7 passed, 1 known-broken, 0 needing
attention** — media placement, blade, trim, cross-track move, and generator
visibility all verified end to end.

### Fixed — the `RESOLVE_VERIFY=1` gate was unrunnable

It ran a single test that threw `TODO — implement once fixtures land`, so the
flag reported a failing suite and everyone learned to ignore it. A gate nobody
can run green is worse than no gate. It is now a documented skip pointing at the
harness above, and `RESOLVE_VERIFY=1 npm test` is clean.

### Changed — release process states the rule

"The file round-trips" and "Resolve honours it" are different claims; only a live
import establishes the second. Changes to the offline `.drp` tier must run the
harness, and a doc may not say "verified live" unless a runnable command produced
that result.

The harness is also robust to `DeleteProject`'s session lock: projects opened in
a session cannot be deleted until Resolve restarts, so it steps off the current
project, retries, falls back to run-unique names rather than colliding, and
reports what it could not remove instead of failing silently.

## What's New in v2.95.1

Withdraws a recommendation this project shipped two releases ago. **`drp
place_fusion_title` produces a title Resolve never renders**, and v2.93.2/v2.93.3
told callers to use it.

### Fixed — the offline title is inert

Measured on Studio 21.0.4.5. The placed clip is structurally perfect: right
track, right frame, right duration, `PrettyType` = `Fusion Title`, and the text
genuinely is written into the `CompositionBA` — it decodes back. But Resolve
never instantiates the comp:

| | offline-placed | live-inserted |
|---|---|---|
| `GetFusionCompCount()` | 1 | 1 |
| `GetToolList()` | **`[]`** | `['Template','MediaOut1']` |
| Inspector Title tab | **blank** | shows `Text+` |
| Viewer | **black** | renders the text |

Reproduced four ways — alone, inside an edit chain, onto a bundled-template base
project, and onto a genuine 21.0.4.5 Resolve export. Ruled out: template
staleness (the bundled clip element is structurally identical to a real one, same
tags, size differing only by text length) and DbId rewriting (the comp blobs hold
no DbId references). Root cause open.

It passes every structural readback while being invisible on screen — the exact
silent-lie shape the `api_truth` ledger exists to catch. The **nested-timeline
route is unaffected** and remains the working answer.

### Narrowed — it is the Fusion-comp path, not clone-a-template

`place_generator`, built the same way, works: an imported Solid Color shows a
populated `Generator - Solid Color` Inspector with a live Color parameter. A
generator's parameters are a protobuf `EffectFiltersBA`, which Resolve reads; a
title's are a `CompositionBA` Fusion-comp blob, which it does not instantiate.

### Changed — "mapped" no longer implies "Resolve honours it"

The drp-format README's honest-scope section conflated file-level fidelity with
live behaviour. A blob that survives a write/read cycle has been *encoded*
correctly; only a live import proves it is *instantiated*. The section now says
so, and the Fusion-title row carries the warning.

## What's New in v2.95.0

Compound clips can now be walked into and edited offline — the one capability
where the offline tier beats the live scripting API outright.

### Added — `drp` nested-sequence actions

`list_nested`, `read_nested`, `read_nested_titles`, `set_nested_title_text`
(`resolve-advanced/vendor/drp-format/compound-nav.js`). Enumerate every compound
clip and nested timeline in a `.drp`, walk into either, and rewrite the title
text inside.

**A compound clip and a nested timeline are the same shape on disk.** Both appear
in `MediaPool/Master/MpFolder.xml` as a media-pool element (`Sm2MpCompoundClip` /
`Sm2MpTimelineClip`) carrying an inline `<Sequence><Sm2Sequence DbId="X">`, and
the `SeqContainer/<uuid>.xml` whose tracks carry `<Sequence>X</Sequence>` holds
the contents. The join is on that **Sm2Sequence DbId, not the container's own
DbId** — which is referenced by nothing else in the package. One asymmetry: a
compound's contents are rebased to `Start` 0 while a nested timeline's keep
timeline-absolute TC.

**Why this matters.** `MediaPoolItem.GetTimeline()` (21.0.4+) resolves through
the timeline handle: it returns the inner Timeline for `Type='Timeline'` and
**`None` for `Type='Compound'`**, and a compounded Text+ reports
`GetFusionCompCount() == 0`. So compounding a title severs its text permanently
as far as scripting is concerned — there is no API route back to it at any
version. Offline, the distinction does not exist.

Verified end to end on Studio 21.0.4.5: text rewritten offline inside a compound,
imported into Resolve, re-exported by Resolve, and read back **from Resolve's own
export** unchanged — so Resolve genuinely parses the write rather than tolerating
it. Ten unit tests against a committed fixture exported from 21.0.4.5 holding a
compound-of-media, a compound-of-Text+, and a nested timeline.

## What's New in v2.94.3

A systematic sweep of catalogued API gaps against **Studio 21.0.4.5**, prompted
by an external report. Two ledger entries were wrong and are corrected; a new
harness proves the routes that DO work.

### Fixed — transitions are not invisible to scripting

- **`Transition create / copy / clone` claimed transitions applied in the UI are
  "invisible to and unmodifiable by scripts". Both halves were wrong.** A
  12-frame Cross Dissolve applied through the Edit-page right-click menu
  enumerates in `GetItemListInTrack` as `GetName() == 'Cross Dissolve'`,
  `GetStart() == 86426`, `GetDuration() == 12` — centered on a cut at 86432 —
  with a stable `GetUniqueId()`. One authored offline into a `.drp` and imported
  reads identically, so the creating route is irrelevant. It is also removable:
  `DeleteClips([transition], False)` returns True and leaves both adjacent clips
  untouched. **The discriminator** is `GetProperty()`: empty on a transition, 26
  transform keys on a clip. Automated QC of existing transitions is therefore
  possible. Genuinely missing: creation, cloning, and any type/alignment detail —
  the kind is knowable only from the name string.

### Fixed — CreateProject is not an "Untitled project" problem

- **`CreateProject` returned None with a NAMED project current and no modal on
  screen** (screenshot-confirmed), while `OpenPage('edit')` succeeded in the same
  session — so the connection was healthy and the documented modal is not the
  only mechanism. Loading any clean project unblocked it on the next call. The
  entry's recommended workaround was `CloseProject`, which **discards unsaved
  changes** — acceptable for a throwaway Untitled project, destructive when the
  current project is a named one belonging to another session. It now recommends
  `LoadProject(clean project)` instead.

### Added — `tests/live_workaround_verification.py`

The sibling of the gap harness: where that one proves absence, this proves
presence, performing each operation and reading the result back. Seven routes
verified on 21.0.4.5 — nested-timeline title placement with a later text edit,
ripple delete (with a non-ripple control showing the gap), the take selector as
an in-place source swap, `GetSelectedClips`, and constant retime through both
OTIO `LinearTimeWarp` and EDL `M2` (each a true 200%: 96 source frames over a
48-frame record, alongside a 1.0 control). It also records the compound-clip trap
as a deliberate `ROUTE FAILS`.

### Changed — the gap harness covers 13 gaps, up from 8

Added control-paired repros for the Source/Auto Track Selector (locking V1 blocks
the insert rather than redirecting it, while a media-backed clip targets V2
fine), transitions, native multicam creation, per-caption subtitle text, and
per-clip audio channel mapping. **13/13 confirmed missing** on 21.0.4.5.

## What's New in v2.94.2

Changelog repair. No code changed.

- **v2.93.3 carried two separate `What's New in v2.93.3` sections.** Two sessions
  were working in one checkout, and one of them ran `git add -A` while the
  other's edits were still uncommitted — so a delivery-target commit swept up an
  unrelated `api_truth` correction, and both wrote their own heading under the
  same version. The two sections are now merged into one entry that describes
  everything v2.93.3 actually shipped: the delivery-target re-verification **and**
  the issue #74 nested-timeline finding. The v2.93.3 GitHub release notes, which
  described only the delivery work, have been amended in place for the same
  reason. No commit or tag was rewritten — both are public.

## What's New in v2.94.1

Removes the `hls_h264` target added in v2.94.0 — it could never work — and fixes
a QC note that told the truth only for image sequences.

### Fixed

- **`hls_h264` is withdrawn.** It resolved cleanly against the format/codec
  matrix, which is why it shipped, but it can never render: on Studio 21.0.4.5
  `GetRenderCodecs('m3u8')` returns `{'H.264': 'H264'}` and
  `GetRenderResolutions('m3u8', 'H264')` returns real rasters, yet
  `SetCurrentRenderFormatAndCodec('m3u8', ...)` is False for every value tried
  (`'H264'`, `'H.264'`, `'h264'`, `''`) while `('mp4', 'H264')` succeeds. Caught
  by queuing an actual job rather than by resolving a name. A target that always
  fails is worse than no target, so it is gone along with its `hls` and
  `streaming` aliases.
- **`qc_note` reported every target's missing QC projection as an image
  sequence.** It was hard-coded, so `webp_animated` — which declines QC because
  its ffprobe values are unmeasured — told callers its output was a many-file
  sequence. It now surfaces the target's own `qc_skip_reason`.

### Notes

- New API-truth finding, folded into the existing `Project.GetRenderCodecs`
  entry: **the format/codec matrix is not a capability contract.** A format can
  advertise a codec, and rasters for it, and still refuse to be selected. That is
  worse than the zero-codec formats, which at least advertise nothing. Presence
  in the matrix proves a pair is *listed*, never that it is usable — the
  authoritative test is setting it and reading the boolean back, which
  `prepare_render_job` and `prepare_delivery_job` already do.
- 31 targets, all verified end to end on Studio 21.0.4.5: resolved, queued as a
  real render job, then deleted.

## What's New in v2.94.0

Adds four delivery targets for deliverable classes the table did not cover:
image sequences for web/graphics, animated web assets, and an HTTP Live
Streaming package. All 32 targets resolve live on Studio 21.0.4.5.

### Added

- **`png_sequence`** — PNG frames for web and motion-graphics handoff. Resolve
  exposes **RGB only** (no alpha codec), so the target says so and points at
  `dpx_sequence` (`RGBA 8 bits`) or `prores4444_master` when transparency is
  actually needed. Alias: `png`.
- **`gif_animated`** — looping animated GIF. No audio track at all, so
  `ExportAudio` is False rather than merely unpinned. Its QC projection uses
  ffprobe values measured on a generated file (`container: gif`, `codec: gif`).
  Alias: `gif`.
- **`webp_animated`** — looping animated WebP. Ships with **no QC projection**:
  the reference machine's ffmpeg has only the `webp_pipe` still-image demuxer, so
  a rendered animated WebP could not be probed and the ffprobe values are
  unmeasured. `qc_skip_reason` says exactly that. Guessing `webp`/`webp` would
  have produced QC failures about vocabulary rather than about the deliverable —
  the same trap as mp4 reporting its container as `mov`. Alias: `webp`.
- **`hls_h264`** — HTTP Live Streaming package (`.m3u8` playlist plus segments),
  in the `package` tier alongside IMF and DCP. Bitrate ladders, variant playlists
  and encryption keys are not expressible as a render target. Aliases: `hls`,
  `streaming`.

### Notes

- PNG, WebP and HLS are **not render formats on Resolve 19.x**. These targets
  resolve on 21.x and fail loudly with the machine's available list on older
  builds, which is the designed behavior rather than a regression.
- Deliberately **not** added, having checked the full 21.0.4.5 matrix: container
  swaps that duplicate existing capability (MKV carries the same ProRes and
  H.264/H.265 codecs already covered), standalone JPEG 2000 (the same essence the
  IMF/DCP targets reach), and legacy formats (AVI, Cineon, MJ2, Panasonic AVC
  8K). All remain reachable via a `format_candidates` override or a user target.
- `braw`, `mts` and `wav` expose zero codecs and reject every codec value, so no
  target is possible for them at all.

## What's New in v2.93.3

Two independent pieces of work landed in this release, both measured against the
**installed** build, Studio 21.0.4.5: the delivery-target table re-verified
against that build rather than the 19.1.3.7 it was first measured on, and a
correction to the issue #74 ledger entry.

### Changed

- **Delivery-target provenance now reflects both builds.** `VERIFIED_ON` reads
  21.0.4.5 (23 formats / 326 pairs) with the original 19.1.3.7 measurement
  (20 formats / 271 pairs) kept alongside it. All 28 targets resolve on 21.0.4.5.
- **The module now records why candidate ordering matters.** Codec **ids were
  stable** across the two majors while **descriptions were not** — every DNx
  description gained an `"Avid "` prefix in 21.x (`"DNxHR HQ"` →
  `"Avid DNxHR HQ 12-bit"`) while `DNxHRHQ`, `DNxHRLB` and `DNxHRHQX_10` did not
  move. The targets that survived the upgrade did so because their candidate list
  contained the real id, so ids now lead every list and descriptions follow.
- **Corrected a claim that went stale between builds.** The module asserted "PNG
  is not a render format at all", which was true on 19.1.3.7 and is false on
  21.0.4.5 (`png`, `jpg` and `webp` are all render formats there). There is still
  no `png_sequence` target, but the reason is now "not added", not "impossible".

### Fixed

- **`api_truth.py`: the zero-codec format list was presented as fixed.** It is
  build-specific — `wav` and `gif` on 19.1.3.7, but `braw`, `mts` and `wav` on
  21.0.4.5 (`gif` gained codecs; BRAW and MTS lost them). `wav` is affected on
  both, so an audio-only WAV deliverable remains inexpressible through
  `SetCurrentRenderFormatAndCodec`, which rejects every value including the empty
  string.
- **The description-vs-id trap is re-confirmed unchanged on 21.0.4.5** —
  `('mp4', 'H.264')` still returns False while `('mp4', 'H264')` returns True,
  two major versions after it was first recorded. The entry now carries evidence
  from both builds and notes that descriptions drift while ids do not.

`docs/reference/api-limitations.md` regenerated from those entries.

### Fixed — issue #74: titles can be placed by track and frame after all

- **A native Text+ CAN be placed at an exact track and frame, and stay editable
  — entirely through the public API.** The issue #74 entry has said for two
  months to "accept the limitation." That was wrong about the outcome, and the
  recommendation is replaced. `InsertFusionTitleIntoTimeline` really does take no
  track/frame/duration and really does produce a source-less item — but it is not
  the only door. Put the title on its **own timeline**, then place *that*
  timeline's media pool item (`Type='Timeline'`) with `AppendToTimeline`'s
  clipInfo `trackIndex`/`recordFrame`. Measured: lands on the requested track at
  the requested frame, exactly.

- **The text survives the nesting.** `placedItem.GetMediaPoolItem().GetTimeline()`
  (Resolve 21.0.4+) opens the inner timeline; the Text+ there still reports
  `GetFusionCompCount() == 1`, so
  `GetFusionCompByIndex(1).FindTool("Template").SetInput("StyledText", …)` works
  and persists across processes. Duration is controllable the same way —
  `duration = endFrame - startFrame`, `endFrame` exclusive, verified at 1, 119 and
  120 frames. It composes: a PNG plus two titles each placed by `trackIndex` into
  one container timeline, and that container placed as a single clip, with every
  element still individually reachable and editable through the nesting.

- **Compound clips are the trap.** `CreateCompoundClip` also gives a source-less
  title a MediaPoolItem and also places correctly — but it **severs the text**.
  `FusionCompCount` drops 1 → 0, and `GetTimeline()` returns `None` for
  `Type='Compound'` while working correctly for `Type='Timeline'`, so nothing gets
  back to the Text+. Nest, never compound, when the text must stay editable.

- Two constraints recorded with the route: every placed instance shares one media
  pool item, so a text edit propagates to all of them (use one source timeline per
  distinct card); and placements must not overlap on a track or the append is
  silently rejected.

## What's New in v2.93.2

Documentation and ledger correction, validated live against DaVinci Resolve
Studio **21.0.4.5** (version read from the running instance, not assumed).

- **A false "verified live" workaround for issue #74 is withdrawn, and the real
  mechanism is documented.** `resolve-advanced/vendor/drp-format/README.md`
  claimed that locking the video tracks below your target redirects
  `InsertFusionTitleIntoTimeline` to that track, and called it verified live. It
  shipped with no test, log, or evidence file, and it contradicted the
  `api_truth` ledger entry written twelve days earlier from an explicit test
  matrix. A third party independently reproduced the ledger's version on
  21.0.4.5, so the two claims were re-measured on one rig, one fresh
  3-video-track timeline per arm so no insert could fail on a collision:

  | Arm | Setup | `InsertFusionTitleIntoTimeline("Text+")` |
  |---|---|---|
  | A | nothing locked | lands on **V1** |
  | B | V1 locked via `Timeline.SetTrackLock` | returns **`None`** |
  | C | V1 locked by **clicking the padlock in the UI** | returns **`None`** |
  | D | nothing locked, source patch dragged to V2 in the UI | lands on **V2** |

  B and C are identical, which kills the standing theory that a GUI lock
  advances the selector where the API lock does not. Locking blocks the target;
  it never re-targets. The README claim is withdrawn as false and the ledger
  entry — previously measured on 21.0.0 — is confirmed on the newest build.

- **The destination is the patch panel, not the lock state.** Arm D is the
  finding: dragging the source patch badge onto V2 in the Edit page sends the
  next insert to V2. The per-track badge column in the track header is the
  auto-track-selector toggle; the source patch badge appears only on the patched
  track, and dragging that is what re-targets. The capability exists in the
  application and is reachable only by GUI automation — so the request to
  Blackmagic is read/write access to the patch panel, which is smaller and
  better defined than adding `trackIndex` to all six `Insert*IntoTimeline`
  methods. The route is unverifiable from the API side (nothing in the scripting
  surface confirms where the selector landed), so read the landing track back
  with `TimelineItem.GetTrackTypeAndIndex()` and treat a wrong track as a
  failure. Offline, `drp place_fusion_title` remains deterministic.

## What's New in v2.93.1

Documentation only; no behavior changed and no Resolve validation required.

- **The immediate-retake blind spot is now in the media-analysis guide.** Issue
  #125 asked for three things; the `rank_takes` caveat and the
  `possible_swallowed_retakes` flag shipped in v2.83.0, but the documented
  limitation never did — the guide had zero mentions of retakes, so the only way
  to learn that word timestamps are untrustworthy around an immediate re-read was
  to already be looking at output that flagged one. The new section states what
  whisper does (emits a re-read sentence once, aligns it to the first take, and
  absorbs pause-plus-second-take into a single word), names every feature that
  inherits it, and records why silence detection cannot substitute — the
  swallowed span measured **−12.1 dB** against adjacent speech at −16.7 dB, and a
  silence pass recalled **3 of 17**. It is explicit that the flag is never a cut
  point, and that no flags is weak evidence rather than proof.

## What's New in v2.93.0

`source_end` is a source frame again, and the guidance v2.91.0 shipped about WAV
frame rates was wrong. Both found by measuring rather than reasoning, live on
Studio 19.1.3.7 with synthetic media in a disposable project.

### Fixed

- **`source_end` was `source_start + duration`, and that duration is a TIMELINE
  duration.** So the sum was unit-mixed the moment the media and timeline rates
  differed. Measured against the `endFrame` actually sent, it overshot by
  **+24, +26, +108 and +149 frames** on a WAV counting at 24 in a 29.97 timeline
  — and `extract_source_frame_ranges` builds pull ranges out of it, reporting
  widths of 543 and 749 for clips that consume 435 and 600 source frames.
  The direction was safe (a longer pull); the number was wrong, and anything
  sizing an archive, a consolidation or a pull list inherited it.

  It is now `round(GetSourceEndTime × source_fps)`. Seconds carry no frame-rate
  assumption, so the product is a source frame by construction, and the field
  stays **EXCLUSIVE** exactly as every caller already read it. Over 8 items in
  both regimes it equals the `endFrame` sent every time, and it reproduces the
  old value wherever the old value was already right — so no matched-rate
  consumer moves, which the full suite confirms without a single existing
  expectation changing. It falls back to the old sum only when the second-reader
  or the rate is unreadable.

- **`GetSourceEndFrame` was the obvious candidate and it is not usable raw.**
  Measured over 12 items, it is **exclusive when the source and timeline rates
  match and inclusive when they differ** — off by one in exactly the case a
  caller reaches for it. Not a media-type split either: the same WAV imported at
  29.97 into a 29.97 timeline reads exclusive like video, and only the mismatch
  flips it. Building on it would have meant branching on a rate comparison the
  code would first have to reconstruct.

### Corrected

- **A WAV is not 24 fps.** v2.91.0's ledger entry said a WAV "carries no frame
  rate, so Resolve falls back to 24" and told callers to treat one as 24 fps.
  That is wrong. A WAV takes the **project's `timelineFrameRate` at import** and
  freezes it: one 400.000 s file imported at 24 reads `FPS 24.0` /
  `Duration 00:06:40:00`, the same file imported at 29.97 reads `29.97` /
  `00:06:39:18`, and changing the project rate after import leaves the clip on
  its original rate. So the trap is "the project moved after import", not "audio
  is always 24" — and a WAV imported at 29.97 has no mismatch at all. Anyone who
  followed the old advice on such a file would have converted a correct number
  into a wrong one. Corrected in the ledger, the `resolve-rough-cut` traps table,
  the `probe_timeline_structure` and `create_variant_from_ranges` action help,
  and the helper docstrings: every site now says read the rate, never assume it.

### Validation

- Suite: 2628 passed, 1 skipped (7 new cases covering both regimes, the rounding
  boundaries, and each fallback). Static checks and drift guards clean.
- Live on **Studio 19.1.3.7**, ffmpeg-generated synthetic media, disposable
  project deleted after each run. The first measurement pass was discarded and
  redone: it zipped `AppendToTimeline`'s return against the request list, two
  entries came back unreadable, and the resulting misalignment looked exactly
  like reader noise. Every number above comes from appending one range at a time.
- **Not tested here:** Resolve 21.x, and retimed clips — there is no clip-speed
  API to build one from, so whether the new route also fixes the retime case
  (where the old arithmetic is wrong for the same reason) is untested.

## What's New in v2.92.0

Two corrections to advice this project was giving confidently and wrongly, both
from issues filed by users who hit them.

### Fixed

- **`PYTHON3HOME` satisfies the macOS bridge preflight — uv/pixi/conda need no
  `sudo`.** The preflight demanded a *framework* Python and sent everyone else
  to a system-wide python.org install, which managed machines often forbid.
  `uv`, `pixi` and conda-forge ship no `--enable-framework` build at all, so
  their users got the warning no matter what they did. Reported by @rusanivsky
  in #143, who had free Resolve 21.0.4.5 serving the bridge on uv-managed
  CPython 3.12.13 with no python.org Python on the machine.

  Framework-ness was never the variable. In `fusionscript.so` — read here on
  Studio 19.1.3.7, a January 2025 binary — every `Python.framework` reference is
  Python **2.7**, and there is no `Python.framework/Versions/3` string anywhere.
  Python 3 is found through `PYTHON3HOME`, else `/usr/local/bin/python3`, then
  probed for `sys.prefix` and dlopened as `<prefix>/lib/libpython3.X.dylib`.
  python.org installs work because that installer creates
  `/usr/local/bin/python3` — verified here, where it is a symlink into
  `Python.framework/Versions/3.11`. Homebrew (`/opt/homebrew`), pyenv, uv and
  conda land in neither place, which is the whole of the "framework Pythons
  only" folklore.

  The preflight now accepts either route and reports both. `PYTHON3HOME` is read
  with `launchctl getenv`, never `os.environ`: Resolve is GUI-launched and
  inherits launchd's environment, so reading our own shell would report a hit in
  exactly the case that does not work. A `PYTHON3HOME` exported in the shell but
  absent from launchd is called out, because it is the natural thing to try. The
  old advice is corrected in the Lua canary, the `BRIDGE_UNAVAILABLE`
  remediation, both READMEs and `docs/SKILL.md`.

### Added

- **Domain skills ask the build what it cannot do.** v2.89.0 taught
  `get_version` to report a connected build's missing surfaces, but only the
  session skill ever asked — an agent entering through
  `/timeline_edit_workflow` or `/color_grade_workflow` got identical guidance
  whatever it was attached to. That is the hole @magwa101 fell into on DR 21 in
  #132. `resolve-edit`, `resolve-color`, `resolve-conform` and
  `resolve-media-analysis` now name the gated surfaces in their own domain, with
  the floor and what to do instead, sourced from `resolve_versions.VERSION_GATES`
  rather than prose. Each section also has to say that an empty list means
  nothing *recorded* is missing, that probes use `name in dir(obj)` and never
  bare `hasattr` (which returns `True` for every name on a Resolve object), and
  that *gated* is not *absent* — clip speed is unreachable on every build and no
  upgrade will help.
- `tests/test_skill_version_gates.py` fails when a skill quotes a floor the
  ledger disagrees with. Confirmed it bites by mis-stating a floor and watching
  it fail, not by trusting a green run.

### Validation

- Suite: 2621 passed, 1 skipped. Static checks and drift guards clean.
- The binary strings and the `/usr/local/bin/python3` mechanism were confirmed
  here on Studio 19.1.3.7. **Not reproduced here:** the live positive on free
  21.0.4.5 with uv Python — that is the reporter's, and is labelled as such in
  the code comment.
- No Resolve scripting behavior changed; the bridge change is installer
  preflight and advice text.

## What's New in v2.91.0

A timeline item's source frames are counted in the **media's** frame rate, not
the timeline's — and a WAV carries no native rate, so Resolve reports **24** for
it. Read back at the timeline rate a WAV offset lands minutes from the real
position in the file, and nothing errors: `source_end` is derived as
`source_start + timeline_duration`, so the start/end pair stays internally
consistent whatever rate the caller assumed. Reported and measured by
@rusanivsky in #144.

### Added

- **`source_fps` beside the frames.** Every timeline-item summary now carries
  the rate its source frames are counted in, plus `source_start_seconds` /
  `source_end_seconds`, so the frame number always arrives with its unit
  attached. The rate is read from the media-pool item's `FPS` property, never
  assumed; an unreadable rate reports `null` so callers see *unknown* rather
  than a guess.
- **The reader that produced the value is tracked**, because the two do not
  agree on units: on an audio item `GetLeftOffset` counts in **timeline** frames
  while `GetSourceStartFrame` counts in **source** frames — 60687 vs 75784 for
  the same edit point. On that fallback the summary reports `source_fps: null`
  rather than pairing a timeline-frame number with the media rate.
- **`create_variant_from_ranges`' per-range `track_index`** — 1-based within
  `track_type`, missing tracks added — was accepted but undocumented, so
  multicam angles collapsed onto V1 for anyone who did not read the source. Now
  in the action help, the action list, the example, and `docs/SKILL.md`.
- The trap is in the `api_truth` ledger and in `resolve-rough-cut`'s verified
  traps table.

### Fixed

- **`source_end_seconds` was the same unit lie the field was added to stop.**
  `source_end` is `source_start + duration`, and that duration comes from
  `GetDuration` — a **timeline** duration. Converting the sum at the media rate
  compounds the very mix-up being guarded. The seconds now come from
  `GetSourceStartTime` / `GetSourceEndTime`, which answer in seconds with no
  rate inference at all, then from `GetSourceEndFrame / source_fps`, and read
  `null` rather than convert the derived value. `source_end` itself is
  unchanged — no consumer moves — but it is now annotated as unit-mixed where
  it is assigned, in the probe action help, and in the ledger.

### Validation

- Suite: 2613 passed, 1 skipped. `gen_api_limitations.py --check` clean.
- **Live on Studio 19.1.3.7** with synthetic media, which also shows the trap is
  not a 21.x regression. A 300 s 48 kHz WAV reports `FPS 24`; appending its
  source frames 4800–5235 to a 29.97 fps timeline yields a timeline duration of
  **543** (= 435 × 29.97/24), so `source_end` came back **5343** where the true
  source end is 5235 — `source_end / 24` reports **222.625 s** against a real
  **218.133 s**, 4.49 s out on a clip 18.1 s long. The patched code reports
  218.133 s. The matching 29.97 video item was unaffected either way (24.524 s
  read vs 24.525 s derived). Both second-readers exist on 19.1.3.7.
- Not tested here: the 21.0.3.7 measurements in the ledger entry, which are
  @rusanivsky's and are labelled as such.

## What's New in v2.90.0

AAF turnovers parsed by `editorial.parse_interchange` on the advanced server now
carry their animation curves, the transforms nobody had interpreted, and the
effects that occupy record time while emitting nothing. All three were losses a
consumer could not see, because the parse reported itself complete.

### Added

- **Keyframe curves ship instead of the word "varying".** A `VaryingValue` was
  read for its values alone, and only to answer "one number or more than one" —
  `ControlPoint.time` was never asked for, so every animated reframe reached a
  consumer as `"varying"`: enough to refuse the clip, never enough to rebuild
  it. Transform stages now carry `keyframes[<AvidParamName>]` and retimes carry
  `speedCurve.playRate` / `speedCurve.sourceOffset`, each with its interpolation
  and its points as `{t, v, frame}`.
- **`domain` names which rule produced `frame`,** because the two curve families
  do not share a time domain and a single conversion rule would have been wrong
  by an effect's whole length on one of them. Measured over all 2047 control
  points of an 878-event Avid picture turnover: transform params are normalized
  over the effect span with the endpoint inclusive (`frame = t x (length - 1)`,
  which lands 1243 of 1254 points on an integer frame against 278 under
  `length`), while speed maps are already in frames. Keys outside `0..1` are
  kept rather than clamped — 107 of 1254 sit before the first frame or past the
  last, which is what Avid leaves when an animated clip is trimmed. A curve with
  one unreadable point is refused whole; interpolating through a missing key
  produces a confident wrong animation.
- **`passthrough` stages carry the four uninterpreted transform operations**
  (SBlend_v2, Stabilize_2, MaskImage_2, 2DMatteKey_2) that were previously
  discarded whole — 22 events on the fixture. Their numbers travel in
  `rawParams`, deliberately not `params`: the same parameter *name* carries
  different units on different operations (SBlend's `DVE_POS_X_U` runs to -315
  where Stabilize's runs to -0.92 on the same show), so there is nothing to
  normalize, and a 2DMatteKey `AFX_POS_X_U` of 500 promoted into `params` would
  become a ~960px shift of a clip nobody repositioned.
- **`effectsWithoutEvents` closes a hole `unhandled` structurally cannot see.**
  An effect can be modelled perfectly and still emit nothing — the group is
  walked, its inputs are walked, and they contain no `SourceClip`. On the
  fixture `unhandled` reads `{}` (a complete parse) while 29 SubCap titles
  occupy real record time and reach the consumer as nothing whatsoever. Charged
  once, to the innermost cause.
- **`speedRatioFromCurve`** — the rate the offset curve itself implies, emitted
  only when that curve is straight, so no variable timewarp is ever averaged
  into a single number.

### Fixed

- **The declared AAF `SpeedRatio` rational is the source span truncated to whole
  frames, and 7 of 18 constant retimes on the fixture disagree with their own
  curve** — `201/112 = 1.794643` where the curve says `201.6/112 = 1.80`, and at
  worst `31/19 = 1.631579` against a curve reading `1.70`, a 4% speed error in a
  number an operator is handed to type in by hand. Every curve slope lands on a
  rate an editor would actually dial (1.7, 1.8, 2.0, 0.75); every declared value
  is that rate spoiled by rounding. Both ship under their own names and neither
  is substituted for the other.
- **Variable timewarps are reconstructible.** The offset curve is dense (up to
  387 points at half-frame steps) and describes where every record frame reads
  from, taking the 4 variable timewarps on the fixture from "flagged, rebuild
  from nothing" to fully described — including one reverse ramp whose offset
  runs 301.0 to -0.78. Reverse read off the curve agreed with the declared flag
  9 of 9, in both directions.

### Validation

- Every pre-existing field is byte-identical on the fixture, verified by a
  structural diff of the full 878-event parse against the previous output; event
  count, `unhandled`, and all existing counters are unchanged.
- 10 new tests in `resolve-advanced/test/aaf-sequences.test.mjs`.
- No DaVinci Resolve scripting behavior changed; this is offline interchange
  parsing, so no live Resolve validation was required.

## What's New in v2.89.0

The build gates this server already enforced are now gates an agent can ask
about, and the capability probe those gates run on no longer lies. Issue #132,
reported by @magwa101.

### Added

- **`get_version` reports what the connected build is missing.** A new `build`
  block carries `unavailable_on_this_build` — every recorded API surface this
  build does not have — plus `known_gates` and the caveat that an absence from
  that list is not a promise a method exists. #132 happened in a session that
  opened with `get_version` and was told a number and nothing the number ruled
  out. `get_resolve_version_fields` gains the same list on the granular server.
- **The version-gate registry went from 7 recorded surfaces to 41.**
  `_requires_method(obj, "GetLayoutPresetList", "21.0.4")` appears 44 times
  across the two servers and gates 31 distinct symbols, but
  `check_version_support` — the call `resolve-session` step 2 tells an agent to
  make — answered from a ledger that knew seven of them. So the one question an
  agent is instructed to ask returned `unknown` for surfaces this server was
  already routing on. On Studio 19.1.3.7 the session preflight named 7 missing
  surfaces; it now names 40. The new floors are labelled `documented` rather
  than `measured`: they come from Blackmagic's release documentation, not a live
  bisect here, and an agent relaying one should be able to say which.
- **`tests/test_version_gate_drift.py`** fails when a call site and the ledger
  disagree, and when a bare method name is gated at two different builds on two
  different classes (which would make a bare-name lookup a coin flip). A table
  copied by hand is exactly what drifts back apart.
- **`src/utils/resolve_probe.py`** — `has_method` and `api_constant`, with the
  measurement behind them. A companion guard fails the suite on a bare `hasattr`
  with a Resolve-shaped attribute name.

### Fixed

- **29 capability probes across `src/` used `hasattr` on Resolve API objects,
  where it is a constant `True`** (measured on Studio 19.1.3.7 across 42 checks,
  recorded in `api_truth`; re-confirmed live for this release —
  `hasattr(project, 'GenerateSpeech')` returns `True` on a build that has no
  such method). It failed in two shapes that look nothing alike:
  - `if not hasattr(clip, "RemoveMotionBlur")` is a dead branch, so the
    "requires Resolve 21+" refusal never fired and the call below it raised
    `AttributeError` on an older build. Eleven of these were the granular
    server's Resolve 21 AI guards.
  - `getattr(r, n) if hasattr(r, n) else n` never reaches its `else`, so a build
    without the constant got `None` where the author wrote a string fallback —
    no exception, no refusal, just a `None` travelling on into `Export()`. This
    reached granular timeline export and `ExportLUT`, and three constant
    lookups on the compound server. Confirmed live: a name Resolve does not
    define returned `None` under the old form and now falls back correctly.
    The fallback keys on `is None`, not truthiness, because `EXPORT_AAF` is
    genuinely `0.0`.
- **The granular AI tools reported a missing Extras pack as success.** Resolve's
  AI methods return the reason as a *string* when the pack is absent, and
  `bool("Required package ... is not installed.")` is `True`. The compound
  server has normalized that since the 21.0.2.4 measurement; the granular one
  had not, so folder and clip audio classification returned `{"success": true}`
  for a call that did not run, and `RemoveMotionBlur` / `GenerateSpeech` walked
  a string into `.GetName()`. All now route through `_ai_result`, which reports
  the failure and carries Resolve's own reason.
- **`Project.ApplyFairlightPresetToCurrentTimeline` was recorded on `Timeline`.**
  The shipped README lists it under Project and the server calls it there; the
  method's name is what made the wrong attribution look right.

### Validation

Suite 2560 → 2580. Live-checked against the running Studio 19.1.3.7 for the
probe semantics, the refusal path, the constant fallback, and the `get_version`
preflight (40 of 41 gates unavailable, as expected on that build). The Resolve 21
and 21.0.4 surfaces themselves remain untested here — this machine cannot run
them — and the Extras-pack failure paths are pinned by a stub that reproduces
the measured attribute-fabrication behaviour rather than by a live 21 build.

## What's New in v2.88.0

The twelve Resolve 21.0.4 surfaces that only existed on the compound server now
exist on the granular one too. Issue #140, PR #142 by @legionsound.

### Added

- **Twelve granular tools closing the 21.0.4 delta.** `get_layout_preset_list`,
  `get_burn_in_preset_list` and `delete_burn_in_preset`; the six
  `*_user_preferences_preset` tools; `get_project_attributes_in_current_folder`;
  `get_clip_timeline`; and `get_selected_timeline_items`. Each is guarded with
  `_requires_method` at 21.0.4, so an older build gets a named version error
  rather than an attribute crash, and each returns the same shape its compound
  counterpart does. `get_selected_timeline_items` is deliberately not called
  `get_selected_clips` — that name belongs to the Media Pool selection tool, and
  the collision was the confusion the issue reported. The granular server is now
  353 tools.
- **`load_user_preferences_preset` carries the SESSION-WIDE warning** in its
  docstring, matching the compound action. It swaps the user's global Resolve
  preferences, not a project setting.

### Fixed

- **Four places still said 341 after the count moved to 353, and the guard that
  exists to catch exactly that was not looking at any of them.** The literal in
  `tests/test_import.py` was the one that bit: that file is pytest-style, so
  `unittest discover` never collects it, and a green 2560-test run said nothing
  while `python tests/test_import.py` — the smoke step in the publish workflow
  and step one of the release process — failed. The other three were the startup
  log line in `src/resolve_mcp_server.py`, `docs/install.md` (which had also been
  quoting 32 compound tools since the compound server reached 34), and the badge,
  server-modes table and metrics table in `README.zh-CN.md`. All six files are in
  `test_doc_tool_counts` now, along with the English README's Tools badge, so the
  next count change fails offline instead of at publish time.

### Validation

- 2560 offline tests OK; `python tests/test_import.py` exits 0; agent-rules
  drift check in sync.
- The twelve 21.0.4 methods were exercised live on Studio 21.0.4.5 by the
  contributor — full round-trips for the layout, burn-in and user-preferences
  preset families, project attributes across 8 projects, and both branches of
  `get_clip_timeline`. `LoadUserPreferencesPreset` was deliberately not executed,
  by them or here. The validation machine for this repo runs 19.1.3, so the live
  results stay attributed to the reporter in `docs/reference/api-coverage.md`.
- What could be checked live here was: against a running Studio 19.1.3.7, the
  new tools return their named `requires DaVinci Resolve 21.0.4+` error rather
  than crashing on a missing attribute — the guard path exercised against a real
  Resolve object, not a stub.

## What's New in v2.87.2

A refused `SetSetting` now says why, when the ledger already knows. Issue #141,
reported by @jus-kim.

### Fixed

- **`project_settings set_setting` returned a bare `{"success": false}` for a
  key that can never be written.** `Project.SetSetting('timelinePlaybackFrameRate')`
  refuses every value form, before and after a timeline exists — measured in
  PR #99, written into `api_truth`, published in `api-limitations.md`, and
  invisible at the one moment it mattered. A bare `false` reads as *your value
  was wrong*, which sends a caller into retrying string, int, and float for a
  key with no writable path at all. A refusal now carries the ledger entry for
  that key: what is really happening, and the UI step that is the way through.
  `timeline set_setting` gets the same treatment.
- The match is deliberately narrow. It requires the exact quoted key on the
  right object — `Project.SetSetting('x')` will not be handed to a `Timeline`
  refusal, and a substring like `timeline` will not collect the
  `timelinePlaybackFrameRate` entry. An unmeasured refusal stays bare, because
  inventing an explanation for a failure nobody measured is the thing this
  ledger exists to prevent. The write is always attempted first, so a key that
  starts working in a later build reports plain success.

### Documentation

- **The `timelinePlaybackFrameRate` ledger entry carries the second report.**
  Issue #141 confirms it independently on **Resolve 20.2**, against a freshly
  created project whose timeline rate already read 60 — so a matching
  `timelineFrameRate` does not unlock the write, which the PR #99 measurement
  alone left open. The reporter's workaround is now recorded too: for repeat
  setups, duplicate a project that already carries the wanted playback rate
  rather than creating one and trying to write it.

## What's New in v2.87.1

Follow-up evidence from @legionsound on PR #139, plus the process fix for the
tooling failure that PR exposed.

### Changed

- **`import_user_preferences_preset` now says what the preset ended up called.**
  The no-name path was the one branch in v2.87.0 with nothing behind it — it
  calls the single-argument binding, which would have been a `TypeError` rather
  than a graceful failure if the binding wanted two positionals. Round-tripped
  on Studio 21.0.4.5 (export → delete → import both ways): the single-arg form
  returns `True`, and the imported preset is **named after the file**. The
  answer now carries that, so a caller who passed no name knows to read the
  name back with `list_user_preferences_presets` instead of guessing.

### Documentation

- **`api-coverage.md`: the import/export rows carry the round-trip**, not
  `dir()` membership. Still 🔬 and still 23 untested of 361 — the counting
  convention is unchanged, because none of this was executed here. What changed
  is the strength of the contributor's evidence behind two of the rows.
- **`AGENTS.md` now states how the API snapshot must be refreshed:** copy the
  shipped `Developer/Scripting/README.txt` over it wholesale, never hand-add the
  lines you already know about. A hand-patch carries a newer `Last Updated:`
  header while hiding everything you did not know to look for — which is
  precisely how the file sat eight weeks stale at 26 May 2026 while ten
  documented 21.0.4 methods went unwired. The v2.87.0 snapshot was verified as a
  wholesale replace (md5 `d732b3f6c1da08dc516bc8f80c5acd92`, byte-identical to
  the 21.0.4.5 shipped file per the contributor).

## What's New in v2.87.0

The ten Resolve 21.0.4 scripting surfaces that the 24 Jul 2026 README refresh
documented beyond the three wired in v2.86.0. Contributed by @legionsound
(PR #139), who reported them as issues #135–#138 from Studio 21.0.4.5.

### Added

- **`layout_presets` gains `list`** (`Resolve.GetLayoutPresetList`). The tool
  had six actions and every one of them took a preset name the caller had no
  way to enumerate.
- **`render_presets` gains `list_burnin` and `delete_burnin`**
  (`Resolve.GetBurnInPresetList` / `DeleteBurnInPreset`). `list_burnin` is the
  missing half of the burn-in surface: the `DataBurnIn` render setting and both
  `load_burnin_preset` actions take a name nothing could list.
- **`resolve_control` gains the six `*_user_preferences_preset` actions** —
  `list`, `save`, `load`, `delete`, `import`, `export`. Two caveats are carried
  in the docstrings and answers rather than left to be discovered:
  `load_user_preferences_preset` is **session-wide** (it swaps the user's global
  Resolve preferences, not a project setting), and
  `import_user_preferences_preset` answers with the README's own caveat that the
  imported preset is *not* auto-loaded, so a caller follows with `load` instead
  of stopping early.
- **`project_manager` gains `list_attributes`**
  (`ProjectManager.GetProjectAttributesInCurrentFolder`) — `lastModifiedDate`,
  `creationDate`, `notes`, and `liveCollaborationMode` per project in the
  current folder, without loading any project.

All ten are `_requires_method`-guarded at 21.0.4, advertised in the capability
and preset-lifecycle probes, and covered by 21 stub contract cases in
`tests/test_resolve2104_preset_actions.py` (answers, name-required errors,
pre-21.0.4 guards, `_unknown` listings, capability advertisement on both a
21.0.4 and a legacy stub).

### Documentation

- **`docs/reference/resolve_scripting_api.txt` was the 26 May 2026 README** —
  which is exactly why this delta went unnoticed. It is now the 24 Jul 2026
  text these wrappers came from.
- **`api-coverage.md`: 351 → 361 methods**, with the ten new rows marked 🔬 and
  carrying the contributor's Studio 21.0.4.5 results as a contributor report,
  not as validation of ours — this machine runs Studio 19.1.3 and free 21.0.3,
  neither of which is 21.0.4. `LoadUserPreferencesPreset` is recorded as
  deliberately unexecuted even by the reporter, same class as
  `DisableBackgroundTasksForCurrentResolveSession`.
- **The README key stats were stale at 349** since the v2.86.0 surfaces landed;
  both READMEs and the live-tested badge now read 361 covered / 338 live-tested
  (93.6%), and the English tested-against row picks up the free 21.0.3 build the
  coverage doc already listed.

## What's New in v2.86.4

The issue #132 follow-up, which turned out not to be a tool bug at all. No
behavior changed in any tool.

### Fixed

- **The skills told an assistant to "route the user to the UI" and stopped
  there, so it invented the directions.** In issue #132 a user was sent hunting
  for a retime dropdown "in the lower left of the clip"; the keyframe tray was
  never mentioned. That direction exists nowhere in this repo — no skill, doc,
  or ledger entry describes where any Resolve control sits. The assistant
  improvised the handoff and delivered it in the same confident register as the
  API facts around it, which had been measured, so the user had no way to tell
  the two apart. `resolve-edit` now carries the rule: **never improvise UI
  geography.** Name the operation, say you cannot see the user's screen, and
  treat a UI pointer already written into a skill (the playback-frame-rate path
  in `resolve-rough-cut`) as the only kind to quote — verbatim, never extended
  from memory. Where no pointer exists, point at Blackmagic's manual for their
  build rather than supplying one. `resolve-rough-cut` picks up the same guard
  at its own UI handoff.

  Deliberately **not** fixed by adding the correct location. This repo verifies
  API behavior and has no mechanism to version-guard a UI claim — every
  `api_truth` entry is stamped with the build it was measured on because
  unstamped claims rot, and UI geography moves between builds, pages and
  layouts with no drift guard that would catch it going stale. The reporter hit
  this on Resolve 21; the validation machine here is Studio 19.1.3.7, so
  confirming a location here and publishing it for 21 would be the exact move
  v2.82.1 exists to correct. Thanks to @magwa101 for coming back with the
  detail that relocated the bug.

## What's New in v2.86.3

A Simplified Chinese phrasing fix from the reviewer who asked for it when #122
merged. No behavior changed.

### Documentation

- **The Linux bridge sentence in `README.zh-CN.md` now reads as native Chinese.**
  `直接对系统 Python 列出脚本` was translationese; it is now
  `用系统 Python 就能直接枚举脚本`. The same sentence picks up two terms the
  macOS paragraph three lines above was already using — `framework 版 Python`
  (the `版` was missing) and `枚举` for script enumeration — so the two
  paragraphs describe the same Resolve behavior with the same words. The claim
  itself is unchanged: the issue #129 Fedora 43 report still stands behind it.
  Thanks to @chenyuxiaojin (PR #134).

## What's New in v2.86.2

Two free-edition/render limitations found while trying to photograph a styled
caption, both of the "returns success, does nothing" shape.

### Documented

- **Studio-gated calls on the free edition raise a modal that blocks LATER
  calls.** The reference documents that a Studio-only function returns `False` on
  the free edition. It does not mention that Resolve also throws a modal upsell
  dialog, and that while it is up, *unrelated* API calls fail too. Confirmed on
  free 21.0.3.7 over the bridge: `CreateSubtitlesFromAudio` and `TranscribeAudio`
  each returned `False` and raised the dialog, after which `SaveProject` returned
  `False` on every attempt until a human dismissed it. Nothing in any return
  value names the dialog, so an automated caller sees a cascade of unexplained
  failures and blames whatever it called next. Detect the edition first rather
  than discovering the gate by tripping it.

- **A render with `ExportSubtitle` / `SubtitleFormat: BurnIn` produced no
  subtitles at all** — no burned-in pixels, no embedded stream, no sidecar —
  despite `SetRenderSettings` reporting success. Recorded as an observation, not
  asserted as a Resolve bug: an unmet precondition (a Deliver-page toggle, output
  enablement) is equally consistent with what was seen. Either way the guidance
  holds — verify the artifact, never the boolean.

## What's New in v2.86.1

Corrects `api-coverage.md` where today's live work on the free edition made it
inaccurate.

### Documentation

- **`GetFairlightPresets` is now recorded as verified from both sides** — live on
  20.3.2 Studio and 21.0.3 free, and confirmed *absent* on 19.1.3, which pins the
  20.2.2 floor rather than assuming it.
- **`ApplyFairlightPresetToCurrentTimeline` says what its ⚠️ actually means.** It
  was reported as "accepts call; returns False without a named preset", which
  reads like a quirk. The real state: it has never been exercised against a
  genuinely saved preset, so no `True` path has ever been observed. The API
  cannot create a preset, and `GetFairlightPresets` returned an empty map on both
  machines, so clearing this needs a preset saved in the Fairlight UI first. The
  entry now says so.
- **The tested-against list includes Resolve 21.0.3 free**, reached through the
  in-app bridge, and the notes that said the validation machine "runs 19.1.3" now
  name both builds present.

## What's New in v2.86.0

The Resolve 21.0.4 scripting-API surfaces, plus a `project_db` fix found while
validating the subtitle-style work against the free edition over the new
automatic bridge.

### Added

- **The three new Resolve 21.0.4 scripting-API surfaces are wired** (PR #133),
  with the 21.0.4 settings keys advertised in the render tool docstring.
  `AddFrameHandles` warns when Resolve silently ignores it rather than reporting
  a success that did not happen, and the `get_timeline` path is guarded; both
  are covered by tests.

### Fixed

- **`project_db` resolved by `projectName` only ever searched the Studio project
  library.** The free edition ships from the App Store and runs **sandboxed**, so
  its library is not under Application Support at all — it lives inside the app
  container, under a differently-named root (`Resolve Project Library`, not
  `Resolve Disk Database`). Every free-edition user hit `no Project.db found`
  and had to supply an absolute path they had no reason to know. Both roots are
  now searched, Studio first, results deduplicated, and a miss names both paths
  it looked in. Confirmed on free 21.0.3.7, macOS.

  macOS-only by design: the sandbox container is an Apple construct, and where
  the free edition keeps its library on Windows and Linux is not verified here,
  so nothing is guessed for those platforms — `projectDb` still takes an
  explicit path.

### Validation

- **Subtitle caption styling is now confirmed on BOTH editions.** v2.82.0 proved
  the write path on Studio 19.1.3; it now also passes on free 21.0.3 with
  *identical* behaviour — Resolve parses the uncompressed `0x80` payload, and on
  its next re-serialisation of that track writes the style back as `0x81` zstd
  with the font descriptor and position preserved exactly, dropping the same
  neighbouring key both times. A freshly added subtitle track carries no style
  blob on either version.

- **The automatic bridge fallback shipped in v2.85.0 is confirmed live.** The
  free edition connected with no `DAVINCI_RESOLVE_BRIDGE` set — the transport it
  refuses outright — so the fallback is what carried the session.

- **`GetFairlightPresets` works on 21.0.3**, returning a preset map. It is absent
  on 19.1.3, confirming the 20.2.2+ floor from both sides. `apply_fairlight_preset`
  still awaits a genuinely saved preset (issue #128).

## What's New in v2.85.0

The free edition now works with no environment variable at all — start the
in-Resolve bridge and the server finds it.

### Changed

- **The in-app bridge is used automatically when external scripting is
  unavailable.** Previously it was strictly opt-in: without
  `DAVINCI_RESOLVE_BRIDGE=1` the bridge was never tried, so a free-edition user
  who had installed and started it still got a connection error until they also
  set a variable — a chicken-and-egg the error text had to explain.
  `connect_resolve` now falls back to the bridge when a direct transport yields
  nothing, including when Blackmagic's Python module is missing entirely (the
  bridge does not need it, which is the whole reason it reaches editions the
  module cannot).

  `DAVINCI_RESOLVE_BRIDGE=1` keeps its exact previous meaning and is now a
  *force* flag: the bridge becomes the only transport tried, so a bridge that
  stops answering reports its own fault instead of silently degrading to another
  path. That property is why the fallback runs *after* a direct attempt rather
  than before — it can only engage where the old code had already given up, so
  it cannot mask a broken bridge.

### Fixed

- **Five surfaces described the variable as required**, which the change above
  turns from true into false. The worst was `scripts/doctor.py` — the tool people
  run precisely when they are confused — reporting "the bridge is installed but
  will not be used". Also corrected: the launcher banner every free-edition user
  sees on startup (the one quoted in issue #109), the `install.py` post-install
  hint, a `src/server.py` log line, and the `BridgeUnavailable` message in the
  bridge client. English and Chinese READMEs, `docs/SKILL.md` and the session
  skill updated to match.

- **A drift guard now fails the build if that text contradicts the connector
  again.** It rejects the specific phrasings that assert the variable is
  required, and requires any surface naming the variable to also say it *forces*
  the bridge — naming it without saying what it does is how the old wording read
  as "required" while being technically true.

## What's New in v2.84.0

Guidance now depends on the build you are actually connected to, and the README
speaks Chinese.

### Added

- **Version-aware routing** (issue #132). The scripting API changes per **patch**
  release, so "Resolve 21" is not a label you can reason from: `GetFairlightPresets`
  exists on 20.2.2 and not 19.1.3, and three surfaces reported in 21.0.4 are
  absent from 21.0.2. Skills and `api_truth` previously gave identical guidance
  whatever was connected, which is how an agent ends up insisting a method is
  there when it is not — exactly the report in #132.

  `utils/resolve_versions.py` parses the three shapes Resolve reports a version
  in (the `GetVersion()` list, `GetVersionString()`, and prose), compares them
  patch-precisely, and holds `VERSION_GATES` — only surfaces with evidence, each
  tagged **measured / reported / vendor** so a relayed fact can state how strong
  it is. All shipped gates were confirmed `dir()`-absent on live 19.1.3.7.

- **`resolve_control check_version_support(symbol?, resolve_version?)`** — does
  *this* build have that method? Omit `symbol` for every recorded gate the build
  does not clear. **`api_truth` now takes `resolve_version`** and annotates each
  fact with whether it was measured on an older, newer or identical build.
  Neither ever connects: `api_truth` is the one call that still answers when
  Resolve is down, and that is worth keeping.

  Two defaults carry the weight. **`unknown` means probe, not yes** — most of the
  API has never been version-bisected, and a false "available" is the failure
  being fixed. And the ledger-wide `VERIFIED_ON` stamp is **never** attributed to
  an individual fact: most entries record their real build in prose, so stamping
  each of them would invent a measurement that never happened.

- **`README.zh-CN.md`** — Simplified Chinese translation (PR #122,
  @chenyuxiaojin), brought current rather than merged at its original v2.80.1.
  `docs/process/release-process.md` now lists it among the surfaces every release
  must update, naming deletion as an acceptable outcome: because the file states
  which release it matches, going stale turns it into a false claim rather than
  vague oldness — and no CI check can catch that, since a lagging translation is
  still valid Markdown.

### Changed

- **The skills ask the build before promising a capability.** `resolve-session`
  gains a step that asks what the build *cannot* do before any project or
  timeline is read, and reports both the Resolve build and `mcp.version` — a
  running server keeps executing the version it started with, so `git pull` does
  not refresh its ledger until restart. `resolve-audio`, `resolve-delivery`,
  `resolve-edit` and `resolve-media-pool` each carry the specific gate that bites
  them rather than a generic reminder; `resolve-color`, `resolve-conform` and
  `resolve-fusion` deliberately get nothing, since no gates are recorded for them.
- `resolve-edit` now states plainly that **there is no clip-speed API at any
  version** — `set_retime` sets retime *quality* and returns `True` for doing so,
  which is the misread behind #132.

### Fixed

- **An `api_truth` entry that had been UNRESOLVED is now partly settled**, because
  writing the probe advice required knowing what a probe actually does. The entry
  asked for five real borrowed method names to be re-run; done on 19.1.3.7 over
  the direct connection, 42 checks across seven object types. No fabrication —
  every one was `getattr`-callable `False` and `dir()`-absent, agreeing in all 42
  cases. The same run showed **bare `hasattr()` returns `True` for every name on
  every Resolve object**, real or invented: it is not a weak probe, it carries no
  information at all. Bridge-side fabrication remains untested, so the
  `dir()`-membership recommendation stands.

## What's New in v2.83.0

Transcript-reading features now say what they cannot see, and the clip-colour
work that shipped undocumented in v2.82.1 is written down.

### Added

- **`possible_swallowed_retake` flags on `plan_transcript_tighten` and
  `rank_takes`** (issue #125, measured by @chenyuxiaojin). When a speaker
  re-reads a sentence immediately, whisper emits the text **once**, aligns it to
  the first take, and absorbs "pause + entire second take" into the duration of
  a single word. Every transcript-reading feature inherits that: the plan cannot
  propose removing a restart it was never told happened, and fluency scoring
  ranks a take that stumbled and recovered above one that did not. Energy
  detection cannot cover for it either — in the original measurement the
  swallowed span peaked at **-12.1 dB against adjacent real speech at -16.7 dB**,
  so `silencedetect` recalled 3 of 17 instances at any threshold.

  The detector is one absolute bar: any word longer than 1.2s. That is
  deliberately dumber than two designs that were tried and measured on English
  material first. A characters-per-second gate — which worked on the original
  Chinese — fires on **0 of 50** English segments, so it is retired rather than
  made configurable. Scoring each word against the distribution of its *own*
  durations elsewhere in the take missed the swallow entirely and produced 8
  false positives, all function words, for a structural reason worth keeping:
  the words that absorb retakes are content words, and content words are rare
  within a single take, so they never accumulate a distribution to score
  against. The plain bar found exactly one stretched word in 191.5s and it was
  the swallow point.

  It emits a flag and never a cut point, because where inside the stretched word
  the second take begins is exactly what the swallow destroyed. The English
  confirmation rests on **n=1** in synthetic material; the Chinese measurement it
  generalises from had 17 real instances.

- The `rank_takes` caveat now states the undercount directly rather than leaving
  it to be discovered.

### Changed

- The `SetClipColor` `api_truth` entry records the sharper form of the trap
  (@chenyuxiaojin): it is not that a decoy vocabulary exists, it is that the
  decoy **half-works**. Five names live in both palettes, so probing from the
  marker constants scores 5 of 16 — which reads as an unreliable API rather than
  as a wrong vocabulary. A clean 0-for-8 would have exposed the mechanism at
  once.

### Note on v2.82.1

The clip-colour fix described below shipped **in v2.82.1**, whose release notes
described only the subtitle-style version correction. The code was correct and
released; only its documentation was missing. Recorded here rather than by
rewriting a published release.

## What's New in v2.82.1

Corrects the Resolve version the v2.82.0 subtitle-style validation was actually
run against — and, undocumented at the time, fixes `SetClipColor`.

### Fixed

- **`SetClipColor`'s value space, enumerated live** (issue #124, reported by
  @chenyuxiaojin). The accepted set is exactly the 16 Edit-page clip colours —
  Orange, Apricot, Yellow, Lime, Olive, Green, Teal, Navy, Blue, Purple, Violet,
  Pink, Tan, Beige, Brown, Chocolate — and it is **identical on `TimelineItem`
  and `MediaPoolItem`**, which the report flagged as unmeasured. Everything else
  is refused with a bare `False`, the empty string included. The scripting
  reference documents `colorName` as a bare string with no enumerated values
  while exporting the *marker* palette as constants, so the only colour
  vocabulary reachable from the API surface is the wrong one.
- **A second failure the report did not contain: on generator and title items
  `SetClipColor` returns `True` and the colour does not persist.** `GetClipColor`
  still reads empty immediately after. A media-backed item on the same timeline
  in the same session persists correctly, so the bool is honest for some items
  and a lie for others with nothing in the return value to separate them.
- All three call sites now read the colour back instead of returning the bare
  bool, and a refusal names the measured-valid set. The set is deliberately
  **not** enforced: it was measured on one build, and hard-rejecting an unlisted
  name would turn a working call into a failure on a Resolve we have not seen.

- **v2.82.0 claimed the subtitle-style write path was confirmed on Resolve 21.
  It was confirmed on Resolve Studio 19.1.3.** The validation itself stands —
  Resolve opened the patched track and re-serialised it to its own zstd form
  with the patched values intact — but it was run against 19.1.3, which is the
  build that was installed. Corrected in `api_truth`, the codec header, and the
  changelog. If anything this widens the supported range rather than narrowing
  it, but the version on the claim has to be the one actually tested.
- **`GetFairlightPresets` / `ApplyFairlightPresetToCurrentTimeline` require
  Resolve 20.2.2+**, now recorded in the `api_truth` Fairlight entry. On 19.1.3
  both are absent (confirmed live), so on older builds the per-parameter gap
  really is the whole story and the preset workaround is unavailable.

## What's New in v2.82.0

Caption styling, which the scripting API cannot touch at all, is now readable
and writable — plus a correction to a claim this repo was about to send to
Blackmagic.

### Added

- **`project_db list_subtitle_styles` / `set_subtitle_style`** — read and patch
  the caption style on a subtitle track: font family, point size, weight,
  italic, and normalised on-screen position. The scripting API exposes none of
  this (subtitle `TimelineItem`s return only the 21 transform/composite
  properties, and every `subtitleFontName`/`subtitlePreset`-shaped setting key
  returns `None`), but the style is persisted in `Sm2TiTrack.FieldsBlob` for
  `Type = 2` tracks: a keyed-dict holding an `EffectFiltersBA` payload whose
  effect 136 carries a Qt `QFont::toString()` descriptor (param 18) and a
  position vector (param 17). New codec at
  `resolve-advanced/vendor/drp-format/subtitle-style.js`.

  Verified live on Resolve Studio 19.1.3 (2026-08-06): a patched track opens without error
  and, once Resolve next re-serialises it, is written back out in Resolve's own
  zstd form with the patched values intact — so Resolve genuinely parses the
  write rather than passing the bytes through. Read side verified against a
  real project carrying 12 subtitle tracks.

  Caveats, all reported by the tool: this is a whole-**track** style and not
  per-caption, the project must be CLOSED, Resolve must be fully quit and
  relaunched afterwards, and the track must already carry a style blob — a
  freshly added subtitle track has none until it is styled once in the UI.

  Only the font descriptor and position are named. The neighbouring parameters
  vary across real projects but have not been correlated against the UI, so
  they round-trip untouched and are reported as opaque rather than guessed at.

### Fixed

- **The `api_truth` Fairlight entry claimed more was missing than actually is.**
  It read "only voice-isolation state and channel-mapping reads are scriptable",
  which omits `Project.ApplyFairlightPresetToCurrentTimeline(name)` — already
  exposed as `project_settings apply_fairlight_preset`, with the names coming
  from `resolve_control get_fairlight_presets`. The real gap is *per-parameter*
  control (volume/pan/EQ/automation/FairlightFX), not the whole surface. Since
  this text generates `docs/reference/api-limitations.md`, the incorrect claim
  was headed for the Blackmagic submission. The subtitle-styling entry got the
  same treatment: it claimed no workaround existed, which the above now closes.

### Documented

- **AI Audio Assistant has no scripting method** — logged with the reason, which
  is *not* that it is a menu command: the API has no generic menu-invocation
  hook, so scriptability is per-feature, and `DetectSceneCuts`, `Stabilize`,
  `SmartReframe` and `TranscribeAudio` are all menu commands that do have
  methods. For a repeatable mix, save the Assistant's result as a Fairlight
  preset once and apply it per-timeline (issues #127, #128).

## What's New in v2.81.0

One render bug where every readback agreed and the file disagreed, plus the two
community skill contributions that were open against it.

### Fixed

- **`prepare_render_job` inherited the Deliver page's loaded preset, and could
  queue an mp4 that rendered with no video stream** (issue #123, reported with
  a full measurement by @chenyuxiaojin). `SetRenderSettings` applies the keys a
  caller passes *on top of* whatever render state the Deliver page is holding
  rather than replacing it, and a loaded preset carries more state than those
  keys. Measured 2026-07-08: after an MP3 render through the stock **Audio
  Only** preset, a job queued with an explicit `ExportVideo: true` and an `.mp4`
  target returned `settings_success: true` and a real `job_id`, `list_jobs`
  reported `IsExportVideo: true`, and the rendered file held only an AAC stream.
  The single visible tell was 18 minutes of material "rendering" in ~10 seconds.

  No caller-side check could have caught it, and the reason is worse than the
  bug itself: the scripting API documents neither `GetRenderSettings` nor
  `GetCurrentRenderPresetName`, so the inherited state cannot be read at all.
  Detection is unreachable; only pinning is.

### Added

- **`from_preset` on `prepare_render_job`** (and through
  `prepare_delivery_job`) runs `LoadRenderPreset` before the explicit settings
  go on top, so a caller pins the base state instead of inheriting one.
  `PresetName` flipping to `Custom` once the explicit settings land is expected.
  The name is validated against `GetRenderPresetList` first, because
  `LoadRenderPreset` refuses an unknown name with a bare `False` that is
  indistinguishable from any other refusal — and a `False` of either kind now
  refuses to queue rather than falling through to an inheriting render.
- **An inherited-state warning** when a job asks for `ExportVideo: true` without
  a pin, naming the risk and saying plainly that the job readback is not a
  witness for the rendered file — verify a `codec_type=video` stream before
  reporting a deliverable. The `before` snapshot now also reports
  `settings_readable: false` and what is unreadable, instead of leaving the gap
  unnamed.
- **`resolve-tighten-recording` skill** (PR #126, @chenyuxiaojin) — the
  subtractive counterpart to `resolve-rough-cut`: one long single-take recording
  in, a tightened variant timeline out, original untouched. Measured live
  against Studio 21.0.1.11 on a real 28.5-minute recording. Its centerpiece is
  the coordinate-system trap between plan `keep_ranges` (source frames,
  exclusive end) and `structural_diff.added` (record frames) — feed one where
  the other is expected and every clip lands at the wrong moment of the right
  file, with correct cut lengths and no error. Also documents the three classes
  of content silence-driven tightening cannot hear, including the whisper
  swallowed-retake blind spot (issue #125).

### Changed

- **`resolve-rough-cut` reconciled with the `api_truth` ledger** (PR #115,
  @bolnet). Two rows contradicted the ledger the skill itself points at. Import
  order was backwards — `ImportMedia` has no destination parameter and always
  lands in the *current* folder, so the bin must be created and made current
  *before* importing. And the traps table still asserted that a comp attached to
  a media clip "never renders", a blanket claim the ledger retracted on
  2026-08-02: a comp wired `MediaIn → Blur → MediaOut` does render, and an
  unrooted `MediaOut` fails the render job outright rather than being silently
  bypassed. Every row now names the build it was confirmed on, and a note
  records that a **running** MCP keeps executing the version it started with, so
  `git pull` does not refresh the ledger until restart.
- The skill index in `docs/README.md` now lists the two end-to-end assembly
  recipes (`resolve-rough-cut`, `resolve-tighten-recording`), neither of which
  had ever appeared there, and `resolve-edit` points at the tighten skill.

## What's New in v2.80.2

Agent tooling only. Ten Claude Code skills that this repository has shipped and
advertised were never loading; they load now. No runtime behavior changed and
nothing under `src/` was touched.

### Fixed

- **The ten `.claude/skills/` domain skills were invisible to every agent.**
  Claude Code discovers skills at `.claude/skills/<name>/SKILL.md`. All ten were
  loose `.md` files at the top level of that directory — a layout the loader
  does not scan — so `resolve-color`, `resolve-edit`, `resolve-conform`,
  `resolve-delivery`, `resolve-audio`, `resolve-fusion`, `resolve-media-pool`,
  `resolve-media-analysis`, `resolve-rough-cut`, and `resolve-mcp` never
  appeared in a session, while the generated domain-routing block in `AGENTS.md`
  and the index in `docs/README.md` both listed them as available. The failure
  was silent: no warning, no error, no degraded mode. Each skill now lives in a
  directory named for its frontmatter `name` (recorded as 100% renames, so
  history follows), and both `docs/README.md` and
  `scripts/agent-rules/README.md` — the file consulted when authoring a new
  skill — state the directory requirement so the next one is not written back
  into the bug.

### Added

- **Two opt-in `PreToolUse` guard scripts** for rules `AGENTS.md` has only ever
  stated in prose. They ship as scripts and are deliberately *not* wired
  repo-wide; `docs/README.md` carries the block to paste into a personal
  gitignored `.claude/settings.local.json`. `frame_verification_guard.py`
  refuses grade-applying actions on `timeline_item_color` until the session has
  actually looked at a Resolve-rendered frame, and asks before `safe_copy_grade`
  / `bulk_match_to_hero` push a whole-grade artifact across clips; `dry_run`
  passes through. `source_media_guard.py` refuses shell commands that write,
  move, or delete source media outside a scratch root — paths are normalized and
  matched by whole path component, and a derivative-output directory
  (`proxies`/`renders`/`exports`) exempts a *write* but never a delete or a
  move, so a camera card with an `exports` folder is still a camera card. Its
  docstring states what it cannot catch — extension-less directory deletes,
  `find -delete`, `xargs rm`, and scripts that write media themselves — because
  it is a tripwire for the common direct mistake, not a sandbox.
- **Two review subagents** in `.claude/agents/`, run in their own context so
  frame images stay out of the main session. `cut-reviewer` screens an assembled
  timeline from its frames and is told explicitly that a metadata summary is not
  a review, because assembling through an API succeeds loudly and fails quietly.
  `grade-match-verifier` measures shot match numerically against the project's
  R−B tolerance and must report the pixel count behind every masked
  measurement — a near-empty skin mask returns a delta near zero and reads as a
  perfect match.
- **Two skills outside the domain routing.** `house-style` accumulates editorial
  corrections so the same note is not given twice, and `/resolve-session`
  reports connection, edition, project, timeline, and media-pool state before
  editing begins.

### Validation

- Full offline suite: 2460 passed, 1 skipped — level with the v2.80.1 baseline,
  as expected for a change that touches no runtime code.
- Both guard scripts exercised against a 26-case matrix covering deny, ask, and
  silent-allow: `ffprobe` reads, `ffmpeg` into scratch, `ffmpeg` overwriting a
  card, chained `ffprobe && rm`, redirection onto a media file, glob `rm`,
  quoted paths, writes into `renders`/`proxies`/`exports`, deletes out of those
  same directories, `..` traversal, and ordinary repo commands (`git status`,
  the test runner, `npm run build`).
- No live Resolve validation: no behavior changed.

## What's New in v2.80.1

A correction to the retime measurement contract published in v2.80.0, and a fix
for a documented timecode conversion that never happened.

### Fixed

- **`timeline_markers.set_current_timecode` now honors the documented
  elapsed-timecode conversion.** The tool doc has always said timecodes before
  the timeline start are treated as elapsed time and converted automatically —
  but only marker actions did the conversion. `set_current_timecode` passed the
  raw string to `Timeline.SetCurrentTimecode`, which refuses sub-start
  timecodes with a bare `False` and no error info (measured on Studio 19.1.3.7:
  on a timeline starting `00:59:50:00`, `00:00:21:03` failed while
  `01:00:11:03` succeeded). The wrapper now lifts elapsed timecodes by the
  start frame — `00:00:21:03` lands the playhead at `01:00:11:03` — with
  drop-frame-correct formatting on DF timelines. Absolute timecodes and strings
  the parser cannot read pass through unchanged. Marker `add()`'s conversion
  was re-verified live on a non-zero-start timeline (elapsed `00:00:21:03` →
  relative frame 507) and was already correct.

### Documentation

- **🚩 Correction to v2.80.0's retime witness — the recommended instrument
  cannot see retimes.** The v2.80.0 retime entry recommended reading
  `GetLeftOffset`/`GetRightOffset` to tell whether a retime was built. A
  calibration with the confound removed (the SAME clip twice in ONE timeline,
  one copy hand-set to 200%, Studio 19.1.3.7) proves that pair reads the
  WARPED domain — position ÷ speed, span always equal to the record span — so
  it is exact for placement and structurally blind for speed. The corrected
  entry installs the calibrated model: judge speed by the
  `GetSourceStartFrame`/`GetSourceEndFrame` span vs the record duration (the
  200% copy read span 96 vs 48; a 0/0 read on xmeml-imported timelines is
  UNKNOWN, never "no retime"), cross-checked by the `Sm2TimeMap` slope in a
  saved Project.db or the `EXPORT_EDL` M2 rate.
- **Two import routes DO build constant retimes**, now documented with their
  emission rules: OTIO `LinearTimeWarp` through `ImportTimelineFromFile` (200%
  and 50% measured; `source_range.duration` is the RECORD span — the
  `time_scalar` handles source consumption; source frames timecode-absolute)
  and EDL `M2` in the exact shape Resolve's own `EXPORT_EDL` writes (200%
  measured; event-line source span equals the record span; `* FROM CLIP NAME:`
  drives linking). Reverse and varying-speed maps remain untested as import
  routes and the entry says so.
- `docs/reference/api-limitations.md` regenerated; the `GetSourceStartFrame`
  off-by-one entry now scopes its GetLeftOffset advice to 100%-speed placement.

### Validation

- Full offline suite: 2460 passed, 1 skipped (up exactly the 7 new tests from
  the 2453 baseline).
- Live Resolve Studio 19.1.3.7: new
  `tests/live_playhead_timecode_validation.py` harness — raw refusal control,
  elapsed lift to `01:00:11:03`, absolute pass-through, and marker add() at
  relative frame 507 all verified against a disposable project.

## What's New in v2.80.0

Three community PRs from @staahlarkitektur, all found on Windows, all real. Each is merged with
its diagnosis intact and a fix on top for what the patch didn't reach.

### Added

- **`background=true` now actually runs the analysis.** `background`/`async_job` were accepted on
  `analyze_clip` / `analyze_bin` / `analyze_file` / `analyze_project` / `analyze_sequence` and
  silently ignored — the call ran the whole analysis inline and returned no `job_id`, which from
  the caller's side is indistinguishable from a hang (#119). The two async opt-ins are now
  distinct and both do what their names say:
  - `prefer_handle=true` — creates the durable batch job and hands it back **queued**. Nothing
    runs until you call `run_batch_job_slice`. Unchanged contract.
  - `background=true` / `async_job=true` — creates the job **and drives it to completion
    off-thread**, matching what `background` means on every other tool in this server. Poll
    `batch_job_status` until `completed` / `completed_with_errors` / `canceled`.

  Aliasing the two, as the PR proposed, would have replaced one silence with a quieter one: a job
  that nothing ever advanced, polled forever. The runner deliberately does **not** hold the
  Resolve busy gate — analysis drives ffmpeg, whisper and vision over file paths and touches the
  scripting bridge nowhere, so holding it for an hour of transcription would lock the editor out
  for nothing. A process-wide slice lock bounds the real cost instead: queued analyses interleave
  a clip at a time rather than starting N ffmpeg passes at once.

### Fixed

- **A timeout could take 82 seconds to report a 5-second limit.** `subprocess.run(timeout=...)`
  kills only the direct child. On Windows a bare-name PATH lookup can resolve to a shim
  (Chocolatey, npm, a pip console script) that runs the real work as a grandchild, so the kill hit
  the wrapper while the real `ffmpeg` kept running — and the follow-up read blocked on the pipe
  handles it had inherited. Measured on a Chocolatey-managed machine: `ffmpeg` on PATH was a 392KB
  shim, and a 5s timeout against an ~82s pass returned after the full 82s with "timed out after
  5s" attached to complete, correct output (#120). `_run_command` now spawns via `Popen` in its own
  session/process group and kills the whole tree. Beyond the PR: the kill helper no longer raises
  (`killpg` returns EPERM, `taskkill` can be missing from PATH — either escaped and broke the
  return contract mid-failure), the read after the kill is bounded and says so when it gives up
  rather than hanging on a survivor, and a cancellation mid-run kills the tree instead of orphaning
  it. Fixes every `_run_command` caller at once — the whisper CLI and every ffmpeg pass in
  `_readthrough_analysis`, `silence_ripple`, and `deep_vision`.
- **The whisper CLI inherited a `PYTHONHOME` that killed it.** `PYTHONHOME`/`PYTHONPATH` point this
  server at Resolve's bundled Python so `DaVinciResolveScript` imports. Inherited by a child that
  is itself a *different* Python, they corrupt its stdlib resolution — and whisper's CLI is exactly
  that. Measured: whisper on 3.14 inheriting a 3.10 `PYTHONHOME` dies on `AssertionError: SRE
  module mismatch` (#118). The whisper subprocess now gets a scrubbed environment. This is the
  **shipped Windows configuration**, not a local quirk: `install.py` writes `PYTHONHOME` into
  generated client configs (issue #26) and `server.py` sets it on Windows whenever it isn't
  already set, so every Windows install hands a foreign `PYTHONHOME` to every child it spawns.

### Corrected in the merged PRs

- The documented async return shape was wrong — `{job_id, status}` was advertised, the real
  envelope is `{success, job, plan}` with the id at `job.job_id`. Now documented as it is, plus
  `running` and a `note` naming the next call so the queued and running routes can't be confused.
- The async divert ran *after* `dry_run` was resolved from the `dry_run_first_default` preference,
  so a user with that preference on still got `background=true` swallowed in silence. An explicit
  `dry_run` still wins; an inherited one no longer does.
- A code comment attributed the whisper failure to a silent stall with an ffmpeg child at 0% CPU —
  a diagnosis the PR's own description retracted, and one that belongs to the shim problem above.

## What's New in v2.79.2

A published contract was **wrong**. This release corrects it. If you read the retime entry in
v2.79.0 or v2.79.1 and built anything on it, read this.

### Corrected

- **The `Clip speed / retime ratio and speed ramps` entry stated a rule that does not exist,
  and missed the hazard that does.** The interchange half of that entry claimed *"any
  `<in>`/`<pproTicksIn>` inconsistency is silently REJECTED, measured in BOTH orientations."*
  **That claim is false and has been removed.** It came from an emitter that wrote
  `ticks = in × ticks-per-frame` at every speed — so what it measured was its own malformed
  files being refused, not a rule of Resolve's importer. In a real Premiere FCP7 export a
  retimed clip's `<in>` and `pproTicksIn` are *supposed* to disagree, by exactly the speed
  ratio: `<in>`/`<out>` are the post-retime (warped) domain and span the **record** duration,
  `pproTicksIn/Out` carry the **true source** position, and `<duration>` is the file length in
  the warped domain. The entry now states that convention with the tick arithmetic shown
  (254016000000/24 = 10584000000 ticks per frame), and notes that
  `resolve-advanced/server/prproj.mjs` already derives Premiere speed from the same tick
  geometry.
- **The graphdict evidence has been replaced.** The "dead in FOUR separate shapes / 0 of 2
  landed" table and the "200% clip emitted `in 200 / out 296` clamped to `out 248`" line
  described that same malformed input being normalized, and did not support the conclusion
  they were cited for. Re-tested on 19.1.3.7 in Premiere's actual convention — one 100%
  control clip plus one 200% clip per timeline — the document imports, the control lands
  correct, and the retimed clip reads back `src 1500..1548`: a 48-frame source span over a
  48-frame record span, i.e. no retime. Identical result with the graphdict removed. **The
  conclusion is unchanged** — the scripting-API xmeml import builds no retime — only the
  evidence behind it.
- **The real hazard, previously absent, is now documented.** **Resolve reads `<in>` literally
  as the true source frame**, honouring neither the ticks nor the graphdict. So importing a
  genuine Premiere XML that contains retimes places every retimed clip at `in ÷ ratio` — the
  200% clip above lands on source frame 1957 instead of 3914. No error, cut lengths still
  correct, every clip linked and online, timeline renders. It reads as a good conform while
  sitting at the wrong moment of the right file — the same failure class as the Avid AAF
  camera-file link, and `docs/guides/conforming-an-avid-aaf.md` now cross-references it.
- **The claim is scoped honestly.** All of it describes the **scripting-API** import
  (`ImportTimelineFromFile`). Resolve's **UI** importer (File > Import > Timeline) is
  **untested**, and that is how editors usually conform a Premiere XML — the entry no longer
  implies otherwise. The existing "no positive control" caveat is kept: no clip *known* to be
  retimed has been read back through `GetLeftOffset`/`GetRightOffset`, because there is no
  scripting path to create one.

The `SetProperty`/`GetProperty` half of the entry was re-measured on 19.1.3.7 and is
unaffected. `docs/reference/api-limitations.md` is generated from `src/utils/api_truth.py` and
was regenerated.

### Validation

- `gen_api_limitations.py --check`, `test_api_limitations_doc`, static/drift guards,
  `audit_api_parity.py`, agent-rules drift, `--help`/`--version`, `npm pack --dry-run`,
  `git diff --check`: clean.
- Docs-only; no code path changed, so no live Resolve validation was required.

## What's New in v2.79.1

One redirect that was never written, in a dispatcher whose other container formats all have one.

### Fixed

- **`parse_interchange` told `.drt`/`.drp` callers the format was unknown — for formats the
  same package parses.** `parseInterchange(format, content)` gives AAF and `.prproj` explicit,
  helpful redirects to their path-based readers, but `drt` and `drp` had no case at all and
  fell through to `unknown format 'drt' (edl|otio|xml|xmeml|fcp7|aaf|prproj)`. Meanwhile
  `list_sequences` in the same cluster parses both by path, and the tool description advertises
  it. So the cluster supports DRT, documents that it supports DRT, then tells the
  content-shaped caller it does not. The failure is silent downstream: a consumer that reads
  "unknown format" (or hands `{ content }` to `drt.parse`, whose schema wants `{ drtPath }`)
  records **zero events**, and an empty sequence is indistinguishable from an unsupported one.
  `parseInterchange` now throws the same shape of redirect the AAF and `.prproj` cases throw —
  naming the ZIP container, `parseDRT(path)`, and the two callable entry points — and the
  `default:` message lists `drt|drp` among the known formats. The `editorial`
  `parse_interchange` schema accepts `drt`/`drp` so the tool-level caller gets that redirect
  instead of a bare enum rejection, and `drt.parse` / `list_sequences` / `validate` now name
  the path argument they wanted rather than emitting a raw zod issue dump.

### Validation

- `resolve-advanced` suite: 778 tests, 748 pass, 30 skipped, 0 fail (4 new assertions, written
  first and confirmed failing on v2.79.0).
- Static/drift checks, `--help`/`--version`, `npm pack --dry-run`, `git diff --check`: clean.
- No Resolve behavior changed; this path never touches the Resolve API, so live validation was
  not required.

## What's New in v2.79.0

Six silent failures in the conform path, found by conforming a real Avid picture turnover
and cross-checking every step against Resolve's own behaviour on 19.1.3. The common shape:
a call that reports success, or reports nothing at all, and leaves you with a timeline you
believe is right.

### Fixed

- **`convert_to_interchange` promised speed survives the DRT target. It does not.** The DRT
  spec builder read four fields per event — start, duration, in, mediaFilePath — and never
  read `speed` or `reverse`. One level down is why: the DRT clip schema has no per-clip speed
  field at all, so there is nothing to write a retime into. A 200% clip and a reversed clip
  both landed at 100% forward and the caller was told the conversion succeeded — inside the
  module whose own description opens by naming "flattened retime → flag, skip-not-fake" as
  its guarantee. Since carrying speed through was not available, the `drt` target now returns
  **`flattened`**: one entry per retimed or reversed event, with its index, recIn, speed,
  reverse, source and reason. It is always an array (empty when there are no retimes), so a
  caller can tell "none to lose" from "this build is too old to report". `otio` (LinearTimeWarp)
  and `edl` (M2) still carry retimes and are now named as the targets to use for a cut that
  has them.
- **The vendored FCP7 emitter produced XML that Resolve 19.1.3 imports as nothing.** Three
  defects, all failing the same silent way — a clean-looking file and a Resolve that does
  nothing. (1) The file def had no `<timecode>` element; Resolve rejects the ENTIRE import
  over one absent block, not the one clip. (2) `<pathurl>` got XML escaping where it needed
  URL escaping, now percent-encoded per segment so `/` separators survive. (3) The sequence
  had no `<rate>`, which bisection showed was the single element standing between "no
  timeline" and a working import. Because a *wrong* timecode block is as fatal as a missing
  one, the emitter never guesses: clips whose media timecode is unknown emit no block and are
  reported through `fcp7TimecodeCoverage()`, which `buildPackage` attaches as `fcp7Timecode`
  with an `importable` flag.
- **Importing a timeline into the never-saved `Untitled Project` silently no-opped.** Resolve
  accepted the call, created nothing, and named no cause; the generic "Resolve created no
  timeline" error that came back pointed at missing media and `sanitize_media` — the wrong
  road, because the file is fine. `import_timeline_checked` now refuses before the call with
  a remediation naming the project state. **Behaviour change:** a call that previously
  returned a generic error now refuses earlier with a different message. The refusal is hard
  and has no override flag, because the call cannot succeed either way.
- **OTIO authored by `convert_to_interchange` would not import into Resolve.** Filed as a
  scripting-API limitation; it was not one. Exporting a timeline with `EXPORT_OTIO` and
  feeding Resolve's own file back proved the API imports OTIO fine — what it refuses is a
  document that is valid OTIO but not Resolve-shaped. The decisive requirement is that source
  frames be **timecode-absolute**: media starting at 01:00:00:00 has an available range at
  frame 86400, and 0-based source offsets put the clip outside it. The emitter now mirrors
  Resolve's own shape (Clip.2 with a `media_references` map, `available_range`, bare
  `target_url`, `global_start_time`) and takes each event's origin via `mediaStartTcFrame` or
  an absolute `srcTcFrame`. Events whose origin had to be assumed come back in
  **`mediaOriginAssumed`** rather than producing a file that imports as nothing.
- **`.otio` failures were misdiagnosed as missing media.** A `.otio` is JSON, so the
  sanitize/relink pass cannot parse it and its advice never applied. `sanitize_media` is now
  N/A for `.otio` as it already was for `.aaf`, and the no-timeline remediation names the
  document's shape and the frame origin instead.

### Documentation

- `api_truth`: the retime entry now records that **the read side is as dead as the write
  side** — `GetProperty('Speed'|'PlaybackSpeed'|'RetimeSpeed'|'ClipSpeed')` all return None on
  19.1.3.7, and the keyless property dict carries no speed value at all. It also records that
  the interchange route is closed (scalar speed filter ignored, `graphdict` dead in four
  shapes, `reverse` dropped, in↔pproTicks inconsistency rejected in both orientations) and the
  trap that makes it expensive to find: Resolve's own FCP7 export writes a degenerate Time
  Remap, so `EXPORT_FCP_7_XML` cannot witness a speed. Each claim now says which Resolve
  version it was measured on.
- `api_truth`: **`AppendToTimeline` does not overwrite an overlapping record** — the earlier
  item wins and the later append is dropped, leaving a silently short timeline.
- `api_truth`: **placements from an errored append chunk are not durable across a save** — a
  timeline verified at 573 items held 500 afterward. Every in-session read agrees with the
  wrong number; only a post-save read catches it.
- `api_truth`: `CreateTimelineFromClips`' clipInfo has **no track field** while
  `AppendToTimeline`'s does, with the empty-timeline + `add_track` + per-clip append workaround.
- `api_truth`: what Resolve's OTIO importer actually requires, and how to debug a refusal by
  diffing against an `EXPORT_OTIO` file.
- **New guide — `docs/guides/conforming-an-avid-aaf.md`.** Three Resolve-native mechanisms
  measured against one real turnover; all three fail. The most convincing-looking one fails
  worst: "Link to source camera files" links 878 of 882 items with **only 144 correct — 734
  wrong takes, 84%** — and then renders as a fully conformed timeline, with no offline media
  and no warning. The guide explains why the matching lands on adjacent takes and says plainly
  that the only witness which catches it is a frame comparison against a reference.

### Validation

- 2417 Python unit tests, 744 Node advanced tests, plus 8 fixture-free packaging tests, all
  green. `packaging.test.js` also no longer fails to load on a fresh clone: it read a
  git-ignored fixture at module scope, which took the fixture-free tests down with it.
- Live-validated on DaVinci Resolve Studio 19.1.3.7 with synthetic media: the fixed FCP7 XML
  imports 2 items / 2 linked where the same file with its timecode blocks stripped imports
  nothing; the authored `.otio` imports 3 items / 3 linked and re-reads frame-exact.

## What's New in v2.78.1

`Timeline.DeleteClips` is page-gated. Contributed by
[@billcarroll](https://github.com/billcarroll) in
[#117](https://github.com/samuelgursky/davinci-resolve-mcp/pull/117).

### Fixed

- **Every delete-capable action failed whenever the UI was left on another page.**
  `Timeline.DeleteClips` deterministically returns False and deletes nothing off
  the Edit page (verified: Fairlight), retries included — the readback-and-retry
  helper from v2.71.1 handles a *flaky* False correctly, but retrying cannot clear
  a page gate. Live verification on Studio 21.0: three identical retries against
  132 valid, unlocked, present items all returned False with all 132 still on the
  track; one `OpenPage("edit")` and the same call returned True and left 0. Track
  lock and enable state were clear throughout — a page gate, not a lock.
  `timeline` `delete_clips` / `move_clips` / `overwrite_range` / `lift_range` /
  `apply_cuts` and `edit_engine execute_swap` now hold the Edit page for the call
  and restore the caller's page after.

The guard is serialized through `page_lock`, alongside the existing Color-page
guard for thumbnail capture: Resolve has one globally-active page, so an
unserialized switch-work-restore races every other page-switching operation, and
under the threaded dispatch from v2.62.0 a concurrent thumbnail capture flipping
to Color mid-delete would land the delete on the wrong page — reintroducing this
same bug. `apply_cuts` holds the guard once around its loop rather than per cut,
which would otherwise cost 2N page flips for N cuts.

The `api_truth` entry is restructured into the two distinct failures now known to
share this call: wrong page (deterministic, mechanism identified, verified) and
flaky first attempt (one observation, cause not established — and the entry now
records that the page state at the time was not captured, so it cannot be ruled in
or out as the first failure in disguise).

## What's New in v2.78.0

The AAF probe reports where in the *source* an event actually lives, not where it
lives in the consolidated fragment the AAF happens to reference.

### Fixed

- **`srcIn`/`srcOut` were handle offsets, not positions in the take.** A
  `SourceClip`'s `start` is an offset into whatever mob it references *directly*,
  and for consolidated media that mob is a per-cut fragment carrying handles — not
  the take. On a real turnover 774 of 878 events reported `srcIn <= 45`, and one
  take used thirteen times reported `srcIn 40` all thirteen times; two cuts of one
  take cannot both begin at frame 42 of it. A consumer placing those numbers
  against camera originals lands on the right cut of the right take showing the
  **wrong moment**, and the number fits inside the file, so no range check catches
  it. The consumer measured 2 of 526 cuts matching its picture reference before
  this.

### Added

- **Physical source position and timecode per event** — `srcPos`, `srcTcFrame`,
  `srcTc`, `srcTcFps`, `srcTcDrop`. The chase sums `start` down the mob chain and
  reads the nearest mob's timecode slot, so a consumer that links camera originals
  can place `sourceTc − fileStartTc` instead of a fragment-relative number. Emitted
  only when actually read: a chain that adds nothing emits nothing rather than
  restating `srcIn`, and per-sequence `sourcePositionCoverage` counters let a
  consumer distinguish "this AAF carries none" from "this probe is too old to emit
  it." `srcIn`/`srcOut` are unchanged — this is additive.

Verified on the fixture: 869/878 events carry `srcPos`, 876 carry source timecode,
and the take used thirteen times separates into thirteen distinct positions.
Frame-exact against an independent witness — at the frame the turnover's own
picture reference burned 21:19:28:21, the probe says 21:19:28:21.

## What's New in v2.77.0

Folder addressing fails loud instead of quietly answering about whichever bin the
UI happens to have open. Contributed by [@billcarroll](https://github.com/billcarroll)
in [#116](https://github.com/samuelgursky/davinci-resolve-mcp/pull/116).

### Fixed

- **An unresolvable folder address no longer falls back to the current bin.**
  `media_pool add_subfolder` and `media_pool get_timeline_mattes` resolved their
  folder argument with `_navigate_folder(...) or fallback`, so a typo'd path was
  dropped and the action proceeded against the current bin (or root) with a
  `success` envelope. For a read that is a wrong answer indistinguishable from a
  right one; for `add_subfolder` it creates the folder wherever the UI happens to
  be pointed. All three sites now share one resolver that returns
  `FOLDER_NOT_FOUND` / `invalid_input` when a supplied address does not resolve,
  with remediation naming `get_subfolders`.
- **A bad folder path came back marked retryable.** The `folder` tool did already
  error on an unresolvable `path`, but with a bare message, so the envelope
  defaulted to `resolve_api_failed` and told the caller to retry an address that
  would never resolve. It is now `invalid_input`, non-retryable — the caller's to
  fix.

### Added

- **`folder_id` is accepted as a folder address**, alongside `path`, on the
  `folder` tool, `media_pool add_subfolder`, and `media_pool get_timeline_mattes`.
  `get_subfolders` hands out ids, and having no way to spend them is what invited
  agents to guess a `folder_id` argument that no action read — which was silently
  dropped, returned the current bin's contents with `success`, and made the tools
  look like they ignored their arguments. Omitting every address still means what
  it did before: the current folder for the `folder` tool, the root folder for the
  two `media_pool` actions.

### Known limitation

Only `path`/`folder_path`/`folderPath` and `folder_id`/`folderId` are recognised
as addresses. Any other invented key (`id`, `bin`, `folderName`) is still dropped,
and the action still answers about its default folder with `success`. This release
narrows the silent-wrong-folder class to a known key set rather than closing it;
closing it needs unknown-parameter rejection at the dispatch layer.

## What's New in v2.76.0

Three AAF conform-fidelity fixes found by placing a full 83-minute Avid turnover and
cross-checking it against Resolve's own native import of the same file.

### Fixed

- **AAF transitions did not subtract from record advancement.** In the AAF Edit
  Protocol a Transition does not occupy record time, it *overlaps* its neighbours:
  `sequence length == sum(components) − sum(transitions)`. The walker annotated the
  clip after a dissolve but never rewound the record position, so **every later event
  on that track was late by the cumulative transition time** — silent, track-local,
  and invisible on any timeline without a dissolve. On a real turnover a single
  59-frame dissolve put 651 subsequent V1 events 59 frames past Resolve's native
  import of the same AAF (probe 566/2586/2652 vs native 507/2527/2593); the fixed
  probe reproduces the native positions exactly. The independent cross-check: each
  layer's walked length used to overshoot its own DECLARED length by exactly that
  layer's transition sum (V1 +59, V6 +77, dissolve-free layers +0) — with the
  subtraction, walked equals declared on every layer. A leading transition clamps at
  the sequence start rather than producing a negative record position.

### Added

- **Sequence start timecode.** `list_sequences` and `parse_interchange` now report
  `startTimecode`, `startFrame`, `startTimecodeFps` and `startTimecodeDrop` per AAF
  sequence. A conform that places events without it builds at Resolve's default
  01:00:00:00 while the AAF starts at 00:59:50:00 — every clip ten seconds out, and
  only visible against a linked picture reference. Avid writes one timecode slot *per
  common rate* (a real turnover carried seven — 86160@24, 89750@25, 107592@30-drop,
  107700@30, 215400@60, all naming the same instant), so the slot matching the
  editorial edit rate is chosen and the rate the frame number is expressed in is always
  reported. An AAF with no timecode slot emits explicit nulls, never a guessed start.
- **Per-clip geometry** — the Avid transform parameters behind Resolve's "Use sizing
  information" import option. Clips wrapped in `PaintResize_v2`, `SpatialAdapter` or
  `FlipHoriz_2` carry a `geometry` list in application order (innermost first: 84 of
  the fixture's clips nest a SpatialAdapter inside a PaintResize, so a single field
  would have dropped a stage). Scale is emitted as a percent — proven, not assumed,
  because 212 of 285 resize groups sit at exactly 100 — and the source/framing
  rectangles yield the unit-free `reformatScaleX/Y` (0.744792 on the fixture: a 2.39:1
  source letterboxed into a 16:9 framing). Parameters whose units the fixture does
  *not* pin down — position, crop, and the absolute rectangle unit — pass through raw
  under Avid's own names rather than being reinterpreted into a normalized field that
  might ship an inversion, the lesson from `SpeedRatio` being stored as the inverse of
  play rate. Animated parameters are named in `varying` and carry no single value.

### Documentation

- `api_truth`: **`TimelineItem.GetSourceStartFrame` reads one frame off on some
  items** while `GetLeftOffset` is exact on the same items — so a conform that
  verifies placement with `GetSourceStartFrame` reports phantom off-by-one drift on
  correctly placed clips, and would hide a real one-frame error just as easily.
  `docs/reference/api-limitations.md` regenerated.
- The two timeline kernels no longer describe AAF as an honest refuse; it has parsed
  via pyaaf2 since v2.73.x.

### Validation

- 2391 Python unit tests, 505 Node advanced tests (40 in the AAF suite, up from 26).
- All release static checks and drift guards green.
- Verified offline against a real 878-event multi-layer Avid picture turnover.
- No Resolve scripting behavior changed — `aaf_probe.py` never touches the Resolve
  API — so no live Resolve validation was required.

## What's New in v2.75.0

The offline AAF reader now recovers retime ratios instead of only flagging them.

### Added

- **Motion Control speed recovery.** OperationGroup parameters are read: a
  constant `SpeedRatio` emits `speedRatio` (play rate) and corrects `speed`, so
  consumers reading only `speed` are no longer told 100 for a 175% clip. Variable
  timewarps (multi-point speed maps) report `speedVarying: true` rather than a
  fabricated number — the reader's honest-refuse contract extends to speeds.
  Note the stored AAF rational is RECORD/SOURCE (Edit Protocol output-over-input),
  the inverse of play rate; the reader emits play rate, verified against the
  length identity (sourceLen = recordLen / |ratio|) and Avid's own speed maps.

### Fixed

- **Motion Control events inflated `recOut`.** Record advancement used the inner
  source clip's length instead of the OperationGroup's declared record length, so
  fast-motion clips claimed more record time than they occupy (and slow motion
  claimed less). On a real 83-minute turnover this produced 40 spurious record
  overlaps; with the declared length driving advancement, one remains — a
  two-input blend genuinely sharing its record span.

## What's New in v2.74.0

### Added

- **`drp-format/set-framerate` — relabel a `.drp` timeline frame rate in place.**
  `setTimelineFrameRate(drpInput, targetFps)` rewrites the timeline
  `<FrameRate>` blob(s) to a new fps while leaving every clip's integer
  Start/Duration/In/Out and every clip-level `<MediaFrameRate>` untouched — a
  relabel, not a retime. Use it to fix a contaminated rate tag (e.g. an export
  step that stamped 23.976 onto a 24.000 timeline whose frames are correct).
  Offline-only by necessity: Resolve locks a timeline's frame rate once the
  timeline exists, so an imported `.drp` can never be relabelled through
  Resolve itself. `readTimelineFrameRates(drpInput)` reports the current
  rate(s) without modifying anything. Both are exported from the `drp-format`
  index; five node:test cases cover relabel, `MediaFrameRate` isolation,
  idempotence, and input validation.

### Fixed

- Corrected a garbled doc comment in `drx-parameters/index.js`.

## What's New in v2.73.2

Two honesty fixes in the conform path, both found by running a real 83-minute
Avid AAF turnover end to end. Neither adds tool surface; `detect_missing_media`
gains two additive response fields.

### Fixed

- **`detect_missing_media` counted an unknown item as a present one.** A timeline
  item with no media pool item has no file path and no offline marker, so it fell
  through to `present` — absence of information reported as presence. An AAF
  imported with `importSourceClips=false` yields 882 such items, and the probe
  answered `present_count: 882, missing_count: 0` while every one of them returned
  `None` from `GetMediaPoolItem()`. The payload contradicted itself: the diagnosis
  already said `unique_media_pool_item_count: 0`.

  Those items now report under `unlinked` / `unlinked_count` and never inflate
  `present_count`. They are deliberately **not** folded into `missing`: those rows
  drive relink plans keyed on `media_pool_item_id`, and there is no pool item here
  to relink. When a timeline is entirely unlinked the diagnosis says so, instead of
  "No offline media detected" — technically true and completely misleading.

- **The "Resolve created no timeline" remediation named the wrong fix.** It advised
  converting the file to FCP7 XML / FCPXML. The far more common cause is that
  `importSourceClips` defaults to `True`, so Resolve tries to pull in the sequence's
  source clips and fails the entire import when those paths do not resolve — the
  normal state of a turnover, whose paths belong to the offline editor.
  `import_source_clips=false` lands the timeline offline and now leads the
  remediation. Note `sourceClipsPath` does not rescue it: Resolve matches source
  clips by the filenames recorded in the sequence, so an AAF referencing Avid MXF
  finds nothing in a folder of differently-named finishing media.

## What's New in v2.73.1

Packaging fix. The npm package shipped the AAF reader's Node half without its
Python half, so offline AAF preview could never have worked from an npm install.

### Fixed

- **`aaf_probe.py` was missing from the published npm package.** The `files`
  allowlist was written in v2.58.0 as `resolve-advanced/server/**/*.mjs`, and
  when `aaf_probe.py` landed in v2.59.0 the allowlist was not extended. `aaf.mjs`
  shipped and shelled out to a file that did not exist on disk, so every
  `parse_interchange` / `list_sequences` call against a `.aaf` failed for
  npm-installed users. Repository clones were unaffected, which is why it
  survived a year of releases unnoticed.

  The failure was at least loud rather than a fake parse — but its remediation
  was actively misleading. The probe exited 2 (`can't open file …aaf_probe.py`),
  which fell through to the generic branch and appended "Install the offline AAF
  reader (`pip install pyaaf2`)". Installing pyaaf2 cannot fix a file that was
  never packaged, so the message sent anyone who hit it down a dead end.

  This means the v2.73.0 multi-layer AAF fix did not reach npm users at all;
  2.73.1 is what actually delivers it.

## What's New in v2.73.0

The offline AAF reader could not read a multi-layer Avid timeline, and said so
in the worst possible way: `ok: true` with an empty event list, indistinguishable
from an empty timeline. Any caller gating on a successful parse would proceed to
conform nothing.

### Fixed

- **AAF: multi-layer timelines returned zero events while reporting success.**
  Avid exports a multi-layer video timeline as a `NestedScope` segment, which the
  offline reader never traversed — `NestedScope` carries `.slots`, not
  `.components`, so the whole timeline fell through the walker's lone-`SourceClip`
  fallback and emitted nothing. Two further drops sat on the same path and had to
  be fixed with it: `OperationGroup.segments` holds a nested `Sequence` rather than
  a direct `SourceClip`, so effect-wrapped clips — the majority of any real
  turnover — were dropped even once `NestedScope` was traversed; and source-name
  resolution stopped one mob hop short of the MasterMob, because Avid routes
  timeline clips through an unnamed intermediate `CompositionMob`, resolving most
  clips to `UNKNOWN`. `Selector` segments are now followed (via the AAF `Selected`
  property — pyaaf2 does not expose it as an attribute), and non-editorial slots
  are skipped by media kind rather than segment class, so `Pulldown`-wrapped
  timecode tracks no longer leak through as editorial.

  Verified against a real 83-minute Avid picture turnover: **0 → 878 events**
  across 5 layers, **0 `UNKNOWN` sources** (779 distinct camera rolls), no
  unhandled component classes, ~1.5 s.

### Added

- AAF probe and `listAafSequences` now report an `unhandled` map (component class
  → count) per sequence. A structural miss is visible instead of masquerading as
  an empty timeline.

### Known limitations, stated deliberately

- **Motion Control retimes are flagged, not quantified.** They carry
  `effect: "Motion Control"` with `speed: 100`, because the ratio is not
  recoverable offline. A consumer reading `speed` alone will treat them as full
  speed. Pre-existing behaviour, preserved on purpose — flag over fabricate.
- **Effect-only layers correctly produce no events.** Layers that wrap
  `ScopeReference` (subtitle burns, blends, mattes) apply to what shows through
  from below and reference no media of their own. OTIO reports such layers as
  tracks of gaps, so its track count can exceed the number of layers with media;
  "6 layers" is not "6 layers with media". Events were not fabricated to make the
  counts match.
- **Only `NestedScope` layers are numbered `V1..Vn`.** Non-nested slots keep the
  flat `V`/`A` label, a deliberate scope limit that keeps the blast radius off
  simple AAFs — notably `editorial.mjs`'s `track === 'A'` audio-follows-video
  heuristic, which reads that label.

## What's New in v2.72.1

Documentation only. The API coverage page stated its method counts in four
places and they disagreed; the cause turned out to be structural rather than
clerical.

### The Resolve 21 surface was never counted

None of the Resolve 21 methods appeared in the Complete API Reference tables —
the tables the `API Methods Covered` denominator counts — although the server
has wrapped, released and live-tested them since v2.28.1. So `337/337 (100%)`
described a surface that excluded nine methods across four classes, and the
`336 → 337` bump for `ResetIntellisearchAnalysis` added one to a count whose
table did not list it.

Thirteen rows added, one per method per object class, since a wrapper on
`Folder` and one on `MediaPoolItem` can fail independently. Signatures taken
from the bundled 21.0.2 scripting reference. `TranscribeAudio` was already
listed — its Resolve 21 change is the optional `useSpeakerDetection` argument,
accepted but producing identical transcripts either way — so those rows are
annotated rather than duplicated.

Every summary figure is now derived from the tables: **349 covered, 338 live
tested, 11 untested**.

### The counting convention is now written down

Two of the three disagreements came from it being implicit:

- A method that could not be executed is **not** counted as a pass. The old
  "Resolve 21 delta 8/9" counted Extras-blocked methods as passes, contradicting
  the prose directly above it and overstating coverage exactly where the risk is
  highest.
- The phase table counts **methods, not assertions**, which is why its Total
  equals Methods Live Tested. That ambiguity is what made two figures look
  independently wrong.

`tests/test_api_coverage_arithmetic.py` derives all four figures from the
reference tables and fails if any disagrees, so the tables stay the single
source. It was checked against both drift shapes: a hand-edited summary figure,
and a row removed from a table.

## What's New in v2.72.0

Resolve 21's AI methods report a missing Extras pack as an error *string*, not
the documented bool — and a non-empty string is truthy. Live-validated against
Studio 21.0.2.4 by @AghisSs in #107.

### The trap

The methods do not agree on how they refuse. With only AI Motion Deblur
installed:

| Method | Return when the pack is absent |
|---|---|
| `AnalyzeForSlate` | `False` |
| `AnalyzeForIntellisearch` | `"Required package 'AI Intellisearch - Faster' is not installed."` |
| `GenerateSpeech` | `"Required Package, 'AI Speech Generator' is not Installed."` |

So `bool(result)` reported **success for analysis that never ran** across eight
call sites, and `generate_speech` let the string past its guard into
`.GetName()`, raising `AttributeError: 'str' object has no attribute 'GetName'`.

`_ai_result` / `_ai_result_payload` now treat any string as a failure and
surface its text as the error. That message is the only machine-readable signal
that a pack is missing, since nothing in the scripting API enumerates installed
Extras.

`remove_motion_blur` is routed through the same helper. It needs the AI Motion
Deblur Extra like its siblings and reproduced *both* failures — the
`AttributeError` on the clip path, and a silent `success: true` with
`created: []` in the confirm-gated folder path that renders new media. Both were
live-tested with the Extra installed, so the absent-pack return was never
observable.

### Also

- `project_settings("reset_intellisearch_analysis")` — documented in the 21.0.2
  scripting README and present in `dir(project)`, but absent from the copy the
  repo bundled, so it was never wrapped.
- A live validation harness for the Resolve 21 delta, source-safe: synthetic
  media in a temp dir, disposable project, teardown that restores the
  originally-open project.
- `api_truth` entries for the string-return bug, the undiscoverable Extras gap,
  and `AnalyzeForSlate`'s documented `resolve.MARKER_*` constants, which do not
  exist on the handle at all.
- The `hasattr` attribute-fabrication entry is scoped as **unresolved**. The
  21.0.2.4 control probe used an invented name, while the 21.0.0 evidence it
  overturns used real method names borrowed from other object types — so it does
  not refute the original record. `_has_method` is what every `_requires_method`
  version gate is built on, and a gate that silently passes is the failure this
  ledger exists to prevent.

## What's New in v2.71.1

`Timeline.DeleteClips` can lie about whether it worked. #111 recorded four
behaviours from a live edit session; #114 mitigates the first of them. Both by
@billcarroll.

### DeleteClips readback-and-retry

`Timeline.DeleteClips` can return `False` on a first call even when every item
passed is a valid, present `TimelineItem`, with an identical retry succeeding.
`_timeline_delete_clips_verified` reads the tracks back on a `False` and retries
once if the items are still there. All four timeline call sites route through
it: the `delete_clips` action, `lift_range`, `duplicate_clips` and `copy_range`.

The readback is deliberately **tri-state**. A walk that raised, enumerated no
track at all, or covered items whose unique ID cannot be read is `unknown`, not
`absent` — so an unverifiable delete is never reported as success, and never
spends a second destructive call buying information it cannot read. An earlier
draft collapsed unknown into absent, which turned a failed delete into a
reported success; that is the exact silent-lie class this series exists to
remove, so it is worth naming.

The `ripple=True` non-idempotence of a retry is recorded in the docstring rather
than claimed to be solved: if the first call deleted some items and left others,
the retry passes the original list back in, stale handles included. It could not
be made to misbehave against a fake.

### Four edit-session behaviours recorded

- **`DeleteClips` flaky first attempt.** The entry states plainly that the cause
  is **unknown**, and specifically that this is *not* the
  `ProjectManager.DeleteProject` shape — that one has an identified mechanism
  which retrying does not clear, whereas a single retry cleared this in the one
  instance seen. One observation is not a mechanism.
- **`DeleteClips` leaves linked audio.** The API deletes exactly the items
  passed; the UI's linked-selection behaviour does not apply, so orphaned audio
  collides with later appends.
- **`AppendToTimeline` mixed-fps duration floor.** Source-to-timeline frame
  conversion rounds down, landing a planned range one frame short.
- **`ImportMedia` current-folder only.** No destination parameter; imports land
  in the current bin.

## What's New in v2.71.0

Keyed metadata getters honor a list of keys, and `delete_timelines` names the
parameter it wants. Reported and fixed by @billcarroll in #113, from live
cataloguing work.

### Keyed getters silently returned everything

Resolve's keyed getters take one string. Handed a list they ignore it and return
the full dict, so a caller asking for three fields silently received all of them
with no signal that the request had been dropped — the kind of thing that reads
as working until someone counts.

`get_metadata`, `get_third_party_metadata` and `get_clip_property` now share a
`_keyed_get` helper that subsets locally, since there is no batch getter to
delegate to. An empty or non-string list is a clear error rather than a silent
superset.

Missing keys deliberately report differently through the two forms: the list
form maps them to `null`, which separates "absent" from "present but empty"; the
string form still returns Resolve's `""`. All three actions document both the
list form and that divergence.

### `delete_timelines` leaked a KeyError

Called with `timeline_names`, or without `timeline_ids` at all, it raised a bare
`KeyError('timeline_ids')`. It now returns a proper error naming the expected
parameter, and when `timeline_names` was passed it says explicitly that
timelines are matched by unique ID rather than by name.

## What's New in v2.70.4

Three silent-failure fixes from community reports, plus the Windows bridge
follow-ups from #112's live confirmation.

### Thumbnails silently failed off the Color page (#110, @billcarroll)

`Timeline.GetCurrentClipThumbnailImage` returns data only while Resolve is on
the Color page — Blackmagic's own reference documents it as returning data "for
current media in the Color Page". `thumbnail_contact_sheet` (and
`marker_thumbnail_review`, which routes through it) reported "No thumbnail
available at frame" for every sample from any other page, which reads as an
empty timeline rather than a page requirement.

A shared `color_page_for_thumbnails` context manager in `page_lock.py` switches
under the existing page lock and restores the previous page after. The granular
server's thumbnail tool shares it and gained a real error message in place of a
bare `{"success": false}`. Where the current page cannot be read, no switch is
attempted at all, so a skipped restore can never strand the user on Color.

### probe_media_pool truncated silently, and good script runs reported failure (#108, @billcarroll)

`_folder_probe` reported `subfolder_count` from the list it had *expanded*, so
at the default depth every unexpanded folder looked like an empty leaf. In the
field, a drive-rename relink sweep trusted `subfolder_count: 0` and skipped
about 40 populated bins and 573 clips. The count is now the real
`GetSubFolderList()` length at every level, and folders carry `truncated: true`
at the cutoff so a walker can descend.

Separately, `fusionscript`'s RemoteApp thread can SIGSEGV during interpreter
teardown *after* a spawned script has finished its work, turning exit 0 into
-11 and a successful run into `success: false`. Scripts now run via `runpy` and
hard-exit before teardown. The guard catches `SystemExit`, so a script ending in
`sys.exit(0)` cannot reopen the race, and repoints `sys.path[0]` at the script's
directory — under `-c` it points at the server's cwd, which would break sibling
imports and let stray files shadow real modules. The cost of `os._exit` (atexit
handlers skipped, non-daemon threads not joined) is documented on the action.

### Bridge: a dead listener no longer reads as a live one (#112)

`serve()` treated "the serve thread is alive" as "the bridge is serving".
`serve_forever()` keeps its thread alive, so that is a narrower question than it
appears, and a bridge was reported lingering with nothing on its port while the
serve loop kept polling. That divergence is not explained here, but a process
running with no listener is useless either way, so the exit condition now asks
the socket directly.

The Win32 prototypes are declared rather than relying on ctypes' default
int-sized handle. The default is safe by documented contract, but the reporter
had to derive that from Microsoft's interop documentation to rule out
truncation; declaring the signatures spares the next reader the exercise.

**The v2.70.3 Windows fix is now confirmed on real hardware.** ZontarLives ran a
same-machine control: on v2.70.2 the bridge outlived Resolve indefinitely; on
v2.70.3 it exits 0.23s after. `_process_is_alive` returned `None` for pid 4
(System), confirming that access-denied reads as unknown rather than death
against a genuinely protected process.

## What's New in v2.70.3

The free-edition bridge could never notice Resolve exiting on Windows, so it
orphaned itself and blocked the next session. Reported in issue #112 by
@ZontarLives, with a self-contained repro.

### The bug

`serve()` detected host exit with a single test:

```python
if os.getppid() != expected_parent:
    break
```

That is a POSIX signal. When a parent dies, POSIX reparents the orphan to init
and the value changes. **Windows does not reparent** — the parent pid is a
static field in the process record, so `os.getppid()` returns the dead parent's
pid forever and the check can never fire.

The consequence is not a cosmetic leak. The orphaned `fuscript.exe` keeps port
49632 and keeps accepting connections while holding a dead `resolve` handle, so
the next Resolve session's bridge cannot bind, and the client sees:

```
bridge_timeout: Resolve did not answer in time - check for an open modal dialog,
which blocks its scripting API entirely
```

against a socket that `Get-NetTCPConnection` reports as healthily `LISTENING`.
Every surface-level check passes and the suggested cause is a red herring, which
is what made it expensive to diagnose.

### The fix

Liveness is now asked directly instead of inferred from a pid changing:

- `parent_has_exited()` keeps the reparent test as the fast path where it works,
  then checks whether the parent pid still resolves to a live process, then
  whether that process still name-matches `PARENT_MARKERS`. The last step also
  catches pid reuse, which the old check would have misread as "Resolve exited".
- On Windows liveness comes from `OpenProcess` + `WaitForSingleObject` via
  `ctypes`. Only "no such process" counts as death: access-denied and every
  other error are *unknown*, and unknown never ends the session — the module's
  standing rule is that a bridge which exits early is worse than one that
  lingers.
- `_process_name()` gained a Windows branch (`QueryFullProcessImageNameW`). It
  previously tried `/proc` then `ps`, so it returned an empty string on every
  Windows machine. `scripts/resolve_bridge_probe.py` gets the same treatment.

Binding failures now name the likely cause and the way out, rather than
surfacing a bare "address already in use" that sends people to check firewalls.

The Windows branch is injectable so it is tested off Windows — a constant
`getppid` plus a simulated liveness answer. The platform difference is precisely
what kept this invisible to everyone developing on macOS or Linux.

### Also confirmed

`%APPDATA%` now joins `%PROGRAMDATA%` as a verified Windows bridge location; the
#112 report served reads from it against free 21.0.3.7. README and `docs/SKILL.md`
updated, along with guidance that a bridge which stops answering while
`LISTENING` is a stale process rather than a modal dialog.

### Also in this release

Two offline guard tests built their "not a temp path" target from `os.getcwd()`,
which failed — and wrote a real `look.cube` into the working directory — whenever
the suite ran from a directory under `/tmp`. `tests/_paths.py` makes them
independent of where the suite runs.

## What's New in v2.70.2

The control panel could never reach the free edition, even with a perfectly
healthy in-app bridge. Reported in issue #109 by @alpaolo.

### The bug

The panel runs as a separate process from the MCP server and has its own Resolve
connector. That connector returned as soon as `import DaVinciResolveScript`
failed:

```python
try:
    import DaVinciResolveScript as dvr_script
except Exception as exc:
    return None, f"Resolve scripting API unavailable: {exc}"
```

On the free edition that import is exactly what fails — Blackmagic's module ships
with the installer, not the App Store build, so there is no
`Developer/Scripting/Modules` tree to import from. The panel returned there,
before ever calling `connect_resolve`, whose entire purpose is that it accepts
`None` in bridge mode:

> `dvr_script` may be None in bridge mode: the bridge does not need Blackmagic's
> module at all, which is precisely why it reaches editions the module cannot.

So the reporter saw the bridge listening, the MCP server connected, and the panel
insisting "Resolve unavailable" — all at the same time, all correct.

`_try_connect` in `src/server.py` already carried this guard, with a comment
recording the same diagnosis from when it bit the server. The panel's connector
was missed. That makes it the third connector overlooked when a transport was
added, after the network-scripting one in v2.64.0.

### The fix

The panel now consults the bridge first and treats both the environment setup and
the module import as optional when it is enabled — the same ordering the MCP
server uses.

The not-connected message no longer assumes Studio. It used to send every reader
to "open Resolve Studio with a project loaded", which is poor advice for a
free-edition user, since free is the one edition external scripting refuses by
design. It now names the fix that fits the situation, and says something
different depending on whether the bridge is enabled.

### Windows bridge: `%PROGRAMDATA%` now confirmed

v2.70.1 shipped Windows script paths unverified. The #109 report was made on free
21.0.1.11 with the bridge installed, listed and serving from `%PROGRAMDATA%`, so
that half is now confirmed rather than assumed. `%APPDATA%` remains untested.

## What's New in v2.70.1

Windows support for the free-edition in-app bridge, and the end of doctor.py's
macOS-only path assumptions. Reported in issue #106 by @kacemmosbah8-afk.

### The bug

`script_targets()` in `scripts/install_resolve_bridge.py` enumerated macOS and
Linux candidates only. There was no Windows branch at all, so the candidate list
came back empty on every Windows machine and the installer exited with:

```
No writable DaVinci Resolve Scripts/Utility folder found. Is Resolve installed?
```

on installs where Resolve was demonstrably present. Since the in-app bridge is
the *only* route to the free edition — external scripting is Studio-gated by
Blackmagic — Windows free-edition users had no working path to this server at
all. The bridge shipped in v2.68.0; it has been macOS/Linux-only that whole time.

Windows now targets the two Scripts/Utility trees Blackmagic documents, per-user
first because `%PROGRAMDATA%` typically needs an elevated prompt:

- `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility`
- `%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Utility`

Three traps came out of implementing that, each now pinned by a test:

- **The per-user tree carries a `Support` segment the all-users tree does not.**
  They are not one layout under two roots; deriving either from the other lands
  in a folder Resolve never scans.
- **Blackmagic's own README writes the per-user root as `%APPDATA%\Roaming\...`,
  which is wrong** — `%APPDATA%` already *is* `...\AppData\Roaming`. Transcribing
  it verbatim yields `AppData\Roaming\Roaming\...`: a real, creatable folder that
  is silently never read.
- **Resolve does not create its `Fusion\Scripts` tree until a script is
  installed**, so gating on that tree existing — or on its parent being writable
  — skips a fresh free-edition install, the exact build the bridge exists for.
  The candidates are gated on Resolve's product folder instead, mirroring how the
  macOS sandbox container is handled.

`install()` no longer aborts when one target is unwritable. The `%PROGRAMDATA%`
tree needs elevation, and Windows `os.access(W_OK)` reports the read-only flag
rather than the ACL, so it cannot be screened out in advance — without this, the
newly added candidate would have crashed the installer on every non-elevated
Windows account *after* it had already succeeded into the per-user tree. Skips
are reported in `warnings`; only a clean sweep is fatal, and that error now names
the folders and the reason instead of asking whether Resolve is installed.

### The macOS framework-Python alarm was firing off macOS

`python_preflight()` looked for a framework Python under `/Library/Frameworks`,
a path that cannot exist on Windows or Linux — so it always found nothing and
emitted the macOS remediation, telling the reporter (running a working python.org
3.12.9) to install the Python they already had. Linux had the same false alarm.
The check is now macOS-only. The Lua canary still ships everywhere, so a genuine
enumeration failure stays diagnosable.

### doctor.py was macOS-only too

`scripts/doctor.py` hardcoded macOS defaults for `RESOLVE_APP`,
`RESOLVE_SCRIPT_API` and `RESOLVE_SCRIPT_LIB`. Run standalone — that is, without
the environment variables the npm/`install.py` flow injects — it reported four
`[FAIL]` lines naming a `.app` bundle and `fusionscript.so` on a Windows 11
machine that had neither, while `install.py` detected that same install
correctly. Two tables describing one thing, one of them platform-blind. Linux was
equally affected.

doctor now selects per-platform candidates, and picks the first that exists so
the reported path matches reality. macOS values are byte-identical to before.
A new `tests/test_doctor_paths.py` drift guard asserts every path doctor names
also appears in `install.py`'s `RESOLVE_PATHS`, so the two cannot diverge again.
Claude Desktop's config path is now MSIX-aware on Windows as well, matching the
issue #93 fix that `install.py` already had.

### Scope — what is and is not verified

The path construction is unit-tested, and a simulated Windows run exercises the
installer end to end. **No Windows hardware has confirmed that Resolve actually
lists the bridge from these folders.** The reporter verified the folders exist
and are writable; issue #104 is precedent that "the folder exists" and "Resolve
reads it" are different claims. The README and `docs/SKILL.md` say so plainly
rather than implying Windows is a supported, tested tier.

Suite: 2312 → 2336.

## What's New in v2.70.0

Headless (`-nogui`) Resolve, measured rather than assumed — and the finding
reverses this project's working belief about it.

### The measurement

A GUI run and a `-nogui` run of the same Resolve Studio 19.1.3.7 were probed
identically and differenced: 139 read-only API probes plus 13 write scenarios
covering pages, media pool, timeline editing, colour, Fusion comps, Gallery,
render-to-disk, interchange export, layout presets, playhead and project
settings. 238 paired observations.

**Zero capabilities worked with a UI and failed without one.** Render to disk,
AAF/EDL/FCPXML/DRT/OTIO export, `ExportCurrentFrameAsStill`, `GrabStill`, Fusion
comp create/delete, colour groups, and even UI layout presets all behave
identically headless.

**Scope, stated up front:** that is a result about *capability* and about
modals. It is **not** a stability result. The probe's render was 2 seconds of
640×360 H.264; long renders, JPEG 2000 decode out of DCP MXF, ProRes-into-MXF
writes and repeated jobs in one session are all untested, and there is a field
report of headless crashing *on completion of writes* for exactly that class of
job. The docs and the runtime guidance say so rather than letting the matrix
be read as a blanket endorsement.

The one difference actually found runs the other way, and it is the one an agent
cares about: **a GUI Resolve can raise a modal dialog no script can dismiss;
headless cannot.** The trigger is project switching, and the obvious defence fails —
`ProjectManager.SaveProject()` returns `False` for the default never-saved
`Untitled Project`, which is exactly the project that raises the prompt.
Headless returns the same `False` and switches anyway.

Two earlier notes are corrected: `ExportCurrentFrameAsStill` was recorded as a
headless-only failure and works headless; `ExportStills` was recorded the same
way and fails in *both* modes (its documented cause is Gallery panel visibility,
which no headless session and no panel-closed GUI session can satisfy).

### Fixed

- **`timeline(action="get_items_in_track")` returned object reprs, not items.**
  The handler passed `GetItemListInTrack`'s result to `_ser`, which has no
  TimelineItem branch and falls through to `str(obj)`, so callers got
  `["<PyRemoteObject at 0x…>", …]` instead of clip data. The docstring's claim of
  "full serialization of each item" was never true. The sibling `get_items`
  takes the same params through the same `_track_selector` and calls the same API
  method, so the two are now one handler and `get_items_in_track` is documented
  as its alias — there was no richer per-item serializer to preserve. Thanks
  [@billcarroll](https://github.com/billcarroll) (#105).

### Added

- `resolve_control(action="runtime_mode")` — is Resolve up, and does it have a
  UI? Answers with no connection needed, and carries the mode-specific guidance
  with it. **There is no API tell**: a headless instance returns a real page from
  `GetCurrentPage()` and identical product/version strings, so this reads the
  process argv, which is the only place `-nogui` appears. `headless` is `null`
  when undeterminable — never read that as `false`.
- `resolve_control(action="launch", params={"headless": true})`, plus
  `DAVINCI_RESOLVE_HEADLESS=1` to make auto-launch headless. Launching the other
  mode while an instance is running returns `RESOLVE_MODE_CONFLICT` instead of
  starting a second one that would fight the singleton.
- `src/utils/resolve_runtime.py` — mode detection and launch-command
  construction. Headless launch runs the binary inside the app bundle, because
  `open -a` hands the argument list to LaunchServices, which discards `-nogui`
  and gives you a window with no error.
- `scripts/resolve_headless.py` — batch/CI entry point: `status`, `guard`,
  `start`, `stop`, and `run -- <cmd>` which only stops what it started.
- `scripts/headless_differential.py` + `src/utils/headless_differential.py` —
  the harness that produced the above, rerunnable after a Resolve upgrade.
- `docs/reference/headless-cli.md` — verified flags, environment variables,
  launch/teardown recipes, singleton rules, and the flags found in the
  application binary but deliberately *not* exercised.
- `docs/reference/headless-capability-matrix.md` — the generated differential.
- Three `api_truth` entries: the `SaveProject`/modal trap, the absence of any
  headless API tell, and the corrected `ExportStills` reality.

### Validation

- Offline suite 2280 → 2305 (`tests/test_headless_runtime.py`, 25 tests).
- Live: full differential recorded in both modes on Resolve Studio 19.1.3.7,
  scratch project created and deleted per run, GUI session restored afterwards.
  Measured teardown 2.1s via `Quit()`, headless boot to scriptable under 3s,
  scripting listener on TCP 15000 in both modes.

## What's New in v2.69.3

Ships the v2.69.2 bundle, which never reached npm. Same fixes, plus the one that
stopped it publishing.

### Fixed

- **The offline guard failed the publish workflow instead of guarding it.**
  `tests/__init__.py` installs the guard before any test module loads, and the
  guard imports `src.server` — which imports `anyio`. The publish workflow
  installs only pyflakes, by design: the static drift guards are pure AST
  readers that deliberately run without the runtime stack. So every module
  argument raised at import, six of them turned into six `_FailedTest` errors,
  and the npm publish failed with what looked like six broken guards rather than
  one missing package.

  This shipped in v2.69.1's tail (the guard moved under `unittest` after that
  tag was cut), so v2.69.2 was the first release to run it and the first to fail.

  A missing third-party package now skips the swap: if `src.server` cannot be
  imported there is no live-Resolve entry point to neuter, so the guard is
  vacuously satisfied. The skip is narrow on purpose — a `ModuleNotFoundError`
  naming something under `src/`, or any non-import error, still propagates.
  Swallowing those would leave the static guards silently vacuous, which is a
  worse failure than the one being fixed since it fails open.

### Added

- `tests/test_offline_guard.py` — five tests, including the two that matter:
  a broken import inside `src/` must still raise, and a non-import error must
  never be swallowed. A skip that fails open would be indistinguishable from a
  passing suite.

### Validation

- Offline suite 2247 → 2252. Reproduced the CI failure locally against an
  interpreter without `anyio` (six errors before, clean after), rather than
  inferring it from the workflow log.

## What's New in v2.69.2

Community bug-fix bundle: #100, #101 and #102, plus the installer half of #104.
The headline is that a fresh clone had stopped working entirely.

### Fixed

- **A fresh install produced a server that could not start** (issue #103, PR
  #101 by @Mastaish). `install.py` installed `mcp[cli]` with no upper bound, and
  the MCP Python SDK published 2.0.0 — which restructured the package and
  dropped `mcp.server.fastmcp`, the module `src/server.py` imports. Every clone
  after that release died at import, surfacing to the user as nothing more
  informative than "Server disconnected".

  The contributed fix caps the SDK in `requirements.txt`, which `install.py`
  installs second. That works, but the unpinned first call still downloads 2.x
  and its `httpx2` tree before downgrading it, and the fix evaporates silently
  if the install order ever changes — so the cap is now on the `pip install`
  call as well. `McpSdkPinTest` guards both sites, reading the actual string
  literals rather than matching text: `install.py` discusses `mcp[cli]` in prose
  too, and a first cut of that guard was satisfied by a comment. It is
  conditional on `server.py` still importing `mcp.server.fastmcp`, so it retires
  itself when the server is ported to the 2.x layout instead of blocking it.

- **The Advanced (Node) suite was not running at all on Node 20+** (PR #102 by
  @double2tea). `node --test` resolves a bare directory argument as a module
  entry point on Node 20 and later, so the suite exited with `MODULE_NOT_FOUND`
  at 4 failures and 0 passes — a shape that reads more like a broken checkout
  than 731 skipped tests. Explicit test-file globs restore the full run on 18,
  20 and 22 alike.

- **`RESOLVE_SCRIPT_API` / `RESOLVE_SCRIPT_LIB` were silently overwritten** (PR
  #100 by @abbc400). `get_resolve_paths()` returned only platform defaults, and
  `src/server.py` writes those straight back into `os.environ` — so a client
  that had correctly pointed at a Resolve installed outside `/Applications` had
  its setting discarded at import. Every other signal looked healthy (Resolve
  running, external scripting Local, `fuscript` listening) while `scriptapp()`
  returned `None`. The override now wins, but only when the path exists, so a
  stale variable cannot shadow a working default install.

- **The bridge installer wrote to a tree Resolve did not read** (issue #104,
  reported by @RananjayRaj). Which script tree the free App Store build scans is
  not decidable from outside Resolve: this installer was measured on a machine
  where the documented Blackmagic Design tree listed, and #104 reports the exact
  opposite on the same 21.0.3.7 build — the documented tree listed nothing, not
  even the Lua canary (which rules out the framework-Python explanation and
  points at the folder), while the Fusion standalone tree listed everything with
  no restart.

  Rather than pick a winner from two contradictory measurements, both container
  trees now receive the files, documented path first. This stays inside the
  sandbox: outside a container that path really is Fusion's own tree and is
  still not targeted.

- **`--probe-only` reported success on a machine with no Resolve installed**
  (also #104). A container outlives the app that created it, and the container's
  existence is precisely what makes the installer target it — so a stale
  container from an uninstalled Resolve produced a clean success listing files
  that had genuinely been written and would never be read. The installer now
  warns when no app bundle can be found, honoring `RESOLVE_APP` as
  `scripts/doctor.py` already does. It warns rather than refuses: not every
  legitimate install location can be enumerated, and refusing wrongly would
  block a working install.

### Validation

- Offline suite 2237 → 2247 (six new installer-target tests, one pin guard).
  Advanced Node suite 731 tests / 701 pass on Node 18.
- The new guards were verified to fail against the pre-fix code, not merely to
  pass against the fix.
- No DaVinci Resolve scripting behavior changed; the path-resolution change is
  env-var-gated with defaults unchanged. Live Resolve validation not required.

## What's New in v2.69.1

Bug fix. The Studio bridge differential no longer reports the Deliver page its
own render probes navigated to as a transport difference.

### Fixed

- **A clean bridge produced a red result on any run that did not start on
  Deliver.** Run live on Studio 19.1.3.7, the differential reported
  `resolve.GetCurrentPage` as a `value_mismatch` — bridge `edit`, native
  `deliver` — and it reproduced on command: start on Edit, one difference; start
  on Deliver, none. The transport was never involved. The harness's own render
  probes navigate Resolve to the Deliver page, and the bridge pass runs before
  the native pass, so the native pass read a page the bridge pass had moved. Read
  at the same instant the two transports always agreed.

  Adding the method to `VOLATILE_METHODS` would have turned red green and thrown
  away the signal — a bridge that genuinely reports the wrong page is exactly
  what this harness exists to catch. Instead each pass now records the page on
  the way in and on the way out, and the value is compared **only when both
  passes prove it held still**. If both were stable and the values still
  disagree, that is the transport, and it is reported as before. A page that
  cannot be read counts as unknown rather than stable, so an unreadable page
  disables the comparison instead of quietly restoring the false positive.

  `page_compared_by_value` and both passes' before/after values now ride in the
  report either way. "The page was not compared" is a fact about the run, and
  burying it would recreate the silence this fixes.

### Added

- `tests/test_bridge_differential.py` — the module's first tests, 13 of them,
  including the one that matters: a stable page that genuinely disagrees must
  still be reported, or the fix is a mute button rather than a fix. The absence
  of any coverage here is why the false positive shipped.

### Validation

- Static checks and the full unit suite: 2243 → 2256 tests, pyflakes clean.
- Live Resolve validation on Studio 19.1.3.7 after the fix: 142 probes, 0
  differences, 110/112 read methods, started from the Edit page that previously
  failed.

## What's New in v2.69.0

The free edition is documented as reachable, silence ripple stops clipping
speech at the cut, and the editorial surface grows a set of review-first
planners: dead-space markers, craft-aware cut points, conform QC, colour
pre-balance, beat detection, turnover manifests, and a project journal.

Two themes run through the additions. **Nothing new executes** — every planner
proposes and reports, and the existing plan → confirm → execute path is
unchanged. And **unverified is never reported as clean**: an item that could not
be analysed, a check that could not run, a handle that could not be measured and
a take with no transcript are each reported as such rather than folded into a
passing result.

### Changed

- **`plan_silence_ripple` guard bands are now 2 pre-head / 4 post-tail frames**
  (previously 0 and 1 — effectively none). This changes default output for any
  caller that does not pass explicit handles.

  The old defaults cut exactly on `silencedetect`'s gate crossings, which are not
  word boundaries. `s` is marked when amplitude falls below the gate, but a
  word's decay and the room reverb after it stay audible below it, so cutting
  from `s` clipped the release. `e` is marked when amplitude rises back above the
  gate, and a soft attack (s, f, th, or any unstressed syllable) crosses later
  than the word actually begins, so `e` sat *inside* the next word and cutting up
  to it ate the onset.

  The onset guard is the larger of the two because that is the asymmetry users
  hear: reviewers of the first public tutorial for this project independently
  reported that "the first split seconds of your clips are trimmed so the audio
  is a bit cut off". At 24 fps the new guards are 83 ms and 167 ms; at 30 fps,
  67 ms and 133 ms — both inside the range dialogue editors use by hand.

  Pass `pre_head_frames` / `post_tail_frames` explicitly to restore the previous
  behaviour.

### Fixed

- **The docs told free-edition users the door was closed.** v2.68.0 shipped the
  in-app bridge, which reaches the free edition through the ungated
  **Workspace > Scripts** menu, but README's Requirements section still said "the
  free edition does not support external scripting" 195 lines below the section
  documenting the bridge, and `docs/install.md` said the same with no mention of
  the bridge at all. The claim is true about *external* scripting and false as
  users read it — the first large public tutorial for this project pinned a
  correction telling viewers the method "REQUIRES the Studio Version".

  README, `docs/install.md`, `install.py` and the MCP server's own `instructions`
  now state the limit and the remedy together. `install.py` also grew the branch
  it was missing: Resolve running, healthy interpreter, no connection is the
  free-edition signature, and it used to print "Not running — start Resolve".

### Added

**Editorial**

- `edit_engine.plan_dead_space_markers` — **the review gate.** Finds dead space
  with the same calibrated detection as `plan_silence_ripple`, but proposes
  Resolve markers instead of assembling a variant, so an editor can see every
  gap before agreeing to lose it. Red = confident; yellow = the gate only just
  cleared its separation floor. Items that could not be analysed are reported
  and are explicitly **not** certified clean.
- `tightness` (`generous` default | `balanced` | `tight`) on the dead-space
  planner. The default is deliberately the loosest: a first assembly is meant to
  run long, because trimming is fast and visible while recovering material the
  machine discarded is slow and invisible. Guard bands are floored regardless of
  preset — `tight` removes more *gaps*, never more *speech*.
- Syntactic pause classification in `plan_transcript_tighten`. A pause after a
  full stop must be markedly longer before it is proposed for removal than the
  acoustically identical pause mid-phrase; the first is usually breathing room
  and the second usually is not. Unpunctuated transcripts are flagged low
  confidence rather than treated as all-removable.
- `edit_engine.rank_takes` — ranks takes on **measurable fluency** (fillers,
  restarts, script coverage) and states in every response that fluency is not
  quality. It never names a best take.
- `edit_engine.plan_beat_cuts` — beat, bar and phrase cut points for
  music-driven cutting, frame-snapped. Requires the optional `librosa` extra and
  honest-refuses without it.
- `edit_engine.plan_string_out` / `propose_structure` — assembly for footage
  with no speech, from shots and motion rather than silence; and a no-script
  mode that proposes a structure and requires approval.
- `edit_engine.plan_broll` — places B-roll against A-roll beats. Placement only:
  relevance is the caller's and is never re-scored, protected beats are never
  covered, and an explicit beat choice is honoured or refused, never moved.
- `edit_engine.rule_of_six_audit` and `split_edit_audit` — audits against the
  classical weighted cut criteria, and J/L-cut classification. The audit is
  explicit that the two heaviest criteria are not measurable and reports its own
  coverage; there is deliberately no composite score.

**Finishing and colour**

- `edit_engine.conform_lint` — the online editor's pre-turnover checklist:
  frame-rate mismatch, offline media, duplicate source timecode, buried layers,
  fragile effects, missing reel names, duplicate usage. Checks that could not run
  are listed in `not_checked`.
- `edit_engine.plan_prebalance` and `plan_reference_match` — neutral technical
  pre-balance, and matching to a graded reference still. Curves, vignettes,
  saturation, qualifiers and windows are refused **in code**; midtones are left
  warm by design. Reference matching is end-points-only and says so.
- `edit_engine.plan_turnover` — sound / VFX / colour turnover manifests with
  per-destination handle floors and a timecode-burned picture reference required
  in all three. Manifests, not exports.
- Plans now carry a `handle_report`: keep ranges that leave too little source
  media at a join for a dissolve, a slip or an audio crossfade.

**Reporting**

- `edit_engine.plan_report` and `include_report` on every audit — Markdown
  renderings covering what would change (in timecode, with a reason per cut),
  what was deliberately left alone, what could not be verified, and what needs a
  human. Off by default for token cost; every audit advertises it.
- `journal` — ingest log, append-only known issues, session-prep summary with
  value figures, technical handoff document, status summary, and a picture-lock
  fingerprint with drift detection.
- `first_impression` — timestamped capture of a first viewing, sealed once
  locked. There is deliberately no unlock.

**Documentation**

- **Optional extras are now documented up front** — README and `docs/install.md`
  list what each extra unlocks and under which licence, and `scripts/doctor.py`
  reports which are present. Four of the features added in this release need
  `numpy` or `librosa`; they refuse honestly with the install line, but a user
  reading the README previously had no way to know before hitting the refusal.
  "Setup too hard" was one of the loudest complaints this release answers, and
  shipping features behind an undocumented `pip install` is the same failure.

**Guards**

- `tests/test_free_edition_docs_drift.py` — a guard that does not forbid stating
  the free-edition limitation, but requires that any file stating it also names
  the bridge. Broad enough to catch a new phrasing rather than only the sentences
  fixed here, and it asserts the remedy exists (the README anchor and the
  installer script the docs promise).
- `tests/test_attribution_drift.py` — keeps named third parties out of the
  committed tree entirely. Stores SHA-256 digests rather than the names it
  forbids, so the guard is not itself the one file containing them.
- `resolve-advanced` now carries an MIT `LICENSE` in its published tarball, and
  the three vendored workspaces declare `"license": "MIT"`.

## What's New in v2.68.2

Bug fixes. The server no longer opens a second DaVinci Resolve, and a failed
connection now tells the caller what is actually wrong.

### Fixed

- **The server launched Resolve when one was already running — usually the wrong
  one.** The free edition refuses external scripting by design, so on a machine
  where only it is running `scriptapp("Resolve")` always returns None.
  `get_resolve()` read that as *"Resolve is not running"* and ran `open` on the
  application; with both editions installed that started **Studio**, a second and
  different application, on every tool call.

  `resolve_is_running()` now answers the question that was being assumed. It
  returns None when it cannot tell, deliberately — "cannot tell" must never decay
  into "nothing is running", because that is the answer that leads to launching
  something. A genuinely absent Resolve is still launched, as documented, and the
  macOS candidate list now contains **both** editions rather than only the
  installer path.
- **The error a caller received described something that had not happened.**
  Eleven sites asserted that Resolve was not running, that starting it had been
  tried and failed, and that the reader should check their Studio install. After
  the fix above none of that was true, and the accurate guidance was only reaching
  the log. `_not_connected_error()` derives the message from the situation and
  names the applicable remedy — external scripting on Studio, or the in-app bridge
  on the free edition, including the framework-Python prerequisite. Three codes:
  `SCRIPTING_UNAVAILABLE`, `BRIDGE_UNAVAILABLE`, `RESOLVE_NOT_RUNNING`.
- **Those two are marked `retryable: false`.** The `not_connected` category
  defaults to retryable because auto-launch may succeed next time; neither of
  these can — one needs a preference changed, the other a script started inside
  Resolve — and reporting them as retryable sends an agent into a loop it cannot
  win.
- **The offline test suite opened Resolve, and connected to whatever was running.**
  A stub-based audio test reached for `AUDIO_SYNC_*`, which are attributes on the
  *live* object, so it called `get_resolve()`, found nothing, and started Resolve;
  when Resolve *was* open it connected instead, making the test's result depend on
  the state of the machine. `tests/conftest.py` closes both suite-wide and names
  any launch attempt in the terminal summary.
- **`src/server.py` reported the wrong tool count to every agent.** Its module
  docstring said "34 compound tools" while the agent-facing workflow prompt and
  the startup log line said 32. The drift guard only required the correct number
  to appear *somewhere* in the file, so the wrong one shipped. It now rejects any
  other count in front of that phrase, and counts decorators from the parsed
  syntax tree rather than by matching text — a docstring mentioning
  `@mcp.tool()` had been counted as a 35th tool.
- **The bridge harness graded the wrong clip and reported a known trap as a
  finding.** It took the first video item, which is often a generator or title
  that has no MediaPoolItem and answers None to every node query, so the grading
  surface read as unreachable; it now takes the first gradeable item. And it
  passed the codec *description* `"H.264"` to `SetCurrentRenderFormatAndCodec`,
  which only accepts the id `"H264"`, making that observation permanently false
  for a documented reason.

### Changed

- `scripts/install_resolve_bridge.py` no longer claims Resolve ignores Fusion's
  standalone script tree. Measured on free 21.0.3.7: markers left in two
  undocumented container paths both appeared under Workspace ▸ Scripts, so Lite
  scans more locations than the README documents. Install behaviour is unchanged —
  the documented paths work, and each extra target is another chance for the macOS
  App Management prompt to stall the copy — but the stated reason is now the true
  one.

### Validated

Free edition alone (21.0.3.7, App Store), Studio never launched at any point,
confirmed by process check after every stage: 165/165 read-shaped MCP actions
clean with Blackmagic's module blocked; 109/112 API read methods exercised; render
to a non-empty file with `set_format` true; AAF/DRT/EDL/FCPXML all written;
SetLUT clears and reads back. Suite 1913 passing.

## What's New in v2.68.1

Bug fix. A missing tool argument now returns the structured error envelope the
rest of the surface uses, instead of escaping as a raw `KeyError`.

### Fixed

- **A missing argument reached the client as an unroutable crash.** Actions read
  `p["track_type"]` directly; when the key was absent the resulting `KeyError`
  escaped the action, escaped the tool, and arrived as
  `ToolError: Error executing tool timeline: 'track_type'` — no code, no
  category, no remediation. Walking the whole surface found **99 of 512 declared
  actions** failing this way across 16 tools (`timeline`, `graph`, `render`,
  `media_pool`, `media_storage`, `fusion_comp`, `folder`, `gallery_stills`,
  `layout_presets`, `project_settings`, `project_manager_*`, `render_presets`,
  `resolve_control`, `timeline_markers`). They now return, for example:

      {"error": {"message": "'track_type' is required",
                 "code": "MISSING_TRACK_TYPE", "category": "invalid_input",
                 "retryable": false, "remediation": "...", "state": {...}}}

  `retryable: false` matters as much as the code: an input error the caller must
  fix was previously reported through a path that defaulted to retryable, which
  sends an agent into a loop it cannot win.

  The mechanism is a params dict whose missing keys raise a dedicated
  `KeyError` subclass, caught at the tool boundary. Catching plain `KeyError`
  there would have been simpler and wrong — it cannot tell a missing argument
  from an internal lookup failure on some other dict, so our own bugs would have
  been relabelled as the caller's mistake. `contracts.validate` remains the
  preferred tool where a type, range or enum also needs checking, and the actions
  already using it are unchanged.

### Added

- `tests/test_tool_argument_validation.py` walks **every declared action** with an
  empty params dict and asserts none leaks a `KeyError`. Reading the source cannot
  find this class — `p[...]` after a guard is correct and `p[...]` without one is a
  bug — so the walk executes each branch against a stub Resolve. It fails on the
  pre-fix tree and runs in 2 s.

### Changed

- `test_doc_tool_counts` counts `@mcp.tool()` decorators from the parsed syntax
  tree rather than by matching the text. A docstring explaining where the
  decorator has to sit was counted as a 35th tool; prose that mentions a
  decorator is not a tool.

## What's New in v2.68.0

Six engines that let an agent judge its own output before shipping it — audio
loudness, silence calibration, image QC, transcript editing, captions — plus the
**in-app bridge**, which reaches the **free edition** of DaVinci Resolve, whose
external scripting API refuses foreign processes entirely.

### Added

- **Audio delivery QC.** Delivery targets carry a named loudness contract
  (`web`, `podcast`, `ebu_r128`, `atsc_a85`, `ott_dialogue_gated`) and project it
  into the existing `loudness_qc` vocabulary. Dialogue-gated standards emit no
  gradeable `integrated` figure — `loudness_qc` measures full-program, so grading
  a dialogue-gated number against it produces a verdict that means nothing; it
  travels as advisory metadata with the reason stated. No shipped target names a
  standard, because a ProRes master has no inherent programme loudness.
  `render(action='list_loudness_standards')`.
- **Auto-calibrated silence gate.** `plan_silence_ripple` derives the threshold
  from each clip's own dynamics instead of a fixed −30 dB. The metric is `astats`
  **RMS trough** paired with RMS peak: `mean_volume` tracks programme level, and
  `Noise floor dB` moved 19 dB between two fixtures sharing an identical noise
  bed purely because one was quieter for longer. Against ground truth the fixed
  threshold was wrong on all four fixtures. When calibration cannot be trusted
  the item is **kept whole** rather than stripped — a fixed threshold applied to
  material it does not suit is not a degraded answer, it is a wrong one.
- **Image QC.** `media_analysis(action='assess_grade')` gives an agent
  deterministic grounds to reject its own grade: tonal frame, noise
  amplification, banding, highlight posterization and clipping growth, with
  validated **CIEDE2000** (all 33 Sharma/Wu/Dalal reference pairs to 4 dp). A
  clean grade costs zero tokens; vision is spent only where the numbers cannot
  settle it. Non-display-referred working spaces are **refused, never guessed** —
  the right transform depends on camera and project colour management, which a
  frame cannot tell you.
- **Word-level transcript editing.** `edit_engine(action='plan_transcript_tighten')`
  removes fillers, false starts and over-long pauses at word boundaries with a
  reason per cut, and `search_spoken_content` searches word timings across a
  whole shoot to build selects. A lexical axis alongside `find_similar`'s
  semantic-visual one.
- **Captions.** `media_analysis(action='generate_captions')` emits SRT and WebVTT
  under broadcast line rules, plus chapters and YouTube description text.
- **The in-app bridge — live read and write control of the FREE edition.**
  Opt-in with `DAVINCI_RESOLVE_BRIDGE=1`; unset changes nothing for existing
  installs. A script launched from Workspace ▸ Scripts is handed the live
  `resolve` object on any edition and re-exports it over an authenticated
  loopback listener, which `connect_resolve` uses as a third transport beside
  Local and Network. Existing call sites need no changes. This is the documented
  in-app path, not a licence circumvention — but Blackmagic could close it, so
  treat it as supported-until-it-is-not.
- **`shutdown` and `reload` for the bridge.** The launcher blocks (correctly — a
  Scripts-menu script is a child process, so a daemon thread dies the instant it
  returns), which used to mean a stale in-Resolve copy could only be replaced by
  quitting Resolve. `reload` re-imports the runtime from disk in place, and
  refuses before stopping if the new sources will not compile.

### Fixed

- **The bridge was unreachable on the machine it exists for.** `_try_connect`
  returned on `dvr_script is None` before calling `connect_resolve`, the function
  that accepts None in bridge mode. Blackmagic's scripting module ships with the
  *installer*, not the App Store build, so a free-edition-only machine has no
  `Developer/Scripting/Modules` tree and the import fails. Verified by blocking
  the import against a healthy live bridge: `get_resolve()` answered None.
- **Auto-launch started the wrong Resolve, or one nobody asked for.** The macOS
  path list contained only the installer location, so a free-only machine found
  nothing and a machine with both always started Studio. In bridge mode it now
  refuses outright: launching cannot create a listener that only a Scripts-menu
  run creates.
- **Interchange export over the bridge was degrading silently.** Resolve's API
  constants (`EXPORT_AAF`, `AUDIO_SYNC_*`) are plain attributes and `dir()` does
  not list them — measured on 21.0.3.7, `dir(resolve)` returns 34 names with no
  `EXPORT_*` among them while the constants read back as real values. The proxy
  could only call methods, so `hasattr` said False and the server fell through to
  handing Resolve the bare string `"EXPORT_AAF"`.
- **The proxy broke every chain longer than one call.** Every live Resolve object
  reports `type(obj).__name__ == "PyRemoteObject"` — root 34 methods, Project 49,
  TimelineItem 88, one class name — so caching method sets on it let the first
  object touched define `hasattr` for everything after. Method sets are now keyed
  on provenance, and absence is re-verified against the object itself.
- **Bridge error codes never crossed the transport.** Every surface code was
  flattened to `operation_failed`, so `stale_handle` (re-fetch) and
  `ambiguous_locator` (disambiguate) arrived as one undifferentiated failure.

### Validated live

On **DaVinci Resolve 21.0.3.7 (App Store, free, sandboxed)**, with Blackmagic's
scripting module blocked to reproduce a free-only machine: 34 tools, 583 declared
actions, **165 read-shaped actions attempted, 145 clean, zero bridge-attributable
failures**; 109 of the 112 API read methods the tools actually call exercised on
the live object graph; a render completed to a non-empty file; AAF/DRT/EDL/FCPXML
all written by `Timeline.Export`; 400 clips appended in 1.23 s and enumerated at
0.81 ms/item; an evicted handle refusing with `stale_handle` rather than
resolving to another object; and reads *and* writes continuing to work with a
native file dialog open, because the bridge runs in its own process.

`scripts/bridge_differential.py --mode differential` diffs the bridge against
native scripting on one Studio instance. That comparison has **not** been run
yet, so the evidenced claim is that the bridge carries the surface the tools use
on the free edition — not that it is byte-identical to native scripting.

## What's New in v2.67.1

Documentation correction. No code changes — v2.67.0 already ships the correct
behavior.

### Changed

- **`docs/kernels/render-deliver-kernel.md` no longer quotes a format/codec count
  as portable.** It presented "23 formats and 99 format/codec pairs" as the
  expected probe result; a live probe on Studio 19.1.3.7 found 20 formats and 271
  pairs. Both mentions now carry the build they came from and point at probing
  the machine in hand (`probe_render_matrix`, or `list_delivery_targets` with
  `check_availability`) instead of comparing against a fixed number.
- The kernel's boundary list now records the two traps the delivery-target work
  verified live: codec **descriptions are not codec ids** (`H.264` vs `H264`, not
  only the ProRes family), and some formats expose **no codecs at all** (`Wave`,
  `GIF` on 19.1.3.7) and cannot be selected through this API.

## What's New in v2.67.0

Adds **delivery targets** — named render intents that carry their own QC spec —
and fixes a silent render-codec bug found while designing them.

### Fixed

- **Render codec display names were rejected.** `GetRenderCodecs` returns
  `{description: id}`, but the codec was passed to
  `SetCurrentRenderFormatAndCodec`, `GetRenderResolutions`, and
  `prepare_render_job` **raw** while the format was normalized. Verified live on
  Studio 19.1.3.7: `('mov', 'Apple ProRes 422 HQ')` returns False while
  `('mov', 'ProRes422HQ')` returns True — and the same holds for
  `('mp4', 'H.264')` vs `('mp4', 'H264')`. Any render set by the codec name shown
  in the Deliver page failed, across every codec family. This is the codec half
  of the format-id fix (issue #59).
- **A rejected format/codec no longer queues a job anyway.**
  `prepare_render_job` previously applied settings and called `AddRenderJob()`
  even when `SetCurrentRenderFormatAndCodec` returned False, reporting
  `success: True` with `format_success: False` buried in the payload — a queued
  job that would render in the *previously set* codec. It now returns
  `RENDER_FORMAT_CODEC_REJECTED` with the machine's available codecs and queues
  nothing. `set_format_and_codec` returns the same structured error instead of a
  bare `success: False`.
- **The granular server never received the issue #59 fix.**
  `get_render_codecs` passed a raw display name, and
  `set_current_render_format_and_codec` passed both format and codec raw. The
  resolvers now live in `src/utils/render_ids.py` and are shared by both servers,
  so the two cannot drift apart again.

### Added

- **Delivery targets** (`src/utils/delivery_targets.py`) — 28 named render
  intents across master / web / sequence / broadcast / package tiers, every one
  resolved live against Resolve Studio 19.1.3.7 (20 formats / 271 pairs). One
  definition projects onto both Resolve `SetRenderSettings` keys and the
  ffprobe-shaped spec `deliverable_qc` consumes, so a render and the check that
  verifies it come from the same source. New `render` actions:
  `list_delivery_targets`, `resolve_delivery_target`, `prepare_delivery_job`.
  - Ids describe the deliverable (`prores422hq_master`, `h264_1080p_web`);
    platform names (`youtube`, `tiktok`, `avid`, `stems`) are **aliases**, so a
    platform changing its guidance repoints an alias instead of rewriting a target.
  - Format and codec are ordered **candidate lists** resolved against the live
    matrix, because codec descriptions vary by Resolve version, license, and
    installed IO plugins. An unavailable target fails with the machine's actual
    available lists; `list_delivery_targets` with `check_availability` reports
    what this install can render.
  - User-defined targets load from `logs/delivery-targets.json` (override with
    `DAVINCI_RESOLVE_MCP_DELIVERY_TARGETS`); a malformed entry is skipped with a
    warning rather than taking out the shipped set.
- **`deliverable(action="spec_from_authored")`** on the advanced server —
  projects the authored deliverable vocabulary (codec display names,
  `"1920x1080"`, `"-16 LUFS"`, `<SHOW>_<EP>_<YYYYMMDD>.mov` naming templates)
  onto a `deliverable_qc` spec plus a `loudness_qc` target. Anything it cannot
  map is reported in `unmapped[]` rather than dropped.
- **The `deliver` apply contract now carries QC specs.**
  `APPLY_CONTRACT.deliver` emits `qc[]` alongside each deliverable, so a render
  job travels with the spec that will verify it. Previously a stub.
- **`tests.test_duplicate_definitions`** — static guard against a module-level
  name being defined twice under `src/`. pyflakes does not catch this (it only
  reports redefinition of an *unused* name), and the dangerous case is exactly
  the one it misses. Added to the release validation set.

### Notes

- Bitrate is deliberately not encoded in delivery targets: Resolve exposes no
  bitrate render-setting key, only `VideoQuality`, whose type varies per codec.
- Image-sequence and package (IMF/DCP) targets return no QC spec —
  `deliverable_qc` probes a single file, and those render many files or a
  directory. Every such target carries an explicit `qc_skip_reason`, so a missing
  check is always explained rather than silent.
- **There is no audio-only WAV target.** The `Wave` format exposes zero codecs
  and `SetCurrentRenderFormatAndCodec('wav', …)` rejects every value tried,
  including the empty string. Recorded in `src/utils/api_truth.py` and the
  generated `docs/reference/api-limitations.md`.
- The live pass corrected candidate spellings that were wrong: plain
  `"DNxHR HQX"` / `"DNxHR 444"` do not exist (live labels carry a bit depth),
  DPX/TIFF codecs are `"RGB 10 bits"` not `"RGB 10-bit"`, and PNG is not a
  Resolve render format.
- `container` is `"mov"` for both `.mov` and `.mp4`: ffprobe reports
  `format_name=mov,mp4,m4a,3gp,3g2,mj2` for each and only the first token is
  kept, so `video.codec` is what discriminates them.

## What's New in v2.66.0

Generalizes the HTTP transcription backend introduced in v2.65.0 into a
configuration-driven registry, so additional local, network, or cloud-backed
adapters no longer require MCP source changes. Contributed in PR #97 by
@double2tea.

### Changed

- **Pluggable HTTP transcription providers** (PR #97, @double2tea) — the
  MLX-specific router backend is replaced by an ordered registry of HTTP
  transcription providers registered via
  `DAVINCI_RESOLVE_MCP_TRANSCRIPTION_HTTP_PROVIDERS` (a JSON array). Each entry
  requires `id` and `base_url`; optional adapter fields cover `label`, `model`,
  `health_path`, `transcribe_path`, `health_field`, `health_value`, `headers`,
  `request_body`, `field_map`, and `response_field`. Configured providers are
  selected as stable `http:<id>` backend names and preferred in transcription
  capability ordering. Auth headers are sent on health and transcription
  requests but kept out of capability reports, and malformed configuration
  fails fast. Response handling now accepts a transcript object, a JSON-encoded
  transcript string, or plain text under the configured `response_field`.
  Audiobox is documented as one adapter example rather than a core requirement.

### Removed

- The `DAVINCI_RESOLVE_MCP_MLX_AUDIO_URL` / `DAVINCI_RESOLVE_MCP_MLX_AUDIO_MODEL`
  environment variables added in v2.65.0 are superseded by the generic provider
  registry above. To keep an Audiobox/MLX router, register it as a provider:
  `[{"id":"audiobox-local","base_url":"http://127.0.0.1:8000","request_body":{"provider":"mlx"}}]`.

### Validation

- `tests/test_media_analysis.py` and the analysis caps/runs/store suites pass
  (153 on the merged tree); static checks and drift guards pass.
- No DaVinci Resolve scripting behavior changed: the change is confined to the
  stdlib HTTP transcription path and is gated behind an env var. Live Resolve
  validation not required.

## What's New in v2.65.0

Bundles two community contributions from @double2tea: an optional HTTP
transcription backend and a localized, build-aware control panel. Both are
opt-in and change no default behavior — with neither configured, existing
transcription backends and the English panel work exactly as before.

### Added

- **MLX Audio Router transcription backend** (PR #95, @double2tea) — an optional
  HTTP transcription backend that runs outside the Resolve MCP Python
  environment. Enabled only when `DAVINCI_RESOLVE_MCP_MLX_AUDIO_URL` is set and a
  bounded `GET /health` probe succeeds; an optional
  `DAVINCI_RESOLVE_MCP_MLX_AUDIO_MODEL` overrides the router's default model.
  When configured and healthy it is preferred in transcription capability
  ordering, and its response is normalized into the existing JSON/SRT/VTT
  transcript artifacts. Standard-library only (`urllib`); the MCP server never
  installs, starts, or downloads anything on the router's behalf, and existing
  Whisper backends are untouched when no URL is set.
- **Control panel localization (English / Simplified Chinese)** (PR #96,
  @double2tea) — a persistent language switch on the local control panel.
  English remains the authored, canonical UI; the browser stores only the
  selected locale in `localStorage` and the initial locale follows browser
  preferences. Translation runs client-side over the DOM (text nodes plus
  `aria-label`/`title`/`placeholder`) and is fully reversible; no server API or
  persisted project data changes.
- **Build-aware AI console** (PR #96, @double2tea) — the Resolve AI console now
  uses the runtime capability payload to disable actions the connected Resolve
  build cannot execute, distinguishing "Requires Resolve 21+" from "Unavailable
  on this build" and surfacing the Resolve 20 transcription methods
  (`TranscribeAudio` / `ClearTranscription`). Narrow-screen navigation and the
  mobile footer were also improved.

### Validation

- Static checks and drift guards pass; `tests/test_media_analysis.py` (110),
  `tests/test_control_panel_i18n.py` + `tests/test_control_panel_ai_capabilities.py`
  + `tests/test_open_control_panel.py` (14) pass on the merged tree.
- No DaVinci Resolve scripting behavior changed: PR #95 is a self-contained
  HTTP/stdlib backend gated behind an env var, and PR #96 changes only the
  control panel's client-side HTML/JS. Live Resolve validation not required.

## What's New in v2.64.0

Adds opt-in support for DaVinci Resolve's **Network** external-scripting mode
(PR #91… correction: PR #94, by @double2tea), so the MCP can drive a Resolve
instance addressed by IP — including a Resolve running on the same machine with
`External scripting using = Network`. Contributed in PR #94 by @double2tea,
with two additional connection sites hardened during adoption. Local mode is
unchanged and remains the default.

### Added

- **Resolve Network scripting mode** — set `RESOLVE_SCRIPT_HOST` to the Resolve
  host IP (`127.0.0.1` on the same machine) to route connections through
  Resolve's explicit IP-targeted `scriptapp("Resolve", host, timeout)` overload.
  `RESOLVE_SCRIPT_TIMEOUT` (positive finite seconds, default 5) bounds the
  connection wait. When `RESOLVE_SCRIPT_HOST` is absent, the server uses the
  one-argument Local discovery exactly as before. A shared `connect_resolve`
  helper centralizes this behavior; the compound server, granular server,
  analysis dashboard, `scripts/doctor.py`, and the installer's post-install
  connection probe all route through it. The installer copies
  `RESOLVE_SCRIPT_HOST`/`RESOLVE_SCRIPT_TIMEOUT` into generated client configs
  when present in its environment.
- **`doctor.py` Network flags** — `python3 scripts/doctor.py --resolve-host
  <ip> [--resolve-timeout <seconds>]` runs the read-only connection check
  against a Network-mode host.

### Security

- Network scripting permits remote control of Resolve. Documentation (SKILL.md,
  install.md) advises using Local mode when remote access is unnecessary, and
  otherwise restricting access with host firewall and network controls.

### Validation

- Live-validated on DaVinci Resolve Studio 19.1.3.7: Local mode (one-argument
  discovery) and Network mode (`--resolve-host 127.0.0.1 --resolve-timeout 8`)
  both connect through the shared `connect_resolve` helper. PR author validated
  against Studio 20.3.2.9 in Network mode. Full offline suite: 1514 tests.

## What's New in v2.63.2

Installer fix for Windows MSIX builds of Claude Desktop (issue #93, reported by
@corolorn). No tool-surface change.

### Fixed

- **Installer writes Claude Desktop config to the MSIX-virtualized path on
  Windows** — Claude Desktop for Windows ships as an MSIX package (even from
  the official website), and MSIX filesystem virtualization redirects the
  app's config to
  `%LOCALAPPDATA%\Packages\Claude_<publisherhash>\LocalCache\Roaming\Claude\claude_desktop_config.json`.
  The installer previously wrote to the documented `%APPDATA%\Claude\` path,
  which the MSIX-packaged app never reads, so the server silently never
  appeared. The installer now detects the containerized path (publisher hash
  globbed, not hard-coded) and writes there when present, falling back to
  `%APPDATA%\Claude\` for non-MSIX installs. Documented both locations in
  `docs/install.md`.

## What's New in v2.63.1

Documentation-only. Records the `Graph.SetLUT` master-LUT-dir behavior (from the
v2.62.3 fix) in the canonical reference surfaces. No code or tool-surface change.

### Documentation

- **`api_truth` + api-limitations report** — added a `Graph.SetLUT` entry
  (`submit: bug`, #90): `SetLUT` resolves LUT paths only against the master
  (system) LUT dir and configured custom paths, never the per-user dir the
  `dctl` tool installs to; an absolute user-dir path fails too, and
  `RefreshLUTList()` does not help, while a master-subfolder path resolves.
  Verified live on Studio 19.1.3.7 (same behavior reported on 21.0.2 in #90).
  Regenerated `docs/reference/api-limitations.md`.
- **`docs/notes/lut-notes.md`** — corrected a misleading claim that any valid
  absolute path resolves (an absolute path into the user LUT dir does not),
  added a "master LUT dir only" section, and documented the per-user install
  location.
- **`docs/notes/dctl-notes.md`** — noted the same caveat on the `set_lut`
  action, including that `set_lut` now auto-relocates into the master dir.

## What's New in v2.63.0

Waveform silence ripple for the edit engine (PR #91, by @EliteSystemsAI),
adopted with follow-up hardening and live-validated in Resolve Studio.

### Added

- **`plan_silence_ripple` / `execute_silence_ripple`** — waveform-driven dead-air
  removal that mirrors Resolve's *Ripple Delete Silence* dialog (ffmpeg
  `silencedetect` → keep-range variant assembly). Tunable `threshold_db`,
  `min_strip_frames`, `pre_head_frames`, and `post_tail_frames`. Original
  timeline is never mutated; execution is confirm-gated like `execute_tighten`.
  New module: `src/utils/silence_ripple.py`; tests in
  `tests/test_silence_ripple.py` and `tests/test_edit_engine.py`.

### Fixed (hardening on the PR before release)

- **Skipped items ride along whole** — timeline items without a readable media
  file path now emit a full-range keep (video + mirrored audio) so the
  assembled variant never silently loses content; only items with no media
  reference at all are omitted, and the `skipped` reason says so explicitly.
- **All audio streams are merged before detection** — production MXF often
  carries one mono PCM stream per channel, and ffmpeg's default stream
  selection could land on a dead scratch channel, reading entire takes as
  silence. Detection now merges every audio stream (silence only when ALL
  channels are silent — Resolve's dialog semantics), with a single-stream
  fallback if `amerge` refuses the graph. Found by live validation on 5-stream
  interview masters.
- **No pointless video decode** — silence detection runs with `-vn`, so 4K
  ProRes sources no longer decode picture just to scan audio.
- **Clear failure modes** — a missing ffmpeg binary now reports itself instead
  of "no silence regions found", and a plan whose keep ranges are empty
  (source quieter than `threshold_db` throughout) carries an explicit warning
  and is refused at execution.

## What's New in v2.62.3

A single grading fix (PR #90, by @Mldphotohraphie), extended and hardened. No
new tool surface.

### Fixed

- **`graph set_lut` now applies LUTs/DCTLs installed by the `dctl` tool** —
  the `dctl` tool installs into Resolve's per-user LUT directory, but
  `Graph.SetLUT()` resolves LUT paths (relative names *and* absolute paths)
  only against the master (system) LUT directory. A freshly installed LUT could
  therefore never be applied, and `set_lut` always returned
  `{"success": false}`. Verified live on Resolve Studio 19.1.3.7: `SetLUT` fails
  for a user-dir LUT even after `RefreshLUTList()` and even via an absolute
  user-dir path, so relocation into the master dir is genuinely required. (The
  originating report, PR #90, observed the same on Studio 21.0.2.) On a `SetLUT`
  failure the server now locates the LUT, stages it under a namespaced
  `MCP/` subfolder of the master LUT dir (avoiding basename collisions with
  stock/vendor LUTs), calls `RefreshLUTList()`, and retries. No behavior change
  when `SetLUT` already succeeds. Applied to both `graph set_lut` (`src/server.py`)
  and the granular `graph_set_lut` (`src/granular/graph.py`) via a shared
  `src/utils/lut_paths.py` helper, with offline coverage in
  `tests/test_lut_paths.py`.

## What's New in v2.62.2

A single cross-platform launcher fix. No new tool surface; default behavior is
unchanged on macOS/Linux.

### Fixed

- **Advanced server launcher no longer crashes on Windows** —
  `bin/davinci-resolve-advanced-mcp.mjs` resolved the server entry to an
  absolute filesystem path and passed it straight to dynamic `import()`. On
  Windows that path (e.g. `C:\...\resolve-advanced\server\index.mjs`) is parsed
  by Node's ESM loader as a URL whose drive letter reads as the protocol, so the
  launcher died on arrival with
  `ERR_UNSUPPORTED_ESM_URL_SCHEME` ("Received protocol 'c:'"). The path is now
  converted with `pathToFileURL()` before importing — the canonical
  cross-platform way to hand an absolute path to `import()`. macOS/Linux behavior
  is unchanged, and paths containing spaces or special characters are now handled
  correctly on every platform. Thanks to Ryan Saunders (@Alpha7449) for the
  report and fix.

### Validation

- Static checks and `node --check` on the modified launcher run. This is the only
  dynamic `import()` call site in the repo receiving an absolute filesystem path;
  the fix touches the Node advanced launcher only and changes no Resolve
  scripting behavior, so a live Resolve run is not required.

## What's New in v2.62.1

Two correctness fixes for real-world project/DRP layouts. No new tool surface;
default behavior is unchanged.

### Fixed

- **Timeline archiving survives out-of-band archive names** — the archive
  version counter was sourced solely from the local brain DB, so any
  `<name>_archived_vNN` timeline the DB hadn't recorded (another
  session/machine, or a crash between `DuplicateTimeline` and the version
  `INSERT`) collided on the next archive: `DuplicateTimeline` failed and Resolve
  raised a blocking "Unable to Rename Timeline" modal that wedged the UI.
  `archive_current_timeline` now scans every existing `_archived_vNN` suffix in
  the project and treats the DB counter as a floor, not the source of truth.
- **`inject_grades` handles the `SeqContainer/<uuid>.xml` folder layout** —
  `listSeqContainerEntries` only matched the legacy flat `SeqContainer<N>.xml`
  naming, so `inject_grades` threw `No SeqContainer*.xml found` on DRPs using
  the `SeqContainer/<uuid>.xml` folder layout that Resolve 19 exports (the same
  layout the grade-node extractor already handles). Both shapes are now matched.

### Validation

- Static checks and focused unit tests
  (`tests.test_timeline_versioning`, `tests.test_import_from_drp`) run. The DRP
  fix is offline zip surgery requiring no Resolve; the archiving fix is
  defensive counter logic covered by unit tests.

## What's New in v2.62.0

Community contribution by [@lukeashford](https://github.com/lukeashford)
([#87](https://github.com/samuelgursky/davinci-resolve-mcp/pull/87), closing
[#88](https://github.com/samuelgursky/davinci-resolve-mcp/issues/88)): server
robustness for long operations plus a batch of timeline-tool ergonomics and
correctness fixes. Every new option is opt-in; default behavior is unchanged.

### Added

- **Background jobs for long ops** — transcription, subtitle generation,
  scene-cut/Dolby analysis, and timeline export/import can exceed the MCP
  client's tool-window timeout. Passing `background=true` now returns a
  `job_id` immediately; poll with `resolve_control(action="job_status")` or
  list with `list_jobs` (both connection-free). Generic registry in
  `src/utils/background_jobs.py`; workers run under the `resolve_busy` gate,
  and finished jobs are pruned after an hour.
- **`create_variant_from_ranges` pack mode** — `pack=true` butts clips
  together at the end of each track (omits `recordFrame`), gap-free even when
  source and timeline frame rates differ. Live-validated.
- **`timeline set_current` by id/name** — accepts a stable `id`/`name`
  selector (precedence id → name → index), not only the shifting 1-based
  index.

### Fixed

- **Transport wedge** — synchronous tool bodies ran inline on the single
  asyncio event-loop thread, so a blocking Resolve call (or the up-to-60s
  launch wait) froze the whole server including the stdio read loop. Sync tool
  bodies now run in a worker thread, serialized on a bridge lock so the
  single-threaded scripting bridge is never entered concurrently; degrades to
  inline behavior if the SDK shape changes.
- **`create_variant_from_ranges` honesty** — results report actual placement
  (`items[].placed` in both frame spaces, plus a `placement_mismatches`
  count) instead of echoing the requested frames; `dry_run` resolves clip ids
  and validates frame ranges so it fails on the same errors as the commit
  path (and no longer leaves an orphan timeline on a bad id); the response
  reports audio presence and warns on a video-only (silent) range list.
- **`get_items` / `get_items_in_track`** — validate their track selector
  (structured error instead of a bare `KeyError`), accept `index` or
  `track_index`, and gained `action_help` entries.
- **`apply_cuts`** — reports `skipped` cuts with reasons instead of silently
  dropping non-applicable entries.
- **`action_help`** — lists every valid action (not only the documented
  subset) and distinguishes an unknown action (`UNKNOWN_ACTION`) from a
  valid-but-undocumented one (`HELP_NOT_REGISTERED`).

### Documentation

- Corrected `create_variant_from_ranges` help: `clip_id` is a media-pool item
  id (not a timeline-item id); `start_frame`/`end_frame` are SOURCE frames,
  `end_frame` exclusive. Stated the timeline tool's frame-space convention
  once, clarified `lift_range` ripple behavior on empty gaps,
  `begin_run`/`end_run` batching, and the timeline-subtitle vs clip-level
  transcript distinction.

### Validation

- Full offline suite: 1,483 tests green (70 new).
- Transport offload, background jobs, and `create_variant_from_ranges`
  placement/pack behavior were live-validated against Resolve Studio 21 by
  the contributor; the threaded-dispatch SDK coupling was additionally
  verified against the pinned mcp SDK (1.27) over a real stdio session.

## What's New in v2.61.1

The strata cleanup batch deferred from the v2.61.0 review — behavior-neutral
consolidation and hot-path efficiency. No new actions or parameters.

### Changed

- **One clip resolver** — `strata.resolve_clip()` replaces the four drifting
  per-module wrappers, and rides the pre-v9 auto-ingest fallback hoisted out
  of deep_vision into `analysis_store.resolve_clip_uuid_ingesting()`: a clip
  ref that resolves for `deepen` now resolves identically for every strata
  action, including on older analysis roots.
- **One float32 codec** — `pack_curve`/`unpack_curve` delegate to
  `embeddings.pack_vector`/`unpack_vector` instead of duplicating the BLOB
  convention.
- **Decode once** — `strata_run` decodes the media file a single time when
  several audio analyzers run (prosody + beat_grid previously each ran a full
  ffmpeg decode); the shared `_audio_context` preamble also collapses their
  duplicated require/resolve/decode blocks.
- **Registry-derived capabilities** — `ANALYZERS` carries run function plus
  requires/writes metadata; `capabilities()` derives from it, so adding an
  analyzer is one entry.
- **Query-layer caching** — word-find hits clustering in one clip unpack each
  curve blob once, and `timeline_strata` resolves + bundles a source clip
  reused across many placements once.
- **Sargable event windows (schema v15)** — windowed `read_events` bounds its
  span-overlap lower edge by the track's `MAX(duration_seconds)` (a b-tree
  descent via the new `ix_events_clip_track_span` index) so
  `ix_events_clip_track` range-seeks instead of scanning the track.
- `backfill_words` iterates report blobs lazily with a transcription
  prefilter instead of loading every blob into memory; `detect_breaths`
  drops its unreachable non-numpy fallbacks.

### Validation

- Full offline suite: 1,431 tests green (13 new covering the shared resolver
  + pre-v9 fallback, codec identity, decode-once, per-clip caching, long-span
  window overlap, and the index range-seek query plan). No Resolve behavior
  changed; live test not required.

## What's New in v2.61.0

Perception strata — a timecoded track model over every analyzed clip, plus the
query layer that turns it into editorial answers. Ten new `media_analysis`
actions, all local compute (ffmpeg + numpy; the face tier detects opencv +
mediapipe and degrades honestly when absent). Everything measures, compares,
flags, or aims — nothing decides; the cut is the editor's.

### Added

- **Schema v13: perception strata** — two generic track shapes instead of a
  table per sensor: `events` (point/span occurrences: pause, breath,
  hesitation, blink, beat, downbeat, …) and `curves` (float32 time series:
  pitch, vocal_energy, speech_rate, motion_energy, face curves), plus two
  promotions out of the report blob: `transcript_words` (per-word timestamps
  as queryable rows) and `story_beats` (units of meaning over the transcript).
  Machine re-runs replace their own rows; `source='human'` rows are append-only
  and always win.
- **Local analyzers (`strata_run`)** — prosody (pitch/energy/speech-rate curves
  + pause/breath/hesitation events), beat grid (beat/downbeat + tempo), motion
  energy (per-frame luma difference), and face strata (blink/gaze/expression
  via opencv + mediapipe when installed). `strata_status` reports the per-clip
  track inventory and what this machine can run; `backfill_words` promotes
  word timestamps already sitting in stored report blobs — no re-analysis.
- **`take_diff(clip_a, clip_b, text?)`** — align two deliveries of the same
  line on transcript words and diff pace, pauses, pitch, and energy. Deltas
  only; it never picks a winner.
- **`cut_candidates(clip_id, time_seconds)`** — the joint solver: scores every
  frame around an intended cut on the cut-point grammar (cut on the blink,
  don't cut mid-word, don't bisect a breath, pauses are doors, land on the
  beat, cut inside movement) with human-readable reasons per candidate and
  honest reporting of missing tracks.
- **`strata_query`** — the strata as one queryable surface: windowed
  cross-track bundles per clip, or project-wide word find with a joined
  ±context bundle per hit. **`timeline_strata`** projects clip strata through
  a versioned timeline's recorded placements.
- **Story beats (host-LLM pass)** — `plan_story_beats` assembles a timecoded
  digest + JSON schema (the server never calls an LLM), the host chat produces
  the beats, `commit_story_beats` validates and persists them append-only;
  `list_story_beats` reads them back.
- **Schema v14: timeline timebase snapshot** — `timeline_versions` now records
  the timeline's fps and start frame at archive time, so `timeline_strata`
  returns timeline-relative frames/seconds instead of assuming 24fps against
  absolute (start-timecode-inclusive) snapshot frames.

### Fixed

Pre-release review (multi-agent, 8 finder angles + adversarial verification)
caught and fixed before anything shipped:

- **Re-ingest cascade wipe** — the ingest `INSERT OR REPLACE` on the clips row
  cascade-deleted every clip-child table under `PRAGMA foreign_keys=ON`. The
  legacy children are rebuilt during ingest, so this was invisible until the
  strata tables (which ingest does NOT rebuild — human annotations included)
  landed on the same cascade. The clips row is now a true upsert and is never
  deleted.
- **Words-less re-analysis wiped word rows** — `ingest_transcript_words`
  deleted before validating; a re-analysis without transcription (or a mixed
  report whose words lived only at the top level) silently destroyed
  previously backfilled rows. Now parses first, preserves existing rows when
  the incoming report has no words, and falls back per-segment to the
  top-level words list.
- **Machine story-beat commits could replace human rows** — the content-hash
  `beat_uuid` let `INSERT OR REPLACE` overwrite a human beat sharing the same
  span+label and erased supersede history on identical recommits. Beat rows
  now get random UUIDs and plain INSERTs; duplicate spans within one commit
  are skipped and reported.
- **Dispatch hardening** — stringified numbers from LLM clients no longer
  crash `strata_query` (TypeError in curve slicing) or silently redirect
  `timeline_strata` to the latest version; `cut_candidates` rejects
  non-positive fps instead of ZeroDivisionError; word matches escape SQL LIKE
  metacharacters; clip bundles fetch every recorded track (gesture_boundary,
  loudness, custom human tracks) instead of a hardcoded subset; analyzer
  ffmpeg calls go through the stdio-safe `proc.safe_run`; a broken
  mediapipe/protobuf install degrades to "face unavailable" instead of
  crashing `strata_status`.

### Validation

- Full offline suite: 1,418 tests green (17 new regression tests covering the
  fixes above). Static checks, drift guards, npm pack, and API-parity audit
  all pass. No live Resolve behavior changed beyond two defensive getter reads
  (`GetSetting("timelineFrameRate")`, `GetStartFrame()`) at archive time, both
  try/except-guarded and unit-tested against mock timelines.

## What's New in v2.60.0

A community bug-fix bundle — three external contributions plus the three issues
they filed, integrated with the contributors credited as co-authors.

### Fixed

- **Frame accuracy (`edit_engine`)** — `MediaPool.AppendToTimeline` clipInfo
  `endFrame` is an *exclusive* bound (duration = `endFrame - startFrame`), but
  three plan builders wrote an inclusive end (`round(t*fps) - 1`) and
  `execute_selects` advanced its record cursor by `end - start + 1`. Result:
  `plan_tighten` kept ranges were one frame short per segment (~4.3s across 130
  segments), `plan_selects`/`plan_swap` source ranges were one frame short, and
  `execute_selects` left a 1-frame gap between selects. Now half-open everywhere.
  (#82, thanks @chenyuxiaojin)
- **Timeline rename no longer archives (`destructive_hook`)** — `timeline.set_name`
  was version-on-mutate, so renames spawned redundant `_archived` timelines
  (and renaming an archive archived the archive). A rename is content-preserving,
  so it's out of the destructive registry. (#83, thanks @chenyuxiaojin)
- **Windows startup (`server`)** — initialize the Resolve scripting env
  (PYTHONHOME, PATH, `os.add_dll_directory`) before importing the fusionscript
  bridge, avoiding a native access violation that crashed network transports
  before bind. No-op off Windows. (#78, thanks @POLEPALLIANVESH)
- Fixed a stale offline test that patched a refactored-away seam
  (`project_manager` delete routing), restoring a fully green baseline.

### Added

- **`execute_tighten(..., include_details?)`** — the readback `structural_diff`
  is compact by default (counts + a small head/tail sample) instead of embedding
  every before/after item id (226 KB for a 130-segment tighten). The full
  per-item diff is persisted in the plan record (`get_plan` →
  `execution_summary.structural_diff`) and returned inline with
  `include_details=true`. (#84, thanks @chenyuxiaojin)
- **`plan_tighten` skip dedup** — identical `(item, reason)` skip rows collapse
  into one entry with a `count` (an unanalyzed layer no longer repeats the same
  row once per segment). (#81, thanks @chenyuxiaojin)

### Documentation

- Recorded the `AppendToTimeline` `endFrame` exclusive-bound semantics in the
  `api_truth` ledger (internal quirk entry). (#80, thanks @chenyuxiaojin)

### Validation

- Full offline suite green (1343 tests). Static/drift guards pass.
- Live Resolve validation of the #82 frame-accuracy fix (selects butt-join +
  tighten frame-exact keep ranges) on a disposable project.

## What's New in v2.59.0

First-class conform ingest for **AAF** and **DRP**, an offline **Premiere `.prproj`** reader with
a conform bridge, and a unified sequence enumerator — so an editorial turnover in any of these
formats can be previewed, picked, and brought into Resolve. Everything keeps the honest-refuse
philosophy: no format is ever faked; an unreadable file yields a clear, actionable error.

### Added

- **AAF** — offline preview via the advanced server's `editorial.parse_interchange` (format `aaf`)
  and `list_sequences`, backed by the pure-Python `aaf2` (pyaaf2) reader (shelled out from Node;
  honest-refuses with an install/convert hint when unavailable). Live AAF import now works through
  `timeline.import_timeline_checked` — the XML sanitize pass is skipped for the binary format and,
  when `relink_search_roots` is passed, a post-import media-pool relink runs (fuzzy-relink parity
  via `RelinkClips`), reported in a `relink` block.
- **DRP** — `drt.list_sequences` enumerates the timelines inside a `.drp`/`.drt`
  (`[{id, name, eventCount}]`) to drive a picker; `timeline.import_from_drp` extracts the chosen
  timelines (offline zip surgery → temp `.drt`) and imports each into a running Resolve.
- **Premiere `.prproj`** — a from-scratch offline reader (gunzip + object-reference-graph walk, no
  new dependencies) exposed through `parse_interchange` / `list_sequences`. Derives cuts, source
  in/out, timeline positions, speed/retime, reverse, transitions, markers, and media paths. Effects
  and Lumetri color are not translated (the Premiere→Resolve semantic gap, flagged not faked).
- **Conform bridge** — `editorial.convert_to_interchange` authors OTIO / EDL / DRT that Resolve
  imports, from normalized events or a parsed source. This lets a `.prproj` be conformed into
  Resolve with no Premiere in the loop.
- **Unified enumeration** — `editorial.list_sequences(path)` is one picker entry point across
  xml/edl/otio/drt/drp/aaf/prproj.

### Dependencies

- New optional-but-default `requirements.txt` pins `pyaaf2` (pure-Python, MIT, ~1 MB) for the
  offline AAF reader; the installer points the advanced server's `AAF_PROBE_PYTHON` at the project
  venv so it works out of the box. Without it, AAF preview honest-refuses; nothing else needs it.

### Validation

- Static checks, drift guards, and focused unit tests pass (advanced Node suite 455 pass / 9 skip;
  new `test_import_from_drp.py` and `prproj-bridge.test.mjs` / `aaf-sequences.test.mjs`). Offline
  AAF parse validated end-to-end against a real `aaf2`-authored AAF.
- **Not yet live-validated in Resolve**: AAF import, the post-import relink, `import_from_drp`, and
  importing an authored OTIO/DRT from a real `.prproj`. These paths are offline-tested (fake Resolve)
  and guarded; confirm against a live session with disposable projects before relying on them.

## What's New in v2.58.0

Major expansion of the optional **advanced** Node server (`davinci-resolve-advanced-mcp`,
bundled in the same package) — the beyond-the-API sibling that edits Resolve files
(`.drp`/`.drt`/`.drx`) offline. It grows from 14 to **18 tools** and adds a deterministic,
offline grading/QC/finishing catalog. All new capability is offline, deterministic, and
carries silent-lie guards (it refuses to fabricate a result). None of it touches the live
Python server or its tool counts.

### Added

- **Grading catalog** (`drx` actions): `scope_read` (frame readouts — RGB parade, vectorscope
  skin-line, black-balance, %clip/%crush + shot-intent signals), `intent_tags`, `verify_grade`
  (intended vs applied → landed/drifted/missing/unverifiable), `extract_frames` (display-referred,
  hard log-refuse), `match_to_reference`, `saturation_match`, `black_balance`, `tone_curve_transfer`
  (luma CDF matching), `skin_match` v2 (luma-preserving skin-line metric), `author_look` / `carry_look`
  (season-look authoring), and `lut_apply` — a reverse-engineered Body-LUT write path that attaches a
  named `.cube` to a grade node with a round-trip assert.
- **`deliverable` tool** — deliverable QC/compliance: `deliverable_qc` (ffprobe vs spec, pass/fail per
  field), `loudness_qc` (EBU R128), `reframe_blanking_check`, `render_manifest` (checksum/reconcile),
  `conform_completeness`, `re_delivery_diff`, `expand_deliverable` (texted/textless/stems entities).
- **`media` tool** — media front-end / AE: `ingest_verify` (hash seal/verify/dupes), `media_inventory`,
  `sync` (TC), `relink_manifest`, `rename_plan` / `reel_normalize` (refuses camera originals),
  `turnover_package`, `project_hygiene`.
- **`editorial` tool** — editorial integrity: `parse_interchange` (EDL/OTIO/XMEML), `turnover_changelist`
  with timing silent-lie guards, `conform_manifest`, `marker_roundtrip`.
- **`provenance` tool** — provenance/audit: `gallery_lineage`, `grade_provenance`, `cdl_export` (+diff),
  `revision_tracking`, `episode_report`.
- **Node-labeling / provenance** on every auto-emitted grade node (`AUTO:<tool> v<n> → <source>`),
  a **runner→apply contract** (stage → live-server action mapping), and runner **stage-resume**.
  The pipeline records per-episode decoded facts, drift, and provenance (`readback`) — the
  substrate the maintainers' managed application mines for cross-episode insights (see the
  README's Bradford Post Assistant note).
- **DRX value-space calibration (Phase 1)** — one unified `space: 'ui' | 'drx'` flag on `drx`
  `generate`/`merge`: `'ui'` (the default) takes Resolve panel numbers for every primary
  (lift ×2, gamma ×4, gain 1:1, offset panel-delta ÷25, saturation 0–100 ÷50 — factors
  calibrated by live panel readback against Resolve 19 Studio); `'drx'` takes raw internal
  floats losslessly. 28 scalar/wheel/affine controls confirmed aligned. Factor reference in
  `resolve-advanced/vendor/drx-parameters/DRX-VALUE-SCALING.md`; coverage ledger in
  `CALIBRATION-STATUS.md` alongside it.
- **DRX structural write fidelity (Phase 2)** — the structural write paths (windows,
  qualifiers, HDR zones, HSL curves, ColorSlice, Color Warper) were audited against live
  Resolve and rebuilt where broken; items marked live-verified below were confirmed by
  applying a generated `.drx` and reading the Resolve panel:
  - **Power windows** — true live-calibrated transform scales (rotate −UI°/180, size
    1+(UI−50)×0.08, aspect (50−UI)/50, pan/tilt ×4096, softness ×16) replace placeholder
    conventions the registry's old ranges clamped to garbage; linear softness masks and
    gradient params now route to their real corrector blocks. Live-verified exact.
  - **HDR zones** — multi-zone grades now write every zone into the single
    `ZONE_ADJUSTMENTS` param (previously only the last zone survived the encode).
    Live-verified with two zones exact.
  - **Qualifiers** — HSL ranges live-verified exact; RGB and luma modes newly reachable via
    `rgbQualifier` / `lumaQualifier` (mode flags corrected to their real varint wire form;
    the Qualifier palette switches modes correctly). RGB live-verified exact.
  - **ColorSlice** — new write path for the six global controls (identity scale, Hue stored
    negated). Live-verified exact.
  - **HSL curves** — sat/lum-axis curves write correctly with per-curve meta
    (`hslCurveMeta`); hue-axis curves are a strict bezier control cage, and a canonical
    emitter (`canonicalizeHueAxisPoints`) reproduces Resolve's own serialization —
    live-verified single- AND multi-band at multiple positions and values. Known-bad
    geometry (a bump edge landing exactly on a band slot) passes through raw instead
    and now surfaces a `warnings` array on the `generate`/`merge` result ("renders
    FLAT"). Because a malformed wrapped cage can crash Resolve 19 outright, caller-built
    pre-wrapped point lists (x outside [0,1]) are **refused** unless
    `allowWrappedHueCage:true` (the verbatim re-encode escape hatch). `generate` and
    `merge` share the same `space:'ui'` default, and every bundled matcher emitter pins
    `space` explicitly.
  - **Polygon/curve window shapes** — new ct6 vertex-ring write path; geometry renders and
    masks exactly as one window row.
  - **Color Warper** — new pin-list write path matching the Resolve 21 wire format;
    round-trips exactly but Resolve 19 ignores it (version-gated — pending an R21 verify).

### Fixed

- `drx` `parse` now reads back custom curves / HSL curves / qualifiers / power windows through the tool
  (the augmentation passed the node params object instead of the flat corrector parameters).
- **Two long-standing DRX "known bugs" resolved as not encoder bugs** (live panel readback):
  `hueRotate` stores `(UI−50)/50` (input 60 → panel Hue 60.00), and `contrastHighRange` is
  stored `1−UI` **by Resolve itself** (input 0.70 → panel ↑Rng 0.700; low range is 1:1).
  Both now round-trip in `space:'drx'` via normalizer compensation; the old bug-locking test
  was replaced with correct assertions.
- Vestigial `satVsSat` registry ranges removed — they silently clamped real gradient-window
  writes (the 0x08F000xx ids belong to the gradient window; the real Sat-vs-Sat curve is an
  HSL spline).
- **Blur / Key / Motion Effects palettes decoded AND writable** (the last unswept native
  palettes): the registry's legacy "Curves corrector (Type 18)" grouping was measured
  wrong — those ids are the Key palette (ct9, identity scales) and the Motion Effects
  palette (a newly identified corrector type 15). Blur-palette radius/H-V ratio store as
  (UI−0.5)×2 (two-point fit). New `gradeParams.blur` / `key` / `motionEffects` write
  paths, panel-readback-verified (Frames varint = frames×2 confirmed); all named in the
  registry and locked by a new fixture + calibration/write tests; the sweep grade decodes
  with zero unknown_ params.
- **3D-qualifier selection volume blob decoded** (the last offline-reachable opaque blob):
  a packed header + float32 sample point cloud — the keyer's chroma-plane stroke path,
  now lifted as `qualifier3d` with a per-sample decode locked by test.
- **Programmatic "Cleanup Node Graph"** — Resolve's node-layout tidy is UI-only (no
  scripting API); a before/after Project.db diff proved it rewrites only the per-node
  x/y position varints in the graded version Body, and direct injection of rewritten
  positions was live-verified to render with the grade intact. Two productized paths:
  - `drx` `relayout` — rewrites node positions in a `.drx` to Resolve's own clean-row
    layout (or explicit `positions`), byte-preserving everything else (labels, keyframes,
    OFX). Live single-clip recipe (verified on a production clip): grab still → `relayout`
    → `reset_all_grades` → `ApplyGradeFromDRX`. The reset is required — a same-structure
    apply silently keeps the existing node layout (new `api_truth` entry).
  - `project_db` `relayout_node_graphs` — whole-project sweep over every graded version
    row (closed project, dry-run, auto-backup, per-row read-back verify, undecodable rows
    skipped and reported, already-clean rows left untouched). Resolve caches open projects
    in memory, so the patch is only visible after a full quit + relaunch — the result
    says so explicitly.

### Documentation

- Advanced-server section + tool table updated to 18 tools; `resolve-advanced/README.md` catalog expanded.
- **Control panel learns about the advanced server** (read-only): Setup → **Advanced**
  (live capability card — pure-JS core + ffmpeg/sharp/better-sqlite3 status with install
  hints), Setup → **Conform QC** (lineage-sidecar browser: snapshots, diff-vs-previous,
  per-cut frame-QC verdicts with tallies), and Docs → **Advanced Server** (the full
  18-tool catalog rendered in-panel). Backed by a deliberate read-only Node bridge
  (`resolve-advanced/scripts/panel-bridge.mjs` — capabilities + lineage
  list/show/diff/verdicts only; ingest/QC/patches stay with the MCP tools) and two new
  panel endpoints (`/api/advanced/capabilities`, `/api/advanced/lineage`). Degrades
  gracefully when Node.js is absent.
- `docs/SKILL.md` gains an advanced-server operating section (value-space rules, hue-axis
  guard/warnings, relayout recipes, closed-project DB-patch + quit/relaunch discipline) plus
  DRX-apply gotchas and a session-start MCP-update note (surface `update_decision` once;
  applying updates stays with `install.py` / the control panel).
- New DRX calibration docs: `CALIBRATION-STATUS.md` (per-control coverage ledger — what is
  confirmed, how it was verified, and what remains experimental) and a corrected
  `DRX-VALUE-SCALING.md` (offset ÷25, saturation ÷50, contrast 1:1, affine hue/contrast-range
  mappings).

### Validation

- Full offline Node suite green (671 tests / 650 pass, legacy live harnesses skip cleanly) +
  doc-count drift guard. DRX write paths live-verified against DaVinci Resolve 19.1.3 Studio
  by panel readback (windows, qualifiers, HDR zones, ColorSlice, HSL curves); Color Warper
  write is R21-format and pends an R21 verify. Resolve-behavior validation for the offline
  QC/finishing tools remains gated on real footage (they compute/plan; apply stays in the
  live server) — no live Python-server behavior changed in this release.

### Cross-platform agent guidance

Also in this release: per-domain agent routing between the live Python server and the
offline advanced server, available in every IDE — not just Claude Code. No tool counts
change (compound 34 / granular 341 / advanced 18).

- **7 per-domain MCP prompts** (`color_grade_workflow`, `timeline_edit_workflow`,
  `conform_workflow`, `delivery_workflow`, `fusion_workflow`, `audio_workflow`,
  `media_pool_workflow`) — slash commands in *every* MCP client, each routing a task
  across its live tools and its offline advanced-server counterpart (compute offline,
  apply live).
- **9 Claude Code skills** (`.claude/skills/`): a `resolve-mcp` index plus eight domain
  routers (color, edit, conform, delivery, fusion, audio, media-pool, media-analysis).
  Thin bridges to the kernels; all 18 advanced tools are routed.
- **Generated cross-platform rule files** from a single manifest
  (`scripts/agent-rules/generate.mjs`): `.cursor/rules/*`, `.github/instructions/*` +
  `.github/copilot-instructions.md`, `.windsurf/rules/*`, `.clinerules`, `.roo/rules/*`,
  `.continue/rules/*`, and an `AGENTS.md` domain-routing block. Tool/action counts are
  parsed from their canonical docs so they cannot drift; a stale generated file fails
  `tests/test_agent_rules_drift.py`.
- Every kernel with an offline counterpart gained an "Advanced (offline) server" section.
  Fixed stale tool counts / doc paths that had drifted in `.github/copilot-instructions.md`,
  `.clinerules`, `.cursorrules`, and `.windsurfrules`.

## What's New in v2.57.5

Fixes a silent data-loss bug on Reel Name writes (issue #77) and bundles the
community-contributed API-limitation entries from PR #76 (issue #75).

- **Fixed** (#77) `set_clip_property` / `set_metadata` reporting `success: true`
  when writing the `Reel Name` clip property even though Resolve silently
  dropped the value. Resolve gates `Reel Name` behind the project setting
  *General Options > Assist using reel names from the:* — when that derives reel
  names automatically, scripted writes are ignored but still return `True`. On a
  batch ingest this meant hundreds of clips believed to have reel names assigned
  when none actually stuck. The server now reads the value back after writing
  known-unreliable keys and refuses to report success on mismatch, surfacing the
  project-setting gate as a `hint`. Wired into `set_clip_property`,
  `set_metadata` (both forms), and the bulk `normalize_metadata` path. Adds an
  `api_truth` bug entry (report now lists 18 missing + 11 bugs) and 10 unit
  tests.
- **Added** (PR #76, thanks @swayll) four `submit: missing` API-limitation
  entries verified on Resolve 21.0.0: per-subtitle text/timing editing, subtitle
  track styling/presets, speech-recognition engine selection + SRT import, and
  Media Pool folder rename. These document the API ceiling behind the subtitle
  feature request in #75 — direct subtitle text editing and SRT round-trip are
  not exposed by the Blackmagic scripting API.

### Validation

- Offline: full unit suite green; new `tests/test_reel_name_writeback.py` (10
  tests) plus the api_truth/limitations drift guards. Live Resolve validation of
  the Reel Name read-back is recommended but not performed here — forcing the
  gate would require writing reel names into a live project's media metadata.

## What's New in v2.57.4

Live mutating verification of the catalogued API gaps.

- **Added** `tests/live_api_gap_verification.py` — attempts each catalogued
  "missing capability" against a disposable project built from synthetic ffmpeg
  media, recording the failing call alongside a positive control that succeeds.
  All 8 surface-audited gaps confirmed missing on Resolve Studio 21.0.0:
  `SetProperty('Speed', …)` / audio-level keys return False while
  `RetimeProcess` / video-transform keys succeed; trim/move/split/proxy/node-
  graph/Smart-Bin methods are absent (by `dir()`), while append/CDL/AddSubFolder
  controls work.
- **Added** a new bug entry: `hasattr()`/`getattr()` are unusable on Resolve
  objects — the Python bridge fabricates a callable for ANY attribute name, so
  capability detection must use `dir()`. (Discovered when the first harness pass
  reported nonexistent methods as present.) Report now lists 14 missing + 10 bugs.
- **Changed** the report's Scope note to record the live mutating-harness
  methodology and the `hasattr` caveat. Strengthened the clip-speed and
  Fairlight-audio entries with the live `SetProperty` rejection evidence (and
  noted that `'Pan'` is the video-transform key, not audio pan).

## What's New in v2.57.3

Expanded the API-limitations catalogue with a live surface audit.

- **Added** 8 newly-catalogued **missing capabilities** to
  `docs/reference/api-limitations.md`, found by a `dir()` audit of the live
  Resolve 21.0.0 API objects diffed against the UI feature set: timeline-item
  trim/move/re-time (getters only, no setters), razor/blade/split, clip
  speed/retime ratio & ramps, color node-graph editing + primary grade values,
  Fairlight audio levels/pan/EQ/automation/FairlightFX, proxy/optimized-media
  generation, insert/overwrite/replace/fit-to-fill edit modes, and Smart/Power
  Bin creation. The report now lists 14 missing capabilities + 9 bugs.
- **Verified** the four previously-doc-derived entries (per-clip audio
  stereo↔mono, native multicam creation, transitions, cloud list/export/user)
  against the live API surface; all confirmed absent.
- **Changed** the generated report to carry an explicit **Scope & completeness**
  note — it is not guaranteed exhaustive (surface audit + incident log; misses
  parameters that exist-but-misbehave and untested capabilities).

## What's New in v2.57.2

Consolidated, submittable list of Resolve scripting-API limitations.

- **Added** `docs/reference/api-limitations.md` — a curated, behaviorally-verified
  catalogue of Resolve scripting-API gaps and bugs, split into **Missing
  Capabilities** (please add) and **Bugs / Unreliable Behavior** (please fix),
  formatted for submission to Blackmagic Design's developer feedback. First cut:
  6 missing capabilities (Source Track Selector / insert `trackIndex`, per-clip
  audio stereo↔mono, native multicam-clip creation, transition create/copy,
  `GetTimelineByName`, cloud project list/export/user management) and 9
  bugs/unreliable behaviors (enum-key silent failures in `AutoSyncAudio`,
  `CreateSubtitlesFromAudio`, CloudProject family, and `Timeline.Export`; flaky
  `DeleteProject`; `Composition.Paste` bridge failure; `FlowView` unreliable
  returns; truncated `Transcription` property; automation-blocking `CreateProject`
  modal).
- **Added** `scripts/gen_api_limitations.py` — the report is generated from the
  `submit`-tagged entries in the `api_truth` ledger (single source of truth, also
  queryable at runtime via `resolve_control api_truth`), so it never drifts.
- **Changed** the release process and CI to keep it current: a new
  `tests.test_api_limitations_doc` drift guard (added to the publish workflow)
  fails if the doc is stale, and `docs/process/release-process.md` now requires
  regenerating it whenever a `submit`-tagged entry changes.

## What's New in v2.57.1

Investigation outcome for community feature request #74 — no behavior change.

- **Note** (issue #74) the DaVinci Resolve scripting API does not expose the
  Source/Auto Track Selector, so there is no way to choose the destination track
  when inserting Text+/titles/generators. Verified live on Resolve Studio 21.0.0:
  no get/set for the selector exists; the `Insert*IntoTimeline` family takes no
  `trackIndex` and always lands on V1; locking lower tracks makes the insert fail
  rather than redirect; and titles/generators can't be relocated afterward (no
  `MediaPoolItem`). Closed as won't-fix (API limitation).
- **Documentation** recorded the limitation in the verified `api_truth` ledger
  (query at runtime with `resolve_control api_truth "track"`) and in
  `docs/reference/api-coverage.md`, with the supported alternative for
  media-backed clips (`MediaPool.AppendToTimeline` clipInfo `trackIndex`, exposed
  as `media_pool.append_to_timeline` `clip_infos`). Added a regression test.

## What's New in v2.57.0

Community feature requests #72 and #73.

- **Added** OpenCode to the installer's supported MCP clients (issue #72). The
  installer now writes/merges `~/.config/opencode/opencode.json` using OpenCode's
  own schema (`type`/`enabled`, a combined `command` array, and an `environment`
  block), and `--manual` prints a ready-to-paste OpenCode snippet.
- **Added** `fusion_comp(action="add_fusion_mask", ...)` (issue #73): a one-call
  Rectangle/Ellipse mask — adds the mask tool, sets its params (`corner_radius`,
  `width`, `height`, `center`/`center_x`/`center_y`, etc., all 0..1), and
  optionally wires it into a tool's mask input (`EffectMask` by default). Each
  input is applied independently so one unsupported parameter never aborts the rest.
- **Added** `fusion_comp(action="set_text_plus" / "get_text_plus", ...)` (issue
  #73): read/write the text of a Fusion `Text+` tool or Fusion title template
  (e.g. a "Deep" title), auto-finding the `Text+` tool when `tool_name` is
  omitted. Complements `timeline(action="set_title_text")` for generator titles.
- **Note** (issue #73) per-clip audio Stereo↔Mono conversion is not in
  Blackmagic's scripting API and was not added. The supported surface is already
  exposed: `timeline get_track_sub_type` (query channel format), `add_track` with
  `audioType` (create mono/stereo tracks), `convert_to_stereo` (timeline-wide),
  and `timeline_item get_source_audio_channel_mapping`.

## What's New in v2.56.1

Final reliability batch from the exhaustive audit (Wave B + P2/P3 selections).

- **Fixed** (EX11) `audio_track_probe` reported `available: true` for track index 0
  (and negatives); audio tracks are 1-indexed, so it now requires
  `1 <= index <= track_count`.
- **Fixed** (EX10) `_find_timeline_item_by_id` no longer silently skips a whole
  track type when `GetTrackCount` errors — it logs the failure so a real API error
  isn't mistaken for "item not found".
- **Fixed** (P3) the raw `timeline_item_color.set_cdl` now validates the ASC-CDL
  payload (shape/ranges) before `SetCDL`, matching its safe twin — malformed CDL
  returns a structured error instead of being silently rejected by Resolve.
- **Fixed** (P2) `media_pool.delete_timelines` is read-back verified: it reports
  `verified` from the project's timeline count dropping, not the unreliable boolean.
  `import_folder` now validates its required `path`.

## What's New in v2.56.0

Destructive-action registry audit (EX-REG) — a systemic version of the EX2 bug.

Many destructive actions were registered under the **wrong tool key**, so
`is_destructive()` returned False and **version-on-mutate archiving / change
logging silently never fired** for them. Examples: `create_timeline`,
`auto_sync_audio`, `create_stereo_clip`, `append_to_timeline` were filed under
`timeline` though `media_pool` dispatches them; `set_cdl`, `copy_grades`,
`export_lut`, the version ops were under `timeline_item` though
`timeline_item_color` dispatches them; the Fusion-comp and take actions used stale
names (`add_fusion_comp`, `delete_take`) that matched no real handler.

- **Fixed** rebuilt `DESTRUCTIVE_ACTIONS_BY_TOOL` so every action is keyed under
  the tool that actually dispatches it (stale names mapped to real ones:
  `*_fusion_comp` → `*_comp`, `*_take` → `add`/`delete`/`select`/`finalize`,
  `import_into` → `import_into_timeline`, `create_subtitles_from_audio` →
  `create_subtitles`). Inert entries whose tool isn't governed (media_pool_item
  `replace_clip`/`link_*`) were dropped. Catastrophic take/Fusion-comp deletes and
  the media-pool create/sync ops are now archived as intended.
- **Added** the registry-drift guard now asserts *every* registry action is a real
  handler of its tool (broad check enabled), so this class can't regress.

## What's New in v2.55.2

Deep-QC P1 1b — required-param validation. Mutating/destructive actions that
hard-indexed required params (`p["name"]`, `p["index"]`, `p["color"]`, …) now
return a structured error instead of crashing with an unhandled `KeyError` (or,
for `set_clip_enabled`/`set_current`, coercing the value). Guarded actions:

- `timeline`: `set_current`, `set_name`, `set_start_timecode`, `add_track`
- `timeline_item`: `set_property`, `set_clip_enabled`
- `project_manager`: `create`, `load`, `import_project`, `export_project`,
  `archive`, `restore`
- marker `delete_by_color` (clip / timeline / item — destructive)
- `layout_presets`: `save`, `export`; `project_settings`: `set_name`, `set_setting`

## What's New in v2.55.1

Deep-QC P1 — settings/options whitelisting + DeleteProject reliability.

- **Fixed** options/settings dicts passed to several Resolve APIs are now
  whitelisted to their documented keys, so a typo'd key is reported instead of
  silently dropped (`_filter_to_keys` → `ignored_options`/`ignored_settings`):
  `media_pool.import_timeline` (ImportTimelineFromFile), `timeline.import_into_timeline`
  (ImportIntoTimeline), raw `render.set_settings` (SetRenderSettings) and
  `render.quick_export`, and `set_voice_isolation_state` (track + item).
- **Fixed** `ProjectManager.DeleteProject` is flaky — it silently returns False
  when the target is/was the current project. All callers (the safe and raw
  `project_manager.delete` actions and the granular `delete_project`) now route
  through `delete_project_safely` (switch-away + retry) and report `delete_detail`.
  Added an `api_truth` entry.
- **Added** a destructive-registry drift guard (`tests/test_destructive_registry_drift.py`)
  that asserts token-gated actions map to real handlers and locks in the media-pool
  delete governance from v2.55.0. (It also surfaced a pre-existing registry
  mis-keying issue now tracked for a dedicated audit.)

## What's New in v2.55.0

Governance for catastrophic Media Pool deletes (exhaustive audit EX2/EX3).

**Behavior change:** `media_pool` `delete_clips`, `delete_folders`, and
`delete_timelines` now require a confirm token, the same two-step handshake
`timeline.delete_track` already uses — the first call returns
`status: "confirmation_required"` with a `confirm_token` and a preview (count +
names); re-call with `params.confirm_token` to execute. Callers that disable
gating via the `destructive.require_confirm_token=false` preference are
unaffected.

- **Fixed** the destructive-action registry listed granular function names
  (`delete_media_pool_clips`, `move_media_pool_folders`, …) that the compound
  `media_pool` tool never dispatches, so `is_destructive()` returned False and
  these catastrophic deletes silently skipped version-on-mutate archiving and
  change logging. The registry now uses the real compound action strings, so the
  deletes are archived/logged as intended.
- **Added** confirm-token gating + previews to the three deletes (EX3). The
  registry fix also re-enables the existing media-pool change log for them.
- Live-validated against DaVinci Resolve Studio 21.0.0 (non-destructively): the
  no-token call returns `confirmation_required` and deletes nothing.

## What's New in v2.54.5

Reliability + security hardening from the exhaustive reliability audit (Wave A).

- **Security** `apply_spec` hooks no longer run with `shell=True`. A spec's hook
  command is now `shlex`-split and executed without a shell, so a hook string
  can't inject arbitrary shell (`; rm -rf …`, pipes, expansion). Hooks needing
  shell features must invoke an interpreter explicitly (e.g. `bash -c "…"`).
- **Fixed** the confirm-token table (`_CONFIRM_TOKENS`) is now guarded by a lock.
  The control panel is threaded, so issue/consume/GC ran concurrently; validate-
  then-pop is now atomic and GC can't race a write.
- **Fixed** negative item indices are rejected instead of silently returning the
  wrong item (Python reverse-indexing): `_get_item`, the audio item resolver, and
  the two timeline-matte helpers now require `0 <= index < len`.
- **Fixed** history queries clamp `limit` to `[1, 1000]`. SQLite treats a negative
  `LIMIT` as "no limit", so a negative value could silently fetch the entire table
  (`get_brain_edit_history`, `list_runs`, `get_media_pool_change_history`).
  `timeline_versioning` version/limit/keep_n params are now validated (no unhandled
  `ValueError`; `rollback` rejects negative versions before archiving). `max_files`
  /`max_seconds` in the relink file search are clamped positive.
- **Fixed** the server-reachable ffmpeg probes (render, audio, review) now pass
  `timeout=120` so a hung ffmpeg can't block the server indefinitely.

(Deferred to a live-validated follow-up: confirm-token gating + archiving for
catastrophic media-pool/take/fusion deletes, and temp-directory lifecycle cleanup.)

## What's New in v2.54.4

Persistence-safety hardening (generalizes issue #71 to the analysis state
stores). A multi-agent audit found several state files whose **readers** swallow a
`JSONDecodeError` and reset to an empty default — so a later read-modify-write
writes back only the new field, silently wiping prior data. Atomic writes don't
help, because the loss happens at *read* time.

- **Fixed** read-modify-write paths now read strictly and **refuse to overwrite**
  a corrupt existing file (via a shared `ConfigParseError` + `_read_json_strict`),
  rather than clobbering it:
  - media-analysis **preferences** — 5 write paths (set-defaults, timed-marker
    default, sampling-mode default, AI governance, caps preset)
  - **update-state** — configure/clear update settings (3 paths), now also written
    atomically (temp + `os.replace`)
  - per-clip **corrections** (human edit history — the highest-value store) —
    update and revert paths
- **Fixed** non-atomic writes that a crash mid-write could truncate: the bin
  summary markdown and Fusion `.setting` files now write to a temp file and
  `os.replace`.
- **Fixed** a read-modify-write race on `analysis.json` under the threaded control
  panel: transcript regeneration is now serialized under the existing state lock,
  so a concurrent regen/batch write can't drop the other's updates.
- Read-only callers keep their forgiving behavior (they fall back to defaults and
  never write). New tests in `tests/test_persistence_safety.py`.

## What's New in v2.54.3

Follow-up to the v2.54.2 config-merge fix (#71): the JSONC sanitizer's
trailing-comma step was not string-aware.

- **Fixed** `_strip_jsonc` removed trailing commas with a regex applied to the
  whole document, so a comma inside a string value followed by whitespace and a
  closing brace/bracket — e.g. `"greeting": "hello, } world"` — had the comma
  silently stripped *from inside the string* when merging a commented (JSONC)
  client config. The trailing-comma pass is now string-aware (mirroring the
  comment stripper), so string contents are never altered while real trailing
  commas are still removed. Added regression tests covering string values that
  contain `, }` / `, ]`. (Dropped the now-unused `re` import.)

## What's New in v2.54.2

A destructive-overwrite bug in the installer (issue #71): the MCP client setup
step could wipe a user's entire editor settings file instead of merging into it.

- **Fixed** `install.py` silently destroyed existing client config files whose
  contents weren't strict JSON. `read_json` swallowed `JSONDecodeError` and
  returned `{}`, so the subsequent "merge" wrote a file containing *only* the
  `davinci-resolve` server entry — wiping themes, terminal env vars, LSP
  settings, keybindings, everything else. Zed was the reported victim because
  its `settings.json` ships with `//` comments (JSONC), but the same latent
  risk existed for **every** supported client — VS Code and Continue also accept
  JSONC. The fix is centralized in the single read/merge path so all clients are
  covered:
  - `read_json` now best-effort strips JSONC `//` and `/* */` comments and
    trailing commas (string-aware, so comment markers inside string values are
    preserved), letting commented configs merge cleanly instead of being lost.
  - When a config file exists but still can't be parsed after that, the
    installer **refuses to overwrite it** and tells the user to add the entry
    manually — rather than silently replacing their settings.
- **Added** regression tests covering JSONC merge, plain-JSON merge,
  refuse-to-overwrite on unparseable files, fresh-file creation, and
  string-aware comment stripping.

## What's New in v2.54.1

One more instance of the enum-keyed silent-failure class (issue #70), plus a
guard so the next one can't ship unnoticed.

- **Fixed** the raw `timeline.export` action passed `type`/`subtype` straight to
  `Timeline.Export`, which needs resolved `resolve.EXPORT_*` enum *values* — a
  JSON/MCP caller can't pass a live enum, so the action silently wrote nothing
  for every caller. It now resolves friendly format names (and `EXPORT_*`
  constant names) via the same `_timeline_export_spec` resolver that
  `export_timeline_checked` uses, and reports the resolved `export_type`/
  `export_subtype`.
- **Fixed** `export_timeline_checked` resolved enum constants against the module
  global `resolve` (which can be `None` and silently degrade the `EXPORT_*` args
  to strings); it now uses `get_resolve()`, matching the issue-#70 lesson.
- **Added** an `api_truth` ↔ mitigation guard test: every `enum`-tagged catalog
  entry must declare a `mitigation` (the resolver/wrapper functions), each of
  which must exist in `src.server`. The next raw enum passthrough — a documented
  symbol with no real resolver, or a renamed/removed resolver — now fails CI.
  Added a `Timeline.Export` catalog entry and wired `mitigation` onto the
  `AutoSyncAudio`, `CreateSubtitlesFromAudio`, and CloudProject entries.

## What's New in v2.54.0

Hardens the rest of the enum-keyed settings APIs against the same silent-failure
class fixed for `AutoSyncAudio` in v2.53.0 (issue #70). Several Resolve methods
key their settings dict by `resolve.<CONST>` enum attributes and silently reject
the whole call when handed plain string keys — returning `False`/`None` with
nothing applied and no error.

- **Fixed** `CreateSubtitlesFromAudio` (both `timeline_ai.create_subtitles` and
  `timeline.subtitle_generation_probe`) now resolves human-readable
  `autoCaptionSettings` — `language`, `preset`, `line_break`, `chars_per_line`,
  `gap` — into live `SUBTITLE_*`/`AUTO_CAPTION_*` enum keys/values. Unknown keys
  and unresolvable values are dropped and reported in `ignored_settings` instead
  of poisoning the call, and generation is read-back verified against the
  timeline's subtitle track count (the boolean return is unreliable).
- **Fixed** the `ProjectManager` CloudProject family (`create`/`load`/
  `import_project`/`restore`) resolves `{cloudSettings}` into live
  `CLOUD_SETTING_*`/`CLOUD_SYNC_*` enums (`project_name`, `media_path`,
  `is_collab`, `sync_mode`, `is_camera_access`), dropping unknown keys into
  `ignored_settings`.
- **Changed** the string→enum resolution is now a shared `_resolve_enum_settings`
  primitive driven by per-field specs, so the next enum-keyed API gets the same
  treatment without re-implementing it.
- **Added** `api_truth` entries for `Timeline.CreateSubtitlesFromAudio` and the
  CloudProject family, documenting the silent-rejection + unreliable-return
  behavior alongside the existing `AutoSyncAudio` entry.

## What's New in v2.53.0

Two improvements to audio sync reliability and inventory control.

`safe_auto_sync_audio` / `media_pool.auto_sync_audio` no longer fail silently on
human-readable settings (issue #70). The previous normalizer recognized
`syncBy`/`mode` but not `method`, and it forwarded *every* unrecognized key
(`group_id`, `primary_clip_id`, …) straight into `MediaPool.AutoSyncAudio` —
which silently rejects the whole call when it sees a key it doesn't understand,
returning `False` with nothing linked and no error.

- **Fixed** `method` (matching the tool's own parameter naming) is now accepted
  as an alias for the sync mode alongside `syncBy`/`sync_by`/`mode`/`syncMode`.
- **Fixed** unrecognized settings keys are dropped instead of forwarded, so a
  stray `group_id`/`primary_clip_id` no longer poisons the call. Dropped keys
  are reported back in a new `ignored_settings` field on the response, so a
  rejection is no longer invisible.
- **Fixed** the raw `media_pool.auto_sync_audio` action now routes settings
  through the same live `AUDIO_SYNC_*` enum resolution as the safe wrapper
  (previously it passed strings straight through).

The Media Pool inventory walk is now configurable:

- **Added** `media_analysis.inventory_exclude_bins` — a comma-separated list of
  folder names to skip entirely during the inventory walk (recursively). Empty
  by default, so every folder is indexed unless you opt out.
- **Added** `media_analysis.inventory_limit` — the maximum clips to index per
  walk, configurable from the control panel and `setup`. The hard ceiling is
  raised from 2000 to 10000.
- Adapted from PR #69 by @rgxdev; the default was changed to exclude nothing
  (the PR defaulted to excluding an `assets` bin, which would have silently
  stopped indexing existing `assets` folders on upgrade).

## What's New in v2.52.1

Analysis reuse no longer blocks on missing capabilities when every clip is
satisfied by an existing report (issue #68). `build_plan` records
`capability_gaps` from the *requested* options before the per-clip reuse
decision runs; when a fully-reused plan only re-keys and imports existing
reports into the current root, no fresh transcription/vision/ffprobe happens,
so the missing-capability gate must not fire.

- **Fixed** the missing-capability gate is now evaluated against the clips that
  still need fresh analysis, not the requested-options gaps. A clip is exempt
  only when it both skips execution and has an existing report path; any clip
  needing fresh work still enforces the gate.
- **Fixed** extended the exemption to the entry points that short-circuit
  before `execute_plan_async` and were still blocking fully-reused runs: the
  `media_analysis` analyze action, metadata-publish analysis, and batch-job
  creation. The batch CLI `plan` preview no longer prints "Missing tools" for a
  fully-reusable plan.
- **Changed** the reuse/capability logic is now a shared
  `plan_requires_capabilities()` / `executing_clips()` helper, replacing the
  duplicated inline comprehensions so every gate stays consistent.
- Includes PR #68 by @diesdaas, which fixed the inner `execute_plan_async` gate
  and isolated the marker-param and host-vision tests from unrelated
  capability/destructive-hook coupling.

## What's New in v2.52.0

`edit_engine` tighten now carries audio. Previously `execute_tighten`
assembled a video-only variant — a speech-driven dead-air cut came out
silent, with nothing in the preview or readback to warn you (issue #67).

- **Fixed** `plan_tighten` mirrors every kept video range onto its linked
  audio track(s) with identical source frames, so the assembled variant
  stays frame-locked and audible. Audio targets the item's detected linked
  audio tracks (same `GetLinkedItems` matching `execute_swap` uses), falling
  back to audio track 1 where a single linked A/V clip's audio lives.
- **Added** `include_audio` parameter to `plan_tighten` (default `true`).
  Pass `include_audio=false` for the prior video-only assembly.
- **Added** an `audio_accounting` block to the `execute_tighten` confirm
  preview and readback (planned vs. actual audio/video item counts), so a
  silent variant can no longer ship unnoticed. Old video-only plans
  re-executed against this build still work and are now loudly flagged as
  silent.

## What's New in v2.51.0

CLAP audio embeddings — the final phase of the post-program improvements.
Detection-based like every other backend (never auto-installed); local
compute, so nothing touches the caps ledger.

- **Added** audio embedding backend detection: CLAP via `transformers`
  (laion/clap-htsat-unfused, preferred) or the `laion_clap` package, plus
  torch + ffmpeg. `capabilities` gains an `audio` block with install
  guidance and a `clap_audio` Tools-page entry.
- **Added** `build_embeddings(kinds=["audio"])`: one CLAP window per shot
  (center-cropped to ~10 s, piped from the source media as raw PCM —
  read-only on source media, no temp files) plus a clip-level mean vector,
  stored as `embedding_kind="audio"` rows. Idempotent via content hashes;
  offline media is reported in `skipped_missing_media`; a missing backend
  is a graceful skip with install guidance.
- **Added** `find_similar(kind="audio")`: shot/clip queries over the audio
  vectors, and free-text queries ("engine revving") via the CLAP text
  encoder.

## What's New in v2.50.0

The last JSON-fed readers now source from the DB-canonical analysis store
(consistency/perf hygiene — the JSON export is lockstep with the DB, so this
is shape-preserving by construction).

- **Changed** `summarize_reports` aggregates from the DB (blob + human
  overlay) when every report dir on disk is covered by an ingested clip row;
  pre-v9 roots and MIXED roots (some clips not ingested) fall back WHOLESALE
  to the JSON walk — a partial DB view would silently under-report. The
  summary gains a `"source": "db"|"json"` key for observability; the F1
  provenance map (source_reports / missing_reports) is unchanged.
- **Changed** `build_analysis_index` sources local reports from the DB
  instead of re-parsing every `analysis.json`; job-linked EXTERNAL report
  paths (their rows live under another project's DB) and pre-v9 dirs keep
  the JSON read. The FTS schema and the query surface are identical; the
  result gains `report_sources` counts.
- **Added** DB-vs-JSON parity tests (semantic equality with normalized
  ordering) plus wholesale-fallback regressions for mixed and pre-v9 roots;
  live-validated on the sample analysis root (summary, index counts, and
  FTS query results identical on both paths).

## What's New in v2.49.0

Cross-shot relationships (spec §4 — pattern recognition only): the shot
page's Relationships group finally fills, and the edit engine can prefer
vision-confirmed alternates.

- **Added** schema v12 `shot_relationships` (same_setup_as / alt_take_of
  symmetric, continues_from directional — the source shot continues from
  the target) with supersede semantics (current rows have
  `superseded_at IS NULL`).
- **Added** `media_analysis` actions `detect_shot_relationships` /
  `commit_shot_relationships` / `list_shot_relationships`: pairwise cosine
  over the per-shot visual vectors (transcript continuity as a second
  signal for continues_from) → a deferred confirmation payload with a
  representative frame PAIR per candidate (caps pre-checked; candidates
  live only in the detection-state stash until committed, so re-detect
  never leaves ghosts) → vision-confirmed rows. Representative frames use
  the shot's middle sample (first/last frames often catch fades).
- **Added** the shot page's Relationships group now renders from the DB
  (`continues_from` shows on the continuing shot; cross-clip targets are
  clip-qualified).
- **Changed** `plan_swap` prefers confirmed `alt_take_of` alternates over
  raw cosine similarity — confirmed takes sort first (and are unioned in
  even when the cosine search missed them); each alternate's rationale
  states which basis ranked it.

## What's New in v2.48.1

Bug fix surfaced by the first real-cut tighten pilot.

- **Fixed** cross-root analysis reuse never landed in the current project's
  DB: when the registry matched a reusable report from another project's
  analysis root, `execute_plan_async` reported success but wrote no DB rows
  and no local export — so `media_ref` lookups against the current media
  pool (edit-engine planners, panel readers) found nothing. The reuse path
  now re-keys the report to the current project's clip identity, ingests it
  into the current root's DB, and writes a lockstep `analysis.json` export
  (provenance kept in `reused_from`).

## What's New in v2.48.0

Edit-engine hardening: trustworthy execute readback ahead of the first
real-cut pilot. Live-validated end-to-end on a disposable synthetic-media
project (24/24 checks).

- **Added** `timeline_versioning(action="diff_timelines", params={from_timeline,
  to_timeline})`: structural diff (added/removed/moved/trimmed + summary)
  between two LIVE timelines by name — read-only, no archived snapshots
  needed. Built for edit-engine variants, which are new-name timelines with
  no shared version chain. The item walk and the snapshot comparison were
  factored out of the version-snapshot path
  (`capture_timeline_clip_usage` / `compare_usage_snapshots`) and reused.
- **Fixed** `execute_swap` audio accounting: the lift was video-only while
  the replacement appended linked video+audio, so item counts drifted on
  every swap. The lift is now scoped to the target's video track plus its
  linked audio tracks (`GetLinkedItems`, with a media-id track-scan fallback;
  items with no linked audio and audio-only timelines are handled
  gracefully), and readback reports per-track-type `track_counts`
  before/after plus an `audio_accounting` block.
- **Added** `execute_tighten` readback now includes `structural_diff`
  (source vs variant); `execute_selects` readback includes a
  `usage_summary` (per-track-type item counts — a diff against a source
  timeline is meaningless for a fresh assembly).
- **Changed** the live edit-engine validation harness asserts the tighten
  structural diff, `diff_timelines` agreement, and swap track-count
  symmetry (24 checks, up from 20).

## What's New in v2.47.0

Edit-engine plan browser in the control panel (Media → Edit Plans) — the
panel UX pass for the v2.45.0 edit engine. Chat-first: the panel surfaces
plans and evidence; execution stays in chat behind the confirm-token gate.

- **Added** a plan browser at `#analysis/review/plans`: every saved
  `edit_engine` plan with kind, summary, save time, and an `executed` chip;
  fingerprint-corrupt plans surface as warning rows instead of being hidden.
- **Added** plan detail views per kind: selects decisions render with shot
  thumbnails, rank, duration, rationale, and a deep link to the shot page;
  tighten plans list each dead-air lift with its transcript-gap evidence and
  skipped items; swap plans show the current item plus numbered alternates
  with similarity scores. Executed plans show their execution readback.
- **Added** a copyable per-kind execute chat prompt on each plan (the panel
  never executes; swaps include an `alternate_index` placeholder).
- **Added** `/api/edit_plans` + `/api/edit_plans/<plan_id>` panel endpoints
  (DB/file only — no Resolve round-trips; decisions are enriched server-side
  with `resolve_clip_id` and a `thumb_frame_index` for the existing frames
  route).
- **Changed** `edit_engine.list_plans` gained `include_corrupt` (default off;
  the MCP action shape is unchanged).

## What's New in v2.46.1

Test and hygiene hardening; no public tool surface changes.

- **Fixed** the three `InventoryCacheReuseTests` failures that appeared
  whenever a live Resolve instance was running: the reuse/build-path tests
  now stub the read-only Resolve probe, so the suite is green with Resolve
  open or closed.
- **Added** `src/utils/project_cleanup.delete_project_safely`: a retrying
  delete helper for disposable Resolve projects (switch away from the target,
  retry `DeleteProject` once after a pause, report the leftover by name on
  persistent failure). The live edit-engine validation harness now uses it
  during cleanup, so disposable pilot projects stop lingering in the library.

## What's New in v2.46.0

Community PR bundle: five contributed fixes and features (#62–#66), live-validated
on Resolve Studio 21.

- **Fixed** timeline marker frames are now correctly relative to the timeline
  start (#66): timecode params and the playhead default rebase by
  `GetStartFrame()`, so markers on hour-start timelines land where the UI
  shows them instead of an hour past the end. Raw `frame` params pass through
  unchanged (documented as relative). Contact sheets and marker thumbnail
  review rebase the other way with a legacy-absolute guard.
- **Fixed** project lint no longer flags audio-only timelines as empty (#62);
  live lint state now reports per-type `video/audio/subtitle_item_count`.
- **Added** `media_pool.check_proxy_media_compatibility` (#63): ffprobe-vs-source
  signature diagnostics (resolution/fps/frames/sample rate, expected
  codec/profile). Same-aspect downscales count as compatible — half-res
  proxies are the normal workflow.
- **Added** readback verification envelopes (`verified_operation`) around
  `media_pool.link_proxy_checked` (#63) and `media_pool.append_to_timeline`
  (#64): preflight, execution, post-state readback, verification status, and a
  journal event. `link_proxy_checked` gains `check_compatibility` /
  `require_compatible` guards that refuse incompatible proxies before linking.
- **Added** `bins` to declarative project specs (#65): missing media-pool bin
  paths plan as `ensure` actions and are created idempotently; existing bins
  are noops. Bin paths normalize to the `Master/` prefix so unprefixed spec
  bins converge instead of reporting perpetual drift.

## What's New in v2.45.0

The edit engine — Phase E, the final phase of the analysis + edit-engine
program. Three evidence-driven loops on one shared skeleton: evidence query
→ dry-run plan with per-decision rationale → confirm token → versioned
timeline ops → metric readback → brain_edits rows.

- **Added** a new `edit_engine` MCP tool (compound tool count: 34):
  - `plan_selects` / `execute_selects` — ranks shots by deep-tier
    `editorial.select_potential` and best moments (clip-level fallback for
    standard-analyzed clips), story-spine order, duration budget; execution
    builds a NEW selects timeline from per-shot source ranges. Additive.
  - `plan_tighten` / `execute_tighten` — dead-air lifts from transcript-gap
    evidence per timeline item (no transcript → reported in `skipped`,
    never silently trimmed); execution assembles a tightened VARIANT
    timeline from keep ranges (true partial trims via the range-copy
    kernel) — the original timeline is never mutated.
  - `plan_swap` / `execute_swap` — alternates for a timeline item via the
    visual-similarity index, filtered to shots that can fill the slot
    exactly; execution replaces the item in place (lift + positioned
    append) on the version-archived timeline.
  - `list_plans` / `get_plan` — plans persist under `memory/edit_plans/`
    with content fingerprints; a stale or tampered plan refuses to execute.
- **Added** `src/utils/edit_engine.py` (DB-only planning/evidence layer) and
  `tests/live_edit_engine_validation.py` (disposable-project live harness).
  execute_* actions are confirm-token gated and registered with the
  version-on-mutate hook (archive + brain_edits come from the same
  machinery as every other destructive op).
- **Fixed** frame→shot mapping in the analysis store: frames now fall back
  to time-containment when a report's shots don't record
  `frame_indices_used` (commit paths that omit it previously produced no
  shot-level visual vectors).
- **Validation**: full offline suite (1118 tests; 13 new). Live pilot on a
  disposable synthetic-media Resolve project (ffmpeg + spoken audio):
  20/20 checks — selects timeline assembled (2 decisions), tighten variant
  removed exactly the 15.2s of transcript dead air while keeping the
  spoken 4.8s (original untouched), swap replaced the item with a 0.92
  cosine alternate, brain_edits rationale rows present for all three
  loops, timeline versions archived.

## What's New in v2.44.0

Cross-clip entities + bin briefing v2 — Phase D of the analysis +
edit-engine program. Recurring people/places/props found by clustering the
visual embeddings, confirmed with one vision call per cluster.

- **Added** schema v11 (`entities` + `entity_appearances`) and
  `src/utils/entities.py`: union-find clustering over the v10 CLIP frame
  vectors (cosine threshold, no new deps), representative-frame selection,
  ghost pruning across re-runs (labeled entities persist), and a
  detection-state stash so `entity_index` always resolves against the exact
  ordering the payload was issued with.
- **Added** `media_analysis` actions: `detect_entities` (clusters + deferred
  one-frame-per-cluster confirmation payload, caps pre-checked),
  `commit_entities` (kind/label/description with conservative-label rules;
  `merge_with` collapses duplicate clusters), `list_entities`,
  `prepare_bin_briefing` (entities + per-clip summaries, text-only), and
  `commit_bin_summary` (host-synthesized briefing written above the v2.0
  aggregate in `memory/bin_summary.md`).
- **Added** a "Recurring across this bin" card on the panel's Review page
  (`/api/entities`), shown once labeled entities exist.
- **Validation**: full offline suite (1105 tests; 10 new). Live on the real
  sample root: 3 clusters detected from 16 CLIP vectors; host-chat
  confirmation labeled the shattered-windshield POV and the white rental
  sedan and merged the sedan's two clusters; bin briefing synthesized and
  committed; panel card verified and screenshots regenerated.

## What's New in v2.43.0

Embeddings + similarity search — Phase C of the analysis + edit-engine
program. "Find clips/shots like this," locally, with no vendor token cost.

- **Added** `src/utils/embeddings.py` and schema v10 (`embeddings` table:
  one float32 vector per entity/kind/model, with content hashes so re-runs
  only re-embed what changed). Brute-force cosine — numpy when present.
- **Added** `media_analysis` actions `build_embeddings` (idempotent; clip
  summaries, shot descriptions + deep field groups, transcript segments,
  sampled frames with per-shot mean vectors) and `find_similar` (query by
  free text, clip, or shot; `kind="text"|"visual"`; free-text visual queries
  go through the CLIP text encoder).
- **Added** backend detection, never installation (the whisper pattern):
  text = ollama `nomic-embed-text` (serving probe) or sentence-transformers;
  visual = open_clip ViT-B-32. Capabilities and the Diagnostics → Tools page
  list availability with install guidance.
- **Added** a `Semantic` toggle on the panel's Review search (shown only
  when a text backend is detected) backed by `/api/search/semantic`, which
  returns rows in the existing search-card shape.
- **Validation**: full offline suite (1095 tests; 14 new, backends mocked).
  Live on the 2026-05-17 sample root: 54 text vectors in 1.2s via ollama
  with correct top hits for three editorial queries; 27 CLIP vectors with
  "cracked broken windshield glass" ranking the shattered-windshield frame
  first; panel endpoint verified and screenshots regenerated.

## What's New in v2.42.0

Deep shot-level vision tier — Phase B of the analysis + edit-engine program.
Opt-in, estimate-first per-shot field filling for the Visual / Content /
Production / Editorial / Cuttability groups the shot pages already render.

- **Added** `src/utils/deep_vision.py` and three `media_analysis` actions:
  `deepen` (estimate → confirm_token → deferred host-vision payload per
  clip/shot), `commit_shot_vision` (writes `vision_deep_v1` provenance rows,
  updates the canonical blob, re-exports analysis.json in lockstep), and
  `vision_pending_sweep` (lists clips stuck in `pending_host_analysis`;
  `reoffer=true` returns the stored payload, `expire=true` stamps them).
- **Added** deep depth to the analyze flow: `depth="deep"` extends the
  deferred payload with the per-shot schema and requires `confirm_deep=true`
  after a token-cost estimate. Caps pre-call refusal applies on both paths.
- **Added** panel affordances: `Deepen analysis` (clip view) and `Deepen this
  shot` (shot view) copy ready-made chat prompts, per the chat-first UX.
  Shots with no sampled frames on disk get 1–2 frames re-extracted via
  ffmpeg, downscaled per caps (source media stays read-only).
- **Fixed** a provenance bug in the analysis store: a source re-deriving an
  unchanged value no longer re-attributes the row (a deep pass would
  otherwise claim every untouched field as `vision_deep_v1`).
- **Validation**: full offline suite (1081 tests; 15 new), and a real
  end-to-end deep pass on the 2026-05-17 sample clip — estimate → confirm →
  frames read by the host chat → commit → rows/blob/export parity → fields
  visible in the panel shot view. Control-panel guide screenshots
  regenerated from the live panel.

## What's New in v2.41.0

DB-canonical clip analysis (C1) — Phase A of the analysis + edit-engine
program. The per-project SQLite DB is now the source of truth for clip
analysis; `analysis.json` becomes a derived export written in lockstep.

- **Added** schema v9 to the per-project timeline-brain DB: `clips`,
  `clip_aliases`, `analysis_reports` (canonical full payload), `shots`,
  `subjective_fields` + `field_changelog` (per-field provenance),
  `transcript_segments`, `frames`, and `qc_observations`.
- **Added** `src/utils/analysis_store.py`: transactional ingest, export with
  human-correction overlay (human rows always win and survive re-analysis),
  alias-based clip lookup, shot ids stable under one-second boundary jitter,
  and a round-trip guard verified against a real sample analysis root.
- **Added** `media_analysis` actions `db_status` (schema version + row
  counts) and `db_ingest` (one-shot migration of existing JSON reports and
  `corrections.json` sidecars into the DB).
- **Changed** the analysis write path: `execute_plan` and `commit_vision`
  write DB rows first, then export the JSON. Panel clip/shot endpoints read
  DB-first with JSON fallback for pre-v9 reports and job-linked report dirs.
- **Changed** `update_clip_field` / `update_shot_field` / `revert_field` to
  mirror corrections into the DB as row-level provenance (the
  `corrections.json` sidecar remains for compatibility).
- **Fixed** eight V2 actions that were unreachable from MCP dispatch since
  v2.24.0 (`get_panel_state`, `set_panel_state`, `session_start_context`,
  `update_shot_field`, `update_clip_field`, `get_field_history`,
  `revert_field`, `list_corrections`): they were checked inside the
  project-root dispatch block but missing from its membership set. The
  control panel proxied to the helpers directly, which masked it.
- **Fixed** the action-list drift guard to inspect async tool functions
  (media_analysis had drifted unchecked) and to fail on actions that are
  unreachable inside membership blocks — the exact class above. Four
  reachable-but-unadvertised actions (`coverage_report`,
  `get_resolve_ai_usage`, `get_ai_governance`, `set_ai_governance`) are now
  listed in the unknown-action error.
- **Validation**: full offline suite (1066 tests; 12 new), round-trip guard
  on the real 2026-05-17 sample root, and a live headless pipeline run on
  synthetic media verifying rows-then-export parity, row-level corrections,
  and DB-first panel reads.

## What's New in v2.40.0

Control panel UX overhaul + docs refresh, from a full live audit of every
panel view, with drift guards so neither can silently go stale again.

- **Added** a governance mode toggle (Advisory / Enforce) to the AI Console,
  with corrected copy (the old text predated v2.39.0 enforce mode), and a
  Recent-runs list on the AI-ops ledger showing each run's actor.
- **Added** chat-first onboarding: empty Overview, Review, and Inventory
  states show plain-language guidance with a copyable suggested prompt
  instead of zero-walls and MCP action names.
- **Added** History as a first-class Media menu item, deep-linkable at
  `#analysis/review/history`; documented the full hash deep-link scheme.
- **Changed** the top-level "Analysis" menu to "Media" (it collided with the
  Preferences page of the same name); "Analyze" is now "Inventory". Full
  vocabulary pass: humanized readiness chips and frame-sampling labels, no
  internal codenames, file names, or absolute paths in UI copy.
- **Fixed** the README's linked screenshot rendering broken in the Docs
  reader: badge parsing no longer claims local linked images, and a new
  `/api/doc_asset/` route serves repo doc images (path-constrained).
- **Fixed** poll hygiene: timers pause while the tab is hidden, panel-state
  polling backs off when unfocused, and unchanged inventory polls return a
  tiny 200 instead of a 304 that Chrome logged as an aborted request.
- **Docs**: `docs/guides/control-panel.md` fully rewritten for the current
  IA with all screenshots regenerated from the live panel
  (`scripts/regen_panel_screenshots.py`). A new drift-guard test fails the
  suite — and the publish workflow, which now runs all three static guards
  on every tag — when the guide drifts from the panel's navigation or
  screenshots.

## What's New in v2.39.0

Governance enforce mode and actor identity — the staged Phase 3 of the
Resolve 21 AI-ops work.

- **Added** governance `mode` for the media-creating AI ops (motion deblur,
  speech generation): `advisory` (default, unchanged — confirm-preview
  warnings only) or `enforce`, where an over-tier run is blocked with
  `GOVERNANCE_BLOCKED` before token issuance, naming the exceeded dimensions.
  Escape hatches: raise the tier, relax the mode, or pass
  `override_governance=true` to consciously exceed the tier once.
  `set_ai_governance` accepts `mode` (preset now optional);
  `get_ai_governance` reports it.
- **Added** instance-level actor identity (per the recorded concurrency
  design): each entry point declares itself — `stdio`, `network-sse`,
  `network-http`, `control-panel`, `batch-cli` — and AI-ops ledger rows,
  brain edits, and timeline versions now carry `actor` (`<instance>:<pid>`)
  alongside `initiator`. Schema v8 (additive columns); migration verified
  against a copy of a real project DB with all rows preserved.

## What's New in v2.38.0

Busy gate for long DaVinci Resolve operations — the first piece of the
concurrency design for the stdio + networked two-instance setup.

- **Added** cross-process registration for long synchronous Resolve calls
  (timeline export/import, scene-cut detection, subtitle generation,
  Dolby Vision analysis, folder/clip audio transcription). A tool call that
  arrives while one is running now waits up to 5 seconds and then returns a
  structured `RESOLVE_BUSY` error (new `busy` category, retryable, with
  `state.busy_with` and `state.age_seconds`) instead of hanging silently
  inside the scripting bridge. Stale registrations from crashed operations
  are ignored automatically; an operation never gates its own thread.
- Design decisions recorded: single-editor/multi-client is the supported
  concurrency target; confirm tokens stay per-instance; actor identity is
  deferred to the governance phase.

## What's New in v2.37.3

Deep-audit fixes, rounds two and three: agent-facing action discovery,
crash-safe user-state persistence, and resource hygiene.

- **Fixed** three tools' unknown-action error lists drifting from their real
  dispatch: `timeline` omitted `clip_where` and `action_help`;
  `timeline_item_color` and `graph` omitted `action_help`. Agents recovering
  from a typo now see the full action set. A static AST test keeps every
  tool's advertised list in both-way sync with its dispatch (and verifies
  docstring-advertised actions are real).
- **Fixed** user-state files being vulnerable to truncation by a crash
  mid-write. Affected files all reset to `{}` on corruption, so the next
  save would silently wipe remaining user data. Writers now use atomic
  temp-file + `os.replace`: `media-analysis-preferences.json` (all
  analysis/caps/governance/update defaults — including the
  `set_resolution_tier` and `set_caps_preset` paths, now routed through the
  shared writer), `update-check.json`, the dashboard's `analysis.json`
  transcription patch, and `transcript-corrections.json`.
- **Fixed** `_safe_project_delete` discarding `SaveProject()`'s result when
  closing the current project before deletion; a failed save now surfaces
  as a warning in the response.
- **Fixed** a file-descriptor leak: the parent kept its copy of the control
  panel's log handle open after spawning the detached child.
- Audit classes verified clean: bare excepts, mutable default arguments,
  `asyncio.run` inside running loops, subprocess timeouts, docstring phantom
  actions, silent-success swallows in metadata/marker/archive write paths.

## What's New in v2.37.2

Static-audit fixes — four undefined-name references that silently fell back
to defaults instead of erroring (the same bug class as the v2.37.0
confirm-token fix), plus a regression guard.

- **Fixed** the `status://mcp_version` resource reporting update channel
  `"stable"` unconditionally; it now calls the real `get_update_channel()`,
  so beta/dev channel installs report correctly.
- **Fixed** the `versioning_auto_run_idle_timeout_seconds` preference being
  silently ignored (auto-run idle timeout was always 90s) due to a
  misspelled preference-reader name in the destructive hook.
- **Fixed** resolve-state snapshot tokens always falling back to a timestamp
  because `short_hash` was never imported; tokens are now content-stable.
- **Fixed** the timeline-kernel live probe's MCP-stub fallback crashing with
  a `NameError` (missing `types` import) exactly when the mcp library is
  absent — the only case the fallback exists for.
- **Added** a static test that runs pyflakes over `src/` and fails on any
  undefined name, so this bug class cannot reappear unnoticed.

## What's New in v2.37.1

Test-suite hygiene — no server behavior changed.

- **Fixed** the legacy live-harness scripts (`test_all_tools`, `test_phase2`–`5`)
  exiting at import when Resolve is unavailable, which crashed pytest
  collection and surfaced as five loader errors under unittest discovery.
  They now skip cleanly under both runners and keep the hard-exit behavior
  when run as standalone scripts. (Adapted from a contribution by @diesdaas.)
- **Fixed** pytest mis-collecting `test_resolve20_api.py`'s internal `test()`
  helper (renamed to `run_live_check()`), and made the batch-CLI synthetic-job
  test independent of which transcription backends the host has installed.
- **CI**: the npm publish workflow no longer reports failure when the registry
  accepted the publish but npm's retried request hit a consumed OIDC token;
  it now verifies the published tarball shasum before failing. Runner actions
  bumped to their Node 24 majors.

## What's New in v2.37.0

Render format-id fix, offline-media diagnosis, and a setup doctor.

- **Fixed** render helpers passing the display name from `GetRenderFormats()`
  (e.g. `QuickTime`) into `GetRenderCodecs`, `GetRenderResolutions`, and
  `SetCurrentRenderFormatAndCodec`, which expect the format id (e.g. `mov`).
  `GetRenderCodecs("QuickTime")` returned empty, so `probe_render_matrix`
  reported no QuickTime codecs and `prepare_render_job` could not target
  ProRes (e.g. `ProRes422LT` proxy renders). Display names and format ids are
  now both accepted as input and normalized to the id for Resolve API calls;
  `probe_render_matrix` rows include `format_id`. Closes #59.
- **Fixed** the destructive confirm-token gate referencing a stale function
  name, which made it silently ignore the `destructive.require_confirm_token`
  preference and always fall back to the default.
- **Added** a `diagnosis` block to `timeline.detect_missing_media`:
  deduplicated missing Media Pool items, volume/folder mounted checks, a
  primary cause (`volume_not_mounted` / `folder_not_found` /
  `files_missing_or_renamed`), and a recommended next step. Optional
  `sanitized`/`sanitize_paths` redacts raw media paths.
- **Added** bounds to `timeline.build_relink_plan`: skips the broad scan by
  default when a source volume (e.g. a camera card) is not mounted, dedupes
  missing basenames, and caps the search with `max_depth`, `max_seconds`
  (default 20s), and `max_files_scanned` (default 50k), reporting per-candidate
  scan stats.
- **Fixed** `media_analysis` accepting `vision: true/false` boolean shorthand
  (now normalized to the full options dict) and `timeline_markers.get_thumbnail`
  returning a structured error instead of raw `None` when no thumbnail is
  available.
- **Added** `scripts/doctor.py`, a read-only setup diagnostic that checks the
  checkout, Python, Resolve app/scripting paths, and MCP client configs, and
  probes the scripting bridge end to end with OK/WARN/FAIL output (`--json`
  supported).

## What's New in v2.36.1

Bug fix — restore the `fusion_comp` MCP tool.

- **Fixed** a regression from `32be0ec` (v2.33.0) that left `fusion_comp`
  unregistered: a new `_parse_pos` helper was inserted between the `@mcp.tool()`
  decorator and `def fusion_comp`, so the decorator landed on the private helper
  instead. As a result `_parse_pos` was exposed as a tool while **all**
  `fusion_comp` node-graph operations (`add_tool`, `connect`, `add_keyframe`,
  `get_keyframes`, `copy_tool`, `set_position`, …) were missing from the tool
  list. The decorator is restored to `fusion_comp` and `_parse_pos` is once
  again a plain internal helper. Live-validated on DaVinci Resolve Studio 21.

## What's New in v2.36.0

Optional networked transport — run the MCP server over the network, safely, with
control-panel management. Local stdio remains the default and is unchanged.

- **Added** `--transport stdio|sse|streamable-http` (default `stdio`). The networked
  modes bind to **loopback (127.0.0.1) by default** and **require a bearer token** on
  every request (from `$DAVINCI_MCP_TOKEN`, or generated + logged at startup). A
  non-loopback bind logs a loud security warning. stdio is untouched; you can run a
  local stdio instance and a networked instance against the same Resolve at once.
- **Added** control-panel management (Setup → MCP): a Transport card showing the live
  mode / URL / token / loopback status, with Start/Stop buttons (loopback-only). Backed
  by `/api/mcp/transport/{start,stop}` and a transport field on `/api/mcp/status`.
- The page-switch lock (v2.34.1) already serializes concurrent page switches across the
  local and networked instances.

## What's New in v2.35.2

Verification observability and a validator consolidation.

- **Added** `resolve_control(action="verification_stats")` returns a
  process-level tally of readback-verification outcomes
  (verified / contradicted / unverified) since server start. A rising
  `contradicted` count means the Resolve API reported success but a readback
  disagreed. No connection required.
- **Changed** `open_page` now validates its `page` argument through the declarative
  contract layer (`contracts.validate`) instead of a hand-written enum check —
  behavior unchanged; part of folding scattered validation into one place.

## What's New in v2.35.1

- **Added** `media_pool_item(action="extract_frames", clip_id, timestamps, output_dir?)`
  extracts still JPEGs from a clip's source media at the given timestamps (seconds)
  via ffmpeg. Source-safe: it reads the source and writes only to a scratch output
  directory — it never modifies, transcodes, or proxies the source. (Closes a
  read/write-symmetry gap: the analysis sampler existed internally but had no
  standalone frame-extraction tool.)

## What's New in v2.35.0

The Cut-IR executor — transcript-driven editing now closes the loop onto the
timeline.

- **Added** `timeline(action="apply_cuts", cuts, dry_run?, confirm_token?)` applies
  a CutList (from `propose_cuts`) to the timeline as lift / ripple deletes. It is
  **DRY-RUN by default**; applying is destructive and fully governed: confirm-token
  gated, and a timeline version is archived first (so it is reversible), through
  the existing destructive hook. Cuts apply latest-first so ripple deletes do not
  invalidate earlier spans. Live-validated end-to-end (propose -> token -> apply ->
  version archived).

## What's New in v2.34.1

Page-switch serialization — the concurrency primitive for safe multi-agent use.

- **Added** `src/utils/page_lock.py` — Resolve has a single globally-active page,
  so two agents that flip pages concurrently corrupt each other. `page_lock()`
  serializes page switches: a reentrant intra-process lock plus a best-effort
  inter-process advisory file lock around the outermost section. The `open_page`
  action now routes through it. This must be in place before any concurrent-agent
  feature ships.
- Networked transport, sandboxed scripting, and capability/role scoping (the rest
  of the safe remote/multi-user design) are security-critical and remain a
  separate, sign-off-gated phase — they are intentionally not shipped here.

## What's New in v2.34.0

First phase of transcript-driven editing: a Cut intermediate representation and a
mechanical cut proposer.

- **Added** `src/utils/cut_ir.py` — the Cut-IR: a typed representation of an
  editorial cut ({kind, span, action, confidence, rationale, evidence}) plus a
  deterministic Pass-1 detector that flags filler words, long pauses, and
  repeated lines from a timestamped transcript. No LLM.
- **Added** `timeline(action="propose_cuts", cues?, long_pause_frames?)` — a
  DRY-RUN that runs Pass-1 over the timeline's subtitle transcript (or provided
  cues) and returns a CutList. It proposes only; it applies nothing. The semantic
  Pass-2 and the governed timeline executor are subsequent phases.

## What's New in v2.33.8

Bridge-call performance instrumentation.

- **Added** `src/utils/bridge_metrics.py` — a counting proxy that wraps a Resolve
  handle and tallies attribute accesses and method calls (each a COM/socket
  round-trip), so the real bridge cost of an operation is measured rather than
  guessed.
- **Added** `scripts/measure_bridge_cost.py` — runs a representative media-pool
  traversal through the proxy and reports round-trips per clip. A minimal
  name+type walk measured ~6.7 round-trips per clip, confirming round-trips scale
  linearly with traversal size. A property cache remains gated on profiling
  *repeated*-read patterns in real workflows (don't cache blind).

## What's New in v2.33.7

Read/write symmetry audit and a gap it surfaced.

- **Added** `scripts/audit_readwrite_symmetry.py` + generated
  `docs/reference/readwrite-symmetry.md` — scans every tool's action surface and
  reports `set_`/`add_`/`create_` writes that lack a read counterpart, so
  write-without-read gaps surface before users hit them. A repeatable
  feature-discovery method.
- **Added** `fusion_comp(action="get_frame_range")` — reads the comp's render
  frame range, the read counterpart to `set_frame_range` (a gap the audit found).

## What's New in v2.33.6

Internal consolidation: a declarative parameter-contract validator and centralized
subprocess hygiene.

- **Added** `src/utils/contracts.py` `validate(params, rules, invariants)` — one
  validator for required/type/enum/min/max/non-empty/parent-dir-exists plus custom
  invariants, returning consistent agent-friendly errors with coercion + defaults
  applied. Replaces scattered, hand-written validation.
- **Changed** `export_frame_as_still` and `set_mark_in_out` (clip + timeline) now
  validate through contracts. Behavior is preserved (same rejections); `mark_in`/
  `mark_out` are now coerced to int.
- **Added** `src/utils/proc.py` `safe_run`/`safe_popen` — subprocess wrappers that
  default `stdin` to DEVNULL so a child can't consume the MCP stdio protocol
  stream. Inline Python execution now routes through `safe_run`.

## What's New in v2.33.5

A queryable ledger of verified Resolve API behavior.

- **Added** `resolve_control(action="api_truth", query?)` returns
  behaviorally-verified facts about quirky or unreliable Resolve scripting-API
  behavior — methods that live on unexpected objects, return values that lie,
  silently-rejected string keys, and calls that don't exist. Each fact records
  the reality, a recommended approach, and the Resolve build it was verified on.
  No connection required. Backed by `src/utils/api_truth.py`, seeded from
  hard-won findings (AutoSyncAudio, Fusion Paste, FlowView positions,
  GetTimelineByName, project render methods, transcription truncation, the
  CreateProject modal, stdio subprocess hygiene) and meant to grow over time.

## What's New in v2.33.4

Internal reliability framework.

- **Added** `verify_by_readback` (`src/utils/readback.py`) — a primitive for
  mutating Resolve ops that verifies an action by reading the real post-state
  back instead of trusting the API's frequently-unreliable return value. A
  contradiction (reported success but a failing readback) is logged as a
  reliability signal.
- **Changed** Auto-sync audio now runs through `verify_by_readback` as its first
  user and reports a `verified` field alongside `linked`/`newly_linked`. Behavior
  is unchanged; the bespoke readback loop is replaced by the shared primitive.

## What's New in v2.33.3

Two read tools that surface existing project state.

- **Added** `project_settings(action="project_summary")` returns a live
  structural readout — current page, timeline count and current timeline, and a
  media-pool inventory (folder/clip counts, clips by type, optional clip
  sample). A cheap "what's in this project right now" snapshot that needs no
  prior analysis.
- **Added** `timeline(action="get_transcript")` reads the current timeline's
  subtitle track(s) as transcript text `{text, cue_count, has_subtitles, cues}`,
  with optional per-cue timecodes. Complements the clip-level
  `get_transcription`.

## What's New in v2.33.2

Documentation: a guide for hand-authoring DaVinci Resolve `.setting` template
files.

- **Added** `docs/authoring/setting-files/` — how to author Edit effects,
  transitions, titles, generators, and Fusion macros as `.setting` files: the
  Lua-table format, the `InstanceInput`/`UserControls` control catalog, thumbnail
  conventions, Templates install paths, and a set of hard-won gotchas (ordered
  vs unordered `Inputs`, `ControlGroup` anchoring, transition easing via
  `LUTLookup`, `KeyStretcher` on titles, the category-subfolder rule, OFX
  boilerplate, and more). Includes 13 copyable starter templates and is linked
  from `docs/SKILL.md`.

## What's New in v2.33.1

Clip transcription read-back and more trustworthy auto-sync reporting.

- **Added** `media_pool_item(action="get_transcription")` returns
  `{text, truncated, status, has_transcription}`. Transcription could previously
  be triggered but never read back. Resolve's `Transcription` clip property is a
  preview that ends in an ellipsis when the full transcript is longer, so
  `truncated` tells callers the returned text is partial.
- **Changed** Auto-sync audio now verifies linkage by reading each clip's
  `Synced Audio` property before and after the call and reporting
  `linked` / `newly_linked` / `already_linked`, instead of trusting
  `AutoSyncAudio`'s unreliable boolean. The boolean is still returned as
  `success`, but callers should trust `linked`.

## What's New in v2.33.0

Fusion node-graph layout and duplication, plus performance and robustness
improvements across the compound server. Live-validated on DaVinci Resolve
Studio 21.0.0.

### Fusion node layout & duplication

- **Added** `fusion_comp(action="get_position")` and `set_position` — read and
  write a node's position on the FlowView canvas. `set_position` confirms the
  move by reading the position back.
- **Added** `fusion_comp(action="copy_tool")` — duplicate a node, optionally
  renaming and repositioning it. Settings are carried through a temporary
  `.setting` file, which round-trips reliably across the Python bridge where the
  in-memory `SaveSettings()`/`Paste()` table form fails.
- **Added** `fusion_comp(action="auto_arrange")` — lay tools out in a row
  (`direction="horizontal"`) or column (`"vertical"`) at a given spacing.

### Performance

- **Changed** Resolve object inspection walks `dir(obj)` once instead of once for
  methods and again for properties, skips `inspect.signature()` for C-extension
  methods (slow and almost always raising there), and reads `__doc__` directly.
  Each attribute access on a Resolve object is a bridge round-trip, so this
  roughly halves inspection cost on the `resolve_control` path.
- **Changed** Media-pool find-by-name lookups walk the folder tree lazily and
  stop at the first match instead of materializing the entire project tree.

### Robustness & fixes

- **Fixed** `export_frame_as_still` rejects an empty path or a nonexistent target
  directory instead of silently returning failure.
- **Fixed** `set_mark_in_out` (clip and timeline) rejects `mark_in > mark_out`.
- **Fixed** Auto-sync audio resolves `AUDIO_SYNC_*` enum constants via the live
  Resolve handle, closing a path where a stale module handle silently degraded
  `AutoSyncAudio` to rejected string keys.
- **Changed** Every `subprocess` call that can run while the MCP stdio server is
  active now sets `stdin=subprocess.DEVNULL`, so a child process cannot consume
  bytes from the JSON-RPC protocol stream; the spec-hook runner also captures its
  child's output. Applies to both the compound and granular launchers.

## What's New in v2.32.2

Fixes `fusion_comp(action="get_keyframes")` serialization.

The handler iterated `Input.GetKeyFrames()` as if it returned `{time: value}`,
but Fusion returns `{1-based index: frame_position}`. The result put the
keyframe **index** in `time` and the **frame position** in `value` — the actual
keyframed values were never reported.

The handler now treats the dict values as frame positions and reads each
keyframed value back via `GetInput(input_name, frame)`.

- **Fixed** `get_keyframes` now returns `[{"time": <frame>, "value": <value>}, ...]`
  in frame order (live-validated on DaVinci Resolve Studio 21.0.0:
  `Size` keyed `1.0@f0` / `1.4@f75` → `[{0.0: 1.0}, {75.0: 1.4}]`).
- Follow-up to the `add_keyframe` fix in v2.32.1; flagged by @sandypoli-boop in #56.

## What's New in v2.32.1

Fixes `fusion_comp(action="add_keyframe")` so it actually **animates** the input.

Previously the handler did `inp[time] = value` on the input directly. On an input
with no animation spline, that only assigns a **static** value (last write wins) —
no keyframe is created. Symptoms: `get_keyframes` returned `[]`, `get_input` at
different times returned the same value, and the clip never animated.

The handler now attaches a `BezierSpline` modifier the first time an input is
animated, then sets the keyframe. A new optional `modifier` param lets callers
pass e.g. `"Path"` for Point inputs such as `Center`. Behavior is unchanged for
inputs that are already animated or otherwise connected.

- **Fixed** `add_keyframe` now creates real, editable keyframes (live-validated on
  DaVinci Resolve Studio 21.0.0).
- **Added** optional `modifier` param to `add_keyframe`.
- Thanks to @sandypoli-boop for the diagnosis and fix ([#56](https://github.com/samuelgursky/davinci-resolve-mcp/pull/56)).

## What's New in v2.32.0

Adds **governance tiers** for the media-creating Resolve 21 AI ops (Phase 3, the
final phase of the AI-ops build: ledger → console → governance).

The two ops that render new files — `remove_motion_blur` and `generate_speech` —
now have **soft, per-session limits** chosen by a named tier:

| dimension | off | lenient | standard | strict |
|---|---|---|---|---|
| deblur runs | ∞ | 50 | 15 | 5 |
| speech runs | ∞ | 50 | 15 | 5 |
| media created | ∞ | 50 GB | 10 GB | 2 GB |
| render time | ∞ | 1 h | 20 min | 5 min |

Governance is **advisory** — it never hard-blocks (the ops are already
confirm-token gated). When you're near or over the active tier, the confirmation
dialog surfaces a warning before you proceed; the limits are computed from the
v2.30.0 AI-ops ledger for the current session.

- **New module** `src/utils/resolve_ai_governance.py` — tiers + `check()` (status
  for the next run) + `status()` (session usage vs tier). Default tier: `standard`.
- **New MCP actions** `media_analysis(action="get_ai_governance")` and
  `media_analysis(action="set_ai_governance", preset, overrides?)`. Override keys:
  `deblur_runs`, `speech_runs`, `render_bytes`, `render_wall_clock_ms` (int or `"unlimited"`).
- **Confirm preview** for the two creators now carries a `governance` block
  (current usage, projected, warnings, exceeded/near flags).
- **Control panel** — the AI Console gains a **Governance** section: a tier picker
  (off/lenient/standard/strict, with each tier's thresholds) plus live
  consumption gauges, and the confirm dialog shows the warning inline.

This completes the staged AI-ops build. Validated live against Resolve Studio
21.0.0.47 (tier switching, persistence, gauges, confirm-dialog warnings).

## What's New in v2.31.0

Adds the **AI Console** to the control panel — an interactive surface for the
Resolve 21 local AI operations (Phase 2 of the staged AI-ops build: ledger →
console → governance).

A new **AI Console** tab runs the 21.0 ops against the current Media Pool folder
or a specific clip:

- **Capability matrix** — shows which AI methods this Resolve build exposes (green
  = available, grey = absent on older builds) and which Extra each gated method
  needs to actually run.
- **Analysis** — Classify audio / Clear classification, IntelliSearch (with
  identify-faces and Better-mode toggles), Analyze for slate (16-color marker
  picker), Transcribe (with speaker-detection toggle), Clear transcription.
- **Motion deblur** and **Speech generator** — full options forms; because both
  create new media files they route through a confirmation modal (the same
  confirm-token gate the MCP tools use) before running.
- **Session** — Disable background tasks for the current Resolve session.
- A live result readout, and the *Resolve 21 AI ops* ledger refreshes after each
  run so file/byte totals stay current.

Backend: a loopback-only `POST /api/resolve_ai/run` endpoint dispatches each op
to the consolidated `folder` / `media_pool_item` / `project_settings` /
`resolve_control` tools, relaying the confirm-token two-step. No new MCP tools or
Resolve API surface — the console reuses the existing v2.29.0 actions. Validated
live end-to-end against Resolve Studio 21.0.0.47.

## What's New in v2.30.0

Adds the **Resolve 21 AI-ops ledger** — usage/time/file accounting for the
Resolve-local AI operations added in v2.29.0 (audio classification, IntelliSearch,
slate, motion-deblur, speech generation). These run on Resolve's own GPU/AI engine
and do **not** consume the Claude-side analysis token budget, so they get their
own ledger instead of being metered by the analysis-caps layer.

**What's tracked.** Every run of the five 21.0 ops records: op name, op class
(`analysis` vs `render`), clip id, success/failure, wall-clock time, and — for the
two media-creating ops (`remove_motion_blur`, `generate_speech`) — the output
file path and byte size. The reliable signal is invocation counts + the
file/disk accounting for the creators; durations for the bool-returning analysis
ops reflect the script-call time (some queue work inside Resolve).

- **New table** `resolve_ai_op_usage` (timeline_brain DB schema v7).
- **New module** `src/utils/resolve_ai_ledger.py` — `timed()` context manager +
  `record_op` / `get_usage` / `get_summary`. All writes are best-effort and never
  block or mask the underlying Resolve op.
- **Instrumentation** wraps the consolidated `folder` / `media_pool_item`
  `perform_audio_classification` / `clear_audio_classification` /
  `analyze_for_intellisearch` / `analyze_for_slate` / `remove_motion_blur`
  handlers and `project_settings.generate_speech`.
- **New MCP action** `media_analysis(action="get_resolve_ai_usage", session_only?, op?, limit?)`
  returns the per-op summary + recent runs.
- **Control panel**: a read-only "Resolve 21 AI ops" card (`/api/resolve_ai_usage`)
  shows runs, success/fail, total time, and files/bytes created.

Phase 1 of a staged build (ledger → interactive console → governance). Granular
`--full` server instrumentation is deferred — the ledger covers the consolidated
server, which is the default surface. Validated live against Resolve Studio 21.0.0.47.

## What's New in v2.29.0

Adds the **DaVinci Resolve 21.0** scripting-API additions. Every new method is
runtime-detected (`_requires_method`/capability flags), so the tools stay inert
on older Resolve builds and activate automatically on Resolve 21+.

**New AI analysis actions** on the `folder` and `media_pool_item` compound tools
(and mirrored as granular `--full` tools):

- `perform_audio_classification` / `clear_audio_classification` — classify clip
  audio into categories and subcategories.
- `analyze_for_intellisearch(identify_faces?, is_better_mode?)` — IntelliSearch
  analysis with optional face identification. Requires the *AI IntelliSearch* Extra.
- `analyze_for_slate(marker_color?)` — slate/clapboard detection that drops a
  marker of the chosen color (validated against the 16 Resolve marker colors).
  Requires the *AI Slate ID* Extra.
- `remove_motion_blur(deblur_option?)` — renders motion-deblurred copies. This
  **creates new media files** (source media is never modified) and is therefore
  **confirm-token gated**: the first call returns a preview + token, the second
  call (with the token) runs.

**Speaker-detection transcription.** `transcribe_audio` now accepts an optional
`use_speaker_detection` boolean (Resolve 21+); omit it to use the project's
Speech Recognition setting.

**Speech generation.** `project_settings(action="generate_speech", ...)` wraps
`Project.GenerateSpeech` (AI text-to-speech). It creates a new audio item and
optionally places it on the timeline, so it is also confirm-token gated.
Requires the *AI Speech Generator* Extra. Granular `--full` tool: `generate_speech`.

**Session control.** `resolve_control(action="disable_background_tasks_for_current_session")`
wraps `Resolve.DisableBackgroundTasksForCurrentResolveSession()` to quiet
background work during heavy scripted runs.

**Capability surface.** The `media_analysis` transcription-capability report and
the control panel's boot payload (`resolve.ai_features`) now list which 21.0 AI
methods are available and which Extras each gated method needs.

Notes: these are Resolve-local GPU/AI operations and do not consume the
Claude-side analysis token budget, so they are not metered by the analysis-caps
layer; the derivative-creating ones are protected by the confirm-token gate
instead. The granular `--full` server grew from 329 to 341 tools.

## What's New in v2.28.1

Bug-fix release.

**Audio transcription no longer passes an invalid `language` argument.** The
`transcribe_audio` (clip) and `transcribe_folder_audio` tools in the full
(`--full`) server were calling `TranscribeAudio(language)` with a language
string, but the Resolve scripting API has never accepted a language positional —
its signature is `TranscribeAudio(useSpeakerDetection=None)`. The string was
silently coerced to a truthy boolean and misread as a speaker-detection flag,
and the success message falsely claimed a transcription language. The language
is controlled by the project's Speech Recognition setting, not per call.

- `transcribe_audio(clip_name, use_speaker_detection=None)` — the `language`
  parameter is replaced with an optional `use_speaker_detection` boolean
  (Resolve 21+). Omit it to use the project's setting.
- `transcribe_folder_audio(folder_name, use_speaker_detection=None)` — same
  change for the folder-level tool.
- Both pass the boolean through only when supplied, so older Resolve builds
  (which take no argument) keep working.

The consolidated 32-tool server was unaffected — its `folder`/`media_pool_item`
`transcribe_audio` actions already called `TranscribeAudio()` correctly.

## What's New in v2.28.0

This release adds a structural timeline-diff engine, a declarative project spec
you can `apply` like infrastructure-as-code, a project health `lint`, a clip
query DSL, and a machine-readable `state` field on error responses.

**Timeline version diff — see exactly what an edit changed.** Comparing two
archived timeline versions now reports clips that were **added, removed, moved,
and trimmed**, plus summary counts and before/after clip totals. A new reusable
diff engine aligns clips by a rename-stable identity (so a reordered or renamed
clip reads as a move/change, not a delete-and-re-add).

- `timeline_versioning(action="diff_versions", timeline_name, from_version, to_version)`
  now returns `{added, removed, moved, trimmed, summary}` (the previous
  `added`/`removed`/`moved` keys are unchanged).
- Dashboard endpoint `GET /api/timeline_versions/diff?timeline_name=&from_version=&to_version=`
  exposes the same diff to the control panel.

**Declarative project spec + `apply` — reproducible project setup.** Describe a
project's desired settings, color preset, timelines, and markers in a
`project.dvr.yaml` (or `.json`), then reconcile the live project toward it. Runs
are **idempotent** — applying twice is a no-op — and a dry run previews every
change before anything is touched.

- New MCP actions on `project_manager`:
  - `diff_to_spec(spec_path | spec)` — preview drift without mutating.
  - `plan_spec(spec_path | spec)` — the ordered action list (dry run).
  - `apply_spec(spec_path | spec, dry_run?, run_hooks?, continue_on_error?)` —
    reconcile. Color/HDR settings apply in dependency order; markers are only
    added when absent; an explicit `color_preset` can be overridden by explicit
    `settings`. Failures can abort on first error or accumulate.
- New headless CLI commands: `davinci-resolve-mcp batch plan-spec SPEC` and
  `davinci-resolve-mcp batch apply SPEC [--dry-run] [--run-hooks] [--continue-on-error]`.
  Exit codes follow the existing convention (`0` ok, `2` partial, `3` fatal).
- Optional before/after shell **hooks** in the spec run only when `run_hooks` is
  passed (opt-in).

**Project health `lint` — a pre-flight before editing.** `project_manager(action="lint")`
returns a graded issue list (errors / warnings / info) covering: no project, no
current timeline, mixed frame rates across timelines, empty timelines, unset
render format, unmanaged color science, offline media, and unanalyzed clips.

**Clip query DSL — find clips in one call.** `timeline(action="clip_where", ...)`
returns the clips on the current timeline matching named filters (AND), instead
of enumerating tracks by hand. Live filters: `track_type`, `track_index`,
`name_contains`, `duration_lt`, `duration_gt`. A typo'd filter name is rejected
rather than silently matching everything.

**Machine-readable error context.** Structured error responses can now carry an
optional `state` object — a snapshot of the relevant values at failure time
(e.g. which filter was unknown, which spec failed and where) — so an agent can
react without parsing prose. Existing error fields are unchanged.

## What's New in v2.27.2

**Control panel under-counted analyzed clips after a Media Pool rename (issue
#51)** — with every clip analyzed (e.g. 303/303 reports on disk), the overview
and Media tab could report something like "108 / 303 analyzed". The panel only
recognized a report when a folder's name exactly matched the clip's *current*
display name, so renaming clips after analysis hid their existing reports even
though the underlying media was unchanged.

Root cause and fix:

- **Lookups are keyed by a rename-stable hash, not the display-name folder.**
  Report folders are named `<display-slug>-<hash>`; the count now matches on the
  trailing hash (and the ids inside each report), so a renamed clip still
  resolves to its existing folder. Both the disk path and the jobs-DB fallback
  were corrected.
- **The hash is now anchored to the normalized file path (canonical basis).**
  Previously the basis was a `clip_id`-first cascade, so the same media hashed
  differently depending on which fields a record carried — Resolve inventory
  (clip_id) vs path-based batch jobs (file path) disagreed on the same clip.
  Anchoring to the file path removes that cross-basis mismatch. Legacy folders
  (clip_id-based, or raw-path-based) still resolve via a migration-safe set of
  candidate hashes, so **no on-disk migration is required**.
- **Writes reuse an existing report folder** (matched by canonical or legacy
  hash) instead of minting a new `<newslug>-<hash>` directory, eliminating
  orphaned duplicate folders when a renamed clip is re-analyzed.
- **A persisted clip index (`clips/index.json`)** maps every stable id found in
  a report (normalized + raw file path, clip_id, media_id) to its folder, so the
  count can still match a clip by any id it carries — including an offline clip
  that no longer reports a file path but retains its clip_id. The index is
  refreshed only when a report is added, removed, or rewritten (cheap signature
  check), so the recurring poll stays inexpensive.

No public MCP tool surface changed. Adds regression tests in
`tests/test_media_analysis.py` covering rename, cross-basis, legacy-folder reuse,
the jobs-DB fallback, and the offline/no-path case.

## What's New in v2.27.1

**Faster control-panel startup with network source media (issue #50)** — on
first open the control panel could sit on "connection pending" for a long time
when Media Pool clips lived on mounted network storage, because the UI only
treated the connection as live once the full media inventory finished loading,
and that inventory probed every clip's file path on disk.

Fixes and performance work:

- **Connection state is decoupled from the media inventory.** The overview and
  diagnostics panels now derive "connected" from the `/api/boot` handshake (which
  returns as soon as the Resolve bridge is reachable) and show inventory loading
  separately, so Resolve reads as live immediately while clips stream in.
- **Parallel, cached file-existence probing.** `os.path.exists` for every clip
  now runs in a thread pool and is memoized for a short TTL, instead of two serial
  `stat()` calls per clip — the dominant cost on network storage.
- **Background polls reuse the cached Media Pool walk.** The recurring poll no
  longer re-runs the ~N serial `GetClipProperty` calls; it reuses the last walk
  and re-applies only the local, disk-backed analysis-status overlay. A cheap
  project-id check still catches a project switched directly in Resolve, and a
  manual refresh always does a full walk.
- **Resolve scripting API access is serialized.** A re-entrant lock guards every
  scripting-API entry point, since the dashboard's threaded HTTP server could
  previously fire concurrent (thread-unsafe) Resolve calls at startup.
- **ETag/304 on the inventory endpoint** skips transfer and table re-render when
  nothing changed; the last good inventory is cached client-side and painted
  instantly on reload; and the first inventory build is warmed in a background
  thread at server start.

No public MCP tool surface changed. Adds regression tests in
`tests/test_media_analysis.py` (path-existence probing, inventory cache reuse,
project-switch detection, lock reentrancy).

## What's New in v2.27.0

**Frame-sampling modes (issue #46)** — how many frames a clip gets for visual
analysis is now governed by a `sampling_mode`, decoupled from `depth` (which
still controls which layers run). A fixed frame count over-sampled short clips
and under-covered long ones; the demand-driven engine already scaled by
duration/content, but the caps layer was flat-truncating its output back to 8
frames — that flat cap was the real cause of long-clip under-coverage.

Four clearly-tiered modes, organized so token cost is predictable per tier:

- **Economy** (`fixed`) — flat N evenly-spaced, content-blind frames. Cheapest and
  most predictable; good for proxies/triage.
- **Balanced** (`per_minute`) — `clamp(minutes × frames_per_minute, floor, ceiling)`
  (defaults 4/min, 3–80). Cost is linear in footage length; content-blind.
- **Thorough** (`adaptive_capped`, recommended/default) — content-aware: samples
  shot boundaries, representatives, and flash candidates, bounded to `[floor,
  ceiling]`. Best coverage with a bounded cost.
- **Thorough (uncapped)** (`adaptive`) — content-aware with no per-clip ceiling
  (up to the 512-frame hard cap). Use only when clips are short or few.

The first time you analyze without a saved default, the tool returns a
`confirmation_required` response with a `sampling_mode_prompt`; choosing a mode
saves it as your standing default (mirrors `timed_markers_default`). Pass
`sampling_mode` per call any time for a one-off that doesn't change the default.
Tunables (`frames_per_minute`, `frame_floor`, `frame_ceiling`) and the mode are
all exposed in the control panel (Preferences → Frame sampling mode) with a live
per-clip token-cost estimate; batch jobs honor the saved default.

Analysis-caps presets were retuned so `frames_per_clip` is now a *safety ceiling*
(minimal/standard/generous = 12/80/200), not the primary frame dial, and the
per-clip/job/day vision-token caps were raised so the default Thorough mode isn't
refused by the per-clip token cap. Cache reuse re-samples only when switching up
the thoroughness rank; a richer prior report still satisfies a cheaper mode. Adds
`tests/test_sampling_modes.py` (30 tests). Validated end-to-end on a synthetic
multi-shot clip with real ffmpeg frame extraction.

## What's New in v2.26.1

**Python 3.13 / 3.14 support (issue #45)** — `npx davinci-resolve-mcp setup`
previously hard-refused any interpreter outside 3.10–3.12, so it failed outright
on Python 3.14. The 3.12 ceiling was based on a stale assumption that Resolve's
scripting bridge has ABI incompatibilities on 3.13+. Verified empirically against
DaVinci Resolve Studio 20.3.2.9: Python 3.14.4 connects and exercises the
dict/list marshalling paths cleanly. The launcher and installer now enforce only
the 3.10 floor (the `mcp[cli]` SDK requirement) with no upper cap. Python 3.13/3.14
are accepted with a soft heads-up; `setup`/`doctor` surface a precise,
connection-aware hint only when Resolve is running but the bridge returns no
connection on 3.13+. Sub-3.10 interpreters get an actionable error instead of a
dead end. `server.py` warns (never exits) on 3.13+. Adds 6 version-gate unit tests.

## What's New in v2.26.0

**Fusion group-settings helpers** — Three new `fusion_comp` actions for
authoring and patching `GroupOperator` macros without leaving the kernel.
`group_settings_export` writes a live group to a `.setting` file and returns a
parsed `published_inputs` summary using a balanced-brace walker so nested
`UserControls` / `ControlGroup` tables are bounded correctly (the original
flat-regex parser truncated `InstanceInput` bodies at the first inner `}`).
`group_settings_splice_inputs` replaces the `Inputs = ordered() { ... }` block
of one `.setting` with the matching block from another, preserving the source's
outer structure and inner `Tools`. `group_settings_load` applies a `.setting`
to a live group with an automatic timestamped backup, wrapped in
`StartUndo`/`Lock`/`LoadSettings`/`Unlock`/`EndUndo(True)` so Fusion's Ctrl+Z
reverses the change — verified live via direct BMD API.

**bulk_set_expressions** — Companion to the existing `bulk_set_inputs`. Batch
attach Fusion expressions across many timeline-item comps in one call. Each op
requires timeline scope plus `tool_name`, `input_name`, `expression`. Returns
per-op `success`/`error` rows + `op_count`, matching the bulk-inputs contract.
Useful for animating many controls at once (`time/30`, etc.) under a single
chat turn.

**Headless batch-runner CLI** — New
`davinci-resolve-mcp batch <plan|run|status|list|resume|cancel>` subcommand
drives `src/utils/media_analysis_jobs` from outside an MCP/chat client so long
analysis batches can run via cron, CI, or terminal without holding a chat turn
open. The orchestration loop and durable state stay in the existing jobs
engine; the CLI only handles argv, progress streaming, and exit codes
(`0` ok / `2` partial / `3` fatal / `130` Ctrl+C). JSON mode (`--json`)
emits one record per progress event for log scraping. Closes #42.

**Adapted from PR #40** — Group-settings work originated as a contribution
from @RaincloudTheDragon; PR #43 retains the keepable parts (parser, exporter,
splicer, loader, `bulk_set_expressions`) with a balanced-brace fix on the
parser and an undo+lock wrap on `group_settings_load`. The two AMZ-specific
templates and the static checklist from #40 were dropped as out-of-scope for a
general kernel.

## What's New in v2.25.0

**Agentic flow improvements** — A second-pass review against the Claude
Certified Architect study material drove a sweep of correctness gains. Every
tool error now returns a structured envelope (`code` / `category` /
`retryable` / `reason` / `remediation` / `message`); `retryable` defaults are
locked per category so a host can make a one-shot retry decision without
inference. Compound-tool descriptions for `media_analysis` and
`timeline_item_color` adopt XML semantic tags (`<when_to_use>`, `<actions>`,
`<returns>`) for cheaper per-turn parsing. Repeated failures on the same
`(scope, action)` pair attach an `escalation` block on the 3rd response —
halts auto-retry loops with a `suggested_action` for the host. Batch
manifests now always carry `partial_success`, `completed_clip_ids`, and
`failed_clip_ids` for safe targeted retry.

**MCP resources surface** — 8 read-only resource URIs the host can poll
without paying a tool-turn cost: `status://mcp_version`,
`status://resolve_connection`, `status://current_project`,
`status://current_timeline`, `status://caps_preset`,
`analysis://recent_reports`, `capabilities://installed_tools`,
`capabilities://install_guidance`. Paired tools still work for hosts that
don't consume resources.

**MCP prompts surface** — 5 slash-command workflow templates:
`/davinci-resolve:analyze_and_propose_grade`,
`/davinci-resolve:match_bin_to_hero`,
`/davinci-resolve:verify_timeline_coverage`,
`/davinci-resolve:open_and_analyze_selection`,
`/davinci-resolve:prep_color_handoff`. First-class agentic intent, no
re-derivation from SKILL.md prose.

**Color-grading evidence base** — `timeline_item_color.grade_evidence_base`
composes `version_snapshot` + `node_graph` + `color_group` + coverage report
into a single `evidence_base` summary string; the SKILL guide now teaches
agents to lead any color recommendation with that line.
`timeline_item_color.propose_grade` formalizes a recommendation as a
validated structured plan (returns `plan_id` + `preview_path`; requires
explicit `execute=true` re-call). `bulk_match_to_hero` drives CDL-delta or
copy-grade across many targets with a `confirm_token` gate and dry-run
preview.

**Analysis caps layer** — Token-budget governance for analysis. 7 cap
dimensions across vision/transcription/job/clip/day scopes, 4 named presets
(`minimal` / `standard` / `generous` / `unlimited`), pre-call refusal with
`CAPS_REFUSAL` / `budget_exhausted` / `retryable: false`. New
`media_analysis` actions: `get_caps`, `set_caps_preset`. Token usage table
in the analysis DB plus a control-panel widget with gauges + override
inputs. Wall-clock timeout helper wraps vision/transcription call sites.

**Timeline versioning + analysis↔timeline marriage** — New
`timeline_versioning` MCP tool: every destructive timeline edit
auto-archives the current timeline into an Archive bin (compound, captions,
ripple, gap close, etc.), so versions can be diffed and rolled back. Run
scoping, schema v4 migrations, concurrency safety, structural snapshots,
action filtering, strict mode, auto-save preference, media-pool destructive
coverage, thumbnails. Backed by new modules `timeline_versioning.py`,
`timeline_brain_db.py`, `brain_edits.py`, `analysis_runs.py`,
`media_pool_changes.py`, `destructive_hook.py`. Surfaced in the control
panel's Review → History view.

**Async opt-in for long-running ops** — `analyze_clip` / `analyze_file` /
`commit_vision` accept `prefer_handle: true`. When set (and the estimated
runtime exceeds the configured threshold), the response is a fast handoff
with `job_id` + `status: "queued"`; poll `batch_job_status({job_id})`.
Default behavior unchanged.

**Aggregated provenance** — `summarize`,
`review_timeline_markers`, and `grade_evidence_base` now return a
`provenance` block: `source_reports[]` (clip_id, signature, report_path,
analyzed_at), `missing_reports[]` (per reason: `no_report` / `stale_report`
/ `caps_refused`), and inline `[ref:<clip_id>]` citations in the human
summary text. Multi-clip claims are now traceable.

**Confirm-token gates on destructive batches** — `propose_grade`,
`bulk_match_to_hero`, and other multi-target writes now require an explicit
`confirm_token` on first execute (returned on the dry-run), with a
`pending_user_decision` error if missing.

**Action-help indirection** — `action_help(name=...)` returns the long-form
guidance for a single action, keeping the top-level tool descriptions
compact while preserving full per-action documentation.

**Tool-choice hint emission** — Analyze responses include a
`host_tool_choice_hint` block. Hosts that respect it pass
`tool_choice={type:"tool", name:"media_analysis"}` on the next API turn,
hard-locking the agent into the correct next call.

**Update process hardening** — Five improvements layered onto the
update-check path: active-job lock prevents updates mid-analysis, auto-stash
strategy preserves uncommitted work across updates, restart-needed marker
surfaces to the host, channels (`stable` / `beta` / `dev`), pre-update
breaking-change scan, integrity SHA verification of downloaded artifacts,
update history table, eager DB migration on update, and rollback to the
previous build. New `analysis_caps.py` + `update_check.py` revisions.

**Source-safe guardrails** — `destructive_hook.py` + decorator coverage
tests ensure every destructive surface goes through the auto-archive path
and never modifies, transcodes, or creates derivatives of source media.

**Test surface** — 30+ new test modules covering error envelopes,
failure tracking, partial-success manifests, `prefer_handle`, MCP resources,
MCP prompts, provenance, XML description shape, `action_help`,
`grade_evidence_base`, `propose_grade`, `bulk_match_to_hero`,
`confirm_token`, the analysis caps layer, caps integration / events /
history, timeline versioning, the timeline-brain DB, destructive decorator
coverage, the destructive hook, update hardening, and update history.

**Validation** — `tests/test_import.py`, `scripts/audit_api_parity.py`,
`node bin/davinci-resolve-mcp.mjs --version`, `npm pack --dry-run`, and
`git diff --check` all pass. 375 focused unit tests pass. Live Resolve
validation covered the D1–F2 surface end-to-end against a live production
project / Timeline 7 (D1 `retryable`, D2 XML descriptions, D3 partial-success on
plans + CAPS_REFUSAL manifests, E1 8 MCP resource URIs, E2 escalation on
3× repeated failure, E3 `prefer_handle` job handoff with
`batch_job_status` polling, F1 provenance block) — 6/6 PASS on the
fourteenth-attempt smoke test. No source media was modified.

## What's New in v2.24.1

**`npx davinci-resolve-mcp` no longer breaks MCP clients when invoked without a
subcommand.** The npm bootstrapper previously defaulted to `--help`, which wrote
usage text to stdout and exited 0. MCP stdio clients (Hermes Agent, Claude
Desktop, Cursor, etc.) read that as malformed JSON-RPC, retried three times,
then dropped the connection. `bin/davinci-resolve-mcp.mjs` now defaults to the
`server` subcommand when no arguments are supplied. Explicit `--help`, `-h`,
`help`, `--version`, and `-v` continue to print to stdout as before, and
existing configs that already pass `server` explicitly are unaffected. Reported
in [#41](https://github.com/samuelgursky/davinci-resolve-mcp/issues/41).

## What's New in v2.24.0

**Host-chat vision protocol (V2)** — `analyze_*` actions now use
`vision.provider="host_chat_paths"` by default. The analyze response is a
deferred payload with absolute `frame_paths`, a per-shot `shot_table`, and a
JSON schema; the host chat reads each frame as a local image, produces JSON per
the schema, and calls `media_analysis(action="commit_vision", params={clip_id,
visual, vision_token})` to finalize. `commit_vision` merges the visual report,
rebuilds Media Pool clip markers, publishes metadata to Resolve, and preserves
human corrections via `corrections.json`. Skipping the commit leaves the run in
`pending_host_vision_analysis` — surfaced explicitly rather than silently
downgraded. The legacy `chat_context`/`mcp_sampling` providers still resolve to
the same host-chat path.

**Trust-by-default analysis defaults** — `analyze_media` defaults to
`include_transcription=true`, `persist=true`, `publish_metadata=true`, and
`timed_markers="ask"` so source-safe no longer means underpowered. Agents that
need a technical-only or read-only run must explicitly pass
`include_visuals=false`, `include_transcription=false`, `publish_metadata=false`,
`timed_markers="no"`, `session_only=true`, or `dry_run=true`. The
`analyze_media` prompt and SKILL.md spell out the anti-regression rule.

**Control panel: Review surface (Phase B)** — The local browser control panel
gains a Review tab backed by new endpoints: `/api/clips`, `/api/clips/<id>`,
`/api/clips/<id>/shots`, `/api/clips/<id>/shots/<index>`,
`/api/clips/<id>/frames/<n>`, `/api/clips/<id>/transcript`,
`/api/clips/<id>/corrections`, `/api/clips/combined`, `/api/clips/export`,
`/api/panel_state`, `/api/update/status`, `/api/update/apply`, and
`/api/resolve/open_clip`. The UI ships a bin grid with thumbnails, a clip
detail with shot strip, a shot detail with grouped V2 fields + frame grid,
inline correction editors per subjective field, transcript correction +
regeneration, an Open-in-Resolve bridge, and 2-second chat ↔ panel state
polling.

**Control panel MCP actions** — `resolve_control.open_control_panel`,
`control_panel_status`, and `close_control_panel` manage the local panel
subprocess via a pidfile. `save_state` / `restore_state` snapshot and restore
Resolve playhead + selection state. `get_panel_state`, `set_panel_state`, and
`session_start_context` share panel focus between chat and the UI through
`panel_state.json`.

**Correction tools** — New `media_analysis` actions for editing analysis
without re-running it: `update_shot_field`, `update_clip_field`,
`get_field_history`, `revert_field`, `list_corrections`. Writes land in
`{clip_dir}/corrections.json` with append-only changelog + provenance
(mirrors the V2 DB schema). `commit_vision` merges corrections on top of the
fresh visual report so human edits survive re-analysis.

**Media Pool item open-in-viewer** — `media_pool_item.open_in_viewer` selects
a clip on the Media page and loads it into the source viewer, optionally
setting mark in/out and bringing Resolve to the foreground via OS-level
window activation. Useful for chat → Resolve hand-off.

**Source-trust prompt grading** — `source_trust` parameter
(`auto`/`filename`/`low`/`medium`/`high`) on analyze actions tunes the vision
prompt to hedge identity/intent/value for archival or thin-evidence clips.

**Analysis memory layer** — New `src/utils/analysis_memory.py` introduces
per-project memory + heartbeat + bin summary + soul scaffolding under the
analysis root. `regenerate_bin_summary_from_manifest` aggregates per-clip
fields (primary use, select potential, style, energy arc, top tags/locations)
into a bin briefing. Auto-initialized on analyze.

**Control-panel polish** — Diagnostics + Overview restyled with a status-pill
design system, navbar dropdowns fixed so top-level buttons no longer navigate
on their own, Preferences consolidated (Dashboard Convenience + Storage pages
removed), summary-style enum renamed to `full`/`concise`/`creative`/
`technical` with backwards compat, navbar version badge + update modal,
source-trust dropdown wired through.

**Server-side bug fixes** — `commit_vision` auto-publish now reflects per-row
status correctly (no silent-lie pending), compact analyze responses by default
(`verbose: true` for the full manifest), `resolve_output_root` skips slug
append when the configured base already terminates in the slug, frame sampler
reserves per-shot budget so shot starts aren't starved by flash candidates,
and machine markers are no longer written to Resolve (V2 architecture).

**Path hardening for GUI launches** — `media_analysis` now augments `PATH`
with the standard tool dirs (`/opt/homebrew/bin`, `/usr/local/bin`, etc.) so
ffprobe/ffmpeg resolve even when the MCP server is launched by a GUI app
(Claude.app, Dock/Spotlight) that inherits launchd's bare PATH.

**Documentation** — `AGENTS.md` adds the "Media Analysis Defaults Are
Mandatory" section. `docs/SKILL.md` rewrites the `analyze_media` prompt
guidance for the host-chat-paths protocol and adds the anti-regression rule.
`docs/guides/media-analysis-guide.md` covers the deferred vision payload and
commit step.

**Validation**: static import checks, API parity audit, focused
media-analysis + marker/range/v232/v233 unit tests, npm CLI smoke,
`npm pack --dry-run`, and `git diff --check` all passed. No source media was
modified. Resolve scripting behavior is additive (new actions; existing
actions unchanged); live Resolve validation covered the control-panel +
open_in_viewer + commit_vision auto-publish + corrections-merge paths during
the V2 push sessions logged in MEMORY.md.

## What's New in v2.23.1

**Control panel navigation fixes** — The local browser control panel now keeps
top-level dropdown buttons from navigating by themselves. Analysis,
Diagnostics, Docs, and Preferences open their menus first; selecting a menu item
is what changes the active view.

**Project dropdown cleanup** — The project context dropdown is back to showing
only the open/current project context plus a bottom `View All Projects` option.
The full database browser stays in the Projects view, and the standalone
Projects navbar button has been removed.

**Validation**: static import checks, API parity audit, focused dashboard unit
tests, npm CLI smoke tests, package dry-run, and `git diff --check` passed. A
local dashboard smoke check verified the served HTML on `127.0.0.1:8765`.
No Resolve scripting behavior changed; live Resolve mutation validation was not
required.

## What's New in v2.23.0

**npm installer** — `npx davinci-resolve-mcp setup` is now the primary quick
start. The npm package bootstraps a managed per-user install, runs the existing
Python installer from that stable location, and keeps MCP client configs pointed
at the managed virtual environment and `src/server.py`.

**Local control panel** — Added a single-user browser control panel for server
status, Resolve clip visibility, source-safe analysis jobs, analysis search, and
preference management. It can be launched from source with
`venv/bin/python -m src.control_panel` or from npm with
`npx davinci-resolve-mcp control-panel`.

**Durable media-analysis jobs and search** — `media_analysis` can now create,
slice, inspect, cancel, resume, and list durable analysis jobs. Persisted reports
refresh a single-user SQLite index with clip, marker, timeline occurrence,
keyframe, and transcript search helpers through `build_index`, `index_status`,
and `query_index`.

**Release automation** — Added npm package metadata, package-content guards, and
a tag-driven GitHub Actions workflow for trusted npm publishing with provenance.
The workflow skips publish when the package version already exists, which keeps
the first manual npm registration from fighting the later tag workflow.

**Validation**: static import checks, API parity audit, focused media-analysis,
update-check, and media-pool ingest unit tests passed. npm smoke tests, setup
dry-run, package dry-run, and `git diff --check` passed. No source media was
modified.

## What's New in v2.22.0

**Configurable MCP update prompting** — Update checks now carry a persisted
policy: `prompt`, `auto`, `notify`, or `never`. The server still never blocks
MCP stdio startup, but the installer can prompt users to update, continue,
snooze for 24 hours, ignore the current release, enable safe auto-update, or
disable checks. Safe auto-update is opt-in and only attempts a clean git
fast-forward from checkouts with no local changes and a configured upstream.

**MCP update controls** — `resolve_control.mcp_update_status` reports the local
MCP version, cached or forced update status, and the current prompt decision.
`set_mcp_update_policy`, `ignore_mcp_update`, `snooze_mcp_update`, and
`clear_mcp_update_preferences` expose the same policy state through the
compound server without requiring Resolve to be connected.

**Conversation setup defaults** — New `setup` compound tool centralizes
conversation-configurable defaults. It can read, set, dry-run, and clear
preferences for media-analysis modality, slate detection, transcription,
analysis persistence, metadata publish fields and overwrite policy, timed marker
types/colors/counts, report style, preferred analysis roots, post-operation page
behavior, and MCP update interval/snooze policy. These defaults shape future
tool calls while preserving explicit confirmation for Resolve project writes.

**Metadata field inventory** — `media_pool.metadata_field_inventory` gives
assistant editors and metadata workflows a read-only map of clip metadata,
clip-property keys, default analysis writeback fields, optional slate fields,
and inferred Resolve Metadata-panel groups. This helps bridge analysis
publishing to the fields Resolve actually exposes on a given clip/build.

**Optional timed analysis markers** — `media_analysis.publish_clip_metadata`
can now write source-frame Media Pool clip markers for slate claps, best
moments, and QC warnings when the user opts in. If no marker preference exists,
the tool returns a prompt with yes/no/default-yes/default-no choices rather than
silently writing markers.

**Validation**: static import checks, API parity audit, `git diff --check`, and
focused update-check, media-analysis, and media-pool ingest unit tests passed.
Media-pool ingest tests cover the new metadata inventory and Metadata-panel
group hints. Live validation used DaVinci Resolve Studio 20.3.2.9 through the
connected MCP server with a disposable project and synthetic media only. It
verified `metadata_field_inventory`, `MediaPool.ExportMetadata()` header
comparison, default analysis writeback field mapping, and `SetMetadata()`
readback for analysis and slate fields. The standalone live metadata inventory
harness is included for future release validation with a Resolve-compatible
Python 3.10-3.12 interpreter.

## What's New in v2.21.0

**Resolve metadata publishing from analysis** —
`media_analysis.publish_clip_metadata` turns source-safe analysis reports into
Resolve-native clip metadata. It proposes field-specific merges for
`Description`, `Comments`, `Keywords`, `People`, and optional slate-derived
fields, preserves existing human metadata by default, writes provenance to
third-party metadata, and requires `confirm=true` before mutating Resolve.

**Slate-aware metadata proposals** — Metadata publishing can reuse
`detect_sync_events` slate-clap evidence and, when chat-context sampling is
available, inspect frames around the clap for high-confidence slate fields before
proposing `Scene`, `Shot`, `Take`, `Camera #`, and `Roll/Card` writes.

**MCP update visibility** — The installer and both MCP server entrypoints now
perform a best-effort GitHub release check, cache the result under `logs/`, and
surface the local MCP version plus last update-check status from
`resolve_control.get_version`. Checks are informational only and never install
code automatically.

**Validation**: static/import checks, API parity audit, focused media-analysis,
sync-event, and update-check unit tests passed. Live validation used DaVinci
Resolve Studio 20.3.2.9 through the active Resolve script runner with disposable
projects and synthetic media only. `tests/live_metadata_publish_validation.py`
verified dry-run previews, confirmed metadata writes, human metadata
preservation, keyword merging, third-party provenance, and cleanup;
`tests/live_sync_event_validation.py` revalidated 2-pop/slate-clap detection and
confirmed marker writes.

## What's New in v2.20.0

**Sync event detection helper** — `media_analysis.detect_sync_events` detects
likely audio 2-pops and slate claps with FFprobe/FFmpeg, returns advisory
frame/timecode positions, and suggests per-file `record_offset` values for
`media_pool.setup_multicam_timeline(sync_mode="record_frame")`. The helper is
source-safe and never installs FFmpeg automatically. It also returns marker
suggestions; `media_analysis.add_sync_event_markers` writes Media Pool item
markers only when called separately with `confirm=true`.

**Validation**: static/import checks, API parity audit, focused media-analysis
and multicam unit tests, and `tests/live_sync_event_validation.py` passed. The
live run used DaVinci Resolve Studio 20.3.2.9, a disposable project, and
synthetic audio only; it verified detection, confirmation refusal, confirmed
Media Pool marker writes, and cleanup.

## What's New in v2.19.0

**Multicam setup support** — `media_pool.setup_multicam_timeline` creates a
source-safe stacked prep timeline from Media Pool clips, with one angle per video
track, optional matching audio tracks, and stack-start, manual record-frame, or
source-timecode planning. Native multicam clip conversion remains a Resolve UI
step because the public scripting API does not expose a multicam-create method;
the current UI workflow is documented in the DaVinci Resolve 20 Manual,
Edit > Chapter 42, "Multicam Editing."

**Documentation**: added `docs/guides/multicam-setup-guide.md` and linked the
helper from the README, docs index, AI skill reference, kernel coverage, ingest
kernel, and API coverage notes so it is clearly listed as a helper rather than
a native API feature.

## What's New in v2.18.0

**Edit-page title / Text+ text (undocumented keys)** — `timeline.title_property_scan`,
`timeline.set_title_text`, and `timeline.bulk_set_title_text` use
`TimelineItem.GetProperty` / `SetProperty` to discover and update generator Text+
payloads when `GetFusionCompCount()` is zero (no Fusion comp for `fusion_comp`).
Heuristic key ranking and a minimal styled-text XML fallback are included; callers
should confirm keys with `title_property_scan` on their Resolve build.

## What's New in v2.17.1

Operational and client-safety hardening for the v2.17 media-analysis release.

**MCP tool metadata**: compound and granular tools now publish MCP
`ToolAnnotations` with conservative read-only, destructive, idempotent, and
external-resource hints. Compound tool annotations are intentionally conservative
because each tool groups multiple actions behind an `action` parameter.

**MCPSafe report cleanup**: explicitly annotated the granular tools highlighted
by the public MCPSafe report, including project settings, media import, page
switching, proxy linking, Gallery album reads, and timeline-item transforms.

**Operational guardrails**: Resolve app-control subprocess fallbacks now use
bounded timeouts and report non-zero exits. Best-effort Resolve object
inspection and state probes now log swallowed exceptions at debug level instead
of failing silently.

**Correctness fix**: fixed the granular
`media_pool.append_to_timeline(clip_infos=...)` path so it retains the current
project handle while normalizing positioned appends against the active timeline
start frame.

**Documentation**: added `SECURITY.md` with the local stdio trust boundary,
confirmation guidance for destructive tools, source-media safety boundaries, and
private vulnerability reporting guidance. The README now links the security
policy and summarizes the local-only auth posture.

**Validation**: static/import checks, API parity audit, compileall, and 161
focused unit tests passed. Live validated against DaVinci Resolve Studio 20.3.2.9
with a direct external-scripting smoke test, `tests/live_v233_validation.py`
passing 10/10 checks, and a v2.17.1 disposable-project
`media_pool.append_to_timeline(clip_infos=...)` normalization probe passing 2/2
checks. The v2.17.1 probe used synthetic media only and verified the default
relative `record_frame` path landed at timeline start frame 86400 + 12 = 86412,
while `record_frame_mode="absolute"` preserved frame 86484.

## What's New in v2.17.0

Media analysis and editorial-assist expansion - `media_analysis` now reuses
existing project reports when cache signatures satisfy the requested analysis
layers, can review timeline marker contact sheets with chat-context vision, and
`timeline` adds editor-facing helpers for story-spine reports, declarative
variant creation, bulk item property writes, multi-item look application,
thumbnail contact sheets, marker thumbnail review, and audio mix capability
fallback reporting.

**New `media_analysis` compound tool**: added `capabilities`,
`install_guidance`, `resolve_output_root`, `plan`, `analyze_file`,
`analyze_clip`, `analyze_bin`, `analyze_project`, `review_timeline_markers`,
`summarize`, `get_report`, and `cleanup_artifacts`.

**MCP prompts and visual review**: the compound server now registers
`davinci_resolve_workflow` and `analyze_media` prompts. `analyze_media` defaults
to chat-context visual analysis when MCP sampling is available, while
`timeline_markers.get_thumbnail_image` returns current Resolve frames as MCP
image content without writing a file.

**Source-safe editorial helpers**: timeline actions now support
`story_spine_report`, `create_variant_from_ranges`, `bulk_set_item_properties`,
`apply_look_to_items`, `thumbnail_contact_sheet`, `marker_thumbnail_review`, and
`audio_mix_capability_report`. Positioned timeline appends normalize
`record_frame` relative to the active timeline start by default, matching
Resolve's common 01:00:00:00 start-frame behavior.

**Documentation reorganization**: moved durable references into `docs/guides`,
`docs/kernels`, `docs/authoring`, `docs/notes`, `docs/process`, and
`docs/reference`, added a compact docs index, and kept local gameplans/scratch
artifacts ignored.

**Privacy cleanup**: sanitized tracked live-test fixtures and scripts that had
workstation-specific source-media paths while leaving public project contact
information intact.

**Validation**: static/import checks, API parity audit, and 141 focused unit
tests passed. Live validated against DaVinci Resolve Studio 20.3.2.9 with a
disposable `_mcp_media_analysis_v2170_probe` project and a generated synthetic
clip only. The run covered source-adjacent output-root rejection,
`media_analysis.plan`, session-only `analyze_file`, `story_spine_report`,
`audio_mix_capability_report`, raw thumbnail retrieval, `thumbnail_contact_sheet`,
and `review_timeline_markers`; the disposable project and temp artifacts were
cleaned up.

## v2.16.0

Extension Authoring kernel expansion - adding lifecycle-aware Fuse, DCTL, ACES
DCTL, and Resolve-page script probes around the existing authoring tools.

**New `script_plugin` extension actions**: added `extension_capabilities`,
`probe_fuse_lifecycle`, `probe_dctl_lifecycle`, `probe_script_lifecycle`,
`safe_install_extension`, `safe_remove_extension`,
`refresh_or_restart_required`, and `extension_boundary_report`.

**Lifecycle and cleanup guards**: safe extension installs require `_mcp_` names
and MCP markers by default. Safe removal refuses to delete unmarked files unless
explicitly overridden. The kernel classifies Fuse and ACES DCTL installs as
restart-required, regular LUT DCTLs as `refresh_luts`-driven, and Resolve-page
scripts as menu-refresh-only.

**Documented support map**: added
[`docs/kernels/extension-authoring-kernel.md`](docs/kernels/extension-authoring-kernel.md) and
updated the Fuse/DCTL and script authoring docs with live lifecycle findings.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with
MCP-marked `_mcp_` extension files only. Final probe result: 14 supported, 1
partially supported installed-Lua-script execution boundary, 1 intentional
unsupported unmarked-source guard, and 0 errors. All generated extension files
and the disposable project were cleaned up.

## v2.15.0

Project / Database / Archive kernel expansion - adding disposable project
lifecycle guards, settings snapshots and write/restore probes, database switch
dry-runs, preset lifecycle probing, archive safety validation, and project
boundary reporting.

**New `project_manager` lifecycle actions**: added `project_capabilities`,
`probe_project_lifecycle`, `probe_project_settings`, `safe_project_create`,
`safe_project_export`, `safe_project_import`, `safe_project_archive`,
`safe_project_restore`, `safe_project_delete`, `safe_set_project_settings`,
`project_settings_snapshot`, `database_capabilities`,
`safe_set_current_database`, `preset_lifecycle_probe`, and
`project_boundary_report`.

**Operational guardrails**: safe project mutation defaults to `_mcp_`
disposable names and temp paths. Database switching dry-runs by default because
Resolve closes open projects when changing databases. Archive source media,
render cache, and proxy media flags are rejected unless explicitly opted in.

**Documented support map**: added
[`docs/kernels/project-lifecycle-kernel.md`](docs/kernels/project-lifecycle-kernel.md) with
project CRUD, DRP import/export, archive/restore, folder, settings, database,
layout preset, render preset, page, keyframe, and cloud-infrastructure
boundaries.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with
disposable `_mcp_` projects only. Final probe result: 35 supported, 5 partially
supported lifecycle/archive/keyframe/render-preset boundaries, 1 intentional
unsupported archive media-flag guard, 1 not-applicable archive restore boundary,
and 0 errors. Disposable projects, layout presets, and temp work files were
cleaned up.

## v2.14.0

Audio / Fairlight kernel expansion - adding audio track/item probes, source
audio mapping reports, guarded audio property writes, voice isolation
capabilities, auto-sync planning, transcription/subtitle probes, and Fairlight
boundary reporting.

**New `timeline` audio actions**: added `audio_capabilities`,
`probe_audio_track`, `probe_audio_item`, `safe_set_audio_properties`,
`voice_isolation_capabilities`, `audio_mapping_report`, `safe_auto_sync_audio`,
`transcription_capabilities`, `subtitle_generation_probe`, and
`fairlight_boundary_report`.

**Audio state and mapping**: the kernel snapshots audio track state, timeline
item audio properties, source audio channel mapping, MediaPoolItem audio
mapping, and track/item voice isolation availability.

**Guarded AI and sync surfaces**: auto-sync dry-runs by default and normalizes
Resolve audio-sync constants. Subtitle generation dry-runs unless
`allow_generate=True`; transcription capability reporting is read-only by
default.

**Documented support map**: added
[`docs/kernels/audio-fairlight-kernel.md`](docs/kernels/audio-fairlight-kernel.md) with
track/item state, voice isolation, mapping, transcription, subtitle, auto-sync,
and Fairlight insertion boundaries.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with
generated synthetic video and audio-only media. Final probe result: 13
supported, 3 partially supported audio property/auto-sync/audio-insert
boundaries, and 0 errors. The disposable project and generated media were
cleaned up.

## v2.13.0

Timeline Conform / Interchange kernel expansion - adding timeline structure
snapshots, source range reporting, gap/overlap detection, guarded interchange
export/import, round-trip comparison, missing-media detection, and relink
planning around Resolve's public timeline APIs.

**New `timeline` conform actions**: added `conform_capabilities`,
`probe_timeline_structure`, `detect_gaps_overlaps`, `source_range_report`,
`export_timeline_checked`, `import_timeline_checked`, `compare_timelines`,
`probe_interchange_roundtrip`, `detect_missing_media`, `build_relink_plan`,
and `conform_boundary_report`.

**Interchange probing**: export aliases now cover FCPXML, DRT, EDL, AAF, OTIO,
FCP 7 XML, and EDL subtype variants. FCPXML directory-style exports are
normalized with a `primary_file` path for import.

**Conform analysis**: the kernel reports track/item structure, same-track gaps
and overlaps, source ranges with handles, missing/offline media, and relink
candidates without mutating user source media.

**Documented support map**: added
[`docs/kernels/timeline-conform-interchange-kernel.md`](docs/kernels/timeline-conform-interchange-kernel.md)
with export, round-trip, missing-media, relink planning, and format-survival
boundaries.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with a
generated synthetic gapped timeline. Final probe result: 17 supported, 1
partially supported FCPXML round-trip survivability boundary, and 0 errors. The
disposable project, generated media, and imported round-trip timelines were
cleaned up.

## v2.12.0

Fusion Composition kernel expansion - adding safe Fusion graph inspection,
tool creation, input writes, connection validation, scoped bulk writes, and
boundary reporting around Resolve's public Fusion comp API.

**New `fusion_comp` kernel actions**: added `fusion_graph_capabilities`,
`probe_fusion_comp`, `probe_fusion_tool`, `safe_add_tool`, `safe_set_inputs`,
`safe_connect_tools`, and `fusion_boundary_report`.

**Timeline item graph automation**: the kernel can target timeline item Fusion
comps via `timeline_item`, `clip_id`, or `timeline_item_id`, then add tools,
write inputs with readback, inspect ports, connect tools, set frame ranges, and
export the comp through `timeline_item_fusion`.

**Scoped bulk writes**: `bulk_set_inputs` remains the safe batch path for
applying input updates across multiple explicitly scoped timeline-item comps,
so agent workflows do not accidentally mutate the active Fusion page comp.

**Documented support map**: added
[`docs/kernels/fusion-composition-kernel.md`](docs/kernels/fusion-composition-kernel.md) with
tool availability, input/output, scope, comp export, and page-state boundaries.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with a
generated synthetic timeline item Fusion comp. Final probe result: 18
supported, 0 unsupported, 0 partially supported, and 0 errors. The disposable
project, generated media, and exported temp comp were cleaned up.

## v2.11.0

Color / Grade kernel expansion - adding safe grade inspection, CDL validation,
node graph probing, grade copy, LUT export, version restore, Gallery, and color
group boundary reporting around Resolve's public Color API.

**New `timeline_item_color` kernel actions**: added `grade_capabilities`,
`probe_grade_item`, `probe_node_graph`, `safe_set_cdl`, `safe_copy_grade`,
`safe_apply_drx`, `safe_export_lut`, `grade_version_snapshot`,
`grade_version_restore`, `color_group_capabilities`, `gallery_capabilities`,
and `grade_boundary_report`.

**Grade and graph probing**: the kernel snapshots item grade versions, graph
availability, node counts, node LUT/cache/label/tools metadata, color-group
assignment, and cache state without guessing at opaque node internals.

**Safe mutation helpers**: CDL payloads are validated and normalized before
`SetCDL`; grade copy resolves target timeline item IDs first; LUT export is
guarded to temp paths by default; DRX apply requires an existing DRX path and
documents that it replaces the target graph.

**Color groups and Gallery**: color-group capability probes cover project
groups plus pre/post graph availability. Gallery capability probes report album
state and classify still export as UI/page dependent when Resolve returns false.

**Documented support map**: added
[`docs/kernels/color-grade-kernel.md`](docs/kernels/color-grade-kernel.md) with graph, LUT, DRX,
version, Gallery, color-group, and AI-tool boundaries.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with a
generated synthetic color-bar timeline. Final probe result: 25 supported, 2
version/page-dependent Gallery/DRX export boundaries, 1 not-applicable DRX apply
path because no DRX could be produced in that run, and 0 errors. The disposable
project, generated media, and temp LUT exports were cleaned up.

## v2.10.0

Review Annotation kernel expansion - adding a unified marker, custom data,
flag, clip color, copy/move, and review report layer across timeline, timeline
item, and media pool item scopes.

**New `timeline_markers` kernel actions**: added
`annotation_capabilities`, `probe_annotations`, `normalize_marker_payload`,
`copy_annotations`, `move_annotations`, `sync_marker_custom_data`,
`clear_annotations_by_scope`, `export_review_report`, and
`annotation_boundary_report`.

**Unified annotation scopes**: the new helpers normalize marker payloads,
frame/timecode aliases, custom data aliases, and marker colors before touching
Resolve. `probe_annotations` snapshots timeline, current timeline item, and
media pool item annotations when the current playhead can resolve them.

**Review metadata copying**: `copy_annotations` and `move_annotations` can copy
marker payloads between timeline, timeline item, and media pool item scopes
using direct frame numbers. When supported by both scopes, flags and clip color
can travel with the marker payload.

**Read-only review reports**: `export_review_report` and
`annotation_boundary_report` produce agent-friendly summaries without mutating
media or projects.

**Documented support map**: added
[`docs/kernels/review-annotation-kernel.md`](docs/kernels/review-annotation-kernel.md) with the
scope matrix, field support, frame-space caveats, and live probe findings.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with a
generated synthetic timeline. Final probe result: 44 supported, 1 expected
unsupported invalid-color boundary, and 0 errors. The disposable project and
generated media were cleaned up after report generation.

## v2.9.0

Render / Deliver kernel expansion — adding a safer render planning, settings,
format/codec compatibility, queue lifecycle, and Quick Export boundary layer.

**New `render` kernel actions**: added `render_capabilities`,
`probe_render_matrix`, `probe_render_settings`, `validate_render_settings`,
`safe_set_render_settings`, `prepare_render_job`,
`render_job_lifecycle_probe`, `quick_export_capabilities`,
`safe_quick_export`, and `export_render_boundary_report`.

**Render compatibility matrix**: `probe_render_matrix` walks available render
formats, codecs, and resolutions so agents can choose what this specific
Resolve install can actually deliver.

**Job-safe rendering helpers**: render settings validation now checks documented
setting keys, value types, frame ranges, and temp-target requirements.
`prepare_render_job` creates queued jobs without starting renders, while
`render_job_lifecycle_probe` validates add/status/delete behavior safely.

**Guarded Quick Export**: `safe_quick_export` validates temp targets, forces
`EnableUpload=False`, and requires `allow_render=True` before it can actually
start Quick Export.

**Documented support map**: added
[`docs/kernels/render-deliver-kernel.md`](docs/kernels/render-deliver-kernel.md) with
format/codec, settings, render job, and Quick Export boundaries.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with a
two-second generated synthetic timeline. Final probe result: 23 supported, 1
version/page-dependent `GetRenderSettings` readback boundary, and 0 errors. The
probe rendered one tiny synthetic output, then cleaned up the disposable project
and generated files.

## v2.8.0

Media Pool / Ingest kernel expansion — applying the timeline edit kernel probe
pattern to import, organization, metadata, annotation, and media-link boundary
workflows while preserving source media integrity.

**New `media_pool` kernel actions**: added `ingest_capabilities`,
`probe_media_pool`, `probe_ingest_item`, `safe_import_media`,
`safe_import_sequence`, `safe_import_folder`, `organize_clips`,
`copy_metadata`, `normalize_metadata`, `probe_clip_properties`,
`safe_relink`, `safe_unlink`, `link_proxy_checked`,
`link_full_resolution_checked`, `set_clip_marks`, `clear_clip_marks`,
`copy_clip_annotations`, and `media_pool_boundary_report`.

**Safe ingest and organization**: safe import helpers validate paths, sequence
patterns, frame ranges, and optional target folders before calling Resolve.
`organize_clips` can move clips to existing folders or create missing folder
paths explicitly. All helpers support dry-run where useful for planning.

**Metadata and annotation workflows**: bulk metadata normalization, metadata
copying, clip property probes, mark in/out bulk operations, and annotation copy
now have agent-friendly wrappers over Resolve's lower-level clip APIs.

**Documented support map**: added
[`docs/kernels/media-pool-ingest-kernel.md`](docs/kernels/media-pool-ingest-kernel.md) so
agents and users can inspect the supported, partial, unsupported, and
version/page-dependent ingest boundaries directly.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with
generated synthetic video, audio, still, image sequence, and non-media
fixtures. Final probe result: 56 supported, 1 expected unsupported non-media
text import, and 0 errors. The disposable project and generated media were
cleaned up after report generation.

## v2.7.0

Timeline edit kernel expansion — turning the v2.6.0 duplicate helper into a
broader, live-probed edit layer for clip duplication, linked audio, range edits,
state copying, and capability reporting while preserving source media integrity.

**Expanded `timeline.duplicate_clips` action**: duplication now supports
`selected=True`, explicit `record_frame`, `track_offset`, and placement modes
`same_time`, `offset`, `at_playhead`, `track_above`, `after_source`, and
`next_gap`. `include_linked=True` duplicates linked audio and restores the
video/audio link state. `copy_clips` is an alias for duplication, and
`move_clips` duplicates successfully first before deleting the original source
items.

**Timeline range operations**: added `copy_range`, `duplicate_range`,
`overwrite_range`, and `lift_range`. Range copies rebuild exact source segments
with positioned append operations. `overwrite_range` deletes whole destination
overlaps before appending. `lift_range` safely deletes whole matching items and
requires explicit `allow_partial_item_delete=True` for whole-item deletion when
a requested range only partially overlaps an item.

**State copying groups**: duplicate/copy operations can now copy transform,
crop, composite, audio, retime, dynamic zoom, scaling, stabilization, clip
color, markers, flags, enabled state, cache, voice isolation, Fusion comps,
grades, takes, and keyframes where Resolve exposes readable/writable item APIs.
Transition cloning is accepted as a requested group but reported unsupported
because Resolve's public scripting API does not expose transition cloning.

**Capability and boundary probes**: added `timeline.edit_kernel_capabilities`
for a maintained support map and `timeline.probe_edit_kernel_item` for read-only
inspection of item methods, properties, keyframes, and linked items. Added
`src/utils/timeline_kernel_live_probe.py` plus offline report/parser tests so
future work can expand the technical boundary without guessing.

**Documented limits**: added
[`docs/kernels/timeline-edit-kernel.md`](docs/kernels/timeline-edit-kernel.md), which records
the supported, partially supported, unsupported, and version/page-dependent
surfaces. Known public-API boundaries include transition cloning, direct
razor/split edits, true partial lifts, source-less item append cloning, and
opaque speed-ramp internals.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with
disposable projects and synthetic media. Final exhaustive probe result:
255 supported, 4 partially supported, 138 unsupported, 4 version/page
dependent, and 0 errors. Static/unit checks include `tests/test_import.py`,
`scripts/audit_api_parity.py`, `git diff --check`, the focused timeline/helper
unit suite, and the full live duplicate/range/probe harness.

## v2.6.0

Timeline clip duplication — adding an Alt-drag-style helper for duplicating
existing video timeline items without creating proxy media, renders, or source
derivatives.

**New `timeline.duplicate_clips` action**: `timeline(action="duplicate_clips")`
duplicates video timeline items by re-appending the same Media Pool item with
the same source trim via `MediaPool.AppendToTimeline([{clipInfo}])`. It accepts
timeline item IDs from `timeline.get_items`, an optional
`target_track_index`, and `record_frame_offset`; each result reports per-clip
success and the duplicated timeline item ID when Resolve exposes or recovers it.

**Resolve append-result hardening**: duplicate results now tolerate thin
`AppendToTimeline` return objects that lack readable `GetUniqueId()` or
`GetName()` methods, then scan the target video track to recover the real item
handle. Bad inputs now return clean per-clip errors for non-video items,
invalid offsets, and nonexistent target tracks.

**Live-tested source trim semantics**: validation against Resolve Studio
20.3.2.9 confirmed that positioned `AppendToTimeline` treats `endFrame` as an
exclusive source boundary in this workflow. `duplicate_clips` now uses
`TimelineItem.GetDuration()` and `GetSourceStartFrame()` where available, so
the duplicate preserves the original duration and source start.

**Validation**: added `tests/live_duplicate_clips_validation.py`, which creates
a disposable project, imports synthetic media, places a trimmed clip, duplicates
it to another track, verifies record frame/duration/source trim/media identity,
checks the invalid-track error path, and deletes the project. Focused unit
coverage now includes anonymous append objects, source-start preference,
video-only `mediaType`, and target-track ID recovery.

## v2.5.0

Three new compound tools for *authoring and conversationally executing* Resolve extensions: Fusion Fuse plugins, DCTL color transforms, and Resolve-page Lua/Python scripts. Plus a documentation pass on six adjacent Resolve extension systems.

**New `fuse_plugin` tool**: generate, install, list, read, remove, and validate Fusion Fuse plugins (`.fuse`). **18 template kinds** spanning color (`color_matrix`, `per_pixel`, `channel_op`), geometric (`transform`, `spatial_warp`), text/shapes (`text_overlay`, `shape_generator`), source/temporal (`source_generator`, `time_displace`), filters (`builtin_blur`, `builtin_resize`, `variable_blur` SAT-based), modifiers (`modifier`, `point_modifier`), display shaders (`view_lut`, `dctl_kernel`), and reference (`controls_demo`, `notifychanged_demo`). Each generator produces ready-to-install Lua (or Lua + GLSL / Lua + DCTL) source that passes `luac -p` syntax checks across all option branches. **Live-verified in DaVinci Resolve Studio 20.3.2.9**: generated Fuses register on Resolve restart and instantiate via `comp:AddTool`; the `text_overlay` template was confirmed rendering glyphs into the viewer. The `view_lut` template supports `float`, `vec2`, `vec3_rgb`, and `vec4_rgba` shader parameter types. Includes a path-bug fix: corrected install path on macOS to `Fusion/Fuses/` (the SDK doc lists `Support/Fusion/Fuses/`, but Fusion's own `MapPath("Fuses:")` returns the path without `/Support/`).

**New `dctl` tool**: generate, install, list, read, remove, and validate DCTL color-transform files plus ACES IDT/ODT transforms. **8 template kinds** — `transform`, `transform_alpha` (Resolve 19.1+ alpha modes), `transition` (with `TRANSITION_PROGRESS`), `matrix` (3x3 color matrix), `kernel` (TODO stub), `lut_apply` (wraps an external `.cube` LUT via `DEFINE_LUT`/`APPLY_LUT`), `aces_idt`, `aces_odt`. UI-parameter syntax covers all six DCTL UI types (slider float/int, value box, checkbox, combo, color picker) with optional tooltips. Per-template `suggested_category` so callers know whether to install to the regular LUT directory or the separate ACES Transforms tree. Subdir support with strict path-traversal guards. Validator catches missing entry points, brace imbalance, and float literals missing the required `f` suffix. Regular DCTLs pick up via `project_settings(action='refresh_luts')`; ACES DCTLs require a Resolve restart.

**New `script_plugin` tool — conversational Lua/Python execution**: generate, install, and **execute** Resolve-page scripts that appear in the Workspace → Scripts menu. Two template kinds: `scaffold` (minimal stub) and `media_rules` (a comprehensive rules-and-variables DSL with sources, extract patterns, transforms, targets, actions, conditions, dry-run mode, external CSV/JSON data with exact/regex/fuzzy matching, and per-rule metadata — ~22k chars Lua engine and ~18k chars Python engine, both first-class). **Two new actions close the conversational loop**: `run_inline(source, language)` runs an ad-hoc Lua/Python snippet inside Resolve and streams stdout + return value back into the conversation; `execute(name, category, language)` runs an installed script the same way. Python uses subprocess with full stdout/stderr capture; Lua uses `fusion.RunScript()` against a temp file with completion-sentinel polling and `app:SetData()` bridge for return values (Resolve 20.x's `fusion.Execute()` is a no-op from the Python bridge — that quirk is encoded in the implementation). **Live-verified end-to-end** on Resolve Studio 20.3.2.9: Python `run_inline` returned project list and walked media pool; Lua `run_inline` enumerated `MapPath` symbols with stdout AND return value captured.

**`list_templates` action** on all three new tools enumerates available kinds.

**Resolve developer-package reference consolidation**: extension-system notes
were consolidated back into README/SKILL guidance, while dedicated authoring
docs remain in `docs/authoring/fuse-dctl-authoring.md` and
`docs/authoring/script-plugin-authoring.md`.

**Test coverage**: 185 offline tests across 7 modules (`test_fuse_dctl_authoring.py` and `test_script_plugin.py` both new in this release), all green in <2s. Includes hermetic round-trip tests with mocked install paths, DSL-coverage tests confirming every documented source/action/target/transform is in both Lua and Python engines, and Python subprocess execution tests with real captured stdout/stderr.

**Compound tool count: 27 → 30**. Granular tool count unchanged at 328.

## v2.4.1

Release process hardening — documenting the version bump, validation, tag, and GitHub Release checklist.

**Release checklist documented**: added `docs/process/release-process.md` with semantic version guidance, required version surfaces, validation requirements, tag/release commands, and release-note template.

**Live-test requirement clarified**: Resolve behavior changes must be validated live with disposable projects and synthetic media before release. Docs-only releases do not require a live Resolve run when no behavior changed.

## v2.4.0

Timeline source range extraction — adding a compound workflow helper for frame-pull and conform preparation.

**New `timeline.extract_source_frame_ranges` action**: `timeline(action="extract_source_frame_ranges")` scans every video clip on the current timeline and returns per-source frame ranges, clip occurrences, timeline positions, source offsets, applied handles, and timeline item IDs. Clip names prefer the basename from the Media Pool `File Path`, with audio extensions skipped by default.

**Handle-aware source ranges**: fixed handles default to 24 frames. Passing `handles=0` switches to gap-only auto handles, using neighboring timeline gaps up to `gap_max` frames. Returned `source_range_final` and `frame_ranges` endpoints are inclusive/inclusive for downstream extraction tools.

**Inclusive endpoint fix**: live validation caught and fixed the off-by-one where Resolve's exclusive source boundary was being returned as an inclusive final frame. A 48-frame synthetic clip with `handles=0` now returns `source_used_inclusive_end=47` and `source_range_final=[0, 47]`.

**Live Resolve validation**: verified against DaVinci Resolve Studio 20.3.2.9 in a disposable project with synthetic media. Added unit coverage in `tests/test_extract_source_frame_ranges.py` for zero-handle and fixed-handle ranges.

## v2.3.4

Marker API hardening for Issue #34 — making the compound marker tools match the parameter shapes agents and users naturally send.

**Marker parameter aliases fixed**: `timeline_markers`, `media_pool_item_markers`, and `timeline_item_markers` now accept `frame`, `frame_id`, and `frameId` consistently for add/get/update/delete operations. Marker lookup and delete paths also accept `customData` as an alias for `custom_data`.

**Timeline marker ergonomics improved**: `timeline_markers(action="add")` can now add at the current playhead when no frame/timecode is provided, and also accepts explicit `timecode` input. Optional marker fields now have sensible defaults (`color="Blue"`, `name` from note or `"Marker"`, `note=""`, `duration=1`).

**Resolve overload fallback**: marker creation first uses the documented six-argument `AddMarker(..., customData)` call, and falls back to the five-argument form when `customData` is empty and a Resolve build rejects the optional parameter.

**Live Resolve validation**: verified against DaVinci Resolve Studio 20.3.2.9 with `tests/live_marker_validation.py`. The harness creates a disposable project, imports synthetic media, inserts a visible timeline generator, and live-tests timeline, media-pool-item, and timeline-item marker add/get/update/delete alias paths. A `--keep-open` mode leaves a marked timeline open for visual inspection.

## v2.3.3

Granular layer hardening — closing exposure gaps and dropped-dict-key bugs surfaced by an exhaustive parity audit of every documented Resolve scripting method against both server layers.

**Cloud project helper rewritten** (Critical): `src/utils/cloud_operations.py` was calling `pm.CreateCloudProject(project_name, folder_path)` with positional arguments — but the documented Resolve API signature is `CreateCloudProject({cloudSettings})`, a single dict. Same bug affected `ImportCloudProject` and `RestoreCloudProject`. Helper now builds proper `{cloudSettings}` dicts and exposes all 5 documented keys (`PROJECT_NAME`, `PROJECT_MEDIA_PATH`, `IS_COLLAB`, `SYNC_MODE`, `IS_CAMERA_ACCESS`) per docs lines 576-594. Granular wrappers (`create_cloud_project_tool`, `import_cloud_project_tool`, `restore_cloud_project_tool`) updated to expose the full settings surface; `load_cloud_project_tool` added (was missing entirely from granular).

**Silent-drop bugs fixed** (Critical):
- **`render_with_quick_export()` (granular)** previously dropped the documented `{param_dict}` (TargetDir, CustomName, VideoQuality, EnableUpload). Now forwards all four keys per docs line 179.
- **`timeline_create_compound_clip()` (granular)** previously dropped the documented `{clipInfo}` dict (`name`, `startTimecode`). Now exposes both keys per docs line 369.

**Missing granular tools added**:
- **`append_to_timeline`** — both simple `clip_ids` form and positioned `clip_infos` form (`MediaPool.AppendToTimeline` was completely absent from granular layer; only compound had it).
- **`auto_sync_audio`** — with proper `{audioSyncSettings}` dict mapping per docs lines 600-614 (`sync_mode`, `channel_number` with `'automatic'`/`'mix'` aliases, `retain_embedded_audio`, `retain_video_metadata`).
- **`load_cloud_project_tool`** — was missing entirely; compound had it.
- **`rename_color_group`** — wraps `ColorGroup.SetName` (compound had it via `color_group(action="set_name")` but no granular tool).

**Removed 4 undocumented cloud method wrappers**:
- `get_cloud_projects` resource → `GetCloudProjectList` not in API docs
- `export_project_to_cloud_tool` → `ExportToCloud`/`ExportProjectToCloud` not in API docs
- `add_user_to_cloud_project_tool` → `AddUserToCloudProject` not in API docs
- `remove_user_from_cloud_project_tool` → `RemoveUserFromCloudProject` not in API docs

**Removed 9 legacy granular gallery tools** that wrapped undocumented or renamed methods (`gallery.GetAlbums()`, `gallery.CreateAlbum()`, `still.GetTimecode()`, `still.IsGrabbed()`, etc.). The proper documented Gallery and GalleryStillAlbum wrappers (lines 743+ of the previous gallery.py — all 14 of those, e.g. `get_gallery_still_albums`, `create_gallery_still_album`, `import_stills_to_album`, `export_stills_from_album`, `get_album_stills`, `set_still_label`) cover the documented API surface and remain. Removed: `get_color_presets`, `save_color_preset`, `apply_color_preset`, `delete_color_preset`, `create_color_preset_album`, `delete_color_preset_album`, `export_lut`, `get_lut_formats`, `export_all_powergrade_luts`.

**Removed 2 granular project optimized-media tools** that wrapped undocumented Resolve methods (`Project.GenerateOptimizedMedia`, `Project.DeleteOptimizedMedia`, `MediaPool.SetClipSelection` — none in API docs). Removed: `generate_optimized_media`, `delete_optimized_media`. Use the Resolve UI for optimized-media generation; `set_optimized_media_mode` (which uses the documented `Project.SetSetting("OptimizedMediaMode", ...)`) is preserved.

**Deprecated method call fixed**: `timeline(action="get_items_in_track")` was calling the deprecated `tl.GetItemsInTrack()` form (docs line 989, marked deprecated) instead of the supported `tl.GetItemListInTrack()` (line 350). Every other call site already used the correct form.

**New: API parity CI guard** at `scripts/audit_api_parity.py`. Parses `docs/reference/resolve_scripting_api.txt` and verifies (1) no `from api.X` broken imports remain, (2) every documented Resolve method appears somewhere in `src/`, (3) wrappers calling undocumented methods are flagged for review. Includes an allowlist for legitimate undocumented-but-real Resolve API surface (Fusion compositing API, UIManager methods like `OpenProjectSettings`/`LoadUILayout`/`SaveUILayout`, internal type-discrimination helpers like `TimelineItem.GetType`/`GetMediaType`). Run with `python3 scripts/audit_api_parity.py` — currently passes all three checks cleanly.

**Tool count: 328 granular tools** (was 354 before v2.3.2; net change since v2.3.1 is −26 broken/duplicate/undocumented tools removed and +4 missing tools added). 20 new unit tests against Resolve stubs covering the cloud settings builder, audio sync settings builder, and AppendToTimeline clipInfo builder. All 41 tests pass without a live Resolve connection.

**Live disposable Resolve validation**: every new and changed v2.3.3 granular tool was exercised against DaVinci Resolve Studio 20.3.2.9 in a disposable project with synthetic temp media via `tests/live_v233_validation.py`. 10/10 checks passed: `append_to_timeline` (simple + positioned + failure path), `auto_sync_audio` (settings dict + invalid input rejection), `import_media` image-sequence form, `timeline_create_compound_clip` (info dict forwarded — compound clip created with explicit name), `rename_color_group` (renamed a real color group), `render_with_quick_export` (params dict forwarded — Resolve's structured `{JobStatus, Error}` response confirms the dict reached it), and the compound-side `GetItemListInTrack` deprecated→supported fix.

## v2.3.2

API parity sweep — closing documented overloads and dropped parameters that the v2.3.1 audit surfaced.

- **Positioned `CreateTimelineFromClips` via `clip_infos`** — `media_pool(action="create_timeline_from_clips", params={"clip_infos": [...]})` and the granular `create_timeline_from_clips(clip_infos=[...])` now expose the documented `MediaPool.CreateTimelineFromClips(name, [{clipInfo}, ...])` overload (4 keys: `mediaPoolItem`, `startFrame`, `endFrame`, `recordFrame`)
- **Image-sequence `ImportMedia` via `clip_infos`** — both layers now expose `MediaPool.ImportMedia([{FilePath, StartIndex, EndIndex}, ...])` for DPX/EXR/etc. sequence imports. PascalCase keys preserved per Resolve docs
- **Positioned `AddItemListToMediaPool` via `item_infos`** — `media_storage(action="import_to_pool", params={"item_infos": [{media, startFrame, endFrame}, ...]})` and granular `add_items_to_media_pool_from_storage(item_infos=[...])` now expose the documented `MediaStorage.AddItemListToMediaPool([{itemInfo}, ...])` overload
- **`Timeline.AddTrack` dict form** — replaced the legacy bare-string `sub_type` argument with the documented `newTrackOptions` dict (`audio_type`, `index`). Granular `timeline_add_track(track_type, audio_type=, index=)` and compound `timeline(action="add_track", params={"track_type", "options": {audio_type, index}})`
- **`CreateSubtitlesFromAudio` actually wired up** — granular `timeline_create_subtitles_from_audio` previously advertised `language` and `preset` parameters then silently dropped them. Now maps user strings (e.g. `"korean"`, `"netflix"`, `"double"`) to `resolve.AUTO_CAPTION_*` constants per docs lines 720-761, and exposes the missing `chars_per_line`, `line_break`, `gap` keys
- **Granular `import_media` no longer crashes** — the granular `import_media` tool was importing from a deleted `api.media_operations` module and would throw `ModuleNotFoundError` on first call. Rewritten to call `MediaPool.ImportMedia` directly and to share the new `clip_infos` overload
- **`SetRenderSettings` docstring completeness** — granular `set_render_settings` now documents all 27 keys per docs lines 765-799 (previously omitted `EncodingProfile`, `MultiPassEncode`, `AlphaMode`, `NetworkOptimization`, `PixelAspectRatio`, `ClipStartFrame`, `TimelineStartTimecode`, `ReplaceExistingFilesInPlace`)
- **Removed 18 broken granular tools (+ 7 broken resources)** that imported from a deleted `api.*` namespace and would crash with `ModuleNotFoundError` on first call. All 25 had working equivalents elsewhere or wrapped undocumented Resolve methods. Granular tool count is now **336** (was 354). Migration map for any caller that was hitting them:
  - `delete_media` → `media_pool(action="delete_clips")`
  - `move_media_to_bin` → `media_pool(action="move_clips")`
  - `auto_sync_audio` (granular tool) → `media_pool(action="auto_sync_audio")`
  - `unlink_clips` → `media_pool(action="unlink")`
  - `relink_clips` → `media_pool(action="relink")`
  - `create_bin` → `media_pool(action="add_subfolder")`
  - `list_media_pool_bins` (resource) → `folder(action="get_subfolders")`
  - `get_media_pool_bin_contents` (resource) → `folder(action="get_clips")`
  - `get_timeline_tracks` (resource) → `timeline(action="get_track_count")` + `timeline(action="get_items_in_track")`
  - `create_empty_timeline` → `media_pool(action="create_timeline")`
  - `delete_timeline` → `media_pool(action="delete_timelines")`
  - `add_marker` (granular timeline tool) → `timeline_markers(action="add")`
  - `add_clip_to_timeline` → `media_pool(action="append_to_timeline")`
  - `apply_lut` (granular graph tool) → `graph(action="set_lut")`
  - `copy_grade` → `timeline_item_color(action="copy_grades")`
  - `get_render_presets` (resource) → `render(action="list_presets")`
  - `add_to_render_queue` → `render(action="add_job")`
  - `start_render` (granular project tool) → `render(action="start")`
  - `get_render_queue_status` (resource) → `render(action="list_jobs")` + `render(action="get_job_status")`
  - `clear_render_queue` (granular project tool) → `render(action="delete_all_jobs")`
  - `create_sub_clip`, `get_current_color_node`, `get_color_wheel_params`, `set_color_wheel_param`, `add_node`: removed — these wrapped undocumented Resolve methods that were never exposed in the official scripting API. No replacement exists; use the Resolve UI for now.

## v2.3.1

- **Positioned `AppendToTimeline` via `clip_infos`** — `media_pool(action="append_to_timeline", params={"clip_infos": [...]})` now exposes the documented `MediaPool.AppendToTimeline([{clipInfo}, ...])` overload, accepting per-entry `clip_id`/`media_pool_item_id`, `start_frame`, `end_frame`, `record_frame`, `track_index`, and optional `media_type`. Each appended item returns its `timeline_item_id` for follow-up Fusion ops
- **Positioned append failure reporting** — the same call now returns `{"error": ...}` when Resolve fails to produce valid timeline items, including falsey `AppendToTimeline()` results and returned item handles without a timeline item id
- **Live disposable Resolve validation** — verified the fix against DaVinci Resolve Studio 20.3.2 with synthetic temp media in a disposable project: valid `clip_infos` append returned `success`, `count=1`, and `timeline_item_id`; invalid `clip_infos` calls returned errors

## v2.3.0

- **Resolve 20.2.2 API sync** — added the 12 scripting methods introduced across Resolve 20.0-20.2.2, with compatibility guards so older Resolve builds return clear "requires Resolve 20.x" errors instead of crashing
- **Resolve 20 live validation** — revalidated the new API surface against DaVinci Resolve Studio 20.3.2, bringing live-tested coverage to 331/336 methods (98.5%)
- **Official scripting docs refreshed** — `docs/reference/resolve_scripting_api.txt` now tracks the Resolve 20 scripting README bundled with the installed 20.3.2 developer package
- **AI skill reference updated** — merged PR #30's `docs/SKILL.md` and updated it for the Resolve 20 method count, granular server, version guards, and source media integrity guidance
- **Stale Resolve handle recovery** — both server modes now validate cached Resolve handles and reconnect cleanly after Resolve restarts or Project Manager transitions

## v2.2.0

- **Granular server modularized internally** — `src/resolve_mcp_server.py` is now a thin entrypoint, with the granular implementation split across `src/granular/resolve_control.py`, `project.py`, `timeline.py`, `timeline_item.py`, `media_pool.py`, `folder.py`, `media_pool_item.py`, `gallery.py`, `graph.py`, and `media_storage.py`
- **Installer now emits env blocks for every generated stdio config** — standard `.mcp.json`, VS Code `.vscode/mcp.json`, Zed `context_servers`, and manual snippets now include `RESOLVE_SCRIPT_API`, `RESOLVE_SCRIPT_LIB`, and `PYTHONPATH`
- **Windows Resolve 20.3 hardening** — on Windows, the installer also emits `PYTHONHOME` derived from the selected interpreter's base install so Resolve binds against the intended Python instead of a newer globally registered one
- **Windows stdio transport hardening** — server entrypoints now run FastMCP through strict LF-only stdio wrappers to avoid client disconnects caused by platform newline translation in Windows pipes
- **`set_cdl` accepts arrays cleanly** — both compound and granular servers now normalize JSON array, tuple, and numeric CDL values into Resolve's required string form like `"1.0 1.0 1.0"`
- **`fusion_comp` can target timeline item comps** — node graph actions can now operate on a clip's Fusion comp via `clip_id`, `timeline_item_id`, or `timeline_item`, and `bulk_set_inputs` applies scoped input changes across multiple timeline comps
- **`python src/server.py --full` now stays intact** — the compound entrypoint now correctly launches the granular server instead of importing it and exiting

## v2.1.0

- **New `fusion_comp` tool** — 20-action tool exposing the full Fusion composition node graph API. Add/delete/find nodes, wire connections, set/get parameters, manage keyframes, control undo grouping, set render ranges, and trigger renders — all on the currently active Fusion page composition
- **`timeline_item_fusion` cache actions** — added `get_cache_enabled` and `set_cache` actions for Fusion output cache control directly on timeline items
- **Fusion node graph reference** — docstring includes common tool IDs (Merge, TextPlus, Background, Transform, ColorCorrector, DeltaKeyer, etc.) for discoverability

## v2.0.9

- **Cross-platform sandbox path redirect** — `_resolve_safe_dir()` now handles macOS (`/var/folders`, `/private/var`), Linux (`/tmp`, `/var/tmp`), and Windows (`AppData\Local\Temp`) sandbox paths that Resolve can't write to. Redirects to `~/Documents/resolve-stills` instead of Desktop
- **Auto-cleanup for `grab_and_export`** — exported files are read into the response (DRX as inline text, images as base64) then deleted from disk automatically. Zero file accumulation. Pass `cleanup: false` to keep files on disk
- **Both servers in sync** — `server.py` and `resolve_mcp_server.py` now share the same version and both use `_resolve_safe_dir()` for all Resolve-facing temp paths (project export, LUT export, still export)

## v2.0.8

- **New `grab_and_export` action on `gallery_stills`** — combines `GrabStill()` + `ExportStills()` in a single atomic call, keeping the live GalleryStill reference for reliable export. Returns a file manifest with exported image + companion `.drx` grade file
- **Format fallback chain** — if the requested format fails, automatically retries with tif then dpx
- **macOS sandbox path redirect** — `/var/folders` and `/private/var` paths are redirected to `~/Desktop/resolve-stills` since Resolve's process can't write to sandboxed temp directories
- **Key finding documented** — `ExportStills` requires the Gallery panel to be visible on the Color page. All 9 supported formats (dpx, cin, tif, jpg, png, ppm, bmp, xpm, drx) produce a companion `.drx` grade file alongside the image

## v2.0.7

- **Security: path traversal protection for layout preset tools** — `export_layout_preset`, `import_layout_preset`, and `delete_layout_preset` now validate that resolved file paths stay within the expected Resolve presets directory, preventing path traversal via crafted preset names
- **Security: document destructive tool risk** — added Security Considerations section noting that `quit_app`/`restart_app` tools can terminate Resolve; MCP clients should require user confirmation before invoking

## v2.0.6

- **Fix color group operations crash** — `timeline_item_color` unpacked `_check()` as `(proj, _, _)` but `_check()` returns `(pm, proj, err)`, so `proj` got the ProjectManager instead of the Project, crashing `assign_color_group` and `remove_from_color_group`

## v2.0.5

- **Lazy connection recovery** — full server (`--full` mode) now auto-reconnects and auto-launches Resolve, matching the compound server behavior
- **Null guards on all chained API calls** — `GetProjectManager()`, `GetCurrentProject()`, `GetCurrentTimeline()` failures now return clear errors instead of `NoneType` crashes
- **Helper functions** — `get_resolve()`, `get_project_manager()`, `get_current_project()` replace 178 boilerplate blocks

## v2.0.4

- **Fix apply_grade_from_drx parameter** — renamed `mode` to `grade_mode` to match Resolve API; corrected documentation from replace/append to actual keyframe alignment modes (0=No keyframes, 1=Source Timecode aligned, 2=Start Frames aligned)
- **Backward compatible** — still accepts `mode` for existing clients, `grade_mode` takes precedence

## v2.0.3

- **Fix GetNodeGraph crash** — `GetNodeGraph(0)` returns `False` in Resolve; now calls without args unless `layer_index` is explicitly provided
- **Falsy node graph check** — guard checks `not g` instead of `g is None` to catch `False` returns

## v2.0.2

- **Antigravity support** — Google's agentic AI coding assistant added as 10th MCP client
- **Alphabetical client ordering** — MCP_CLIENTS list sorted for easier maintenance

## v2.0.1

- **26-tool compound server** — all 324 API methods grouped into 26 context-efficient tools (default)
- **Universal installer** — single `python install.py` for macOS/Windows/Linux, 10 MCP clients
- **Dedicated timeline_item actions** — retime/speed, transform, crop, composite, audio, keyframes with validation
- **Lazy Resolve connection** — server starts instantly, connects when first tool is called
- **Bug fixes** — CreateMagicMask param type, GetCurrentClipThumbnailImage args, Python 3.13+ warning
