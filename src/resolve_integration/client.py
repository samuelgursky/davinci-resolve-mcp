#!/usr/bin/env python
"""
DaVinci Resolve API client module.

This module handles connecting to DaVinci Resolve via the official API.
"""
import os
import sys
import platform
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from loguru import logger

def setup_resolve_env() -> None:
    """Set up the environment variables for DaVinci Resolve API based on platform."""
    system = platform.system()
    
    if system == "Darwin":  # macOS
        resolve_script_api = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/"
        resolve_script_lib = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
        
        os.environ["RESOLVE_SCRIPT_API"] = resolve_script_api
        os.environ["RESOLVE_SCRIPT_LIB"] = resolve_script_lib
        
        # Append to PYTHONPATH
        if "PYTHONPATH" in os.environ:
            os.environ["PYTHONPATH"] = f"{os.environ['PYTHONPATH']}:{resolve_script_api}/Modules/"
        else:
            os.environ["PYTHONPATH"] = f"{resolve_script_api}/Modules/"
            
    elif system == "Windows":
        resolve_script_api = "%PROGRAMDATA%\\Blackmagic Design\\DaVinci Resolve\\Support\\Developer\\Scripting\\"
        resolve_script_lib = "C:\\Program Files\\Blackmagic Design\\DaVinci Resolve\\fusionscript.dll"
        
        os.environ["RESOLVE_SCRIPT_API"] = resolve_script_api
        os.environ["RESOLVE_SCRIPT_LIB"] = resolve_script_lib
        
        # Append to PYTHONPATH
        if "PYTHONPATH" in os.environ:
            os.environ["PYTHONPATH"] = f"{os.environ['PYTHONPATH']};{resolve_script_api}\\Modules\\"
        else:
            os.environ["PYTHONPATH"] = f"{resolve_script_api}\\Modules\\"
            
    elif system == "Linux":
        resolve_script_api = "/opt/resolve/Developer/Scripting/"
        resolve_script_lib = "/opt/resolve/libs/Fusion/fusionscript.so"
        
        # Check for standard ISO Linux installation
        if not Path(resolve_script_api).exists():
            resolve_script_api = "/home/resolve/Developer/Scripting/"
            resolve_script_lib = "/home/resolve/libs/Fusion/fusionscript.so"
            
        os.environ["RESOLVE_SCRIPT_API"] = resolve_script_api
        os.environ["RESOLVE_SCRIPT_LIB"] = resolve_script_lib
        
        # Append to PYTHONPATH
        if "PYTHONPATH" in os.environ:
            os.environ["PYTHONPATH"] = f"{os.environ['PYTHONPATH']}:{resolve_script_api}/Modules/"
        else:
            os.environ["PYTHONPATH"] = f"{resolve_script_api}/Modules/"
    else:
        logger.error(f"Unsupported operating system: {system}")
        sys.exit(1)
    
    # Add the API modules directory to Python path
    api_modules_path = os.path.join(os.environ["RESOLVE_SCRIPT_API"], "Modules")
    if api_modules_path not in sys.path:
        sys.path.append(api_modules_path)

def get_resolve_instance():
    """
    Get an instance of the Resolve application.
    
    Returns:
        The DaVinci Resolve application instance or None if unsuccessful.
    """
    try:
        # Set up environment variables if not already set
        if "RESOLVE_SCRIPT_API" not in os.environ:
            setup_resolve_env()
        
        # Import DaVinci Resolve's API
        import DaVinciResolveScript as dvr_script
        
        # Try to get the Resolve instance
        resolve = dvr_script.scriptapp("Resolve")
        
        if resolve:
            logger.info("Successfully connected to DaVinci Resolve")
            return resolve
        else:
            logger.error("Could not connect to DaVinci Resolve. Make sure the application is running.")
            return None
            
    except ImportError as e:
        logger.error(f"Error importing DaVinci Resolve scripting API: {e}")
        logger.error("Please make sure DaVinci Resolve is installed and API paths are correctly set.")
        return None
    except Exception as e:
        logger.error(f"Unexpected error connecting to DaVinci Resolve: {e}")
        return None

