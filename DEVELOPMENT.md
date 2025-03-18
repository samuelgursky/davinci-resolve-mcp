# Development Guide for DaVinci Resolve MCP

This document contains information for developers who want to extend the MCP server or understand the DaVinci Resolve API integration.

## DaVinci Resolve API Overview

The DaVinci Resolve API allows scripted access to most features of DaVinci Resolve. It's a powerful but sometimes inconsistent API with varying functionality across different versions.

### API Object Hierarchy

- **Resolve**: Top-level object providing access to the application
  - **ProjectManager**: Manages projects, databases, and folders
    - **Project**: Represents a DaVinci Resolve project
      - **MediaPool**: Manages media in the project
        - **Folder**: Represents a folder in the media pool
          - **Clip**: Represents a media clip
      - **Timeline**: Represents a timeline in the project
        - **TimelineItem**: Represents an item on the timeline

### API Capabilities

Based on our testing, the DaVinci Resolve API provides access to:

- 23 methods on the Resolve object
- 28 methods on the ProjectManager object
- 43 methods on the Project object
- 25 methods on the MediaPool object
- 11 methods on the Folder object
- 55 methods on the Timeline object

The server automatically detects which methods are available in the current DaVinci Resolve installation and adapts its behavior accordingly.

### Known API Limitations

- `GetTimelineNames()` may fail with a `'NoneType' object is not callable` error in some versions
- The free version of DaVinci Resolve has limited API support
- Some methods require specific arguments that aren't well-documented

## Adding New Operations

To add a new operation to the MCP server:

1. Add the operation to the `SUPPORTED_OPERATIONS` list in `src/mcp_server/config.py`
2. Implement the operation in the `process_resolve_operation` function in `src/mcp_server/server.py`
3. Add appropriate functionality in the `ResolveClient` class in `src/resolve_integration/client.py`
4. Document the new operation in the README.md

### Operation Implementation Example

```python
elif operation == "new_operation":
    try:
        result = resolve_client.new_method()
        return {"result": result, "api_capabilities": api_capabilities}
    except Exception as e:
        logger.error(f"Error processing new operation: {e}")
        return {"error": f"Failed to process new operation: {str(e)}", 
                "api_capabilities": api_capabilities}
```

### Recently Added Operations

#### select_clips_by_name

This operation allows you to select all clips in a timeline that match a specified name.

**Request:**
```json
{
    "operation": "select_clips_by_name",
    "data": {
        "clip_name": "Interview"
    }
}
```

**Response:**
```json
{
    "success": true,
    "items_found": 3,
    "items_selected": 3,
    "api_capabilities": {
        // API capabilities object
    }
}
```

This operation is useful for:
- Selecting clips for batch operations
- Finding specific footage in a complex timeline
- Preparing clips for color grading or effects

## Error Handling

The MCP server implements robust error handling that:

1. Detects available API capabilities during initialization
2. Provides fallback methods when primary methods aren't available
3. Returns informative error messages to clients
4. Logs details for debugging purposes

When extending the server, maintain this approach by:
- Checking API capabilities before calling methods
- Providing fallbacks for missing functionality
- Handling exceptions and returning informative error messages
- Logging detailed errors for troubleshooting

## Testing API Capabilities

During development, it's helpful to test which API methods are available. Consider creating a diagnostic script that:

1. Attempts to call various API methods
2. Reports which methods succeed and which fail
3. Captures error messages for failed methods
4. Creates a capabilities map for use in the main server

This approach helps ensure compatibility across different DaVinci Resolve versions and configurations.

## Security Considerations

- Always validate input data before passing it to the DaVinci Resolve API
- Use API keys for authentication
- Configure allowed origins to prevent unauthorized access
- Be cautious when implementing operations that modify projects

## References

- [DaVinci Resolve Scripting Documentation](https://www.blackmagicdesign.com/developer/product/davinciresolve)
- [Model Context Protocol Specification](https://github.com/anthropics/anthropic-model-context-protocol) 