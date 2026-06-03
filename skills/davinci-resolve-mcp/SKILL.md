---
name: davinci-resolve-mcp
description: Use when working with DaVinci Resolve projects through the local davinci-resolve MCP server, including project inspection, timeline editing, media pool management, markers, color/Fusion/Fairlight/Deliver operations, Resolve script plugins, DCTLs, Fuses, UI automation fallbacks, or troubleshooting Resolve MCP connectivity.
---

# DaVinci Resolve MCP

Use the local `davinci-resolve` MCP server to work with DaVinci Resolve Studio
projects. Treat Resolve project state and source media as production assets:
verify before writing, and never modify source media unless the user asks for
that exact operation.

This skill is portable. Do not hard-code user-specific paths. Prefer:

- `DAVINCI_MCP_REPO` for the local checkout path
- `DAVINCI_MCP_PYTHON` for the Python interpreter
- `CODEX_HOME` for Codex configuration
- repo-relative helper paths when this skill is used from the checkout

## Local Setup

- MCP checkout: `$DAVINCI_MCP_REPO` or the repository containing this skill
- Server entrypoint: `$DAVINCI_MCP_REPO/src/server.py`
- Python: `$DAVINCI_MCP_PYTHON` or `$DAVINCI_MCP_REPO/.venv/bin/python`
- Codex config: `$CODEX_HOME/config.toml`
- Claude Desktop config:
  `~/Library/Application Support/Claude/claude_desktop_config.json`
- Detailed upstream skill reference: `$DAVINCI_MCP_REPO/docs/SKILL.md`
- Install/reference docs: `$DAVINCI_MCP_REPO/docs/install.md`
- Control panel docs: `$DAVINCI_MCP_REPO/docs/guides/control-panel.md`
- Read-only doctor:
  `$DAVINCI_MCP_REPO/skills/davinci-resolve-mcp/scripts/doctor.py`

If DaVinci MCP tools are not present in the active tool list, tell the user to
restart the MCP client so the server config is reloaded. Do not pretend to have
live Resolve tool access when the tools are not available.

Run the doctor when setup or connection state is unclear:

```bash
python skills/davinci-resolve-mcp/scripts/doctor.py
```

## Before Acting

1. Confirm the user's Resolve intent: inspect, organize, edit, grade, render,
   automate, or troubleshoot.
2. Use MCP tools directly when available. Start with
   `resolve_control(action="launch")`, then `get_version` and `get_page`.
3. If Resolve does not connect, check that DaVinci Resolve Studio is running and
   Preferences > General > External scripting using is set to `Local`. If the
   Python module imports but `scriptapp("Resolve")` returns false, this is the
   exact user-facing next action:

```text
App: DaVinci Resolve Studio
Exact screen: DaVinci Resolve > Settings/Preferences > General
Click path: External scripting using
Value: Local
Expected result: restart Resolve, then resolve_control(get_version) returns product/version
```

4. Before destructive actions such as delete project, delete clips, quit app, or
   overwrite exports, ask for explicit confirmation.
5. Re-fetch project, timeline, clip, and item IDs after destructive edits because
   Resolve API object references can become stale.

## UI Automation Fallback

Prefer Resolve's scripting API and MCP actions first. When Resolve has a UI
feature that is not exposed by `GetSetting/SetSetting` or any documented API
method, use macOS UI automation as the second layer instead of inventing visual
overlays or non-native workarounds. This is local, macOS-only, and requires
Accessibility permission, but it keeps the operation native inside Resolve.

Use the generic helper for menu-only features:

```bash
python skills/davinci-resolve-mcp/scripts/resolve_menu_click.py \
  Timeline "Output Blanking" 2.39
```

Use `--dry-run` before a new path, and `--list-menu-bar` when menu labels are
unclear. If the command reports `-1719`, `Hilfszugriff`, or assistive access,
tell the user the exact fix: `System Settings > Privacy & Security >
Accessibility`, then allow the app/process running the MCP client or
`osascript`/Terminal. UI automation must be verified with a read-back where
possible: Resolve settings snapshot, current page/timeline, rendered frame,
still, thumbnail, or visible menu state.

## Output Blanking

For native timeline output blanking, do not build overlay mattes unless the user
explicitly asks for that workaround. Resolve does not expose Timeline > Output
Blanking through the normal `GetSetting/SetSetting` API on tested builds, so use
the local macOS UI automation path:

