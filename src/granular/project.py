"""Project, render, cache, cloud, and project-property tools."""

from src.granular.common import *  # noqa: F401,F403

resolve = ResolveProxy()

@mcp.resource("resolve://projects")
def list_projects() -> List[str]:
    """List all available projects in the current database."""
    project_manager = get_project_manager()
    if not project_manager:
        return ["Error: Failed to get Project Manager"]
    
    projects = project_manager.GetProjectListInCurrentFolder()
    
    # Filter out any empty strings that might be in the list
    return [p for p in projects if p]


@mcp.resource("resolve://current-project")
def get_current_project_name() -> str:
    """Get the name of the currently open project."""
    pm, current_project = get_current_project()
    if not current_project:
        return "No project currently open"
    
    return current_project.GetName()


@mcp.resource("resolve://project-settings")
def get_project_settings() -> Dict[str, Any]:
    """Get all project settings from the current project."""
    pm, current_project = get_current_project()
    if not current_project:
        return {"error": "No project currently open"}
    
    try:
        # Get all settings
        return current_project.GetSetting('')
    except Exception as e:
        return {"error": f"Failed to get project settings: {str(e)}"}


@mcp.resource("resolve://project-setting/{setting_name}")
def get_project_setting(setting_name: str) -> Dict[str, Any]:
    """Get a specific project setting by name.
    
    Args:
        setting_name: The specific setting to retrieve.
    """
    pm, current_project = get_current_project()
    if not current_project:
        return {"error": "No project currently open"}
    
    try:
        # Get specific setting
        value = current_project.GetSetting(setting_name)
        return {setting_name: value}
    except Exception as e:
        return {"error": f"Failed to get project setting '{setting_name}': {str(e)}"}


@mcp.tool()
def set_project_setting(setting_name: str, setting_value: Any) -> str:
    """Set a project setting to the specified value.
    
    Args:
        setting_name: The name of the setting to change
        setting_value: The new value for the setting (can be string, integer, float, or boolean)
    """
    pm, current_project = get_current_project()
    if not current_project:
        return "Error: No project currently open"
    
    try:
        # Convert setting_value to string if it's not already
        if not isinstance(setting_value, str):
            setting_value = str(setting_value)
            
        # Try to determine if this should be a numeric value
        # DaVinci Resolve sometimes expects numeric values for certain settings
        try:
            # Check if it's a number in string form
            if setting_value.isdigit() or (setting_value.startswith('-') and setting_value[1:].isdigit()):
                # It's an integer
                numeric_value = int(setting_value)
                # Try with numeric value first
                if current_project.SetSetting(setting_name, numeric_value):
                    return f"Successfully set project setting '{setting_name}' to numeric value {numeric_value}"
            elif '.' in setting_value and setting_value.replace('.', '', 1).replace('-', '', 1).isdigit():
                # It's a float
                numeric_value = float(setting_value)
                # Try with float value
                if current_project.SetSetting(setting_name, numeric_value):
                    return f"Successfully set project setting '{setting_name}' to numeric value {numeric_value}"
        except (ValueError, TypeError):
            # Not a number or conversion failed, continue with string value
            pass
            
        # Fall back to string value if numeric didn't work or wasn't applicable
        result = current_project.SetSetting(setting_name, setting_value)
        if result:
            return f"Successfully set project setting '{setting_name}' to '{setting_value}'"
        else:
            return f"Failed to set project setting '{setting_name}'"
    except Exception as e:
        return f"Error setting project setting: {str(e)}"


@mcp.tool()
def open_project(name: str) -> str:
    """Open a project by name.
    
    Args:
        name: The name of the project to open
    """
    resolve = get_resolve()
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    if not name:
        return "Error: Project name cannot be empty"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    # Check if project exists
    projects = project_manager.GetProjectListInCurrentFolder()
    if name not in projects:
        return f"Error: Project '{name}' not found. Available projects: {', '.join(projects)}"
    
    result = project_manager.LoadProject(name)
    if result:
        return f"Successfully opened project '{name}'"
    else:
        return f"Failed to open project '{name}'"


@mcp.tool()
def create_project(name: str, media_location_path: str = None) -> str:
    """Create a new project with the given name.
    
    Args:
        name: The name for the new project
        media_location_path: Optional project media location path (Resolve 20.2.2+).
    """
    resolve = get_resolve()
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    if not name:
        return "Error: Project name cannot be empty"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    # Check if project already exists
    projects = project_manager.GetProjectListInCurrentFolder()
    if name in projects:
        return f"Error: Project '{name}' already exists"
    
    if media_location_path:
        version = resolve.GetVersion() or [0]
        if version[0] < 20 or (version[0] == 20 and len(version) > 2 and (version[1], version[2]) < (2, 2)):
            return "Error: ProjectManager.CreateProject media_location_path requires DaVinci Resolve 20.2.2+"
        result = project_manager.CreateProject(name, media_location_path)
    else:
        result = project_manager.CreateProject(name)
    if result:
        return f"Successfully created project '{name}'"
    else:
        return f"Failed to create project '{name}'"


