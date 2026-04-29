"""Gallery, still album, and powergrade tools."""

from src.granular.common import *  # noqa: F401,F403

resolve = ResolveProxy()

@mcp.resource("resolve://color/presets")
def get_color_presets() -> List[Dict[str, Any]]:
    """Get all available color presets in the current project."""
    pm, current_project = get_current_project()
    if not current_project:
        return [{"error": "No project currently open"}]
    
    # Switch to color page to access presets
    current_page = resolve.GetCurrentPage()
    if current_page != "color":
        resolve.OpenPage("color")
    
    try:
        # Get gallery
        gallery = current_project.GetGallery()
        if not gallery:
            return [{"error": "Failed to get gallery"}]
        
        # Get all albums
        albums = gallery.GetAlbums()
        if not albums:
            return [{"info": "No albums found in gallery"}]
        
        result = []
        for album in albums:
            # Get stills in the album
            stills = album.GetStills()
            album_info = {
                "name": album.GetName(),
                "stills": []
            }
            
            if stills:
                for still in stills:
                    still_info = {
                        "id": still.GetUniqueId(),
                        "label": still.GetLabel(),
                        "timecode": still.GetTimecode(),
                        "isGrabbed": still.IsGrabbed()
                    }
                    album_info["stills"].append(still_info)
            
            result.append(album_info)
        
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
            
        return result
    
    except Exception as e:
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        return [{"error": f"Error retrieving color presets: {str(e)}"}]


@mcp.tool()
def save_color_preset(clip_name: str = None, preset_name: str = None, album_name: str = "DaVinci Resolve") -> str:
    """Save a color preset from the specified clip.
    
    Args:
        clip_name: Name of the clip to save preset from (uses current clip if None)
        preset_name: Name to give the preset (uses clip name if None)
        album_name: Album to save the preset to (default: "DaVinci Resolve")
    """
    pm, current_project = get_current_project()
    if not current_project:
        return "Error: No project currently open"
    
    # Switch to color page
    current_page = resolve.GetCurrentPage()
    if current_page != "color":
        resolve.OpenPage("color")
    
    try:
        # Get the current timeline
        current_timeline = current_project.GetCurrentTimeline()
        if not current_timeline:
            return "Error: No timeline is currently open"
        
        # Get the specific clip or current clip
        if clip_name:
            # Find the clip by name in the timeline
            timeline_clips = current_timeline.GetItemListInTrack("video", 1)
            target_clip = None
            
            for clip in timeline_clips:
                if clip.GetName() == clip_name:
                    target_clip = clip
                    break
            
            if not target_clip:
                return f"Error: Clip '{clip_name}' not found in the timeline"
            
            # Select the clip
            current_timeline.SetCurrentSelectedItem(target_clip)
        
        # Get gallery
        gallery = current_project.GetGallery()
        if not gallery:
            return "Error: Failed to get gallery"
        
        # Get or create album
        album = None
        albums = gallery.GetAlbums()
        
        if albums:
            for a in albums:
                if a.GetName() == album_name:
                    album = a
                    break
        
        if not album:
            # Create a new album if it doesn't exist
            album = gallery.CreateAlbum(album_name)
            if not album:
                return f"Error: Failed to create album '{album_name}'"
        
        # Set preset name if specified
        final_preset_name = preset_name
        if not final_preset_name:
            if clip_name:
                final_preset_name = f"{clip_name} Preset"
            else:
                # Get current clip name if available
                current_clip = current_timeline.GetCurrentVideoItem()
                if current_clip:
                    final_preset_name = f"{current_clip.GetName()} Preset"
                else:
                    final_preset_name = f"Preset {len(album.GetStills()) + 1}"
        
        # Capture still
        result = gallery.GrabStill()
        
        if not result:
            return "Error: Failed to grab still for the preset"
        
        # Get the still that was just created
        stills = album.GetStills()
        if stills:
            latest_still = stills[-1]  # Assume the last one is the one we just grabbed
            # Set the label
            latest_still.SetLabel(final_preset_name)
        
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        
        return f"Successfully saved color preset '{final_preset_name}' to album '{album_name}'"
    
    except Exception as e:
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        return f"Error saving color preset: {str(e)}"


