"""
Core Color Correction Functions for DaVinci Resolve MCP

This module provides functionality for working with color grading in DaVinci Resolve including:
- Node management (add, delete, navigate)
- Primary color correction (lift, gamma, gain)
- Node labeling and organization
- LUT operations
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Union, Tuple

from ..resolve_init import get_resolve

# ===== Helper Functions =====

def _get_color_page():
    """
    Helper function to get the current clip in the color page
    
    Returns:
        Current clip object or None if not available
    """
    resolve = get_resolve()
    if not resolve:
        return None
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return None
    
    project = project_manager.GetCurrentProject()
    if not project:
        return None
    
    # Access the color page
    page_type = resolve.GetCurrentPage()
    if page_type != "color":
        return {"error": "Not on the color page. Please switch to the color page."}
    
    # Get the current timeline
    timeline = project.GetCurrentTimeline()
    if not timeline:
        return None
    
    return timeline

def _get_current_clip_node_graph():
    """
    Helper function to get the node graph for the current clip
    
    Returns:
        Node graph object or None if not available
    """
    timeline = _get_color_page()
    if not timeline:
        return None
    
    # Get current clip
    current_item = timeline.GetCurrentVideoItem()
    if not current_item:
        return None
    
    # Get node graph
    node_graph = current_item.GetNodeGraph()
    if not node_graph:
        return None
    
    return node_graph

# ===== Node Management Functions =====

def get_current_node_index():
    """
    Get the index of the currently selected node
    
    Returns:
        Dictionary containing the current node index
    """
    node_graph = _get_current_clip_node_graph()
    if not node_graph:
        return {"error": "Could not get current clip node graph"}
    
    current_node = node_graph.GetCurrentNode()
    if not current_node:
        return {"error": "No node is currently selected"}
    
    node_index = current_node.GetNodeIndex()
    
    return {
        "status": "success",
        "node_index": node_index
    }

def set_current_node_index(index: int):
    """
    Set the current node by index
    
    Args:
        index: The index of the node to select
        
    Returns:
        Status of the operation
    """
    node_graph = _get_current_clip_node_graph()
    if not node_graph:
        return {"error": "Could not get current clip node graph"}
    
    # Get all nodes to validate index
    nodes = node_graph.GetNodeList()
    if not nodes:
        return {"error": "No nodes found in node graph"}
    
    # Check if index is valid
    if index < 1 or index > len(nodes):
        return {"error": f"Invalid node index: {index}. Valid range is 1-{len(nodes)}"}
    
    # Get the node at the specified index
    target_node = None
    for node in nodes:
        if node.GetNodeIndex() == index:
            target_node = node
            break
    
    if not target_node:
        return {"error": f"Could not find node with index {index}"}
    
    # Set the current node
    result = node_graph.SetCurrentNode(target_node)
    if not result:
        return {"error": f"Failed to set current node to index {index}"}
    
    return {
        "status": "success",
        "message": f"Current node set to index {index}"
    }

def add_serial_node():
    """
    Add a new serial node after the current node
    
    Returns:
        Status of the operation and information about the new node
    """
    node_graph = _get_current_clip_node_graph()
    if not node_graph:
        return {"error": "Could not get current clip node graph"}
    
    # Add a new serial node
    new_node = node_graph.AddSerialNode()
    if not new_node:
        return {"error": "Failed to add new serial node"}
    
    node_index = new_node.GetNodeIndex()
    
    return {
        "status": "success",
        "message": "Added new serial node",
        "node_index": node_index
    }

def add_parallel_node():
    """
    Add a new parallel node to the current node
    
    Returns:
        Status of the operation and information about the new node
    """
    node_graph = _get_current_clip_node_graph()
    if not node_graph:
        return {"error": "Could not get current clip node graph"}
    
    # Add a new parallel node
    new_node = node_graph.AddParallelNode()
    if not new_node:
        return {"error": "Failed to add new parallel node"}
    
    node_index = new_node.GetNodeIndex()
    
    return {
        "status": "success",
        "message": "Added new parallel node",
        "node_index": node_index
    }

def add_layer_node():
    """
    Add a new layer node to the current node
    
    Returns:
        Status of the operation and information about the new node
    """
    node_graph = _get_current_clip_node_graph()
    if not node_graph:
        return {"error": "Could not get current clip node graph"}
    
    # Add a new layer node
    new_node = node_graph.AddLayerNode()
    if not new_node:
        return {"error": "Failed to add new layer node"}
    
    node_index = new_node.GetNodeIndex()
    
    return {
        "status": "success",
        "message": "Added new layer node",
        "node_index": node_index
    }

def delete_current_node():
    """
    Delete the currently selected node
    
    Returns:
        Status of the operation
    """
    node_graph = _get_current_clip_node_graph()
    if not node_graph:
        return {"error": "Could not get current clip node graph"}
    
    current_node = node_graph.GetCurrentNode()
    if not current_node:
        return {"error": "No node is currently selected"}
    
    # Can't delete the first node (Node 1)
    if current_node.GetNodeIndex() == 1:
        return {"error": "Cannot delete Node 1 (first node)"}
    
    # Delete the current node
    result = node_graph.DeleteCurrentNode()
    if not result:
        return {"error": "Failed to delete current node"}
    
    return {
        "status": "success",
        "message": "Deleted current node"
    }

def reset_current_node():
    """
    Reset all grades on the current node
    
    Returns:
        Status of the operation
    """
    node_graph = _get_current_clip_node_graph()
    if not node_graph:
        return {"error": "Could not get current clip node graph"}
    
    current_node = node_graph.GetCurrentNode()
    if not current_node:
        return {"error": "No node is currently selected"}
    
    # Reset the current node
    result = current_node.ResetNode()
    if not result:
        return {"error": "Failed to reset current node"}
    
    return {
        "status": "success",
        "message": f"Reset node {current_node.GetNodeIndex()}"
    }

def get_node_list():
    """
    Get a list of all nodes in the current clip's node graph
    
    Returns:
        Dictionary containing a list of nodes with their properties
    """
    node_graph = _get_current_clip_node_graph()
    if not node_graph:
        return {"error": "Could not get current clip node graph"}
    
    nodes = node_graph.GetNodeList()
    if not nodes:
        return {"error": "No nodes found in node graph"}
    
    node_list = []
    current_node_index = -1
    
    # Get the current node index
    current_node = node_graph.GetCurrentNode()
    if current_node:
        current_node_index = current_node.GetNodeIndex()
    
    # Get information about each node
    for node in nodes:
        node_info = {
            "index": node.GetNodeIndex(),
            "label": node.GetLabel(),
            "is_current": node.GetNodeIndex() == current_node_index,
            "node_type": "Serial"  # Default, we'll try to determine actual type
        }
        
        # Try to determine node type
        try:
            if node.IsParallelNode():
                node_info["node_type"] = "Parallel"
            elif node.IsLayerNode():
                node_info["node_type"] = "Layer"
        except:
            # Some node type functions might not be available, ignore errors
            pass
        
        node_list.append(node_info)
    
    return {
        "status": "success",
        "node_count": len(node_list),
        "current_node_index": current_node_index,
        "nodes": node_list
    }

# ===== Color Correction Functions =====

def get_primary_correction():
    """
    Get the primary correction parameters of the current node
    
    Returns:
        Dictionary containing lift, gamma, and gain values
    """
    node_graph = _get_current_clip_node_graph()
    if not node_graph:
        return {"error": "Could not get current clip node graph"}
    
    current_node = node_graph.GetCurrentNode()
    if not current_node:
        return {"error": "No node is currently selected"}
    
    try:
        # Get lift, gamma, gain
        lift = {
            "red": current_node.GetLift("red"),
            "green": current_node.GetLift("green"),
            "blue": current_node.GetLift("blue"),
            "master": current_node.GetLift("master")
        }
        
        gamma = {
            "red": current_node.GetGamma("red"),
            "green": current_node.GetGamma("green"),
            "blue": current_node.GetGamma("blue"),
            "master": current_node.GetGamma("master")
        }
        
        gain = {
            "red": current_node.GetGain("red"),
            "green": current_node.GetGain("green"),
            "blue": current_node.GetGain("blue"),
            "master": current_node.GetGain("master")
        }
        
        # Try to get additional parameters if available
        contrast = {}
        saturation = 1.0
        
        try:
            contrast = {
                "red": current_node.GetContrast("red"),
                "green": current_node.GetContrast("green"),
                "blue": current_node.GetContrast("blue"),
                "master": current_node.GetContrast("master")
            }
            saturation = current_node.GetSaturation()
        except:
            # These might not be available in all API versions
            pass
        
        result = {
            "status": "success",
            "node_index": current_node.GetNodeIndex(),
            "lift": lift,
            "gamma": gamma,
            "gain": gain
        }
        
        # Add optional parameters if available
        if contrast:
            result["contrast"] = contrast
        if saturation:
            result["saturation"] = saturation
            
        return result
    except Exception as e:
        return {"error": f"Failed to get primary correction: {str(e)}"}

def set_primary_correction(
    lift: Dict[str, float] = None, 
    gamma: Dict[str, float] = None, 
    gain: Dict[str, float] = None,
    contrast: Dict[str, float] = None,
    saturation: float = None
):
    """
    Set the primary correction parameters of the current node
    
    Args:
        lift: Dictionary with red, green, blue, master values for lift
        gamma: Dictionary with red, green, blue, master values for gamma
        gain: Dictionary with red, green, blue, master values for gain
        contrast: Dictionary with red, green, blue, master values for contrast
        saturation: Float value for saturation
        
    Returns:
        Status of the operation
    """
    node_graph = _get_current_clip_node_graph()
    if not node_graph:
        return {"error": "Could not get current clip node graph"}
    
    current_node = node_graph.GetCurrentNode()
    if not current_node:
        return {"error": "No node is currently selected"}
    
    changes_made = 0
    
    try:
        # Set lift values
        if lift:
            for channel, value in lift.items():
                if channel in ["red", "green", "blue", "master"]:
                    current_node.SetLift(channel, float(value))
                    changes_made += 1
        
        # Set gamma values
        if gamma:
            for channel, value in gamma.items():
                if channel in ["red", "green", "blue", "master"]:
                    current_node.SetGamma(channel, float(value))
                    changes_made += 1
        
        # Set gain values
        if gain:
            for channel, value in gain.items():
                if channel in ["red", "green", "blue", "master"]:
                    current_node.SetGain(channel, float(value))
                    changes_made += 1
        
        # Set contrast values if available
        if contrast:
            try:
                for channel, value in contrast.items():
                    if channel in ["red", "green", "blue", "master"]:
                        current_node.SetContrast(channel, float(value))
                        changes_made += 1
            except:
                # Contrast might not be available in all API versions
                pass
        
        # Set saturation if provided
        if saturation is not None:
            try:
                current_node.SetSaturation(float(saturation))
                changes_made += 1
            except:
                # Saturation might not be available in all API versions
                pass
        
        if changes_made > 0:
            return {
                "status": "success",
                "message": f"Updated {changes_made} primary correction parameters",
                "node_index": current_node.GetNodeIndex()
            }
        else:
            return {"error": "No valid correction parameters provided"}
    
    except Exception as e:
        return {"error": f"Failed to set primary correction: {str(e)}"}

def get_node_label():
    """
    Get the label of the current node
    
    Returns:
        Dictionary containing the node label
    """
    node_graph = _get_current_clip_node_graph()
    if not node_graph:
        return {"error": "Could not get current clip node graph"}
    
    current_node = node_graph.GetCurrentNode()
    if not current_node:
        return {"error": "No node is currently selected"}
    
    label = current_node.GetLabel()
    
    return {
        "status": "success",
        "node_index": current_node.GetNodeIndex(),
        "label": label
    }

def set_node_label(label: str):
    """
    Set the label of the current node
    
    Args:
        label: The new label for the node
        
    Returns:
        Status of the operation
    """
    node_graph = _get_current_clip_node_graph()
    if not node_graph:
        return {"error": "Could not get current clip node graph"}
    
    current_node = node_graph.GetCurrentNode()
    if not current_node:
        return {"error": "No node is currently selected"}
    
    result = current_node.SetLabel(label)
    
    if not result:
        return {"error": "Failed to set node label"}
    
    return {
        "status": "success",
        "message": f"Set label for node {current_node.GetNodeIndex()} to '{label}'"
    }

def get_node_color():
    """
    Get the tile color of the current node
    
    Returns:
        Dictionary containing the node color
    """
    node_graph = _get_current_clip_node_graph()
    if not node_graph:
        return {"error": "Could not get current clip node graph"}
    
    current_node = node_graph.GetCurrentNode()
    if not current_node:
        return {"error": "No node is currently selected"}
    
    # The color is usually represented as an RGBA tuple
    try:
        color = current_node.GetTileColor()
        color_dict = {"red": 0, "green": 0, "blue": 0, "alpha": 0}
        
        if isinstance(color, tuple) and len(color) >= 3:
            color_dict["red"] = color[0]
            color_dict["green"] = color[1]
            color_dict["blue"] = color[2]
            if len(color) > 3:
                color_dict["alpha"] = color[3]
        
        return {
            "status": "success",
            "node_index": current_node.GetNodeIndex(),
            "color": color_dict
        }
    except:
        # Color might not be available in all API versions
        return {"error": "Failed to get node color"}

def set_node_color(red: float, green: float, blue: float, alpha: float = 1.0):
    """
    Set the tile color of the current node
    
    Args:
        red: Red component (0-1)
        green: Green component (0-1)
        blue: Blue component (0-1)
        alpha: Alpha component (0-1)
        
    Returns:
        Status of the operation
    """
    node_graph = _get_current_clip_node_graph()
    if not node_graph:
        return {"error": "Could not get current clip node graph"}
    
    current_node = node_graph.GetCurrentNode()
    if not current_node:
        return {"error": "No node is currently selected"}
    
    # Ensure values are in valid range
    red = max(0.0, min(1.0, float(red)))
    green = max(0.0, min(1.0, float(green)))
    blue = max(0.0, min(1.0, float(blue)))
    alpha = max(0.0, min(1.0, float(alpha)))
    
    try:
        result = current_node.SetTileColor((red, green, blue, alpha))
        
        if not result:
            return {"error": "Failed to set node color"}
        
        return {
            "status": "success",
            "message": f"Set color for node {current_node.GetNodeIndex()}"
        }
    except:
        # SetTileColor might not be available in all API versions
        return {"error": "Failed to set node color, function not supported"}

# ===== LUT Operations =====

def import_lut(lut_path: str):
    """
    Import a LUT file
    
    Args:
        lut_path: Path to the LUT file
        
    Returns:
        Status of the operation
    """
    node_graph = _get_current_clip_node_graph()
    if not node_graph:
        return {"error": "Could not get current clip node graph"}
    
    # Check if file exists
    if not os.path.exists(lut_path):
        return {"error": f"LUT file not found: {lut_path}"}
    
    # Check file extension
    valid_extensions = [".cube", ".3dl", ".mga", ".dat"]
    if not any(lut_path.lower().endswith(ext) for ext in valid_extensions):
        return {"error": f"Invalid LUT file format. Supported formats: {', '.join(valid_extensions)}"}
    
    # Try to import the LUT
    try:
        result = node_graph.ImportLUT(lut_path)
        
        if not result:
            return {"error": f"Failed to import LUT: {lut_path}"}
        
        return {
            "status": "success",
            "message": f"Imported LUT: {os.path.basename(lut_path)}"
        }
    except:
        return {"error": f"Failed to import LUT, function not supported"}

def apply_lut_to_current_node(lut_path: str):
    """
    Apply a LUT to the current node
    
    Args:
        lut_path: Path to the LUT file
        
    Returns:
        Status of the operation
    """
    node_graph = _get_current_clip_node_graph()
    if not node_graph:
        return {"error": "Could not get current clip node graph"}
    
    current_node = node_graph.GetCurrentNode()
    if not current_node:
        return {"error": "No node is currently selected"}
    
    # Check if file exists
    if not os.path.exists(lut_path):
        return {"error": f"LUT file not found: {lut_path}"}
    
    # Check file extension
    valid_extensions = [".cube", ".3dl", ".mga", ".dat"]
    if not any(lut_path.lower().endswith(ext) for ext in valid_extensions):
        return {"error": f"Invalid LUT file format. Supported formats: {', '.join(valid_extensions)}"}
    
    # Try to apply the LUT
    try:
        # Import the LUT first
        import_result = node_graph.ImportLUT(lut_path)
        if not import_result:
            return {"error": f"Failed to import LUT: {lut_path}"}
        
        # Get LUT name (filename without extension)
        lut_name = os.path.splitext(os.path.basename(lut_path))[0]
        
        # Apply LUT to current node
        result = current_node.ApplyLUT(lut_name)
        
        if not result:
            return {"error": f"Failed to apply LUT to node {current_node.GetNodeIndex()}"}
        
        return {
            "status": "success",
            "message": f"Applied LUT '{lut_name}' to node {current_node.GetNodeIndex()}"
        }
    except:
        return {"error": f"Failed to apply LUT, function not supported"}

# ===== MCP Interface Functions =====

def mcp_get_current_node_index(args: dict = None):
    """MCP function to get the index of the currently selected node"""
    result = get_current_node_index()
    return json.dumps(result)

def mcp_set_current_node_index(args: dict):
    """MCP function to set the current node by index"""
    if not args or "index" not in args:
        return json.dumps({"error": "Missing required parameter: index"})
    
    try:
        index = int(args["index"])
    except:
        return json.dumps({"error": "Invalid index parameter, must be an integer"})
    
    result = set_current_node_index(index)
    return json.dumps(result)

def mcp_add_serial_node(args: dict = None):
    """MCP function to add a new serial node after the current node"""
    result = add_serial_node()
    return json.dumps(result)

def mcp_add_parallel_node(args: dict = None):
    """MCP function to add a new parallel node to the current node"""
    result = add_parallel_node()
    return json.dumps(result)

def mcp_add_layer_node(args: dict = None):
    """MCP function to add a new layer node to the current node"""
    result = add_layer_node()
    return json.dumps(result)

def mcp_delete_current_node(args: dict = None):
    """MCP function to delete the currently selected node"""
    result = delete_current_node()
    return json.dumps(result)

def mcp_reset_current_node(args: dict = None):
    """MCP function to reset all grades on the current node"""
    result = reset_current_node()
    return json.dumps(result)

def mcp_get_node_list(args: dict = None):
    """MCP function to get a list of all nodes in the current clip's node graph"""
    result = get_node_list()
    return json.dumps(result)

