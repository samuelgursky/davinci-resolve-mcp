# Fuse and DCTL Authoring Tools (Experimental)

The `fuse_plugin` and `dctl` compound tools (introduced in v2.5.0) generate and
install Fusion Fuse plugins and DCTL color-transform files. They are the first
*authoring* tools in this MCP — every other tool wraps Resolve's scripting API,
while these two write source files into Resolve's plugin/LUT directories.

**Status: lifecycle-tested, runtime rendering still experimental.** The v2.16.0
Extension Authoring kernel live-tested template generation, validation,
install/read/list/remove, LUT refresh for regular DCTLs, and restart-required
classification for Fuse and ACES DCTL surfaces. It does not prove every Fuse
renders correctly after a restart or that every DCTL compiles on every GPU
backend. Community feedback on runtime behavior is still welcome — please open
an issue with the template kind, your Resolve version and platform, and any
console output from Resolve's Workspace → Console.

## What's covered

### `fuse_plugin` — Fusion Fuse plugins

Fuses are Lua plugins (or GLSL view-LUT shaders) that Fusion loads at startup.
A new Fuse requires a Resolve restart to register; existing Fuses can be
edited and reloaded from the Inspector's Edit/Reload buttons without a
restart. The MCP cannot trigger reload — that's a UI-only action.

Actions: `path`, `list`, `install`, `remove`, `read`, `validate`, `template`,
`list_templates`.

**18 template kinds**, grouped by purpose:

| Group           | Kind                  | Type           | Lang        | Risk  |
|-----------------|-----------------------|----------------|-------------|-------|
| Color           | `color_matrix`        | `CT_Tool`      | Lua         | Low   |
|                 | `per_pixel`           | `CT_Tool`      | Lua         | Low   |
|                 | `channel_op`          | `CT_Tool`      | Lua         | Low   |
| Geometric       | `transform`           | `CT_Tool`      | Lua         | Low   |
|                 | `spatial_warp`        | `CT_Tool`      | Lua         | Med   |
| Text & shapes   | `text_overlay`        | `CT_Tool`      | Lua         | Med   |
|                 | `shape_generator`     | `CT_Tool`      | Lua         | Med   |
| Source/temporal | `source_generator`    | `CT_Tool` (source) | Lua    | Med   |
|                 | `time_displace`       | `CT_Tool`      | Lua         | Low   |
| Filters         | `builtin_blur`        | `CT_Tool`      | Lua         | Low   |
|                 | `builtin_resize`      | `CT_Tool`      | Lua         | Low   |
|                 | `variable_blur`       | `CT_Tool`      | Lua (SAT)   | Med   |
| Modifiers       | `modifier`            | `CT_Modifier`  | Lua         | High  |
|                 | `point_modifier`      | `CT_Modifier`  | Lua         | High  |
| Display/shaders | `view_lut`            | `CT_ViewLUTPlugin` | Lua + GLSL | Med |
|                 | `dctl_kernel`         | `CT_Tool`      | Lua + DCTL  | High  |
| Reference       | `controls_demo`       | `CT_Tool`      | Lua         | Low   |
|                 | `notifychanged_demo`  | `CT_Tool`      | Lua         | Low   |

Risk levels reflect how confident we are the template is correct based on the
SDK reference and parser-level checks:

- **Low** — directly mirrors a documented SDK example, simple Lua, no aux paths.
- **Medium** — uses several documented APIs together (Shape system, sampling,
  source-tool registration, GLSL parameter passing). Each API is documented
  but the combination has more surface area to misalign on.
- **High** — `CT_Modifier` is barely covered in the SDK; `dctl_kernel` exercises
  GPU-compute integration (`DVIPComputeNode`, parameter blocks, samplers) that
  isn't reachable by static checks.

Install location:

| Platform | Path |
|---|---|
| macOS   | `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Support/Fusion/Fuses` |
| Windows | `%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Fuses` |
| Linux   | `~/.local/share/DaVinciResolve/Fusion/Fuses` |

### `dctl` — DCTL color-transform files

Regular DCTLs live under Resolve's LUT directory and appear as LUT-style entries
in the LUT browser, the Clip/Node LUT picker, and the ResolveFX DCTL plugin.
After install, call `project_settings(action='refresh_luts')` to make Resolve
discover the new file.

