# Media Analysis Guide for DaVinci Resolve MCP

This guide teaches AI coding assistants how to use FFprobe, FFmpeg, and Whisper to understand source media files — so the DaVinci Resolve MCP can operate with full context of what the footage actually is.

This guide is tool-agnostic. It works with any AI assistant that can run shell commands alongside the MCP server.

---

## The First Rule: Never Touch the Source

**This is the foundational, non-negotiable principle.**

Your relationship to source media is **READ-ONLY**. Every department in a post-production pipeline depends on an unbroken chain from the camera original files (OCFs) through to final delivery.

### NEVER do any of the following unless the user explicitly requests it:
- Transcode, convert, or re-encode any media file
- Create proxies, mezzanines, or lower-resolution copies
- Export media from Resolve and reimport it
- Apply LUTs, color transforms, or any processing to files on disk
- Create rendered versions of timeline segments
- Modify, rename, move, or reorganize source media files
- Strip, modify, or rewrite metadata in source files
- Change timecode in source files
- Create "optimized" or "analysis-friendly" copies

### ALWAYS limit yourself to:
- Reading files with FFprobe (metadata extraction — zero disk writes)
- Analyzing files with FFmpeg using `-f null -` output (read-through analysis — zero disk writes)
- Writing analysis results to separate sidecar JSON files only
- Running Whisper transcription that writes only to an analysis directory
- Creating sampled frames/contact sheets only for visual analysis workflows, only
  in a designated analysis directory. The `analyze_media` prompt defaults
  visual analysis and transcription on, and writes metadata/markers back to the
  Resolve project by default; pass `include_visuals=false`,
  `include_transcription=false`, `publish_metadata=false`, or
  `timed_markers=no` to opt out.

### Why This Matters

- **Assistant Editor:** Every transcode introduces a generation loss. Every conversion makes assumptions about color space, bit depth, and timecode that may be wrong. An unauthorized proxy that doesn't match source timecode breaks the online conform.
- **Editor:** The edit is discovered from the real footage. Analysis informs creative decisions without creating derivatives that confuse the media pool or timeline.
- **Colorist:** The grade starts with every bit of dynamic range the camera captured. A transcode bakes in assumptions about color space and gamma. Once latitude is lost, it's gone forever.
- **Online Editor:** The entire conform workflow traces back to OCFs. Exported-and-reimported media looks like the original but breaks the file path, media hash, and metadata chain.
- **Producer:** Distributors trace chain of custody back to camera originals. Unauthorized derivatives risk QC failure, E&O issues, and delivery rejection.

### The Only Exception

If the user explicitly requests a derivative ("make me a proxy," "transcode this to ProRes"), then:
- Confirm the request before executing
- Clearly label the output as a derivative
- Never overwrite or replace the original
- Document what was created and where
- Preserve all metadata including timecode

---

## Setup: First Interaction

On first use, determine:

### 1. Where should analysis files be saved?
- **alongside** — Sidecar files next to each media file (e.g., `clip.mov` -> `clip.mov.analysis.json`)
- **directory** — A central analysis directory (default: `~/resolve-media-analysis/`)
- **project** — Inside a `.analysis/` folder within the Resolve project's media folder

If source media is on read-only storage (camera cards, SAN volumes), use `directory` or `project`.

### 2. What tools are available?

Check automatically:
```bash
# Required
which ffprobe && ffprobe -version 2>&1 | head -1

# Optional — enhanced analysis
which ffmpeg && ffmpeg -version 2>&1 | head -1

# Optional — transcription
which whisper 2>/dev/null || which whisper-cpp 2>/dev/null || python3 -c "import whisper" 2>/dev/null
```

FFprobe is required. If missing:
- macOS: `brew install ffmpeg`
- Linux: `sudo apt install ffmpeg` or `sudo dnf install ffmpeg`
- Windows: Download from https://ffmpeg.org

### 3. Analysis depth preference
- **quick** — FFprobe metadata only (~1 second per file)
- **standard** — Metadata, loudness, full-stream scene detection, cut-boundary
  analysis, flash-frame candidates, motion/variance scoring, and analysis
  keyframes (~30-60 seconds per file)
- **deep** — Standard analysis plus transcription and expanded visual sampling
  via host_chat_paths (finalized per clip with commit_vision, ~2-5 minutes per
  file plus host-chat read time)

