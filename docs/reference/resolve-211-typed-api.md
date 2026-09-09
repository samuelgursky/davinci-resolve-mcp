# Resolve 21.1 typed API snapshot

The vendor-shipped [DaVinciResolveScript.pyi](DaVinciResolveScript.pyi) preserves
Blackmagic's typed Resolve API separately from the legacy
[README snapshot](resolve_scripting_api.txt). The legacy file and its line
anchors are unchanged. The accompanying
[scripting changelog](resolve_scripting_changelog_21.1.md) lists the 21.1 additions.

## Provenance

Collected September 9, 2026 from the installed official MCP's
`get_scripting_api(as_file=True)` on macOS, DaVinci Resolve Studio **21.1.0.14**.
The changelog was copied from the installed `Developer/Scripting/CHANGELOG.md`
and is dated September 1, 2026. The stub is unmodified vendor reference material;
it is not authored by this project. Its SHA-256 is
`00078fa1256851b9807621a4eea5e670f4266b0e7003763cba4a62655543f0ec`.

This supplies the typed snapshot requested in
[the review of #197](https://github.com/samuelgursky/davinci-resolve-mcp/pull/197#issuecomment-5584959121).
Future refreshes should replace the whole vendor file, retain provenance and
review the signature/option changes, rather than patch selected methods into it.

## Diagnostic inventory

Run from the repository root:

```sh
python scripts/audit_typed_api.py
python scripts/audit_typed_api.py --json > /tmp/resolve-api-inventory.json
```

The JSON includes every public class method, its signatures and source line,
all TypedDict option fields and their descriptions, and source references split
between compound, granular and helper files. An alternate installed stub can be
passed with `--stub`; `--source-root` selects an alternate source tree.

The 21.1 snapshot has **410 unique class-qualified public methods** and **46
TypedDicts containing 513 fields**. Compared with the 361 methods parsed from
the legacy README, 57 are newly represented and eight legacy names are absent
from the stub. That does **not** mean 57 newly introduced runtime functions or
eight removed functions: newly documented existing methods and deprecated
aliases are part of the difference. For example, the 21.1 README deprecates
`GetSetting`/`SetSetting` in favor of `GetSettings`/`SetSettings` and
`GetProperty`/`SetProperty` in favor of their plural forms. The special
four-argument Super Scale `SetSetting` form is explicitly not deprecated.

At main `91d03a52c139002061e325824004162366f0902c`, 50 method names had no
executable attribute or literal-getattr reference under `src/`. These are
**candidate gaps**, not a claim that 50 user-facing features are missing.

## What this audit proves, and what it does not

- Comments and docstrings cannot count as executable coverage. In particular,
  `CreateMulticamClip` mentioned in the API-truth ledger is not a wrapper.
- Class identity is preserved in the inventory, but Python receiver types are
  **not inferred**. A `pm.GetCurrentProject()` reference does not prove that
  the new `Resolve.GetCurrentProject()` utility is used. Matching names carry
  `unresolved_receiver`, not `covered`.
- A literal `getattr` can be a capability probe rather than an invocation.
  Attribute references and direct calls have separate kinds in the report.
- A helper reference does not prove that both public server layers expose it,
  or that all arguments/options are forwarded. Follow each candidate through
  action dispatch, parameter validation, version guards and response shaping.
- Computed dispatch and equivalent older APIs require manual review.
- The script only parses files. It does not import source modules, connect to
  Resolve, mutate projects, or establish behavior.

Exit zero means the inventory completed, **not** that API parity passed. Empty
or malformed inputs fail rather than reporting a false clean inventory. The
existing `audit_api_parity.py` guard remains unchanged; promoting this diagnostic
to a coverage gate requires an explicitly reviewed method-to-action manifest.

## Validation

`python -m unittest tests.test_typed_api_audit` covers comment-only false
coverage, class-name collisions, source layers, call versus getattr references,
option-field descriptions, overload preservation and invalid input. No Resolve
behavior is changed, so no live mutation test is required for this contribution.
