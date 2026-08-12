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

- `resolve-mcp` (`.claude/skills/resolve-mcp/SKILL.md`) — orientation/index: the map to the domain skills below (self-trigger; not an auto-loader)
- `resolve-color` (`.claude/skills/resolve-color/SKILL.md`) — grading, looks, shot match, LUT/CDL/DRX
- `resolve-edit` (`.claude/skills/resolve-edit/SKILL.md`) — cutting, ranges, variants, changelist
- `resolve-conform` (`.claude/skills/resolve-conform/SKILL.md`) — conform, relink, finishing QC, grade tracing
- `resolve-delivery` (`.claude/skills/resolve-delivery/SKILL.md`) — render, deliverable QC, media/provenance
- `resolve-fusion` (`.claude/skills/resolve-fusion/SKILL.md`) — Fusion comps (titles, motion graphics, VFX)
- `resolve-audio` (`.claude/skills/resolve-audio/SKILL.md`) — audio/Fairlight tracks, buses, loudness, sync
- `resolve-media-pool` (`.claude/skills/resolve-media-pool/SKILL.md`) — media pool ingest, organize, multicam
- `resolve-media-analysis` (`.claude/skills/resolve-media-analysis/SKILL.md`) — source-safe media intelligence

Each skill is a directory containing `SKILL.md`. Claude Code does not discover
loose `.md` files in `.claude/skills/`; a skill placed at the top level of that
directory silently never loads.

Two end-to-end assembly recipes sit alongside the domain skills. Where a domain
skill routes, these two walk a whole job:

- `resolve-rough-cut` (`.claude/skills/resolve-rough-cut/SKILL.md`) — **additive**:
  select shots from a folder of many clips into an assembled timeline.
- `resolve-tighten-recording` (`.claude/skills/resolve-tighten-recording/SKILL.md`)
  — **subtractive**: remove dead air from one long single-take recording.

Two more sit outside the domain routing:

- `house-style` (`.claude/skills/house-style/SKILL.md`) — accumulated editorial
  corrections, so the same note is not given twice. Claude-only; append to it
  when an editorial decision is corrected.
- `resolve-session` (`.claude/skills/resolve-session/SKILL.md`) — `/resolve-session`
  connects, confirms edition and bridge, and reports project/timeline/pool state.

The offline half of every one is the advanced server; see
[Advanced Server](../resolve-advanced/README.md).

## Claude Code Hooks and Subagents

Two `PreToolUse` guards enforce rules `AGENTS.md` states in prose. They ship as
scripts but are **not** wired up by default — the repository does not enable
hooks on your behalf. Opt in by adding the block below to your own
`.claude/settings.local.json` (gitignored, so it stays yours):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "mcp__davinci-resolve__(timeline_item_color|color_group)",
        "hooks": [
          {
            "type": "command",
            "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/frame_verification_guard.py",
            "timeout": 15
          }
        ]
      },
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/source_media_guard.py",
            "timeout": 15
          }
        ]
      }
    ]
  }
}
```

Hooks are read at session start, so restart Claude Code after adding them. The
two guards are:

- `.claude/hooks/frame_verification_guard.py` — denies grade-applying actions on
  `timeline_item_color` until the session has actually looked at a
  Resolve-rendered frame, and asks before whole-grade artifacts
  (`safe_copy_grade`, `bulk_match_to_hero`) overwrite hand-work. `dry_run`
  passes through untouched.
- `.claude/hooks/source_media_guard.py` — denies shell commands that write,
  move, or delete source media outside a scratch root. Reads (`ffprobe`, and
  `ffmpeg` writing into scratch) pass.

Two review subagents in `.claude/agents/` run in their own context so frame
images stay out of the main session:

- `cut-reviewer` — screens an assembled timeline from its frames and reports on
  pacing, shot order, continuity, and coverage gaps.
- `grade-match-verifier` — measures shot match numerically from rendered frames
  against the project's R−B tolerance, and reports mask pixel counts so an empty
  skin mask cannot pass as a match.

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
