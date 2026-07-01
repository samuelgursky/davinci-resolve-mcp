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
| `place_fusion_title` | Text+ on a chosen track. Options: `text, font, style, size, vJustify, hJustify, color:{r,g,b}`, `trackIndex`, `startFrame`, `durationFrames` |
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
`InsertFusionTitleIntoTimeline` takes no track arg (always the lowest unlocked video track). Bypass:
via computer-use, **lock the video tracks below your target**, then call `timeline.insert_fusion_title` —
it lands on the chosen track. Verified live. (For export-based workflows, `place_fusion_title` does this
offline.)

---

## What's mapped (honest scope)

**Fully mapped (read + write, round-trips byte-for-byte):** project packaging; tracks
(`Sm2TiTrack`+Type+Sequence); clips; source in-points (`<In>`); Fusion titles
(text/font/style/size/justify/color); generators; transitions; markers; grades (full DRX body);
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

**Limit:** media authoring is h264-only (cross-codec needs a per-codec template).
