# Release Process

This checklist is the required path for version bumps, tags, and GitHub
Releases. It exists so fixes do not ship without the matching release artifact,
and so Resolve behavior changes are live-tested before release.

## Version Selection

Use semantic versioning:

- Patch (`x.y.Z`) for bug fixes, docs, test harnesses, and release-process
  hardening that do not add public tool surface.
- Minor (`x.Y.0`) for new MCP actions, new documented parameters, new tools, or
  workflow capabilities.
- Major (`X.0.0`) for breaking behavior, renamed tools/actions, or removed
  public API surface without a compatible replacement.

When in doubt, choose the smallest version bump that accurately describes the
public API impact.

## Files To Update

Every release bump must update all version surfaces:

- `src/server.py`
- `src/granular/common.py`
- `install.py`
- `package.json`
- README version badge
- README current stats or latest-release summary when they changed
- `CHANGELOG.md` latest release entry
- `docs/SKILL.md` when tool discovery, examples, or behavior changed
- Git tag, e.g. `v2.4.1`
- GitHub Release notes

Do not consider a release complete until the GitHub Release exists and is marked
latest when appropriate.

## Required Validation

Always run static checks before release:

```bash
venv/bin/python tests/test_import.py
venv/bin/python scripts/audit_api_parity.py
node bin/davinci-resolve-mcp.mjs --help
node bin/davinci-resolve-mcp.mjs --version
npm pack --dry-run
git diff --check
```

Run focused unit tests for the changed surface. For recent timeline/marker
helpers, this usually includes:

```bash
venv/bin/python -m unittest tests.test_extract_source_frame_ranges tests.test_marker_params tests.test_v232_helpers tests.test_v233_helpers tests.test_append_clip_infos_result_handling
```

Behavior changes that touch DaVinci Resolve scripting must also have a live
Resolve validation before release. Use disposable projects and synthetic media
only. Never modify, transcode, proxy, or create derivatives of source media
unless the user explicitly requests it.

Examples:

```bash
env RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting" \
  RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so" \
  PYTHONPATH="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules" \
  python3.11 tests/live_marker_validation.py

env RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting" \
  RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so" \
  PYTHONPATH="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules" \
  venv/bin/python tests/live_v233_validation.py
```

One-off live harnesses are acceptable during review, but reusable coverage
should live under `tests/`. Do not commit generated media or disposable project
artifacts.

Docs-only releases do not require a Resolve live run, but the release notes
should say that no behavior changed.

## Release Checklist

1. Start from a clean tracked worktree. Leave unrelated untracked user files
   alone.
2. Merge or land the feature/fix commit.
3. Update all version surfaces, README current stats, and `CHANGELOG.md`.
4. Run required static checks, focused unit tests, and live Resolve validation
   when behavior changed.
5. Commit the release bump with a conventional commit, for example:

   ```bash
   git commit -m "chore(release): bump version to 2.4.1"
   ```

6. Push `main`.
7. Create and push the annotated tag:

   ```bash
   git tag -a v2.4.1 -m "v2.4.1"
   git push origin v2.4.1
   ```

8. Create the GitHub Release:

   ```bash
   gh release create v2.4.1 \
     --repo samuelgursky/davinci-resolve-mcp \
     --title "v2.4.1" \
     --notes-file /path/to/release-notes.md \
     --latest
   ```

9. Verify the result:

   The `Publish npm package` workflow publishes the npm package from `v*` tags.
   The npm package should use trusted publishing/OIDC and provenance, not a
   long-lived npm token.

   ```bash
   gh release list --repo samuelgursky/davinci-resolve-mcp --limit 5
   git tag --list "v2.4.*" --sort=-v:refname
   ```

## Release Notes Template

```markdown
## vX.Y.Z

Short release summary.

### Added

- ...

### Fixed

- ...

### Documentation

- ...

### Validation

- Unit/static checks run.
- Live Resolve validation details, or "No Resolve behavior changed; live test
  not required."
```
