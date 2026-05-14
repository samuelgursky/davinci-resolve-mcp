# Color / Grade Kernel

The Color / Grade kernel expands `timeline_item_color` into a safer grade
inspection, versioning, copy, LUT, DRX, Gallery, and color-group boundary layer.

Live validation was run against DaVinci Resolve Studio 20.3.2.9 with a
disposable `_mcp_color_grade_probe_*` project and generated synthetic color-bar
media. Final release probe counts:

| Status | Count |
| --- | ---: |
| `supported` | 25 |
| `version_or_page_dependent` | 2 |
| `not_applicable` | 1 |
| `partially_supported` | 0 |
| `unsupported` | 0 |
| `error` | 0 |

The version/page-dependent results were Gallery still export and
`ExportCurrentFrameAsStill(.drx)` in this Resolve/UI state. `safe_apply_drx`
was marked `not_applicable` because the probe could not produce a DRX file
through the public API in that run.

## Added Actions

All actions are exposed through `timeline_item_color`.

| Action | Purpose |
| --- | --- |
| `grade_capabilities` | Return callable item methods, graph sources, LUT export types, version modes, guards, and known boundaries. |
| `probe_grade_item` | Snapshot grade versions, item graph, color group, cache states, ids, names, and callable methods. |
| `probe_node_graph` | Inspect item, timeline, pre-clip group, or post-clip group graph availability and node metadata. |
| `safe_set_cdl` | Validate and normalize CDL payloads before calling `SetCDL`; supports dry run. |
| `safe_copy_grade` | Resolve target timeline item IDs before calling `CopyGrades`; supports dry run. |
| `safe_apply_drx` | Validate DRX file existence and temp-path guard before calling `ApplyGradeFromDRX`. |
| `safe_export_lut` | Resolve LUT export type aliases and require temp output paths by default. |
| `grade_version_snapshot` | Read current, local, and remote grade version names. |
| `grade_version_restore` | Safely load a named local/remote version after verifying it exists. |
| `color_group_capabilities` | Report color groups and pre/post graph availability. |
| `gallery_capabilities` | Report Gallery availability, albums, and callable Gallery methods. |
| `grade_boundary_report` | Return capabilities, current item snapshot, color groups, Gallery, and timeline graph summary. |

## Scope Matrix

| Scope | Probe Support | Mutation Support | Notes |
| --- | --- | --- | --- |
| Timeline item graph | Supported | CDL, LUT export, grade copy, DRX apply when file exists | Primary grade entry point. |
| Timeline graph | Supported | Raw `graph` tool can mutate | Live probe found zero timeline nodes by default. |
| Color group pre-clip graph | Supported | Raw `graph` tool can mutate | Requires existing `group_name`. |
| Color group post-clip graph | Supported | Raw `graph` tool can mutate | Requires existing `group_name`. |
| Gallery albums/stills | Partially environment dependent | Album create and list supported; still export may require UI panel state | Public API can return false if Gallery export is not ready. |

## Supported Findings

- `SetCDL` worked after payload validation and Resolve-specific string
  normalization.
- Item graph and timeline graph objects were available; item graph exposed one
  node in the synthetic clip.
- Node graph metadata probes worked for node count, LUT, cache mode, label, and
  tools-in-node where Resolve returned data.
- Local grade version add, rename, load, restore, and delete worked when the
  version to delete was not currently loaded.
- `CopyGrades` worked from the first synthetic timeline item to the second.
- `ExportLUT` produced a 33-point `.cube` file under the generated temp probe
  directory.
- Color group create, assign, capability probe, pre/post graph probe, remove,
  and delete worked.
- Gallery capability and album list/create calls worked.

## Boundaries

- Node graph internals are intentionally limited by Resolve's public API. The
  kernel can inspect high-level node count and a few node attributes, but not
  every grading control inside a node.
- `ApplyGradeFromDRX` replaces the target graph. There is no append mode in the
  public API.
- `safe_apply_drx` requires an existing DRX path. The live release probe could
  not produce one because both Gallery still export and
  `ExportCurrentFrameAsStill(.drx)` were unavailable in the current UI/build
  state.
- Gallery still export may require the Color page Gallery panel to be open and
  ready. The public API returned false in the release probe even after the page
  was active.
- LUT export writes files, so `safe_export_lut` requires temp paths by default.
- Stabilize, Smart Reframe, Magic Mask, and Magic Mask regeneration are exposed
  as callable methods but are not forced in the boundary report because they can
  be asynchronous, page dependent, and expensive.

## Live Probe

Run the live boundary probe with:

```bash
python3.11 tests/live_color_grade_validation.py --output-dir /tmp/color-grade-probe
```

The harness creates a disposable project, generates synthetic color-bar media,
builds a two-item timeline, probes grade/node/version/copy/LUT/group/Gallery
surfaces, writes JSON and Markdown reports, deletes the project, and removes
generated media and exported probe files.

Use `--keep-open` only when you intentionally want to inspect the disposable
project by hand.
