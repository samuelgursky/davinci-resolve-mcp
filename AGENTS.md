# DaVinci Resolve MCP Server — AI Agent Instructions

This file provides instructions for any AI coding assistant working with this project.

## Project Overview

Python MCP server providing 30 compound tools (or 328 granular tools in `--full` mode) for controlling DaVinci Resolve via its Scripting API. 100% API coverage, 98.5% live-tested, with 109 guarded kernel workflow actions.

## Key Paths

- Main server: `src/server.py` (compound, 30 tools — recommended)
- Full server: `src/resolve_mcp_server.py` (granular, 328 tools)
- Utilities: `src/utils/`
- Tests: `tests/` (5-phase live API test suite)
- Installer: `install.py` (supports 10+ MCP clients)
- API reference: `docs/resolve_scripting_api.txt`

## Running

```bash
python src/server.py          # Compound server (recommended)
python src/server.py --full   # Full 328-tool server
```

## Source Media Integrity — Non-Negotiable

**Never modify, transcode, convert, create proxies of, or create any derivative of source media files unless the user explicitly requests it.**

This applies to all tools, workflows, and automation in this project:

- Analysis tools (FFprobe, FFmpeg) read source files — they never write to them
- All analysis output goes to designated sidecar files or analysis directories
- No export-and-reimport cycles — always reference the original
- The chain from camera original to final delivery must remain unbroken
- If a user needs proxies, transcodes, or conversions, they will ask

For the full rationale from every post-production department, see `docs/media-analysis-guide.md`.

## Media Analysis Guide

This project includes a guide for using FFprobe, FFmpeg, and Whisper to analyze source media so the MCP can operate with full context. Read `docs/media-analysis-guide.md` for:

- Read-only analysis commands (FFprobe metadata, FFmpeg loudness/scene detection, Whisper transcription)
- JSON sidecar output format
- How to connect analysis results to MCP actions
- Proactive warnings for VFR, HDR, interlaced content, timecode issues
- Setup workflow for first interaction

## MCP Tool Categories

The 30 compound tools cover:

| Tool | Purpose |
|------|---------|
| `resolve_control` | App control, version, pages |
| `project_manager` | Project CRUD and management |
| `project_manager_folders` | Project Manager folder navigation and CRUD |
| `project_manager_database` | Project database listing and switching |
| `project_manager_cloud` | Cloud project create/load/import/restore wrappers |
| `project_settings` | Project properties and metadata |
| `media_storage` | Volume browsing, media import |
| `media_pool` | Folders, clips, timelines |
| `folder` | Media Pool folder clip listing, export, transcription |
| `media_pool_item` | Clip metadata, properties, transcription |
| `media_pool_item_markers` | Clip markers, flags, custom data, clip color |
| `timeline` | Timeline structure, generators, titles |
| `timeline_markers` | Timeline marker operations |
| `timeline_ai` | Subtitles, scene cuts, Dolby Vision |
| `timeline_item` | Item properties, transforms, keyframes |
| `timeline_item_markers` | Timeline item markers, flags, custom data, clip color |
| `timeline_item_color` | Grading, LUTs, versions, AI tools |
| `timeline_item_fusion` | Fusion composition management on timeline items |
| `timeline_item_takes` | Timeline item take management |
| `render` | Render pipeline, jobs, formats |
| `render_presets` | Render and burn-in preset import/export |
| `gallery` / `gallery_stills` | Still albums and power grades |
| `graph` | Node graph operations |
| `color_group` | Color group names, clips, pre/post clip graphs |
| `fusion_comp` | Fusion composition node graph operations |
| `fuse_plugin` | Fusion Fuse authoring and lifecycle helpers |
| `dctl` | DCTL and ACES transform authoring helpers |
| `script_plugin` | Resolve-page script authoring and execution helpers |
| `layout_presets` | Resolve UI layout preset management |

Each tool uses an `action` parameter to select the specific operation.

## Kernel Action Coverage

The README tracks 109 higher-level kernel actions across 8 compound tools. These are MCP workflow actions layered on top of the public Resolve API for timeline editing, ingest, render/deliver, review annotation, color/grade, Fusion composition, conform/interchange, audio/Fairlight, project lifecycle, and extension authoring.

## Development Guidelines

- Python 3.10+ required (3.11 or 3.12 recommended; 3.13+ may have ABI issues with Resolve)
- Uses `mcp` and `fastmcp` packages (installed in venv)
- All tools return dict responses with consistent error format
- Lazy connection to Resolve (auto-launches if not running)
- Platform-specific paths handled in `src/utils/platform.py`
