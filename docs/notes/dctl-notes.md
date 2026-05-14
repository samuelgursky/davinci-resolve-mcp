# DaVinci Resolve DCTL Notes

Blackmagic's DaVinciCTL README documents DaVinci Color Transform Language
(DCTL). DCTLs are GPU-accelerated, C-like pixel programs used by Resolve as
programmable color transforms, ResolveFX DCTL effects, DCTL transitions, and
custom ACES IDT/ODT transforms.

This is adjacent to, but not the same as, the Python scripting API used by the
MCP. The MCP can refresh Resolve's LUT list and set discovered LUT-style files
on Color page nodes, but it does not compile DCTL, encrypt DCTL, or manipulate
ResolveFX DCTL plugin UI controls directly.

## Current MCP Surface

Relevant existing actions:

- `project_settings(action="refresh_luts")` wraps `Project.RefreshLUTList()`.
  Call it after adding or editing `.dctl`, `.dctle`, or `.cube` files in
  Resolve's LUT folders.
- `graph(action="set_lut", params={"node_index": 1, "lut_path": "..."})`
  wraps `Graph.SetLUT(nodeIndex, lutPath)`. DCTLs that Resolve exposes through
  LUT selection follow the same discovery constraints as LUTs.
- `graph(action="get_lut", params={"node_index": 1})` wraps `Graph.GetLUT()`.
- `graph(action="get_tools_in_node", ...)` may report ResolveFX tools present
  in a Color page node, but the scripting API does not expose a general
  "configure DCTL plugin parameter" helper.

There is no documented Resolve scripting method to list installed DCTLs, encrypt
DCTLs, choose a DCTL in the ResolveFX DCTL plugin, or apply a DCTL transition.

## DCTL Types

Blackmagic describes two primary DCTL types:

- Transform DCTL: processes a single clip/frame. It can be applied as a LUT, via
  the ResolveFX DCTL plugin, from the LUT browser, or from clip/node LUT
  selection.
- Transition DCTL: blends two clips over time and is used through the OpenFX
  DCTL Transition plugin under ResolveFX Color.

DCTL source files are plain text `.dctl` files. Resolve can encrypt a DCTL from
the LUT browser, producing an expiring `.dctle` file for distribution.

## Transform Entry Points

Every transform DCTL must provide exactly one supported `transform()` entry
point. Common signatures are:

```c
__DEVICE__ float3 transform(int p_Width, int p_Height, int p_X, int p_Y, float p_R, float p_G, float p_B)
__DEVICE__ float3 transform(int p_Width, int p_Height, int p_X, int p_Y, __TEXTURE__ p_TexR, __TEXTURE__ p_TexG, __TEXTURE__ p_TexB)
```

Resolve 19.1 added transform DCTL with alpha for the ResolveFX DCTL plugin:

```c
__DEVICE__ float4 transform(int p_Width, int p_Height, int p_X, int p_Y, float p_R, float p_G, float p_B, float p_A)
__DEVICE__ float4 transform(int p_Width, int p_Height, int p_X, int p_Y, __TEXTURE__ p_TexR, __TEXTURE__ p_TexG, __TEXTURE__ p_TexB, __TEXTURE__ p_TexA)
```

Alpha mode tags:

```c
DEFINE_DCTL_ALPHA_MODE_STRAIGHT
DEFINE_DCTL_ALPHA_MODE_PREMULTIPLY
```

If no alpha tag is specified for an alpha transform, Resolve defaults to
premultiplied alpha.

## Transition Entry Point

Transition DCTLs use a `transition()` function and read the global
`TRANSITION_PROGRESS` value, which runs from `0.0f` to `1.0f` over the
transition:

```c
__DEVICE__ float4 transition(
    int p_Width,
    int p_Height,
    int p_X,
    int p_Y,
    __TEXTURE__ p_FromTexR,
    __TEXTURE__ p_FromTexG,
    __TEXTURE__ p_FromTexB,
    __TEXTURE__ p_FromTexA,
    __TEXTURE__ p_ToTexR,
    __TEXTURE__ p_ToTexG,
    __TEXTURE__ p_ToTexB,
    __TEXTURE__ p_ToTexA)
```

Texture signatures can sample pixels with `_tex2D(texture, x, y)`.

## Language Notes

DCTL is C-like and uses base C types plus Resolve-specific qualifiers and vector
types:

- `float2`, `float3`, `float4`
- `make_float2`, `make_float3`, `make_float4`
- `__TEXTURE__`
- `__DEVICE__`
- `__CONSTANT__`
- `__CONSTANTREF__`

Float literals need an `f` suffix, for example `1.2f`.

Useful global keys:

- `__RESOLVE_VER_MAJOR__` and `__RESOLVE_VER_MINOR__` for version guards.
- `DEVICE_IS_CUDA`, `DEVICE_IS_OPENCL`, and `DEVICE_IS_METAL` for backend guards.
- `TRANSITION_PROGRESS` in transition DCTLs.
- `TIMELINE_FRAME_INDEX` when running through the ResolveFX DCTL plugin.
  When a DCTL is used as a LUT, this defaults to `1`.

