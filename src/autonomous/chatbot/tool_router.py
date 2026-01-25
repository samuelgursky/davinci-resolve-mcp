#!/usr/bin/env python3
"""
Tool Router for Resolve AI Chatbot

Routes AI function calls to the actual DaVinci Resolve tool implementations.
"""

import logging
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("chatbot.tool_router")

# Add src to path for imports
src_path = Path(__file__).parent.parent.parent
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))


class ToolRouter:
    """Routes tool calls to their implementations."""
    
    # Page name mappings
    PAGE_NAMES = {
        "media": "Media",
        "cut": "Cut", 
        "edit": "Edit",
        "fusion": "Fusion",
        "color": "Color",
        "fairlight": "Fairlight",
        "deliver": "Deliver"
    }
    
    def __init__(self):
        """Initialize the tool router."""
        self.resolve = None
        self.tools: Dict[str, Callable] = {}
        self._initialized = False
        self._current_page = None
    
    def initialize(self) -> bool:
        """
        Initialize connection to DaVinci Resolve and load tools.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Import and connect to Resolve
            from utils.resolve_connection import get_resolve_connection
            self.resolve = get_resolve_connection()
            
            if self.resolve is None:
                logger.error("Could not connect to DaVinci Resolve")
                return False
            
            # Register all tools
            self._register_tools()
            self._initialized = True
            
            logger.info(f"Tool router initialized with {len(self.tools)} tools")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize tool router: {e}")
            return False
    
    def _register_tools(self):
        """Register all available tools."""
        # Import tool functions from resolve_mcp_server
        # We need to import the actual functions, not the decorated versions
        
        try:
            # Project operations
            from api.project_operations import (
                open_project, create_project, save_project, close_project
            )
            self.tools['open_project'] = lambda **kw: open_project(self.resolve, **kw)
            self.tools['create_project'] = lambda **kw: create_project(self.resolve, **kw)
            self.tools['save_project'] = lambda **kw: save_project(self.resolve)
            self.tools['close_project'] = lambda **kw: close_project(self.resolve)
        except ImportError as e:
            logger.warning(f"Could not import project_operations: {e}")
        
        try:
            # Timeline operations
            from api.timeline_operations import (
                create_timeline, create_empty_timeline, delete_timeline,
                set_current_timeline, add_marker
            )
            self.tools['create_timeline'] = lambda **kw: create_timeline(self.resolve, **kw)
            self.tools['create_empty_timeline'] = lambda **kw: create_empty_timeline(self.resolve, **kw)
            self.tools['delete_timeline'] = lambda **kw: delete_timeline(self.resolve, **kw)
            self.tools['set_current_timeline'] = lambda **kw: set_current_timeline(self.resolve, **kw)
            self.tools['add_marker'] = lambda **kw: add_marker(self.resolve, **kw)
        except ImportError as e:
            logger.warning(f"Could not import timeline_operations: {e}")
        
        try:
            # Media operations
            from api.media_operations import (
                import_media, add_clip_to_timeline, create_bin,
                get_bin_contents
            )
            self.tools['import_media'] = lambda **kw: import_media(self.resolve, **kw)
            self.tools['add_clip_to_timeline'] = lambda **kw: add_clip_to_timeline(self.resolve, **kw)
            self.tools['create_bin'] = lambda **kw: create_bin(self.resolve, **kw)
            self.tools['list_bin_clips'] = lambda **kw: get_bin_contents(self.resolve, **kw)
        except ImportError as e:
            logger.warning(f"Could not import media_operations: {e}")
        
        try:
            # Color operations
            from api.color_presets import apply_preset_to_clips, get_available_presets
            self.tools['apply_color_preset'] = lambda **kw: apply_preset_to_clips(self.resolve, **kw)
            self.tools['list_color_presets'] = lambda **kw: get_available_presets()
        except ImportError as e:
            logger.warning(f"Could not import color_presets: {e}")
        
        try:
            # Color operations extended
            from api.color_operations import apply_lut
            self.tools['apply_lut'] = lambda **kw: apply_lut(self.resolve, **kw)
        except ImportError as e:
            logger.warning(f"Could not import color_operations: {e}")
        
        # Register inline implementations for complex tools
        self._register_inline_tools()
    
    def _register_inline_tools(self):
        """Register tools with inline implementations."""
        
        # Switch page
        def switch_page(page: str) -> str:
            if self.resolve is None:
                return "Error: Not connected to DaVinci Resolve"
            try:
                result = self.resolve.OpenPage(page)
                if result:
                    return f"Switched to {page} page"
                return f"Failed to switch to {page} page"
            except Exception as e:
                return f"Error: {e}"
        
        self.tools['switch_page'] = switch_page
        
        # Add clip from bin
        def add_clip_from_bin(clip_name: str, bin_name: str = "Master") -> str:
            if self.resolve is None:
                return "Error: Not connected to DaVinci Resolve"
            try:
                pm = self.resolve.GetProjectManager()
                project = pm.GetCurrentProject()
                media_pool = project.GetMediaPool()
                timeline = project.GetCurrentTimeline()
                
                if not timeline:
                    return "Error: No timeline active"
                
                # Find clip in bin
                root = media_pool.GetRootFolder()
                clip = None
                
                def find_clip(folder, target_bin, target_clip):
                    if folder.GetName() == target_bin or target_bin == "Master":
                        for c in folder.GetClipList() or []:
                            if c.GetName() == target_clip:
                                return c
                    for subfolder in folder.GetSubFolderList() or []:
                        result = find_clip(subfolder, target_bin, target_clip)
                        if result:
                            return result
                    return None
                
                clip = find_clip(root, bin_name, clip_name)
                
                if clip:
                    media_pool.AppendToTimeline([clip])
                    return f"Added '{clip_name}' to timeline"
                return f"Clip '{clip_name}' not found in '{bin_name}'"
            except Exception as e:
                return f"Error: {e}"
        
        self.tools['add_clip_from_bin'] = add_clip_from_bin
        
        # Add all clips from bin
        def add_all_bin_clips_to_timeline(bin_name: str, timeline_name: str = None) -> str:
            if self.resolve is None:
                return "Error: Not connected to DaVinci Resolve"
            try:
                pm = self.resolve.GetProjectManager()
                project = pm.GetCurrentProject()
                media_pool = project.GetMediaPool()
                
                # Find the bin
                root = media_pool.GetRootFolder()
                target_folder = root if bin_name == "Master" else None
                
                def find_folder(folder, name):
                    if folder.GetName() == name:
                        return folder
                    for sub in folder.GetSubFolderList() or []:
                        result = find_folder(sub, name)
                        if result:
                            return result
                    return None
                
                if not target_folder:
                    target_folder = find_folder(root, bin_name)
                
                if not target_folder:
                    return f"Bin '{bin_name}' not found"
                
                clips = target_folder.GetClipList() or []
                if not clips:
                    return f"No clips in bin '{bin_name}'"
                
                media_pool.AppendToTimeline(clips)
                return f"Added {len(clips)} clips from '{bin_name}' to timeline"
            except Exception as e:
                return f"Error: {e}"
        
        self.tools['add_all_bin_clips_to_timeline'] = add_all_bin_clips_to_timeline
        
        # Get audio clip path
        def get_audio_clip_path(clip_name: str) -> str:
            if self.resolve is None:
                return "Error: Not connected to DaVinci Resolve"
            try:
                pm = self.resolve.GetProjectManager()
                project = pm.GetCurrentProject()
                media_pool = project.GetMediaPool()
                root = media_pool.GetRootFolder()
                
                def find_clip(folder):
                    for clip in folder.GetClipList() or []:
                        if clip.GetName() == clip_name:
                            props = clip.GetClipProperty()
                            return props.get("File Path", "")
                    for sub in folder.GetSubFolderList() or []:
                        result = find_clip(sub)
                        if result:
                            return result
                    return None
                
                path = find_clip(root)
                return path if path else f"Clip '{clip_name}' not found"
            except Exception as e:
                return f"Error: {e}"
        
        self.tools['get_audio_clip_path'] = get_audio_clip_path
        self.tools['get_video_clip_path'] = get_audio_clip_path  # Same implementation
        
        # Beat analysis
        def analyze_audio_beats(audio_file_path: str) -> Dict:
            try:
                from autonomous.beat_analyzer import BeatAnalyzer
                analyzer = BeatAnalyzer()
                result = analyzer.analyze(audio_file_path)
                if result:
                    return {
                        'success': True,
                        'bpm': round(result.bpm, 1),
                        'total_beats': len(result.beat_times),
                        'duration': round(result.duration, 1)
                    }
                return {'success': False, 'error': 'Analysis failed'}
            except Exception as e:
                return {'success': False, 'error': str(e)}
        
        self.tools['analyze_audio_beats'] = analyze_audio_beats
        
        # Add beat markers
        def add_beat_markers(audio_file_path: str, marker_color: str = "Blue", max_markers: int = 50) -> str:
            if self.resolve is None:
                return "Error: Not connected to DaVinci Resolve"
            try:
                from autonomous.beat_analyzer import BeatAnalyzer
                analyzer = BeatAnalyzer()
                result = analyzer.analyze(audio_file_path)
                
                if not result:
                    return "Beat analysis failed"
                
                pm = self.resolve.GetProjectManager()
                project = pm.GetCurrentProject()
                timeline = project.GetCurrentTimeline()
                
                if not timeline:
                    return "No timeline active"
                
                fps = float(timeline.GetSetting("timelineFrameRate") or 24)
                start_frame = timeline.GetStartFrame()
                
                markers_added = 0
                for beat_time in result.beat_times[:max_markers]:
                    frame = int(beat_time * fps) + start_frame
                    try:
                        timeline.AddMarker(frame, marker_color, f"Beat", "", 1, "")
                        markers_added += 1
                    except:
                        pass
                
                return f"Added {markers_added} beat markers. BPM: {result.bpm:.1f}"
            except Exception as e:
                return f"Error: {e}"
        
        self.tools['add_beat_markers'] = add_beat_markers
        
        # Render queue
        def add_to_render_queue(**kwargs) -> str:
            if self.resolve is None:
                return "Error: Not connected to DaVinci Resolve"
            try:
                pm = self.resolve.GetProjectManager()
                project = pm.GetCurrentProject()
                project.AddRenderJob()
                return "Added to render queue"
            except Exception as e:
                return f"Error: {e}"
        
        self.tools['add_to_render_queue'] = add_to_render_queue
        
        def start_render(**kwargs) -> str:
            if self.resolve is None:
                return "Error: Not connected to DaVinci Resolve"
            try:
                pm = self.resolve.GetProjectManager()
                project = pm.GetCurrentProject()
                project.StartRendering()
                return "Render started"
            except Exception as e:
                return f"Error: {e}"
        
        self.tools['start_render'] = start_render
        
        def clear_render_queue(**kwargs) -> str:
            if self.resolve is None:
                return "Error: Not connected to DaVinci Resolve"
            try:
                pm = self.resolve.GetProjectManager()
                project = pm.GetCurrentProject()
                project.DeleteAllRenderJobs()
                return "Render queue cleared"
            except Exception as e:
                return f"Error: {e}"
        
        self.tools['clear_render_queue'] = clear_render_queue
        
        # Context/state tools
        def get_current_page_tool() -> str:
            page = self.get_current_page()
            return f"Current page: {page}"
        
        self.tools['get_current_page'] = get_current_page_tool
        
        def get_timeline_info() -> Dict:
            if self.resolve is None:
                return {"error": "Not connected to DaVinci Resolve"}
            try:
                pm = self.resolve.GetProjectManager()
                project = pm.GetCurrentProject()
                timeline = project.GetCurrentTimeline()
                
                if not timeline:
                    return {"error": "No timeline active"}
                
                return {
                    "name": timeline.GetName(),
                    "video_tracks": timeline.GetTrackCount("video"),
                    "audio_tracks": timeline.GetTrackCount("audio"),
                    "start_frame": timeline.GetStartFrame(),
                    "end_frame": timeline.GetEndFrame(),
                    "frame_rate": timeline.GetSetting("timelineFrameRate"),
                    "resolution": f"{timeline.GetSetting('timelineResolutionWidth')}x{timeline.GetSetting('timelineResolutionHeight')}"
                }
            except Exception as e:
                return {"error": str(e)}
        
        self.tools['get_timeline_info'] = get_timeline_info
        
        def get_audio_info() -> Dict:
            return self.get_timeline_audio_info()
        
        self.tools['get_audio_info'] = get_audio_info
        
        def get_video_info() -> Dict:
            return self.get_timeline_video_info()
        
        self.tools['get_video_info'] = get_video_info
    
    def execute(self, tool_name: str, args: Dict[str, Any]) -> str:
        """
        Execute a tool by name with the given arguments.
        
        Args:
            tool_name: Name of the tool to execute
            args: Arguments to pass to the tool
            
        Returns:
            Result string from the tool
        """
        if not self._initialized:
            return "Error: Tool router not initialized"
        
        tool = self.tools.get(tool_name)
        if not tool:
            return f"Error: Unknown tool '{tool_name}'"
        
        try:
            logger.info(f"Executing tool: {tool_name} with args: {args}")
            result = tool(**args)
            
            # Convert result to string if needed
            if isinstance(result, dict):
                import json
                return json.dumps(result, indent=2)
            return str(result)
            
        except Exception as e:
            error_msg = f"Error executing {tool_name}: {e}"
            logger.error(error_msg)
            return error_msg
    
    def get_available_tools(self) -> list:
        """Get list of available tool names."""
        return list(self.tools.keys())
    
    def is_connected(self) -> bool:
        """Check if connected to DaVinci Resolve."""
        return self.resolve is not None
    
    def get_current_page(self) -> str:
        """
        Get the current page/workspace in DaVinci Resolve.
        
        Returns:
            Page name: media, cut, edit, fusion, color, fairlight, deliver
        """
        if self.resolve is None:
            return "unknown"
        
        try:
            page = self.resolve.GetCurrentPage()
            self._current_page = page
            return page if page else "unknown"
        except Exception as e:
            logger.warning(f"Could not get current page: {e}")
            return "unknown"
    
    def get_page_context(self) -> Dict[str, Any]:
        """
        Get detailed context about the current page and state.
        
        Returns:
            Dictionary with page info and relevant context
        """
        context = {
            "page": self.get_current_page(),
            "project": None,
            "timeline": None,
            "selected_clips": [],
            "audio_tracks": 0,
            "video_tracks": 0
        }
        
        if self.resolve is None:
            return context
        
        try:
            pm = self.resolve.GetProjectManager()
            project = pm.GetCurrentProject()
            
            if project:
                context["project"] = project.GetName()
                timeline = project.GetCurrentTimeline()
                
                if timeline:
                    context["timeline"] = timeline.GetName()
                    context["video_tracks"] = timeline.GetTrackCount("video")
                    context["audio_tracks"] = timeline.GetTrackCount("audio")
                    
                    # Get selected items on current page
                    page = context["page"]
                    if page == "color":
                        # Try to get current clip on color page
                        try:
                            current_clip = timeline.GetCurrentVideoItem()
                            if current_clip:
                                context["current_clip"] = current_clip.GetName()
                        except:
                            pass
                    elif page == "fairlight":
                        # Audio-specific context
                        context["fairlight_context"] = {
                            "audio_tracks": context["audio_tracks"],
                            "can_edit_audio": True
                        }
                    elif page == "fusion":
                        # Fusion-specific context
                        context["fusion_context"] = {
                            "can_edit_nodes": True
                        }
        except Exception as e:
            logger.warning(f"Error getting page context: {e}")
        
        return context
    
    def get_timeline_audio_info(self) -> Dict[str, Any]:
        """Get detailed audio information from the current timeline."""
        info = {
            "audio_tracks": [],
            "total_audio_clips": 0
        }
        
        if self.resolve is None:
            return info
        
        try:
            pm = self.resolve.GetProjectManager()
            project = pm.GetCurrentProject()
            timeline = project.GetCurrentTimeline()
            
            if not timeline:
                return info
            
            audio_track_count = timeline.GetTrackCount("audio")
            
            for track_idx in range(1, audio_track_count + 1):
                track_name = timeline.GetTrackName("audio", track_idx)
                items = timeline.GetItemListInTrack("audio", track_idx)
                clip_count = len(items) if items else 0
                info["audio_tracks"].append({
                    "index": track_idx,
                    "name": track_name,
                    "clip_count": clip_count
                })
                info["total_audio_clips"] += clip_count
                
        except Exception as e:
            logger.warning(f"Error getting audio info: {e}")
        
        return info
    
    def get_timeline_video_info(self) -> Dict[str, Any]:
        """Get detailed video information from the current timeline."""
        info = {
            "video_tracks": [],
            "total_video_clips": 0
        }
        
        if self.resolve is None:
            return info
        
        try:
            pm = self.resolve.GetProjectManager()
            project = pm.GetCurrentProject()
            timeline = project.GetCurrentTimeline()
            
            if not timeline:
                return info
            
            video_track_count = timeline.GetTrackCount("video")
            
            for track_idx in range(1, video_track_count + 1):
                track_name = timeline.GetTrackName("video", track_idx)
                items = timeline.GetItemListInTrack("video", track_idx)
                clip_names = []
                if items:
                    for item in items:
                        try:
                            clip_names.append(item.GetName())
                        except:
                            pass
                info["video_tracks"].append({
                    "index": track_idx,
                    "name": track_name,
                    "clip_count": len(items) if items else 0,
                    "clips": clip_names[:5]  # First 5 clip names
                })
                info["total_video_clips"] += len(items) if items else 0
                
        except Exception as e:
            logger.warning(f"Error getting video info: {e}")
        
        return info


# Singleton instance
_router_instance: Optional[ToolRouter] = None


def get_tool_router() -> ToolRouter:
    """Get the singleton tool router instance."""
    global _router_instance
    if _router_instance is None:
        _router_instance = ToolRouter()
    return _router_instance
