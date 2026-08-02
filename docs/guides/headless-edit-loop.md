# Building edits headless: the iterative loop

How to drive Resolve entirely from the command line to import media, link it,
assemble a cut, and then round-trip that cut repeatedly — with the format and
option choices justified by measurement rather than habit.

Everything here was measured on Resolve Studio 19.1.3.7 in **both** GUI and
`-nogui` sessions on 2026-08-01. Regenerate with `scripts/roundtrip_matrix.py`;
the raw runs are in `docs/reference/evidence/`.

## The short answer

**Mode does not matter.** All six interchange formats round-trip
frame-accurately in headless exactly as they do in the GUI — see
[roundtrip-fidelity.md](../reference/roundtrip-fidelity.md). Choose a format on
its other properties, not on whether you have a UI.

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