@mcp.tool()
def apply_color_preset(preset_id: str = None, preset_name: str = None, 
                     clip_name: str = None, album_name: str = "DaVinci Resolve") -> str:
    """Apply a color preset to the specified clip.
    
    Args:
        preset_id: ID of the preset to apply (if known)
        preset_name: Name of the preset to apply (searches in album)
        clip_name: Name of the clip to apply preset to (uses current clip if None)
        album_name: Album containing the preset (default: "DaVinci Resolve")
    """
    resolve = get_resolve()
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    if not preset_id and not preset_name:
        return "Error: Must provide either preset_id or preset_name"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    # Switch to color page
    current_page = resolve.GetCurrentPage()
    if current_page != "color":
        resolve.OpenPage("color")
    
    try:
        # Get the current timeline
        current_timeline = current_project.GetCurrentTimeline()
        if not current_timeline:
            return "Error: No timeline is currently open"
        
        # Get the specific clip or current clip
        if clip_name:
            # Find the clip by name in the timeline
            timeline_clips = current_timeline.GetItemListInTrack("video", 1)
            target_clip = None
            
            for clip in timeline_clips:
                if clip.GetName() == clip_name:
                    target_clip = clip
                    break
            
            if not target_clip:
                return f"Error: Clip '{clip_name}' not found in the timeline"
            
            # Select the clip
            current_timeline.SetCurrentSelectedItem(target_clip)
        
        # Get gallery
        gallery = current_project.GetGallery()
        if not gallery:
            return "Error: Failed to get gallery"
        
        # Find the album
        album = None
        albums = gallery.GetAlbums()
        
        if albums:
            for a in albums:
                if a.GetName() == album_name:
                    album = a
                    break
        
        if not album:
            return f"Error: Album '{album_name}' not found"
        
        # Find the still to apply
        stills = album.GetStills()
        if not stills:
            return f"Error: No presets found in album '{album_name}'"
        
        target_still = None
        
        if preset_id:
            # Find by ID
            for still in stills:
                if still.GetUniqueId() == preset_id:
                    target_still = still
                    break
        elif preset_name:
            # Find by name
            for still in stills:
                if still.GetLabel() == preset_name:
                    target_still = still
                    break
        
        if not target_still:
            search_term = preset_id if preset_id else preset_name
            return f"Error: Preset '{search_term}' not found in album '{album_name}'"
        
        # Apply the preset
        result = target_still.ApplyToClip()
        
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        
        if result:
            return f"Successfully applied color preset to {'specified clip' if clip_name else 'current clip'}"
        else:
            return f"Failed to apply color preset"
    
    except Exception as e:
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        return f"Error applying color preset: {str(e)}"


@mcp.tool()
def delete_color_preset(preset_id: str = None, preset_name: str = None, 
                       album_name: str = "DaVinci Resolve") -> str:
    """Delete a color preset.
    
    Args:
        preset_id: ID of the preset to delete (if known)
        preset_name: Name of the preset to delete (searches in album)
        album_name: Album containing the preset (default: "DaVinci Resolve")
    """
    resolve = get_resolve()
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    
    if not preset_id and not preset_name:
        return "Error: Must provide either preset_id or preset_name"
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"
    
    # Switch to color page
    current_page = resolve.GetCurrentPage()
    if current_page != "color":
        resolve.OpenPage("color")
    
    try:
        # Get gallery
        gallery = current_project.GetGallery()
        if not gallery:
            return "Error: Failed to get gallery"
        
        # Find the album
        album = None
        albums = gallery.GetAlbums()
        
        if albums:
            for a in albums:
                if a.GetName() == album_name:
                    album = a
                    break
        
        if not album:
            return f"Error: Album '{album_name}' not found"
        
        # Find the still to delete
        stills = album.GetStills()
        if not stills:
            return f"Error: No presets found in album '{album_name}'"
        
        target_still = None
        
        if preset_id:
            # Find by ID
            for still in stills:
                if still.GetUniqueId() == preset_id:
                    target_still = still
                    break
        elif preset_name:
            # Find by name
            for still in stills:
                if still.GetLabel() == preset_name:
                    target_still = still
                    break
        
        if not target_still:
            search_term = preset_id if preset_id else preset_name
            return f"Error: Preset '{search_term}' not found in album '{album_name}'"
        
        # Delete the preset
        result = album.DeleteStill(target_still)
        
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        
        if result:
            return f"Successfully deleted color preset from album '{album_name}'"
        else:
            return f"Failed to delete color preset"
    
    except Exception as e:
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        return f"Error deleting color preset: {str(e)}"


