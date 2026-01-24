# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DaVinci Resolve MCP Server - A Model Context Protocol (MCP) server that connects AI coding assistants (Cursor, Claude Desktop) to DaVinci Resolve, enabling them to query and control DaVinci Resolve through natural language.

## Development Commands

### Setup
```bash
# Create virtual environment and install dependencies
python -m venv venv
# Activate: Windows: venv\Scripts\activate | macOS/Linux: source venv/bin/activate
pip install -r requirements.txt

# Or use one-step installation
# Windows: install.bat | macOS/Linux: ./install.sh
```

### Running the Server
```bash
# Quick start (recommended)
# Windows: run-now.bat | macOS/Linux: ./run-now.sh

# Run via main entry point with debug logging
python src/main.py --debug

# Client-specific launch scripts (macOS)
./scripts/mcp_resolve-cursor_start
./scripts/mcp_resolve-claude_start
```

### Pre-launch Verification
```bash
# Windows: scripts\check-resolve-ready.bat | macOS: ./scripts/check-resolve-ready.sh
```

## Architecture

### Entry Points
- `src/main.py` - Main entry point, handles environment setup and server startup
- `src/resolve_mcp_server.py` - Core MCP server implementation with all tool/resource definitions

### Core Components
The MCP server uses FastMCP from the `mcp` package and exposes tools/resources for:
- **Project Management**: List/open/create/save projects via `resolve.GetProjectManager()`
- **Timeline Operations**: Create/list/switch timelines, add markers
- **Media Pool Operations**: Import media, create bins, manage clips
- **Color Page Operations**: Apply LUTs, color correction, node management
- **Delivery Operations**: Render queue management

### Module Organization
```
src/
├── api/              # Domain-specific API wrappers
│   ├── project_operations.py
│   ├── timeline_operations.py
│   ├── media_operations.py
│   ├── color_operations.py
│   └── delivery_operations.py
└── utils/            # Utility modules
    ├── platform.py           # Platform detection and path resolution
    ├── resolve_connection.py # DaVinci Resolve connection handling
    ├── object_inspection.py  # API introspection utilities
    ├── layout_presets.py     # UI layout management
    ├── app_control.py        # Application lifecycle control
    ├── cloud_operations.py   # Cloud project operations
    └── project_properties.py # Project settings management
```

### DaVinci Resolve Scripting API
The server connects to Resolve via `DaVinciResolveScript` module which requires environment variables:
- `RESOLVE_SCRIPT_API` - Path to Developer/Scripting directory
- `RESOLVE_SCRIPT_LIB` - Path to fusionscript.dll/.so
- `PYTHONPATH` - Must include the Modules directory

The connection is established at module load time in `src/resolve_mcp_server.py`:
```python
import DaVinciResolveScript as dvr_script
resolve = dvr_script.scriptapp("Resolve")
```

### Platform Paths
**Windows:**
- API: `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting`
- Lib: `C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll`

**macOS:**
- API: `/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting`
- Lib: `/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so`

## Key Patterns

### MCP Tool Registration
Tools are registered using decorators in `src/resolve_mcp_server.py`:
```python
@mcp.tool()
def switch_page(page: str) -> str:
    """Switch to a specific page in DaVinci Resolve."""
    # Implementation
```

### MCP Resource Registration
Resources provide read-only data access:
```python
@mcp.resource("resolve://version")
def get_resolve_version() -> str:
    """Get DaVinci Resolve version information."""
    return f"{resolve.GetProductName()} {resolve.GetVersionString()}"
```

### Resolve Object Hierarchy
```
Resolve (root)
├── GetProjectManager() -> ProjectManager
│   ├── GetCurrentProject() -> Project
│   │   ├── GetMediaPool() -> MediaPool
│   │   ├── GetCurrentTimeline() -> Timeline
│   │   └── GetGallery() -> Gallery
```

## Configuration

MCP configuration for Cursor/Claude is stored in:
- **System**: `~/.cursor/mcp.json` (macOS) or `%APPDATA%\Cursor\mcp.json` (Windows)
- **Project**: `.cursor/mcp.json`

Example configuration:
```json
{
  "mcpServers": {
    "davinci-resolve": {
      "command": "/path/to/venv/bin/python",
      "args": ["/path/to/davinci-resolve-mcp/src/main.py"]
    }
  }
}
```

## Important Notes

- DaVinci Resolve must be running before starting the MCP server
- The server auto-detects platform and sets appropriate paths via `src/utils/platform.py`
- Many features are implemented but not all have been verified working (see docs/FEATURES.md for status)
- Windows support is stable as of v1.3.3; Linux is not supported
