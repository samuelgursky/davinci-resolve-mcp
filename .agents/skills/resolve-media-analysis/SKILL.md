---
name: resolve-media-analysis
description: Media intelligence layer for the DaVinci Resolve MCP. Uses FFprobe, FFmpeg, and optionally Whisper to READ and ANALYZE source media — never modify, transcode, convert, or create derivatives. Provides the MCP with full context of what footage actually is so it can take informed actions within Resolve.
---

# Resolve Media Analysis
This skill wraps the project's canonical media analysis guide with Claude Code-specific integration.

**Read `docs/guides/media-analysis-guide.md` for the complete guide.** Everything below is Claude Code-specific context.

## The First Rule

**Never touch the source.** Your relationship to source media is READ-ONLY. See `docs/guides/media-analysis-guide.md` section "The First Rule: Never Touch the Source" for the full rationale from every post-production department.

## What this build cannot do (check before you offer it)

The scripting API changes per **patch** release, so "Resolve 21" is not a usable
label. Read `resolve_control get_version` → `build.unavailable_on_this_build`
before offering a gated surface; `check_version_support` asks about one named
symbol. Gated in *this* domain — note all of it is Resolve's **own** analysis,
not this repo's:

| Surface | Needs | If absent |
|---|---|---|
| `MediaPoolItem` / `Folder.AnalyzeForIntellisearch` | 21.0 | No IntelliSearch index |
| `Project.ResetIntellisearchAnalysis` | 21.0 | The index cannot be cleared from a script |
| `MediaPoolItem` / `Folder.AnalyzeForSlate` | 21.0 | No automatic slate detection |
| `MediaPoolItem` / `Folder.PerformAudioClassification` / `ClearAudioClassification` | 21.0 | No Resolve-side audio classification |
| `MediaPoolItem` / `Folder.RemoveMotionBlur` | 21.0 | Unavailable |
| `Project.GenerateSpeech` | 21.0 | No AI speech generation |

**This repo's own analysis stack does not depend on any of them.** `analyze_media`
reads frames and audio off disk and runs its own vision/transcription/embedding
tiers, so an older Resolve loses Resolve's AI features, not this pipeline. Say
which one the user is actually missing.

An empty `unavailable_on_this_build` means **nothing recorded is missing**, not
that everything exists — most of the API has never been version-bisected. A
symbol with no gate returns `unknown`, which means probe it. Probe with
`name in dir(obj)`, never bare `hasattr`: on a Resolve object `hasattr` returns
`True` for every name, real or invented, so it can only say yes.

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

## Deliverables from a transcript

- **`generate_captions(clip_ref, format='srt'|'vtt', with_chapters=?)`** — caption
  blocks under broadcast rules: line-length and lines-per-block caps, max **and
  min** block duration, breaks at sentence ends then pauses then clauses, timings
  snapped to spoken words, a minimum inter-block gap, no single-word orphan.
  Never drops a word to make text fit — it refuses instead.
- **`assess_grade`** — numeric grade-damage QC on a decoded frame. See the
  color-grade skill; it is exposed here because it lives beside the other frame
  analysis. `image_qc_capabilities` reports numpy/ffmpeg availability and the
  cost tiers.

## Setup

On first use, ask the user the three setup questions documented in the guide:
1. Where to save analysis files (alongside / directory / project)
2. Tool detection (FFprobe required, FFmpeg/Whisper optional)
3. Analysis depth (quick / standard / deep)

## Full Reference

All analysis commands, output format, examples, proactive warnings, and principles are in `docs/guides/media-analysis-guide.md`. Do not duplicate that content — read and follow it.
