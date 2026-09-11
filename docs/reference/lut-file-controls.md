# LUT file controls

`graph set_lut` could already put a LUT on a node, and `export_lut` could pull
one out of a grade. Nothing answered the question `set_lut` raises: **which
LUTs exist?** There was no listing, no install and no removal — even though the
same needs for DCTL shaders are served by the `dctl` tool, in the same directory
tree, and `project_settings refresh_luts` exists precisely because files get
added by something else.

Blackmagic's own MCP exposes `list_luts`, `generate_lut` and `delete_lut`. This
closes that gap.

## Two rules

**Reads roam, writes do not.** `list` and `read` walk the whole master LUT root,
so stock, vendor and hand-installed LUTs are all discoverable. `install`,
`remove` and `attenuate` write only inside the namespaced `MCP/` subfolder —
the same confinement Blackmagic's MCP applies to its own write tools. Stock and
vendor LUTs are never modified or removed here.

**Master root, not the user LUT dir.** `Graph.SetLUT()` resolves relative names,
and even absolute paths, only against the master root — never the per-user dir
the `dctl` tool installs into. That is measured behaviour already recorded in
`utils/lut_paths.py`, so installs land where `set_lut` can reach them, and every
listing reports `set_lut_path` in the exact form `set_lut` accepts.

## Live results

Measured against a real LUT tree of 249 LUTs. Resolve was **not** running, which
is itself worth noting: these are filesystem operations, so discovery works
whether or not Resolve is up, where Blackmagic's `list_luts` refuses without it.

| Check | Result |
| --- | --- |
| LUTs discovered | 249 |
| Compound and granular listings identical | yes |
| Install | `MCP/mcp_live_probe.cube`, 179 bytes, appeared in listing, marked writable, count +1 |
| Read | parsed, size 2, 8 entries, whole table not returned |
| Re-install without `overwrite` | refused |
| Path traversal (`../escaped.cube`) | refused, no file created outside the root |
| Removing a stock LUT | refused, file intact |
| Cleanup | probe removed, count back to 249 |

## Application proof

The tool's purpose rests on one claim: the `set_lut_path` that `install` returns
is resolved by `Graph.SetLUT` on a live node. Measured on Studio 21.1.0.14 in a
disposable project, with a solid-red clip and a constant-green 3D LUT so that
application is unmistakable in decoded pixels. Each row is a real render.

| Path | set_lut | Readback | Rendered centre pixel |
| --- | --- | --- | --- |
| Baseline, no LUT | — | — | `[255, 0, 0]` |
| Compound: `lut install` → `refresh_luts` → `graph set_lut` → `get_lut` | True, no fallback | `MCP/mcp_apply_probe_compound.cube` | `[0, 255, 0]` |
| Granular: `install_lut_file` → `refresh_lut_list` → `graph_set_lut` → `graph_get_lut` | True, no fallback | `MCP/mcp_apply_probe_granular.cube` | `[0, 255, 0]` |

"No fallback" matters: the compound `set_lut` has a relocation retry for LUTs
outside the master root, and a success through that retry would have hidden
whether the installed path resolved on its own. It did not fire in either run.

Three native facts came out of it. `SetLUT` on a just-installed path works
immediately after `RefreshLUTList`, with no delay. `GetLUT` reads back the exact
master-relative path. `SetLUT(1, "")` clears the node.

Two pre-existing behaviours worth knowing, neither changed here: the compound
`graph` tool targets the **timeline** node graph by default, which had no nodes,
so `set_lut` on a clip needs `source="item"`; and compound `get_lut` answers
`{lut}` where granular `graph_get_lut` answers `{lut_path}`.

## Not ported from the official MCP

Its `generate_lut` takes a Python function body from the caller and executes it
on every lattice point. This server does not execute caller-supplied code, so
authoring here is limited to declarative operations already implemented in
`utils/cube_lut.py`: writing a provided `.cube`, and blending an existing one
toward identity. `capabilities` says so explicitly rather than leaving a caller
to guess why `generate` is missing.

## Scope

Application was proved for a 3D `.cube` on a clip's first node graph. Other LUT
formats, `layer_index` > 1 graphs and colour-group graphs were not measured.
`attenuate` is unit-tested for bounds and missing sources but was not run
against a real vendor LUT. Windows and Linux master roots, and a read-only
master root, are untested.