@mcp.tool()
def save_project() -> str:
    """Save the current project.
    
    Note that DaVinci Resolve typically auto-saves projects, so this may not be necessary.
    """
    pm, current_project = get_current_project()
    if not current_project:
        return "Error: No project currently open"
    
    project_name = current_project.GetName()
    success = False
    error_message = None
    
    # Try multiple approaches to save the project
    try:
        # Method 1: Try direct save method if available
        try:
            if hasattr(current_project, "SaveProject"):
                result = current_project.SaveProject()
                if result:
                    logger.info(f"Project '{project_name}' saved using SaveProject method")
                    success = True
        except Exception as e:
            logger.error(f"Error in SaveProject method: {str(e)}")
            error_message = str(e)
            
        # Method 2: Try project manager save method
        if not success:
            try:
                if hasattr(project_manager, "SaveProject"):
                    result = project_manager.SaveProject()
                    if result:
                        logger.info(f"Project '{project_name}' saved using ProjectManager.SaveProject method")
                        success = True
            except Exception as e:
                logger.error(f"Error in ProjectManager.SaveProject method: {str(e)}")
                if not error_message:
                    error_message = str(e)
        
        # Method 3: Try the export method as a backup approach
        if not success:
            try:
                # Get a temporary file path that Resolve can access
                temp_dir = _resolve_safe_dir(tempfile.gettempdir())
                os.makedirs(temp_dir, exist_ok=True)
                temp_file = os.path.join(temp_dir, f"{project_name}_temp.drp")
                
                # Try to export the project, which should trigger a save
                result = project_manager.ExportProject(project_name, temp_file)
                if result:
                    logger.info(f"Project '{project_name}' saved via temporary export to {temp_file}")
                    # Try to clean up temp file
                    try:
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
                    except:
                        pass
                    success = True
            except Exception as e:
                logger.error(f"Error in export method: {str(e)}")
                if not error_message:
                    error_message = str(e)
                    
        # If all else fails, rely on auto-save
        if not success:
            return f"Automatic save likely in effect for project '{project_name}'. Manual save attempts failed: {error_message if error_message else 'Unknown error'}"
        else:
            return f"Successfully saved project '{project_name}'"
            
    except Exception as e:
        logger.error(f"Error saving project: {str(e)}")
        return f"Error saving project: {str(e)}"


@mcp.tool()
def close_project() -> str:
    """Close the current project.
    
    This closes the current project without saving. If you need to save, use the save_project function first.
    """
    pm, current_project = get_current_project()
    if not current_project:
        return "Error: No project currently open"
    
    project_name = current_project.GetName()
    
    # Close the project
    try:
        result = project_manager.CloseProject(current_project)
        if result:
            logger.info(f"Project '{project_name}' closed successfully")
            return f"Successfully closed project '{project_name}'"
        else:
            logger.error(f"Failed to close project '{project_name}'")
            return f"Failed to close project '{project_name}'"
    except Exception as e:
        logger.error(f"Error closing project: {str(e)}")
        return f"Error closing project: {str(e)}"


@mcp.resource("resolve://delivery/render-presets")
def get_render_presets() -> List[Dict[str, Any]]:
    """Get all available render presets in the current project."""
    from api.delivery_operations import get_render_presets as get_presets_func
    return get_presets_func(resolve)


@mcp.tool()
def add_to_render_queue(preset_name: str, timeline_name: str = None, use_in_out_range: bool = False) -> Dict[str, Any]:
    """Add a timeline to the render queue with the specified preset.
    
    Args:
        preset_name: Name of the render preset to use
        timeline_name: Name of the timeline to render (uses current if None)
        use_in_out_range: Whether to render only the in/out range instead of entire timeline
    """
    from api.delivery_operations import add_to_render_queue as add_queue_func
    return add_queue_func(resolve, preset_name, timeline_name, use_in_out_range)


@mcp.tool()
def start_render() -> Dict[str, Any]:
    """Start rendering the jobs in the render queue."""
    from api.delivery_operations import start_render as start_render_func
    return start_render_func(resolve)


@mcp.resource("resolve://delivery/render-queue/status")
def get_render_queue_status() -> Dict[str, Any]:
    """Get the status of jobs in the render queue."""
    from api.delivery_operations import get_render_queue_status as get_status_func
    return get_status_func(resolve)


@mcp.tool()
def clear_render_queue() -> Dict[str, Any]:
    """Clear all jobs from the render queue."""
    from api.delivery_operations import clear_render_queue as clear_queue_func
    return clear_queue_func(resolve)


@mcp.resource("resolve://cache/settings")
def get_cache_settings() -> Dict[str, Any]:
    """Get current cache settings from the project."""
    pm, current_project = get_current_project()
    if not current_project:
        return {"error": "No project currently open"}
    
    try:
        # Get all cache-related settings
        settings = {}
        cache_keys = [
            "CacheMode", 
            "CacheClipMode",
            "OptimizedMediaMode",
            "ProxyMode", 
            "ProxyQuality",
            "TimelineCacheMode",
            "LocalCachePath",
            "NetworkCachePath"
        ]
        
        for key in cache_keys:
            value = current_project.GetSetting(key)
            settings[key] = value
            
        return settings
    except Exception as e:
        return {"error": f"Failed to get cache settings: {str(e)}"}


@mcp.tool()
def set_cache_mode(mode: str) -> str:
    """Set cache mode for the current project.
    
    Args:
        mode: Cache mode to set. Options: 'auto', 'on', 'off'
    """
    pm, current_project = get_current_project()
    if not current_project:
        return "Error: No project currently open"
    
    # Validate mode
    valid_modes = ["auto", "on", "off"]
    mode = mode.lower()
    if mode not in valid_modes:
        return f"Error: Invalid cache mode. Must be one of: {', '.join(valid_modes)}"
    
    # Convert mode to API value
    mode_map = {
        "auto": "0",
        "on": "1",
        "off": "2"
    }
    
    try:
        result = current_project.SetSetting("CacheMode", mode_map[mode])
        if result:
            return f"Successfully set cache mode to '{mode}'"
        else:
            return f"Failed to set cache mode to '{mode}'"
    except Exception as e:
        return f"Error setting cache mode: {str(e)}"


