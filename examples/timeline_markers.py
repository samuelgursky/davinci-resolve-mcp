#!/usr/bin/env python3
"""
Example script demonstrating timeline marker functionality
"""
import os
import sys
import json
from pathlib import Path

# Add the parent directory to sys.path to allow imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from src.davinci_resolve_mcp.client import MCPClient
except ImportError:
    try:
        # Alternative import approach
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from src.davinci_resolve_mcp.client import MCPClient
    except ImportError:
        print("Error: Cannot import the MCPClient module.")
        print("Make sure the DaVinci Resolve MCP package is properly installed.")
        print("Make sure the MCP server is running (python -m src.resolve_mcp)")
        sys.exit(1)

def print_separator():
    """Print a separator line"""
    print("\n" + "=" * 50 + "\n")

def print_markers(markers):
    """Pretty print marker information"""
    if not markers:
        print("No markers found")
        return
    
    print(f"Found {len(markers)} markers:")
    for i, marker in enumerate(markers):
        print(f"\n{i+1}. Marker at frame {marker['frame']}")
        print(f"   Name: {marker['name'] or '(unnamed)'}")
        print(f"   Color: {marker['color']}")
        
        if marker.get('note'):
            print(f"   Note: {marker['note']}")
        
        if marker.get('duration') and marker['duration'] > 1:
            print(f"   Duration: {marker['duration']} frames")

def main():
    """Main function demonstrating timeline marker operations"""
    print("DaVinci Resolve Timeline Markers Example")
    print("========================================")
    
    # Connect to MCP server
    print("\nConnecting to MCP server...")
    client = MCPClient()
    
    # Step 1: Get current timeline information
    print("\nGetting current timeline information...")
    timeline_info = client.call("mcp_get_timeline_info")
    if "error" in timeline_info:
        print(f"Error: {timeline_info['error']}")
        sys.exit(1)
    
    print(f"Current timeline: {timeline_info['name']}")
    print(f"Timeline duration: {timeline_info['duration']} frames")
    print(f"Frame rate: {timeline_info['frame_rate']} fps")
    
    # Step 2: Get existing markers
    print_separator()
    print("Getting existing markers...")
    markers_result = client.call("mcp_get_timeline_markers")
    
    if "error" in markers_result:
        print(f"Error: {markers_result['error']}")
        sys.exit(1)
    
    existing_markers = markers_result.get("markers", [])
    print_markers(existing_markers)
    
    # Step 3: Add new markers
    print_separator()
    print("Adding new markers...")
    
    # Calculate some frame positions based on timeline duration
    duration = timeline_info['duration']
    marker_positions = [
        int(duration * 0.1),  # 10% into timeline
        int(duration * 0.25), # 25% into timeline
        int(duration * 0.5),  # 50% into timeline
        int(duration * 0.75), # 75% into timeline
    ]
    
    # Add markers at these positions
    new_markers = []
    marker_colors = ["Blue", "Green", "Red", "Yellow"]
    marker_names = ["Intro", "First transition", "Climax", "Conclusion"]
    
    for i, frame in enumerate(marker_positions):
        color = marker_colors[i % len(marker_colors)]
        name = marker_names[i % len(marker_names)]
        note = f"Auto-generated marker {i+1}"
        
        print(f"\nAdding {color} marker '{name}' at frame {frame}...")
        result = client.call("mcp_add_timeline_marker", 
                           frame=frame,
                           color=color,
                           name=name,
                           note=note)
        
        if "error" in result:
            print(f"Error: {result['error']}")
        else:
            print(f"Marker added successfully")
            new_markers.append(result["marker"])
    
    # Step 4: Get updated markers list
    print_separator()
    print("Getting updated markers list...")
    markers_result = client.call("mcp_get_timeline_markers")
    
    if "error" in markers_result:
        print(f"Error: {markers_result['error']}")
    else:
        updated_markers = markers_result.get("markers", [])
        print_markers(updated_markers)
    
    # Step 5: Update a marker
    if new_markers:
        print_separator()
        print("Updating a marker...")
        marker_to_update = new_markers[0]
        frame = marker_to_update["frame"]
        
        print(f"Updating marker at frame {frame}...")
        update_result = client.call("mcp_update_marker",
                                  frame=frame,
                                  color="Purple",
                                  name="UPDATED: " + marker_to_update["name"],
                                  note="This marker was updated")
        
        if "error" in update_result:
            print(f"Error: {update_result['error']}")
        else:
            print("Marker updated successfully")
            print(f"New color: {update_result['marker']['color']}")
            print(f"New name: {update_result['marker']['name']}")
    
    # Step 6: Delete a marker
    if len(new_markers) > 1:
        print_separator()
        print("Deleting a marker...")
        marker_to_delete = new_markers[1]
        frame = marker_to_delete["frame"]
        
        print(f"Deleting marker at frame {frame}...")
        delete_result = client.call("mcp_delete_marker", frame=frame)
        
        if "error" in delete_result:
            print(f"Error: {delete_result['error']}")
        else:
            print("Marker deleted successfully")
    
    # Step 7: Delete markers by color
    if new_markers:
        print_separator()
        print("Deleting markers by color...")
        color_to_delete = "Purple"  # This should delete the marker we updated earlier
        
        print(f"Deleting all {color_to_delete} markers...")
        delete_result = client.call("mcp_delete_markers_by_color", color=color_to_delete)
        
        if "error" in delete_result:
            print(f"Error: {delete_result['error']}")
        else:
            print(f"Successfully deleted {delete_result['deleted_count']} {color_to_delete} markers")
    
    # Step 8: Final markers list
    print_separator()
    print("Final markers list:")
    markers_result = client.call("mcp_get_timeline_markers")
    
    if "error" in markers_result:
        print(f"Error: {markers_result['error']}")
    else:
        final_markers = markers_result.get("markers", [])
        print_markers(final_markers)
    
    print_separator()
    print("Timeline markers example complete!")

if __name__ == "__main__":
    main() 