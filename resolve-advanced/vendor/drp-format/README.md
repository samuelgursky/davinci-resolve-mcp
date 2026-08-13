# drp-format — offline DaVinci Resolve project authoring & editing

Read, author, and edit **real, importable** DaVinci Resolve 21 projects (`.drp`) and timelines
(`.drt`) as files — no Resolve required. Everything here is verified by a live round-trip
(author/edit → `import_project` → `lint`/`clip_where` → re-export decode), not just self-parse.

Background + the full schema map: `docs/design/drp-drx-drt-closeout-harness/knowledge/resolve21-schema-reconciliation.md`
and `.../resolve-authoring-completion.md`.

> **Key fact:** a `.drp`/`.drt` is a zip of `SeqContainer/<uuid>.xml` (+ `MpFolder.xml`, `project.xml`,
> `Gallery.xml`). A clip's track is just which `<Sm2TiTrack>` it sits under. Source in-points live in
> `<In>` (timeline frames). Resolve links media by the path **inside the Media Pool blob**, not the
> timeline's `<MediaFilePath>`, and does **not** reconform on import — so cached specs must match.

---

## MCP actions

### `drt` tool — timeline format

| Action | Purpose |
|---|---|
| `parse` | `.drt`/`.drp` → `{ timelines, metadata }` (reads real Resolve exports) |
| `author` | spec → `.drt` |
| `validate` | structural check |
| `inject_into_drp` / `extract_from_drp` | graft / pull a SeqContainer |

### `drp` tool — project authoring + editing (all offline/local unless noted)

**Author from scratch**
| Action | What it does |
|---|---|
| `create_empty_project` | fresh `.drp`, one empty timeline → `{ buffer, startFrame: 86400 }` |
| `assemble_timeline` | declarative spec `{ timelineName, elements:[{type:'title'\|'generator', track, startFrame, …}], transitions }` → importable project |
| `add_media_clip` | one media clip from an arbitrary **h264** file: `{ mediaFile, spec:{width,height,frameCount,fps}, timelineName?, durationFrames? }` |

