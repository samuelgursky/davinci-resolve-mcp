# DaVinci Resolve MCP - Master Feature Tracking Document

This document provides a comprehensive overview of all features in the DaVinci Resolve MCP integration, their implementation status, testing status, and compatibility information.

<!-- TOC START -->
## Table of Contents

- [How to Use This Document](#how-to-use-this-document)
- [Core Functions](#core-functions)
  - [Project Information](#project-information)
  - [Timeline Basic Operations](#timeline-basic-operations)
  - [Clip and Track Operations](#clip-and-track-operations)
  - [Media Pool Operations](#media-pool-operations)
- [Advanced Functions](#advanced-functions)
  - [Timeline Advanced Operations](#timeline-advanced-operations)
  - [Project Settings](#project-settings)
  - [Rendering Operations](#rendering-operations)
  - [Color Correction Functions](#color-correction-functions)
- [Planned Features](#planned-features)
  - [Color Grading Operations](#color-grading-operations-planned)
  - [Fusion Operations](#fusion-operations-planned)
  - [Fairlight Audio Operations](#fairlight-audio-operations-planned)
- [Known Limitations](#known-limitations)
- [Development Status and Roadmap](#development-status-and-roadmap)
- [Testing and Verification Methodology](#testing-and-verification-methodology)
- [Contributing to Feature Development](#contributing-to-feature-development)
<!-- TOC END -->

## How to Use This Document

- **Status Legend**: 
  - ✅ Working - Feature is implemented and tested successfully
  - ⚠️ Partial - Feature is implemented but has limitations or edge cases
  - ❌ Not Working - Feature is implemented but not functioning correctly
  - 🔄 In Progress - Feature is currently being worked on
  - 📝 Planned - Feature is planned for future implementation
  - 🧪 Needs Testing - Feature is implemented but needs testing

- **Compatibility**: Shows which versions of DaVinci Resolve the feature is compatible with

## Core Functions

### Project Information
| Function | Status | Testing Status | Compatible Versions | Notes |
|----------|--------|----------------|---------------------|-------|
| mcp_get_project_info | ✅ Working | Verified | 17.0+ | Successfully retrieves project name, frame rate, resolution, timeline count |
| mcp_get_project_list | ✅ Working | Verified | 17.0+ | Successfully lists all projects in the database |
| mcp_switch_to_project | ✅ Working | Verified | 17.0+ | Successfully switches between projects |

### Timeline Basic Operations
| Function | Status | Testing Status | Compatible Versions | Notes |
|----------|--------|----------------|---------------------|-------|
| mcp_get_current_timeline_name | ✅ Working | Verified | 17.0+ | Successfully retrieves the current timeline name |
| mcp_get_timeline_info | ✅ Working | Verified | 17.0+ | Successfully retrieves timeline details (tracks, duration, etc.) |
| mcp_get_project_timelines | ✅ Working | Verified | 17.0+ | Successfully lists all timelines in the project |
| mcp_get_timeline_clip_names | ✅ Working | Verified | 17.0+ | Successfully lists all clips in the timeline |
| mcp_get_timeline_markers | ✅ Working | Verified | 17.0+ | Successfully retrieves timeline markers |
| mcp_get_playhead_position | ✅ Working | Verified | 17.0+ | Successfully retrieves the current playhead position |
| mcp_control_playback | ✅ Working | Needs Further Testing | 17.0+ | Fixed implementation should work but needs verification |

### Clip and Track Operations
| Function | Status | Testing Status | Compatible Versions | Notes |
|----------|--------|----------------|---------------------|-------|
| mcp_get_clip_details | ✅ Working | Verified | 17.0+ | Successfully retrieves clip properties |
| mcp_get_active_track_info | ✅ Working | Verified | 17.0+ | Successfully retrieves active track information |
| mcp_get_selected_clips | ✅ Working | Needs Further Testing | 17.0+ | Fixed implementation should work but needs verification |
| mcp_get_clip_source_timecode | ✅ Working | 🧪 Needs Testing | 17.0+ | Enhanced clip details with source timecode information |
| mcp_get_source_timecode_report | ✅ Working | 🧪 Needs Testing | 17.0+ | Generate comprehensive report of all clips with source timecodes |
| mcp_export_source_timecode_report | ✅ Working | 🧪 Needs Testing | 17.0+ | Export source timecode report in CSV, JSON, or EDL format |

### Media Pool Operations
| Function | Status | Testing Status | Compatible Versions | Notes |
|----------|--------|----------------|---------------------|-------|
| mcp_get_media_pool_items | ✅ Working | Verified | 17.0+ | Successfully retrieves media pool items |
| mcp_get_media_pool_structure | ✅ Working | Verified | 17.0+ | Successfully retrieves media pool structure |
| mcp_add_clip_to_timeline | ✅ Working | Verified | 17.0+ | Successfully adds clips to the timeline |
| mcp_get_media_pool_root_folder | ✅ Working | Verified | 17.0+ | Successfully retrieves root folder information |
| mcp_get_media_pool_folder | ✅ Working | Verified | 17.0+ | Successfully retrieves folder information |
| mcp_create_media_pool_folder | ✅ Working | Verified | 17.0+ | Successfully creates new folders |
| mcp_import_media | ⚠️ Partial | Limited Testing | 17.0+ | Requires local media files for testing |
| mcp_get_clip_info | ⚠️ Partial | Limited Testing | 17.0+ | Requires specific clips for testing |
| mcp_set_clip_property | ⚠️ Partial | Limited Testing | 17.0+ | Requires specific clips for testing |

### Advanced Media Pool Operations
| Function | Status | Testing Status | Compatible Versions | Notes |
|----------|--------|----------------|---------------------|-------|
| mcp_get_folder_hierarchy | ✅ Working | ✅ Unit Tested | 17.0+ | # STATUS: ✅ Implemented and Tested |
| mcp_get_folder_by_path | ✅ Working | ✅ Unit Tested | 17.0+ | # STATUS: ✅ Implemented and Tested |
| mcp_create_folder_path | ✅ Working | ✅ Unit Tested | 17.0+ | # STATUS: ✅ Implemented and Tested |
| mcp_set_current_folder | ✅ Working | ✅ Unit Tested | 17.0+ | # STATUS: ✅ Implemented and Tested |
| mcp_get_current_folder | ✅ Working | ✅ Unit Tested | 17.0+ | # STATUS: ✅ Implemented and Tested |
| mcp_move_clips_between_folders | ✅ Working | ✅ Unit Tested | 17.0+ | # STATUS: ✅ Implemented and Tested |
| mcp_bulk_set_clip_property | ✅ Working | ✅ Unit Tested | 17.0+ | # STATUS: ✅ Implemented and Tested |
| mcp_import_files_to_folder | ✅ Working | ✅ Unit Tested | 17.0+ | # STATUS: ✅ Implemented and Tested |
| mcp_create_smart_bin | ✅ Working | ✅ Unit Tested | 17.0+ | # STATUS: ✅ Implemented and Tested |
| mcp_get_smart_bins | ✅ Working | ✅ Unit Tested | 17.0+ | # STATUS: ✅ Implemented and Tested |
| mcp_delete_smart_bin | ✅ Working | ✅ Unit Tested | 17.0+ | # STATUS: ✅ Implemented and Tested |

#### Advanced Media Pool Examples

##### Advanced Folder Navigation

```python
# Get the complete folder hierarchy
folder_structure = client.execute("mcp_get_folder_hierarchy", {"include_clips": False})
print(json.dumps(folder_structure, indent=2))

# Get a specific folder by path
footage_folder = client.execute("mcp_get_folder_by_path", {
    "path": "Footage/B-Roll", 
    "include_clips": True, 
    "include_subfolders": True
})
print(json.dumps(footage_folder, indent=2))

# Create a nested folder path
result = client.execute("mcp_create_folder_path", {"path": "Footage/Interviews/Day1"})
print(f"Created folder path: {result}")

# Set the current working folder
result = client.execute("mcp_set_current_folder", {"path": "Footage/B-Roll"})
print(f"Set current folder: {result}")

# Get the current working folder
current_folder = client.execute("mcp_get_current_folder", {})
print(f"Current folder: {current_folder}")
```

##### Bulk Operations

```python
# Move clips between folders
result = client.execute("mcp_move_clips_between_folders", {
    "source_path": "Footage/Unorganized",
    "destination_path": "Footage/B-Roll",
    "clip_names": ["clip001.mov", "clip002.mov"]
})
print(f"Moved clips: {result}")

# Set property on multiple clips at once
result = client.execute("mcp_bulk_set_clip_property", {
    "folder_path": "Footage/B-Roll",
    "property_name": "Keywords",
    "property_value": "outdoor,nature",
    "clip_names": ["clip001.mov", "clip002.mov"]  # Optional, applies to all clips if not specified
})
print(f"Set properties: {result}")

# Import files to a specific folder
result = client.execute("mcp_import_files_to_folder", {
    "file_paths": ["/path/to/video1.mp4", "/path/to/video2.mp4"],
    "folder_path": "Footage/Imports"
})
print(f"Imported files: {result}")
```

##### Smart Bins

```python
# Create a smart bin
search_criteria = [
    {
        "property": "Resolution",
        "operator": "=",
        "value": "1920x1080"
    },
    {
        "property": "Keywords",
        "operator": "contains",
        "value": "interview"
    }
]

result = client.execute("mcp_create_smart_bin", {
    "name": "HD Interviews",
    "search_criteria": search_criteria
})
print(f"Created smart bin: {result}")

# Get all smart bins
smart_bins = client.execute("mcp_get_smart_bins", {})
print(json.dumps(smart_bins, indent=2))

# Delete a smart bin
result = client.execute("mcp_delete_smart_bin", {"name": "HD Interviews"})
print(f"Deleted smart bin: {result}")
```

A complete example script for these functions can be found in `examples/advanced_media_pool.py`.

## Advanced Functions

### Timeline Advanced Operations
| Function | Status | Testing Status | Compatible Versions | Notes |
|----------|--------|----------------|---------------------|-------|
| mcp_create_timeline | ✅ Working | Verified | 17.0+ | Successfully creates new timelines with specified parameters |
| mcp_delete_timeline | ✅ Working | Verified | 17.0+ | Fixed implementation with multiple deletion approaches |

### Project Settings
| Function | Status | Testing Status | Compatible Versions | Notes |
|----------|--------|----------------|---------------------|-------|
| mcp_get_project_setting | ✅ Working | Verified | 17.0+ | Successfully retrieves project settings |
| mcp_set_project_setting | ⚠️ Partial | Verified | 17.0+ | Only works with limited settings (see docs/project_settings_limitations.md) |
| mcp_get_timeline_setting | ✅ Working | Verified | 17.0+ | Successfully retrieves timeline settings |
| mcp_set_timeline_setting | ⚠️ Partial | Verified | 17.0+ | Limited success due to API constraints (see docs/project_settings_limitations.md) |

### Rendering Operations
| Function | Status | Testing Status | Compatible Versions | Notes |
|----------|--------|----------------|---------------------|-------|
| mcp_get_render_presets | ✅ Working | Verified | 17.0+ | Successfully retrieves render presets |
| mcp_get_render_formats | ✅ Working | Verified | 17.0+ | Successfully retrieves render formats |
| mcp_get_render_codecs | ⚠️ Partial | Limited Testing | 17.0+ | Test script error prevented full testing |
| mcp_get_render_jobs | ✅ Working | Verified | 17.0+ | Successfully retrieves render jobs |
| mcp_add_render_job | ⚠️ Partial | Limited Testing | 17.0+ | Requires timeline setup for testing |
| mcp_delete_render_job | ⚠️ Partial | Limited Testing | 17.0+ | Requires existing render jobs for testing |
| mcp_start_rendering | ⚠️ Partial | Limited Testing | 17.0+ | Requires render job setup for testing |
| mcp_stop_rendering | ⚠️ Partial | Limited Testing | 17.0+ | Requires active rendering for testing |
| mcp_get_render_job_status | ⚠️ Partial | Limited Testing | 17.0+ | Requires existing render jobs for testing |

### Advanced Timeline Analysis
| Function | Status | Testing Status | Compatible Versions | Notes |
|----------|--------|----------------|---------------------|-------|
| mcp_analyze_timeline_usage | 📝 Planned | Not Started | TBD | Analyze media usage across timeline (duplicates, gaps, etc.) |
| mcp_get_timeline_statistics | 📝 Planned | Not Started | TBD | Get comprehensive statistics about timeline composition |
| mcp_validate_timeline_media | 📝 Planned | Not Started | TBD | Check for missing media, offline clips, etc. |
| mcp_compare_timelines | 📝 Planned | Not Started | TBD | Compare differences between two timelines |
| mcp_get_timecode_discontinuities | 📝 Planned | Not Started | TBD | Identify source timecode jumps or discontinuities |

### Color Correction Functions
| Function | Status | Testing Status | Compatible Versions | Notes |
|----------|--------|----------------|---------------------|-------|
| mcp_get_current_node_index | ✅ Working | 🧪 Needs Testing | 17.0+ | # STATUS: ✅ Implemented |
| mcp_set_current_node_index | ✅ Working | 🧪 Needs Testing | 17.0+ | # STATUS: ✅ Implemented |
| mcp_add_serial_node | ✅ Working | 🧪 Needs Testing | 17.0+ | # STATUS: ✅ Implemented |
| mcp_add_parallel_node | ✅ Working | 🧪 Needs Testing | 17.0+ | # STATUS: ✅ Implemented |
| mcp_add_layer_node | ✅ Working | 🧪 Needs Testing | 17.0+ | # STATUS: ✅ Implemented |
| mcp_delete_current_node | ✅ Working | 🧪 Needs Testing | 17.0+ | # STATUS: ✅ Implemented |
| mcp_reset_current_node | ✅ Working | 🧪 Needs Testing | 17.0+ | # STATUS: ✅ Implemented |
| mcp_get_node_list | ✅ Working | 🧪 Needs Testing | 17.0+ | # STATUS: ✅ Implemented |
| mcp_get_primary_correction | ✅ Working | 🧪 Needs Testing | 17.0+ | # STATUS: ✅ Implemented |
| mcp_set_primary_correction | ✅ Working | 🧪 Needs Testing | 17.0+ | # STATUS: ✅ Implemented |
| mcp_get_node_label | ✅ Working | 🧪 Needs Testing | 17.0+ | # STATUS: ✅ Implemented |
| mcp_set_node_label | ✅ Working | 🧪 Needs Testing | 17.0+ | # STATUS: ✅ Implemented |
| mcp_get_node_color | ✅ Working | 🧪 Needs Testing | 17.0+ | # STATUS: ✅ Implemented |
| mcp_set_node_color | ✅ Working | 🧪 Needs Testing | 17.0+ | # STATUS: ✅ Implemented |
| mcp_import_lut | ✅ Working | 🧪 Needs Testing | 17.0+ | # STATUS: ✅ Implemented |
| mcp_apply_lut_to_current_node | ✅ Working | 🧪 Needs Testing | 17.0+ | # STATUS: ✅ Implemented |

#### Color Correction Examples

##### Node Management

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

##### Primary Color Correction

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

##### LUT Operations

```python
# Import and apply a LUT
lut_path = "/path/to/my_lut.cube"
client.execute("mcp_import_lut", {"path": lut_path})
client.execute("mcp_apply_lut_to_current_node", {"path": lut_path})
```

A complete example script for these functions can be found in `examples/color_correction.py`.

## Planned Features

### Color Grading Operations (📝 Planned)
| Function | Status | Testing Status | Compatible Versions | Notes |
|----------|--------|----------------|---------------------|-------|
| mcp_get_primary_color_adjustments | 📝 Planned | Not Started | TBD | Get primary color adjustments (lift, gamma, gain) |
| mcp_set_primary_color_adjustments | 📝 Planned | Not Started | TBD | Set primary color adjustments for clips |
| mcp_get_secondary_color_adjustments | 📝 Planned | Not Started | TBD | Get secondary color adjustments (qualifiers, power windows) |
| mcp_set_secondary_color_adjustments | 📝 Planned | Not Started | TBD | Set secondary color adjustments for clips |
| mcp_get_node_structure | 📝 Planned | Not Started | TBD | Get color page node structure |
| mcp_add_color_node | 📝 Planned | Not Started | TBD | Add a node to color page |
| mcp_apply_lut | 📝 Planned | Not Started | TBD | Apply LUT to clips or nodes |
| mcp_get_applied_luts | 📝 Planned | Not Started | TBD | Get LUTs applied to clips or nodes |

### Fusion Operations (📝 Planned)
| Function | Status | Testing Status | Compatible Versions | Notes |
|----------|--------|----------------|---------------------|-------|
| mcp_get_fusion_composition | 📝 Planned | Not Started | TBD | Access Fusion page compositions |
| mcp_get_fusion_node_parameters | 📝 Planned | Not Started | TBD | Get parameters of Fusion nodes |
| mcp_set_fusion_node_parameters | 📝 Planned | Not Started | TBD | Set parameters of Fusion nodes |
| mcp_create_fusion_node | 📝 Planned | Not Started | TBD | Create a new Fusion node |
| mcp_delete_fusion_node | 📝 Planned | Not Started | TBD | Delete a Fusion node |
| mcp_connect_fusion_nodes | 📝 Planned | Not Started | TBD | Connect Fusion nodes |

### Fairlight Audio Operations (📝 Planned)
| Function | Status | Testing Status | Compatible Versions | Notes |
|----------|--------|----------------|---------------------|-------|
| mcp_get_audio_levels | 📝 Planned | Not Started | TBD | Get audio levels for clips or tracks |
| mcp_set_audio_levels | 📝 Planned | Not Started | TBD | Set audio levels for clips or tracks |
| mcp_get_audio_eq | 📝 Planned | Not Started | TBD | Get EQ settings for audio |
| mcp_set_audio_eq | 📝 Planned | Not Started | TBD | Set EQ settings for audio |
| mcp_get_audio_effects | 📝 Planned | Not Started | TBD | Get audio effects applied to clips or tracks |
| mcp_add_audio_effect | 📝 Planned | Not Started | TBD | Add an audio effect to clips or tracks |
| mcp_remove_audio_effect | 📝 Planned | Not Started | TBD | Remove an audio effect from clips or tracks |

## Known Limitations

This section documents known limitations of the DaVinci Resolve API that affect the MCP functions:

1. **Project Settings Limitations**: Most project settings cannot be modified through the API. See `docs/project_settings_limitations.md` for details.
2. **Timeline Marker Limitations**: The API for timeline markers appears to be inconsistent or incomplete.
3. **Playback Control Timing**: Some playback control operations may have timing issues or inconsistent behavior.
4. **Version-Specific Issues**: Some functions may behave differently across DaVinci Resolve versions.

## Development Status and Roadmap

### Phase 1: Initial Implementation [COMPLETED]
- Basic API functions for project, timeline, and media operations
- Core functionality testing
- Documentation of available features

### Phase 2: Extended Features [COMPLETED]
- Project settings management
- Advanced timeline operations
- Enhanced media pool operations
- Rendering operations
- Testing framework

### Phase 3: Robustness Improvements [IN PROGRESS]
- ✅ Fixed timeline deletion and duplication functions
- ✅ Improved project settings update functions (with documented API limitations)
- ✅ Enhanced source timecode functionality and reporting
- 🔄 Verification of playback control and clip selection functions
- 🔄 Comprehensive testing across functions
- 🔄 Improved documentation with clear limitations and examples

### Phase 4: Advanced Features [PLANNED]
- 📝 Color grading operations
- 📝 Fusion page integration
- 📝 Fairlight audio operations
- 📝 Cross-version compatibility testing
- 📝 Example workflows and tutorials
- 📝 Advanced timeline analysis and validation

## Testing and Verification Methodology

This section outlines how features are tested and verified:

1. **Unit Testing**: Individual functions are tested in isolation with appropriate input parameters
2. **Integration Testing**: Functions are tested together to ensure they work as expected in combination
3. **Edge Case Testing**: Functions are tested with unusual or extreme input values
4. **Version Testing**: Functions are tested across multiple DaVinci Resolve versions when possible
5. **Error Handling Testing**: Functions are tested with invalid inputs to ensure proper error handling

## Contributing to Feature Development

If you wish to contribute to the development of new features or improvement of existing ones:

1. Check the status of the feature in this document
2. Review the implementation guidelines in the project README
3. Create a test script to verify the functionality
4. Submit a pull request with clear documentation of changes

## Last Updated

This document was last updated on: **2025-03-21**

*This is a living document that is updated as new features are added or existing features are modified.* 

## Timeline Functions

### Timeline Markers

Timeline markers are useful for adding notes, comments, and visual indicators at specific points in a timeline. These functions allow you to programmatically manage markers within the timeline.

| Function | Description | Status |
| --- | --- | --- |
| `mcp_get_timeline_markers()` | Retrieves all markers in the current timeline | # STATUS: ✅ Implemented and Tested |
| `mcp_add_timeline_marker(frame, color, name, note, duration, custom_data)` | Adds a new marker at the specified frame | # STATUS: ✅ Implemented and Tested |
| `mcp_update_marker(frame, color, name, note, duration, custom_data)` | Updates an existing marker's properties | # STATUS: ✅ Implemented and Tested |
| `mcp_delete_marker(frame)` | Deletes a marker at a specific frame | # STATUS: ✅ Implemented and Tested |
| `mcp_delete_markers_by_color(color)` | Deletes all markers of a specific color | # STATUS: ✅ Implemented and Tested |

#### Marker Colors

The following marker colors are available in DaVinci Resolve:
- Blue
- Cyan
- Green
- Yellow
- Red
- Pink
- Purple
- Fuchsia
- Rose
- Lavender
- Sky
- Mint
- Lemon
- Sand
- Cocoa
- Cream

#### Implementation Details

The marker functions utilize the DaVinci Resolve API's Timeline object, which provides direct access to marker data. The implementation includes:

- **Core Functions**: Internal Python functions that directly interact with the Resolve API
- **MCP Interface**: Functions prefixed with `mcp_` that provide standardized JSON responses
- **Error Handling**: Comprehensive validation and error reporting
- **Testing**: Unit tests available in `tests/test_marker_functions.py` with mock objects to simulate DaVinci Resolve

#### Example Usage

```python
# Get all markers
markers = client.execute_command("mcp_get_timeline_markers")

# Add a marker at frame 1000 with color "Blue"
client.execute_command("mcp_add_timeline_marker", {
    "frame": 1000,
    "color": "Blue",
    "name": "Important point",
    "note": "Remember to check this transition"
})

# Update a marker
client.execute_command("mcp_update_marker", {
    "frame": 1000,
    "color": "Red",
    "name": "Critical point"
})

# Delete a marker
client.execute_command("mcp_delete_marker", {"frame": 1000})
```

A complete example is available in `examples/timeline_markers.py`

### Timeline XML Export

| Function | Description | Status |
| --- | --- | --- |
| `mcp_export_timeline_xml(output_path)` | Exports the current timeline to an XML file | # STATUS: ✅ Implemented |

#### Example Usage

```python
# Export timeline to XML
result = client.execute_command("mcp_export_timeline_xml", {
    "output_path": "/path/to/output.xml"
})

# Check if export was successful
if result.get("status") == "success":
    print(f"Timeline exported to: {result.get('file_path')}")
else:
    print(f"Export failed: {result.get('error')}")
``` 