ACES DCTLs (IDT/ODT) install to a separate ACES Transforms directory and are
scanned **only at Resolve startup**. Install requires a Resolve restart.

Actions: `path`, `list`, `install`, `remove`, `read`, `validate`, `template`,
`list_templates`.

**8 template kinds**:

| Kind                | Entry point                | Category       | Notes                          |
|---------------------|----------------------------|----------------|--------------------------------|
| `transform`         | `__DEVICE__ float3 transform()` | `lut`     | Per-pixel, no alpha            |
| `transform_alpha`   | `__DEVICE__ float4 transform()` | `lut`     | Resolve 19.1+; alpha mode tag  |
| `transition`        | `__DEVICE__ float4 transition()` | `lut`    | Reads `TRANSITION_PROGRESS`    |
| `matrix`            | `__DEVICE__ float3 transform()` | `lut`     | 3x3 color matrix as constants  |
| `kernel`            | `__DEVICE__ float3 transform()` | `lut`     | Bare TODO stub                 |
| `lut_apply`         | `__DEVICE__ float3 transform()` | `lut`     | Wraps an external `.cube` LUT  |
| `aces_idt`          | `__DEVICE__ float3 transform()` | `aces_idt` | ACES Input Device Transform   |
| `aces_odt`          | `__DEVICE__ float3 transform()` | `aces_odt` | ACES Output Device Transform  |

The `template` action returns `suggested_category` so callers know which install
path to use:

```python
gen = dctl('template', {'kind': 'aces_idt', 'name': 'MyIDT'})
dctl('install', {'name': 'MyIDT', 'source': gen['source'],
                 'category': gen['suggested_category']})
```

Install locations:

| Category | macOS | Windows | Linux |
|---|---|---|---|
| `lut`      | `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/LUT` | `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\LUT` | `~/.local/share/DaVinciResolve/LUT` |
| `aces_idt` | `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/ACES Transforms/IDT` | `%APPDATA%\…\ACES Transforms\IDT` | `~/.local/share/DaVinciResolve/ACES Transforms/IDT` |
| `aces_odt` | …`/ACES Transforms/ODT` | …`\ACES Transforms\ODT` | …`/ACES Transforms/ODT` |

Subdir support is available within any category for organization (e.g.
`subdir='MCP'` puts a generated DCTL under `LUT/MCP/`).

See `docs/notes/dctl-notes.md` for the full DCTL language reference, custom UI
parameter syntax (`DCTLUI_SLIDER_FLOAT`, `DCTLUI_COLOR_PICKER`, etc.), and
ACES parametric V1/V2 details.

## What's been tested vs. what hasn't

**Tested:**
- All 18 Fuse templates pass `luac -p` (Lua 5.5) with default *and* varied
  options
- All 8 DCTL templates produce a valid entry-point signature
- Filesystem round-trip (install → list → read → remove) for both tools across
  all install categories (LUT, ACES IDT, ACES ODT)
- Live v2.16.0 lifecycle probe confirmed generated Fuse install/read/list/remove,
  regular DCTL install/read/list/refresh/remove, and ACES IDT
  install/read/list/remove on Resolve Studio 20.3.2.9
- `list_templates` enumeration for both tools
- Path-traversal and name-regex rejection paths
- Subdir handling with traversal guards (no `..`, no hidden dirs)
- `view_lut` parameter types: `float`, `vec2`, `vec3_rgb`, `vec4_rgba`

**Still not fully proven:**
- Restarting Resolve and confirming every generated Fuse appears in the Fusion
  tool list
- Confirming every template renders correctly at runtime (e.g. does
  `color_matrix` brightness actually shift values? does `text_overlay` draw
  glyphs? does `point_modifier` drive a Merge Center input?)
- The Modifier templates — `CT_Modifier` is barely covered in the Fuse SDK
- The `dctl_kernel` Fuse — `DVIPComputeNode` runtime, sampler setup,
  parameter struct memory layout
- GLSL `view_lut` shader compilation (we only check braces and the
  `ShadePixel` substring; `glslangValidator` would be needed for full GLSL
  parsing)
