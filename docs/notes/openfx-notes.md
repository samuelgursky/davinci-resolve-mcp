# DaVinci Resolve OpenFX Notes

Blackmagic's OpenFX developer package is for building native C++ image-effect
plugins that Resolve can load. It is not a separate control API for this MCP
server. The MCP can call Resolve scripting methods that reference installed OFX
generators, but it should not try to compile, install, or manage OFX bundles
unless the user explicitly asks.

## What The Bundled Package Contains

The installed Resolve developer package includes:

| Directory | Purpose |
|---|---|
| `OpenFX-1.4` | Official OpenFX header files. |
| `Support` | C++ wrapper/support library around the OFX C plugin API. |
| `GainPlugin` | Single-input filter sample with CPU, CUDA, OpenCL, and Metal render paths. |
| `TemporalBlurPlugin` | Temporal sample that requests neighboring frames. |
| `DissolveTransitionPlugin` | Transition sample with two compulsory inputs and a `Transition` parameter. |
| `RandomFrameAccessPlugin` | Sample that demonstrates random temporal frame access. |

Each sample includes Xcode project files, Visual Studio files, and a Makefile.
The plugin source is split between the plugin class/factory files and optional
GPU kernel files:

- `[PluginName].h`
- `[PluginName].cpp`
- `CudaKernel.cu`
- `OpenCLKernel.cpp`
- `MetalKernel.mm`

## Plugin Install Locations

Compiled plugins produce a `[PluginName].ofx.bundle` directory. Resolve discovers
plugins from the standard OFX plugin folders:

| Platform | OFX plugin folder |
|---|---|
| macOS | `/Library/OFX/Plugins` |
| Linux | `/usr/OFX/Plugins` |
| Windows | `C:\Program Files\Common Files\OFX\Plugins` |

Installing into these locations is outside normal MCP behavior because it writes
to system plugin directories and may require administrator privileges.

## OFX Plugin Shape

The bundled samples follow the OpenFX support-library pattern:

- Subclass `OFX::ImageProcessor` and implement processing paths such as
  `processImagesCUDA`, `processImagesOpenCL`, `processImagesMetal`, and
  `multiThreadProcessImages`.
- Subclass `OFX::ImageEffect`; `render()` is the core render callback.
- Implement `isIdentity()` when a parameter state can pass the source through
  unchanged.
- Implement `changedParam()` and `changedClip()` for host notifications.
- Implement `getFramesNeeded()` for temporal effects that need neighboring or
  random frames.
- Keep `setupAndProcess()` as the handoff from Resolve render arguments to the
  image processor.
- Implement a factory with `describe()`, `describeInContext()`, and
  `createInstance()`.
- Register factories through `OFX::Plugin::getPluginIDs()`.

Important Resolve/OpenFX capability flags from the samples:

- `OFX::eContextFilter` is for a traditional one-input effect.
- `OFX::eContextTransition` requires two input clips plus the standard
  transition parameter.
- `setNoSpatialAwareness(true)` tells the host the result does not depend on
  neighboring pixels, which can make an effect eligible during LUT generation.
- `setTemporalClipAccess(true)` is needed for effects that request frames beyond
  the current source frame.
- `setSupportsCudaRender`, `setSupportsOpenCLRender`, and
  `setSupportsMetalRender` advertise GPU render paths to the host.
- If using the host-provided CUDA stream, call `setSupportsCudaStream(true)`.
  If using an internal/default stream, synchronize GPU work before returning
  from `render()`.

## What This Means For The MCP

The current scripting overlap is small and already present:

- `timeline(action="insert_ofx_generator", params={"name": "..."})` wraps
  `Timeline.InsertOFXGeneratorIntoTimeline(generatorName)`.
- `graph(action="get_tools_in_node", ...)` can report OFX tools present in a
  color node when Resolve exposes them.

The Resolve scripting README does not expose a general "list installed OFX
plugins" method. If an OFX insert fails, the likely causes are:

- The named OFX generator is not installed in Resolve's OFX plugin path.
- Resolve has not been restarted since the bundle was installed.
- The plugin is an effect/transition rather than an OFX generator accepted by
  `InsertOFXGeneratorIntoTimeline`.
- The plugin name/grouping shown in Resolve does not match the string passed to
  the scripting API.
- The plugin failed to load because of host capability, binary compatibility, or
  GPU/backend issues.

## Useful Future Additions

Good repo additions, if this becomes a real workflow need:

1. A read-only diagnostic helper that scans standard OFX plugin folders and
   reports discovered `.ofx.bundle` names. This would be a filesystem inventory,
   not a Resolve API guarantee.
2. Better error text for `insert_ofx_generator` that points users to plugin
   install paths and restart/name-mismatch checks.
3. A small developer example showing how an installed OFX generator can be
   inserted through the MCP, plus how to inspect resulting Color-page node tools.
4. No automatic OFX install/build flow by default. Compiling and installing
   native plugins is a system-level operation and should stay explicit.

## Source Media Integrity

OpenFX effects process frames provided by Resolve and should not modify camera
originals. Any generated renders, caches, logs, or diagnostics should remain
explicit outputs, cache files, or sidecars. Do not use OFX examples as a reason
to create proxies or derivatives of source media without a direct user request.
