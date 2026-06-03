---
name: davinci-resolve-mcp
description: Work with DaVinci Resolve projects through the local davinci-resolve MCP server, including project inspection, timeline editing, media pool management, Output Blanking UI fallback, offline media diagnosis, and Resolve MCP troubleshooting.
---

# DaVinci Resolve MCP — Claude Skill Wrapper

This is a Claude-compatible wrapper for the canonical repo skill.

Read and follow:

`skills/davinci-resolve-mcp/SKILL.md`

Use the helper scripts from:

`skills/davinci-resolve-mcp/scripts/`

Do not duplicate local machine paths into this wrapper. The canonical skill uses
environment variables and repo-relative paths so it can be installed into Codex,
Claude, OpenCode, OpenClaude, or another MCP client without user-specific path
leaks.
