#!/usr/bin/env python
"""
Add Selected Screenshot to Timeline

This script takes the currently selected item in the media pool (e.g., a screenshot)
and adds it to a new timeline that's named after the file.
"""

import sys
import os
import time

# Try to import the DaVinci Resolve scripting module
try:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Paths for macOS
    if sys.platform.startswith("darwin"):
        resolve_api_path = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
        resolve_module_path = os.path.join(resolve_api_path, "Modules")
    # Paths for Windows
    elif sys.platform.startswith("win") or sys.platform.startswith("cygwin"):
        resolve_api_path = "C:\\ProgramData\\Blackmagic Design\\DaVinci Resolve\\Support\\Developer\\Scripting"
        resolve_module_path = os.path.join(resolve_api_path, "Modules")
    # Paths for Linux
    elif sys.platform.startswith("linux"):
        resolve_api_path = "/opt/resolve/Developer/Scripting"
        resolve_module_path = os.path.join(resolve_api_path, "Modules")
    else:
        raise OSError(f"Unsupported platform: {sys.platform}")
    
    sys.path.append(resolve_module_path)
    import DaVinciResolveScript as dvr
    
except ImportError as e:
    print(f"Error importing DaVinci Resolve scripting modules: {e}")
    sys.exit(1)

def get_resolve_instance():
    """Get the current instance of DaVinci Resolve"""
    try:
        resolve = dvr.scriptapp("Resolve")
        return resolve
    except NameError as e:
        print(f"Error: DaVinci Resolve not found: {e}")
        return None

def get_selected_media_pool_items():
    """Get the currently selected items in the media pool"""
    resolve = get_resolve_instance()
    if not resolve:
        print("Could not connect to DaVinci Resolve")
        return []
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        print("Could not get project manager")
        return []
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        print("No project is currently open")
        return []
    
    media_pool = current_project.GetMediaPool()
    if not media_pool:
        print("Could not access media pool")
        return []
    
    # The correct way to get selected media pool items
    selected_items = []
    try:
        # First method: direct method
        selected_items = media_pool.GetCurrentFolder().GetClips()
        if selected_items:
            # Filter for selected clips if we got all clips
            selected_items = [clip for clip in selected_items.values() if hasattr(clip, 'IsSelected') and clip.IsSelected()]
        
        # Second method: if that didn't work
        if not selected_items:
            folder_items = media_pool.GetRootFolder().GetClips()
            if folder_items:
                selected_items = [clip for clip in folder_items.values() if hasattr(clip, 'IsSelected') and clip.IsSelected()]
        
        # Third method: try to get all clips from all folders
        if not selected_items:
            print("Looking for selected items in all folders...")
            all_clips = []
            
            def get_clips_from_folder(folder):
                clips = folder.GetClipList()
                subfolders = folder.GetSubFolderList()
                
                for clip in clips:
                    all_clips.append(clip)
                
                for subfolder in subfolders:
                    get_clips_from_folder(subfolder)
            
            get_clips_from_folder(media_pool.GetRootFolder())
            
            # Now find selected clips
            selected_items = [clip for clip in all_clips if hasattr(clip, 'IsSelected') and clip.IsSelected()]
    
    except Exception as e:
        print(f"Error getting selected clips: {e}")
    
    # Fallback: If all methods failed, prompt the user to enter a clip name
    if not selected_items:
        print("Could not detect selected items. Please select at least one item in the Media Pool.")
        print("Alternatively, enter the exact name of the clip you want to use:")
        clip_name = input("Clip name (or press Enter to cancel): ")
        
        if not clip_name:
            return []
        
        # Try to find the clip by name
        all_clips = {}
        try:
            all_clips = media_pool.GetRootFolder().GetClips()
            for clip in all_clips.values():
                if clip.GetName() == clip_name:
                    selected_items = [clip]
                    break
        except Exception as e:
            print(f"Error finding clip by name: {e}")
    
    return selected_items

def create_timeline(name):
    """Create a new timeline with the given name"""
    resolve = get_resolve_instance()
    if not resolve:
        return False
    
    project_manager = resolve.GetProjectManager()
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return False
    
    media_pool = current_project.GetMediaPool()
    if not media_pool:
        return False
    
    # Create the timeline
    new_timeline = media_pool.CreateEmptyTimeline(name)
    if not new_timeline:
        return False
    
    return True

def set_current_timeline(name):
    """Set the timeline with the given name as the current timeline"""
    resolve = get_resolve_instance()
    if not resolve:
        return False
    
    project_manager = resolve.GetProjectManager()
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return False
    
    # Get all timelines
    timeline_count = current_project.GetTimelineCount()
    for i in range(1, timeline_count + 1):
        timeline = current_project.GetTimelineByIndex(i)
        if timeline and timeline.GetName() == name:
            # Set as current timeline
            success = current_project.SetCurrentTimeline(timeline)
            return success
    
    return False

def add_screenshot_to_timeline():
    """Add the selected screenshot to a new timeline named after the file"""
    print("Getting selected media pool items...")
    selected_items = get_selected_media_pool_items()
    
    if not selected_items:
        print("No items selected in the media pool. Please select a screenshot or image.")
        return False
    
    # Get the first selected item
    media_item = selected_items[0]
    
    # Get the file name to use for the timeline
    try:
        # Get the clip name
        file_name = media_item.GetName()
        
        # Remove file extension if present
        file_name = os.path.splitext(file_name)[0]
        
        # Create a valid timeline name
        timeline_name = f"{file_name}_Timeline"
        
        print(f"Creating new timeline: {timeline_name}")
        
        # Create the new timeline
        success = create_timeline(timeline_name)
        
        if not success:
            print(f"Error creating timeline: {timeline_name}")
            return False
        
        print("Timeline created successfully")
        
        # Set it as the current timeline
        success = set_current_timeline(timeline_name)
        
        if not success:
            print(f"Error setting current timeline: {timeline_name}")
            return False
        
        print("Timeline set as current")
        
        # Add the media item to the timeline
        print("Adding media item to timeline...")
        
        # Get Resolve objects directly
        resolve = get_resolve_instance()
        project_manager = resolve.GetProjectManager()
        current_project = project_manager.GetCurrentProject()
        media_pool = current_project.GetMediaPool()
        current_timeline = current_project.GetCurrentTimeline()
        
        # Use the media pool to add the item to the timeline
        success = media_pool.AppendToTimeline([media_item])
        
        if not success:
            print("Could not add the media item to the timeline")
            print("Trying alternative method...")
            
            # Alternative: if the clip is already in the Media Pool
            try:
                # Try using ImportIntoTimeline
                import_result = media_pool.ImportIntoTimeline(media_item.GetClipProperty('File Path'))
                if import_result:
                    success = True
            except Exception as e:
                print(f"Error with alternative method: {e}")
        
        if success:
            print(f"Successfully added {file_name} to new timeline {timeline_name}")
            return True
        else:
            print("All methods to add item to timeline failed")
            return False
        
    except Exception as e:
        print(f"Error: {e}")
        return False

if __name__ == "__main__":
    print("Adding selected screenshot to a new timeline...")
    success = add_screenshot_to_timeline()
    
    if success:
        print("Operation completed successfully!")
    else:
        print("Operation failed. Please check the error messages above.") 