@mcp.tool()
def set_optimized_media_mode(mode: str) -> str:
    """Set optimized media mode for the current project.
    
    Args:
        mode: Optimized media mode to set. Options: 'auto', 'on', 'off'
    """
    pm, current_project = get_current_project()
    if not current_project:
        return "Error: No project currently open"
    
    # Validate mode
    valid_modes = ["auto", "on", "off"]
    mode = mode.lower()
    if mode not in valid_modes:
        return f"Error: Invalid optimized media mode. Must be one of: {', '.join(valid_modes)}"
    
    # Convert mode to API value
    mode_map = {
        "auto": "0",
        "on": "1",
        "off": "2"
    }
    
    try:
        result = current_project.SetSetting("OptimizedMediaMode", mode_map[mode])
        if result:
            return f"Successfully set optimized media mode to '{mode}'"
        else:
            return f"Failed to set optimized media mode to '{mode}'"
    except Exception as e:
        return f"Error setting optimized media mode: {str(e)}"


@mcp.tool()
def set_proxy_mode(mode: str) -> str:
    """Set proxy media mode for the current project.
    
    Args:
        mode: Proxy mode to set. Options: 'auto', 'on', 'off'
    """
    pm, current_project = get_current_project()
    if not current_project:
        return "Error: No project currently open"
    
    # Validate mode
    valid_modes = ["auto", "on", "off"]
    mode = mode.lower()
    if mode not in valid_modes:
        return f"Error: Invalid proxy mode. Must be one of: {', '.join(valid_modes)}"
    
    # Convert mode to API value
    mode_map = {
        "auto": "0",
        "on": "1",
        "off": "2"
    }
    
    try:
        result = current_project.SetSetting("ProxyMode", mode_map[mode])
        if result:
            return f"Successfully set proxy mode to '{mode}'"
        else:
            return f"Failed to set proxy mode to '{mode}'"
    except Exception as e:
        return f"Error setting proxy mode: {str(e)}"


@mcp.tool()
def set_proxy_quality(quality: str) -> str:
    """Set proxy media quality for the current project.
    
    Args:
        quality: Proxy quality to set. Options: 'quarter', 'half', 'threeQuarter', 'full'
    """
    pm, current_project = get_current_project()
    if not current_project:
        return "Error: No project currently open"
    
    # Validate quality
    valid_qualities = ["quarter", "half", "threeQuarter", "full"]
    if quality not in valid_qualities:
        return f"Error: Invalid proxy quality. Must be one of: {', '.join(valid_qualities)}"
    
    # Convert quality to API value
    quality_map = {
        "quarter": "0",
        "half": "1",
        "threeQuarter": "2",
        "full": "3"
    }
    
    try:
        result = current_project.SetSetting("ProxyQuality", quality_map[quality])
        if result:
            return f"Successfully set proxy quality to '{quality}'"
        else:
            return f"Failed to set proxy quality to '{quality}'"
    except Exception as e:
        return f"Error setting proxy quality: {str(e)}"


@mcp.tool()
def set_cache_path(path_type: str, path: str) -> str:
    """Set cache file path for the current project.
    
    Args:
        path_type: Type of cache path to set. Options: 'local', 'network'
        path: File system path for the cache
    """
    pm, current_project = get_current_project()
    if not current_project:
        return "Error: No project currently open"
    
    # Validate path_type
    valid_path_types = ["local", "network"]
    path_type = path_type.lower()
    if path_type not in valid_path_types:
        return f"Error: Invalid path type. Must be one of: {', '.join(valid_path_types)}"
    
    # Check if directory exists
    if not os.path.exists(path):
        return f"Error: Path '{path}' does not exist"
    
    setting_key = "LocalCachePath" if path_type == "local" else "NetworkCachePath"
    
    try:
        result = current_project.SetSetting(setting_key, path)
        if result:
            return f"Successfully set {path_type} cache path to '{path}'"
        else:
            return f"Failed to set {path_type} cache path to '{path}'"
    except Exception as e:
        return f"Error setting cache path: {str(e)}"


@mcp.tool()
def generate_optimized_media(clip_names: List[str] = None) -> str:
    """Generate optimized media for specified clips or all clips if none specified.
    
    Args:
        clip_names: Optional list of clip names. If None, processes all clips in media pool
    """
    pm, current_project = get_current_project()
    if not current_project:
        return "Error: No project currently open"
    
    media_pool = current_project.GetMediaPool()
    if not media_pool:
        return "Error: Failed to get Media Pool"
    
    # Get clips to process
    if clip_names:
        # Get specified clips
        all_clips = get_all_media_pool_clips(media_pool)
        clips_to_process = []
        missing_clips = []
        
        for name in clip_names:
            found = False
            for clip in all_clips:
                if clip.GetName() == name:
                    clips_to_process.append(clip)
                    found = True
                    break
            if not found:
                missing_clips.append(name)
        
        if missing_clips:
            return f"Error: Could not find these clips: {', '.join(missing_clips)}"
        
        if not clips_to_process:
            return "Error: No valid clips found to process"
    else:
        # Get all clips
        clips_to_process = get_all_media_pool_clips(media_pool)
    
    try:
        # Select the clips
        media_pool.SetCurrentFolder(media_pool.GetRootFolder())
        for clip in clips_to_process:
            clip.AddFlag("Green")  # Temporarily add flag to help with selection
        
        # Switch to Media page if not already there
        current_page = resolve.GetCurrentPage()
        if current_page != "media":
            resolve.OpenPage("media")
        
        # Select clips with Green flag
        media_pool.SetClipSelection([clip for clip in clips_to_process])
        
        # Generate optimized media
        result = current_project.GenerateOptimizedMedia()
        
        # Remove temporary flags
        for clip in clips_to_process:
            clip.ClearFlags("Green")
        
        if result:
            return f"Successfully started optimized media generation for {len(clips_to_process)} clips"
        else:
            return f"Failed to start optimized media generation"
    except Exception as e:
        # Clean up flags in case of error
        try:
            for clip in clips_to_process:
                clip.ClearFlags("Green")
        except:
            pass
        return f"Error generating optimized media: {str(e)}"


