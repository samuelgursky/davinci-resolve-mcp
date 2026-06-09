# Timeline Conform / Interchange Kernel

The Timeline Conform / Interchange kernel expands `timeline` into a safer
structure, source-range, gap/overlap, interchange, comparison, missing-media,
and relink-planning layer.

Live validation was run against DaVinci Resolve Studio 20.3.2.9 with a
disposable `_mcp_timeline_conform_probe_*` project and generated synthetic
video/audio media. Final release probe counts:

| Status | Count |
| --- | ---: |
| `supported` | 17 |
| `partially_supported` | 1 |
| `unsupported` | 0 |
| `version_or_page_dependent` | 0 |
| `not_applicable` | 0 |
| `error` | 0 |

The partially supported result was FCPXML round-trip survival: export and import
both worked, but the imported timeline did not preserve MediaPoolItem-name
linkage in the comparison snapshot. DRT round-trip matched exactly.

## Added Actions

All actions are exposed through `timeline`.

| Action | Purpose |
| --- | --- |
| `conform_capabilities` | Return structure, analysis, interchange, relink-planning, and source-media safety boundaries. |
| `probe_timeline_structure` | Snapshot timeline identity, track counts, items, source ranges, media file paths, markers, and optional clip properties. |
| `detect_gaps_overlaps` | Report same-track gaps and overlaps from the current timeline snapshot. |
| `source_range_report` | Group source frame ranges by MediaPoolItem/file path, with optional handles and merging. |
| `export_timeline_checked` | Resolve export aliases and guard timeline export paths to temp locations by default. |
| `import_timeline_checked` | Guard timeline imports from temp locations and normalize import options. |
| `compare_timelines` | Compare current timeline to another timeline or two supplied snapshots. |
| `probe_interchange_roundtrip` | Export, import, compare, and optionally delete the imported timeline. |
| `detect_missing_media` | Detect missing/offline media using Resolve status fields and file-path existence, with a sanitized diagnosis block for mounted-volume/folder/file failure modes. |
| `build_relink_plan` | Read-only, bounded search-root scan for relink candidates by missing file basename. Skips broad scans by default when the source volume is not mounted. |
| `conform_boundary_report` | Return capabilities, timeline structure, gaps/overlaps, source ranges, and missing-media summary. |

## Interchange Matrix

| Format Alias | Export | Round Trip | Notes |
| --- | --- | --- | --- |
| `drt` | Supported | Supported | DRT export/import compared with zero differences in the live probe. |
| `fcpxml` | Supported | Partially supported | Resolve exported a folder containing `Info.fcpxml`; import worked after resolving the primary file, but MediaPoolItem-name linkage was not preserved. |
| `edl` | Supported | Not forced in release probe | Export succeeded to temp path. EDL round trips can be lossy by design. |
| `aaf` | Supported | Not forced in release probe | Export succeeded to temp path. AAF options and media relink behavior are build/content dependent. |
| `otio` | Supported | Not forced in release probe | Export succeeded to temp path. |

Supported aliases include `aaf`, `drt`, `edl`, `edl_cdl`, `edl_sdl`,
`edl_missing_clips`, `fcp7xml`, `fcpxml`, `fcpxml_1_8`, `fcpxml_1_9`,
`fcpxml_1_10`, and `otio`.

## Supported Findings

- Timeline structure snapshots worked across video, audio, and subtitle track
  categories.
- Same-track gap detection found the deliberate 24-frame video gap in the
  generated timeline.
- Source range reporting grouped generated media paths with requested handles.
- Guarded exports succeeded for FCPXML, DRT, EDL, AAF, and OTIO.
- FCPXML directory-style exports are normalized with a `primary_file` path.
- DRT export/import/compare round-trip succeeded and cleaned up the imported
  timeline.
- Synthetic-only unlink, missing-media detection, relink candidate planning,
  and safe relink all worked through generated media.

## Boundaries

- Interchange formats are not semantically equivalent. DRT is the strongest
  project-native round-trip path; EDL and FCPXML can lose Resolve-specific
  relationships.
- The public API exposes timeline items, source ranges, markers, and some media
  references, but not full transition/effect/retime semantics for every format.
- `build_relink_plan` is intentionally read-only. It deduplicates missing
  basenames, supports `max_depth`, `max_seconds`, and `max_files_scanned`, and
  skips broad scans by default when a source volume such as a camera card is not
  mounted. Execute relinks through `media_pool.safe_relink` only with synthetic
  or explicitly approved paths.
- Missing-media status fields vary by Resolve build. The kernel combines status
  text with local file existence when a file path is available.
- Export and import helpers require temp paths by default because they write
  interchange artifacts.

## Live Probe

Run the live boundary probe with:

```bash
python3.11 tests/live_timeline_conform_validation.py --output-dir /tmp/timeline-conform-probe
```

The harness creates a disposable project, generates synthetic media, builds a
gapped timeline, probes structure, source ranges, gap/overlap detection,
interchange export/import/round-trip behavior, synthetic missing-media relink
planning, writes JSON and Markdown reports, deletes the project, and removes
generated media.

Use `--keep-open` only when you intentionally want to inspect the disposable
project by hand.
