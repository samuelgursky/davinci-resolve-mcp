# DaVinci Resolve MCP Integration - Installation Guide

This guide provides step-by-step instructions for installing and configuring the DaVinci Resolve MCP integration for use with Cursor AI. The integration allows Cursor AI to control DaVinci Resolve through its API.

## Prerequisites

- DaVinci Resolve installed (Free or Studio version)
- Python 3.9+ installed
- Cursor AI installed

## Installation Steps

### 1. New One-Step Installation (Recommended)

We now provide a unified installation script that handles everything automatically, with robust error detection and configuration:

**macOS/Linux:**
```bash
# Make sure DaVinci Resolve is running, then:
./install.sh
```

**Windows:**
```bash
# Make sure DaVinci Resolve is running, then:
install.bat
```

This new installation script will:
- Detect the correct installation path automatically
- Create the Python virtual environment
- Install all required dependencies
- Set up environment variables
- Generate the correct Cursor MCP configuration
- Verify the installation
- Optionally start the server if everything is correct

### 2. Quick Start (Alternative)

The earlier quick start scripts are still available:

**macOS/Linux:**
```bash
# Make sure DaVinci Resolve is already running before executing this script
./run-now.sh
```

**Windows:**
```bash
# Make sure DaVinci Resolve is already running before executing this script
run-now.bat
```

**Windows (PowerShell pre-launch check):**
```powershell
.\dev.ps1
```

### Optional: VAD-Based Audio Ducking

If you want VAD-driven ducking (music dips only where speech occurs), use:

```bash
# 1) Detect speech segments (VAD)
python -m src.autonomous.cli vad --audio path/to/voice.wav

# 2) Duck music during speech segments
python -m src.autonomous.cli duck-vad --music path/to/music.wav --vad work/audio/vad.json

# 3) Or run the full pipeline with VAD ducking
python -m src.autonomous.cli run-all --music path/to/music.wav --vad work/audio/vad.json
```

Requires `ffmpeg` on your PATH and the optional VAD dependency (`webrtcvad-wheels`).

### 3. Manual Setup (Advanced)

If you prefer to set up the integration manually or if you encounter issues with the automatic methods:

#### Step 3.1: Create a Python Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

#### Step 3.2: Install Dependencies

```bash
# Install all required dependencies from requirements.txt
pip install -r requirements.txt
```

Alternatively, you can install just the MCP SDK:

```bash
pip install "mcp[cli]"
```

#### Step 3.3: Set Environment Variables

On macOS/Linux, add the following to your `~/.zshrc` or `~/.bashrc`:

```bash
export RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
export RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
export PYTHONPATH="$PYTHONPATH:$RESOLVE_SCRIPT_API/Modules/"
```

On Windows, set these environment variables in PowerShell or through System Properties:

```powershell
$env:RESOLVE_SCRIPT_API = "C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting"
$env:RESOLVE_SCRIPT_LIB = "C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"
$env:PYTHONPATH = "$env:PYTHONPATH;$env:RESOLVE_SCRIPT_API\Modules\"
```

#### Step 3.4: Configure Cursor

The installation creates two MCP configuration files:

**System-level configuration**:
- macOS/Linux: `~/.cursor/mcp/config.json`
- Windows: `%APPDATA%\Cursor\mcp\config.json`

**Project-level configuration**:
- In the project root: `.cursor/mcp.json`

Both configurations use absolute paths to the Python interpreter and script. This ensures Cursor can find the correct files regardless of how the project is opened.

#### Sample configuration:
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

The installation scripts automatically create both configuration files with the correct absolute paths for your system. If you need to move the project to a new location, you'll need to run the installation script again to update the paths.

### 4. Start the Integration

For a more controlled setup with additional options:

**macOS/Linux:**
```bash
# From the scripts directory
cd scripts
./mcp_resolve-cursor_start
```

### 5. Verify Your Installation

After completing the installation steps, you can verify that everything is set up correctly by running:

**macOS/Linux:**
```bash
./scripts/verify-installation.sh
```

**Windows:**
```bash
scripts\verify-installation.bat
```

This verification script checks:
- Python virtual environment setup
- MCP SDK installation
- DaVinci Resolve running status
- Cursor configuration
- Environment variables
- Server script presence

If all checks pass, you're ready to use the integration. If any checks fail, the script will provide guidance on how to fix the issues.

## Troubleshooting

### DaVinci Resolve Detection Issues

If the script cannot detect that DaVinci Resolve is running:

1. Make sure DaVinci Resolve is actually running before executing scripts
2. The detection method has been updated to use `ps -ef | grep -i "[D]aVinci Resolve"` instead of `pgrep`, which provides more reliable detection

### Path Resolution Issues

If you see errors related to file paths:

1. The scripts now use the directory where they're located as the reference point
2. Check that the `resolve_mcp_server.py` file exists in the expected location
3. Verify that your Cursor MCP configuration points to the correct paths
4. If you move the project to a new location, you'll need to run the installation script again to update the paths

### Environment Variables

If you encounter Python import errors:

1. Verify that the environment variables are correctly set
2. The paths may differ depending on your DaVinci Resolve installation location
3. You can check the log file at `scripts/cursor_resolve_server.log` for details

### Cursor Configuration Issues

If Cursor isn't connecting to the MCP server:

1. Check both the system-level and project-level configuration files
2. Ensure the paths in the configurations match your actual installation
3. The absolute paths must be correct - verify they point to your actual installation location
4. After moving the project, run `./install.sh` or `install.bat` again to update the paths

## Configuration Reference

The integration creates two configuration files:

1. **System-level config** (for global use): `~/.cursor/mcp/config.json` (macOS/Linux) or `%APPDATA%\Cursor\mcp\config.json` (Windows)
2. **Project-level config** (for specific project use): `.cursor/mcp.json` in the project root

Both configurations have the same structure:

```json
{
  "mcpServers": {
    "davinci-resolve": {
      "name": "DaVinci Resolve MCP",
      "command": "<absolute-path-to-python-interpreter>",
      "args": ["<absolute-path-to-resolve_mcp_server.py>"]
    }
  }
}
```

## Support

If you encounter any issues not covered in this guide, please file an issue on the GitHub repository. 
