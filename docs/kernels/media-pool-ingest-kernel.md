# Media Pool / Ingest Kernel

The Media Pool / Ingest kernel expands the raw Resolve Media Storage,
Media Pool, Folder, MediaPoolItem, and MediaPoolItem marker wrappers into a
safer agent-facing layer for import, organization, metadata, annotation, and
link-boundary work.

Source media integrity remains the first rule: these helpers do not transcode,
render, proxy-generate, overwrite, or mutate source files. They validate paths
before calling Resolve, and the live harness uses generated synthetic media in
disposable `_mcp_...` projects only.

## New Compound Actions

All actions are under `media_pool(action=...)`.

| Action | Status | Purpose |
| --- | --- | --- |
| `ingest_capabilities` | Supported | Maintained support/partial/unsupported map for ingest workflows. |
| `probe_media_pool` | Supported | Read-only Media Pool, folder, selected clip, and method availability snapshot. |
| `probe_ingest_item` | Supported | Read-only metadata/property/annotation/audio snapshot for clip IDs or selected clips. |
| `safe_import_media` | Supported | Validates existing paths, optionally targets a Media Pool folder, supports dry-run, then calls `ImportMedia(paths)`. |
| `safe_import_sequence` | Supported | Validates printf-style sequence patterns and frame ranges before calling `ImportMedia([{clipInfo}])`. |
| `safe_import_folder` | Supported dry-run | Validates folder paths before `ImportFolderFromFile`; dry-run is recommended unless importing Resolve folder exports intentionally. |
| `setup_multicam_timeline` | Supported setup helper | Creates a stacked multicam prep timeline from Media Pool clips, with one angle per video track and optional matching audio tracks. |
| `organize_clips` | Supported | Moves clips to an existing or optionally created Media Pool folder. |
| `copy_metadata` | Supported | Copies Resolve metadata and optional third-party metadata from one clip to target clips. |
| `normalize_metadata` | Supported | Bulk-writes explicit metadata and third-party metadata to clip IDs or selected clips. |
| `probe_clip_properties` | Supported | Read-only full and known-key clip property snapshots. |
| `metadata_field_inventory` | Supported | Read-only metadata, clip-property, and inferred Metadata-panel group inventory for selected or explicit clips. |
| `safe_relink` | Supported | Validates clip IDs and target directory before `RelinkClips`; supports dry-run. |
| `safe_unlink` | Supported | Validates clip IDs before `UnlinkClips`; supports dry-run. |
| `link_proxy_checked` | Supported | Validates clip ID and proxy file path before `LinkProxyMedia`. |
| `link_full_resolution_checked` | Supported on Resolve 20+ | Version-guards and validates path before `LinkFullResolutionMedia`. |
| `set_clip_marks` | Supported | Bulk `SetMarkInOut` for clip IDs or selected clips. |
| `clear_clip_marks` | Supported | Bulk `ClearMarkInOut` for clip IDs or selected clips. |
| `copy_clip_annotations` | Supported | Copies clip color, flags, and media-pool item markers from one clip to targets. |
| `media_pool_boundary_report` | Supported | Combines capabilities, Media Pool probe, and optional item probes. |

## Multicam Setup Helper

`setup_multicam_timeline` is intentionally documented as a helper tool rather
than API coverage. It prepares the timeline structure Resolve's multicam UI can
consume, while leaving native conversion to Resolve.

Supported planning inputs:

- `clip_ids`: simple one-angle-per-clip setup.
- `angles`: explicit rows with `clip_id`, `angle_name`, source range, track
  index, audio track index, source timecode, record frame, or record offset.
- `sync_mode`: `stack_start`, `source_timecode`, or `record_frame`.
- `include_audio`: append audio-only rows for each angle.
- `dry_run`: return the planned append rows without creating a timeline.

After the helper creates the setup timeline, verify sync in Resolve, duplicate
the timeline if it should remain recoverable, then use the Media Pool context
menu command "Convert Compound Clips (Timelines) to Multicam Clips." See
`docs/guides/multicam-setup-guide.md` for examples and the Resolve 20 manual
reference.

