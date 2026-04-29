"""Resolve control resources, inspection helpers, and app-level tools."""

from src.granular.common import *  # noqa: F401,F403

resolve = ResolveProxy()

@mcp.resource("resolve://version")
def get_resolve_version() -> str:
    """Get DaVinci Resolve version information."""
    resolve = get_resolve()
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    return f"{resolve.GetProductName()} {resolve.GetVersionString()}"


@mcp.resource("resolve://current-page")
def get_current_page() -> str:
    """Get the current page open in DaVinci Resolve (Edit, Color, Fusion, etc.)."""
    resolve = get_resolve()
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    return resolve.GetCurrentPage()


@mcp.tool()
def switch_page(page: str) -> str:
    """Switch to a specific page in DaVinci Resolve.
    
    Args:
        page: The page to switch to. Options: 'media', 'cut', 'edit', 'fusion', 'color', 'fairlight', 'deliver'
    """
    resolve = get_resolve()
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    valid_pages = ['media', 'cut', 'edit', 'fusion', 'color', 'fairlight', 'deliver']
    page = page.lower()
    
    if page not in valid_pages:
        return f"Error: Invalid page name. Must be one of: {', '.join(valid_pages)}"
    
    result = resolve.OpenPage(page)
    if result:
        return f"Successfully switched to {page} page"
    else:
        return f"Failed to switch to {page} page"


@mcp.resource("resolve://inspect/resolve")
def inspect_resolve_object() -> Dict[str, Any]:
    """Inspect the main resolve object and return its methods and properties."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    
    return inspect_object(resolve)


@mcp.resource("resolve://inspect/project-manager")
def inspect_project_manager_object() -> Dict[str, Any]:
    """Inspect the project manager object and return its methods and properties."""
    project_manager = get_project_manager()
    if not project_manager:
        return {"error": "Failed to get Project Manager"}
    
    return inspect_object(project_manager)


@mcp.resource("resolve://inspect/current-project")
def inspect_current_project_object() -> Dict[str, Any]:
    """Inspect the current project object and return its methods and properties."""
    pm, current_project = get_current_project()
    if not current_project:
        return {"error": "No project currently open"}
    
    return inspect_object(current_project)


@mcp.resource("resolve://inspect/media-pool")
def inspect_media_pool_object() -> Dict[str, Any]:
    """Inspect the media pool object and return its methods and properties."""
    pm, current_project = get_current_project()
    if not current_project:
        return {"error": "No project currently open"}
    
    media_pool = current_project.GetMediaPool()
    if not media_pool:
        return {"error": "Failed to get Media Pool"}
    
    return inspect_object(media_pool)


@mcp.resource("resolve://inspect/current-timeline")
def inspect_current_timeline_object() -> Dict[str, Any]:
    """Inspect the current timeline object and return its methods and properties."""
    pm, current_project = get_current_project()
    if not current_project:
        return {"error": "No project currently open"}
    
    current_timeline = current_project.GetCurrentTimeline()
    if not current_timeline:
        return {"error": "No timeline currently active"}
    
    return inspect_object(current_timeline)


@mcp.tool()
def object_help(object_type: str) -> str:
    """
    Get human-readable help for a DaVinci Resolve API object.
    
    Args:
        object_type: Type of object to get help for ('resolve', 'project_manager', 
                     'project', 'media_pool', 'timeline', 'media_storage')
    """
    resolve = get_resolve()
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    # Map object type string to actual object
    obj = None
    
    if object_type == 'resolve':
        obj = resolve
    elif object_type == 'project_manager':
        obj = resolve.GetProjectManager()
    elif object_type == 'project':
        pm = resolve.GetProjectManager()
        if pm:
            obj = pm.GetCurrentProject()
    elif object_type == 'media_pool':
        pm = resolve.GetProjectManager()
        if pm:
            project = pm.GetCurrentProject()
            if project:
                obj = project.GetMediaPool()
    elif object_type == 'timeline':
        pm = resolve.GetProjectManager()
        if pm:
            project = pm.GetCurrentProject()
            if project:
                obj = project.GetCurrentTimeline()
    elif object_type == 'media_storage':
        obj = resolve.GetMediaStorage()
    else:
        return f"Error: Unknown object type '{object_type}'"
    
    if obj is None:
        return f"Error: Failed to get {object_type} object"
    
    # Generate and return help text
    return print_object_help(obj)


@mcp.tool()
def inspect_custom_object(object_path: str) -> Dict[str, Any]:
    """
    Inspect a custom DaVinci Resolve API object by path.
    
    Args:
        object_path: Path to the object using dot notation (e.g., 'resolve.GetMediaStorage()')
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    
    try:
        # Start with resolve object
        obj = resolve
        
        # Split the path and traverse down
        parts = object_path.split('.')
        
        # Skip the first part if it's 'resolve'
        start_index = 1 if parts[0].lower() == 'resolve' else 0
        
        for i in range(start_index, len(parts)):
            part = parts[i]
            
            # Check if it's a method call
            if part.endswith('()'):
                method_name = part[:-2]
                if hasattr(obj, method_name) and callable(getattr(obj, method_name)):
                    obj = getattr(obj, method_name)()
                else:
                    return {"error": f"Method '{method_name}' not found or not callable"}
            else:
                # It's an attribute access
                if hasattr(obj, part):
                    obj = getattr(obj, part)
                else:
                    return {"error": f"Attribute '{part}' not found"}
        
        # Inspect the object we've retrieved
        return inspect_object(obj)
    except Exception as e:
        return {"error": f"Error inspecting object: {str(e)}"}


