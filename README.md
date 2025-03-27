# DaVinci Resolve MCP Server

[![Version](https://img.shields.io/badge/version-1.3.3-blue.svg)](https://github.com/samuelgursky/davinci-resolve-mcp/releases)
[![DaVinci Resolve](https://img.shields.io/badge/DaVinci%20Resolve-18.5+-darkred.svg)](https://www.blackmagicdesign.com/products/davinciresolve)
[![Python](https://img.shields.io/badge/python-3.6+-green.svg)](https://www.python.org/downloads/)
[![macOS](https://img.shields.io/badge/macOS-stable-brightgreen.svg)](https://www.apple.com/macos/)
[![Windows](https://img.shields.io/badge/Windows-stable-brightgreen.svg)](https://www.microsoft.com/windows)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://opensource.org/licenses/MIT)

A Model Context Protocol (MCP) server that connects AI coding assistants (Cursor, Claude Desktop) to DaVinci Resolve, enabling them to query and control DaVinci Resolve through natural language.

## Features

- **Connect to DaVinci Resolve**: Query information and control DaVinci Resolve from your AI assistant
- **Project Management**: List, open, and create DaVinci Resolve projects
- **Timeline Operations**: Create timelines, switch between them, add markers
- **Media Management**: Import media, create bins, list clips
- **Multi-Client Support**: Works with both Cursor and Claude Desktop
- **Cross-Platform**: Full support for both macOS and Windows

## Requirements

- **macOS** or **Windows** with DaVinci Resolve installed
- **Python 3.6+**
- DaVinci Resolve running in the background
- (Optional) Node.js/npm for some features

## Platform Support

| Platform | Status | Quick Start |
|----------|--------|-------------|
| macOS | ✅ Stable | `./run-now.sh` |
| Windows | ✅ Stable | `run-now.bat` |
| Linux | ❌ Not supported | N/A |

## Quick Start Guide

### All

- Clone the repository:
   ```bash
   git clone https://github.com/samuelgursky/davinci-resolve-mcp.git
   cd davinci-resolve-mcp
   ```
- Make sure DaVinci Resolve Studio is installed and running


These quick start scripts will:
1. Check if DaVinci Resolve is running
2. Create a Python virtual environment
3. Install the MCP SDK from the official repository
4. Set up environment variables
5. Configure Cursor/Claude integration
6. Start the MCP server in development mode


### For Windows Users

- Double-click `run-now.bat` or run it from Command Prompt

### For macOS Users

Make the script executable and run:
   ```bash
   chmod +x run-now.sh
   ./run-now.sh
   ```

## Configuration

For configuration of DaVinci Resolve MCP with different AI assistant clients like Cursor or Claude, see [config-templates]()

## Troubleshooting

### Windows
- Make sure to use forward slashes (/) in configuration files
- Python must be installed and paths configured in configs
- DaVinci Resolve must be running before starting the server

### macOS
- Make sure scripts have execute permissions
- Check Console.app for any Python-related errors
- Verify environment variables are set correctly
- DaVinci Resolve must be running before starting the server

## Support

For issues and feature requests, please use the GitHub issue tracker.

## Launch Options

After installation, you have several ways to start the server:

### Client-Specific Launch Scripts

The repository includes dedicated scripts for launching with specific clients:

```bash
# For Cursor integration (macOS)
chmod +x scripts/mcp_resolve-cursor_start
./scripts/mcp_resolve-cursor_start

# For Claude Desktop integration (macOS)
chmod +x scripts/mcp_resolve-claude_start
./scripts/mcp_resolve-claude_start
```

These specialized scripts:
- Set up the proper environment for each client
- Verify DaVinci Resolve is running
- Configure client-specific settings
- Start the MCP server with appropriate parameters

### Pre-Launch Check

Before connecting AI assistants, verify your environment is properly configured:

```bash
# On macOS
./scripts/check-resolve-ready.sh

# On Windows
./scripts/check-resolve-ready.bat
```

These scripts will:
- Verify DaVinci Resolve is running (and offer to start it)
- Check environment variables are properly set
- Ensure the Python environment is configured correctly
- Validate Cursor/Claude configuration
- Optionally launch Cursor

### Universal Launcher

For advanced users, our unified launcher provides full control over both Cursor and Claude Desktop servers:

```bash
# Make the script executable (macOS only)
chmod +x scripts/mcp_resolve_launcher.sh

# Run in interactive mode
./scripts/mcp_resolve_launcher.sh

# Or use command line options
./scripts/mcp_resolve_launcher.sh --start-cursor    # Start Cursor server (uses mcp_resolve-cursor_start)
./scripts/mcp_resolve_launcher.sh --start-claude    # Start Claude Desktop server (uses mcp_resolve-claude_start)
./scripts/mcp_resolve_launcher.sh --start-both      # Start both servers
./scripts/mcp_resolve_launcher.sh --stop-all        # Stop all running servers
./scripts/mcp_resolve_launcher.sh --status          # Show server status
```

Additional options:
- Force mode (skip Resolve running check): `--force`
- Project selection: `--project "Project Name"`

## Full Installation

For a complete manual installation:

1. Clone this repository:
   ```bash
   git clone https://github.com/samuelgursky/davinci-resolve-mcp.git
   cd davinci-resolve-mcp
   ```

2. Create a Python virtual environment:
   ```bash
   # Create virtual environment
   python -m venv venv
   
   # Activate it
   # On macOS/Linux:
   source venv/bin/activate
   # On Windows:
   venv\Scripts\activate
   
   # Install MCP SDK from the official repository
   pip install git+https://github.com/modelcontextprotocol/python-sdk.git
   ```

3. Set up DaVinci Resolve scripting environment variables:

   **For macOS**:
   ```bash
   export RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
   export RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
   export PYTHONPATH="$PYTHONPATH:$RESOLVE_SCRIPT_API/Modules/"
   ```

   **For Windows**:
   ```cmd
   set RESOLVE_SCRIPT_API=C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting
   set RESOLVE_SCRIPT_LIB=C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll
   set PYTHONPATH=%PYTHONPATH%;%RESOLVE_SCRIPT_API%\Modules
   ```
   
   Alternatively, run the pre-launch check script which will set these for you:
   ```
   # On macOS
   ./scripts/check-resolve-ready.sh
   
   # On Windows
   ./scripts/check-resolve-ready.bat
   ```

4. Configure Cursor to use the server by creating a configuration file:

   **For macOS** (`~/.cursor/mcp.json`):
   ```json
   {
     "mcpServers": {
       "davinci-resolve": {
         "name": "DaVinci Resolve MCP",
         "command": "/path/to/venv/bin/python",
         "args": ["/path/to/davinci-resolve-mcp/resolve_mcp_server.py"]
       }
     }
   }
   ```

   **For Windows** (`%APPDATA%\Cursor\mcp.json`):
   ```json
   {
     "mcpServers": {
       "davinci-resolve": {
         "name": "DaVinci Resolve MCP",
         "command": "C:\\path\\to\\venv\\Scripts\\python.exe",
         "args": ["C:\\path\\to\\davinci-resolve-mcp\\resolve_mcp_server.py"]
       }
     }
   }
   ```

5. Start the server using one of the client-specific scripts:
   ```bash
   # For Cursor
   ./scripts/mcp_resolve-cursor_start
   
   # For Claude Desktop
   ./scripts/mcp_resolve-claude_start
   ```

## Usage with AI Assistants

### Using with Cursor

1. Start the Cursor server using the dedicated script:
   ```bash
   ./scripts/mcp_resolve-cursor_start
   ```
   Or use the universal launcher:
   ```bash
   ./scripts/mcp_resolve_launcher.sh --start-cursor
   ```

2. Start Cursor and open a project.

3. In Cursor's AI chat, you can now interact with DaVinci Resolve. Try commands like:
   - "What version of DaVinci Resolve is running?"
   - "List all projects in DaVinci Resolve"
   - "Create a new timeline called 'My Sequence'"
   - "Add a marker at the current position"

### Using with Claude Desktop

1. Create a `claude_desktop_config.json` file in your Claude Desktop configuration directory using the template in the `config-templates` directory.

2. Run the Claude Desktop server using the dedicated script:
   ```bash
   ./scripts/mcp_resolve-claude_start
   ```
   Or use the universal launcher:
   ```bash
   ./scripts/mcp_resolve_launcher.sh --start-claude
   ```

3. In Claude Desktop, you can now interact with DaVinci Resolve using the same commands as with Cursor.

## Available Features

### General
- Get DaVinci Resolve version
- Get/switch current page (Edit, Color, Fusion, etc.)

### Project Management
- List available projects
- Get current project name
- Open project by name
- Create new project
- Save current project

### Timeline Operations
- List all timelines
- Get current timeline info
- Create new timeline
- Switch to timeline by name
- Add marker to timeline

### Media Pool Operations
- List media pool clips
- Import media file
- Create media bin
- Add clip to timeline

## Windows Support Notes

Windows support is stable in v1.3.3 and should not require additional troubleshooting:
- Ensure DaVinci Resolve is installed in the default location
- Environment variables are properly set as described above
- Windows paths may require adjustment based on your installation
- For issues, please check the logs in the `logs/` directory

## Troubleshooting

### DaVinci Resolve Connection
Make sure DaVinci Resolve is running before starting the server. If the server can't connect to Resolve, check that:

1. Your environment variables are set correctly
2. You have the correct paths for your DaVinci Resolve installation
3. You have restarted your terminal after setting environment variables

## Project Structure

```
davinci-resolve-mcp/
├── README.md                 # Main documentation
├── CHANGELOG.md              # Version history
├── FEATURES.md               # Feature matrix
├── LICENSE                   # License information
├── resolve_mcp_server.py     # Main server implementation
├── mcp_resolve_launcher.sh   # Symbolic link to the universal launcher
├── run-now.sh                # Symbolic link to the quick start script
├── run-now.bat               # Symbolic link to the Windows quick start script
├── src/                      # Source code modules
│   └── utils/                # Utility modules
│       ├── platform.py       # Platform-specific functionality
│       └── resolve_connection.py # Resolve connection utilities
├── config-templates/         # Configuration templates
│   ├── README.md             # Template documentation
│   ├── cursor-mcp-config.template.json # Cursor configuration template
│   └── claude-desktop-config.template.json # Claude Desktop configuration template
├── scripts/                  # Helper scripts
│   ├── README.md             # Script documentation
│   ├── run-now.sh            # Quick start script
│   ├── run-now.bat           # Quick start script (Windows)
│   ├── check-resolve-ready.bat # Pre-launch check (Windows)
│   ├── setup.sh              # Full installation
│   ├── server.sh             # Consolidated server management
│   ├── mcp_resolve_launcher.sh # Universal launcher script
│   ├── mcp_resolve-cursor_start # Cursor-specific launcher
│   ├── mcp_resolve-claude_start # Claude-specific launcher
│   └── check-resolve-ready.sh # Pre-launch check
├── examples/                 # Example usage scripts
│   ├── README.md             # Examples documentation
│   ├── getting_started.py    # Simple starter example
│   ├── markers/              # Marker-related examples
│   │   ├── README.md         # Marker examples documentation
│   │   └── ...               # Marker example scripts
│   ├── timeline/             # Timeline examples
│   │   ├── README.md         # Timeline examples documentation
│   │   └── ...               # Timeline example scripts
│   └── media/                # Media management examples
│       ├── README.md         # Media examples documentation
│       └── ...               # Media example scripts
└── venv/                     # Python virtual environment (created by setup script)
```

## License

MIT

## Acknowledgments

- Blackmagic Design for DaVinci Resolve and its API
- The MCP protocol team for enabling AI assistant integration

## Author

Samuel Gursky (samgursky@gmail.com)
- GitHub: [github.com/samuelgursky](https://github.com/samuelgursky)

## Future Plans

- Windows and Linux support
- Additional DaVinci Resolve features
- Support for Claude Desktop

## Development

If you'd like to contribute, please check the feature checklist in the repo and pick an unimplemented feature to work on. The code is structured with clear sections for different areas of functionality.

## License

MIT

## Acknowledgments

- Blackmagic Design for DaVinci Resolve and its API
- The MCP protocol team for enabling AI assistant integration

## Project Structure

After cleanup, the project has the following structure:

- `resolve_mcp_server.py` - The main MCP server implementation
- `run-now.sh` - Quick start script that handles setup and runs the server
- `setup.sh` - Complete setup script for installation
- `check-resolve-ready.sh` - Pre-launch check to verify DaVinci Resolve is ready
- `start-server.sh` - Script to start the server
- `run-server.sh` - Simplified script to run the server directly

**Key Directories:**
- `src/` - Source code and modules
- `assets/` - Project assets and resources
- `logs/` - Log files directory
- `scripts/` - Helper scripts

When developing, it's recommended to use `./run-now.sh` which sets up the environment and launches the server in one step. 