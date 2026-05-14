# Media Pool And Ingest Examples

These prompts use the Media Pool / Ingest kernel. They are designed to preserve
source media integrity: read metadata, import references into Resolve, and write
analysis sidecars only when explicitly requested.

## First Rule

Never modify, transcode, proxy, relink, rename, move, or create derivatives of
source media unless the user explicitly requests that operation. See
`docs/guides/media-analysis-guide.md` for the full workflow.

## Probe The Media Pool

```text
Probe the current Media Pool. Report the root folder, current folder, selected
clips, folder structure to depth 2, and ingest capabilities. Do not import,
move, relink, or modify any clip metadata yet.
```

Expected actions:

- `media_pool.ingest_capabilities`
- `media_pool.probe_media_pool`
- `media_pool.media_pool_boundary_report`

## Safe Import With Dry Run

```text
Dry-run importing media from /tmp/resolve-mcp-demo/media into a bin named
"_mcp_demo_import". Validate paths first, report what would be imported, and
wait for approval before calling the real import action.
```

Expected actions:

- `media_pool.safe_import_media`
- `media_pool.safe_import_folder`

## Image Sequence Import

```text
Dry-run importing the image sequence
/tmp/resolve-mcp-demo/media/sequence/demo_seq_%03d.png from frames 1 through
12 into a bin named "_mcp_demo_sequences". Validate the pattern and frame range
before importing.
```

Expected actions:

- `media_pool.safe_import_sequence`

## Metadata Normalization

```text
For the selected imported demo clips, dry-run setting metadata fields for Scene,
Shot, and Comments plus third-party metadata under an "mcp_demo" namespace.
Show the before/after values and wait for approval before writing.
```

Expected actions:

- `media_pool.probe_ingest_item`
- `media_pool.normalize_metadata`
- `media_pool.probe_clip_properties`

## Relink Plan, Not Relink

```text
Detect missing media on the current timeline and build a relink plan. Do not
execute relinks. If a relink is possible, show the exact clip IDs and candidate
folders that would be used.
```

Expected actions:

- `timeline.detect_missing_media`
- `timeline.build_relink_plan`
- `media_pool.safe_relink` with `dry_run`

## Media Analysis Prompt

```text
Use read-only media analysis for the selected clips. Run FFprobe metadata only,
write JSON sidecars to /tmp/resolve-mcp-demo/analysis, and do not create
thumbnails, proxies, transcodes, renders, or any visual derivatives unless I
explicitly approve them.
```

Expected workflow:

- Resolve clip path lookup through MCP.
- Read-only FFprobe.
- Sidecar JSON output only.
