"""
Media Pool Functions for DaVinci Resolve MCP

This package contains modules for working with the Media Pool in DaVinci Resolve:
- advanced_media_pool: Enhanced media pool functionality including folder navigation,
  bulk operations, and smart bins
"""

# Import all public functions from submodules
from .advanced_media_pool import (
    # Core functions
    get_folder_hierarchy,
    get_folder_by_path,
    create_folder_path,
    set_current_folder,
    get_current_folder,
    move_clips_between_folders,
    create_smart_bin,
    get_smart_bins,
    delete_smart_bin,
    bulk_set_clip_property,
    import_files_to_folder,
    
    # MCP interface functions
    mcp_get_folder_hierarchy,
    mcp_get_folder_by_path,
    mcp_create_folder_path,
    mcp_set_current_folder,
    mcp_get_current_folder,
    mcp_move_clips_between_folders,
    mcp_create_smart_bin,
    mcp_get_smart_bins,
    mcp_delete_smart_bin,
    mcp_bulk_set_clip_property,
    mcp_import_files_to_folder
)

# Package version
__version__ = "1.0.0" 