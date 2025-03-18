# DaVinci Resolve MCP Integration

This project implements a Model Context Protocol (MCP) server for DaVinci Resolve. It allows LLM applications (like Claude, GPT, etc.) to interact directly with DaVinci Resolve projects, enabling AI-assisted video editing capabilities.

## What is MCP?

The Model Context Protocol (MCP) is an open protocol that standardizes how applications provide context to LLMs (Large Language Models). It allows AI models to interact with various data sources and tools in a standardized way, similar to how USB-C provides a standardized way to connect devices.

## Features

- Seamless integration between AI assistants and DaVinci Resolve
- Access to timeline, media, and project information
- Ability to manipulate edits and automate workflows
- Cross-platform support for macOS, Windows, and Linux
- WebSocket-based API for real-time communication

## Server Information

```json
{
  "mcp_version": "0.1.0",
  "name": "DaVinci Resolve MCP",
  "version": "0.1.0",
  "display_name": "DaVinci Resolve MCP",
  "description": "MCP server for DaVinci Resolve integration",
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
```

## Supported Operations

The MCP server supports the following operations:

```json
{
  "operations": [
    "get_projects",
    "get_project_info",
    "get_timeline_info",
    "get_media_pool_items",
    "get_timeline_clips",
    "create_project",
    "open_project",
    "add_clip_to_timeline",
    "export_timeline",
    "apply_lut",
    "render_project",
    "get_api_capabilities",
    "select_clips_by_name"
  ]
}
```

### Operation Examples

- **Get Projects**: `{"operation": "get_projects", "data": {}}`
- **Get Project Info**: `{"operation": "get_project_info", "data": {}}`
- **Open Project**: `{"operation": "open_project", "data": {"name": "My Project"}}`
- **Get Media Pool Items**: `{"operation": "get_media_pool_items", "data": {}}`
- **Add Clip to Timeline**: `{"operation": "add_clip_to_timeline", "data": {"clip_name": "My Clip"}}`
- **Select Clips by Name**: `{"operation": "select_clips_by_name", "data": {"clip_name": "interview"}}`

## Prerequisites

- DaVinci Resolve Studio (18.0 or later recommended)
- Python 3.6+ (64-bit)
- DaVinci Resolve Scripting API access (included with DaVinci Resolve Studio)

## Installation

1. Clone this repository:
   ```
   git clone https://github.com/yourusername/davinci-resolve-mcp.git
   cd davinci-resolve-mcp
   ```

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Create your environment configuration:
   ```
   cp .env.example .env
   ```

4. Edit the `.env` file to set:
   - Uncomment your OS-specific environment variables
   - Set a unique API key for security
   - Configure allowed origins if needed

## Running the Server

1. Start DaVinci Resolve and open a project
2. Run the MCP server:
   ```
   python scripts/run_server.py
   ```

The server will start on `ws://localhost:8765/mcp` by default.

## Connecting to LLMs

### Claude
1. Configure an MCP connection in Claude settings
2. Use the endpoint: `ws://localhost:8765/mcp`
3. Enter your API key from the `.env` file

### Other LLMs
For other LLMs that support MCP, follow their specific documentation for connecting external tools and use the same endpoint and API key.

## Project Structure

- `src/mcp_server/`: Main server code for the MCP implementation
- `src/resolve_integration/`: DaVinci Resolve API integration code
- `scripts/`: Utility scripts for running the server and setup
- `docs/`: Documentation files

## Error Handling and API Capabilities

The server includes automatic detection of available DaVinci Resolve API features and gracefully handles missing functionality by providing alternatives or informative error messages. This ensures compatibility across different DaVinci Resolve versions and configurations.

## Security

The server includes authentication via API key and can be configured to restrict access to specific origins. Make sure to set a strong API key in your `.env` file before deploying.

## License

MIT

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Example MCP Client Usage

```python
import asyncio
from src.mcp_client_example import MCPClient

async def main():
    client = MCPClient("ws://localhost:8765/mcp")
    
    # Connect to the server
    await client.connect()
    
    # Get list of projects
    projects = await client.send_request("get_projects", {})
    print(f"Available projects: {projects}")
    
    # Get current project info
    project_info = await client.send_request("get_project_info", {})
    print(f"Current project: {project_info}")
    
    # Disconnect
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
```

## Example Tasks You Can Try

1. **Get project information**: Ask the LLM to tell you about your current project
   ```
   "What projects do I have open in DaVinci Resolve right now?"
   ```

2. **Analyze timeline**: Have the LLM analyze your timeline structure
   ```
   "Analyze my current timeline in DaVinci Resolve and give me statistics about it"
   ```

3. **Control editing**: Have the LLM perform editing operations
   ```
   "Open my project named 'Test' in DaVinci Resolve"
   ```

## Troubleshooting

- Ensure DaVinci Resolve is running before starting the server
- Check that your API environment variables are correctly set for your OS
- See server logs for detailed error information
- Make sure you're using DaVinci Resolve Studio, as the free version has limited API support