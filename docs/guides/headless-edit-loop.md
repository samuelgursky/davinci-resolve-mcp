# Building edits headless: the iterative loop

How to drive Resolve entirely from the command line to import media, link it,
assemble a cut, and then round-trip that cut repeatedly — with the format and
option choices justified by measurement rather than habit.

Everything here was measured on Resolve Studio 19.1.3.7 in **both** GUI and
`-nogui` sessions on 2026-08-01. Regenerate with `scripts/roundtrip_matrix.py`;
the raw runs are in `docs/reference/evidence/`.

## The short answer

**Mode does not matter.** Every result below is byte-identical between GUI and
`-nogui` — the flat round trip, the complex-cut round trip, and the moved-media
relink. Choose a format on its properties, never on whether you have a UI.

**There is no single best format.** Three measurements pull in different
directions, and the right choice depends on which one you are up against:

| what you need | format | why |
| --- | --- | --- |
| **Full fidelity**, media staying put | **DRT** | the only format that kept *everything*: transforms, colours, flags, item and timeline markers |
| **Iterative loop**, media staying put | **FCP7 XML** or AAF | no media duplication, controllable timeline name — DRT has neither |
| **Media has MOVED** (real conform) | **FCP7 XML**, AAF, FCPXML 1.10 | the only three that relink. **DRT, OTIO and EDL all fail** |

The trap is that DRT looks like the obvious choice — it is native and it is the
only format that survives a rich cut intact — and it is the *worst* choice for
both of the other two jobs. It re-imports its media every time, and it cannot
relink media that has moved at all.

**For an iterative loop, use FCP7 XML (or AAF) with:**

```python
options = {
    "timelineName": f"CUT_v{iteration:03d}",   # MUST be unique per import
    "importSourceClips": False,                 # reuse the pool, do not re-import
    "sourceClipsFolders": [pool.GetRootFolder()],
}
timeline = pool.ImportTimelineFromFile(path, options)
```

Verified: five consecutive imports, all succeeded, source in-points preserved
exactly, and **no media duplicated** — the media pool grew by exactly one item
per import, which is the imported timeline itself, not another copy of the
footage.

## The traps, each measured

### A repeated `timelineName` silently stops working

Importing the same file three times with the *same* `timelineName`:

| import | result |
| --- | --- |
| 1 | succeeded, timeline `ITER_FIXED` |
| 2 | **returned None** |
| 3 | **returned None** |

No error, no exception — `ImportTimelineFromFile` just returns None once the
name is taken. An iterative loop that reuses one name works exactly once and
then quietly does nothing, which is the worst possible failure for an automated
edit cycle. Make the name unique per iteration.

### A unique `timelineName` is still not enough — the file's internal name wins

