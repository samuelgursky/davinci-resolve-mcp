# Extension Authoring Kernel

The Extension Authoring kernel turns the existing `fuse_plugin`, `dctl`, and
`script_plugin` tools into a lifecycle-aware boundary layer for generated
Resolve extensions.

Kernel actions are exposed through `script_plugin` as the cross-extension
orchestrator. The raw authoring tools remain available for direct file
operations.

Live validation was run against DaVinci Resolve Studio 20.3.2.9 with only
MCP-marked `_mcp_` Fuse, DCTL, ACES DCTL, and Resolve-page script files. Final
release probe counts:

| Status | Count |
| --- | ---: |
| `supported` | 14 |
| `partially_supported` | 1 |
| `unsupported` | 1 |
| `not_applicable` | 0 |
| `version_or_page_dependent` | 0 |
| `error` | 0 |

The unsupported result is intentional: safe install rejects provided source that
does not include the expected MCP marker.

## Added Actions

All kernel actions are exposed through `script_plugin`.

| Action | Purpose |
| --- | --- |
| `extension_capabilities` | Report Fuse, DCTL, script paths, template kinds, MCP markers, lifecycle rules, and safety guards. |
| `probe_fuse_lifecycle` | Generate, validate, optionally install/read/list/remove a Fuse template. |
| `probe_dctl_lifecycle` | Generate, validate, optionally install/read/list/remove a LUT or ACES DCTL template. |
| `probe_script_lifecycle` | Generate, validate, optionally install/read/list/execute/remove a Resolve-page script. |
| `safe_install_extension` | Install Fuse, DCTL, or script source/templates with `_mcp_` name and marker guards. |
| `safe_remove_extension` | Remove Fuse, DCTL, or script files only when the file is MCP-marked by default. |
| `refresh_or_restart_required` | Classify whether an extension needs LUT refresh, menu refresh, UI reload, or Resolve restart. |
| `extension_boundary_report` | Return lifecycle classifications, template validation matrix, and dry-run probes. |

## Lifecycle Map

| Surface | Install Target | Live Pickup | Restart |
| --- | --- | --- | --- |
| Fuse | Fusion Fuses directory | Existing Fuses can be UI-reloaded from Inspector; MCP cannot trigger it. | Required for new Fuse registration. |
| Regular DCTL | LUT directory | `project_settings.refresh_luts` picks it up. | Not required for LUT-category DCTLs. |
| ACES IDT/ODT DCTL | ACES Transforms IDT/ODT | Not picked up by LUT refresh. | Required. |
| Resolve-page script | Fusion/Scripts category directory | Workspace Scripts menu refreshes when opened. | Not required. |
| Inline Python script | Temp file subprocess | Captured synchronously. | Not required. |
| Inline Lua script | Temp Lua file via `fusion.RunScript` | Captured through Fusion app data bridge. | Not required. |

## Supported Findings

- Fuse template generation, validation, install, read, MCP-managed list, and
  safe marker-enforced remove worked.
- Regular LUT DCTL template generation, validation, install into `LUT/MCP`,
  read, list, `project_settings.refresh_luts`, and safe remove worked.
- ACES IDT DCTL template generation, install into `ACES Transforms/IDT/MCP`,
  read, list, and safe remove worked. It remains restart-required before Resolve
  can use the transform.
- Python Resolve-page script template generation, install, read, list, execute,
  stdout/stderr capture, and safe remove worked.
- `script_plugin.run_inline` worked for Python with stdout capture.
- `script_plugin.run_inline` worked for Lua with stdout and return-value capture.
- The template matrix generated and validated every Fuse, DCTL, and script
  template kind.
- Safe install rejected unmarked provided source by default.

## Boundaries

- Installed Lua script execution through `fusion.RunScript(path)` returned
  `success=False` in the release probe, even though install/read/list/remove
  worked and inline Lua execution worked. Use `run_inline(language="lua")` when
  captured output/return values matter.
- New Fuses still require a Resolve restart to appear as registered Fusion
  tools. The MCP can install/remove files but cannot force Fusion to register a
  new Fuse in-process.
- ACES IDT/ODT DCTLs are scanned at Resolve startup. `RefreshLUTList` is only
  appropriate for LUT-category DCTLs.
- Template validation is structural/parser-level. It does not prove a Fuse
  renders correctly after restart or that every DCTL compiles on every GPU
  backend.
- Safe remove refuses to delete unmarked extension files unless
  `require_marker=False` is explicitly passed.

## Live Probe

Run the live boundary probe with:

```bash
python3.11 tests/live_extension_authoring_validation.py --output-dir /tmp/extension-authoring-probe
```

The harness creates a disposable `_mcp_` project, installs and removes a
generated Fuse, regular DCTL, ACES DCTL, Python script, and Lua script, probes
inline Python/Lua execution, writes JSON and Markdown reports, deletes the
project, and removes its temp work directory.

Use `--keep-open` only when you intentionally want to inspect the disposable
project by hand.