- Every DCTL template compiling on every Resolve GPU backend (Metal/CUDA/OpenCL
  each have edge cases)
- `variable_blur` SAT-based pattern — `UseSAT()`/`SampleAreaW()`/`RecycleSAT()`
  are documented but unverified in this combination
- `source_generator` `CT_SourceTool` registration — the `REG_Source_*Ctrls`
  attributes mirror the SDK example but the global `Width`/`Height`/`Scale`/
  `XAspect`/`YAspect` variables we reference are inferred, not documented
- `controls_demo` and `notifychanged_demo` — Inspector layout and dynamic
  show/hide behavior

## Reporting feedback

If a template fails to load, render incorrectly, or produces a Resolve
console error, please open an issue at
<https://github.com/samuelgursky/davinci-resolve-mcp/issues> with:

- Template kind (e.g. `text_overlay`, `dctl_kernel`)
- DaVinci Resolve version and platform
- The exact MCP call you made (action, name, options)
- Any console output from Workspace → Console (for Fuses) or the build-error
  dialog (for DCTLs)
- Whether the bug reproduces with default options or only with custom ones

A short manual-smoke-test recipe for the highest-risk templates lives at the
end of this document.

## Manual smoke test

For maintainers who want to live-test before merging template changes.

```bash
# Install the highest-risk Fuses
venv/bin/python <<'EOF'
import sys
sys.modules['DaVinciResolveScript'] = type(sys)('DaVinciResolveScript')
from src.server import fuse_plugin
for kind in ('text_overlay', 'dctl_kernel', 'point_modifier', 'variable_blur'):
    name = 'McpSmoke' + kind.replace('_', '').title()
    src = fuse_plugin('template', {'kind': kind, 'name': name})['source']
    print(fuse_plugin('install', {'name': name, 'source': src, 'overwrite': True}))
EOF

# Quit and relaunch Resolve, then in the Fusion page:
#   Effects Library → Tools → Fuses → MCP → McpSmokeTextoverlay
#   Effects Library → Tools → Fuses → MCP → McpSmokeDctlkernel
#   Effects Library → Tools → Fuses → MCP → McpSmokeVariableblur
# Drop each onto a node graph between MediaIn1 and MediaOut1.
# For McpSmokePointmodifier: right-click any Point input (e.g. Merge Center)
# in any tool → Modify with → MCP → McpSmokePointmodifier.
# Verify Inspector controls work and the image responds.
```

For the DCTL side:

```bash
venv/bin/python <<'EOF'
import sys
sys.modules['DaVinciResolveScript'] = type(sys)('DaVinciResolveScript')
from src.server import dctl
# Regular DCTL — refresh-luts to pick up
gen = dctl('template', {'kind': 'lut_apply', 'name': 'McpSmokeLut'})
dctl('install', {'name': 'McpSmokeLut', 'source': gen['source'],
                 'subdir': 'MCP', 'overwrite': True})
# ACES IDT — restart Resolve to pick up
gen = dctl('template', {'kind': 'aces_idt', 'name': 'McpSmokeIdt'})
dctl('install', {'name': 'McpSmokeIdt', 'source': gen['source'],
                 'category': gen['suggested_category'], 'overwrite': True})
EOF
# Then: project_settings(action='refresh_luts') in your MCP client for the
# regular one; restart Resolve for the ACES IDT.
```

Cleanup:

```bash
venv/bin/python -c "
import sys
sys.modules['DaVinciResolveScript'] = type(sys)('DaVinciResolveScript')
from src.server import fuse_plugin, dctl
for n in ('McpSmokeTextoverlay', 'McpSmokeDctlkernel',
          'McpSmokePointmodifier', 'McpSmokeVariableblur'):
    print(fuse_plugin('remove', {'name': n}))
print(dctl('remove', {'name': 'McpSmokeLut', 'subdir': 'MCP'}))
print(dctl('remove', {'name': 'McpSmokeIdt', 'category': 'aces_idt'}))
"
```

## Source media integrity

These tools write into Resolve's plugin and LUT directories. They do not
touch source media. Effects authored with these tools modify Resolve's
grade/render pipeline, not the original camera files. Do not bake template
effects into source media, create rendered derivatives, or export/reimport
processed media unless the user explicitly asks for that workflow.