@mcp.tool()
def create_color_preset_album(album_name: str) -> str:
    """Create a new album for color presets.
    
    Args:
        album_name: Name for the new album
    """
    pm, current_project = get_current_project()
    if not current_project:
        return "Error: No project currently open"
    
    # Switch to color page
    current_page = resolve.GetCurrentPage()
    if current_page != "color":
        resolve.OpenPage("color")
    
    try:
        # Get gallery
        gallery = current_project.GetGallery()
        if not gallery:
            return "Error: Failed to get gallery"
        
        # Check if album already exists
        albums = gallery.GetAlbums()
        
        if albums:
            for a in albums:
                if a.GetName() == album_name:
                    # Return to the original page if we switched
                    if current_page != "color":
                        resolve.OpenPage(current_page)
                    return f"Album '{album_name}' already exists"
        
        # Create a new album
        album = gallery.CreateAlbum(album_name)
        
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        
        if album:
            return f"Successfully created album '{album_name}'"
        else:
            return f"Failed to create album '{album_name}'"
    
    except Exception as e:
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        return f"Error creating album: {str(e)}"


@mcp.tool()
def delete_color_preset_album(album_name: str) -> str:
    """Delete a color preset album.
    
    Args:
        album_name: Name of the album to delete
    """
    pm, current_project = get_current_project()
    if not current_project:
        return "Error: No project currently open"
    
    # Switch to color page
    current_page = resolve.GetCurrentPage()
    if current_page != "color":
        resolve.OpenPage("color")
    
    try:
        # Get gallery
        gallery = current_project.GetGallery()
        if not gallery:
            return "Error: Failed to get gallery"
        
        # Find the album
        album = None
        albums = gallery.GetAlbums()
        
        if albums:
            for a in albums:
                if a.GetName() == album_name:
                    album = a
                    break
        
        if not album:
            # Return to the original page if we switched
            if current_page != "color":
                resolve.OpenPage(current_page)
            return f"Error: Album '{album_name}' not found"
        
        # Delete the album
        result = gallery.DeleteAlbum(album)
        
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        
        if result:
            return f"Successfully deleted album '{album_name}'"
        else:
            return f"Failed to delete album '{album_name}'"
    
    except Exception as e:
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        return f"Error deleting album: {str(e)}"


