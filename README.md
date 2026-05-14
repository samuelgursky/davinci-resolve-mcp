# DaVinci Resolve MCP Server

[![Version](https://img.shields.io/badge/version-2.17.0-blue.svg)](https://github.com/samuelgursky/davinci-resolve-mcp/releases)
[![API Coverage](https://img.shields.io/badge/API%20Coverage-100%25-brightgreen.svg)](docs/reference/api-coverage.md)
[![Tools](https://img.shields.io/badge/MCP%20Tools-31%20(328%20full)-blue.svg)](#server-modes)
[![Tested](https://img.shields.io/badge/Live%20Tested-98.5%25-green.svg)](docs/reference/api-coverage.md#test-results)
[![DaVinci Resolve](https://img.shields.io/badge/DaVinci%20Resolve-18.5+-darkred.svg)](https://www.blackmagicdesign.com/products/davinciresolve)
[![Python](https://img.shields.io/badge/python-3.10--3.12-green.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://opensource.org/licenses/MIT)

A Model Context Protocol (MCP) server that lets AI assistants control DaVinci Resolve Studio through the official Scripting API. It provides full API coverage plus guarded workflow helpers for editing, media pool organization, render setup, review markers, grading, Fusion, Fairlight, project lifecycle tasks, extension authoring, and source-safe media analysis.

## Quick Start

```bash
git clone https://github.com/samuelgursky/davinci-resolve-mcp.git
cd davinci-resolve-mcp
python install.py
```

Before connecting, open DaVinci Resolve Studio and set **Preferences > General > External scripting using** to **Local**. The installer creates a virtual environment, detects Resolve paths, and can configure Claude Desktop, Claude Code, Cursor, VS Code, Windsurf, Zed, Continue, Cline, Roo Code, and JetBrains IDEs.

For platform paths, client-specific config, and manual setup, see [Installation and Configuration](docs/install.md).

## Server Modes

| Mode | Entry point | Tools | Best for |
|------|-------------|-------|----------|
| Compound | `src/server.py` | 31 | Default mode for most assistants. Related Resolve operations are grouped behind action parameters to keep context usage low. |
| Full / granular | `src/server.py --full` or `src/resolve_mcp_server.py` | 328 | Power users who want one MCP tool per Resolve API method. |

The compound server is recommended unless you specifically need the granular one-tool-per-method surface.

## What You Can Do

```text
"List all projects and open the one called 'My Film'"
"Create a timeline called 'Assembly Cut' from all clips in the current bin"
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
| Media pool and ingest | Safe import, image sequences, bin organization, metadata normalization, marks, annotations, relink/proxy/full-resolution guards |
| Media analysis | Read-only file/clip/bin/project analysis, session-only defaults, existing-report reuse, chat-context visual analysis by default in `analyze_media` with opt-out, optional transcription |
| Timeline editing and conform | Track/item probing, copy/move/duplicate helpers, range operations, gaps/overlaps, source ranges, checked interchange exports/imports |
| Review annotations | Timeline/item/clip markers, custom data, flags, clip color, copy/move/sync cleanup, review reports, marker thumbnail review |
| Color and grading | Node graph probing, CDL validation, grade copy, DRX/LUT helpers, versions, Gallery stills, color groups |
| Fusion | Timeline-item comps, safe tool creation, input writes, port inspection, validated connections, scoped bulk writes |
| Audio and Fairlight | Track/item probes, source mapping, guarded audio property writes, voice isolation, auto-sync planning, transcription/subtitle probes |
| Render and deliver | Format/codec matrix probing, render settings validation, queued job lifecycle checks, guarded Quick Export |
| Extension authoring | Fuse, DCTL, ACES DCTL, and Resolve-page Lua/Python script lifecycle helpers with safe MCP-marked install/remove |

## Source Media Safety

This project treats camera originals and source media as immutable. Analysis tools read source files and write reports only to sidecar or project analysis directories. The server must not modify, transcode, proxy, or create derivatives of source media unless the user explicitly asks for that. See [Media Analysis Guide](docs/guides/media-analysis-guide.md) for the detailed source-safe workflow.

## Key Stats

| Metric | Value |
|--------|-------|
| MCP Tools | **31** compound / **328** granular |
| Kernel Actions | **128** guarded workflow actions across 9 compound tools |
| API Methods Covered | **336/336** (100%) |
| Methods Live Tested | **331/336** (98.5%) |
| Live Test Pass Rate | **331/331** (100%) |
| Tested Against | DaVinci Resolve 19.1.3 Studio + Resolve 20.3.2 Studio |

For method-by-method status, see [API Coverage and Test Results](docs/reference/api-coverage.md). For current workflow support, see [Kernel Action Coverage](docs/kernels/README.md).

`analyze_media` uses in-chat visual analysis by default when the MCP client supports sampling/image messages. Pass `include_visuals=false` for technical-only or privacy-sensitive runs. If in-chat vision is unavailable, analysis continues with local technical/motion evidence and reports the skipped visual layer.

## Documentation

| Document | Use it for |
|----------|------------|
| [Installation and Configuration](docs/install.md) | Requirements, installer options, supported clients, server modes, manual config |
| [API Coverage and Test Results](docs/reference/api-coverage.md) | Key stats, API coverage table, live-test status, full method reference |
| [Kernel Action Coverage](docs/kernels/README.md) | Current guarded workflow action map |
| [AI Skill Reference](docs/SKILL.md) | Operational context for AI assistants using the compound server |
| [Media Analysis Guide](docs/guides/media-analysis-guide.md) | Source-safe FFprobe, FFmpeg, Whisper, sidecar, and analysis-root workflows |
| [Editorial Decision Guide](docs/guides/editorial-decision-guide.md) | Project-owned editorial craft guidance for analysis and timeline decisions |
| [Color Decision Guide](docs/guides/color-decision-guide.md) | Project-owned color correction guidance and Resolve color API boundaries |
| [Contributing and Project Layout](docs/contributing.md) | Contribution workflow, platform support, security notes, repository structure |
| [Release Process](docs/process/release-process.md) | Maintainer release checklist, version surfaces, validation, tags, and release notes |
| [Changelog](CHANGELOG.md) | Historical release notes |

Extension authoring references live in [docs/authoring](docs/authoring/). Resolve developer-package notes live in [docs/notes](docs/notes/) and [docs/integrations](docs/integrations/). Prompt recipes live in [examples](examples/).

## Requirements

- DaVinci Resolve Studio 18.5+ on macOS, Windows, or Linux. The free edition does not support external scripting.
- Python 3.10-3.12 recommended. Python 3.13+ may have ABI incompatibilities with Resolve's scripting library.
- Resolve external scripting set to **Local**.

Resolve 19.1.3 remains the compatibility baseline. Resolve 20.x scripting calls are additive, version-guarded, and live-tested on 20.3.2. Resolve 21 beta APIs are intentionally deferred until stable.

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
- Anthropic for Claude Code, used extensively in development and testing