@mcp.tool()
def delete_optimized_media(clip_names: List[str] = None) -> str:
    """Delete optimized media for specified clips or all clips if none specified.
    
    Args:
        clip_names: Optional list of clip names. If None, processes all clips in media pool
    """
    pm, current_project = get_current_project()
    if not current_project:
        return "Error: No project currently open"
    
    media_pool = current_project.GetMediaPool()
    if not media_pool:
        return "Error: Failed to get Media Pool"
    
    # Get clips to process
    if clip_names:
        # Get specified clips
        all_clips = get_all_media_pool_clips(media_pool)
        clips_to_process = []
        missing_clips = []
        
        for name in clip_names:
            found = False
            for clip in all_clips:
                if clip.GetName() == name:
                    clips_to_process.append(clip)
                    found = True
                    break
            if not found:
                missing_clips.append(name)
        
        if missing_clips:
            return f"Error: Could not find these clips: {', '.join(missing_clips)}"
        
        if not clips_to_process:
            return "Error: No valid clips found to process"
    else:
        # Get all clips
        clips_to_process = get_all_media_pool_clips(media_pool)
    
    try:
        # Select the clips
        media_pool.SetCurrentFolder(media_pool.GetRootFolder())
        for clip in clips_to_process:
            clip.AddFlag("Green")  # Temporarily add flag to help with selection
        
        # Switch to Media page if not already there
        current_page = resolve.GetCurrentPage()
        if current_page != "media":
            resolve.OpenPage("media")
        
        # Select clips with Green flag
        media_pool.SetClipSelection([clip for clip in clips_to_process])
        
        # Delete optimized media
        result = current_project.DeleteOptimizedMedia()
        
        # Remove temporary flags
        for clip in clips_to_process:
            clip.ClearFlags("Green")
        
        if result:
            return f"Successfully deleted optimized media for {len(clips_to_process)} clips"
        else:
            return f"Failed to delete optimized media"
    except Exception as e:
        # Clean up flags in case of error
        try:
            for clip in clips_to_process:
                clip.ClearFlags("Green")
        except:
            pass
        return f"Error deleting optimized media: {str(e)}"


@mcp.resource("resolve://cloud/projects")
def get_cloud_projects() -> Dict[str, Any]:
    """Get list of available cloud projects."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve", "success": False}
    
    return get_cloud_project_list(resolve)


@mcp.tool()
def create_cloud_project_tool(project_name: str, folder_path: str = None) -> Dict[str, Any]:
    """Create a new cloud project.
    
    Args:
        project_name: Name for the new cloud project
        folder_path: Optional path for the cloud project folder
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve", "success": False}
    
    return create_cloud_project(resolve, project_name, folder_path)


@mcp.tool()
def import_cloud_project_tool(cloud_id: str, project_name: str = None) -> Dict[str, Any]:
    """Import a project from DaVinci Resolve cloud.
    
    Args:
        cloud_id: Cloud ID or reference of the project to import
        project_name: Optional custom name for the imported project (uses original name if None)
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve", "success": False}
    
    return import_cloud_project(resolve, cloud_id, project_name)


@mcp.tool()
def restore_cloud_project_tool(cloud_id: str, project_name: str = None) -> Dict[str, Any]:
    """Restore a project from DaVinci Resolve cloud.
    
    Args:
        cloud_id: Cloud ID or reference of the project to restore
        project_name: Optional custom name for the restored project (uses original name if None)
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve", "success": False}
    
    return restore_cloud_project(resolve, cloud_id, project_name)


@mcp.tool()
def export_project_to_cloud_tool(project_name: str = None) -> Dict[str, Any]:
    """Export current or specified project to DaVinci Resolve cloud.
    
    Args:
        project_name: Optional name of project to export (uses current project if None)
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve", "success": False}
    
    return export_project_to_cloud(resolve, project_name)


@mcp.tool()
def add_user_to_cloud_project_tool(cloud_id: str, user_email: str, permissions: str = "viewer") -> Dict[str, Any]:
    """Add a user to a cloud project with specified permissions.
    
    Args:
        cloud_id: Cloud ID of the project
        user_email: Email of the user to add
        permissions: Permission level (viewer, editor, admin)
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve", "success": False}
    
    return add_user_to_cloud_project(resolve, cloud_id, user_email, permissions)