Headers can be included relative to the `.dctl` file:

```c
#include "ColorConversion.h"
```

## LUTs Inside DCTL

DCTL can reference external `.cube` LUTs:

```c
DEFINE_LUT(FilmToVideo, ../LUT/Blackmagic Design/Blackmagic_46K_Film_to_Video.cube)
```

It can also define inline cube LUTs with `DEFINE_CUBE_LUT(...) { ... }`
starting in Resolve 17. Use `APPLY_LUT(r, g, b, lutName)` to apply either kind.

Rules:

- Define LUTs before use.
- Multiple LUTs may be defined and applied in one DCTL.
- External LUTs must be `.cube` files.
- 1D and shaper LUTs use linear interpolation.
- 3D LUTs use the project's 3D LUT interpolation setting: trilinear or
  tetrahedral.

See `docs/notes/lut-notes.md` for the cube file format itself.

## Custom UI

Transform DCTLs used through the ResolveFX DCTL plugin can define UI controls
with `DEFINE_UI_PARAMS`. Resolve supports:

- `DCTLUI_SLIDER_FLOAT`
- `DCTLUI_SLIDER_INT`
- `DCTLUI_VALUE_BOX`
- `DCTLUI_CHECK_BOX`
- `DCTLUI_COMBO_BOX`
- `DCTLUI_COLOR_PICKER`

Each type can have up to 64 controls per DCTL. Resolve 19.1 added the color
picker, tooltips, incremental slider steps, and improved build-error handling.

Tooltips use:

```c
DEFINE_UI_TOOLTIP(Target Color, "Choose target color")
```

Build errors from the ResolveFX DCTL plugin appear in Resolve's DCTL Build Error
dialog. After editing a DCTL file, the plugin combo-box Reset rebuilds the
selected DCTL while preserving custom UI values when possible.

## DCTL And ACES

Custom ACES DCTLs live outside the normal LUT folder and are loaded at Resolve
startup from:

| Platform | ACES transform root |
|---|---|
| macOS | `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/ACES Transforms` |
| Windows | `%AppData%\Blackmagic Design\DaVinci Resolve\Support\ACES Transforms` |
| Linux | `~/.local/share/DaVinciResolve/ACES Transforms` |
| iPadOS | `On My iPad/DaVinciResolve/ACES Transforms` |

Use `IDT/` for Input Device Transforms and `ODT/` for Output Device Transforms.
Resolve discovers these at startup, not through `RefreshLUTList()`.

ACES DCTL modes:

- Non-parametric ACES transforms with
  `DEFINE_ACES_PARAM(IS_PARAMETRIC_ACES_TRANSFORM: 0)`.
- Parametric ACES Transform V1 with `DEFINE_ACES_PARAM(...)`, supported for
  ACES 1.1 through 1.3.
- Parametric ACES Transform V2 with `DEFINE_ACES_V2_PARAM(...)`, supported by
  Resolve 20.1 for ACES 2.0.

V1 supports custom EOTF functions and skipping the standard ACES RRT. V2 uses
the newer `DEFINE_ACES_V2_PARAM` template and adds Gamma 2.2, but does not
support custom EOTF or skipping RRT.

## Practical Failure Checks

If a DCTL does not appear or does not apply:

- Confirm the file is in Resolve's LUT directory for normal DCTL/plugin use, or
  in the user ACES `IDT/` or `ODT/` folder for ACES transforms.
- Call `project_settings(action="refresh_luts")` after adding/editing normal
  DCTL files; restart Resolve for ACES DCTLs.
- Confirm the file extension is `.dctl` or `.dctle`.
- Confirm the exact entry point signature and parameter names match the required
  form.
- Confirm float constants use the `f` suffix where needed.
- Confirm external headers and `DEFINE_LUT` paths are relative to the DCTL file
  or absolute.
- For transform-with-alpha behavior, confirm Resolve is 19.1+ and the alpha
  mode tag matches the intended straight/premultiplied workflow.
- For animated/noise effects, remember `TIMELINE_FRAME_INDEX` is meaningful in
  the DCTL plugin but defaults to `1` when used as a LUT.

## Useful Future Additions

Good repo additions, if DCTL workflows become common:

1. A read-only DCTL inventory helper that scans Resolve LUT roots and ACES
   transform roots.
2. A lightweight DCTL linter for entry point signatures, UI param count, include
   paths, `DEFINE_LUT` paths, and obvious missing `f` suffixes.
3. Better `graph.set_lut` failure text that mentions `.dctl` discovery,
   `RefreshLUTList()`, and DCTL-vs-ResolveFX-plugin limitations.
4. A small fixture set using Blackmagic's simple examples (`Gain.dctl`,
   `GainDCTLPlugin.dctl`, `LUTApply.dctl`) for non-rendering parser tests.

## Source Media Integrity

DCTLs process pixels in Resolve's grade/effects pipeline. Do not bake DCTL
results into camera originals, create transformed copies, or export/reimport
processed media unless the user explicitly asks for that workflow.
