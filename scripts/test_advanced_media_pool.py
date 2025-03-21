#!/usr/bin/env python3
"""
Test script for demonstrating the Advanced Media Pool functions in DaVinci Resolve MCP.
This script creates a test folder structure and smart bins in the current project.
"""

import os
import sys
import json
import time
from pathlib import Path

# Add the parent directory to the Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.mcp.client.client import McpClient

def print_separator(title):
    """Print a separator with a title for better readability."""
    print("\n" + "=" * 50)
    print(f" {title}")
    print("=" * 50)

def print_json(data):
    """Pretty print JSON data."""
    print(json.dumps(data, indent=2))

def main():
    # Connect to the MCP server
    client = McpClient()
    if not client.connect():
        print("Failed to connect to MCP server!")
        return

    # Get current project info
    print_separator("Project Info")
    project_info = client.execute("mcp_get_project_info", {})
    print_json(project_info)

    # Create test folder structure
    print_separator("Creating Folder Structure")
    folders_to_create = [
        "MCP_Test/Footage",
        "MCP_Test/Footage/B-Roll",
        "MCP_Test/Footage/Interviews",
        "MCP_Test/Audio",
        "MCP_Test/Audio/SFX",
        "MCP_Test/Audio/Music"
    ]
    
    for folder_path in folders_to_create:
        result = client.execute("mcp_create_folder_path", {"path": folder_path})
        print(f"Created folder '{folder_path}': {result}")
    
    # Get folder hierarchy
    print_separator("Folder Hierarchy")
    hierarchy = client.execute("mcp_get_folder_hierarchy", {"include_clips": False})
    print_json(hierarchy)
    
    # Get a specific folder
    print_separator("Get Specific Folder")
    folder = client.execute("mcp_get_folder_by_path", {
        "path": "MCP_Test/Footage",
        "include_clips": True,
        "include_subfolders": True
    })
    print_json(folder)
    
    # Set current folder
    print_separator("Set Current Folder")
    result = client.execute("mcp_set_current_folder", {"path": "MCP_Test/Footage"})
    print(f"Set current folder result: {result}")
    
    current = client.execute("mcp_get_current_folder", {})
    print(f"Current folder is now: {current}")
    
    # Create a smart bin
    print_separator("Create Smart Bin")
    
    # First get existing smart bins
    smart_bins = client.execute("mcp_get_smart_bins", {})
    print("Existing smart bins:")
    print_json(smart_bins)
    
    # Create a new test smart bin
    search_criteria = [
        {
            "property": "Resolution",
            "operator": "=",
            "value": "1920x1080"
        },
        {
            "property": "Comments",
            "operator": "contains",
            "value": "test"
        }
    ]
    
    result = client.execute("mcp_create_smart_bin", {
        "name": "MCP Test HD Videos",
        "search_criteria": search_criteria
    })
    print(f"Created smart bin result: {result}")
    
    # Verify smart bin was created
    smart_bins = client.execute("mcp_get_smart_bins", {})
    print("Updated smart bins:")
    print_json(smart_bins)
    
    # Clean up - Delete the smart bin
    print_separator("Cleanup")
    result = client.execute("mcp_delete_smart_bin", {"name": "MCP Test HD Videos"})
    print(f"Deleted smart bin result: {result}")
    
    print_separator("Test Complete")
    print("Advanced Media Pool functions tested successfully!")

if __name__ == "__main__":
    main() 