Resolve honours the sequence name **inside** the interchange file over the
`timelineName` option (issue #171, measured on Studio 21.0.4.5). Export → edit
→ re-import with `timelineName: CUT_v002` while the XML still says `CUT_v001`
and Resolve hands back the **existing** `CUT_v001` timeline: the raw API
reports the old timeline as if it were the import, and the loop operates on one
timeline forever. When driving the raw API, bump the `<sequence><name>` inside
the XML each iteration.

`timeline.import_timeline_checked` handles both halves for you: it rewrites the
FCP7 XML's internal sequence name to the requested `timelineName` before
importing, and if a format it cannot rewrite still returns an existing timeline
it errors instead of reporting success.

### DRT ignores `timelineName` and re-imports the media

DRT is the native format and the obvious first choice, but it behaves
differently on import, in ways the documentation states but that are easy to
miss:

- `timelineName`, `importSourceClips` and `sourceClipsFolders` are **all invalid
  for DRT**. Passing them gets you a failure that says nothing about the format.
- The imported timeline is named after the **file**, not the timeline inside it,
  and repeated imports auto-uniquify: `iter`, `iter 2`, `iter 3`.
- Because `importSourceClips` cannot be set to False, each DRT import **adds
  another copy of the source media** to the pool. Measured: three DRT imports
  grew the pool by four items, against one per import for the XML route.

So DRT is excellent for a one-shot hand-off and wrong for a loop that runs a
hundred times.

### FCPXML 1.10 exports a *directory*, not a file

`Timeline.Export(path, EXPORT_FCPXML_1_10, EXPORT_NONE)` returns True and
creates a **bundle directory** at `path` containing `Info.fcpxml` — the
`.fcpxmld` shape Final Cut uses. Consequences:

- `path.stat().st_size` reports the directory inode (96 bytes here), so a
  size check reads it as a near-empty export.
- `ImportTimelineFromFile(path)` fails, because the path is a directory.

Point the import at the member instead, and the format round-trips exactly:

```python
inner = next(Path(export_path).glob("*.fcpxml"))     # Info.fcpxml
pool.ImportTimelineFromFile(str(inner), options)
```

This is why the first round-trip run reported FCPXML 1.10 as import-failed in
both modes. It was the harness, not the format.

### OTIO with `importSourceClips: False` arrives fully offline

Every other format relinks against the existing pool. OTIO does not: with
`reuse_pool` the timeline rebuilds with correct structure and **all four items
offline**, in both modes. With `importSourceClips: True` and a `sourceClipsPath`
it links correctly. If you want OTIO, re-import the sources.

## What each format actually keeps

The flat single-track round trip found every format frame-exact — because a flat
cut of untouched clips gives them nothing to disagree about. On a real cut (two
video tracks, audio, a per-item transform, clip colours, flags, item and timeline
markers) they diverge sharply. Identical in both modes:

| format | cut | tracks | transform | colour | flags | item markers | timeline markers |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **drt** | kept | kept | **kept** | **kept** | kept | **kept** | kept |
| fcpxml_1_10 | kept | **lost an audio track** | kept | lost | kept | lost | lost |
| fcp7xml | kept | kept | lost **only FlipX** | lost | kept | lost | lost |
| aaf | kept | kept | **lost: all reset to defaults** | lost | kept | lost | kept |
| otio | **lost: source** | kept | kept | lost | lost | kept | kept |
| edl | **lost** | **1v1a** | n/a | lost | lost | lost | lost |

Two details worth having:

- **AAF resets the entire transform to defaults**, while **FCP7 XML preserves
  zoom, pan and rotation exactly** and drops only `FlipX`. A whole-dict
  comparison called both "lost", which is the same word for "carries geometry"
  and "does not". Crop comes back as 39.999936 against 40.0 — that is unit
  round-tripping, not loss.
- **FCPXML 1.10 silently drops an audio track** (2v2a in, 2v1a out).

## Relinking media that has moved

The test that matters for conform: build the cut, export it, **rename the media
directory** so every baked-in path is dead, then import in a fresh project with
`sourceClipsPath` pointing at the new location. Identical in both modes:

| format | relinked | cut still frame-exact |
| --- | --- | --- |
| fcp7xml | **3/3** | yes |
| aaf | **3/3** | yes |
| fcpxml_1_10 | **3/3** | yes |
| drt | **0/3** — items stay pointing at the dead path | yes (but offline) |
| edl | **0/3** | yes (but offline) |
| otio | **import returned None** — fails outright | — |

`sourceClipsPath` is not valid for DRT, so DRT has no mechanism to be told where
the media went. EDL carries reel names rather than paths and did not resolve
either. OTIO did not merely fail to relink — the import returned `None`.

Note that "frame-exact" stays true even where nothing relinked: the *cut*
survives offline. That is worth knowing, because it means a failed relink leaves
a correct timeline you can relink by other means, rather than a wrong one.

## Format selection

All are frame-exact in both modes; these are the tie-breakers. Payload sizes are
for the same four-item test timeline.

| format | size | links from pool | name controllable | notes |
| --- | --- | --- | --- | --- |
| **fcp7xml** | 42 KB | yes | yes | the recommended loop format |
| **aaf** | 315 KB | yes | yes | same behaviour, 7x the payload |
| **edl** | 512 B | yes | yes | astonishingly, frame-exact — see below |
| drt | 19 KB | n/a (always re-imports) | no | native; one-shot hand-off |
| otio | 85 KB | **no — offline** | yes | needs `importSourceClips: True` |
| fcpxml_1_10 | 3 KB | yes | yes | writes a bundle directory |

**On EDL:** 512 bytes round-tripped frame-exactly with media linked, which is not
what EDL's reputation suggests. It works here because the test media carries
embedded timecode (`-timecode 01:00:00:00`) and the sources relink by name. EDL
carries no effects, no multiple tracks, and no speed changes — so this result
means "EDL is sufficient for a flat single-track conform of timecoded media",
not "EDL is a good interchange format". Do not generalise it to a real cut.

## The whole loop, headless

```bash
# 1. one Resolve, no UI, and confirm nothing else holds the singleton
python scripts/resolve_headless.py guard
python scripts/resolve_headless.py start
```

```python
# 2. import media and build the initial cut through the API, not a file.
#    AppendToTimeline with explicit clipInfo dicts is frame-exact and needs no
#    interchange format at all.
clips = resolve.GetMediaStorage().AddItemListToMediaPool(paths)
timeline = pool.CreateEmptyTimeline("CUT_v001")
project.SetCurrentTimeline(timeline)
pool.AppendToTimeline([
    {"mediaPoolItem": clips[0], "startFrame": 0,  "endFrame": 191},
    {"mediaPoolItem": clips[1], "startFrame": 24, "endFrame": 71},
])
```

Two things about that call, both measured and both able to waste a session:

- **`endFrame` is inclusive-of-the-last-frame here** — pass `frames` rather than
  `frames - 1` and you append nothing.
- **Do not build a repeated clip with `CreateTimelineFromClips([clip] * n)`.** It
  deduplicates identical MediaPoolItem references: fifteen copies produced a
  one-copy timeline, returned a valid Timeline, and reported no error. Use
  `AppendToTimeline` with one dict per instance, and assert the resulting frame
  count.

```python
# 3. iterate: export, mutate outside Resolve, re-import under a NEW name
timeline.Export(str(path), resolve.EXPORT_FCP_7_XML, resolve.EXPORT_NONE)
...                                            # edit the XML however you like
pool.ImportTimelineFromFile(str(path), {
    "timelineName": f"CUT_v{n:03d}",
    "importSourceClips": False,
    "sourceClipsFolders": [pool.GetRootFolder()],
})
```

```bash
# 4. done
python scripts/resolve_headless.py stop
```

## Rules that apply to the whole loop

- **Never call `SaveProject()` without checking the project name.** On the
  never-saved `Untitled Project` it blocks the entire application — in both
  modes — and needs a force-kill. Use
  `src/utils/project_cleanup.py:save_project_if_safe`.
- **Verify structure, not return values.** Every finding above involved a call
  that returned success. After building or importing a cut, read the item count
  and each item's `GetLeftOffset()` back and compare against what you intended.
- **Teardown order is `CloseProject` → `LoadProject(something named)` →
  `DeleteProject`.** `CloseProject` is what releases the session lock, and
  landing on the unsaveable default project is what raises the next modal.
- Capability is identical headless, but **stability under long renders is not
  established** — see the limits section in
  [headless-cli.md](../reference/headless-cli.md).