@mcp.tool()
def remove_user_from_cloud_project_tool(cloud_id: str, user_email: str) -> Dict[str, Any]:
    """Remove a user from a cloud project.
    
    Args:
        cloud_id: Cloud ID of the project
        user_email: Email of the user to remove
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve", "success": False}
    
    return remove_user_from_cloud_project(resolve, cloud_id, user_email)


@mcp.resource("resolve://project/properties")
def get_project_properties_endpoint() -> Dict[str, Any]:
    """Get all project properties for the current project."""
    pm, current_project = get_current_project()
    if not current_project:
        return {"error": "No project currently open"}
    
    return get_all_project_properties(current_project)


@mcp.resource("resolve://project/property/{property_name}")
def get_project_property_endpoint(property_name: str) -> Dict[str, Any]:
    """Get a specific project property value.
    
    Args:
        property_name: Name of the property to get
    """
    pm, current_project = get_current_project()
    if not current_project:
        return {"error": "No project currently open"}
    
    value = get_project_property(current_project, property_name)
    return {property_name: value}


@mcp.tool()
def set_project_property_tool(property_name: str, property_value: Any) -> str:
    """Set a project property value.
    
    Args:
        property_name: Name of the property to set
        property_value: Value to set for the property
    """
    pm, current_project = get_current_project()
    if not current_project:
        return "Error: No project currently open"
    
    result = set_project_property(current_project, property_name, property_value)
    
    if result:
        return f"Successfully set project property '{property_name}' to '{property_value}'"
    else:
        return f"Failed to set project property '{property_name}'"


@mcp.resource("resolve://project/timeline-format")
def get_timeline_format() -> Dict[str, Any]:
    """Get timeline format settings for the current project."""
    pm, current_project = get_current_project()
    if not current_project:
        return {"error": "No project currently open"}
    
    return get_timeline_format_settings(current_project)


@mcp.tool()
def set_timeline_format_tool(width: int, height: int, frame_rate: float, interlaced: bool = False) -> str:
    """Set timeline format (resolution and frame rate).
    
    Args:
        width: Timeline width in pixels
        height: Timeline height in pixels
        frame_rate: Timeline frame rate
        interlaced: Whether the timeline should use interlaced processing
    """
    pm, current_project = get_current_project()
    if not current_project:
        return "Error: No project currently open"
    
    result = set_timeline_format(current_project, width, height, frame_rate, interlaced)
    
    if result:
        interlace_status = "interlaced" if interlaced else "progressive"
        return f"Successfully set timeline format to {width}x{height} at {frame_rate} fps ({interlace_status})"
    else:
        return "Failed to set timeline format"


@mcp.resource("resolve://project/superscale")
def get_superscale_settings_endpoint() -> Dict[str, Any]:
    """Get SuperScale settings for the current project."""
    pm, current_project = get_current_project()
    if not current_project:
        return {"error": "No project currently open"}
    
    return get_superscale_settings(current_project)


@mcp.tool()
def set_superscale_settings_tool(enabled: bool, quality: int = 0) -> str:
    """Set SuperScale settings for the current project.
    
    Args:
        enabled: Whether SuperScale is enabled
        quality: SuperScale quality (0=Auto, 1=Better Quality, 2=Smoother)
    """
    pm, current_project = get_current_project()
    if not current_project:
        return "Error: No project currently open"
    
    quality_names = {
        0: "Auto",
        1: "Better Quality",
        2: "Smoother"
    }
    
    result = set_superscale_settings(current_project, enabled, quality)
    
    if result:
        status = "enabled" if enabled else "disabled"
        quality_name = quality_names.get(quality, "Unknown")
        return f"Successfully {status} SuperScale with quality set to {quality_name}"
    else:
        return "Failed to set SuperScale settings"


@mcp.resource("resolve://project/color-settings")
def get_color_settings_endpoint() -> Dict[str, Any]:
    """Get color science and color space settings for the current project."""
    pm, current_project = get_current_project()
    if not current_project:
        return {"error": "No project currently open"}
    
    return get_color_settings(current_project)


@mcp.tool()
def set_color_science_mode_tool(mode: str) -> str:
    """Set color science mode for the current project.
    
    Args:
        mode: Color science mode ('YRGB', 'YRGB Color Managed', 'ACEScct', or numeric value)
    """
    pm, current_project = get_current_project()
    if not current_project:
        return "Error: No project currently open"
    
    result = set_color_science_mode(current_project, mode)
    
    if result:
        return f"Successfully set color science mode to '{mode}'"
    else:
        return f"Failed to set color science mode to '{mode}'"


@mcp.tool()
def set_color_space_tool(color_space: str, gamma: str = None) -> str:
    """Set timeline color space and gamma.
    
    Args:
        color_space: Timeline color space (e.g., 'Rec.709', 'DCI-P3 D65', 'Rec.2020')
        gamma: Timeline gamma (e.g., 'Rec.709 Gamma', 'Gamma 2.4')
    """
    pm, current_project = get_current_project()
    if not current_project:
        return "Error: No project currently open"
    
    result = set_color_space(current_project, color_space, gamma)
    
    if result:
        if gamma:
            return f"Successfully set timeline color space to '{color_space}' with gamma '{gamma}'"
        else:
            return f"Successfully set timeline color space to '{color_space}'"
    else:
        return "Failed to set timeline color space"


@mcp.resource("resolve://project/metadata")
def get_project_metadata_endpoint() -> Dict[str, Any]:
    """Get metadata for the current project."""
    pm, current_project = get_current_project()
    if not current_project:
        return {"error": "No project currently open"}
    
    return get_project_metadata(current_project)


@mcp.resource("resolve://project/info")
def get_project_info_endpoint() -> Dict[str, Any]:
    """Get comprehensive information about the current project."""
    pm, current_project = get_current_project()
    if not current_project:
        return {"error": "No project currently open"}
    
    return get_project_info(current_project)


@mcp.tool()
def archive_project(project_name: str, archive_path: str, archive_src_media: bool = True, archive_render_cache: bool = True, archive_proxy_media: bool = False) -> Dict[str, Any]:
    """Archive a project to a file with optional media.

    Args:
        project_name: Name of the project to archive.
        archive_path: Absolute path for the archive file (.dra).
        archive_src_media: Include source media in archive. Default: True.
        archive_render_cache: Include render cache. Default: True.
        archive_proxy_media: Include proxy media. Default: False.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    result = pm.ArchiveProject(project_name, archive_path, archive_src_media, archive_render_cache, archive_proxy_media)
    return {"success": bool(result), "project_name": project_name, "archive_path": archive_path}


