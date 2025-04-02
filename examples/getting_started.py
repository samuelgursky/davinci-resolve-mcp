#!/usr/bin/env python3
"""
Getting Started Example for DaVinci Resolve MCP

This example demonstrates the basics of connecting to DaVinci Resolve via MCP.
It shows how to:
1. Check if DaVinci Resolve is running
2. Get the current project information
3. List available timelines
4. Get the current page

Prerequisites:
- DaVinci Resolve must be running
- The MCP server must be properly set up
- A project should be open in DaVinci Resolve
"""

import sys
from mcp.client import Client


# Connect to the MCP server
def connect_to_mcp_server():
    """Connect to the MCP server and return the client."""
    print("Connecting to DaVinci Resolve MCP server...")
    client = Client()
    client.connect_to_local_server("DaVinciResolveMCP")
    return client


# Get DaVinci Resolve version
def get_resolve_version(client):
    """Get the version of DaVinci Resolve."""
    print("\n--- DaVinci Resolve Version ---")
    response = client.resource("resolve://version")
    print(f"DaVinci Resolve Version: {response}")
    return response


# Get current page
def get_current_page(client):
    """Get the current page in DaVinci Resolve (Edit, Color, etc.)."""
    print("\n--- Current Page ---")
    response = client.resource("resolve://current-page")
    print(f"Current Page: {response}")
    return response


# List projects
def list_projects(client):
    """List all available projects in DaVinci Resolve."""
    print("\n--- Available Projects ---")
    response = client.resource("resolve://projects")

    if isinstance(response, list):
        if len(response) > 0:
            for i, project in enumerate(response, 1):
                print(f"{i}. {project}")
        else:
            print("No projects found.")
    else:
        print(f"Error: {response}")

    return response


# Get current project
def get_current_project(client):
    """Get the name of the currently open project."""
    print("\n--- Current Project ---")
    response = client.resource("resolve://current-project")
    print(f"Current Project: {response}")
    return response


# List timelines
def list_timelines(client):
    """List all timelines in the current project."""
    print("\n--- Available Timelines ---")
    response = client.resource("resolve://timelines")

    if isinstance(response, list):
        if len(response) > 0:
            for i, timeline in enumerate(response, 1):
                print(f"{i}. {timeline}")
        else:
            print("No timelines found.")
    else:
        print(f"Error: {response}")

    return response


# Main function
def main():
    """Main function to demonstrate basic DaVinci Resolve MCP functionality."""
    try:
        # Connect to the MCP server
        client = connect_to_mcp_server()
        print("Connected to MCP server!")

        # Get DaVinci Resolve version
        get_resolve_version(client)

        # Get current page
        get_current_page(client)

        # List projects
        list_projects(client)

        # Get current project
        get_current_project(client)

        # List timelines
        list_timelines(client)

        print("\nGetting Started Example completed successfully!")

    except Exception as e:
        print(f"Error: {str(e)}")
        print("\nTroubleshooting tips:")
        print("1. Make sure DaVinci Resolve is running")
        print("2. Check that the MCP server is running (`./run-now.sh`)")
        print("3. Ensure a project is open in DaVinci Resolve")
        print("4. Check environment variables are set correctly")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
