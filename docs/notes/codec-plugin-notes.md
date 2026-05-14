# DaVinci Resolve Codec Plugin Notes

Blackmagic's CodecPlugin README documents the DaVinci Resolve IO Encode Plugin
SDK. These plugins extend Resolve Studio's Deliver page with additional render
containers/codecs. They are native encode plugins, not a Python scripting API
surface.

The SDK is encode-focused: it enables additional codecs and container formats
that can be rendered directly from Resolve. It does not describe a decoder or
Media Pool import plugin API. Blackmagic notes that only CPU-based plugins are
currently supported.

## Current MCP Surface

The MCP cannot build, install, load, or configure codec plugins directly.
Relevant existing render actions are:

- `render(action="get_formats")` wraps `Project.GetRenderFormats()`.
- `render(action="get_codecs", params={"format": "..."})` wraps
  `Project.GetRenderCodecs(renderFormat)`.
- `render(action="set_format_and_codec", params={"format": "...", "codec": "..."})`
  wraps `Project.SetCurrentRenderFormatAndCodec(format, codec)`.
- `render(action="get_format_and_codec")` wraps
  `Project.GetCurrentRenderFormatAndCodec()`.
- `render(action="get_resolutions", params={"format": "...", "codec": "..."})`
  wraps `Project.GetRenderResolutions(format, codec)`.
- `render(action="set_settings")`, `render(action="add_job")`, and
  `render(action="start")` run the normal render pipeline once Resolve exposes
  the desired format/codec.

After an IO encode plugin is installed and Resolve is restarted, plugin-provided
formats and codecs should appear through the same format/codec query actions.
There is no documented Resolve scripting method to list codec plugin bundles or
distinguish built-in codecs from plugin-provided codecs.

## Plugin Packaging

Codec plugins are native binaries:

| Platform | Binary type |
|---|---|
| macOS | 64-bit dynamic library |
| Linux | 64-bit shared object |
| Windows | 64-bit DLL |

Plugins are packaged as `.dvcp.bundle` folders:

```text
PLUGIN.dvcp.bundle
  Contents/
    ARCH_1/
      PLUGIN.dvcp
    ARCH_2/
      PLUGIN.dvcp
```

The plugin name must match in both the bundle name and binary name.

Supported architecture folder names:

| Platform | Architecture folder |
|---|---|
| macOS | `MacOS` for Universal2 or Arm64 |
| macOS Intel | `MacOS-x86-64`, checked before `MacOS` on Intel-only machines |
| Linux | `Linux-x86-64` |
| Windows | `Win64` |

## Install Locations

Install the `.dvcp.bundle` into Resolve's `IOPlugins` folder:

| Platform | IOPlugins folder |
|---|---|
| macOS | `/Library/Application Support/Blackmagic Design/DaVinci Resolve/IOPlugins` |
| macOS App Store | `~/Library/Containers/com.blackmagic-design.DaVinciResolveAppStore/Data/Library/Application Support/IOPlugins` |
| Linux | `/opt/resolve/IOPlugins` |
| Windows | `%ProgramData%\Blackmagic Design\DaVinci Resolve\Support\IOPlugins` |

System-wide install paths may require administrator privileges. Installing or
replacing native codec plugins should remain an explicit user request.

## Sample Plugin

The developer package includes `Examples/x264_encoder_plugin`, which wraps the
x264 encoder. The sample flow is:

1. Build/install x264 from source.
2. Point `.mk.defs` on macOS/Linux or `plugin2015.vcxproj` on Windows at the
   x264 install path.
3. Build with `make` on macOS/Linux or Visual Studio on Windows.
4. Package the resulting binary into a `.dvcp.bundle` architecture folder.
5. Copy the bundle to `IOPlugins`.
6. Restart Resolve.

Once loaded, the plugin's supported containers should appear in the Deliver page
format list. If a plugin-supported container, or QuickTime, is selected, the
plugin's codecs should appear in the codec list and expose any plugin-specific
render-settings UI.

## Practical Failure Checks

If a custom codec is missing from `render.get_formats` or `render.get_codecs`:

- Confirm Resolve Studio supports the plugin and has been restarted after
  installation.
- Confirm the bundle suffix is `.dvcp.bundle`.
- Confirm the bundle and binary names match exactly.
- Confirm the architecture folder matches the current platform and CPU.
- Confirm the plugin binary is in `Contents/<ARCH>/PLUGIN.dvcp`.
- Confirm the plugin is an encode plugin for Deliver, not an import/decode
  extension.
- Confirm any external codec library dependencies, such as x264, can be found by
  the plugin at runtime.
- Query formats first, then codecs for the selected format. A codec may only
  appear for specific containers.

## Useful Future Additions

Good repo additions, if codec-plugin troubleshooting becomes common:

1. A read-only IOPlugins inventory helper that scans known plugin folders and
   reports `.dvcp.bundle` structure, architecture folders, and matching binary
   names.
2. Better `render.set_format_and_codec` failure text that suggests checking
   `render.get_formats`, `render.get_codecs`, plugin install paths, and restart
   requirements.
3. A developer checklist for packaging `.dvcp.bundle` outputs from the bundled
   x264 sample.
4. No automatic native build/install flow by default. Codec plugins are native
   executable code in system/plugin directories and should stay opt-in.

## Source Media Integrity

Codec plugins affect render output from Resolve. They should not be used as a
reason to transcode, proxy, or replace source media unless the user explicitly
asks for that derivative workflow.