@mcp.resource("resolve://layout-presets")
def get_layout_presets() -> List[Dict[str, Any]]:
    """Get all available layout presets for DaVinci Resolve."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    
    return list_layout_presets(layout_type="ui")


@mcp.tool()
def save_layout_preset_tool(preset_name: str) -> Dict[str, Any]:
    """Save the current UI layout as a preset.

    Calls Resolve.SaveLayoutPreset() to save the current UI layout.

    Args:
        preset_name: Name for the saved preset.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    result = resolve.SaveLayoutPreset(preset_name)
    return {"success": bool(result), "preset_name": preset_name}


@mcp.tool()
def load_layout_preset_tool(preset_name: str) -> Dict[str, Any]:
    """Load a UI layout preset.

    Calls Resolve.LoadLayoutPreset() to load a saved UI layout.

    Args:
        preset_name: Name of the preset to load.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    result = resolve.LoadLayoutPreset(preset_name)
    return {"success": bool(result), "preset_name": preset_name}


@mcp.tool()
def export_layout_preset_tool(preset_name: str, export_path: str) -> Dict[str, Any]:
    """Export a layout preset to a file.

    Calls Resolve.ExportLayoutPreset() to export a preset to disk.

    Args:
        preset_name: Name of the preset to export.
        export_path: Absolute file path to export the preset to.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    result = resolve.ExportLayoutPreset(preset_name, export_path)
    return {"success": bool(result), "preset_name": preset_name, "export_path": export_path}


@mcp.tool()
def import_layout_preset_tool(import_path: str, preset_name: str = None) -> Dict[str, Any]:
    """Import a layout preset from a file.

    Calls Resolve.ImportLayoutPreset() to import a preset from disk.

    Args:
        import_path: Absolute path to the preset file to import.
        preset_name: Name to save the imported preset as (uses filename if None).
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    if preset_name:
        result = resolve.ImportLayoutPreset(import_path, preset_name)
    else:
        result = resolve.ImportLayoutPreset(import_path)
        preset_name = os.path.splitext(os.path.basename(import_path))[0]
    return {"success": bool(result), "preset_name": preset_name, "import_path": import_path}


@mcp.tool()
def delete_layout_preset_tool(preset_name: str) -> Dict[str, Any]:
    """Delete a layout preset.

    Calls Resolve.DeleteLayoutPreset() to remove a saved preset.

    Args:
        preset_name: Name of the preset to delete.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    result = resolve.DeleteLayoutPreset(preset_name)
    return {"success": bool(result), "preset_name": preset_name}


@mcp.resource("resolve://app/state")
def get_app_state_endpoint() -> Dict[str, Any]:
    """Get DaVinci Resolve application state information."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve", "connected": False}
    
    return get_app_state(resolve)


@mcp.tool()
def quit_app(force: bool = False, save_project: bool = True) -> str:
    """
    Quit DaVinci Resolve application.
    
    Args:
        force: Whether to force quit even if unsaved changes (potentially dangerous)
        save_project: Whether to save the project before quitting
    """
    resolve = get_resolve()
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    result = quit_resolve_app(resolve, force, save_project)
    
    if result:
        return "DaVinci Resolve quit command sent successfully"
    else:
        return "Failed to quit DaVinci Resolve"


@mcp.tool()
def restart_app(wait_seconds: int = 5) -> str:
    """
    Restart DaVinci Resolve application.
    
    Args:
        wait_seconds: Seconds to wait between quit and restart
    """
    resolve = get_resolve()
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    result = restart_resolve_app(resolve, wait_seconds)
    
    if result:
        return "DaVinci Resolve restart initiated successfully"
    else:
        return "Failed to restart DaVinci Resolve"


@mcp.tool()
def open_settings() -> str:
    """Open the Project Settings dialog in DaVinci Resolve."""
    resolve = get_resolve()
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    result = open_project_settings(resolve)
    
    if result:
        return "Project Settings dialog opened successfully"
    else:
        return "Failed to open Project Settings dialog"


@mcp.tool()
def open_app_preferences() -> str:
    """Open the Preferences dialog in DaVinci Resolve."""
    resolve = get_resolve()
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    result = open_preferences(resolve)
    
    if result:
        return "Preferences dialog opened successfully"
    else:
        return "Failed to open Preferences dialog"


@mcp.tool()
def get_resolve_version_fields() -> Dict[str, Any]:
    """Get DaVinci Resolve version as structured fields [major, minor, patch, build, suffix]."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    version = resolve.GetVersion()
    if version:
        return {"major": version[0], "minor": version[1], "patch": version[2], "build": version[3], "suffix": version[4] if len(version) > 4 else ""}
    return {"error": "Failed to get version"}


