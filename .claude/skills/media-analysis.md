---
name: resolve-media-analysis
description: Media intelligence layer for the DaVinci Resolve MCP. Uses FFprobe, FFmpeg, and optionally Whisper to READ and ANALYZE source media — never modify, transcode, convert, or create derivatives. Provides the MCP with full context of what footage actually is so it can take informed actions within Resolve.
---

# Resolve Media Analysis — Claude Code Skill

This skill wraps the project's canonical media analysis guide with Claude Code-specific integration.

**Read `docs/media-analysis-guide.md` for the complete guide.** Everything below is Claude Code-specific context.

## The First Rule

**Never touch the source.** Your relationship to source media is READ-ONLY. See `docs/media-analysis-guide.md` section "The First Rule: Never Touch the Source" for the full rationale from every post-production department.

## MCP Integration

When using the DaVinci Resolve MCP tools alongside media analysis:

### Getting File Paths from Resolve

1. **From media pool clips:** `media_pool_item` -> `get_clip_property(clip_id)` returns `"File Path"`
2. **From timeline items:** `timeline_item` -> `get_media_pool_item(item_id)` -> then get clip properties
3. **From media storage:** `media_storage` -> `get_files(path)` lists files in a directory

### Workflow: Analyze Before Acting

1. **Identify the media** — Use MCP to get clip IDs and file paths
2. **Check for existing analysis** — Look for sidecar JSON files
3. **Analyze if needed** — Run FFprobe (+ optional tools) on the files
4. **Act with context** — Use MCP tools with full knowledge of what the media is

Analysis informs Resolve actions. At no point do we create intermediate files that enter the media pipeline.

## Setup

On first use, ask the user the three setup questions documented in the guide:
1. Where to save analysis files (alongside / directory / project)
2. Tool detection (FFprobe required, FFmpeg/Whisper optional)
3. Analysis depth (quick / standard / deep)

## Full Reference

All analysis commands, output format, examples, proactive warnings, and principles are in `docs/media-analysis-guide.md`. Do not duplicate that content — read and follow it.
