---
name: release-check
description: Walk through a version bump and release for the DaVinci Resolve MCP server — version selection, every file that needs updating, required validation, tag, and GitHub Release.
---

# Release Check

`AGENTS.md` is explicit: this repository does not maintain a separate release
checklist here or anywhere else — [docs/process/release-process.md](../../../docs/process/release-process.md)
is the single source of truth for version bumps, validation, tags, and GitHub
Releases. This skill does not restate that checklist; restating it would
create a second copy that can drift from the original.

## Steps

1. Read `docs/process/release-process.md` in full, current from disk — not
   from memory of a prior run. It changes as the release process hardens.
2. Follow it top to bottom: version selection, every file under "Files To
   Update," the "Required Validation" section, and the tag/GitHub Release
   steps at the end.
3. Report progress against that doc's own sections as you go, so the user can
   see which step you're on. Do not invent extra steps or skip any listed
   file — the doc calls out drift guards (`test_api_limitations_doc`,
   `test_panel_docs_drift`, etc.) that fail CI if a listed file is missed.
4. If the doc's content is genuinely ambiguous or conflicts with the current
   repo state, stop and ask rather than guessing — this is release engineering
   on a published package, not exploratory work.