`depth` controls *which layers run*. How many frames each clip gets for visual
analysis is a separate axis — the **sampling mode** — because a fixed frame count
over-samples short clips and under-covers long ones.

### 3b. Frame-sampling mode

Pass `sampling_mode` on any analyze action, or set a standing default in the
control panel (Preferences → Frame sampling mode). The mode owns frame count and
thus token cost; `analysis_caps.frames_per_clip` is now a safety ceiling above it,
not the primary dial.

- **Economy** (`fixed`) — flat N frames (depth-derived, default 8) regardless of
  clip length. Cheapest and most predictable; good for proxies/triage.
- **Balanced** (`per_minute`) — `frames = clamp(minutes × frames_per_minute, floor,
  ceiling)` (defaults 4/min, 3–80). Cost is linear in footage length; content-blind.
- **Thorough** (`adaptive_capped`, **recommended**) — content-aware: samples shot
  boundaries, representatives, and flash candidates, bounded to `[floor, ceiling]`
  (3–80). Best coverage with a bounded cost.
- **Thorough (uncapped)** (`adaptive`) — content-aware with no per-clip ceiling
  (up to the absolute 512-frame hard cap). Use only when clips are short or few.

Tunables (`frames_per_minute`, `frame_floor`, `frame_ceiling`) apply to Balanced
and Thorough. The first time you analyze without a saved default, the tool returns
a `confirmation_required` response with a `sampling_mode_prompt`; re-run with
`sampling_mode=<choice>` (which saves it as your default) or pick it in the panel.
Pass `sampling_mode` explicitly any time for a one-off that doesn't change the default.

---

## Analysis Commands

Every command below is source-file read-only. Resolve-target analysis may write
metadata and Media Pool clip markers to the Resolve project database by default;
none of these commands write to the source media file.

### FFprobe: Technical Metadata (Required)

```bash
ffprobe -v quiet -print_format json -show_format -show_streams -show_chapters "INPUT_FILE"
```

Extract and structure:
- **Video**: codec, profile, level, pixel format, bit depth, resolution, frame rate, scan type (progressive/interlaced), color primaries, transfer characteristics, matrix coefficients, HDR metadata
- **Audio**: codec, sample rate, channels, channel layout, bit depth
- **Container**: format, duration, overall bitrate, timecode (if present)
- **Chapters**: timestamps and titles

For frame rate, distinguish between `r_frame_rate` (container) and `avg_frame_rate` (actual). Flag VFR if they differ significantly.

### FFmpeg: Content Analysis (Optional)

All commands use `-f null -` as output — read-through analysis, zero disk writes.

**Loudness (EBU R128):**
```bash
ffmpeg -i "INPUT_FILE" -af ebur128=peak=true -f null - 2>&1 | tail -30
```

**Scene Detection:**
```bash
ffmpeg -i "INPUT_FILE" -filter:v "select='gt(scene,0.3)',showinfo" -f null - 2>&1 | grep "showinfo"
```

Scene detection is a full-stream read. Standard/deep analysis turns the detected
times into cut-boundary evidence: one frame before and one frame after each
candidate cut, first/last usable clip frames, and short adjacent scene ranges
that may be flash frames. Those candidates are advisory until visual review
checks whether the boundary is a true edit, a flash/title/black insertion, or a
high-motion moment inside one continuous shot.

**Black Frame Detection:**
```bash
ffmpeg -i "INPUT_FILE" -vf blackdetect=d=0.5:pix_th=0.10 -f null - 2>&1 | grep "blackdetect"
```

**Silence Detection:**
```bash
ffmpeg -i "INPUT_FILE" -af silencedetect=noise=-50dB:d=1 -f null - 2>&1 | grep "silence"
```

### Sync Event Detection

Use `media_analysis(action="detect_sync_events")` when the task is to find
advisory sync points in deliverables, single-camera footage, dual-system sound,
or multicam source clips.

The detector is source-safe:

- It uses FFprobe for metadata and FFmpeg to decode source audio to in-memory
  mono samples.
- It writes no media files, proxies, renders, or derivatives.
- It returns likely 1 kHz 2-pops, slate-clap transients, frame/timecode
  positions when frame rate/timecode are known, and per-file record-offset
  suggestions.
- It returns marker suggestions for Media Pool clips, but never writes markers
  during detection.
- It does not install FFmpeg automatically. If `ffmpeg` or `ffprobe` is missing,
  report the missing optional dependency and suggest installing FFmpeg.