@mcp.tool()
def export_lut(clip_name: str = None, 
              export_path: str = None, 
              lut_format: str = "Cube", 
              lut_size: str = "33Point") -> str:
    """Export a LUT from the current clip's grade.
    
    Args:
        clip_name: Name of the clip to export grade from (uses current clip if None)
        export_path: Path to save the LUT file (generated if None)
        lut_format: Format of the LUT. Options: 'Cube', 'Davinci', '3dl', 'Panasonic'
        lut_size: Size of the LUT. Options: '17Point', '33Point', '65Point'
    """
    pm, current_project = get_current_project()
    if not current_project:
        return "Error: No project currently open"
    
    # Switch to color page
    current_page = resolve.GetCurrentPage()
    if current_page != "color":
        resolve.OpenPage("color")
    
    try:
        # Get the current timeline
        current_timeline = current_project.GetCurrentTimeline()
        if not current_timeline:
            return "Error: No timeline is currently open"
        
        # Get the specific clip or current clip
        if clip_name:
            # Find the clip by name in the timeline
            timeline_clips = current_timeline.GetItemListInTrack("video", 1)
            target_clip = None
            
            for clip in timeline_clips:
                if clip.GetName() == clip_name:
                    target_clip = clip
                    break
            
            if not target_clip:
                return f"Error: Clip '{clip_name}' not found in the timeline"
            
            # Select the clip
            current_timeline.SetCurrentSelectedItem(target_clip)
        
        # Generate export path if not provided
        if not export_path:
            clip_name_safe = clip_name if clip_name else "current_clip"
            clip_name_safe = clip_name_safe.replace(' ', '_').replace(':', '-')

            extension = ".cube"
            if lut_format.lower() == "davinci":
                extension = ".ilut"
            elif lut_format.lower() == "3dl":
                extension = ".3dl"
            elif lut_format.lower() == "panasonic":
                extension = ".vlut"

            safe_dir = _resolve_safe_dir(tempfile.gettempdir())
            os.makedirs(safe_dir, exist_ok=True)
            export_path = os.path.join(safe_dir, f"{clip_name_safe}_lut{extension}")
        
        # Validate LUT format
        valid_formats = ['Cube', 'Davinci', '3dl', 'Panasonic']
        if lut_format not in valid_formats:
            return f"Error: Invalid LUT format. Must be one of: {', '.join(valid_formats)}"
        
        # Validate LUT size
        valid_sizes = ['17Point', '33Point', '65Point']
        if lut_size not in valid_sizes:
            return f"Error: Invalid LUT size. Must be one of: {', '.join(valid_sizes)}"
        
        # Map format string to numeric value expected by DaVinci Resolve API
        format_map = {
            'Cube': 0,
            'Davinci': 1,
            '3dl': 2,
            'Panasonic': 3
        }
        
        # Map size string to numeric value
        size_map = {
            '17Point': 0,
            '33Point': 1,
            '65Point': 2
        }
        
        # Get current clip
        current_clip = current_timeline.GetCurrentVideoItem()
        if not current_clip:
            return "Error: No clip is currently selected"
        
        # Create a directory for the export path if it doesn't exist
        export_dir = os.path.dirname(export_path)
        if export_dir and not os.path.exists(export_dir):
            os.makedirs(export_dir, exist_ok=True)
        
        # Export the LUT
        colorpage = resolve.GetCurrentPage() == "color"
        if not colorpage:
            resolve.OpenPage("color")
        
        # Access Color page functionality 
        result = current_project.ExportCurrentGradeAsLUT(
            format_map[lut_format], 
            size_map[lut_size], 
            export_path
        )
        
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        
        if result:
            return f"Successfully exported LUT to '{export_path}' in {lut_format} format with {lut_size} size"
        else:
            return f"Failed to export LUT"
    
    except Exception as e:
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        return f"Error exporting LUT: {str(e)}"


@mcp.resource("resolve://color/lut-formats")
def get_lut_formats() -> Dict[str, Any]:
    """Get available LUT export formats and sizes."""
    formats = {
        "formats": [
            {
                "name": "Cube",
                "extension": ".cube",
                "description": "Industry standard LUT format supported by most applications"
            },
            {
                "name": "Davinci",
                "extension": ".ilut",
                "description": "DaVinci Resolve's native LUT format"
            },
            {
                "name": "3dl",
                "extension": ".3dl",
                "description": "ASSIMILATE SCRATCH and some Autodesk applications"
            },
            {
                "name": "Panasonic",
                "extension": ".vlut",
                "description": "Panasonic VariCam and other Panasonic cameras"
            }
        ],
        "sizes": [
            {
                "name": "17Point",
                "description": "Smaller file size, less precision (17x17x17)"
            },
            {
                "name": "33Point",
                "description": "Standard size with good balance of precision and file size (33x33x33)"
            },
            {
                "name": "65Point",
                "description": "Highest precision but larger file size (65x65x65)"
            }
        ]
    }
    return formats


