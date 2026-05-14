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
already discovered. The `lut_path` may be absolute or relative to Resolve's
master/custom LUT paths.

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

## Practical Failure Checks

If `graph.set_lut` fails or `graph.get_lut` returns empty:

- Confirm the current page/context has a valid Color graph and the node index is
  1-based.
- Confirm the LUT file is in a Resolve LUT folder or is referenced by a valid
  absolute path.
- Call `project_settings(action="refresh_luts")` after adding or changing LUT
  files.
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