Analyze explicit files:

```json
{
  "action": "detect_sync_events",
  "params": {
    "paths": ["/path/to/camera_a.mov", "/path/to/camera_b.mov"],
    "fps": 24,
    "event_types": ["two_pop", "slate_clap"],
    "scan_start_seconds": 30,
    "scan_tail_seconds": 30,
    "prefer_event_type": "slate_clap"
  }
}
```

Analyze selected Media Pool clips:

```json
{
  "action": "detect_sync_events",
  "params": {
    "target": "selected",
    "prefer_event_type": "slate_clap"
  }
}
```

For multicam prep, use `alignment.suggestions[].suggested_record_offset_frames`
as per-angle `record_offset` values with
`media_pool(action="setup_multicam_timeline", sync_mode="record_frame")`, then
verify sync in Resolve before converting the setup timeline to a native multicam
clip.

To add source-frame Media Pool markers from detected sync events, first show the
user the marker suggestions. Only after the user approves, call:

```json
{
  "action": "add_sync_event_markers",
  "params": {
    "target": "selected",
    "prefer_event_type": "slate_clap",
    "confirm": true
  }
}
```

If you already have a detection result, pass it back as `detection` with
`confirm=true`. Raw file-path detections cannot be marked in Resolve unless
they are tied to Media Pool clips.

### Host-Chat Visual Analysis (`host_chat_paths` + `commit_vision`)

Vision uses `host_chat_paths` by default. It works with any MCP client whose
chat model is vision-capable; no `sampling/createMessage` support is required
on the client side.

The protocol is two tool calls per clip:

**1. Analyze.** `analyze_clip` / `analyze_file` / `analyze_bin` etc. extract
representative frames to disk under the project analysis root and return a
deferred-vision payload in `manifest.clips[*].visual`:

```json
{
  "success": true,
  "status": "pending_host_analysis",
  "provider": "host_chat_paths",
  "vision_token": "<16-char hash>",
  "frame_paths": [
    "/Users/.../analysis/.../clips/<clip-dir>/frames/sampled_0001.jpg",
    "..."
  ],
  "frame_metadata": [
    {"frame_index": 1, "time_seconds": 0.0, "selection_reason": "first_usable", "boundary_role": null, ...},
    ...
  ],
  "shot_table": [
    {
      "shot_index": 1,
      "time_seconds_start": 0.0,
      "time_seconds_end": 1.969,
      "duration_seconds": 1.969,
      "frame_indices": [1, 2],
      "has_in_shot_frame": true
    },
    ...
  ],
  "prompt": "<the JSON schema you must return>",
  "schema_reference": "davinci_resolve_mcp.visual_analysis.v1",
  "commit_action": {
    "tool": "media_analysis",
    "action": "commit_vision",
    "params": {
      "clip_id": "<clip-id>",
      "analysis_root": "<absolute project root>",
      "vision_token": "<same token>",
      "visual": "<host chat: fill with JSON matching prompt>"
    }
  },
  "instructions": "Read every file under frame_paths..."
}
```

The manifest also carries `vision_pending: true` and `pending_action` at the
top level so the response shape signals incompleteness to any caller.

**2. Commit.** The host chat reads each `frame_paths` entry as a local image
(Claude Code's `Read` tool handles JPG/PNG natively; Claude Desktop accepts
images in chat; Cursor/Continue/Cline etc. expose comparable mechanisms),
produces JSON matching the `prompt`, then calls:

```json
{
  "action": "commit_vision",
  "params": {
    "clip_id": "<clip-id>",
    "vision_token": "<token>",
    "visual": { "clip_summary": "...", "editorial_classification": {...}, ... }
  }
}
```

`commit_vision` validates the token (rejects stale commits if the analysis has
been re-run), normalizes the visual payload against the schema, rewrites
`visual.json` / `analysis.json` / `clip_analysis_markers.json`, refreshes the
SQLite index entry, and — for Resolve-target clips — publishes metadata and
Media Pool clip markers automatically. The response includes a
`metadata_publish` block reporting the publish outcome.

**Shot-level descriptions are required, not optional.** The host chat must
return one `shot_descriptions` entry per `shot_index` in `shot_table`:

```json
"shot_descriptions": [
  {
    "shot_index": 1,
    "time_seconds_start": 0.0,
    "time_seconds_end": 1.969,
    "frame_indices_used": [1, 2],
    "description": "What is visible in this shot's frames specifically.",
    "editing_value": "How an editor might use this shot.",
    "qc_flags": []
  }
]
```