@mcp.tool()
def export_all_powergrade_luts(export_dir: str) -> str:
    """Export all PowerGrade presets as LUT files.
    
    Args:
        export_dir: Directory to save the exported LUTs
    """
    pm, current_project = get_current_project()
    if not current_project:
        return "Error: No project currently open"
    
    # Switch to color page
    current_page = resolve.GetCurrentPage()
    if current_page != "color":
        resolve.OpenPage("color")
    
    try:
        # Get gallery
        gallery = current_project.GetGallery()
        if not gallery:
            return "Error: Failed to get gallery"
        
        # Get PowerGrade album
        powergrade_album = None
        albums = gallery.GetAlbums()
        
        if albums:
            for album in albums:
                if album.GetName() == "PowerGrade":
                    powergrade_album = album
                    break
        
        if not powergrade_album:
            return "Error: PowerGrade album not found"
        
        # Get all stills in the PowerGrade album
        stills = powergrade_album.GetStills()
        if not stills:
            return "Error: No stills found in PowerGrade album"
        
        # Create export directory if it doesn't exist
        if not os.path.exists(export_dir):
            os.makedirs(export_dir, exist_ok=True)
        
        # Export each still as a LUT
        exported_count = 0
        failed_stills = []
        
        for still in stills:
            still_name = still.GetLabel()
            if not still_name:
                still_name = f"PowerGrade_{still.GetUniqueId()}"
            
            # Create safe filename
            safe_name = ''.join(c if c.isalnum() or c in ['-', '_'] else '_' for c in still_name)
            lut_path = os.path.join(export_dir, f"{safe_name}.cube")
            
            # Apply the still to the current clip
            current_clip = current_timeline.GetCurrentVideoItem()
            if not current_clip:
                failed_stills.append(f"{still_name} (no clip selected)")
                continue
            
            # Apply the grade from the still
            applied = still.ApplyToClip()
            if not applied:
                failed_stills.append(f"{still_name} (could not apply grade)")
                continue
            
            # Export as LUT
            result = current_project.ExportCurrentGradeAsLUT(0, 1, lut_path)  # Cube format, 33-point
            
            if result:
                exported_count += 1
            else:
                failed_stills.append(f"{still_name} (export failed)")
        
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        
        if failed_stills:
            return f"Exported {exported_count} LUTs to '{export_dir}'. Failed to export: {', '.join(failed_stills)}"
        else:
            return f"Successfully exported all {exported_count} PowerGrade LUTs to '{export_dir}'"
    
    except Exception as e:
        # Return to the original page if we switched
        if current_page != "color":
            resolve.OpenPage(current_page)
        return f"Error exporting PowerGrade LUTs: {str(e)}"


@mcp.tool()
def get_gallery_album_name() -> Dict[str, Any]:
    """Get the name of the current gallery album."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    if not gallery:
        return {"error": "Failed to get Gallery"}
    name = gallery.GetAlbumName()
    return {"album_name": name if name else ""}


@mcp.tool()
def set_gallery_album_name(name: str) -> Dict[str, Any]:
    """Set the name of the current gallery album.

    Args:
        name: New album name.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    if not gallery:
        return {"error": "Failed to get Gallery"}
    result = gallery.SetAlbumName(name)
    return {"success": bool(result)}


@mcp.tool()
def get_gallery_still_albums() -> Dict[str, Any]:
    """Get list of all gallery still albums."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    if not gallery:
        return {"error": "Failed to get Gallery"}
    albums = gallery.GetGalleryStillAlbums()
    return {"albums": [str(a) for a in albums] if albums else []}


@mcp.tool()
def get_gallery_power_grade_albums() -> Dict[str, Any]:
    """Get list of all gallery power grade albums."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    if not gallery:
        return {"error": "Failed to get Gallery"}
    albums = gallery.GetGalleryPowerGradeAlbums()
    return {"albums": [str(a) for a in albums] if albums else []}


@mcp.tool()
def get_current_still_album() -> Dict[str, Any]:
    """Get the current still album."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    if not gallery:
        return {"error": "Failed to get Gallery"}
    album = gallery.GetCurrentStillAlbum()
    return {"has_album": album is not None}


@mcp.tool()
def set_current_still_album(album_index: int) -> Dict[str, Any]:
    """Set the current still album by index.

    Args:
        album_index: 0-based index of the album in GetGalleryStillAlbums() list.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    if not gallery:
        return {"error": "Failed to get Gallery"}
    albums = gallery.GetGalleryStillAlbums()
    if not albums or album_index >= len(albums):
        return {"error": f"No album at index {album_index}"}
    result = gallery.SetCurrentStillAlbum(albums[album_index])
    return {"success": bool(result)}


