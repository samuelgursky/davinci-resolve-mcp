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
- `package-lock.json` — regenerate with `npm install --package-lock-only`, do
  not hand-edit the version. It carries the version in two places and, more
  importantly, the resolved dependency tree. When it disagrees with
  `package.json`, **`npm ci` refuses to install at all** (`EUSAGE — Missing: X
  from lock file`), which breaks CI, fresh clones, and container builds while
  `npm install` and `npm publish` stay green and hide it. The
  `tests.test_import` guard `test_package_lock_in_sync` fails the suite on
  either drift.
- README version badge
- README current stats or latest-release summary when they changed
- `README.zh-CN.md` — the Simplified Chinese translation. Update its version
  badge and the `本翻译对应 vX.Y.Z 版 README` line, and carry over any
  substantive English change. **If you cannot keep it current, delete the file
  and the language switcher at the top of `README.md`** — a translation that
  silently lags is worse than no translation, because its version line then
  makes a claim that is false. No drift guard covers this; it is a human check.
- `CHANGELOG.md` latest release entry
- `docs/reference/api-limitations.md` when any `submit`-tagged entry in
  `src/utils/api_truth.py` was added or changed (a newly documented Resolve API
  gap/bug, a closed won't-fix issue, etc.). Regenerate it — do not hand-edit:
  `venv/bin/python scripts/gen_api_limitations.py`. The
  `tests.test_api_limitations_doc` drift guard fails the suite if it is stale.
- `docs/SKILL.md` when tool discovery, examples, or behavior changed
- `docs/guides/control-panel.md` — check EVERY release, not only when the
  panel "changed": panel surfaces grow transitively (new tools, new docs pages,
  new diagnostics cards), so review the guide for accuracy and update it plus
  regenerated screenshots: start the panel against a project with analysis
  data, then run `venv/bin/python scripts/regen_panel_screenshots.py`.
  The `tests.test_panel_docs_drift` guard fails the suite (and the publish
  workflow) when the guide drifts from the panel's navigation or screenshots —
  but the guard checks presence, not prose accuracy; the human pass is the
  accuracy check.
- Git tag, e.g. `v2.4.1`
- GitHub Release notes

Do not consider a release complete until the GitHub Release exists and is marked
latest when appropriate.

## Required Validation

Always run static checks before release:

```bash
venv/bin/python tests/test_import.py
npm install --package-lock-only --no-audit --no-fund   # re-stage package-lock.json if it moved
venv/bin/python scripts/audit_api_parity.py
venv/bin/python scripts/gen_api_limitations.py --check
venv/bin/python scripts/audit_readwrite_symmetry.py --check
node scripts/agent-rules/generate.mjs --check
venv/bin/python -m unittest tests.test_static_undefined_names tests.test_duplicate_definitions tests.test_action_list_drift tests.test_panel_docs_drift tests.test_doc_tool_counts tests.test_agent_rules_drift
node bin/davinci-resolve-mcp.mjs --help
node bin/davinci-resolve-mcp.mjs --version
npm pack --dry-run
git diff --check
```

`test_import` carries `test_package_lock_in_sync`, which is the actual gate on the
lockfile: it asserts both version fields and the root dependency blocks match
`package.json`. Run the `npm install --package-lock-only` line above first so the
regeneration is in the working tree when the test reads it — that ordering is why
the check is a regeneration followed by a test, not a `git diff --exit-code`,
which would fire on the release bump's own legitimate change.

`test_duplicate_definitions` asserts no module-level name is defined twice under
`src/`. A second `def foo` silently replaces the first, and in a module the size
of `src/server.py` the two can be thousands of lines apart with different
signatures. pyflakes does **not** catch this — it only reports redefinition of an
*unused* name, so the dangerous case (first definition used, then shadowed)
passes clean.

The drift guards (undefined names in `src/`, tool action lists vs dispatch,
control-panel guide vs panel navigation/screenshots, api-limitations vs the
api_truth ledger, and **tool counts across the docs vs reality** —
`test_doc_tool_counts`) also run in the `Publish npm package` workflow on every
`v*` tag, so a stale doc or drifted action list fails the publish — fix the drift
rather than bypassing the gate.

`test_doc_tool_counts` statically counts the compound (`src/server.py`), granular
(`src/granular/`), and Node advanced (`resolve-advanced/server/index.mjs`) tools and
asserts the numbers quoted in README, `resolve-advanced/README.md`, `docs/contributing.md`,
`docs/SKILL.md`, `docs/reference/api-coverage.md`, and `.github/copilot-instructions.md`
still match. When you add/remove a tool, update those docs to the counts the test prints.

The cross-platform agent rule files (`.cursor/rules/*`, `.github/instructions/*`,
`.windsurf/rules/*`, `.cursorrules`, `.windsurfrules`, the `AGENTS.md` domain-routing
block, and `.github/copilot-instructions.md`) are **generated** by
`scripts/agent-rules/generate.mjs`, which parses those same counts from their
canonical docs. After a count or tool-routing change, run
`node scripts/agent-rules/generate.mjs` and commit the result;
`test_agent_rules_drift` fails the suite (and publish) if the committed files are
stale. See `scripts/agent-rules/README.md`.

Run focused unit tests for the changed surface. For recent timeline/marker
helpers, this usually includes:

```bash
venv/bin/python -m unittest tests.test_extract_source_frame_ranges tests.test_marker_params tests.test_v232_helpers tests.test_v233_helpers tests.test_append_clip_infos_result_handling
```

Behavior changes that touch DaVinci Resolve scripting must also have a live
Resolve validation before release. Use disposable projects and synthetic media
only. Never modify, transcode, proxy, or create derivatives of source media
unless the user explicitly requests it.

**Changes to the offline `.drp` authoring tier must run the round-trip harness,
and a structural readback is NOT sufficient evidence on its own:**

```bash
RESOLVE_VERIFY=1 venv/bin/python tests/live_drp_roundtrip_verification.py
```

It authors a `.drp` per primitive, imports it into Resolve, asserts intent
against structural readback, **and exports the composited frame to assert the
item is visible on screen.** That last assertion exists because
`place_fusion_title` passes every structural check — right track, frame,
duration, type, and correctly-encoded text — while rendering nothing. Anything
that only diffs `GetStart()`/`GetDuration()` will call that green. Known-broken
cases are declared in the harness rather than skipped, so a fix reports
`UNEXPECTED PASS` and fails until the docs describing it are updated.

The same rule generalises: **"the file round-trips" and "Resolve honours it" are
different claims.** Only a live import establishes the second one. Do not write
"verified live" in a doc unless a runnable command produced that result.

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

For Fusion comp changes (masks, Text+/title text), run the issue #73 harness,
which creates a disposable Fusion-title project, exercises `add_fusion_mask` and
`set_text_plus` / `get_text_plus`, and deletes the project:

```bash
env RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting" \
  RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so" \
  PYTHONPATH="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules" \
  venv/bin/python tests/live_fusion_mask_title_validation.py
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
