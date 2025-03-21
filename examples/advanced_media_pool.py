#!/usr/bin/env python3
"""
Example script demonstrating advanced media pool functionality
"""
import os
import sys
import json
from pathlib import Path
import time

# Add the parent directory to sys.path to allow imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from src.mcp.client.client import MCPClient
except ImportError:
    try:
        # Alternative import approach
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from src.mcp.client.client import MCPClient
    except ImportError:
        print("Error: Cannot import the MCPClient module.")
        print("Make sure the DaVinci Resolve MCP package is properly installed.")
        print("Make sure the MCP server is running (python -m src.resolve_mcp)")
        sys.exit(1)

def print_section(title):
    """Print a section header"""
    width = 80
    padding = (width - len(title) - 2) // 2
    print("\n" + "=" * width)
    print(" " * padding + title + " " * padding)
    print("=" * width + "\n")

def print_json(data):
    """Pretty print JSON data"""
    print(json.dumps(data, indent=2))

def main():
    """Main function demonstrating advanced media pool operations"""
    print_section("DaVinci Resolve Advanced Media Pool Example")
    
    # Connect to MCP server
    print("Connecting to MCP server...")
    client = MCPClient()
    
    try:
        # Check current project
        print_section("Current Project")
        project_info = client.execute_command("mcp_get_project_info")
        if "error" in project_info:
            print(f"Error: {project_info['error']}")
            return
            
        print(f"Current project: {project_info['name']}")
        print(f"Frame rate: {project_info['frame_rate']}")
        print(f"Resolution: {project_info['resolution']}")
        
        # Example 1: Create folder structure
        print_section("Creating Folder Structure")
        folder_paths = [
            "Footage/Interviews",
            "Footage/B-Roll",
            "Audio/Music",
            "Audio/SFX",
            "Graphics"
        ]
        
        for path in folder_paths:
            print(f"Creating folder: {path}")
            result = client.execute_command("mcp_create_folder_path", {
                "path": path
            })
            
            if "error" in result:
                print(f"  Error: {result['error']}")
            else:
                print(f"  Success: {result['message']}")
        
        # Example 2: Get folder hierarchy
        print_section("Folder Hierarchy")
        hierarchy = client.execute_command("mcp_get_folder_hierarchy", {
            "include_clips": False
        })
        
        if "error" in hierarchy:
            print(f"Error getting hierarchy: {hierarchy['error']}")
        else:
            print(json.dumps(hierarchy["hierarchy"], indent=2))
        
        # Example 3: Get specific folder by path
        print_section("Footage Folder Info")
        footage_folder = client.execute_command("mcp_get_folder_by_path", {
            "path": "Footage",
            "include_clips": True,
            "include_subfolders": True
        })
        
        if "error" in footage_folder:
            print(f"Error getting folder: {footage_folder['error']}")
        else:
            print_json(footage_folder["folder"])
        
        # Example 4: Set current folder
        print_section("Setting Current Folder")
        result = client.execute_command("mcp_set_current_folder", {
            "path": "Footage/B-Roll"
        })
        
        if "error" in result:
            print(f"Error setting folder: {result['error']}")
        else:
            print(f"Success: {result['message']}")
            
            # Get current folder to verify
            current = client.execute_command("mcp_get_current_folder")
            if "error" not in current:
                print(f"Current folder is: {current['folder']['name']}")
        
        # Example 5: Smart Bins
        print_section("Smart Bins")
        
        # Get existing smart bins
        print("Getting existing smart bins...")
        bins = client.execute_command("mcp_get_smart_bins")
        if "error" in bins:
            print(f"Error getting smart bins: {bins['error']}")
        else:
            if bins["smart_bins"]:
                print("Found existing smart bins:")
                for bin in bins["smart_bins"]:
                    print(f"  {bin['name']} ({bin['clip_count']} clips)")
            else:
                print("No smart bins found")
        
        # Create a smart bin
        print("\nCreating a test smart bin...")
        search_criteria = {
            "Resolution": "1920x1080",
            "Type": "Video"
        }
        
        bin_result = client.execute_command("mcp_create_smart_bin", {
            "name": "Test HD Videos",
            "search_criteria": search_criteria
        })
        
        if "error" in bin_result:
            print(f"Error creating smart bin: {bin_result['error']}")
        else:
            print(f"Success: {bin_result['message']}")
            
            # Pause to let DaVinci Resolve process the changes
            print("Waiting for DaVinci Resolve to update...")
            time.sleep(2)
            
            # Verify the bin was created
            bins = client.execute_command("mcp_get_smart_bins")
            if "error" not in bins and bins["smart_bins"]:
                print("Updated smart bins:")
                for bin in bins["smart_bins"]:
                    print(f"  {bin['name']} ({bin['clip_count']} clips)")
        
        # Example 6: Bulk clip property operations
        print_section("Bulk Clip Properties")
        print("This example requires clips in your media pool.")
        print("If you don't have any clips yet, import some media first.")
        
        # Add a keyword to all clips in root folder
        result = client.execute_command("mcp_bulk_set_clip_property", {
            "folder_path": "",  # Root folder
            "property_name": "Keywords",
            "property_value": "example,test,MCP"
        })
        
        if "error" in result:
            print(f"Error setting clip properties: {result['error']}")
        else:
            print(f"Success: {result['message']}")
        
        # Example 7: Moving Clips
        print_section("Moving Clips")
        print("This example demonstrates how to move clips between folders.")
        print("Note: This example is for demonstration purposes and requires clips in your Media Pool.")
        
        # Just show the command example without executing
        print("\nExample command to move clips:")
        print("""
client.execute_command("mcp_move_clips_between_folders", {
    "source_path": "Footage/B-Roll",
    "destination_path": "Footage/Interviews",
    "clip_names": ["Clip1", "Clip2"]  # Optional, omit to move all clips
})
        """)
        
        # Example 8: Importing Files
        print_section("Importing Files")
        print("This example demonstrates how to import files to a specific folder.")
        print("Note: This example is for demonstration purposes and requires valid file paths.")
        
        # Just show the command example without executing
        print("\nExample command to import files:")
        print("""
client.execute_command("mcp_import_files_to_folder", {
    "file_paths": ["/path/to/video1.mp4", "/path/to/video2.mp4"],
    "folder_path": "Footage/B-Roll"  # Optional, omit to use current folder
})
        """)
        
        print_section("Advanced Media Pool Example Completed")
        print("These examples demonstrate the key functionality of the advanced")
        print("media pool management API. You can use these functions to:")
        print("  - Navigate and create complex folder structures")
        print("  - Manage smart bins for automatic clip organization")
        print("  - Perform bulk operations on clips")
        print("  - Import media to specific folders")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Disconnect
        print("\nDisconnecting from MCP server...")
        client.disconnect()

if __name__ == "__main__":
    main() 