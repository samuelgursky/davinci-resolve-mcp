# Source Timecode Functions

This document describes the source timecode functions available in the DaVinci Resolve MCP.

## Overview

These functions provide tools to work with source timecodes in DaVinci Resolve timelines, allowing you to:

1. Retrieve source timecode information for specific clips
2. Generate comprehensive reports of all clips in a timeline with their source timecodes
3. Export these reports in various formats (CSV, JSON, EDL)
4. Perform timecode calculations and conversions

## Functions

### `get_clip_source_timecode`

Retrieves detailed source timecode information for a specific clip in the timeline.

**Parameters:**
- `track_type` (string): The type of track to access ("video" or "audio")
- `track_index` (int): The index of the track (1-based)
- `clip_index` (int): The index of the clip in the track (0-based)

**Returns:**
A dictionary containing:
- Basic clip information (name, duration, start frame, etc.)
- Source timecodes (start, end)
- Timeline timecodes (start, end)
- Media information (source path, format, etc.)

**Example:**
```python
# Get source timecode for the first clip in video track 1
result = get_clip_source_timecode("video", 1, 0)
print(result)
```

### `get_source_timecode_report`

Generates a comprehensive report of all clips in the timeline with their source timecode information.

**Parameters:**
None

**Returns:**
A dictionary containing:
- `timeline_name`: The name of the current timeline
- `clips`: A list of clip objects, each with source timecode information

**Example:**
```python
# Get a report of all clips in the timeline
report = get_source_timecode_report()
print(f"Timeline: {report['timeline_name']}")
print(f"Total clips: {len(report['clips'])}")
```

### `export_source_timecode_report`

Exports a report of all timeline clips with their source timecodes in various formats.

**Parameters:**
- `export_path` (string): The file path where the report should be saved
- `format` (string, default="csv"): The format of the export (options: "csv", "json", "edl")
- `video_tracks_only` (bool, default=False): If True, only include video tracks in the report

**Returns:**
A dictionary with the status of the export operation

**Example:**
```python
# Export as CSV
csv_result = export_source_timecode_report("/path/to/report.csv", "csv", False)

# Export as JSON
json_result = export_source_timecode_report("/path/to/report.json", "json", False)

# Export as EDL (video tracks only)
edl_result = export_source_timecode_report("/path/to/report.edl", "edl", True)
```

## Utility Functions

### `timecode_to_frames`

Converts a timecode string to frame count.

**Parameters:**
- `timecode` (string): The timecode to convert (format: "HH:MM:SS:FF")
- `fps` (float): The frames per second rate

**Returns:**
An integer representing the total number of frames

**Example:**
```python
frames = timecode_to_frames("01:00:30:15", 24.0)
print(frames)  # Output: 86415
```

### `frames_to_timecode`

Converts frame count to a timecode string.

**Parameters:**
- `frame_count` (int): The number of frames
- `fps` (float): The frames per second rate

**Returns:**
A string representing the timecode in format "HH:MM:SS:FF"

**Example:**
```python
tc = frames_to_timecode(86415, 24.0)
print(tc)  # Output: "01:00:30:15"
```

### `calculate_source_timecode`

Calculates a new timecode by adding frames to a starting timecode.

**Parameters:**
- `start_tc` (string): The starting timecode (format: "HH:MM:SS:FF")
- `offset_frames` (int): The number of frames to add (can be negative)
- `fps` (float): The frames per second rate

**Returns:**
A string representing the resulting timecode

**Example:**
```python
# Add 1200 frames (50 seconds at 24fps) to 00:30:00:00
new_tc = calculate_source_timecode("00:30:00:00", 1200, 24.0)
print(new_tc)  # Output: "00:30:50:00"
```

## Report Formats

### CSV Format
The CSV export includes the following columns:
- Track: The track identifier (V1, A1, etc.)
- Clip Name: The name of the clip
- Timeline Start TC: The start timecode in the timeline
- Timeline End TC: The end timecode in the timeline
- Source Start TC: The start timecode in the source media
- Source End TC: The end timecode in the source media
- Duration: The duration of the clip
- Source File: The file path of the source media

### JSON Format
The JSON export includes detailed information about each clip, including:
- All timecode information
- Media details (format, resolution, etc.)
- File paths
- Track information

### EDL Format
The EDL (Edit Decision List) export follows standard EDL format conventions and includes:
- Event numbers
- Source file names
- Source timecodes
- Timeline timecodes

## Example Usage

See the `examples/source_timecode_example.py` script for a complete demonstration of how to use these functions.

## Notes and Limitations

- All timecode functions require DaVinci Resolve to be running and a project with a timeline to be open.
- EDL exports work best with video tracks only, as audio tracks may not be represented correctly in EDL format.
- Source timecode information depends on the metadata available in the source media files.
- The timecode format used is "HH:MM:SS:FF" (hours:minutes:seconds:frames).
- These functions have been tested with DaVinci Resolve 17.0 and later versions. 