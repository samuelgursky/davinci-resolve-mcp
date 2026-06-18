# Installation and Configuration

This guide covers Resolve requirements, the universal installer, supported MCP clients, server modes, and manual configuration.

## Requirements

- **DaVinci Resolve Studio** 18.5+ (macOS, Windows, or Linux) — the free edition does not support external scripting
- **Python 3.10+** (the MCP SDK requires 3.10). **3.10–3.12 is the lowest-risk
  choice**; 3.13/3.14 also work on recent Resolve builds — see below
- DaVinci Resolve running with **Preferences > General > "External scripting using"** set to **Local**

> **Python 3.13 / 3.14:** these are **allowed** — setup will use them and warn.
> Python 3.14 is verified working against DaVinci Resolve Studio 20.3.2. On
> *older* Resolve builds the scripting bridge may fail to load on 3.13+
> (`scriptapp("Resolve")` returns `None`); setup's connection check will tell you
> if that happens. If it does, install a 3.10–3.12 interpreter
> (`brew install python@3.12`, `pyenv install 3.12`, or python.org on Windows) and
> point the launcher at it with `DAVINCI_RESOLVE_MCP_PYTHON=/path/to/python3.12`.

Validated live coverage is based on **DaVinci Resolve 19.1.3 Studio** for the original API surface, plus **DaVinci Resolve 20.3.2 Studio** for the Resolve 20.0-20.2.2 scripting additions. Resolve 21 beta APIs are intentionally deferred until a stable release.

## Quick Start

```bash
# Make sure DaVinci Resolve Studio is running, then:
npx davinci-resolve-mcp setup
```

The npm launcher installs a managed copy in your user application-data directory
and then runs the universal Python installer from there. MCP client configs point
directly at the managed Python virtual environment and `src/server.py`, so Node
is not required after setup.

For source installs:

```bash
git clone https://github.com/samuelgursky/davinci-resolve-mcp.git
cd davinci-resolve-mcp

python install.py
```

The universal installer auto-detects your platform, finds your DaVinci Resolve installation, creates a virtual environment, and configures your MCP client — all in one step.

The installer and MCP server perform a best-effort update check against the latest GitHub release. The server check runs in the background, is throttled to once every 24 hours, and never installs code automatically. Set `DAVINCI_RESOLVE_MCP_UPDATE_CHECK=0` to disable it, or `DAVINCI_RESOLVE_MCP_UPDATE_INTERVAL_HOURS` to adjust the interval.

### Supported MCP Clients

The installer can automatically configure any of these clients:

| Client | Config Written To |
|--------|-------------------|
| Claude Desktop | `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) |
| Claude Code | `.mcp.json` (project root) |
| Cursor | `~/.cursor/mcp.json` |
| VS Code (Copilot) | `.vscode/mcp.json` (workspace) |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` |
| Cline | VS Code global storage |
| Roo Code | VS Code global storage |
| Zed | `~/.config/zed/settings.json` |
| Continue | `~/.continue/config.json` |
| OpenCode | `~/.config/opencode/opencode.json` (or project-root `opencode.json`) |
| JetBrains IDEs | Manual (Settings > Tools > AI Assistant > MCP) |

You can configure multiple clients at once, or use `--clients manual` to get copy-paste config snippets.

### Installer Options

```bash
npx davinci-resolve-mcp setup                 # Interactive npm setup
npx davinci-resolve-mcp setup --clients all   # Configure all clients
npx davinci-resolve-mcp doctor                # Dry-run environment/config check
npx davinci-resolve-mcp server                # Launch the managed MCP server
npx davinci-resolve-mcp control-panel         # Launch the local control panel

python install.py                              # Interactive mode
python install.py --clients all                # Configure all clients
python install.py --clients cursor,claude-desktop  # Specific clients
python install.py --clients manual             # Just print the config
python install.py --dry-run --clients all      # Preview without writing
python install.py --no-venv --clients cursor   # Skip venv creation
```

### Server Modes

The MCP server comes in two modes:

| Mode | File | Tools | Best For |
|------|------|-------|----------|
| **Compound** (default) | `src/server.py` | 32 | Most users — fast, clean, low context usage |
| **Full** | `src/resolve_mcp_server.py` | 341 | Power users who want one tool per API method |

The compound server's `timeline_item` tool includes dedicated actions for common workflows:

| Category | Actions | Parameters |
|----------|---------|------------|
| **Retime** | `get_retime`, `set_retime` | process (nearest, frame_blend, optical_flow), motion_estimation (0-6) |
| **Transform** | `get_transform`, `set_transform` | Pan, Tilt, ZoomX/Y, RotationAngle, AnchorPointX/Y, Pitch, Yaw, FlipX/Y |
| **Crop** | `get_crop`, `set_crop` | CropLeft, CropRight, CropTop, CropBottom, CropSoftness, CropRetain |
| **Composite** | `get_composite`, `set_composite` | Opacity, CompositeMode |
| **Audio** | `get_audio`, `set_audio` | Volume, Pan, AudioSyncOffset |
| **Keyframes** | `get_keyframes`, `add_keyframe`, `modify_keyframe`, `delete_keyframe`, `set_keyframe_interpolation` | property, frame, value, interpolation (Linear, Bezier, EaseIn, EaseOut, EaseInOut) |

The installer uses the compound server by default. To use the full server:
```bash
python src/server.py --full    # Launch full 341-tool server
# Or point your MCP config directly at src/resolve_mcp_server.py
```

### Local Control Panel

The repository includes a local, single-user control panel for server status,
Resolve clip visibility, source-safe media-analysis jobs, and the searchable
analysis index. Persisted analysis jobs refresh the index automatically after
successful slices; the manual Build Index action is for rebuilding from existing
reports.

From the repository root:

```bash
venv/bin/python -m src.control_panel
```

This opens the browser by default. Use `--no-open` to run only the localhost
server, or `--port` to choose a different port:

```bash
venv/bin/python -m src.control_panel --no-open --port 8766
```

You can also ask an AI coding agent: **"Open the Resolve MCP control panel for
this repo."** The agent should launch the command above and open the local URL.

### Manual Configuration

If you prefer to set things up yourself, add to your MCP client config:

```json
{
  "mcpServers": {
    "davinci-resolve": {
      "command": "/path/to/venv/bin/python",
      "args": ["/path/to/davinci-resolve-mcp/src/server.py"],
      "env": {
        "RESOLVE_SCRIPT_API": "/path/to/DaVinci Resolve/Developer/Scripting",
        "RESOLVE_SCRIPT_LIB": "/path/to/fusionscript.so-or-dll",
        "PYTHONPATH": "/path/to/DaVinci Resolve/Developer/Scripting/Modules"
      }
    }
  }
}
```

On Windows, installer-generated configs also include `PYTHONHOME`. That scopes Resolve's Python binding to the selected interpreter and avoids the Resolve 20.3 multi-Python crash reported in [Issue #26](https://github.com/samuelgursky/davinci-resolve-mcp/issues/26).

When the compound server is running, `resolve_control(action="get_version")`
includes the local MCP version, the last update-check status, and the current
update decision under the `mcp` key. `resolve_control(action="mcp_update_status",
params={"force_check": true})` performs an explicit foreground check.

### MCP Update Policy

The server keeps update checks non-interactive so MCP stdio startup remains safe
for every client. The installer is the human-facing prompt surface: when a newer
GitHub release is available, interactive installs can update now, continue,
snooze for 24 hours, ignore that release, enable safe auto-update, or disable
checks for the checkout.

Safe auto-update only runs for clean git checkouts with a configured upstream,
and applies `git fetch --tags --prune` followed by `git pull --ff-only`. If the
checkout has local changes, no upstream, or a non-fast-forward update, the
installer continues with the current build.

Installer flags:

```bash
python install.py --update-now
python install.py --update-policy prompt
python install.py --update-policy auto
python install.py --update-policy notify
python install.py --update-policy never
python install.py --clear-update-preferences
```

The same local defaults are available from chat through
`setup(action="get_defaults")` and `setup(action="set_defaults")`. For example,
`{"defaults":{"updates":{"mode":"notify"}}}` changes the MCP update policy
without rerunning the installer. `updates.check_interval_hours` and
`updates.snooze_hours` can also be set from the same setup tool; environment
variables still take precedence when present.

Environment controls:

```bash
DAVINCI_RESOLVE_MCP_UPDATE_CHECK=0
DAVINCI_RESOLVE_MCP_UPDATE_MODE=prompt|auto|notify|never
DAVINCI_RESOLVE_MCP_UPDATE_INTERVAL_HOURS=24
DAVINCI_RESOLVE_MCP_UPDATE_SNOOZE_HOURS=24
DAVINCI_RESOLVE_MCP_UPDATE_STATE=/path/to/update-check.json
```

Platform-specific paths:

| Platform | API Path | Library Path |
|----------|----------|-------------|
| macOS | `/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting` | `fusionscript.so` in DaVinci Resolve.app |
| Windows | `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting` | `fusionscript.dll` in Resolve install dir |
| Linux | `/opt/resolve/Developer/Scripting` | `/opt/resolve/libs/Fusion/fusionscript.so` |