- Preferred MCP action:
  `timeline(action="set_output_blanking_ui", params={"aspect": "2.39"})`
- Capabilities/readiness:
  `timeline(action="output_blanking_ui_capabilities")`
- Direct helper fallback:

```bash
python skills/davinci-resolve-mcp/scripts/resolve_output_blanking_ui.py 2.39
```

Common presets/aliases: `1.33`/`4:3`, `1.66`, `1.77`/`16:9`, `1.85`, `2.0`,
`2.35`, `2.39`, `2.40`, and `off`.

## Offline Media / Relink

For offline media, lead with a sanitized readback:

```text
timeline(action="detect_missing_media", params={"sanitized": true})
```

The response includes a `diagnosis` block with deduplicated Media Pool items,
missing volume roots, sample basenames, and a recommended next step. If a source
volume such as a camera card is not mounted, `build_relink_plan` skips broad
search by default and reports `skip_reason="missing_source_volume_not_mounted"`.
Mount the volume or pass `skip_search_when_volume_missing=false` only when a
bounded scan of approved roots is intentional.

Relinking is a Resolve project database change. Use `media_pool.safe_relink`
with explicit, user-approved paths after reviewing the plan.

## Page Context

Switch pages before page-sensitive work:

- Edit/Cut: timeline edits, tracks, generators, titles
- Media: media import and storage browsing
- Color: node graphs, CDL, Gallery stills
- Fusion: active Fusion composition work
- Fairlight: audio-specific work
- Deliver: render queue, render settings, export jobs

Use `resolve_control(action="open_page", params={"page": "<page>"})` when the
current page is wrong.

## Common Workflow

For a new Resolve task:

1. Launch/connect and get version/page.
2. Get current project via `project_manager(action="get_current")`.
3. Get current timeline via `timeline(action="get_current")`.
4. Fetch media pool clips or timeline items before editing.
5. Make the smallest safe MCP change.
6. Verify with a read-back tool call such as timeline/project/item get/list.

For visual inspection, prefer:

- `timeline_markers(action="get_thumbnail_image")` for an MCP image when the
  client can display images.
- `timeline_markers(action="get_thumbnail")` only when raw Resolve thumbnail
  data is needed by tooling.
- `gallery_stills(action="grab_and_export")` on the Color page when a standard
  image export is needed.

For the local control panel, prefer the MCP actions in current builds:

- `resolve_control(action="open_control_panel")`
- `resolve_control(action="control_panel_status")`
- `resolve_control(action="close_control_panel")`

If those actions are unavailable, run:

```bash
python -m src.control_panel --no-open
```

## Tool Families

The compound server exposes action-based tools. Key families:

- `resolve_control`, `layout_presets`, `render_presets`
- `project_manager`, `project_manager_folders`, `project_manager_database`,
  `project_manager_cloud`, `project_settings`
- `media_storage`, `media_pool`, `folder`, `media_pool_item`
- `timeline`, `timeline_markers`, `timeline_ai`
- `timeline_item`, `timeline_item_markers`, `timeline_item_fusion`,
  `timeline_item_color`, `timeline_item_takes`
- `timeline_versioning`, `gallery`, `gallery_stills`, `graph`, `color_group`,
  `fusion_comp`, `render`
- `fuse_plugin`, `dctl`, `script_plugin`
- `media_analysis`, `setup`

## Media Analysis Defaults

Source-safe does not mean underpowered. For Resolve-target media analysis, keep
visual analysis, transcription, persisted artifacts, metadata writeback, and
Media Pool marker writeback enabled unless the user explicitly opts out. If
`host_chat_paths` returns frame paths and a `vision_token`, read the frames as
images and finish the run with
`media_analysis(action="commit_vision", params={...})`; pending vision is not a
successful completed analysis.

Use these docs when needed:

- Media analysis: `docs/guides/media-analysis-guide.md`
- Editorial decisions: `docs/guides/editorial-decision-guide.md`
- Color decisions: `docs/guides/color-decision-guide.md`
- Kernel map: `docs/kernels/README.md`

When a failure involves Fuses, DCTLs, scripts, LUTs, OpenFX, Fusion templates,
workflow integrations, or codec plugins, read the relevant note from the repo's
`docs/authoring/`, `docs/notes/`, or `docs/integrations/` directory instead of
guessing.
