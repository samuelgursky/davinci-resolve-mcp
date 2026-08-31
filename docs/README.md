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

## Portable Agent Skills

Per-domain skills in `.agents/skills/` route craft ↔ live tools ↔ offline
advanced tools automatically when an agent works in that domain. This is the
canonical, client-neutral source. Codex discovers it directly; Claude Code loads
`.claude/skills/` copies that are CONTENT-COMPLETE and byte-identical to the
canonical files — Claude routes on the frontmatter description at selection
time, so a pointer stub would degrade skill routing. Edit either copy, then run
`scripts/agent-rules/sync_portable_assets.py`; the parity guard
(`tests/test_portable_asset_parity.py`) fails the suite on drift.

- `resolve-mcp` — orientation/index: the map to the domain skills below (self-trigger; not an auto-loader)
- `resolve-color` — grading, looks, shot match, LUT/CDL/DRX
- `resolve-edit` — cutting, ranges, variants, changelist
- `resolve-conform` — conform, relink, finishing QC, grade tracing
- `resolve-delivery` — render, deliverable QC, media/provenance
- `resolve-fusion` — Fusion comps (titles, motion graphics, VFX)
- `resolve-audio` — audio/Fairlight tracks, buses, loudness, sync
- `resolve-media-pool` — media pool ingest, organize, multicam
- `resolve-media-analysis` — source-safe media intelligence

Each canonical skill is a directory containing `SKILL.md`. The Claude adapter
uses the same directory shape because Claude Code does not discover loose files.

Two end-to-end assembly recipes sit alongside the domain skills. Where a domain
skill routes, these two walk a whole job:

- `resolve-rough-cut` — **additive**:
  select shots from a folder of many clips into an assembled timeline.
- `resolve-tighten-recording`
  — **subtractive**: remove dead air from one long single-take recording.

Three more sit outside the domain routing:

- `house-style` — accumulated editorial
  corrections, so the same note is not given twice. Append to it
  when an editorial decision is corrected.
- `resolve-session` — `/resolve-session`
  connects, confirms edition and bridge, and reports project/timeline/pool state.
- `release-check` — `/release-check`
  walks a version bump using [docs/process/release-process.md](process/release-process.md)
  as the sole source; the skill wraps that doc, it does not duplicate it.

The offline half of every one is the advanced server; see
[Advanced Server](../resolve-advanced/README.md).

## Portable Hooks and Reviewers

Four canonical hooks live in `.agents/hooks/` — two `PreToolUse` guards
enforcing rules `AGENTS.md` states in prose, and two `PostToolUse` checks that
surface engineering drift immediately after the edit that caused it. Thin
wrappers in `.claude/hooks/` and `.codex/hooks/` translate only the host
protocol; policy stays in the canonical scripts.

Codex wiring is committed in `.codex/hooks.json`. Because project hooks execute
commands, review and trust that file through Codex's `/hooks` UI. Claude Code
users opt in by adding this block to `.claude/settings.local.json`:

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
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/agent_rules_drift_check.py",
            "timeout": 30
          },
          {
            "type": "command",
            "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/run_matching_test.py",
            "timeout": 90
          }
        ]
      }
    ]
  }
}
```

Hooks are read at session start, so restart the client after enabling them. The
four canonical policies are:

- `.agents/hooks/frame_verification_guard.py` — denies grade-applying actions on
  `timeline_item_color` until the session has actually looked at a
  Resolve-rendered frame, and asks before whole-grade artifacts
  (`safe_copy_grade`, `bulk_match_to_hero`) overwrite hand-work. `dry_run`
  passes through untouched.
- `.agents/hooks/source_media_guard.py` — denies shell commands that write,
  move, or delete source media outside a scratch root. Reads (`ffprobe`, and
  `ffmpeg` writing into scratch) pass.
- `.agents/hooks/agent_rules_drift_check.py` — after an edit to anything
  `generate.mjs` reads (`docs/SKILL.md`, `docs/kernels/README.md`,
  `resolve-advanced/README.md`, and `generate.mjs` itself, which carries the
  DOMAINS manifest inline) or to `AGENTS.md`, which it writes, runs
  `node scripts/agent-rules/generate.mjs --check` and surfaces the result. It
  distinguishes real drift from a generator that threw before it could look —
  regenerating fixes the first and not the second. Informational only; never
  blocks. Skips quietly if `node` isn't on `PATH`. **If `generate.mjs` grows a
  new input, add it to `SOURCE_PATHS` in the hook** — an unwatched input is a
  silent hook on exactly the edit it exists to catch.
- `.agents/hooks/run_matching_test.py` — after an edit to `src/<module>.py`,
  runs the matching `tests/test_<module>.py` if one exists, using the project
  venv (`venv/bin/python`) so `pytest` is actually importable. Informational
  only; skips quietly if there's no matching test file or no working `pytest`.
  A fast partial net, not coverage: 72 of the 126 modules under `src/` have a
  matching test under this convention, densely in `src/utils/` and not at all
  for `src/server.py` or `src/granular/common.py`. Silence means "no matching
  test file", not "this edit is fine".

Codex does not currently support an interactive `ask` result from `PreToolUse`.
For the two whole-grade actions, its adapter adds a warning while the MCP
server's confirmation-token gate remains authoritative. Hard denials, including
missing frame evidence and source-media writes, block in both clients.

Three canonical reviewer roles live in `.agents/roles/`, with native Codex
definitions under `.codex/agents/` and Claude adapters under `.claude/agents/`:

- `cut-reviewer` — screens an assembled timeline from its frames and reports on
  pacing, shot order, continuity, and coverage gaps.
- `grade-match-verifier` — measures shot match numerically from rendered frames
  against the project's R−B tolerance, and reports mask pixel counts so an empty
  skin mask cannot pass as a match.
- `drift-guard-reviewer` — runs the doc/generated-file drift-guard test family
  (the same checks `npm-publish.yml` runs before every release) and reports
  which files are stale relative to their source, without fixing them.

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
