# Using the DaVinci Resolve MCP Server

This guide explains how to use the Model Context Protocol (MCP) server with DaVinci Resolve.

## Prerequisites

Before you begin, make sure you have:

1. DaVinci Resolve installed and running
2. Python 3.6+ installed
3. All required dependencies installed (`pip install -r requirements.txt`)
4. Properly configured environment variables for DaVinci Resolve scripting API

## Starting the Server

1. First, make sure DaVinci Resolve is running and a project is open
2. Start the MCP server:

```bash
python scripts/run_server.py
```

Or directly:

```bash
python src/mcp_server/server.py
```

The server will start on `localhost:8765` by default. You can modify these settings in the `.env` file.

## Connecting from an MCP Client

Any MCP-compatible client can connect to the server. Here's how to connect using our example client:

```bash
python src/mcp_client_example.py
```

## Available Operations

The MCP server supports the following operations:

### Project Operations

- **get_projects**: Get a list of available projects
  ```json
  { "operation": "get_projects", "data": {} }
  ```

- **get_project_info**: Get information about the current project
  ```json
  { "operation": "get_project_info", "data": {} }
  ```

- **create_project**: Create a new project
  ```json
  { "operation": "create_project", "data": { "name": "My New Project" } }
  ```

- **open_project**: Open an existing project
  ```json
  { "operation": "open_project", "data": { "name": "Existing Project" } }
  ```

### Timeline Operations

- **get_timeline_info**: Get information about the current timeline
  ```json
  { "operation": "get_timeline_info", "data": {} }
  ```

- **get_timeline_clips**: Get clips in the current timeline
  ```json
  { "operation": "get_timeline_clips", "data": {} }
  ```

### Media Operations

- **get_media_pool_items**: Get items in the media pool
  ```json
  { "operation": "get_media_pool_items", "data": {} }
  ```

- **add_clip_to_timeline**: Add a clip to the timeline
  ```json
  { "operation": "add_clip_to_timeline", "data": { "clip_name": "My Clip" } }
  ```

## Integrating with LLM Applications

To integrate this MCP server with an LLM application (like Claude), you need to:

1. Configure the LLM application to use MCP protocol for external tools
2. Connect to the DaVinci Resolve MCP server endpoint (`ws://localhost:8765/mcp`)
3. Send requests as per the operations documented above

### Example with Claude

```python
# Example using Claude with MCP to interact with DaVinci Resolve
import anthropic
from mcp_client import MCPClient

# Initialize Claude client
claude = anthropic.Client(api_key="your_api_key")

# Initialize MCP client
mcp_client = MCPClient()
await mcp_client.connect()

# Get project info through MCP
project_info = await mcp_client.send_request("get_project_info")

# Use Claude to analyze the project
response = claude.messages.create(
    model="claude-3-opus-20240229",
    max_tokens=1000,
    messages=[
        {"role": "user", "content": f"Analyze this DaVinci Resolve project: {project_info}"}
    ]
)

print(response.content)

# Disconnect from MCP server
await mcp_client.disconnect()
```

## Security Considerations

- The MCP server enforces API key authentication if configured
- Currently, the server listens only on localhost by default for security
- Make sure to set a strong API key in the `.env` file if exposing the server to a network

## Troubleshooting

If you encounter issues, check the following:

1. Make sure DaVinci Resolve is running before starting the MCP server
2. Verify your environment variables are set correctly for the DaVinci Resolve API
3. Check the server logs for detailed error messages
4. Make sure you're using the correct operations and data format

If issues persist, check the README for contact information and support resources. 