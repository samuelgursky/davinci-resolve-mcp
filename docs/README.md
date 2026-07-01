# DaVinci Resolve MCP Documentation

This folder keeps durable project documentation. Temporary research notes,
session logs, and build gameplans should live outside this folder or under
ignored scratch folders such as `docs/_scratch/`.

## Operating References

- [Installation and Configuration](install.md) — requirements, supported MCP
  clients, installer options, server modes, and manual configuration.
- [API Coverage and Test Results](reference/api-coverage.md) — current stats,
  live-test status, and the method-by-method Resolve API reference.
- [AI Skill Reference](SKILL.md) — operational context for AI assistants using
  the compound MCP server.
- [Media Analysis Guide](guides/media-analysis-guide.md) — source-safe FFprobe, FFmpeg,
  Whisper, sidecar, and analysis-root workflows.
- [Multicam Setup Helper Guide](guides/multicam-setup-guide.md) — source-safe
  stacked timeline prep, helper/API boundary, and Resolve UI conversion steps.
- [Editorial Decision Guide](guides/editorial-decision-guide.md) — project-owned
  editorial craft guidance for analysis and edit decisions.
- [Color Decision Guide](guides/color-decision-guide.md) — project-owned color
  correction guidance and Resolve color API boundaries.
- [Resolve Scripting API Reference](reference/resolve_scripting_api.txt) — bundled
  Resolve scripting API text used for parity checks.
- [Contributing and Project Layout](contributing.md) — contribution workflow,
  platform support, security notes, and repository structure.
- [Release Process](process/release-process.md) — maintainer release checklist.
- [Changelog](../CHANGELOG.md) — historical release notes.

## Kernel Support Maps

- [Kernel Action Coverage](kernels/README.md)
- [Timeline Edit](kernels/timeline-edit-kernel.md)
- [Media Pool / Ingest](kernels/media-pool-ingest-kernel.md)
- [Render / Deliver](kernels/render-deliver-kernel.md)
- [Review Annotation](kernels/review-annotation-kernel.md)
- [Color / Grade](kernels/color-grade-kernel.md)
- [Fusion Composition](kernels/fusion-composition-kernel.md)
- [Timeline Conform / Interchange](kernels/timeline-conform-interchange-kernel.md)
- [Audio / Fairlight](kernels/audio-fairlight-kernel.md)
- [Project Lifecycle](kernels/project-lifecycle-kernel.md)
- [Extension Authoring](kernels/extension-authoring-kernel.md)

## Claude Code Skills

Per-domain skills in `.claude/skills/` route craft ↔ live tools ↔ offline
advanced tools automatically when an agent works in that domain. They are thin
bridges — the authoritative depth stays in the kernels and guides above.

- `resolve-mcp` (`.claude/skills/resolve.md`) — orientation/index: the map to the domain skills below (self-trigger; not an auto-loader)
- `resolve-color` (`.claude/skills/color-grade.md`) — grading, looks, shot match, LUT/CDL/DRX
- `resolve-edit` (`.claude/skills/timeline-edit.md`) — cutting, ranges, variants, changelist
- `resolve-conform` (`.claude/skills/conform.md`) — conform, relink, finishing QC, grade tracing
- `resolve-delivery` (`.claude/skills/delivery.md`) — render, deliverable QC, media/provenance
- `resolve-fusion` (`.claude/skills/fusion.md`) — Fusion comps (titles, motion graphics, VFX)
- `resolve-audio` (`.claude/skills/audio.md`) — audio/Fairlight tracks, buses, loudness, sync
- `resolve-media-pool` (`.claude/skills/media-pool.md`) — media pool ingest, organize, multicam
- `resolve-media-analysis` (`.claude/skills/media-analysis.md`) — source-safe media intelligence

The offline half of every one is the advanced server; see
[Advanced Server](../resolve-advanced/README.md).

## Authoring References

- [Fuse + DCTL Authoring](authoring/fuse-dctl-authoring.md)
- [Script Plugin Authoring + Conversational Lua/Python](authoring/script-plugin-authoring.md)

## Resolve Developer-Package References

- [Workflow Integrations](integrations/workflow-integrations.md)
- [OpenFX](notes/openfx-notes.md)
- [LUTs](notes/lut-notes.md)
- [Fusion Templates](notes/fusion-template-notes.md)
- [DCTL](notes/dctl-notes.md)
- [Codec Plugins](notes/codec-plugin-notes.md)
