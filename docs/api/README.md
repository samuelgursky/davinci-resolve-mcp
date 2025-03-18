# DaVinci Resolve MCP API Reference

This document provides a detailed reference for the operations available through the DaVinci Resolve MCP server.

## MCP Protocol

The Model Context Protocol (MCP) is implemented over WebSockets. The server is available at:

```
ws://localhost:8765/mcp
```

### Message Format

All messages follow this basic structure:

```json
{
  "id": "unique-message-id",
  "type": "request|response|error|ping|pong|close|close_ack|server_info",
  "operation": "operation-name",  // For request and response messages
  "data": { 
    // Operation-specific data
  }
}
```

## Server Information

When connecting to the WebSocket, the server sends a `server_info` message with metadata about the server:

```json
{
  "type": "server_info",
  "data": {
    "mcp_version": "0.1.0",
    "name": "DaVinci Resolve MCP",
    "version": "0.1.0",
    "display_name": "DaVinci Resolve MCP",
    "description": "MCP server for DaVinci Resolve integration",
    "contact_email": "your-email@example.com",
    "icons": {
      "small": "https://raw.githubusercontent.com/yourusername/davinci-resolve-mcp/main/assets/icon-small.png",
      "medium": "https://raw.githubusercontent.com/yourusername/davinci-resolve-mcp/main/assets/icon-medium.png",
      "large": "https://raw.githubusercontent.com/yourusername/davinci-resolve-mcp/main/assets/icon-large.png"
    },
    "categories": ["video-editing", "creativity"],
    "authentication": {
      "type": "api_key",
      "api_key_location": "header",
      "api_key_name": "X-API-Key"
    },
    "capabilities": {
      "read_projects": true,
      "modify_projects": true,
      "read_timeline": true,
      "modify_timeline": true,
      "read_media": true,
      "render_export": true,
      "color_grading": true
    }
  }
}
```

## Operations

### Project Operations

#### `get_projects`

Get a list of available projects.

**Request**:
```json
{
  "id": "msg-id",
  "type": "request",
  "operation": "get_projects",
  "data": {}
}
```

**Response**:
```json
{
  "id": "msg-id",
  "type": "response",
  "operation": "get_projects",
  "data": {
    "projects": ["Project 1", "Project 2", "Project 3"]
  }
}
```

#### `get_project_info`

Get information about the current project.

**Request**:
```json
{
  "id": "msg-id",
  "type": "request",
  "operation": "get_project_info",
  "data": {}
}
```

**Response**:
```json
{
  "id": "msg-id",
  "type": "response",
  "operation": "get_project_info",
  "data": {
    "name": "My Project",
    "fps": "24",
    "resolution": {
      "width": 1920,
      "height": 1080
    },
    "timelines": ["Timeline 1", "Timeline 2"],
    "current_timeline": "Timeline 1",
    "media_pool_item_count": 42
  }
}
```

#### `create_project`

Create a new project.

**Request**:
```json
{
  "id": "msg-id",
  "type": "request",
  "operation": "create_project",
  "data": {
    "name": "My New Project"
  }
}
```

**Response**:
```json
{
  "id": "msg-id",
  "type": "response",
  "operation": "create_project",
  "data": {
    "success": true,
    "project_name": "My New Project"
  }
}
```

#### `open_project`

Open an existing project.

**Request**:
```json
{
  "id": "msg-id",
  "type": "request",
  "operation": "open_project",
  "data": {
    "name": "Existing Project"
  }
}
```

**Response**:
```json
{
  "id": "msg-id",
  "type": "response",
  "operation": "open_project",
  "data": {
    "success": true,
    "project_name": "Existing Project"
  }
}
```

### Timeline Operations

#### `get_timeline_info`

Get information about the current timeline.

**Request**:
```json
{
  "id": "msg-id",
  "type": "request",
  "operation": "get_timeline_info",
  "data": {}
}
```

**Response**:
```json
{
  "id": "msg-id",
  "type": "response",
  "operation": "get_timeline_info",
  "data": {
    "name": "Main Timeline",
    "track_count": 8,
    "item_count": 25
  }
}
```

#### `get_timeline_clips`

Get clips in the current timeline.

**Request**:
```json
{
  "id": "msg-id",
  "type": "request",
  "operation": "get_timeline_clips",
  "data": {}
}
```

**Response**:
```json
{
  "id": "msg-id",
  "type": "response",
  "operation": "get_timeline_clips",
  "data": {
    "clips": [
      {
        "name": "Interview_001",
        "duration": 1250
      },
      {
        "name": "B-Roll_002",
        "duration": 450
      }
    ]
  }
}
```

### Media Operations

#### `get_media_pool_items`

Get items in the media pool.

**Request**:
```json
{
  "id": "msg-id",
  "type": "request",
  "operation": "get_media_pool_items",
  "data": {}
}
```

**Response**:
```json
{
  "id": "msg-id",
  "type": "response",
  "operation": "get_media_pool_items",
  "data": {
    "items": [
      {
        "name": "Interview_001.mp4",
        "type": "Video"
      },
      {
        "name": "B-Roll_002.mp4",
        "type": "Video"
      },
      {
        "name": "Music_Track.mp3",
        "type": "Audio"
      }
    ]
  }
}
```

#### `add_clip_to_timeline`

Add a clip to the timeline.

**Request**:
```json
{
  "id": "msg-id",
  "type": "request",
  "operation": "add_clip_to_timeline",
  "data": {
    "clip_name": "Interview_001.mp4"
  }
}
```

**Response**:
```json
{
  "id": "msg-id",
  "type": "response",
  "operation": "add_clip_to_timeline",
  "data": {
    "success": true,
    "clip_name": "Interview_001.mp4"
  }
}
```

## Error Handling

If an operation fails, an error response is returned:

```json
{
  "id": "msg-id",
  "type": "error",
  "operation": "operation-name",
  "data": {
    "message": "Detailed error message"
  }
}
```

Common error scenarios:

- DaVinci Resolve not running or not accessible
- Invalid operation
- Missing required parameters
- Project or timeline not found
- Authentication failure 