class ResolveClient:
    """Client for interacting with DaVinci Resolve."""
    
    def __init__(self):
        """Initialize the Resolve client."""
        self.resolve = get_resolve_instance()
        self.api_capabilities = {}
        
        if self.resolve:
            self.fusion = self.resolve.Fusion()
            self.project_manager = self.resolve.GetProjectManager()
            self.current_project = self.project_manager.GetCurrentProject() if self.project_manager else None
            
            # Ensure a project is open
            if not self.current_project and self.project_manager:
                # Try to open the first project in the list
                projects = self.get_project_list()
                if projects:
                    logger.info(f"No project open, attempting to open project: {projects[0]}")
                    self.open_project(projects[0])
            
            # Check which API features are available
            self.check_api_capabilities()
        else:
            self.fusion = None
            self.project_manager = None
            self.current_project = None
            self.api_capabilities = {}
    
    def check_api_capabilities(self):
        """Check which DaVinci Resolve API features are available and working."""
        self.api_capabilities = {
            "get_project_manager": False,
            "get_project_list": False,
            "get_current_project": False,
            "get_project_name": False,
            "get_timeline_names": False,
            "get_current_timeline": False,
            "get_timeline_by_index": False,
            "get_media_pool": False,
            "get_root_folder": False,
            "get_clip_list": False,
        }
        
        # Check basic connection
        if not self.resolve:
            logger.error("Resolve API not available")
            return
        
        # Check Project Manager
        try:
            project_manager = self.resolve.GetProjectManager()
            if project_manager:
                self.api_capabilities["get_project_manager"] = True
                
                # Check project list
                try:
                    projects = project_manager.GetProjectListInCurrentFolder()
                    if isinstance(projects, list):
                        self.api_capabilities["get_project_list"] = True
                except Exception as e:
                    logger.error(f"GetProjectListInCurrentFolder not available: {e}")
                
                # Check current project
                try:
                    current_project = project_manager.GetCurrentProject()
                    if current_project:
                        self.api_capabilities["get_current_project"] = True
                        
                        # Check project name
                        try:
                            name = current_project.GetName()
                            if name:
                                self.api_capabilities["get_project_name"] = True
                        except Exception as e:
                            logger.error(f"GetName not available: {e}")
                        
                        # Check GetTimelineNames
                        try:
                            timeline_names = current_project.GetTimelineNames()
                            if timeline_names is not None:
                                self.api_capabilities["get_timeline_names"] = True
                        except Exception as e:
                            logger.warning(f"GetTimelineNames not available: {e}")
                        
                        # Check GetCurrentTimeline
                        try:
                            timeline = current_project.GetCurrentTimeline()
                            if timeline:
                                self.api_capabilities["get_current_timeline"] = True
                        except Exception as e:
                            logger.warning(f"GetCurrentTimeline not available: {e}")
                        
                        # Check GetTimelineByIndex
                        try:
                            timeline = current_project.GetTimelineByIndex(0)
                            # Even if it returns None (no timeline at index 0), the method exists
                            self.api_capabilities["get_timeline_by_index"] = True
                        except Exception as e:
                            logger.warning(f"GetTimelineByIndex not available: {e}")
                        
                        # Check GetMediaPool
                        try:
                            media_pool = current_project.GetMediaPool()
                            if media_pool:
                                self.api_capabilities["get_media_pool"] = True
                                
                                # Check GetRootFolder
                                try:
                                    root_folder = media_pool.GetRootFolder()
                                    if root_folder:
                                        self.api_capabilities["get_root_folder"] = True
                                        
                                        # Check GetClipList
                                        try:
                                            clips = root_folder.GetClipList()
                                            self.api_capabilities["get_clip_list"] = True
                                        except Exception as e:
                                            logger.warning(f"GetClipList not available: {e}")
                                except Exception as e:
                                    logger.warning(f"GetRootFolder not available: {e}")
                        except Exception as e:
                            logger.warning(f"GetMediaPool not available: {e}")
                except Exception as e:
                    logger.error(f"GetCurrentProject not available: {e}")
        except Exception as e:
            logger.error(f"GetProjectManager not available: {e}")
        
        # Log capabilities
        logger.info(f"DaVinci Resolve API capabilities: {self.api_capabilities}")
    
    def is_connected(self) -> bool:
        """Check if connected to DaVinci Resolve."""
        return self.resolve is not None
    
    def get_project_list(self) -> List[str]:
        """Get a list of all projects."""
        if not self.is_connected():
            return []
        
        return self.project_manager.GetProjectListInCurrentFolder()
    
    def open_project(self, project_name: str) -> bool:
        """Open a project by name."""
        if not self.is_connected():
            return False
            
        result = self.project_manager.LoadProject(project_name)
        if result:
            self.current_project = self.project_manager.GetCurrentProject()
        return result
    
    def get_timeline_list(self) -> List[str]:
        """Get a list of all timelines in the current project."""
        if not self.is_connected() or not self.current_project:
            logger.warning("Not connected or no project open when trying to get timeline list")
            return []
        
        # Use capabilities to determine best method
        if self.api_capabilities.get("get_timeline_names", False):
            try:
                timeline_names = self.current_project.GetTimelineNames()
                if timeline_names is None:
                    logger.warning("GetTimelineNames returned None")
                    return []
                return timeline_names
            except Exception as e:
                logger.error(f"Error getting timeline list: {e}")
                # Fall through to alternative methods
        
        # Try alternative method: check for current timeline
        if self.api_capabilities.get("get_current_timeline", False):
            try:
                current_timeline = self.get_current_timeline()
                if current_timeline:
                    try:
                        name = current_timeline.GetName()
                        if name:
                            logger.info(f"Got current timeline name using alternative method: {name}")
                            return [name]
                    except Exception as e:
                        logger.error(f"Error getting timeline name: {e}")
            except Exception as e:
                logger.error(f"Error in alternative timeline method: {e}")
        
        # Try alternative method: get timeline by index
        if self.api_capabilities.get("get_timeline_by_index", False):
            try:
                found_timelines = []
                for idx in range(5):  # Try indices 0-4
                    timeline = self.get_timeline_by_index(idx)
                    if timeline:
                        try:
                            name = timeline.GetName()
                            if name and name not in found_timelines:
                                found_timelines.append(name)
                        except Exception as e:
                            logger.error(f"Error getting name for timeline at index {idx}: {e}")
                
                if found_timelines:
                    logger.info(f"Found timelines using index method: {found_timelines}")
                    return found_timelines
            except Exception as e:
                logger.error(f"Error using timeline by index method: {e}")
        
        # If all methods fail
        return []
    
    def get_current_timeline(self):
        """Get the current timeline."""
        if not self.is_connected() or not self.current_project:
            logger.warning("Not connected or no project open when trying to get current timeline")
            return None
            
        try:
            timeline = self.current_project.GetCurrentTimeline()
            if timeline is None:
                logger.warning("GetCurrentTimeline returned None")
            return timeline
        except Exception as e:
            logger.error(f"Error getting current timeline: {e}")
            return None
    
    def get_timeline_by_index(self, index=0):
        """Alternative method to get a timeline by index without using GetTimelineNames."""
        if not self.is_connected() or not self.current_project:
            logger.warning("Not connected or no project open when trying to get timeline by index")
            return None
        
        try:
            # Try to get the timeline using index
            timeline = self.current_project.GetTimelineByIndex(index)
            if timeline:
                logger.info(f"Got timeline at index {index}")
                return timeline
            else:
                logger.warning(f"No timeline found at index {index}")
                return None
        except Exception as e:
            logger.error(f"Error getting timeline by index: {e}")
            # Fall back to current timeline
            try:
                return self.get_current_timeline()
            except Exception as inner_e:
                logger.error(f"Error in fallback to current timeline: {inner_e}")
                return None
    
    def get_timeline_items(self, timeline=None):
        """Get all timeline items from the timeline.
        
        Args:
            timeline: The timeline object. If None, uses current timeline.
            
        Returns:
            List of timeline items or None if no timeline is available.
        """
        if not self.is_connected() or not self.current_project:
            return None
            
        if timeline is None:
            timeline = self.get_current_timeline()
            
        if not timeline:
            return None
            
        try:
            # Get all items from all video tracks
            all_items = []
            video_track_count = timeline.GetTrackCount("video")
            
            for i in range(1, video_track_count + 1):
                try:
                    track_items = timeline.GetItemListInTrack("video", i)
                    if track_items:
                        all_items.extend(track_items)
                except Exception as e:
                    logger.error(f"Error getting items from track {i}: {str(e)}")
            
            # Also try audio tracks if needed
            # audio_track_count = timeline.GetTrackCount("audio")
            # for i in range(1, audio_track_count + 1):
            #     try:
            #         track_items = timeline.GetItemListInTrack("audio", i)
            #         if track_items:
            #             all_items.extend(track_items)
            #     except Exception as e:
            #         logger.error(f"Error getting items from audio track {i}: {str(e)}")
            
            return all_items
        except Exception as e:
            logger.error(f"Error getting timeline items: {str(e)}")
            return None
    
    def get_media_pool_items(self):
        """Get all media pool items."""
        if not self.is_connected() or not self.current_project:
            logger.warning("Not connected or no project open when trying to get media pool items")
            return []
        
        # Check if media pool capabilities are available
        if not self.api_capabilities.get("get_media_pool", False):
            logger.warning("GetMediaPool capability not available")
            return []
        
        try:
            media_pool = self.current_project.GetMediaPool()
            if not media_pool:
                logger.error("Failed to get media pool from project")
                return []
            
            # Check if root folder capability is available
            if not self.api_capabilities.get("get_root_folder", False):
                logger.warning("GetRootFolder capability not available")
                return []
            
            try:
                root_folder = media_pool.GetRootFolder()
                if not root_folder:
                    logger.error("Failed to get root folder from media pool")
                    return []
                
                # Check if clip list capability is available
                if not self.api_capabilities.get("get_clip_list", False):
                    logger.warning("GetClipList capability not available")
                    return []
                
                try:
                    clip_list = root_folder.GetClipList()
                    if clip_list is None:
                        logger.warning("GetClipList returned None")
                        return []
                    return clip_list
                except Exception as e:
                    logger.error(f"Error getting clip list from root folder: {e}")
                    return []
            except Exception as e:
                logger.error(f"Error getting root folder: {e}")
                return []
        except Exception as e:
            logger.error(f"Error getting media pool: {e}")
            return []
    
    def export_project_info(self) -> Dict[str, Any]:
        """Export basic information about the current project."""
        if not self.is_connected() or not self.current_project:
            return {"error": "Not connected to DaVinci Resolve or no project is open"}
        
        try:
            project_info = {
                "name": self.current_project.GetName(),
                "fps": None,
                "resolution": {
                    "width": None,
                    "height": None
                },
                "timelines": [],
                "current_timeline": None,
            }

            # Safely get FPS and resolution
            try:
                project_info["fps"] = self.current_project.GetSetting("timelineFrameRate")
            except Exception as e:
                logger.error(f"Error getting timeline frame rate: {e}")
            
            try:
                project_info["resolution"]["width"] = self.current_project.GetSetting("timelineResolutionWidth")
                project_info["resolution"]["height"] = self.current_project.GetSetting("timelineResolutionHeight")
            except Exception as e:
                logger.error(f"Error getting resolution settings: {e}")
            
            # Safely get timeline information
            try:
                timelines = self.get_timeline_list()
                project_info["timelines"] = timelines
            except Exception as e:
                logger.error(f"Error getting timeline list for project info: {e}")
            
            # Try to get timeline by index if timeline list is empty
            if not project_info["timelines"]:
                try:
                    # Try first few potential timelines
                    found_timelines = []
                    for idx in range(3):  # Try indices 0, 1, 2
                        timeline = self.get_timeline_by_index(idx)
                        if timeline:
                            try:
                                name = timeline.GetName()
                                if name:
                                    found_timelines.append(name)
                            except Exception as e:
                                logger.error(f"Error getting name for timeline at index {idx}: {e}")
                    
                    if found_timelines:
                        project_info["timelines"] = found_timelines
                        logger.info(f"Found timelines using index method: {found_timelines}")
                except Exception as e:
                    logger.error(f"Error using timeline by index method: {e}")
            
            # Safely get current timeline
            try:
                timeline = self.get_current_timeline()
                if timeline:
                    try:
                        project_info["current_timeline"] = timeline.GetName()
                    except Exception as e:
                        logger.error(f"Error getting current timeline name: {e}")
            except Exception as e:
                logger.error(f"Error getting current timeline: {e}")
            
            # Get media pool items count safely
            try:
                media_pool_items = self.get_media_pool_items()
                project_info["media_pool_item_count"] = len(media_pool_items) if media_pool_items else 0
            except Exception as e:
                logger.error(f"Error getting media pool items: {e}")
                project_info["media_pool_item_count"] = 0
            
            return project_info
        except Exception as e:
            logger.error(f"Error exporting project info: {e}")
            return {"error": f"Failed to get project info: {str(e)}"}

    def ensure_project_open(self) -> bool:
        """Ensure that a project is open in DaVinci Resolve."""
        if not self.is_connected():
            logger.error("Not connected to DaVinci Resolve")
            return False
        
        if not self.project_manager:
            logger.error("Project manager not available")
            return False
        
        if not self.current_project:
            # Try to open a project
            projects = self.get_project_list()
            if not projects:
                logger.error("No projects available to open")
                return False
            
            logger.info(f"Attempting to open project: {projects[0]}")
            success = self.open_project(projects[0])
            if not success:
                logger.error(f"Failed to open project: {projects[0]}")
                return False
            
            logger.info(f"Successfully opened project: {projects[0]}")
        
        return self.current_project is not None

    def select_clips_by_name(self, clip_name, timeline=None):
        """Select clips in the timeline by name.
        
        Args:
            clip_name: The name to search for in clip names (case-insensitive)
            timeline: Optional timeline object. If None, uses current timeline.
            
        Returns:
            Dictionary with results, including success status and counts.
        """
        result = {
            "success": False,
            "items_found": 0,
            "items_selected": 0,
            "error": None
        }
        
        if not self.is_connected():
            result["error"] = "Not connected to DaVinci Resolve"
            return result
            
        if not self.ensure_project_open():
            result["error"] = "No project is open"
            return result
            
        # Get timeline
        if timeline is None:
            timeline = self.get_current_timeline()
            
        if not timeline:
            result["error"] = "No timeline available"
            return result
            
        try:
            # Get all timeline items
            timeline_items = self.get_timeline_items(timeline)
            
            if not timeline_items:
                result["error"] = "No clips found in timeline"
                return result
                
            # Find matching clips
            matching_clips = []
            for item in timeline_items:
                try:
                    name = item.GetName()
                    if clip_name.lower() in name.lower():
                        matching_clips.append(item)
                except Exception as e:
                    logger.error(f"Error checking clip name: {e}")
            
            result["items_found"] = len(matching_clips)
            
            if not matching_clips:
                result["error"] = f"No clips found matching '{clip_name}'"
                return result
                
            # Try different methods to select the clips
            success = False
            
            # Method 1: Try SetSelection
            try:
                timeline.SetSelection(matching_clips)
                success = True
                logger.info(f"Selected {len(matching_clips)} clips using SetSelection")
            except Exception as e:
                logger.warning(f"SetSelection failed: {e}")
                
            # Method 2: Try individual selection with AddFlag
            if not success:
                try:
                    for clip in matching_clips:
                        clip.AddFlag("Selected")
                    success = True
                    logger.info(f"Selected {len(matching_clips)} clips using AddFlag")
                except Exception as e:
                    logger.error(f"AddFlag selection failed: {e}")
            
            if success:
                result["success"] = True
                result["items_selected"] = len(matching_clips)
            else:
                result["error"] = "Failed to select clips (API methods unavailable)"
                
            return result
                
        except Exception as e:
            logger.error(f"Error in select_clips_by_name: {e}")
            result["error"] = str(e)
            return result

def main():
    """Test the Resolve client."""
    client = ResolveClient()
    
    if client.is_connected():
        print(f"Connected to DaVinci Resolve")
        
        projects = client.get_project_list()
        print(f"Available projects: {projects}")
        
        if client.current_project:
            project_info = client.export_project_info()
            print(f"Current project info: {project_info}")
    else:
        print("Failed to connect to DaVinci Resolve")

if __name__ == "__main__":
    main() 