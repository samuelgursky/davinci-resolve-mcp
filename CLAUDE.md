# CLAUDE.md

## Project Overview

DaVinci Resolve MCP Server — provides complete coverage of the DaVinci Resolve Scripting API via MCP (Model Context Protocol). Two server modes: compound (26 tools) and full/granular (342 tools).

## Version Locations

When bumping the version, ALL of these must be updated:

- `src/server.py` → `VERSION = "x.y.z"`
- `src/resolve_mcp_server.py` → `VERSION = "x.y.z"`
- `README.md` → version badge on line 3: `badge/version-x.y.z-blue.svg`
- `README.md` → "What's New in vX.Y.Z" section (add new, demote previous)

## Release Checklist (MANDATORY for every version bump)

Every incremental update MUST include ALL of the following before the commit is made:

1. **Bump `VERSION` in both server files** — `src/server.py` and `src/resolve_mcp_server.py` must match
2. **Update README.md version badge** — the shields.io badge on line 3 must reflect the new version
3. **Update README.md changelog** — add a new "What's New in vX.Y.Z" section at the top, demote the previous version's section to just "### vX.Y.Z"
4. **Update any other badges** if tool count, API coverage, or test percentage changed
5. **After pushing, create/update the GitHub release** — use `gh release create vX.Y.Z` (or `gh release edit`) with:
   - Tag: `vX.Y.Z`
   - Title: `vX.Y.Z`
   - Body: the changelog entry from the README
6. **Verify the release** — `gh release view vX.Y.Z` to confirm it's live

Do NOT commit a version bump without completing steps 1-4. Steps 5-6 happen after push.

## Coding Conventions

- Python 3.10+, no type stubs needed
- Helper functions prefixed with `_` (e.g., `_err`, `_ok`, `_check`, `_resolve_safe_dir`)
- Compound server tools use action-based dispatch pattern
- All temp/sandbox paths must go through `_resolve_safe_dir()` — never use `tempfile.gettempdir()` directly for paths Resolve will write to
- Commit messages use conventional format: `feat:`, `fix:`, `docs:`, `security:`, `refactor:`
