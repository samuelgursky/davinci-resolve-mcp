# DaVinci Resolve MCP Extension

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Lint](https://github.com/samuelgursky/davinci-resolve-mcp/actions/workflows/python-lint.yml/badge.svg)](https://github.com/samuelgursky/davinci-resolve-mcp/actions/workflows/python-lint.yml)
[![Version](https://img.shields.io/badge/version-1.1.0-blue)](https://github.com/samuelgursky/davinci-resolve-mcp)

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

## Timeline Functions

### Timeline Markers

The MCP framework provides several functions for working with timeline markers:

- `mcp_get_timeline_markers()` - Get all markers in the current timeline
- `mcp_add_timeline_marker(frame, color, name, note, duration, custom_data)` - Add a new marker
- `mcp_update_marker(frame, color, name, note, duration, custom_data)` - Update an existing marker
- `mcp_delete_marker(frame)` - Delete a marker at a specific frame
- `mcp_delete_markers_by_color(color)` - Delete all markers of a specific color

Example usage:

```python
# Get all markers in the timeline
markers = client.call("mcp_get_timeline_markers")

# Add a marker at frame 1000 with color "Blue"
client.call("mcp_add_timeline_marker", frame=1000, color="Blue", name="My Marker")

# Update a marker
client.call("mcp_update_marker", frame=1000, color="Red", note="Updated note")

# Delete a marker
client.call("mcp_delete_marker", frame=1000)
```

For a complete example, see `examples/timeline_markers.py`.

## Media Pool Functions

### Advanced Folder Navigation

The MCP framework provides functions for advanced folder navigation in the Media Pool:

- `mcp_get_folder_hierarchy(include_clips)` - Get the complete folder hierarchy of the media pool
- `mcp_get_folder_by_path(path, include_clips, include_subfolders)` - Get a folder by path (e.g., "Footage/Scenes/Scene1")
- `mcp_create_folder_path(path)` - Create a folder path, creating any missing folders in between
- `mcp_set_current_folder(path)` - Set the current working folder in the media pool
- `mcp_get_current_folder()` - Get information about the current working folder

Example usage:

```python
# Get complete folder structure
hierarchy = client.execute_command("mcp_get_folder_hierarchy", {
    "include_clips": True  # Optional: include clips in hierarchy
})

# Get a specific folder by path
folder = client.execute_command("mcp_get_folder_by_path", {
    "path": "Footage/Interviews",
    "include_clips": True,             # Optional
    "include_subfolders": True         # Optional
})

# Create a complex folder path
client.execute_command("mcp_create_folder_path", {
    "path": "Footage/Scenes/Scene5/Takes"
})

# Set the current working folder
client.execute_command("mcp_set_current_folder", {
    "path": "Footage/Scenes/Scene5"
})
```

### Bulk Operations

These functions allow you to perform operations on multiple clips at once:

- `mcp_move_clips_between_folders(source_path, destination_path, clip_names)` - Move clips between folders
- `mcp_bulk_set_clip_property(folder_path, property_name, property_value, clip_names)` - Set a property on multiple clips
- `mcp_import_files_to_folder(file_paths, folder_path)` - Import files to a specific folder

Example usage:

```python
# Move all clips from one folder to another
client.execute_command("mcp_move_clips_between_folders", {
    "source_path": "Footage/B-Roll",
    "destination_path": "Footage/Archive"
})

# Move only specific clips
client.execute_command("mcp_move_clips_between_folders", {
    "source_path": "Footage/B-Roll",
    "destination_path": "Footage/Selected",
    "clip_names": ["Clip1", "Clip2", "Clip3"]
})

# Set a keyword on all clips in a folder
client.execute_command("mcp_bulk_set_clip_property", {
    "folder_path": "Footage/Interviews",
    "property_name": "Keywords",
    "property_value": "interview,documentary,completed"
})

# Import files to a specific folder
client.execute_command("mcp_import_files_to_folder", {
    "file_paths": ["/path/to/video1.mp4", "/path/to/video2.mp4"],
    "folder_path": "Footage/B-Roll"
})
```

### Smart Bins

Functions for working with Smart Bins in DaVinci Resolve:

- `mcp_create_smart_bin(name, search_criteria)` - Create a smart bin with specific search criteria
- `mcp_get_smart_bins()` - Get a list of all smart bins in the project
- `mcp_delete_smart_bin(name)` - Delete a smart bin

Example usage:

```python
# Create a smart bin for 4K videos
client.execute_command("mcp_create_smart_bin", {
    "name": "4K Videos",
    "search_criteria": {
        "Resolution": "3840x2160",
        "Type": "Video"
    }
})

# Get all smart bins
smart_bins = client.execute_command("mcp_get_smart_bins")

# Delete a smart bin
client.execute_command("mcp_delete_smart_bin", {
    "name": "4K Videos"
})
```

For a complete example, see `examples/advanced_media_pool.py`.

## Color Correction Functions

The MCP framework provides powerful color grading capabilities through a set of functions for working with the DaVinci Resolve Color page:

### Node Management

Functions for creating and managing nodes in the color page:

- `mcp_get_current_node_index()` - Get the index of the currently selected node
- `mcp_set_current_node_index(index)` - Set the current node by index
- `mcp_add_serial_node()` - Add a new serial node after the current node
- `mcp_add_parallel_node()` - Add a new parallel node to the current node
- `mcp_add_layer_node()` - Add a new layer node to the current node
- `mcp_delete_current_node()` - Delete the currently selected node
- `mcp_reset_current_node()` - Reset all grades on the current node
- `mcp_get_node_list()` - Get a list of all nodes in the current clip's node graph

Example usage:

```python
# Get all nodes in the current clip
nodes = client.execute("mcp_get_node_list", {})

# Add a new serial node
result = client.execute("mcp_add_serial_node", {})
node_index = result["node_index"]

# Select a specific node
client.execute("mcp_set_current_node_index", {"index": 2})

# Reset the current node
client.execute("mcp_reset_current_node", {})
```

### Primary Color Correction

Functions for applying and retrieving primary color correction settings:

- `mcp_get_primary_correction()` - Get the primary correction parameters of the current node
- `mcp_set_primary_correction(lift, gamma, gain, contrast, saturation)` - Set primary correction values
- `mcp_get_node_label()` - Get the label of the current node
- `mcp_set_node_label(label)` - Set the label of the current node
- `mcp_get_node_color()` - Get the tile color of the current node
- `mcp_set_node_color(red, green, blue, alpha)` - Set the tile color of the current node

Example usage:

```python
# Get current color correction settings
correction = client.execute("mcp_get_primary_correction", {})

# Apply a warm look
client.execute("mcp_set_primary_correction", {
    "lift": {"red": 0.02, "green": 0.01, "blue": -0.02, "master": 0.0},
    "gamma": {"red": 0.05, "green": 0.02, "blue": -0.03, "master": 0.02},
    "gain": {"red": 1.1, "green": 1.05, "blue": 0.9, "master": 1.05},
    "saturation": 1.1
})

# Label and colorize the node
client.execute("mcp_set_node_label", {"label": "Warm Look"})
client.execute("mcp_set_node_color", {
    "red": 0.8, "green": 0.6, "blue": 0.2, "alpha": 1.0
})
```

### LUT Operations

Functions for working with LUTs (Look-Up Tables):

- `mcp_import_lut(path)` - Import a LUT file
- `mcp_apply_lut_to_current_node(path)` - Apply a LUT to the current node

Example usage:

```python
# Import and apply a LUT
lut_path = "/path/to/my_lut.cube"
client.execute("mcp_import_lut", {"path": lut_path})
client.execute("mcp_apply_lut_to_current_node", {"path": lut_path})
```

For a complete example, see `examples/color_correction.py`.

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
- [Comprehensive Documentation](docs/DOCUMENTATION.md): Detailed usage instructions for all functions
- [Contributing Guidelines](CONTRIBUTING.md): Guidelines for contributing to the project
- [Changelog](CHANGELOG.md): History of changes and new features
- [Next Steps](docs/NEXT_STEPS.md): Planned future development
- [Project Settings Limitations](docs/project_settings_limitations.md): Details on project settings limitations

## Testing

```
python -m tests.test_timeline_functions
python -m tests.test_project_settings
python -m tests.test_playback_functions
```

## License

This project is licensed under the MIT License. 