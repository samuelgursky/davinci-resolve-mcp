# DaVinci Resolve MCP Configuration Templates

This directory contains configuration templates for integrating DaVinci Resolve MCP with different AI assistant clients.

## Available Templates

### Cursor Integration

`cursor-mcp-config.template.json` - Template for configuring Cursor AI to use the DaVinci Resolve MCP server.

To use this template:

1. Copy the contents to your Cursor MCP configuration file:
   - macOS: `~/.cursor/mcp.json`
   - Windows: `%APPDATA%\Cursor\mcp.json`

2. Replace the placeholders with your actual paths:
   - `${YOUR_PYTHON_PATH}` - Path to your Python interpreter (typically in a virtual environment)
   - `${YOUR_REPO_PATH}` - Path to the DaVinci Resolve MCP repository

Example (macOS):
```json
{
  "mcpServers": {
    "davinci-resolve": {
      "name": "DaVinci Resolve MCP",
      "command": "/Users/username/davinci-resolve-mcp/venv/bin/python",
      "args": ["/Users/username/davinci-resolve-mcp/resolve_mcp_server.py"]
    }
  }
}
```

### Claude Desktop Integration

`claude-desktop-config.template.json` - Template for configuring Claude Desktop to use the DaVinci Resolve MCP server.

To use this template:

- Copy the template to your Claude Desktop configuration directory (location varies by installation)
  - Windows - %appdata%\Claude\claude_desktop_config.json
- Rename it to `claude_desktop_config.json`
- Replace the placeholders with your actual paths:
   - `${YOUR_PYTHON_PATH}` - Path to your Python interpreter
   - `${YOUR_REPO_PATH}` - Path to the DaVinci Resolve MCP repository

## Automatic Setup

For automatic configuration, use the appropriate launch script which will set up the configuration for you:

```bash
# For Cursor
./scripts/mcp_resolve-cursor_start

# For Claude Desktop
./scripts/mcp_resolve-claude_start
```

Or use the universal launcher:

```bash
./scripts/mcp_resolve_launcher.sh 