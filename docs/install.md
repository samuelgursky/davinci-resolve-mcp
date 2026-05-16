# Installation and Configuration

This guide covers Resolve requirements, the universal installer, supported MCP clients, server modes, and manual configuration.

## Requirements

- **DaVinci Resolve Studio** 18.5+ (macOS, Windows, or Linux) — the free edition does not support external scripting
- **Python 3.10–3.12** recommended (3.13+ may have ABI incompatibilities with Resolve's scripting library)
- DaVinci Resolve running with **Preferences > General > "External scripting using"** set to **Local**

Validated live coverage is based on **DaVinci Resolve 19.1.3 Studio** for the original API surface, plus **DaVinci Resolve 20.3.2 Studio** for the Resolve 20.0-20.2.2 scripting additions. Resolve 21 beta APIs are intentionally deferred until a stable release.

## Quick Start

```bash
# Clone the repository
git clone https://github.com/samuelgursky/davinci-resolve-mcp.git
cd davinci-resolve-mcp

# Make sure DaVinci Resolve is running, then:
python install.py
```

The universal installer auto-detects your platform, finds your DaVinci Resolve installation, creates a virtual environment, and configures your MCP client — all in one step.

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
| JetBrains IDEs | Manual (Settings > Tools > AI Assistant > MCP) |

You can configure multiple clients at once, or use `--clients manual` to get copy-paste config snippets.

### Installer Options

```bash
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
| **Compound** (default) | `src/server.py` | 31 | Most users — fast, clean, low context usage |
| **Full** | `src/resolve_mcp_server.py` | 329 | Power users who want one tool per API method |

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
python src/server.py --full    # Launch full 329-tool server
# Or point your MCP config directly at src/resolve_mcp_server.py
```

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

Platform-specific paths:

| Platform | API Path | Library Path |
|----------|----------|-------------|
| macOS | `/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting` | `fusionscript.so` in DaVinci Resolve.app |
| Windows | `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting` | `fusionscript.dll` in Resolve install dir |
| Linux | `/opt/resolve/Developer/Scripting` | `/opt/resolve/libs/Fusion/fusionscript.so` |