@mcp.tool()
def delete_project(project_name: str) -> Dict[str, Any]:
    """Delete a project from the current database. WARNING: This is irreversible.

    Args:
        project_name: Name of the project to delete.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    result = pm.DeleteProject(project_name)
    return {"success": bool(result), "project_name": project_name}


@mcp.tool()
def create_project_folder(folder_name: str) -> Dict[str, Any]:
    """Create a new folder in the current project folder location.

    Args:
        folder_name: Name of the folder to create.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    result = pm.CreateFolder(folder_name)
    return {"success": bool(result), "folder_name": folder_name}


@mcp.tool()
def delete_project_folder(folder_name: str) -> Dict[str, Any]:
    """Delete a folder from the current project folder location.

    Args:
        folder_name: Name of the folder to delete.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    result = pm.DeleteFolder(folder_name)
    return {"success": bool(result), "folder_name": folder_name}


@mcp.tool()
def get_project_folder_list() -> Dict[str, Any]:
    """Get list of folders in the current project folder location."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    folders = pm.GetFolderListInCurrentFolder()
    return {"folders": folders if folders else []}


@mcp.tool()
def goto_root_project_folder() -> Dict[str, Any]:
    """Navigate to the root project folder."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    result = pm.GotoRootFolder()
    return {"success": bool(result)}


@mcp.tool()
def goto_parent_project_folder() -> Dict[str, Any]:
    """Navigate up one level in the project folder hierarchy."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    result = pm.GotoParentFolder()
    return {"success": bool(result)}


@mcp.tool()
def get_current_project_folder() -> Dict[str, Any]:
    """Get the name of the current project folder."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    folder = pm.GetCurrentFolder()
    return {"current_folder": folder}


@mcp.tool()
def open_project_folder(folder_name: str) -> Dict[str, Any]:
    """Open/navigate into a project folder.

    Args:
        folder_name: Name of the folder to open.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    result = pm.OpenFolder(folder_name)
    return {"success": bool(result), "folder_name": folder_name}


@mcp.tool()
def import_project_from_file(file_path: str) -> Dict[str, Any]:
    """Import a project from a .drp file.

    Args:
        file_path: Absolute path to the .drp project file.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    result = pm.ImportProject(file_path)
    return {"success": bool(result), "file_path": file_path}


@mcp.tool()
def export_project_to_file(project_name: str, file_path: str, with_stills_and_luts: bool = True) -> Dict[str, Any]:
    """Export a project to a .drp file.

    Args:
        project_name: Name of the project to export.
        file_path: Absolute path for the exported .drp file.
        with_stills_and_luts: Include stills and LUTs in export. Default: True.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    result = pm.ExportProject(project_name, file_path, with_stills_and_luts)
    return {"success": bool(result), "project_name": project_name, "file_path": file_path}


@mcp.tool()
def restore_project(file_path: str) -> Dict[str, Any]:
    """Restore a project from an archive (.dra) file.

    Args:
        file_path: Absolute path to the .dra archive file.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    result = pm.RestoreProject(file_path)
    return {"success": bool(result), "file_path": file_path}


@mcp.tool()
def get_current_database() -> Dict[str, Any]:
    """Get information about the current database."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    db = pm.GetCurrentDatabase()
    return db if db else {"error": "Failed to get current database"}


@mcp.tool()
def get_database_list() -> Dict[str, Any]:
    """Get list of all available databases."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    dbs = pm.GetDatabaseList()
    return {"databases": dbs if dbs else []}


@mcp.tool()
def set_current_database(db_info: Dict[str, str]) -> Dict[str, Any]:
    """Switch to a different database.

    Args:
        db_info: Database info dict with keys 'DbType' and 'DbName'. Example: {"DbType": "Disk", "DbName": "Local Database"}
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    result = pm.SetCurrentDatabase(db_info)
    return {"success": bool(result), "database": db_info}


@mcp.tool()
def set_project_name(name: str) -> Dict[str, Any]:
    """Rename the current project.

    Args:
        name: New name for the project.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.SetName(name)
    return {"success": bool(result), "name": name}


@mcp.tool()
def get_timeline_by_index(index: int) -> Dict[str, Any]:
    """Get a timeline by its 1-based index.

    Args:
        index: 1-based timeline index.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    tl = project.GetTimelineByIndex(index)
    if tl:
        return {"name": tl.GetName(), "start_frame": tl.GetStartFrame(), "end_frame": tl.GetEndFrame(), "unique_id": tl.GetUniqueId()}
    return {"error": f"No timeline at index {index}"}


