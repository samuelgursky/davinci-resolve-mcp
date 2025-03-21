"""
Color Correction Functions for DaVinci Resolve MCP

This package contains modules for working with color grading in DaVinci Resolve:
- color_correction: Core color grading functionality including primary corrections, 
  node management, and LUT operations
- color_presets: Functions for saving, loading, and applying color presets
- scopes: Functions for working with video scopes data
"""

# Import all public functions from submodules
from .color_correction import (
    # Core functions
    get_current_node_index,
    set_current_node_index,
    add_serial_node,
    add_parallel_node,
    add_layer_node,
    delete_current_node,
    reset_current_node,
    get_node_list,
    
    # Node color correction
    get_primary_correction,
    set_primary_correction,
    get_node_label,
    set_node_label,
    get_node_color,
    set_node_color,
    
    # LUT operations
    import_lut,
    apply_lut_to_current_node,
    
    # MCP interface functions
    mcp_get_current_node_index,
    mcp_set_current_node_index,
    mcp_add_serial_node,
    mcp_add_parallel_node,
    mcp_add_layer_node,
    mcp_delete_current_node,
    mcp_reset_current_node,
    mcp_get_node_list,
    mcp_get_primary_correction,
    mcp_set_primary_correction,
    mcp_get_node_label,
    mcp_set_node_label,
    mcp_get_node_color,
    mcp_set_node_color,
    mcp_import_lut,
    mcp_apply_lut_to_current_node
)

# Package version
__version__ = "1.0.0" 