**Place elements (track-targeted — the #74 bypass, offline)**
| Action | What it does |
|---|---|
| `place_fusion_title` | ⚠️ **INERT on 21.0.4.5 — placed but not rendered, see below.** Text+ on a chosen track. Options: `text, font, style, size, vJustify, hJustify, color:{r,g,b}`, `trackIndex`, `startFrame`, `durationFrames` |
| `place_generator` | built-in generator (`generatorName`, e.g. "Solid Color") on a chosen track |
| `place_transition` | cross-dissolve at an abutting cut (`track`, `atFrame`, `durationFrames`) — clips need handle media |

**Edit in place (video or audio via `trackType`)**
| Action | What it does |
|---|---|
| `move_clip` | relocate a clip to another track / new `toStart` |
| `delete_clip` | remove a clip; `ripple` closes the gap on that track |
| `trim_clip` | tail-trim `newDuration`; `ripple` shifts later clips |
| `trim_clip_head` | head trim — advances the source `<In>`; `ripple` keeps Start |
| `split_clip` | razor at `atFrame` → two source-continuous clips |
| `ripple_timeline` | cross-track ripple — shift all clips ≥ `at` by `delta` (video+audio, keeps sync) |

**Media (conform / relink)**
| Action | What it does |
|---|---|
| `relink_media` | repoint media paths in the Media Pool blobs + plain text (`mappings:[{from,to}]`) |
| `repoint_media` | relink **+ fix cached specs** (res/frames/fps) for a differently-formatted file (`{from,to,fromSpec,toSpec}`) |

**Grades + analysis (server/local)**
| Action | What it does |
|---|---|
| `inject_grades` | apply DRX grades into a `.drp` |
| `extract_node_graphs` | pull per-clip grade `<Body>` blobs as DRX envelopes |
| `diff` | structural diff of two `.drp`s |
| `validate` / `validate_async` / `status` | DRP validation (server) |

> Clip selectors on the edit ops: `clipIndex` (0-based), `clipDbId`, or `nameContains`.

---

## Library functions (`require('drp-format')`)

Same surface as the MCP actions, returning `{ buffer, … }`:
`createEmptyProject`, `assembleTimeline`, `addMediaClip`, `placeFusionTitle`, `placeGenerator`,
`placeTransition`, `moveClip`, `deleteClip`, `trimClip`, `trimClipHead`, `splitClip`, `rippleTimeline`,
`relinkMedia`, `repointMedia`, `injectGrades`, `diff`.

Title text/style codec: `decodeTitleInputs`, `setTitleInputs`, `decodeTitleText`, `setTitleText`.
Shared surgery primitives: `seq-surgery.js`. Title-comp codec: `composition-text.js`.
Plus the full **DRX grade** surface (`createSimpleGrade`, curves/qualifiers/windows/node-tree encoders).

`drt-format` re-exports the timeline-only surface: `parseDRT`, `buildDRT`, `validateDRT`.

---

## Live-edit recipe (the one thing that needs Resolve running)

**#74 — insert a Text+/generator on a chosen track of the OPEN timeline.** The API's
`InsertFusionTitleIntoTimeline` takes no track arg; the insert lands on the Source/Auto Track
Selector's current target (V1 in practice), which no API can read or set.

> **Track locking does not redirect the insert — through the API *or* the UI.** An earlier
> revision of this README claimed that locking the tracks below your target via computer-use
> redirects the insert, and called it verified live. That claim shipped with no test or evidence
> and is **withdrawn as false.** Measured 2026-08-12 on **Studio 21.0.4.5** (version read live,
> not assumed), one fresh 3-video-track timeline per arm so no insert could fail on a collision:
>
> | Arm | Setup | `InsertFusionTitleIntoTimeline("Text+")` |
> |---|---|---|
> | A | nothing locked | lands on **V1** |
> | B | V1 locked via `Timeline.SetTrackLock` | returns **None**, nothing placed |
> | C | V1 locked by **clicking the padlock in the UI** | returns **None**, nothing placed |
> | D | nothing locked, source patch dragged to V2 in the UI | lands on **V2** |
>
> B and C are identical, so the GUI-lock hypothesis is dead: locking blocks the target, it never
> re-targets. This also reproduces issue #74 (measured on 21.0.0) on the newest build.
>
> **D is the real control.** The destination is the Edit-page patch panel, not the lock state.
> Dragging the source patch onto V2 sends the insert to V2. In the header, the x-column of
> per-track badges is the auto-track-selector toggle; the source patch badge appears only on the
> patched track, and dragging it is what re-targets. The API can neither read nor set any of it —
> which is exactly the gap to put in front of Blackmagic, and a far smaller ask than new
> parameters on all six `Insert*IntoTimeline` methods.
>
> So a live-edit recipe does exist, but it is **GUI automation of the patch panel**, not track
> locking. Treat it as such: it is not verifiable from the API side, since nothing in the
> scripting surface can confirm the selector landed where you dragged it.

> ⚠️ **`place_fusion_title` currently produces an INERT title — do not use it for this.**
> Measured on Studio 21.0.4.5: the placed clip is structurally perfect (right track, frame and
> duration, `PrettyType` = `Fusion Title`, and the text really is written into the
> `CompositionBA` — it decodes back), but **Resolve never instantiates the comp**. The imported
> item reports `GetFusionCompCount() == 1` while `GetFusionCompByIndex(1).GetToolList()` is
> **empty** (a live-inserted Text+ returns `['Template','MediaOut1']`), the Inspector's Title tab
> is blank, and the viewer renders nothing. Reproduced four ways: alone, in an edit chain, onto a
> bundled-template base, and onto a genuine 21.0.4.5 export. Ruled out so far — template staleness
> (the bundled clip element is structurally identical to a real one: same tags, size differing
> only by text length) and DbId rewriting (the comp blobs contain no DbId references). Root cause
> open. Use the live nested-timeline route until this is fixed.
>
> **The defect is specific to the Fusion-comp path, not to clone-a-template.** `place_generator`,
> built the same way, works: an imported Solid Color shows a populated `Generator - Solid Color`
> Inspector with a live Color parameter and renders on the timeline. The difference is where the
> parameters live — a generator's are a protobuf `EffectFiltersBA`, which Resolve reads happily,
> while a title's are a `CompositionBA` Fusion-comp blob, which it does not instantiate. That is
> the narrowest place to start looking.

---

## What's mapped (honest scope)

> **Read "mapped" as file-level fidelity, not as "Resolve honours it."** Those are different
> claims and this README conflated them. `place_fusion_title` round-trips byte-for-byte and its
> text decodes back correctly, yet Resolve builds no comp from it (see the ⚠️ above). A blob that
> survives a write/read cycle has been *encoded* correctly; only a live import proves it is
> *instantiated*. Everything below is the first claim. The second is only established where an
> entry says it was measured against a running Resolve build.

**Fully mapped (read + write, round-trips byte-for-byte):** project packaging; tracks
(`Sm2TiTrack`+Type+Sequence); clips; source in-points (`<In>`); Fusion titles
(text/font/style/size/justify/color — **encoded correctly but not instantiated by Resolve 21.0.4.5;
see the ⚠️ above**); generators; transitions; markers; grades (full DRX body);
media path + resolution + frame-count + fps. **Plus the full Media-Pool metadata layer:** the
keyed-dict format (`Geometry`/`Time`/`VideoMetadata`/`Proxy`/audio/small `FieldsBlob`) with typed
values (`keyed-dict.js`); audio config (`TracksBA`/`VirtualAudioTrackBA` → sample-rate/channels/codec
via `readAudioTracks`); the protobuf blobs `Radiometry` + transition/generator `EffectFiltersBA`
(wire-level, `protobuf-wire.js`); and `MediaTimemapBA` retime — both the 1× compact form and the
retimed `Sm2TimeMap` keyed-dict, including **dynamic/variable-speed ramps** (KeyframesBA = repeated
`(record,source)` points; per-segment speed = Δsource/Δrecord), decoded *and* authorable
(`media-timemap.js`, `buildConstantSpeedTimemap` / `buildTimemap`).

**Carried verbatim (cloned, not byte-decoded — Resolve accepts, never authored):** zstd-compressed
internal-state/cache `FieldsBlob`s (`classifyBlob` flags them; Node has no built-in zstd); the
protobuf blobs' *field names* (wire structure is decoded; names need Resolve's private `.proto`); the
Fusion comp beyond the title inputs we edit.