@mcp.tool()
def get_project_preset_list() -> Dict[str, Any]:
    """Get list of available project presets."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    presets = project.GetPresetList()
    return {"presets": presets if presets else []}


@mcp.tool()
def set_project_preset(preset_name: str) -> Dict[str, Any]:
    """Apply a project preset to the current project.

    Args:
        preset_name: Name of the preset to apply.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.SetPreset(preset_name)
    return {"success": bool(result), "preset_name": preset_name}


@mcp.tool()
def delete_render_job(job_id: str) -> Dict[str, Any]:
    """Delete a specific render job by its ID.

    Args:
        job_id: The unique ID of the render job to delete.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.DeleteRenderJob(job_id)
    return {"success": bool(result), "job_id": job_id}


@mcp.tool()
def get_render_job_list() -> Dict[str, Any]:
    """Get list of all render jobs in the queue."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    jobs = project.GetRenderJobList()
    return {"render_jobs": jobs if jobs else []}


@mcp.tool()
def start_rendering_jobs(job_ids: Optional[List[str]] = None, is_interactive_mode: bool = False) -> Dict[str, Any]:
    """Start rendering jobs. If no job IDs specified, renders all queued jobs.

    Args:
        job_ids: Optional list of job IDs to render. If None, renders all.
        is_interactive_mode: If True, enables interactive rendering mode.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    if job_ids:
        result = project.StartRendering(job_ids, is_interactive_mode)
    else:
        result = project.StartRendering(is_interactive_mode)
    return {"success": bool(result)}


@mcp.tool()
def stop_rendering() -> Dict[str, Any]:
    """Stop the current rendering process."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    project.StopRendering()
    return {"success": True}


@mcp.tool()
def is_rendering_in_progress() -> Dict[str, Any]:
    """Check if rendering is currently in progress."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.IsRenderingInProgress()
    return {"is_rendering": bool(result)}


@mcp.tool()
def load_render_preset(preset_name: str) -> Dict[str, Any]:
    """Load a render preset by name.

    Args:
        preset_name: Name of the render preset to load.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.LoadRenderPreset(preset_name)
    return {"success": bool(result), "preset_name": preset_name}


@mcp.tool()
def save_as_new_render_preset(preset_name: str) -> Dict[str, Any]:
    """Save current render settings as a new preset.

    Args:
        preset_name: Name for the new render preset.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.SaveAsNewRenderPreset(preset_name)
    return {"success": bool(result), "preset_name": preset_name}


@mcp.tool()
def delete_render_preset(preset_name: str) -> Dict[str, Any]:
    """Delete a render preset.

    Args:
        preset_name: Name of the render preset to delete.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.DeleteRenderPreset(preset_name)
    return {"success": bool(result), "preset_name": preset_name}


@mcp.tool()
def set_render_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Set render settings for the current project.

    Args:
        settings: Dict of render settings. Supported keys include:
            SelectAllFrames (bool), MarkIn (int), MarkOut (int),
            TargetDir (str), CustomName (str), UniqueFilenameStyle (0/1),
            ExportVideo (bool), ExportAudio (bool), FormatWidth (int),
            FormatHeight (int), FrameRate (float), VideoQuality (int/str),
            AudioCodec (str), AudioBitDepth (int), AudioSampleRate (int),
            ColorSpaceTag (str), GammaTag (str), ExportAlpha (bool),
            ExportSubtitle (bool), SubtitleFormat ("BurnIn", "EmbeddedCaptions", or "SeparateFile").
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.SetRenderSettings(settings)
    return {"success": bool(result)}


@mcp.tool()
def get_render_job_status(job_id: str) -> Dict[str, Any]:
    """Get the status of a specific render job.

    Args:
        job_id: The unique ID of the render job.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    status = project.GetRenderJobStatus(job_id)
    return status if status else {"error": f"No render job with ID {job_id}"}


@mcp.tool()
def get_render_formats() -> Dict[str, Any]:
    """Get all available render formats."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    formats = project.GetRenderFormats()
    return {"formats": formats if formats else {}}


@mcp.tool()
def get_render_codecs(format_name: str) -> Dict[str, Any]:
    """Get available codecs for a given render format.

    Args:
        format_name: Render format name (e.g. 'mp4', 'mov', 'avi').
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    codecs = project.GetRenderCodecs(format_name)
    return {"format": format_name, "codecs": codecs if codecs else {}}


@mcp.tool()
def get_current_render_format_and_codec() -> Dict[str, Any]:
    """Get the current render format and codec setting."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.GetCurrentRenderFormatAndCodec()
    return result if result else {"error": "Failed to get render format and codec"}


@mcp.tool()
def set_current_render_format_and_codec(format_name: str, codec_name: str) -> Dict[str, Any]:
    """Set the render format and codec.

    Args:
        format_name: Render format (e.g. 'mp4', 'mov').
        codec_name: Codec name (e.g. 'H264', 'H265', 'ProRes422HQ').
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.SetCurrentRenderFormatAndCodec(format_name, codec_name)
    return {"success": bool(result), "format": format_name, "codec": codec_name}


@mcp.tool()
def get_current_render_mode() -> Dict[str, Any]:
    """Get the current render mode (0=Individual Clips, 1=Single Clip)."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    mode = project.GetCurrentRenderMode()
    return {"render_mode": mode, "mode_name": "Individual Clips" if mode == 0 else "Single Clip"}