For 2-pop or slate-clap assisted sync, run
`media_analysis(action="detect_sync_events")` first and pass its suggested
`record_offset` values into `setup_multicam_timeline(sync_mode="record_frame")`.
If the detected sync points should become Resolve markers, ask the user first;
the guarded write step is `media_analysis(action="add_sync_event_markers",
params={"confirm": true, ...})`.

## Supported Boundaries

- Media Storage browsing: volumes, subfolders, and file listing.
- Media import through simple paths and image sequence clipInfos.
- Safe import helpers with path validation and dry-run support.
- Media Pool organization: folder creation, current folder switching, selected
  clip get/set, and clip moves.
- Multicam setup timelines: source-safe placement of existing Media Pool clips
  on per-angle tracks via `AppendToTimeline([{clipInfo}])`, with stack-start,
  manual record-frame, or source-timecode planning.
- Metadata: scalar and dict metadata writes, third-party metadata writes,
  metadata copy, explicit normalization, and field inventory for mapping
  analysis writeback targets to Resolve metadata/clip-property surfaces.
- Clip property probing: full snapshot plus known keys such as `File Path`,
  `Type`, `FPS`, `Duration`, `Resolution`, `Codec`, and audio fields.
- Media Pool item annotations: markers, custom marker data, flags, clip color,
  and mark in/out.
- Link boundaries: relink/unlink dry-runs, proxy linking, and Resolve 20+
  full-resolution media linking, with generated media used for live validation.
- Export metadata to a caller-provided path.

## Partial Or Version-Dependent Areas

- Clip property writes are still key/media/build dependent. The kernel probes
  properties read-only; raw `media_pool_item.set_clip_property` remains
  available for explicit writes.
- Proxy and full-resolution linking may accept paths without deep media
  compatibility validation. Use checked helpers for path validation, and verify
  editorial intent before changing real project links.
- Audio transcription depends on Studio features, installed language
  components, media type, and Resolve state; it remains exposed on existing
  `folder` and `media_pool_item` actions, not folded into the ingest live pass.
- Image sequence import depends on a valid printf-style pattern and Resolve's
  still/sequence interpretation.
- `ImportFolderFromFile` is a Resolve folder/project interchange operation, not
  a general filesystem import. The safe helper validates the folder and supports
  dry-run to prevent accidental misuse.

## Unsupported Or Intentionally Guarded

- Non-media files are not imported. The final live probe classified a generated
  `.txt` fixture as `unsupported` because Resolve returned zero imported items
  without raising an API error.
- The kernel does not create proxies, transcodes, renders, or derivatives of
  source media.
- Destructive replacement APIs (`ReplaceClip`, `ReplaceClipPreserveSubClip`)
  remain raw explicit clip actions and are not used by the kernel probe.
- Resolve does not guarantee a stable writable metadata schema across versions
  or locales.
- Native multicam clip creation, angle switching, and multicam flattening are
  not exposed by the public Resolve scripting API. The setup helper prepares a
  timeline that can be converted to a native multicam clip in Resolve's UI. See
  the installed DaVinci Resolve 20 Manual, Edit > Chapter 42, "Multicam
  Editing," for the current UI workflow.

## Live Evidence

Final validation ran on May 9, 2026 with DaVinci Resolve Studio 20.3.2.9 and
Python 3.11.14.

```
python3.11 tests/live_media_pool_ingest_validation.py \
  --output-dir /private/tmp/media-pool-ingest-probe-20260509-release
```

Result:

- `supported`: 56
- `unsupported`: 1
- `partially_supported`: 0
- `version_or_page_dependent`: 0
- `write_only_unverifiable`: 0
- `read_only`: 0
- `not_applicable`: 0
- `error`: 0

The live harness created and deleted a disposable project named
`_mcp_media_pool_ingest_probe_1778341105`, generated synthetic video/audio/still
fixtures, wrote JSON and Markdown reports, and removed the generated media
directory after the report was written.
