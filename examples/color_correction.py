#!/usr/bin/env python3
"""
Example script demonstrating Color Correction Functions in DaVinci Resolve MCP.

This script shows how to:
1. Navigate and manage nodes in the node graph
2. Apply and retrieve color correction settings
3. Organize nodes with labels and colors
4. Apply LUTs to nodes
"""

import os
import sys
import json
import time
from pathlib import Path

# Add parent directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.mcp.client.client import McpClient

def print_section(title):
    """Print a section header."""
    print(f"\n{'-' * 80}")
    print(f"  {title}")
    print(f"{'-' * 80}")

def print_json(data):
    """Pretty print JSON data."""
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except:
            pass
    print(json.dumps(data, indent=2))

def main():
    """Main function demonstrating color correction operations."""
    # Connect to the MCP server
    client = McpClient()
    if not client.connect():
        print("Failed to connect to MCP server!")
        return

    # Get current timeline info
    print_section("Current Timeline Information")
    timeline_info = client.execute("mcp_get_timeline_info", {})
    print_json(timeline_info)
    
    # Switch to the color page if needed
    print("\nPlease switch to the Color page in DaVinci Resolve")
    input("Press Enter to continue...")
    
    # Example 1: Get Node List
    print_section("1. Getting Node Information")
    node_list = client.execute("mcp_get_node_list", {})
    print_json(node_list)
    
    # Example 2: Add a Serial Node
    print_section("2. Adding a Serial Node")
    new_node = client.execute("mcp_add_serial_node", {})
    print_json(new_node)
    
    # Set a label for the new node
    if "node_index" in new_node:
        node_index = new_node["node_index"]
        result = client.execute("mcp_set_node_label", {
            "label": f"MCP Test Node"
        })
        print("\nSet node label:")
        print_json(result)
        
        # Set node color to blue
        result = client.execute("mcp_set_node_color", {
            "red": 0.2,
            "green": 0.4,
            "blue": 0.8,
            "alpha": 1.0
        })
        print("\nSet node color:")
        print_json(result)
    
    # Example 3: Get Primary Correction
    print_section("3. Getting Primary Correction Values")
    correction = client.execute("mcp_get_primary_correction", {})
    print_json(correction)
    
    # Example 4: Set Primary Correction
    print_section("4. Setting Primary Correction Values")
    
    # Apply a warm look with higher contrast
    correction_params = {
        "lift": {
            "red": 0.02,
            "green": 0.01,
            "blue": -0.02,
            "master": 0.0
        },
        "gamma": {
            "red": 0.05,
            "green": 0.02,
            "blue": -0.03,
            "master": 0.02
        },
        "gain": {
            "red": 1.1,
            "green": 1.05,
            "blue": 0.9,
            "master": 1.05
        },
        "contrast": {
            "master": 1.1
        },
        "saturation": 1.1
    }
    
    result = client.execute("mcp_set_primary_correction", correction_params)
    print_json(result)
    
    # Example 5: Add and Manage Multiple Nodes
    print_section("5. Creating a Multi-Node Structure")
    
    # Create and set up a parallel node
    print("\nAdding a parallel node:")
    parallel_node = client.execute("mcp_add_parallel_node", {})
    print_json(parallel_node)
    
    if "node_index" in parallel_node:
        # Label the node
        client.execute("mcp_set_node_label", {"label": "Green Channel Boost"})
        
        # Apply a green channel adjustment
        client.execute("mcp_set_primary_correction", {
            "gamma": {
                "green": 1.1
            }
        })
    
    # Create and set up a layer node
    print("\nAdding a layer node:")
    layer_node = client.execute("mcp_add_layer_node", {})
    print_json(layer_node)
    
    if "node_index" in layer_node:
        # Label the node
        client.execute("mcp_set_node_label", {"label": "Soft Overlay"})
        
        # Set a tint with overlay
        client.execute("mcp_set_primary_correction", {
            "gamma": {
                "red": 1.05,
                "blue": 1.05
            },
            "saturation": 1.2
        })
    
    # Example 6: Get updated node list
    print_section("6. Final Node Structure")
    final_nodes = client.execute("mcp_get_node_list", {})
    print_json(final_nodes)
    
    # Example 7: Reset a node
    print_section("7. Resetting a Node")
    # First select a node to reset (let's pick node 2 if it exists)
    node_count = final_nodes.get("node_count", 0)
    
    if node_count >= 2:
        client.execute("mcp_set_current_node_index", {"index": 2})
        reset_result = client.execute("mcp_reset_current_node", {})
        print_json(reset_result)
    else:
        print("Not enough nodes to demonstrate reset")

    print_section("Color Correction Functions Demo Complete")
    print("The example has demonstrated:")
    print("- Node navigation and management")
    print("- Primary color correction settings")
    print("- Node labeling and organization")
    print("- Creating a multi-node color grade structure")

if __name__ == "__main__":
    main() 