Each shot marker in Resolve inherits its `visual_description` from
`shot_descriptions[shot_index]`. If a shot has no entry, the server falls back
to an in-range `analysis_keyframe` description, and finally to a
clip-summary-tagged fallback so the marker is honest about being inherited
rather than authored — it never copies a far-away neighbour's description.
Use `analysis_keyframes` for sparse notable-moment observations (motion peaks,
slate visibility, flash candidates); it is additive and does not replace
`shot_descriptions`.

Per-layer artifacts (technical, loudness, scenes, motion, transcription) persist
during the initial analyze call regardless of vision status, so a partial
completion still leaves usable inspectable reports on disk.

Skip vision entirely with `include_visuals=false` or set
`vision={"enabled": false}` — only do this when the user explicitly opts out.

### Publishing Analysis Back To Resolve Metadata

Use `media_analysis(action="publish_clip_metadata")` when analysis should become
searchable and usable inside Resolve's own Media Pool metadata views, smart bins,
and filters.

The publish step is a Resolve-project mutation. It does not modify source media,
but it does write to the Resolve project database. Executed Resolve-target
analysis publishes metadata and source-time Media Pool markers by default; pass
`dry_run=true`, `publish_metadata=false`, or `timed_markers=no` to disable those
writes for a run.

Optional dry-run:

```json
{
  "action": "publish_clip_metadata",
  "params": {
    "target": "selected",
    "fields": ["Description", "Comments", "Keywords", "People"],
    "merge_policy": "append_relevant",
    "vision": {"enabled": true, "provider": "host_chat_paths"},
    "slate_detection": {"enabled": true, "use_vision": true},
    "dry_run": true
  }
}
```

To force an explicit publish call after review:

```json
{
  "action": "publish_clip_metadata",
  "params": {
    "target": "selected",
    "fields": ["Description", "Comments", "Keywords", "People", "Scene", "Shot", "Take", "Camera #"],
    "merge_policy": "append_relevant",
    "slate_detection": {"enabled": true, "use_vision": true},
    "dry_run": false,
    "confirm": true
  }
}
```

Field policies are conservative by default:

- `Description` and `Comments` preserve existing text and update an MCP-owned
  analysis block.
- `Keywords` and `People` are list-merged with case-insensitive de-duplication.
- `Scene`, `Shot`, `Take`, `Camera #`, and roll/card fields are fill-empty fields
  unless the caller explicitly requests overwrite behavior.
- Machine provenance is written to third-party metadata using
  `davinci_resolve_mcp.*` keys so future runs can check report path, signature,
  publish timestamp, publisher version, and changed fields.
- Source-time observations are written as Media Pool clip markers by default,
  including shot ranges, best moments, sync events, and warnings. Use
  `timed_markers=no`, `marker_types`, or `max_markers` when a run needs fewer
  markers.
- If `ask_before_metadata_publish=true`, `publish_clip_metadata` returns a
  confirmation prompt until `confirm=true` is supplied. Timed-marker choices
  still support `yes`, `no`, `default_yes`, and `default_no` for local defaults.
- Conversation-level defaults can also be managed through
  `setup(action="get_defaults")` and `setup(action="set_defaults")`. For
  example, pass
  `{"defaults":{"media_analysis":{"timed_markers_default":"default_no"}}}` to
  disable timed markers by default.
  The setup tool also stores defaults for slate detection, host_chat_paths vision,
  transcription, session-only vs persisted reports, metadata field lists,
  metadata overwrite policy, timed-marker types/colors/counts, confidence/time
  note reporting, summary style, report format, preferred analysis roots,
  generated-media folders, post-operation page preference, marker custom-data
  style, metadata writeback default, and dry-run-first behavior. These defaults
  shape future analysis calls
  and can restore prompt-before-write behavior with
  `ask_before_metadata_publish=true`.

When slate detection is enabled, the helper first looks for likely audio clap
cues with the source-safe sync detector, then checks temporary frames around the
cue before publishing slate-specific metadata or markers. Audio-only detections
remain sync evidence; they do not become slate keywords, slate comments, slate
fields, or slate markers unless visual review confirms that a slate or clapper
is actually present. Only high-confidence visual slate reads are proposed for
structured fields; lower-confidence reads stay out of structured writeback.

