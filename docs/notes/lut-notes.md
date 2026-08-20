# DaVinci Resolve LUT Notes

Blackmagic's LUT developer README documents Resolve's supported `.cube` LUT
format. This is directly relevant to the MCP's color tools because Resolve will
only apply LUTs that it can parse and discover.

## Current MCP Surface

The scripting API already exposes the important LUT operations:

- `project_settings(action="refresh_luts")` wraps `Project.RefreshLUTList()`.
  Call this after adding LUT files to Resolve's LUT folders.
- `graph(action="set_lut", params={"node_index": 1, "lut_path": "..."})`
  wraps `Graph.SetLUT(nodeIndex, lutPath)`.
- `graph(action="get_lut", params={"node_index": 1})` wraps
  `Graph.GetLUT(nodeIndex)`.
- `timeline_item_color(action="export_lut", ...)` wraps
  `TimelineItem.ExportLUT(exportType, path)`.
- `graph(action="apply_arri_cdl_lut")` wraps `Graph.ApplyArriCdlLut()`.
- `project_manager(action="export_project", params={"with_stills_and_luts": true})`
  can include LUTs in a `.drp` export.

`SetLUT()` uses 1-based node indexes and succeeds only for LUT paths Resolve has
already discovered.

### `SetLUT` resolves against the master LUT dir only

Resolve resolves the `lut_path` given to `SetLUT()` **only against the master
(system) LUT directory and its configured custom LUT paths — not the per-user
LUT directory** that the `dctl` tool and Project-level LUT installs write to.
This trips up the obvious workflow (install a LUT/DCTL, then apply it):

- A bare basename that lives only in the user LUT dir returns `False`.
- An **absolute path into the user LUT dir also returns `False`** — absolute
  paths are not a workaround.
- `project_settings(action="refresh_luts")` (`RefreshLUTList()`) does **not**
  change this; the file is discovered but still not resolvable by `SetLUT`.
- A **subfolder-relative** path under the master root (e.g. `MCP/Foo.cube`)
  *does* resolve.

Verified live on Studio 19.1.3.7; the same behavior was reported on 21.0.2
(PR #90), so it is not version-specific. See the `Graph.SetLUT` entry in
`src/utils/api_truth.py`.

`graph.set_lut` (and the granular `graph_set_lut`) handle this automatically:
on a `False` return they stage the LUT into an `MCP/` subfolder of the master
LUT dir, refresh, and retry, returning `resolved_lut` on success. If you call
`Graph.SetLUT` directly, relocate the file into the master dir yourself first
(`src.utils.lut_paths.ensure_lut_in_master`).

## Cube LUT Format

A `.cube` file is a text file with a header followed by lookup-table data.
Resolve supports:

- 1D LUTs
- 3D LUTs
- An optional 1D shaper LUT before a 1D or 3D LUT

### 1D LUT

Header keywords:

```text
LUT_1D_SIZE N
LUT_1D_INPUT_RANGE MIN_VAL MAX_VAL
```

`N` is the number of entries, up to 65536. Each data row contains three
space-separated floating point values for output R, G, and B. Rows map evenly
from `MIN_VAL` to `MAX_VAL`; values between rows are linearly interpolated.

### 3D LUT

Header keywords:

```text
LUT_3D_SIZE N
LUT_3D_INPUT_RANGE MIN_VAL MAX_VAL
```

`N` is the number of samples per channel, so the file must contain `N * N * N`
data rows. Each row contains output R, G, and B. Resolve expects the R axis to
change fastest, then G, then B. Resolve supports trilinear and tetrahedral
interpolation for 3D LUTs.

### Shaper LUT

A shaper LUT is a 1D LUT placed before the main LUT. It remaps the input range
so the main 1D/3D LUT can spend more samples on important parts of the signal,
for example a log curve's lower code values.

## Optional Properties

Comments begin with `#` and are ignored by the parser.

The optional title form is:

```text
TITLE "Description"
```

Resolve applies LUTs in data range, with values normalized from `0.0` to `1.0`.
For LUTs designed around video range values, the cube file can declare:

```text
LUT_IN_VIDEO_RANGE
LUT_OUT_VIDEO_RANGE
```

Those flags tell Resolve to compensate when applying the LUT inside its
data-range processing pipeline.

## Built-In LUT Locations

Blackmagic's examples live in the installed LUT folder:

| Platform | LUT folder |
|---|---|
| macOS | `/Library/Application Support/Blackmagic Design/DaVinci Resolve/LUT` |
| Linux | `/opt/resolve/LUT` |
| Windows | `%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\LUT` |

Example built-in LUT categories include `VFX IO`, `Blackmagic Design`, and
`ACES`.

The `dctl` tool and Project-level LUT installs instead write to the **per-user**
LUT dir (macOS `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/LUT`,
Windows `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\LUT`). Files there
are discovered by the LUT browser but are **not** resolvable by `SetLUT` until
relocated into the master dir above — see "master LUT dir only".

## Practical Failure Checks

If `graph.set_lut` fails or `graph.get_lut` returns empty:

- Confirm the current page/context has a valid Color graph and the node index is
  1-based.
- Confirm the LUT is in the **master** LUT folder (or a configured custom LUT
  path) — not just the per-user LUT dir. A file only in the user dir fails even
  by absolute path (see "master LUT dir only" above). `graph.set_lut` relocates
  it for you; a direct `Graph.SetLUT` call does not.
- Call `project_settings(action="refresh_luts")` after adding or changing LUT
  files (note: refresh alone does not make a user-dir LUT resolvable by
  `SetLUT`).
- Check the `.cube` header and row count. 3D LUTs must contain exactly
  `N * N * N` rows.
- Confirm the file extension is `.cube` and the content is plain text.
- Check whether video-range flags are needed; wrong range assumptions can look
  like a broken grade even when the file parses.

## Useful Future Additions

Good repo additions, if LUT troubleshooting becomes common:

1. A read-only `.cube` validator that checks header shape, row count, numeric
   values, shaper/main LUT ordering, and video-range flags.
2. A read-only LUT folder inventory helper that scans known Resolve LUT roots.
   This would be a filesystem diagnostic, not a Resolve API list.
3. Better `graph.set_lut` failure text that reminds users to refresh the LUT
   list and verify the 1-based node index.
4. A tiny synthetic LUT fixture for tests of any future validator.

## Source Media Integrity

Applying a LUT in Resolve changes the grade/render pipeline, not the source
media file on disk. Do not bake LUTs into camera originals, create transformed
copies, or export/reimport derivative media unless the user explicitly asks for
that workflow.
