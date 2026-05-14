# DaVinci Resolve MCP Examples

These examples are prompt recipes for MCP clients such as Claude, Cursor,
Windsurf, Codex, and VS Code. The server exposes 31 compound MCP tools and 128
higher-level kernel actions, so examples should be written as safe
agent-facing workflows rather than legacy direct `DaVinciResolveScript` scripts.

## Before Running Examples

1. Open DaVinci Resolve Studio.
2. Enable external scripting in Resolve preferences.
3. Install or configure this MCP server with `python install.py`.
4. Use disposable projects, synthetic media, or explicitly approved demo media.
5. Never modify, transcode, proxy, relink, or create derivatives of source media
   unless the user explicitly asks for that operation.

## Example Categories

| Directory | Focus |
|-----------|-------|
| `markers/` | Timeline, timeline item, and media pool item annotation workflows |
| `timeline/` | Timeline inspection, edit kernel operations, conform reports, and render planning |
| `media/` | Safe ingest, metadata normalization, media analysis, and source-integrity guardrails |

## Getting Started Prompt

Paste this into an MCP-enabled client:

```text
Check that DaVinci Resolve is connected. Report the Resolve version, current
page, current project, current timeline, and the MCP kernel surfaces available
for safe project, ingest, timeline, annotation, color, Fusion, audio, render,
and extension workflows. Do not mutate anything yet.
```

Good first follow-up:

```text
Create a disposable _mcp_demo_* project only if needed, then show me a dry-run
plan before importing media, editing a timeline, changing render settings, or
installing any extension files.
```

## Creating New Examples

New examples should be small prompt recipes with:

- The intended Resolve state.
- The exact prompt to paste into an MCP client.
- The expected MCP tools/actions.
- Safety notes, especially around source media, relinks, renders, archives, and
  extension installs.
- Cleanup steps for disposable projects or temp files.