**Nested sequences — compounds AND nested timelines (`compound-nav.js`):** enumerate, walk
into, and rewrite title text inside either. **A compound clip and a nested timeline are the same
shape on disk:** both appear in `MediaPool/Master/MpFolder.xml` as a media-pool element
(`Sm2MpCompoundClip` / `Sm2MpTimelineClip`) carrying an inline `<Sequence><Sm2Sequence DbId="X">`,
and the `SeqContainer/<uuid>.xml` whose tracks carry `<Sequence>X</Sequence>` holds the contents.
The join is on that **Sm2Sequence DbId, not the container's own DbId** — the container id is
referenced by nothing else in the package. One asymmetry worth knowing: a compound's contents are
rebased to `Start` 0, while a nested timeline's keep timeline-absolute TC.

> This is the one place the offline tier beats the live API outright. `MediaPoolItem.GetTimeline()`
> (21.0.4+) resolves through the timeline handle: it returns the inner Timeline for
> `Type='Timeline'` and **`None` for `Type='Compound'`**, and a compounded Text+ reports
> `GetFusionCompCount() == 0`. So compounding a title severs its text permanently as far as
> scripting is concerned. Offline the distinction does not exist. Verified end to end on Studio
> 21.0.4.5: text rewritten offline inside a compound, imported, re-exported by Resolve, and read
> back **from Resolve's own export** unchanged.

**Limit:** media authoring is h264-only (cross-codec needs a per-codec template).
