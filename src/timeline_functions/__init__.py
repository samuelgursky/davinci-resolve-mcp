"""
Timeline functions for DaVinci Resolve MCP

This package contains various modules for working with timelines in DaVinci Resolve:
- marker_functions: Functions for working with timeline markers
"""

# Import all public functions from submodules
from .marker_functions import (
    get_all_timeline_markers,
    add_timeline_marker,
    update_marker,
    delete_marker,
    delete_markers_by_color,
    mcp_get_timeline_markers,
    mcp_add_timeline_marker,
    mcp_update_marker,
    mcp_delete_marker,
    mcp_delete_markers_by_color
)

# Package version
__version__ = "1.0.0" 