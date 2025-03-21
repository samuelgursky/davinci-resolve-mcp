# DaVinci Resolve MCP Integration

This project implements a Model Context Protocol (MCP) server that interfaces with DaVinci Resolve to provide tools for accessing information about the current project, timeline, and clips.

## Requirements

- DaVinci Resolve Studio or the free version of DaVinci Resolve
- Python 3.6+
- MCP Python SDK (`pip install git+https://github.com/modelcontextprotocol/python-sdk.git`)

## Setup

1. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Make sure DaVinci Resolve is installed and running on your system.

3. Ensure that the DaVinci Resolve API is accessible. The script automatically attempts to locate the API modules based on your operating system.

## Running the DaVinci Resolve MCP Server

Start the MCP server:

```
python src/resolve_mcp.py
```

The server will be available at `http://localhost:8000`.

## Testing the Server

In a separate terminal, run the test client:

```
python src/test_resolve_client.py
```

This will connect to the MCP server, list the available tools, and demonstrate calling various DaVinci Resolve-related tools.

## Available Tools

The DaVinci Resolve MCP server provides the following tools:

1. `get_timeline_clip_names` - Returns a list of all clips in the current timeline, including their track and duration.

2. `get_project_info` - Returns information about the current project, including name, frame rate, resolution, and timeline count.

3. `get_current_timeline_name` - Returns the name of the current timeline.

4. `get_timeline_info` - Returns detailed information about the current timeline, including frame count, track counts, FPS, and timecodes.

5. `get_clip_details` - Returns detailed information about a specific clip in the timeline, including its properties and media pool information.
   - Parameters:
     - `track_type`: The type of track ('video' or 'audio'), defaults to 'video'
     - `track_index`: The index of the track (1-based), defaults to 1
     - `clip_index`: The index of the clip in the track (0-based), defaults to 0

6. `get_project_timelines` - Returns a list of all timelines in the current project with their names and track counts.

## Using with Cursor

To use this MCP server with Cursor:

1. Open Cursor Settings
2. Go to Features > MCP
3. Click "+ Add New MCP Server"
4. Select "stdio" as the Type
5. Enter a Name (e.g., "DaVinci Resolve MCP")
6. Set the Command to `python /path/to/src/resolve_mcp.py`
7. Click "Save"

You can now use the DaVinci Resolve MCP tools in Cursor's Agent by referencing them in your prompts.

## Troubleshooting

- **Error: Could not locate DaVinci Resolve API modules**: Check if DaVinci Resolve is installed in the default location for your operating system. If it's installed in a custom location, you may need to modify the `add_resolve_module_path` function.

- **Error: Unable to connect to DaVinci Resolve**: Make sure DaVinci Resolve is running before starting the MCP server.

- **No project/timeline is currently open**: Open a project and timeline in DaVinci Resolve before using the tools.

## Future Enhancements

- Add tools for modifying the timeline and clips
- Add support for color grading operations
- Implement tools for rendering and export 