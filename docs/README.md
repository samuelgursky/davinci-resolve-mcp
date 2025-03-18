# DaVinci Resolve MCP Documentation

Welcome to the documentation for the DaVinci Resolve Model Context Protocol (MCP) server. This project enables AI-powered tools to interact with DaVinci Resolve for enhanced video editing workflows.

## Getting Started

- [Installation and Setup](../README.md) - How to install and set up the server
- [Usage Guide](usage.md) - How to use the MCP server with DaVinci Resolve

## API Reference

- [API Documentation](api/README.md) - Detailed API reference for available operations

## Examples

- [Example Scripts](examples/) - Example scripts demonstrating MCP usage with LLMs
  - [Video Project Summary](examples/llm_video_summary.py) - Generate a summary of a DaVinci Resolve project using an LLM

## Integration Guides

### Integrating with LLMs

The primary purpose of this MCP server is to allow Large Language Models (LLMs) to interact with DaVinci Resolve. Here are the basic steps:

1. **Start DaVinci Resolve** - Ensure DaVinci Resolve is running with a project open
2. **Start the MCP Server** - Run the server using `python scripts/run_server.py` or directly with `python src/mcp_server/server.py`
3. **Connect your LLM Application** - Connect your LLM application to the MCP endpoint at `ws://localhost:8765/mcp`
4. **Send Operations** - Send operation requests to interact with DaVinci Resolve

### Example Integration with Claude

Claude and other Anthropic LLMs have built-in support for MCP. To integrate with Claude:

1. Configure Claude to connect to your MCP server
2. Use Claude's tool-use capability to interact with DaVinci Resolve
3. Claude can then analyze footage, suggest edits, or automate repetitive tasks

See the examples directory for more detailed integration examples.

## Troubleshooting

If you encounter issues while using the MCP server:

1. Make sure DaVinci Resolve is running before starting the MCP server
2. Check that your environment variables are set correctly
3. Look at the server logs for error messages
4. Verify that your client is sending properly formatted requests

For more help, please open an issue on the GitHub repository. 