When visual analysis is requested for metadata publishing, `Description` and
editorial `Comments` are generated from successful visual analysis rather than
falling back to filename/duration/motion summaries. Vision uses host_chat_paths
by default — analyze actions return a deferred payload and the publish flow
defers until the host chat calls `commit_vision` with the visual JSON. If the
host chat skips `commit_vision`, the publish result reports the visual layer as
`pending_host_vision_analysis` and leaves descriptive fields unchanged.

### Clip Marker JSON And Sequence Analysis

Executed media analysis writes `clip_analysis_markers.json` beside each
`analysis.json` report under the project analysis root. This JSON is the durable
edit-intelligence layer: shot ranges, black/title/QC ranges, best moments, visual
descriptions, sound notes, transcript excerpts, word-timestamp availability,
color intent, and timeline occurrences when the clip came from a sequence.

Resolve Media Pool clip markers are optional writeback, not the source of truth.
Only `publish_clip_metadata` with marker writeback enabled and confirmed should
add markers to the Resolve project. Analysis itself should produce JSON marker
plans without mutating the project.

Use `media_analysis(action="analyze_bin")` for a bin of source clips. Use
`media_analysis(action="analyze_sequence")` or target `"sequence"`/`"timeline"`
when the task is to understand an existing edit; the sequence target analyzes
the distinct Media Pool assets used on the timeline and records each timeline
occurrence as structured data for later cutdown, adjustment, or recommendation
work.

### Local SQLite Analysis Index

For large single-user projects, the derived SQLite index is built automatically
after persisted analysis reports are written. Durable batch jobs refresh the
index after each successful slice, so search becomes useful as soon as the first
clip is analyzed instead of waiting for a long job to finish.

Use the explicit build action when you want to repair or fully rebuild the cache
from existing reports:

```json
{"action": "build_index", "params": {"analysis_root": "/path/to/analysis-root"}}
```

The database is stored as `index.sqlite` beside `manifest.json` and
`project_summary.json` under the project analysis root. The JSON reports remain
the source of truth; the SQLite index is a rebuildable cache for searching clips,
markers, transcript segments, visual tags, timeline occurrences, warnings, and
computed keyframe metrics.

Use `media_analysis(action="index_status")` to inspect row counts and size. Use
`media_analysis(action="query_index", params={"query": "quiet reflective b-roll"})`
to search indexed clip summaries, marker descriptions, and transcript text.

Do not store sampled frames or contact sheets in SQLite. The index stores
text/metadata only; generated frame files remain disposable artifacts under the
analysis root and can be removed with `cleanup_artifacts(frames_only=true)`.

### Batch Jobs And Local Dashboard

For long runs, prefer durable batch jobs over one large analysis call. A job
stores operational state in `jobs.sqlite` under the same project analysis root
as the reports and index. Each slice processes a bounded number of clips, exits
cleanly, and can be resumed by a later agent or dashboard action.

Resolve-aware MCP workflow:

```json
{"action": "start_batch_job", "params": {"target": {"type": "bin", "path": "Master/Day 01"}, "depth": "standard"}}
```

```json
{"action": "run_batch_job_slice", "params": {"job_id": "job-...", "max_clips": 1}}
```

```json
{"action": "batch_job_status", "params": {"job_id": "job-..."}}
```

Use `list_batch_jobs`, `cancel_batch_job`, and `resume_batch_job` for operations
around the same project analysis root. Jobs refresh the SQLite search index
after each successful analyzed or reused clip, and completed jobs do a final
rebuild if needed. Pass `auto_build_index=false` when creating the job to disable
that behavior.

Standalone local dashboard:

```bash
venv/bin/python -m src.analysis_dashboard --analysis-root ~/Documents/davinci-resolve-mcp-analysis --open
```

The dashboard can create file/folder jobs without Resolve open, run one clip
slice at a time or auto-run slices, inspect recent events, build the local
index, and query completed analysis. Chat-context visual analysis still requires
the MCP request path because the standalone dashboard cannot call the host
chat/sampling model. It is intentionally single-user and local; it does not
provide authentication, multi-user locking, media playback, or image storage in
SQLite.

### Mapping Resolve Metadata Fields

Use `media_pool(action="metadata_field_inventory")` before expanding metadata
writeback beyond the default analysis fields. The probe is read-only and reports
three distinct surfaces for selected or explicit Media Pool clips:

