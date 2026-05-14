# DaVinci Resolve Workflow Integration Notes

Blackmagic ships a separate Workflow Integrations developer package alongside the
Python/Lua scripting docs. This MCP server does not need a Workflow Integration
plugin to run; it talks to Resolve through the standard Python scripting API.
The Workflow Integration package is still useful context when building an
optional Resolve-hosted panel or script UI around the MCP.

## What Workflow Integrations Are

Workflow Integration plugins are Electron apps loaded by DaVinci Resolve Studio
under `Workspace > Workflow Integrations`. Resolve scans a platform-specific
plugin root on startup, reads each plugin's `manifest.xml`, and launches the
plugin's configured JavaScript entry point.

Plugin roots:

| Platform | Workflow Integration plugin root |
|---|---|
| macOS | `/Library/Application Support/Blackmagic Design/DaVinci Resolve/Workflow Integration Plugins/` |
| Windows | `%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Support\Workflow Integration Plugins\` |

Resolve-hosted Python/Lua Workflow Integration scripts are also supported. Those
scripts use the same Resolve scripting API as this MCP server and can create
small UIManager windows inside Resolve. Plugins are supported on macOS and
Windows; scripts are supported on macOS, Windows, and Linux.

## Current Blackmagic Notes Worth Preserving

- Resolve 19.0.2 and newer use an Electron runtime with process sandboxing and
  context isolation enabled by default. New plugins should use a preload script,
  `contextBridge`, and `ipcMain` rather than renderer-side Node access.
- Resolve 20.1 updated Workflow Integrations to Electron 36.3.2 and added
  promise-based JavaScript APIs: `InitializePromise()` and
  `GetResolvePromise()`.
- Plugin authors should keep `WorkflowIntegration.node` current by copying the
  version bundled with the installed Resolve developer package.
- JavaScript Resolve access is plugin-hosted only; Blackmagic notes that there
  is no console-based JavaScript API support.
- `WorkflowIntegration.SetAPITimeout(seconds)` exists for plugin calls that
  should fail instead of blocking indefinitely. `0` disables the timeout.
- `WorkflowIntegration.CleanUp()` should be called when the plugin app quits.

## WorkflowIntegration Module Surface

The Electron-side native module exposes:

| Function | Purpose |
|---|---|
| `GetInfo()` | Returns module metadata, including module version. |
| `Initialize(pluginId)` | Initializes the native bridge for the manifest plugin ID. |
| `InitializePromise(pluginId)` | Promise-returning initialize variant. |
| `GetResolve()` | Returns the Resolve scripting root object. |
| `GetResolvePromise()` | Returns a promise Resolve object; subsequent API calls return promises. |
| `RegisterCallback(name, fn)` | Registers a supported callback. |
| `DeregisterCallback(name)` | Removes a registered callback. |
| `CleanUp()` | Releases the Workflow Integration bridge on plugin quit. |
| `SetAPITimeout(seconds)` | Sets a blocking API timeout for plugin calls. |

Supported callback names:

- `RenderStart`
- `RenderStop`
- `ResolveQuit`

These callbacks are not exposed through the standard Python scripting API used
by this MCP server. If the MCP ever needs event-style render notifications, the
clean design is an optional Workflow Integration companion that forwards these
callbacks to the MCP process over a local HTTP/WebSocket bridge. The core MCP
server should continue to use polling actions such as `render.list_jobs`,
`render.get_job_status`, and `render.is_rendering`.

## UIManager Script Notes

Workflow Integration Python scripts launched by Resolve are automatically given
`resolve` and `project` variables. UI windows are built with:

```python
ui = fusion.UIManager()
dispatcher = bmd.UIDispatcher(ui)
```

The useful primitives for small Resolve-hosted panels are:

- `dispatcher.AddWindow(props, children)` and `dispatcher.AddDialog(...)`
- `win.Show()` followed by `dispatcher.RunLoop()`
- `dispatcher.ExitLoop()` in the window close handler
- `win.Find(id)`, `win.GetItems()`, and `ui.FindWindow(id)` for element lookup
- event handlers via `win.On[element_id].Clicked = handler`

Common UI elements include `Label`, `Button`, `CheckBox`, `ComboBox`, `SpinBox`,
`Slider`, `LineEdit`, `TextEdit`, `ColorPicker`, `TabBar`, `Tree`, and
`TreeItem`. Layout is usually composed with `ui.VGroup`, `ui.HGroup`, `ui.VGap`,
and `ui.HGap`.

## Good Additions For This Repo

The Workflow Integration docs suggest a few possible additions, but none should
be treated as required for the MCP server itself:

1. Add an optional `examples/workflow-integration-panel/` Electron panel that
   demonstrates a Resolve-hosted UI talking to a local MCP-adjacent endpoint.
   Do not vendor `WorkflowIntegration.node`; document that users copy it from
   their installed Resolve developer package.
2. Add an optional Python UIManager script example for launching a few common
   MCP-assisted workflows from inside Resolve.
3. Add a render callback companion only if we need push-style `RenderStart`,
   `RenderStop`, or `ResolveQuit` events. Keep the main MCP render tools
   polling-based and dependency-free.
4. Extend the installer only after there is a real companion plugin/script to
   install into the Workflow Integration root. The current MCP client installer
   should stay focused on MCP client configuration.

## Source Media Integrity Caveat

Blackmagic's sample Workflow Integration Python script includes proxy-linking
examples. This repo's policy is stricter: never create, link, transcode, or
otherwise introduce proxy/derivative source media unless the user explicitly
asks for that workflow. Workflow Integration examples should preserve that rule
and keep analysis outputs in sidecar files or analysis directories.
