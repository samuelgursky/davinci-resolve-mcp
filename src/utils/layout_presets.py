#!/usr/bin/env python3
"""
DaVinci Resolve MCP Server - Layout Presets Utilities

This module provides functions for working with DaVinci Resolve UI layout presets:
- Saving layout presets
- Loading layout presets
- Exporting/importing preset files
- Managing layout configurations
"""

import os
import json
import logging
from typing import Dict, List, Any, Optional, Union

# Configure logging
logger = logging.getLogger("davinci-resolve-mcp.layout_presets")

# Default preset locations by platform
DEFAULT_PRESET_PATHS = {
    "darwin": "~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Presets/",
    "win32": "C:\\ProgramData\\Blackmagic Design\\DaVinci Resolve\\Presets\\",
    "linux": "~/.local/share/DaVinciResolve/Presets/",
}


def get_layout_preset_path(platform: str = None) -> str:
    """
    Get the path to layout presets for the current platform.

    Args:
        platform: Override the detected platform (darwin, win32, linux)

    Returns:
        Path to the layout presets directory
    """
    import platform as platform_module
    import os

    # Determine platform if not specified
    if platform is None:
        platform = platform_module.system().lower()
        if platform == "darwin":
            platform = "darwin"
        elif platform == "windows":
            platform = "win32"
        elif platform == "linux":
            platform = "linux"
        else:
            platform = "darwin"  # Default to macOS if unknown

    # Get default path for platform
    preset_path = DEFAULT_PRESET_PATHS.get(platform, DEFAULT_PRESET_PATHS["darwin"])

    # Expand user directory if needed
    preset_path = os.path.expanduser(preset_path)

    # Ensure directory exists
    if not os.path.exists(preset_path):
        os.makedirs(preset_path, exist_ok=True)

    return preset_path


def get_ui_layout_path(preset_path: str = None) -> str:
    """
    Get the path to UI layout presets.

    Args:
        preset_path: Base preset directory path (determined automatically if None)

    Returns:
        Path to the UI layout presets directory
    """
    if preset_path is None:
        preset_path = get_layout_preset_path()

    # UI layouts are in a specific subdirectory
    ui_layout_path = os.path.join(preset_path, "UILayouts")

    # Ensure directory exists
    if not os.path.exists(ui_layout_path):
        os.makedirs(ui_layout_path, exist_ok=True)

    return ui_layout_path


def list_layout_presets(layout_type: str = "ui") -> List[Dict[str, Any]]:
    """
    List available layout presets.

    Args:
        layout_type: Type of layout presets to list ('ui', 'window', 'workspace')

    Returns:
        List of preset information dictionaries
    """
    # Get appropriate preset directory
    if layout_type.lower() == "ui":
        preset_dir = get_ui_layout_path()
    else:
        # Other layout types would be handled here
        preset_dir = get_ui_layout_path()

    # List files in the directory
    if not os.path.exists(preset_dir):
        return []

    presets = []
    for filename in os.listdir(preset_dir):
        # Only include layout preset files
        if filename.endswith(".layout"):
            preset_path = os.path.join(preset_dir, filename)
            presets.append(
                {
                    "name": os.path.splitext(filename)[0],
                    "path": preset_path,
                    "type": layout_type,
                    "size": os.path.getsize(preset_path),
                }
            )

    return presets


def save_layout_preset(resolve_obj, preset_name: str, layout_type: str = "ui") -> bool:
    """
    Save the current layout as a preset.

    Args:
        resolve_obj: DaVinci Resolve API object
        preset_name: Name for the saved preset
        layout_type: Type of layout to save ('ui', 'window', 'workspace')

    Returns:
        True if successful, False otherwise
    """
    try:
        # Ensure preset name has no spaces or special characters
        safe_name = preset_name.replace(" ", "_").replace("/", "_").replace("\\", "_")

        # Different layout types have different save methods
        if layout_type.lower() == "ui":
            # For UI layouts, use the UI Manager
            ui_manager = resolve_obj.GetUIManager()
            if not ui_manager:
                logger.error("Failed to get UI Manager")
                return False

            # Save the current UI layout
            return ui_manager.SaveUILayout(safe_name)
        else:
            # Other layout types would be handled here
            logger.error(f"Unsupported layout type: {layout_type}")
            return False
    except Exception as e:
        logger.error(f"Error saving layout preset: {str(e)}")
        return False


