# DaVinci Resolve MCP Server — Agent Instructions

This is the canonical short operating brief for AI coding agents working in this
repository. Keep it durable: do not duplicate version numbers, tool counts,
kernel-action counts, release notes, or long reference tables here.

## Non-Negotiable Source Media Safety

Never modify, transcode, convert, proxy, relink, replace, or create derivatives
of source media unless the user explicitly asks for that exact operation.

Analysis workflows may read source media, but file outputs must go to sidecar
files, session scratch space, or the configured
`davinci-resolve-mcp-analysis` project root. Resolve-target analysis should run
visual analysis, transcription, metadata writeback, and Media Pool marker
writeback by default unless the user opts out; those writes are Resolve project
database changes, not source-media changes. Preserve the chain from camera
original to final delivery.

See `docs/guides/media-analysis-guide.md` for the full source-safe workflow.

## Media Analysis Defaults Are Mandatory

Do not translate source-safe into underpowered, read-only, no-writeback analysis.
When the user asks to analyze Resolve media, run the requested analysis directly
with visual analysis, transcription, persisted artifacts, metadata writeback, and
Media Pool marker writeback enabled by default. Do not add
`include_visuals=false`, `include_transcription=false`,
`publish_metadata=false`, `timed_markers=no`, `session_only=true`, or
`dry_run=true` unless the user explicitly asks for that opt-out, the target is a
raw file path that cannot receive Resolve project writeback. Vision uses
`host_chat_paths` by default — analyze actions return a deferred payload with
absolute `frame_paths` and a JSON schema; the host chat must read those frames
as local images, produce JSON per the schema, and call
`media_analysis(action="commit_vision", params={clip_id, visual, vision_token})`
to merge the result and trigger metadata + Media Pool clip-marker writeback.
Not completing `commit_vision` leaves the analysis in
`pending_host_vision_analysis` — that is a failure mode, not a success. Users
must explicitly opt out with `include_visuals=false` for a technical-only run.

## Frame-Referenced Color Work

Before applying a grade, look, shot match, LUT, CDL, DRX, or copied grade to an
existing Resolve timeline, inspect representative Resolve-rendered frames for
the target shot or shots. Use thumbnails, contact sheets, Gallery stills, marker
frames, or visual analysis reports written only to scratch/analysis locations.
When the API can safely provide them, compare matched untreated/bypass, current,
and after frames at the same timecodes; restore the previous active version or
node-enabled state after any temporary bypass capture.

Do not grade only from clip metadata, graph availability, or a requested style
label unless the user explicitly asks for a blind/global pass. Preserve or create
a recoverable grade version, and report which frame references informed the
change. Do not describe Resolve's default one-node graph as an existing creative
grade unless active grade tools, LUTs, or other grade state are present.

When the user asks to build on or adjust an existing grade, treat the current
grade as creative work to preserve. Inspect the active grade version and node
graph first, create or switch to a recoverable adjustment version, and make
incremental changes only through supported controls. Do not reset grades, replace
graphs, or apply whole-grade artifacts unless the user explicitly asks for that
semantics.

## Source Of Truth

- Public overview, current stats, and docs map: `README.md`
- Historical release notes: `CHANGELOG.md`
- AI assistant operating reference: `docs/SKILL.md`
- Release checklist and validation rules: `docs/process/release-process.md`
- Kernel workflow support maps: `docs/kernels/`
- API coverage and live-test status: `docs/reference/api-coverage.md`
- Blackmagic-facing API gaps/bugs (generated from `api_truth`):
  `docs/reference/api-limitations.md` — when you document a new Resolve API
  limitation, add a `submit`-tagged entry to `src/utils/api_truth.py` and
  regenerate with `scripts/gen_api_limitations.py` (a drift guard enforces it)
- Bundled Resolve API text: `docs/reference/resolve_scripting_api.txt`

## Key Paths

- Compound server: `src/server.py`
- Granular server entrypoint: `src/resolve_mcp_server.py`
- Local control panel launcher: `src/control_panel.py`
- Granular implementation: `src/granular/`
- Utilities: `src/utils/`
- Installer: `install.py`
- Tests: `tests/`
- Examples: `examples/`

## Common Commands

```bash
python src/server.py
python src/server.py --full
venv/bin/python -m src.control_panel
python install.py
venv/bin/python tests/test_import.py
venv/bin/python scripts/audit_api_parity.py
```

Python 3.10+ is required (the MCP SDK floor). 3.10-3.12 is the lowest-risk range
for Resolve scripting; 3.13/3.14 are accepted and verified on Resolve Studio
20.3.2, but older Resolve builds may fail to connect on 3.13+.

## Development Notes

- Prefer the compound server unless a task specifically needs granular tools.
- Use existing action-dispatch patterns and helper functions before adding new
  abstractions.
- All Resolve-facing temp or export paths should use the repo's safe path
  helpers; do not invent ad hoc temp paths for files Resolve writes.
- For changes touching Resolve behavior, update focused tests and follow the
  live-validation guidance in `docs/process/release-process.md`.
- For docs changes, keep the README concise and move durable detail into
  dedicated files under `docs/`.
