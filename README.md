# DaVinci Resolve MCP Server

[![Version](https://img.shields.io/badge/version-2.66.0-blue.svg)](https://github.com/samuelgursky/davinci-resolve-mcp/releases)
[![npm](https://img.shields.io/npm/v/davinci-resolve-mcp.svg?label=npm&color=CB3837)](https://www.npmjs.com/package/davinci-resolve-mcp)
[![API Coverage](https://img.shields.io/badge/API%20Coverage-100%25-brightgreen.svg)](docs/reference/api-coverage.md)
[![Tools](https://img.shields.io/badge/MCP%20Tools-34%20(341%20full)-blue.svg)](#server-modes)
[![Advanced](https://img.shields.io/badge/Advanced%20(offline)-18%20tools-blueviolet.svg)](#server-modes)
[![Tested](https://img.shields.io/badge/Live%20Tested-98.5%25-green.svg)](docs/reference/api-coverage.md#test-results)
[![DaVinci Resolve](https://img.shields.io/badge/DaVinci%20Resolve-18.5+-darkred.svg)](https://www.blackmagicdesign.com/products/davinciresolve)
[![Python](https://img.shields.io/badge/python-3.10+-green.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://opensource.org/licenses/MIT)

A Model Context Protocol (MCP) server that lets AI assistants control DaVinci Resolve Studio through the official Scripting API. It provides full API coverage plus guarded workflow helpers for editing, media pool organization, render setup, review markers, grading, Fusion, Fairlight, project lifecycle tasks, extension authoring, and source-safe media analysis.

[![Local control panel](https://raw.githubusercontent.com/samuelgursky/davinci-resolve-mcp/main/docs/images/control-panel/01-overview.png)](docs/guides/control-panel.md)

A local browser control panel ships with the server for inspecting Resolve state, running source-safe analysis, drilling into analyzed clips and shots, and editing analysis output inline. See the [Control Panel Guide](docs/guides/control-panel.md) for the full tour.

## Quick Start

```bash
npx davinci-resolve-mcp setup
```

Before connecting, open DaVinci Resolve Studio and set **Preferences > General > External scripting using** to **Local**. The npm launcher installs a managed copy under your user application-data directory, then runs the universal Python installer. The installer creates a virtual environment, detects Resolve paths, and can configure Claude Desktop, Claude Code, Cursor, VS Code, Windsurf, Zed, Continue, Cline, Roo Code, OpenCode, and JetBrains IDEs.

For source installs:

```bash
git clone https://github.com/samuelgursky/davinci-resolve-mcp.git
cd davinci-resolve-mcp
python install.py
```

For platform paths, client-specific config, and manual setup, see [Installation and Configuration](docs/install.md).

The installer and server check the latest GitHub release for MCP updates. Checks are best-effort and throttled; the server never blocks MCP startup for a prompt. The installer can prompt, snooze, ignore a release, disable checks, or apply an opt-in safe auto-update for clean git checkouts.

## Local Control Panel

Launch the single-user local control panel from the repository root:

```bash
venv/bin/python -m src.control_panel
```

The command starts a localhost server and opens the control panel in your browser. To have an AI coding agent do this, ask: **"Open the Resolve MCP control panel for this repo."** Agents should use `venv/bin/python -m src.control_panel` unless your Python environment is already active. Persisted analysis jobs refresh the local search index automatically after successful slices; the manual Build Index action is for rebuilding from existing reports.

## Server Modes

| Mode | Entry point | Tools | Best for |
|------|-------------|-------|----------|
| Compound | `src/server.py` | 34 | Default mode for most assistants. Related Resolve operations are grouped behind action parameters to keep context usage low. |
| Full / granular | `src/server.py --full` or `src/resolve_mcp_server.py` | 341 | Power users who want one MCP tool per Resolve API method. |

The compound server is recommended unless you specifically need the granular one-tool-per-method surface.

### Advanced server — beyond the scripting API (optional, Node)

The same package ships a second, optional MCP server: **`davinci-resolve-advanced-mcp`** (bin
`bin/davinci-resolve-advanced-mcp.mjs`). Where the Python server drives a *live* Resolve over the
sanctioned scripting API, the advanced server does what the API **can't** — it reads and edits Resolve
**files** (`.drp` / `.drt` / `.drx`) and applies DB/XML-level changes **with no Resolve running**, so it
runs cloud *or* local. 18 tools: `drp`, `drt`, `drx` (per-clip grade codec **plus a deterministic,
offline grading/QC catalog** — within-camera + cross-camera skin (v2 skin-line metric) + b-roll +
neutral-patch WB matching, match-to-reference, saturation/black-balance, contrast-normalize, ASC CDL
import, lossless grade-transfer + season-look authoring, named-LUT attach, scope reads + intent tags,
verify-grade, display-referred frame extraction, broadcast-legal QC), `offline_ref`,
`conform` (frame-oracle conform/relink QC + lineage), `color_trace` (carry grades across a re-conform),
`fusion`, `audio_plan`, `fairlight` (bus routing), `audio`, `project_read`, `project_db`, `pipeline`
(a **DB-as-truth pipeline**: compile YAML project specs into a canonical SQLite DB, then run stages with
gates, provenance, and intent↔actual drift detection), `capabilities`, `deliverable` (deliverable QC /
compliance), `media` (media front-end / AE ingest), `editorial` (editorial integrity / changelist),
`provenance` (provenance / audit / episode report). It can also be consumed **as a
library** (importable engine API), not just spawned as a server.

DRX grade writes are **live-calibrated against Resolve Studio**: grade params take Resolve's
on-screen panel units by default (`space: 'ui' | 'drx'`), and the structural writes (power windows,
qualifiers, HDR zones, HSL curves, ColorSlice, blur/key/motion-effects) are panel-readback-verified —
per-control status in `resolve-advanced/vendor/drx-parameters/CALIBRATION-STATUS.md`. It also closes
a UI-only gap: **programmatic "Cleanup Node Graph"** (`drx` `relayout` for one clip, `project_db`
`relayout_node_graphs` for a whole project) — node layout tidied, grade content byte-preserved.

Add it alongside the live server (both ship in one `npm install`):

```json
{
  "mcpServers": {
    "davinci-resolve": { "command": "<python>", "args": ["<path>/src/server.py"] },
    "davinci-resolve-advanced": { "command": "node", "args": ["<path>/bin/davinci-resolve-advanced-mcp.mjs"] }
  }
}
```

`install.py` prints both entries. The core is pure-JS/MIT with no required native modules; a few features
need user-installed tools (ffmpeg for `audio`, `sharp`/`better-sqlite3` for some paths) — call the
`capabilities` tool for live status and install hints.

### Bradford Post Assistant — managed application (closed beta)

The maintainers also build **Bradford Post Assistant**, a desktop application on top of this
open foundation. Where the MCP servers give an agent hands, Post Assistant is the working
copilot around them — an on-device AI assistant for post-production where client material
never leaves the workstation:

- **A post-production copilot** — a desktop app that sits alongside DaVinci Resolve and
  watches the session live (timeline, grades, and frames — not just API calls), with an
  embedded AI assistant and agent runtime, local media analysis (transcription, frame
  analysis, editorial intelligence), and in-app conform QC.
- **Memory** — persistent, encrypted on-device assistant memory plus cross-episode learning
  mined from your pipeline's decoded facts (season-look drift, per-camera correction priors,
  hero-frame libraries, conform path-map reuse), with accumulation managed for you and a
  reviewed-insight workflow.
- **Self-contained by design** — Post Assistant wires everything itself: this MCP for
  Resolve control, the Bradford API for its extended services, and your choice of LLM
  provider. Nothing to configure by hand, no separate clients to manage, and the app keeps
  itself (and its bundled MCP) current with signed auto-updates.
- **An extended professional toolset** — grade surgery on live projects, 22+ adaptive grade
  families, a curated looks library, delivery-spec validation, editorial pacing/cleanup
  analysis, natural-language color direction, and Fusion composition authoring — delivered
  through the managed Bradford API.
- **Production workflows** — the raw tools composed into finished, real-world flows
  (turnover → conform → QC → delivery, season-look carry, episode reporting) with the
  guardrails and approvals a client-facing shop expects.

It is currently in **closed beta** — you can request access at
[bradfordoperations.com/software/post-assistant](https://www.bradfordoperations.com/software/post-assistant).
The open-source servers are complete and fully functional on their own.

## What You Can Do

```text
"List all projects and open the one called 'My Film'"
"Create a timeline called 'Assembly Cut' from all clips in the current bin"
"Build a multicam prep timeline from selected camera angles and preserve source media"
"Detect 2-pops or slate claps and suggest record offsets for sync prep"
"Publish analysis summaries, keywords, people, and slate hints into Resolve clip metadata"
"Probe this timeline for gaps, overlaps, missing media, and source frame ranges"
"Safely import this image sequence, organize it into bins, and normalize clip metadata"
"Build a ProRes 422 HQ render plan, validate the settings, and queue the job"
"Copy review markers from the timeline to the selected clip and export a review report"
"Snapshot this clip's grade, validate a CDL update, and export a temp LUT"
"Create a Fusion TextPlus overlay on the selected clip and verify graph connections"
"Report audio channel mappings, voice isolation availability, and subtitle support"
"Install this MCP-marked DCTL or script, classify refresh/restart needs, then remove it"
```

## Core Capabilities

| Area | What the compound server supports |
|------|-----------------------------------|
| App and project control | Launch/reconnect, page switching, project CRUD, project folders, databases, cloud project wrappers, settings, presets, archives |
| Media pool and ingest | Safe import, image sequences, multicam prep timelines, bin organization, metadata normalization, metadata field inventory, marks, annotations, relink/proxy/full-resolution guards |
| Media analysis | Source-safe file/clip/bin/project analysis, 2-pop/slate-clap sync-event detection, default Resolve metadata and Media Pool marker writeback, persisted analysis artifacts, existing-report reuse, host_chat_paths visual analysis (finalized per clip with `commit_vision`, works with any vision-capable MCP client) with opt-out, transcription with opt-out |
| Timeline editing and conform | Track/item probing, title text key scans/writes, copy/move/duplicate helpers, range operations, gaps/overlaps, source ranges, checked interchange exports/imports |
| Review annotations | Timeline/item/clip markers, custom data, flags, clip color, copy/move/sync cleanup, review reports, marker thumbnail review |
| Color and grading | Node graph probing, CDL validation, grade copy, DRX/LUT helpers, versions, Gallery stills, color groups |
| Fusion | Timeline-item comps, safe tool creation, input writes, port inspection, validated connections, scoped bulk writes |
| Audio and Fairlight | Track/item probes, source mapping, guarded audio property writes, voice isolation, auto-sync planning, transcription/subtitle probes |
| Render and deliver | Format/codec matrix probing, render settings validation, queued job lifecycle checks, guarded Quick Export |
| Extension authoring | Fuse, DCTL, ACES DCTL, and Resolve-page Lua/Python script lifecycle helpers with safe MCP-marked install/remove |

## Source Media Safety

This project treats camera originals and source media as immutable. Analysis tools read source files and write reports only to sidecar, scratch, or project analysis directories; confirmed metadata publishing writes only to Resolve's project database. The server must not modify, transcode, proxy, or create derivatives of source media unless the user explicitly asks for that. See [Media Analysis Guide](docs/guides/media-analysis-guide.md) for the detailed source-safe workflow.

## Security Posture

The default server is a local stdio process launched by your MCP client; it does not expose a network listener or built-in multi-user auth surface. Tool metadata includes MCP client-safety hints for read-only, destructive, idempotent, and external-resource operations. See [Security Policy](SECURITY.md) for operational boundaries, confirmation guidance, and vulnerability reporting.

## Key Stats

| Metric | Value |
|--------|-------|
| MCP Tools | **34** compound / **341** granular (live server) |
| Advanced (offline) tools | **18** — .drp/.drt/.drx + DB authoring, no Resolve running |
| Kernel Actions | **136** guarded workflow actions across 9 compound tools |
| API Methods Covered | **336/336** (100%) |
| Methods Live Tested | **331/336** (98.5%) |
| Live Test Pass Rate | **331/331** (100%) |
| Tested Against | DaVinci Resolve 19.1.3 Studio + Resolve 20.3.2 Studio |

For method-by-method status, see [API Coverage and Test Results](docs/reference/api-coverage.md). For current workflow support, see [Kernel Action Coverage](docs/kernels/README.md).

`analyze_media` executes directly by default, persists inspectable reports/artifacts under the analysis root, requests host-chat visual analysis via the `host_chat_paths` protocol (analyze returns absolute frame paths + a JSON schema; the host chat reads each frame as an image and calls `media_analysis(action="commit_vision", ...)` to finalize), runs transcription through the configured local backend, and writes analysis summaries plus source-time Media Pool clip markers back to the Resolve project. Pass `include_visuals=false`, `include_transcription=false`, `publish_metadata=false`, `timed_markers=no`, or `dry_run=true` only when you want to opt out of those default behaviors. Skipping `commit_vision` leaves the run in `pending_host_vision_analysis` — surfaced as a failure mode, not silently downgraded.

## Documentation

| Document | Use it for |
|----------|------------|
| [Installation and Configuration](docs/install.md) | Requirements, installer options, supported clients, server modes, manual config |
| [API Coverage and Test Results](docs/reference/api-coverage.md) | Key stats, API coverage table, live-test status, full method reference |
| [Kernel Action Coverage](docs/kernels/README.md) | Current guarded workflow action map |
| [AI Skill Reference](docs/SKILL.md) | Operational context for AI assistants using the compound server |
| [Control Panel Guide](docs/guides/control-panel.md) | Local browser panel tour: Overview, Review (bin/clip/shot), Analyze, Setup, Preferences |
| [Media Analysis Guide](docs/guides/media-analysis-guide.md) | Source-safe FFprobe, FFmpeg, Whisper, sidecar, and analysis-root workflows |
| [Multicam Setup Helper Guide](docs/guides/multicam-setup-guide.md) | Stacked timeline prep, helper/API boundary, and Resolve UI conversion steps |
| [Editorial Decision Guide](docs/guides/editorial-decision-guide.md) | Project-owned editorial craft guidance for analysis and timeline decisions |
| [Color Decision Guide](docs/guides/color-decision-guide.md) | Project-owned color correction guidance and Resolve color API boundaries |
| [Contributing and Project Layout](docs/contributing.md) | Contribution workflow, platform support, security notes, repository structure |
| [Security Policy](SECURITY.md) | Local stdio trust boundary, tool metadata, confirmation guidance, reporting |
| [Release Process](docs/process/release-process.md) | Maintainer release checklist, version surfaces, validation, tags, and release notes |
| [Changelog](CHANGELOG.md) | Historical release notes |

Extension authoring references live in [docs/authoring](docs/authoring/). Resolve developer-package notes live in [docs/notes](docs/notes/) and [docs/integrations](docs/integrations/). Prompt recipes live in [examples](examples/).

## Requirements

- DaVinci Resolve Studio 18.5+ on macOS, Windows, or Linux. The free edition does not support external scripting.
- Python 3.10+ (3.10-3.12 is the lowest-risk range). Python 3.13/3.14 also work on recent Resolve builds (verified on Studio 20.3.2); older builds may fail to connect on 3.13+, in which case use 3.10-3.12.
- Resolve external scripting set to **Local**.

Resolve 19.1.3 remains the compatibility baseline. Resolve 20.x scripting calls are additive, version-guarded, and live-tested on 20.3.2. Resolve 21.0 scripting additions (audio classification, speaker-detection transcription, IntelliSearch, slate analysis, motion-deblur, speech generation, session background-task control) are exposed behind runtime capability detection, so they stay inert on older builds and activate automatically on Resolve 21+.

## Development

```bash
python src/server.py          # Compound server
python src/server.py --full   # Granular server
venv/bin/python tests/test_import.py
venv/bin/python scripts/audit_api_parity.py
```

Release and validation rules are in [docs/process/release-process.md](docs/process/release-process.md). AI agents working in this repository should start with [AGENTS.md](AGENTS.md); Claude Code users can also read [CLAUDE.md](CLAUDE.md), which points to the same canonical instructions.

## License

MIT

## Author

Samuel Gursky (samgursky@gmail.com)
- GitHub: [github.com/samuelgursky](https://github.com/samuelgursky)

## Acknowledgments

- Blackmagic Design for DaVinci Resolve and its scripting API
- The Model Context Protocol team for enabling AI assistant integration
