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

## When Resolve is unreachable

An unreachable Resolve used to end the work. It no longer has to: `timeline` serves two
actions **above** the connection check, and every not-connected error carries an
`offline_alternative` block naming them.

- `author_offline(clips[], output_path, target?, name?, fps?, start_timecode?,
  resolution?)` — write an importable timeline from a file-path clip plan.
  Targets, in preference order:
  - **`drt`** (default) — Resolve-native, carries track structure. Stamped at project
    version 17 (Resolve 21.0); older builds need the advanced server's
    `drt(action='downgrade')`. Verified map: 18.0.4 → 11, 19.1.x → 14, 21.0 → 17.
  - **`otio`** — round-trips through this repo's own parser and carries gaps, per-clip
    speed, and transitions. The target to pick when the plan has retimes.
  - **`edl`** — CMX3600: video cuts and M2 speed, nothing else.
- `offline_fallback_capabilities()` — whether authoring is available here, and why not
  if it is not.

Frame numbers are at the timeline rate and `end_frame` is **EXCLUSIVE**, matching
`AppendToTimeline`'s half-open range.

**It is an offer, not a substitute.** A caller who asked to build a timeline *in Resolve*
has not succeeded because a file was written. The connection error stays an error, the
block says outright that authoring does not complete what failed, and nothing is authored
unless someone asks for it.

Two warnings the result can carry, both for failures that are otherwise silent:

- `media_tc_origin_assumed` — OTIO source frames are **timecode-absolute**. An event with
  no media timecode origin imports as an *empty* timeline: the file opens, nothing
  appears, no error is raised. Pass `media_start_tc_frame` (or an absolute
  `src_tc_frame`) per clip. Every event that had to assume is named.
- `retimes_flattened` — a `.drt` has no per-clip speed field, so retimes flatten to 100%
  forward. Every event that lost one is named; author OTIO to keep them.

Authoring runs in Node against `resolve-advanced/server/author-interchange.mjs` rather
than a second Python writer — two writers to keep in agreement means the one that drifts
is always the copy nobody runs. Without Node it refuses and says so.

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

## Advanced (offline) server — the conform QC engine

The live actions above operate on a *running* Resolve. The companion advanced
server (`davinci-resolve-advanced`, see `resolve-advanced/README.md`) does the
finishing-grade conform work with **no Resolve running**, against `.drt`/`.drp`
files and the project DB.

- **`conform`** — offline conform/relink QC with **frame-oracle math, not
  filename matching** (it catches a clip relinked to the wrong-but-similarly-named
  source). Also: reverse/retimed subclip DB repair (reversed `source_start` =
  `masterFrames − 1 − endoffset`, live-validated), sequence lineage store + diff +
  rollback (hashed snapshots), and per-cut frame QC (oracle-frame vs
  reference-render, scale-corrected, red/yellow/cyan verdicts; each cut is
  compared clear of its transition windows, and Resolve's own FCP7 export
  ingests with its `-1` edges resolved and its missing ticks tolerated).
- **`color_trace`** — cross-project clip matching → a trace plan for carrying
  grades across a re-conform (pairs with the color kernel's `drx grade_transfer`).
- **`offline_ref`** — offline-reference clips have **no scripting API** but live
  inside `.drp`/`.drt` as `<OfflineClip>` entries; patch them here.
- **`editorial`** — `parse_interchange` (EDL/OTIO/XMEML natively; **AAF via pyaaf2**,
  multi-layer Avid turnovers included — honest refuse only when pyaaf2 is absent),
  `turnover_changelist` (moved/retimed/trimmed/replaced/new/gone plus transitions
  added/dropped/changed with fade in/out, with timing guards),
  `conform_manifest`, `marker_roundtrip`.
- **`drt` / `project_db`** — timeline file authoring and DB patching.

Gotchas the live path shares:

- **XML import via the scripting API goes _offline_** (missing-media/generators
  abort). Use `import_timeline_checked` with media **sanitize** (FCP7/FCPXML) so
  the API imports with links intact, then exact-path relink. Restart a running MCP
  server to pick up the sanitize fix.
- **`.drt` version.** For DaVinci Resolve 19.1.3, set `DbPrjVer` 17 → 16 when
  authoring a `.drt`.
- **`project_db` patches** require the project **CLOSED** plus
  `iConfirmProjectClosed:true`; writes auto-back-up and read-back verify. Resolve
  caches open projects — **fully quit and relaunch** after patching.
- **Deps.** `better-sqlite3` gates lineage/reverse/DB; `sharp`/ffmpeg gate frame
  compare — call the advanced `capabilities` tool.

See the `resolve-conform` skill (`.agents/skills/resolve-conform/SKILL.md`) for the
craft ↔ live ↔ offline routing.

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