@mcp.tool()
def create_gallery_still_album(album_name: str = "") -> Dict[str, Any]:
    """Create a new gallery still album.

    Args:
        album_name: Optional name for the new album.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    if not gallery:
        return {"error": "Failed to get Gallery"}
    if album_name:
        album = gallery.CreateGalleryStillAlbum(album_name)
    else:
        album = gallery.CreateGalleryStillAlbum()
    return {"success": album is not None}


@mcp.tool()
def create_gallery_power_grade_album(album_name: str = "") -> Dict[str, Any]:
    """Create a new gallery power grade album.

    Args:
        album_name: Optional name for the new album.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    if not gallery:
        return {"error": "Failed to get Gallery"}
    if album_name:
        album = gallery.CreateGalleryPowerGradeAlbum(album_name)
    else:
        album = gallery.CreateGalleryPowerGradeAlbum()
    return {"success": album is not None}


@mcp.tool()
def get_album_stills(album_index: int = 0) -> Dict[str, Any]:
    """Get list of stills in a gallery album.

    Args:
        album_index: 0-based index of the album. Default: 0.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    if not gallery:
        return {"error": "Failed to get Gallery"}
    albums = gallery.GetGalleryStillAlbums()
    if not albums or album_index >= len(albums):
        return {"error": f"No album at index {album_index}"}
    stills = albums[album_index].GetStills()
    return {"still_count": len(stills) if stills else 0}


@mcp.tool()
def get_still_label(album_index: int, still_index: int) -> Dict[str, Any]:
    """Get the label of a still in a gallery album.

    Args:
        album_index: 0-based album index.
        still_index: 0-based still index.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    albums = gallery.GetGalleryStillAlbums()
    if not albums or album_index >= len(albums):
        return {"error": f"No album at index {album_index}"}
    stills = albums[album_index].GetStills()
    if not stills or still_index >= len(stills):
        return {"error": f"No still at index {still_index}"}
    label = albums[album_index].GetLabel(stills[still_index])
    return {"label": label if label else ""}


@mcp.tool()
def set_still_label(album_index: int, still_index: int, label: str) -> Dict[str, Any]:
    """Set the label of a still in a gallery album.

    Args:
        album_index: 0-based album index.
        still_index: 0-based still index.
        label: New label for the still.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    albums = gallery.GetGalleryStillAlbums()
    if not albums or album_index >= len(albums):
        return {"error": f"No album at index {album_index}"}
    stills = albums[album_index].GetStills()
    if not stills or still_index >= len(stills):
        return {"error": f"No still at index {still_index}"}
    result = albums[album_index].SetLabel(stills[still_index], label)
    return {"success": bool(result)}


@mcp.tool()
def import_stills_to_album(album_index: int, file_paths: List[str]) -> Dict[str, Any]:
    """Import stills from file paths into a gallery album.

    Args:
        album_index: 0-based album index.
        file_paths: List of absolute file paths to import.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    albums = gallery.GetGalleryStillAlbums()
    if not albums or album_index >= len(albums):
        return {"error": f"No album at index {album_index}"}
    result = albums[album_index].ImportStills(file_paths)
    return {"success": bool(result)}


@mcp.tool()
def export_stills_from_album(album_index: int, folder_path: str, file_prefix: str = "still", format: str = "dpx") -> Dict[str, Any]:
    """Export stills from a gallery album.

    Args:
        album_index: 0-based album index.
        folder_path: Directory to export to.
        file_prefix: Filename prefix. Default: 'still'.
        format: File format (dpx, cin, tif, jpg, png, ppm, bmp, xpm, drx). Default: 'dpx'.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    albums = gallery.GetGalleryStillAlbums()
    if not albums or album_index >= len(albums):
        return {"error": f"No album at index {album_index}"}
    stills = albums[album_index].GetStills()
    if not stills:
        return {"error": "No stills in album"}
    result = albums[album_index].ExportStills(stills, folder_path, file_prefix, format)
    return {"success": bool(result)}


@mcp.tool()
def delete_stills_from_album(album_index: int, still_indices: List[int]) -> Dict[str, Any]:
    """Delete stills from a gallery album.

    Args:
        album_index: 0-based album index.
        still_indices: List of 0-based still indices to delete.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    albums = gallery.GetGalleryStillAlbums()
    if not albums or album_index >= len(albums):
        return {"error": f"No album at index {album_index}"}
    stills = albums[album_index].GetStills()
    if not stills:
        return {"error": "No stills in album"}
    to_delete = [stills[i] for i in still_indices if i < len(stills)]
    result = albums[album_index].DeleteStills(to_delete)
    return {"success": bool(result)}
