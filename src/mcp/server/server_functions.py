"""
Server functions for DaVinci Resolve MCP
"""

# Import our new XML export function
from ...timeline_functions.export_xml import mcp_export_timeline_xml

# Import our new marker functions
from ...timeline_functions.marker_functions import (
    mcp_get_timeline_markers,
    mcp_add_timeline_marker,
    mcp_update_marker,
    mcp_delete_marker,
    mcp_delete_markers_by_color
)

# Import our new advanced media pool functions
from ...media_pool_functions.advanced_media_pool import (
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

# Import our new color correction functions
from ...color_functions.color_correction import (
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

def register_functions(self):
    """Register all available MCP functions"""
    
    # Original timeline functions
    timeline_functions = {
        # Existing timeline functions
        # [Keep any existing timeline functions]
        
        # Timeline marker functions
        'mcp_get_timeline_markers': mcp_get_timeline_markers,
        'mcp_add_timeline_marker': mcp_add_timeline_marker,
        'mcp_update_marker': mcp_update_marker,
        'mcp_delete_marker': mcp_delete_marker,
        'mcp_delete_markers_by_color': mcp_delete_markers_by_color,
        'mcp_export_timeline_xml': mcp_export_timeline_xml,
    }
    
    # Media pool functions
    media_pool_functions = {
        # Existing media pool functions
        # [Keep any existing media pool functions]
        
        # Advanced folder navigation
        'mcp_get_folder_hierarchy': mcp_get_folder_hierarchy,
        'mcp_get_folder_by_path': mcp_get_folder_by_path,
        'mcp_create_folder_path': mcp_create_folder_path,
        'mcp_set_current_folder': mcp_set_current_folder,
        'mcp_get_current_folder': mcp_get_current_folder,
        
        # Bulk operations
        'mcp_move_clips_between_folders': mcp_move_clips_between_folders,
        'mcp_bulk_set_clip_property': mcp_bulk_set_clip_property,
        'mcp_import_files_to_folder': mcp_import_files_to_folder,
        
        # Smart bins
        'mcp_create_smart_bin': mcp_create_smart_bin,
        'mcp_get_smart_bins': mcp_get_smart_bins,
        'mcp_delete_smart_bin': mcp_delete_smart_bin
    }
    
    # Color correction functions
    color_functions = {
        # Node management
        'mcp_get_current_node_index': mcp_get_current_node_index,
        'mcp_set_current_node_index': mcp_set_current_node_index,
        'mcp_add_serial_node': mcp_add_serial_node,
        'mcp_add_parallel_node': mcp_add_parallel_node,
        'mcp_add_layer_node': mcp_add_layer_node,
        'mcp_delete_current_node': mcp_delete_current_node,
        'mcp_reset_current_node': mcp_reset_current_node,
        'mcp_get_node_list': mcp_get_node_list,
        
        # Primary color correction
        'mcp_get_primary_correction': mcp_get_primary_correction,
        'mcp_set_primary_correction': mcp_set_primary_correction,
        'mcp_get_node_label': mcp_get_node_label,
        'mcp_set_node_label': mcp_set_node_label,
        'mcp_get_node_color': mcp_get_node_color,
        'mcp_set_node_color': mcp_set_node_color,
        
        # LUT operations
        'mcp_import_lut': mcp_import_lut,
        'mcp_apply_lut_to_current_node': mcp_apply_lut_to_current_node
    }
    
    # Combine all function dictionaries
    all_functions = {}
    all_functions.update(timeline_functions)
    all_functions.update(media_pool_functions)
    all_functions.update(color_functions)
    
    # Add all functions to the server
    for function_name, function in all_functions.items():
        self.add_function(function_name, function)
    
    return True 