def load_layout_preset(resolve_obj, preset_name: str, layout_type: str = "ui") -> bool:
    """
    Load a layout preset.

    Args:
        resolve_obj: DaVinci Resolve API object
        preset_name: Name of the preset to load
        layout_type: Type of layout to load ('ui', 'window', 'workspace')

    Returns:
        True if successful, False otherwise
    """
    try:
        # Different layout types have different load methods
        if layout_type.lower() == "ui":
            # For UI layouts, use the UI Manager
            ui_manager = resolve_obj.GetUIManager()
            if not ui_manager:
                logger.error("Failed to get UI Manager")
                return False

            # Load the specified UI layout
            return ui_manager.LoadUILayout(preset_name)
        else:
            # Other layout types would be handled here
            logger.error(f"Unsupported layout type: {layout_type}")
            return False
    except Exception as e:
        logger.error(f"Error loading layout preset: {str(e)}")
        return False


def export_layout_preset(
    preset_name: str, export_path: str, layout_type: str = "ui"
) -> bool:
    """
    Export a layout preset to a file.

    Args:
        preset_name: Name of the preset to export
        export_path: Path to export the preset file to
        layout_type: Type of layout to export ('ui', 'window', 'workspace')

    Returns:
        True if successful, False otherwise
    """
    try:
        # Get the source preset path
        if layout_type.lower() == "ui":
            preset_dir = get_ui_layout_path()
        else:
            # Other layout types would be handled here
            preset_dir = get_ui_layout_path()

        # Construct source and destination paths
        source_path = os.path.join(preset_dir, f"{preset_name}.layout")

        # Ensure source file exists
        if not os.path.exists(source_path):
            logger.error(f"Preset file not found: {source_path}")
            return False

        # Ensure destination directory exists
        export_dir = os.path.dirname(export_path)
        if export_dir and not os.path.exists(export_dir):
            os.makedirs(export_dir, exist_ok=True)

        # Copy the preset file
        import shutil

        shutil.copy2(source_path, export_path)

        return True
    except Exception as e:
        logger.error(f"Error exporting layout preset: {str(e)}")
        return False


def import_layout_preset(
    import_path: str, preset_name: str = None, layout_type: str = "ui"
) -> bool:
    """
    Import a layout preset from a file.

    Args:
        import_path: Path to the preset file to import
        preset_name: Name to save the imported preset as (uses filename if None)
        layout_type: Type of layout to import ('ui', 'window', 'workspace')

    Returns:
        True if successful, False otherwise
    """
    try:
        # Ensure source file exists
        if not os.path.exists(import_path):
            logger.error(f"Import file not found: {import_path}")
            return False

        # Get the destination preset path
        if layout_type.lower() == "ui":
            preset_dir = get_ui_layout_path()
        else:
            # Other layout types would be handled here
            preset_dir = get_ui_layout_path()

        # Use filename as preset name if not specified
        if preset_name is None:
            preset_name = os.path.splitext(os.path.basename(import_path))[0]

        # Ensure preset name has no spaces or special characters
        safe_name = preset_name.replace(" ", "_").replace("/", "_").replace("\\", "_")

        # Construct destination path
        dest_path = os.path.join(preset_dir, f"{safe_name}.layout")

        # Copy the preset file
        import shutil

        shutil.copy2(import_path, dest_path)

        return True
    except Exception as e:
        logger.error(f"Error importing layout preset: {str(e)}")
        return False


def delete_layout_preset(preset_name: str, layout_type: str = "ui") -> bool:
    """
    Delete a layout preset.

    Args:
        preset_name: Name of the preset to delete
        layout_type: Type of layout to delete ('ui', 'window', 'workspace')

    Returns:
        True if successful, False otherwise
    """
    try:
        # Get the preset path
        if layout_type.lower() == "ui":
            preset_dir = get_ui_layout_path()
        else:
            # Other layout types would be handled here
            preset_dir = get_ui_layout_path()

        # Construct the preset file path
        preset_path = os.path.join(preset_dir, f"{preset_name}.layout")

        # Ensure file exists
        if not os.path.exists(preset_path):
            logger.error(f"Preset file not found: {preset_path}")
            return False

        # Delete the file
        os.remove(preset_path)

        return True
    except Exception as e:
        logger.error(f"Error deleting layout preset: {str(e)}")
        return False
