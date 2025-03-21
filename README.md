# DaVinci Resolve MCP Extension

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Lint](https://github.com/samuelgursky/davinci-resolve-mcp/actions/workflows/python-lint.yml/badge.svg)](https://github.com/samuelgursky/davinci-resolve-mcp/actions/workflows/python-lint.yml)
[![Version](https://img.shields.io/badge/version-1.0.0-blue)](https://github.com/samuelgursky/davinci-resolve-mcp)

A Python extension that enhances the DaVinci Resolve API integration with Claude through the MCP (Multi-Call Protocol).

## Quick Start

### Requirements

- DaVinci Resolve Studio (Free version has limited scripting support)
- Python 3.6+ (64-bit)

### Environment Setup

**Mac OS X:**
```
RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
PYTHONPATH="$PYTHONPATH:$RESOLVE_SCRIPT_API/Modules/"
```

**Windows:**
```
RESOLVE_SCRIPT_API="%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting"
RESOLVE_SCRIPT_LIB="C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"
PYTHONPATH="%PYTHONPATH%;%RESOLVE_SCRIPT_API%\Modules\"
```

**Linux:**
```
RESOLVE_SCRIPT_API=`/opt/resolve/Developer/Scripting`
RESOLVE_SCRIPT_LIB=`/opt/resolve/libs/Fusion/fusionscript.so`
PYTHONPATH="$PYTHONPATH:$RESOLVE_SCRIPT_API/Modules/"
```

### Installation

```
pip install -e .
```

## Core Features

- **Project Management**: Get project info, list projects, switch projects
- **Timeline Operations**: Create/delete timelines, control playback, manage clips
- **Media Management**: Browse media pool, import files, organize content
- **Project Settings**: Get/set project and timeline settings
- **Rendering**: Manage render jobs and monitor status

## Basic Usage

```python
# Get current project information
response = mcp_get_project_info()

# Create a new timeline
response = mcp_create_timeline("My New Timeline", {"width": "1920", "height": "1080"}, 24.0)

# Add a clip to the timeline
response = mcp_add_clip_to_timeline("My Clip", 1, "video", 0)
```

## Project Structure

- `src/`: Core implementation files
- `tests/`: Test scripts for verification
- `examples/`: Example usage scripts
- `docs/`: Documentation files
- `scripts/`: Utility scripts for project maintenance

## Detailed Documentation

For complete documentation on all available functions, implementation status, and limitations, see:

- [Master Feature Tracking Document](MASTER_DAVINCI_RESOLVE_MCP.md): Comprehensive overview of all features
- [Project Settings Limitations](docs/project_settings_limitations.md): Details on project settings limitations

## Testing

```
python -m tests.test_timeline_functions
python -m tests.test_project_settings
python -m tests.test_playback_functions
```

## License

This project is licensed under the MIT License. 