def mcp_get_primary_correction(args: dict = None):
    """MCP function to get the primary correction parameters of the current node"""
    result = get_primary_correction()
    return json.dumps(result)

def mcp_set_primary_correction(args: dict):
    """MCP function to set the primary correction parameters of the current node"""
    if not args:
        return json.dumps({"error": "Missing correction parameters"})
    
    lift = args.get("lift")
    gamma = args.get("gamma")
    gain = args.get("gain")
    contrast = args.get("contrast")
    saturation = args.get("saturation")
    
    result = set_primary_correction(lift, gamma, gain, contrast, saturation)
    return json.dumps(result)

def mcp_get_node_label(args: dict = None):
    """MCP function to get the label of the current node"""
    result = get_node_label()
    return json.dumps(result)

def mcp_set_node_label(args: dict):
    """MCP function to set the label of the current node"""
    if not args or "label" not in args:
        return json.dumps({"error": "Missing required parameter: label"})
    
    label = args["label"]
    result = set_node_label(label)
    return json.dumps(result)

def mcp_get_node_color(args: dict = None):
    """MCP function to get the tile color of the current node"""
    result = get_node_color()
    return json.dumps(result)

def mcp_set_node_color(args: dict):
    """MCP function to set the tile color of the current node"""
    if not args:
        return json.dumps({"error": "Missing color parameters"})
    
    try:
        red = float(args.get("red", 0))
        green = float(args.get("green", 0))
        blue = float(args.get("blue", 0))
        alpha = float(args.get("alpha", 1.0))
    except:
        return json.dumps({"error": "Invalid color parameters, must be numeric"})
    
    result = set_node_color(red, green, blue, alpha)
    return json.dumps(result)

def mcp_import_lut(args: dict):
    """MCP function to import a LUT file"""
    if not args or "path" not in args:
        return json.dumps({"error": "Missing required parameter: path"})
    
    lut_path = args["path"]
    result = import_lut(lut_path)
    return json.dumps(result)

def mcp_apply_lut_to_current_node(args: dict):
    """MCP function to apply a LUT to the current node"""
    if not args or "path" not in args:
        return json.dumps({"error": "Missing required parameter: path"})
    
    lut_path = args["path"]
    result = apply_lut_to_current_node(lut_path)
    return json.dumps(result) 