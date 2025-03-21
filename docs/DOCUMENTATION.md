# DaVinci Resolve MCP Framework Documentation

This document provides comprehensive documentation for the DaVinci Resolve Media Control Protocol (MCP) framework.

## Table of Contents

- [Installation](#installation)
- [Getting Started](#getting-started)
- [Core Functionality](#core-functionality)
- [Timeline Functions](#timeline-functions)
- [Media Pool Functions](#media-pool-functions)
- [Color Correction Functions](#color-correction-functions)
- [Advanced Usage](#advanced-usage)
- [Troubleshooting](#troubleshooting)
- [Version Compatibility](#version-compatibility)

## Installation

```bash
pip install davinci-resolve-mcp
```

## Getting Started

### Server Setup

Start the MCP server to enable communication with DaVinci Resolve:

```python
from mcp.server import MCPServer

server = MCPServer()
server.start()
```

### Client Connection

Connect to the MCP server from your client application:

```python
from mcp.client import MCPClient

client = MCPClient()
client.connect()

# Execute commands
project_info = client.execute("mcp_get_project_info", {})
print(project_info)

# Always disconnect when done
client.disconnect()
```

## Core Functionality

### Project Information

```python
# Get project information
project_info = client.execute("mcp_get_project_info", {})

# Get current timeline name
timeline_name = client.execute("mcp_get_current_timeline_name", {})

# Get detailed timeline information
timeline_info = client.execute("mcp_get_timeline_info", {})

# List all project timelines
timelines = client.execute("mcp_get_project_timelines", {})
```

### Playback Control

```python
# Play
client.execute("mcp_control_playback", {"command": "play"})

# Pause
client.execute("mcp_control_playback", {"command": "pause"})

# Stop
client.execute("mcp_control_playback", {"command": "stop"})

# Jump to specific frame
client.execute("mcp_control_playback", {"command": "to_frame", "frame": 1000})
```

## Timeline Functions

### Clip Operations

```python
# Get timeline clip names
clips = client.execute("mcp_get_timeline_clip_names", {})

# Get clip details (video track 1, first clip)
clip_details = client.execute("mcp_get_clip_details", {
    "track_type": "video",
    "track_index": 1,
    "clip_index": 0
})

# Get selected clips
selected_clips = client.execute("mcp_get_selected_clips", {})
```

### Timeline Markers

```python
# Get all timeline markers
markers = client.execute("mcp_get_timeline_markers", {})

# Add a marker
client.execute("mcp_add_timeline_marker", {
    "frame": 1000,
    "color": "Blue", 
    "name": "Scene 1 Start",
    "note": "Beginning of first scene",
    "duration": 0
})

# Update a marker
client.execute("mcp_update_marker", {
    "frame": 1000,
    "color": "Green",
    "name": "Scene 1 Start - Updated",
    "note": "Updated note"
})

# Delete a marker
client.execute("mcp_delete_marker", {"frame": 1000})

# Delete markers by color
client.execute("mcp_delete_markers_by_color", {"color": "Blue"})
```

## Media Pool Functions

### Basic Media Pool Operations

```python
# Get media pool items
items = client.execute("mcp_get_media_pool_items", {})

# Get media pool structure
structure = client.execute("mcp_get_media_pool_structure", {})
```

### Advanced Folder Navigation

```python
# Get folder hierarchy
hierarchy = client.execute("mcp_get_folder_hierarchy", {"include_clips": True})

# Get specific folder by path
folder = client.execute("mcp_get_folder_by_path", {
    "path": "Footage/B-Roll",
    "include_clips": True,
    "include_subfolders": True
})

# Create folder path
client.execute("mcp_create_folder_path", {"path": "Footage/Interviews/Subject1"})

# Set current folder
client.execute("mcp_set_current_folder", {"path": "Footage/B-Roll"})

# Get current folder
current_folder = client.execute("mcp_get_current_folder", {})
```

### Bulk Operations

```python
# Move clips between folders
client.execute("mcp_move_clips_between_folders", {
    "source_path": "Footage/B-Roll",
    "destination_path": "Footage/Selected",
    "clip_names": ["clip1.mp4", "clip2.mp4"]
})

# Set properties on multiple clips
client.execute("mcp_bulk_set_clip_property", {
    "folder_path": "Footage/B-Roll",
    "property_name": "Keywords",
    "property_value": "outdoor,daytime",
    "clip_names": ["clip1.mp4", "clip2.mp4"]
})

# Import files to folder
client.execute("mcp_import_files_to_folder", {
    "file_paths": ["/path/to/file1.mp4", "/path/to/file2.mp4"],
    "folder_path": "Footage/New Imports"
})
```

### Smart Bins

```python
# Create smart bin
client.execute("mcp_create_smart_bin", {
    "name": "HD Videos",
    "search_criteria": {
        "Resolution": "1920x1080",
        "Keywords": "interview"
    }
})

# Get all smart bins
smart_bins = client.execute("mcp_get_smart_bins", {})

# Delete smart bin
client.execute("mcp_delete_smart_bin", {"name": "HD Videos"})
```

## Color Correction Functions

### Node Management

```python
# Get current node index
current_node = client.execute("mcp_get_current_node_index", {})

# Set current node index
client.execute("mcp_set_current_node_index", {"index": 2})

# Add a serial node
new_node = client.execute("mcp_add_serial_node", {})

# Add a parallel node
new_parallel = client.execute("mcp_add_parallel_node", {})

# Add a layer node
new_layer = client.execute("mcp_add_layer_node", {})

# Delete current node
client.execute("mcp_delete_current_node", {})

# Reset current node
client.execute("mcp_reset_current_node", {})

# Get node list
nodes = client.execute("mcp_get_node_list", {})
```

### Primary Color Correction

```python
# Get current primary correction
correction = client.execute("mcp_get_primary_correction", {})

# Set primary correction
client.execute("mcp_set_primary_correction", {
    "lift": {"red": 0.02, "green": 0.01, "blue": -0.02, "master": 0.0},
    "gamma": {"red": 0.05, "green": 0.02, "blue": -0.03, "master": 0.02},
    "gain": {"red": 1.1, "green": 1.05, "blue": 0.9, "master": 1.05},
    "saturation": 1.1
})

# Get node label
label = client.execute("mcp_get_node_label", {})

# Set node label
client.execute("mcp_set_node_label", {"label": "Warm Look"})

# Get node color
color = client.execute("mcp_get_node_color", {})

# Set node color
client.execute("mcp_set_node_color", {
    "red": 0.8, "green": 0.6, "blue": 0.2, "alpha": 1.0
})
```

### LUT Operations

```python
# Import a LUT
client.execute("mcp_import_lut", {"path": "/path/to/my_lut.cube"})

# Apply LUT to current node
client.execute("mcp_apply_lut_to_current_node", {"path": "/path/to/my_lut.cube"})
```

## Advanced Usage

### Error Handling

```python
try:
    result = client.execute("mcp_get_timeline_info", {})
except Exception as e:
    print(f"Error: {e}")
    # Handle the error
```

### Asynchronous Operations

```python
# Execute an operation asynchronously
future = client.execute_async("mcp_get_media_pool_structure", {})

# Do other operations while it's processing

# Get the result when needed
result = future.result()
```

## Troubleshooting

### Common Issues

1. **Connection Refused**
   - Ensure DaVinci Resolve is running
   - Check if the server is started with the correct port
   - Verify firewall settings

2. **Function Not Found**
   - Verify the function name is correct
   - Check if the function is registered in the server
   - Ensure you're using a compatible DaVinci Resolve version

3. **Parameter Errors**
   - Double-check parameter names and types
   - Verify that all required parameters are provided

### Debugging

Enable debug logging to get more detailed information:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Then start your server or client
```

## Version Compatibility

| Feature Category | Min DaVinci Resolve Version | Notes |
|------------------|----------------------------|-------|
| Core Functions | 17.0+ | Basic functionality works on all supported versions |
| Timeline Markers | 17.0+ | Marker colors may vary by version |
| Media Pool Advanced | 17.1+ | Smart bins require 17.1+ |
| Color Correction | 17.0+ | Full node features may need 17.4+ |

For specific function compatibility, refer to the function tables in the MASTER_DAVINCI_RESOLVE_MCP.md file. 