- `GetMetadata("")`: project metadata values that have been explicitly written
  or are otherwise exposed through Resolve's metadata API.
- `GetClipProperty("")`: the larger clip-property map that usually mirrors the
  fields visible in Resolve's Metadata panel.
- Inferred Metadata-panel groups such as `Shot & Scene`, `Camera`, `Audio`,
  `Production`, and `Reviewed By`.

Resolve does not expose a guaranteed public schema for the Metadata panel group
layout, and field names can differ subtly between the UI and scripting surfaces.
For example, the UI may show `Keywords` while `GetClipProperty("")` exposes
`Keyword`; live validation on Resolve Studio 20.3 showed that writeback should
still call `SetMetadata("Keywords", value)`. Likewise, slate roll/card values
should write to `Roll Card #` even when older helper code or UI/property maps use
`Roll/Card`. The probe reports aliases and marks this group map as best-effort.

For live validation against a disposable synthetic project, run:

```bash
venv/bin/python tests/live_metadata_field_inventory_validation.py --output-dir /tmp/resolve-metadata-field-probe
```

That harness compares `metadata_field_inventory`, `MediaPool.ExportMetadata()`,
and `SetMetadata()` readback without touching user source media. Use a Resolve
scripting-compatible Python 3.10-3.12 environment for the live run.

**Interlace Detection:**
```bash
ffmpeg -i "INPUT_FILE" -vf idet -frames:v 500 -f null - 2>&1 | grep "idet"
```

**Thumbnail Extraction (explicit user approval required; writes to analysis directory ONLY):**
```bash
ffmpeg -i "INPUT_FILE" -vf "select=eq(n\,FRAME_NUM)" -frames:v 1 -q:v 2 "ANALYSIS_DIR/thumbnail.jpg"
ffmpeg -i "INPUT_FILE" -vf "fps=1/INTERVAL,scale=320:-1,tile=4x4" -frames:v 1 "ANALYSIS_DIR/contact_sheet.jpg"
```

### Whisper: Transcription (Optional)

```bash
# OpenAI Whisper CLI
whisper "INPUT_FILE" --model base --output_format json --output_dir "ANALYSIS_DIR"

# Or whisper-cpp
whisper-cpp -m /path/to/model -f "INPUT_FILE" --output-json

# Or Python whisper
python3 -c "
import whisper, json, sys
model = whisper.load_model('base')
result = model.transcribe(sys.argv[1])
print(json.dumps(result, indent=2))
" "INPUT_FILE"
```

---

## Analysis Output Format

Save as JSON sidecar files:

```json
{
  "analysis_version": "1.0",
  "analyzed_at": "2026-03-09T12:00:00Z",
  "source_file": "/path/to/clip.mov",
  "source_file_size_bytes": 1234567890,
  "source_file_modified": "2026-03-01T10:30:00Z",

  "video": {
    "codec": "prores",
    "codec_long": "Apple ProRes 422 HQ",
    "profile": "3",
    "pixel_format": "yuv422p10le",
    "bit_depth": 10,
    "width": 3840,
    "height": 2160,
    "display_aspect_ratio": "16:9",
    "frame_rate": "23.976",
    "frame_rate_exact": "24000/1001",
    "is_vfr": false,
    "scan_type": "progressive",
    "color_primaries": "bt709",
    "transfer_characteristics": "bt709",
    "matrix_coefficients": "bt709",
    "hdr": null,
    "duration_seconds": 125.5,
    "frame_count": 3010,
    "bitrate_mbps": 220.5
  },

  "audio": [
    {
      "stream_index": 1,
      "codec": "pcm_s24le",
      "sample_rate": 48000,
      "channels": 2,
      "channel_layout": "stereo",
      "bit_depth": 24,
      "duration_seconds": 125.5
    }
  ],

  "container": {
    "format": "mov",
    "duration_seconds": 125.5,
    "overall_bitrate_mbps": 225.3,
    "timecode_start": "01:00:00:00",
    "creation_time": "2026-03-01T10:30:00Z"
  },

  "loudness": {
    "integrated_lufs": -23.1,
    "loudness_range_lu": 12.5,
    "true_peak_dbtp": -1.2
  },

  "scenes": [
    {"time": 0.0, "score": 0.95},
    {"time": 5.2, "score": 0.45},
    {"time": 12.8, "score": 0.72}
  ],

  "transcription": {
    "language": "en",
    "text": "Full transcription text...",
    "segments": [
      {"start": 1.2, "end": 3.5, "text": "Hello and welcome..."}
    ]
  }
}
```