@mcp.tool()
def get_fusion_object() -> Dict[str, Any]:
    """Get the Fusion object. Starting point for Fusion scripts."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    fusion = resolve.Fusion()
    if fusion:
        return {"success": True, "fusion_available": True}
    return {"success": False, "fusion_available": False}


@mcp.tool()
def update_layout_preset(preset_name: str) -> Dict[str, Any]:
    """Overwrite an existing layout preset with the current UI layout.

    Args:
        preset_name: Name of the preset to overwrite.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    result = resolve.UpdateLayoutPreset(preset_name)
    return {"success": bool(result), "preset_name": preset_name}


@mcp.tool()
def import_render_preset(preset_path: str) -> Dict[str, Any]:
    """Import a render preset from a file.

    Args:
        preset_path: Absolute path to the render preset file.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    result = resolve.ImportRenderPreset(preset_path)
    return {"success": bool(result), "preset_path": preset_path}


@mcp.tool()
def export_render_preset(preset_name: str, export_path: str) -> Dict[str, Any]:
    """Export a render preset to a file.

    Args:
        preset_name: Name of the render preset to export.
        export_path: Absolute path where the preset file will be saved.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    result = resolve.ExportRenderPreset(preset_name, export_path)
    return {"success": bool(result), "preset_name": preset_name, "export_path": export_path}


@mcp.tool()
def import_burn_in_preset(preset_path: str) -> Dict[str, Any]:
    """Import a burn-in preset from a file.

    Args:
        preset_path: Absolute path to the burn-in preset file.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    result = resolve.ImportBurnInPreset(preset_path)
    return {"success": bool(result), "preset_path": preset_path}


@mcp.tool()
def export_burn_in_preset(preset_name: str, export_path: str) -> Dict[str, Any]:
    """Export a burn-in preset to a file.

    Args:
        preset_name: Name of the burn-in preset to export.
        export_path: Absolute path where the preset file will be saved.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    result = resolve.ExportBurnInPreset(preset_name, export_path)
    return {"success": bool(result), "preset_name": preset_name, "export_path": export_path}


@mcp.tool()
def get_keyframe_mode() -> Dict[str, Any]:
    """Get the current keyframe mode in Resolve. Returns 0=ALL, 1=COLOR, 2=SIZING."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    mode = resolve.GetKeyframeMode()
    mode_names = {0: "All", 1: "Color", 2: "Sizing"}
    return {"keyframe_mode": mode, "mode_name": mode_names.get(mode, "Unknown")}


@mcp.tool()
def set_keyframe_mode(mode: int) -> Dict[str, Any]:
    """Set the keyframe mode in Resolve.

    Args:
        mode: Keyframe mode - 0=All, 1=Color, 2=Sizing.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    if mode not in (0, 1, 2):
        return {"error": "Invalid mode. Must be 0 (All), 1 (Color), or 2 (Sizing)"}
    result = resolve.SetKeyframeMode(mode)
    mode_names = {0: "All", 1: "Color", 2: "Sizing"}
    return {"success": bool(result), "keyframe_mode": mode, "mode_name": mode_names[mode]}


@mcp.tool()
def get_fairlight_presets() -> Dict[str, Any]:
    """Get the available Fairlight preset names."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    missing = _requires_method(resolve, "GetFairlightPresets", "20.2.2")
    if missing:
        return missing
    presets = resolve.GetFairlightPresets()
    return {"presets": presets if presets else []}


@mcp.tool()
def quit_resolve() -> Dict[str, Any]:
    """Quit DaVinci Resolve. WARNING: This will close the application."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    result = resolve.Quit()
    return {"success": True, "message": "DaVinci Resolve is quitting"}