@mcp.tool()
def set_current_render_mode(mode: int) -> Dict[str, Any]:
    """Set the render mode.

    Args:
        mode: 0 for Individual Clips, 1 for Single Clip.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.SetCurrentRenderMode(mode)
    return {"success": bool(result), "render_mode": mode}


@mcp.tool()
def get_render_resolutions(format_name: str, codec_name: str) -> Dict[str, Any]:
    """Get available render resolutions for a format/codec combination.

    Args:
        format_name: Render format (e.g. 'mp4').
        codec_name: Codec name (e.g. 'H264').
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    resolutions = project.GetRenderResolutions(format_name, codec_name)
    return {"format": format_name, "codec": codec_name, "resolutions": resolutions if resolutions else []}


@mcp.tool()
def refresh_lut_list() -> Dict[str, Any]:
    """Refresh the LUT list in the project. Call after adding new LUT files."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.RefreshLUTList()
    return {"success": bool(result)}


@mcp.tool()
def get_project_unique_id() -> Dict[str, Any]:
    """Get the unique ID of the current project."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    uid = project.GetUniqueId()
    return {"unique_id": uid}


@mcp.tool()
def insert_audio_to_current_track(file_path: str) -> Dict[str, Any]:
    """Insert audio file to current track at playhead position.

    Args:
        file_path: Absolute path to the audio file.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.InsertAudioToCurrentTrackAtPlayhead(file_path)
    return {"success": bool(result), "file_path": file_path}


@mcp.tool()
def load_burn_in_preset(preset_name: str) -> Dict[str, Any]:
    """Load a burn-in preset by name for the project.

    Args:
        preset_name: Name of the burn-in preset to load.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.LoadBurnInPreset(preset_name)
    return {"success": bool(result), "preset_name": preset_name}


@mcp.tool()
def export_current_frame_as_still(file_path: str) -> Dict[str, Any]:
    """Export the current frame as a still image.

    Args:
        file_path: Absolute path for the exported still image.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.ExportCurrentFrameAsStill(file_path)
    return {"success": bool(result), "file_path": file_path}


@mcp.tool()
def get_color_groups_list() -> Dict[str, Any]:
    """Get list of all color groups in the current project."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    groups = project.GetColorGroupsList()
    if groups:
        return {"color_groups": [{"name": g.GetName()} for g in groups]}
    return {"color_groups": []}


@mcp.tool()
def add_color_group(group_name: str) -> Dict[str, Any]:
    """Create a new color group in the current project.

    Args:
        group_name: Name for the new color group.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.AddColorGroup(group_name)
    return {"success": bool(result), "group_name": group_name}


@mcp.tool()
def delete_color_group(group_name: str) -> Dict[str, Any]:
    """Delete a color group from the current project.

    Args:
        group_name: Name of the color group to delete.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    # Find the group by name
    groups = project.GetColorGroupsList()
    target = None
    if groups:
        for g in groups:
            if g.GetName() == group_name:
                target = g
                break
    if not target:
        return {"error": f"Color group '{group_name}' not found"}
    result = project.DeleteColorGroup(target)
    return {"success": bool(result), "group_name": group_name}


@mcp.tool()
def apply_fairlight_preset_to_current_timeline(preset_name: str) -> Dict[str, Any]:
    """Apply a Fairlight preset to the current timeline.

    Args:
        preset_name: Name of the Fairlight preset to apply.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    missing = _requires_method(project, "ApplyFairlightPresetToCurrentTimeline", "20.2.2")
    if missing:
        return missing
    result = project.ApplyFairlightPresetToCurrentTimeline(preset_name)
    return {"success": bool(result), "preset_name": preset_name}


@mcp.tool()
def get_quick_export_render_presets() -> Dict[str, Any]:
    """Get list of available quick export render presets."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    presets = project.GetQuickExportRenderPresets()
    return {"presets": presets if presets else []}


@mcp.tool()
def render_with_quick_export(preset_name: str) -> Dict[str, Any]:
    """Render the current timeline using a Quick Export preset.

    Args:
        preset_name: Name of the Quick Export preset (e.g. 'H.264', 'YouTube', 'Vimeo').
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    result = project.RenderWithQuickExport(preset_name)
    return {"success": bool(result), "preset_name": preset_name}


@mcp.tool()
def add_render_job() -> Dict[str, Any]:
    """Add a render job based on current render settings to the render queue.

    Returns the unique job ID string for the new render job.
    Configure render settings first with set_render_settings, set_render_format_and_codec, etc.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project currently open"}
    job_id = project.AddRenderJob()
    if job_id:
        return {"success": True, "job_id": job_id}
    return {"success": False, "error": "Failed to add render job. Check render settings are configured."}


@mcp.tool()
def load_cloud_project(project_name: str, project_media_path: str, sync_mode: str = "proxy") -> Dict[str, Any]:
    """Load a cloud project from DaVinci Resolve cloud.

    Args:
        project_name: Name of the cloud project to load.
        project_media_path: Local path for project media cache.
        sync_mode: Sync mode - 'proxy' or 'full' (default: 'proxy').
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    pm = resolve.GetProjectManager()
    if not pm:
        return {"error": "Failed to get ProjectManager"}
    cloud_settings = {
        resolve.CLOUD_SETTING_PROJECT_NAME: project_name,
        resolve.CLOUD_SETTING_PROJECT_MEDIA_PATH: project_media_path,
        resolve.CLOUD_SETTING_SYNC_MODE: sync_mode,
    }
    project = pm.LoadCloudProject(cloud_settings)
    if project:
        return {"success": True, "project_name": project.GetName()}
    return {"success": False, "error": "Failed to load cloud project. Check cloud settings and connectivity."}