---

## Connecting Analysis to the MCP

### Getting File Paths from Resolve

Use MCP tools to get file paths from the current project, then analyze them externally:

1. **From media pool clips:** `media_pool_item` -> `get_clip_property(clip_id)` returns `"File Path"`
2. **From timeline items:** `timeline_item` -> `get_media_pool_item(item_id)` -> then get clip properties
3. **From media storage:** `media_storage` -> `get_files(path)` lists files in a directory

### Workflow: Analyze Before Acting

1. **Identify the media** — Use MCP to get clip IDs and file paths
2. **Check for existing analysis** — Look for sidecar JSON files
3. **Analyze if needed** — Run FFprobe (+ optional tools) on the files
4. **Act with context** — Use MCP tools with full knowledge of what the media is

Analysis informs Resolve actions. At no point do we create intermediate files that enter the media pipeline.

### Examples

**"Set up my timeline for this footage"**
- FFprobe reveals 4K ProRes 422 HQ, 23.976fps, Rec.709
- Use `project_settings` to set timeline resolution, frame rate, and color science
- Original files stay untouched

**"Create markers at scene changes"**
- Run FFmpeg scene detection (`-f null -` — no output file)
- Use `timeline_markers` or `media_pool_item_markers` to add markers
- Analysis writes nothing to source; markers live in Resolve's database

**"What are my audio levels?"**
- Run EBU R128 loudness analysis (`-f null -`)
- Report current levels vs target (-24 LUFS broadcast, -14 LUFS streaming)
- Suggest adjustments in Resolve's Fairlight page

**"Help me set up color management"**
- FFprobe reveals ARRI LogC3, wide gamut, 12-bit
- Recommend ACES IDT or DaVinci Wide Gamut
- Camera original retains full latitude

---

## What Analysis Enables

| Task | Without Analysis | With Analysis |
|------|-----------------|---------------|
| Set timeline settings | Guess or ask user | Auto-detect from footage |
| Color space setup | Default to Rec.709 | Match source (ARRI LogC, S-Log3, etc.) |
| Audio normalization | Manual measurement | Report LUFS, suggest Fairlight adjustments |
| Scene-based editing | Manual review | Auto-mark scene changes via MCP markers |
| Subtitle creation | Use Resolve's built-in | Whisper transcription -> import via MCP |
| QC checks | Visual inspection | Automated codec/bitrate/level verification |
| Render settings | Generic defaults | Match source codec/colorspace for delivery |
| Timecode sync | Manual entry | Extract embedded timecode for reference |
| VFR detection | Unknown issues | Flag before problems occur in timeline |
| Mixed-camera projects | Manual identification | Auto-detect cameras, suggest per-clip IDTs |

---

## Proactive Warnings

When analysis reveals potential issues, always alert the user:

- **VFR** — Variable frame rate detected; Resolve may interpret differently than expected
- **Mismatched sample rates** — 44.1kHz audio in a 48kHz timeline causes drift
- **HDR metadata** — HDR10/HLG/Dolby Vision present; color management must account for it
- **Color space flags** — ARRI LogC3 / S-Log3 / V-Log etc. requires appropriate IDT
- **Timecode discontinuity** — Multiple clips share starting TC; conform conflicts possible
- **Interlaced content** — Set deinterlacing mode before editing
- **Missing audio** — No audio streams detected
- **Extremely high bitrate** — Verify storage can sustain real-time playback

---

## Key Principles

- **The source is sacred.** Read from source files, write only to analysis sidecars unless a visual analysis workflow needs sampled frames/contact sheets in a separate analysis directory. Confirmed metadata publishing writes to Resolve's project database, not source media. `analyze_media` can opt out with `include_visuals=false`.
- **Respect file paths.** Use exact paths from Resolve or the filesystem.
- **Cache analysis.** Skip re-analysis if the sidecar is newer than the source.
- **Report clearly.** Present analysis to inform the user's next action within Resolve.
- **Timecode matters.** Always extract and report TC — it's the foundation of conform, sync, and delivery.
- **Handle errors gracefully.** If a file can't be analyzed, report and move on.
- **Chain of custody is real.** This tool provides intelligence about the source — never creates alternatives to it.
