from mcp.server.fastmcp import FastMCP
import sys
import os


# Add DaVinci Resolve script module paths based on OS
def add_resolve_module_path():
    """Add the appropriate DaVinci Resolve API path based on the operating system."""
    if sys.platform.startswith("darwin"):
        # macOS
        resolve_api_path = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/"
        script_path = os.path.expanduser("~/") + resolve_api_path
        if not os.path.isdir(script_path):
            script_path = resolve_api_path
    elif sys.platform.startswith("win") or sys.platform.startswith("cygwin"):
        # Windows
        resolve_api_path = "C:\\ProgramData\\Blackmagic Design\\DaVinci Resolve\\Support\\Developer\\Scripting\\Modules\\"
        script_path = resolve_api_path
    elif sys.platform.startswith("linux"):
        # Linux
        resolve_api_path = "/opt/resolve/Developer/Scripting/Modules/"
        script_path = resolve_api_path
    else:
        raise ValueError(f"Unsupported platform: {sys.platform}")

    if os.path.isdir(script_path):
        sys.path.append(script_path)
        return True
    else:
        return False


# Initialize Resolve API
def init_resolve():
    """Initialize the DaVinci Resolve API and return the Resolve object."""
    if add_resolve_module_path():
        import DaVinciResolveScript as dvr_script

        resolve = dvr_script.scriptapp("Resolve")
        if not resolve:
            print(
                "Error: Unable to connect to DaVinci Resolve. Make sure Resolve is running."
            )
            return None
        return resolve
    else:
        print("Error: Could not locate DaVinci Resolve API modules.")
        return None


# Create an MCP server for DaVinci Resolve
def create_server():
    """Create and return the DaVinci Resolve MCP server."""
    # Initialize Resolve
    try:
        resolve = init_resolve()
        if not resolve:
            sys.exit(1)
    except ImportError:
        print(
            "Error: Could not import DaVinci Resolve API. Make sure Resolve is running."
        )
        sys.exit(1)

    # Create MCP server
    mcp = FastMCP("DaVinci Resolve")

    @mcp.tool()
    def get_timeline_clip_names() -> list:
        """Get the names of all clips in the current timeline."""
        try:
            # Navigate the Resolve object hierarchy to reach the timeline
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()

            if not project:
                return {"error": "No project is currently open"}

            timeline = project.GetCurrentTimeline()

            if not timeline:
                return {"error": "No timeline is currently open"}

            # Get all clips in the timeline
            clip_names = []
            video_tracks_count = timeline.GetTrackCount("video")

            for track_index in range(1, video_tracks_count + 1):
                # GetItemListInTrack returns a list of clips
                clips = timeline.GetItemListInTrack("video", track_index)
                if clips:
                    for clip in clips:
                        clip_names.append(
                            {
                                "track": f"V{track_index}",
                                "name": clip.GetName(),
                                "duration": clip.GetDuration(),
                            }
                        )

            # Also get audio clips
            audio_tracks_count = timeline.GetTrackCount("audio")
            for track_index in range(1, audio_tracks_count + 1):
                clips = timeline.GetItemListInTrack("audio", track_index)
                if clips:
                    for clip in clips:
                        clip_names.append(
                            {
                                "track": f"A{track_index}",
                                "name": clip.GetName(),
                                "duration": clip.GetDuration(),
                            }
                        )

            return clip_names
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    @mcp.tool()
    def get_project_info() -> dict:
        """Get information about the current project in DaVinci Resolve."""
        try:
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()

            if not project:
                return {"error": "No project is currently open"}

            # Get the timeline count
            timeline_count = project.GetTimelineCount()

            return {
                "name": project.GetName(),
                "frame_rate": project.GetSetting("timelineFrameRate"),
                "resolution": {
                    "width": project.GetSetting("timelineResolutionWidth"),
                    "height": project.GetSetting("timelineResolutionHeight"),
                },
                "timeline_count": timeline_count,
            }
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    @mcp.tool()
    def get_current_timeline_name() -> str:
        """Get the name of the current timeline."""
        try:
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()

            if not project:
                return "No project is currently open"

            timeline = project.GetCurrentTimeline()

            if not timeline:
                return "No timeline is currently open"

            return timeline.GetName()
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    def get_timeline_info() -> dict:
        """Get detailed information about the current timeline."""
        try:
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()

            if not project:
                return {"error": "No project is currently open"}

            timeline = project.GetCurrentTimeline()

            if not timeline:
                return {"error": "No timeline is currently open"}

            # Get timeline information - only use methods that are confirmed to work
            info = {
                "name": timeline.GetName(),
                "video_track_count": timeline.GetTrackCount("video"),
                "audio_track_count": timeline.GetTrackCount("audio"),
            }

            # Try to get additional timeline information that might be available
            try:
                info["start_frame"] = timeline.GetStartFrame()
                info["end_frame"] = timeline.GetEndFrame()

                # Only calculate frame count if both start and end frames were retrieved
                if "start_frame" in info and "end_frame" in info:
                    info["frame_count"] = info["end_frame"] - info["start_frame"] + 1
            except:
                pass

            # Try to get timecode information
            try:
                info["timecode_start"] = timeline.GetStartTimecode()
                info["timecode_end"] = timeline.GetEndTimecode()
            except:
                pass

            # Try to get additional settings from project
            try:
                info["fps"] = project.GetSetting("timelineFrameRate")
                info["resolution"] = {
                    "width": project.GetSetting("timelineResolutionWidth"),
                    "height": project.GetSetting("timelineResolutionHeight"),
                }
            except:
                pass

            return info
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    @mcp.tool()
    def get_clip_details(
        track_type: str = "video", track_index: int = 1, clip_index: int = 0
    ) -> dict:
        """Get detailed information about a specific clip in the timeline.

        Args:
            track_type: The type of track ('video' or 'audio')
            track_index: The index of the track (1-based)
            clip_index: The index of the clip in the track (0-based)

        Returns:
            A dictionary with clip details or an error message
        """
        try:
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()

            if not project:
                return {"error": "No project is currently open"}

            timeline = project.GetCurrentTimeline()

            if not timeline:
                return {"error": "No timeline is currently open"}

            # Validate track type
            if track_type not in ["video", "audio"]:
                return {"error": "Track type must be 'video' or 'audio'"}

            # Validate track index
            track_count = timeline.GetTrackCount(track_type)
            if track_index < 1 or track_index > track_count:
                return {"error": f"Track index must be between 1 and {track_count}"}

            # Get clips in the track
            clips = timeline.GetItemListInTrack(track_type, track_index)

            if not clips or len(clips) <= clip_index:
                return {
                    "error": f"Clip index {clip_index} not found in {track_type} track {track_index}"
                }

            # Get the specific clip
            clip = clips[clip_index]

            # Collect basic clip properties
            properties = {"name": clip.GetName(), "duration": clip.GetDuration()}

            # Try to get additional timeline item properties
            try:
                properties["start_frame"] = clip.GetStart()
                properties["end_frame"] = clip.GetEnd()
            except:
                pass

            try:
                properties["track"] = f"{track_type[0].upper()}{track_index}"
            except:
                pass

            # Try to access media pool item in multiple ways
            try:
                # First try the standard method
                media_item = clip.GetMediaPoolItem()
                has_media_item = media_item is not None
                properties["media_pool_item"] = has_media_item

                # If we have a valid media pool item, get its properties
                if has_media_item:
                    try:
                        media_props = {"name": media_item.GetName()}

                        # Try to get additional media properties
                        try:
                            media_props["clip_color"] = media_item.GetClipColor()
                        except:
                            pass

                        # Try to get clip properties using the GetClipProperty method
                        for prop in [
                            "Duration",
                            "FPS",
                            "File Path",
                            "Resolution",
                            "Format",
                        ]:
                            try:
                                media_props[prop.lower().replace(" ", "_")] = (
                                    media_item.GetClipProperty(prop)
                                )
                            except:
                                pass

                        properties["media"] = media_props
                    except Exception as e:
                        properties["media_error"] = str(e)
                else:
                    # Alternative approach for media properties
                    try:
                        # Try to access metadata directly from the timeline item
                        if hasattr(clip, "GetMetadata"):
                            metadata = clip.GetMetadata()
                            if metadata:
                                properties["metadata"] = metadata
                    except:
                        pass
            except Exception as e:
                properties["media_pool_error"] = str(e)

            return properties
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    @mcp.tool()
    def get_project_timelines() -> list:
        """Get a list of all timelines in the current project."""
        try:
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()

            if not project:
                return {"error": "No project is currently open"}

            # Get the number of timelines in the project
            timeline_count = project.GetTimelineCount()

            # Get information about each timeline
            timelines = []
            for i in range(1, timeline_count + 1):
                try:
                    timeline = project.GetTimelineByIndex(i)
                    if timeline:
                        timeline_info = {"index": i, "name": timeline.GetName()}

                        # Try to get additional information
                        try:
                            timeline_info["video_track_count"] = timeline.GetTrackCount(
                                "video"
                            )
                            timeline_info["audio_track_count"] = timeline.GetTrackCount(
                                "audio"
                            )
                        except:
                            pass

                        timelines.append(timeline_info)
                except:
                    continue

            return timelines
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    @mcp.tool()
    def get_timeline_markers() -> list:
        """Get all markers in the current timeline."""
        try:
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()

            if not project:
                return {"error": "No project is currently open"}

            timeline = project.GetCurrentTimeline()

            if not timeline:
                return {"error": "No timeline is currently open"}

            # Get the markers
            markers = []
            marker_list = timeline.GetMarkers()

            if marker_list:
                for frame_id, marker_info in marker_list.items():
                    marker = {
                        "frame": frame_id,
                        "name": marker_info.get("name", ""),
                        "color": marker_info.get("color", ""),
                        "duration": marker_info.get("duration", 1),
                        "note": marker_info.get("note", ""),
                    }
                    markers.append(marker)

            return markers
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    @mcp.tool()
    def get_active_track_info() -> dict:
        """Get information about the currently active track in the timeline."""
        try:
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()

            if not project:
                return {"error": "No project is currently open"}

            timeline = project.GetCurrentTimeline()

            if not timeline:
                return {"error": "No timeline is currently open"}

            # Get information about the currently active track
            track_info = {}

            # Try to get video track selection
            try:
                selected_tracks = timeline.GetHighlightedTracks()
                if selected_tracks:
                    track_info["selected_tracks"] = selected_tracks
            except:
                pass

            # Try to get current video track
            try:
                video_track_count = timeline.GetTrackCount("video")
                for i in range(1, video_track_count + 1):
                    if timeline.IsTrackEnabled("video", i):
                        clips = timeline.GetItemListInTrack("video", i)
                        if "video_tracks" not in track_info:
                            track_info["video_tracks"] = []
                        track_info["video_tracks"].append(
                            {
                                "index": i,
                                "enabled": True,
                                "clip_count": len(clips) if clips else 0,
                            }
                        )
                    else:
                        if "video_tracks" not in track_info:
                            track_info["video_tracks"] = []
                        track_info["video_tracks"].append(
                            {"index": i, "enabled": False}
                        )
            except:
                pass

            # Try to get current audio track
            try:
                audio_track_count = timeline.GetTrackCount("audio")
                for i in range(1, audio_track_count + 1):
                    if timeline.IsTrackEnabled("audio", i):
                        clips = timeline.GetItemListInTrack("audio", i)
                        if "audio_tracks" not in track_info:
                            track_info["audio_tracks"] = []
                        track_info["audio_tracks"].append(
                            {
                                "index": i,
                                "enabled": True,
                                "clip_count": len(clips) if clips else 0,
                            }
                        )
                    else:
                        if "audio_tracks" not in track_info:
                            track_info["audio_tracks"] = []
                        track_info["audio_tracks"].append(
                            {"index": i, "enabled": False}
                        )
            except:
                pass

            return track_info
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    @mcp.tool()
    def get_media_pool_items() -> list:
        """Get a list of all items in the media pool."""
        try:
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()

            if not project:
                return {"error": "No project is currently open"}

            media_pool = project.GetMediaPool()
            if not media_pool:
                return {"error": "Could not access the media pool"}

            # Get the root folder
            root_folder = media_pool.GetRootFolder()
            if not root_folder:
                return {"error": "Could not access the root folder"}

            # Get all clips in the root folder
            clips = root_folder.GetClipList()

            # Format the clip information
            media_items = []
            for clip in clips:
                # Get basic clip properties
                item = {"name": clip.GetName(), "duration": clip.GetDuration()}

                # Try to get additional clip properties
                try:
                    for prop in [
                        "FPS",
                        "Resolution",
                        "Format",
                        "File Path",
                        "Clip Color",
                    ]:
                        try:
                            value = clip.GetClipProperty(prop)
                            if value:
                                item[prop.lower().replace(" ", "_")] = value
                        except:
                            pass
                except:
                    pass

                media_items.append(item)

            return media_items
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    @mcp.tool()
    def get_media_pool_structure() -> dict:
        """Get the folder structure of the media pool."""
        try:
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()

            if not project:
                return {"error": "No project is currently open"}

            media_pool = project.GetMediaPool()
            if not media_pool:
                return {"error": "Could not access the media pool"}

            # Get the root folder
            root_folder = media_pool.GetRootFolder()
            if not root_folder:
                return {"error": "Could not access the root folder"}

            # Helper function to process a folder recursively
            def process_folder(folder):
                folder_data = {"name": folder.GetName(), "clips": [], "subfolders": []}

                # Get clips in the folder
                clips = folder.GetClipList()
                if clips:
                    for clip in clips:
                        clip_info = {
                            "name": clip.GetName(),
                            "duration": clip.GetDuration(),
                        }
                        folder_data["clips"].append(clip_info)

                # Get subfolders
                subfolders = folder.GetSubFolderList()
                if subfolders:
                    for subfolder in subfolders:
                        folder_data["subfolders"].append(process_folder(subfolder))

                return folder_data

            # Start with the root folder
            media_structure = process_folder(root_folder)

            return media_structure
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    @mcp.tool()
    def get_playhead_position() -> dict:
        """Get the current playhead position in the timeline."""
        try:
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()

            if not project:
                return {"error": "No project is currently open"}

            timeline = project.GetCurrentTimeline()

            if not timeline:
                return {"error": "No timeline is currently open"}

            # Get the current position
            position = {}

            # Try to get frame number
            try:
                current_frame = timeline.GetCurrentVideoItem().GetStart()
                position["frame"] = current_frame
            except:
                try:
                    # Alternative method
                    current_frame = timeline.GetCurrentFrame()
                    position["frame"] = current_frame
                except:
                    pass

            # Try to get timecode
            try:
                current_timecode = timeline.GetCurrentTimecode()
                position["timecode"] = current_timecode
            except:
                pass

            # Calculate time in seconds if possible
            if "frame" in position and timeline.GetSetting("fps"):
                try:
                    fps = float(timeline.GetSetting("fps"))
                    if fps > 0:
                        seconds = position["frame"] / fps
                        position["seconds"] = seconds
                except:
                    pass

            return position
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    @mcp.tool()
    def control_playback(command: str = "play") -> dict:
        """Control the playback of the timeline.

        Args:
            command: The playback command to execute.
                     Options: play, stop, pause, forward, reverse, next_frame, prev_frame,
                     next_clip, prev_clip, to_in, to_out, toggle_play

        Returns:
            Status of the operation
        """
        try:
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()

            if not project:
                return {"error": "No project is currently open"}

            # Get the current timeline
            timeline = project.GetCurrentTimeline()
            if not timeline:
                return {"error": "No timeline is currently open"}

            # Access the playback controls
            valid_commands = [
                "play",
                "stop",
                "pause",
                "forward",
                "reverse",
                "next_frame",
                "prev_frame",
                "next_clip",
                "prev_clip",
                "to_in",
                "to_out",
                "toggle_play",
            ]

            if command not in valid_commands:
                return {
                    "error": f"Invalid command. Valid options are: {', '.join(valid_commands)}"
                }

            # Apply the requested command
            result = {"command": command, "status": "executed"}

            try:
                if command == "play":
                    timeline.Play()
                elif command == "stop":
                    timeline.Stop()
                elif command == "pause":
                    timeline.Pause()
                elif command == "toggle_play":
                    # This is a custom command that toggles between play and pause
                    if timeline.IsPlaying():
                        timeline.Pause()
                        result["new_state"] = "paused"
                    else:
                        timeline.Play()
                        result["new_state"] = "playing"
                elif command == "forward":
                    timeline.SetPlaybackSpeed(2.0)  # Play forward at 2x speed
                elif command == "reverse":
                    timeline.SetPlaybackSpeed(-1.0)  # Play in reverse
                elif command == "next_frame":
                    timeline.GoToNextFrame()
                elif command == "prev_frame":
                    timeline.GoToPreviousFrame()
                elif command == "next_clip":
                    timeline.GoToNextClip()
                elif command == "prev_clip":
                    timeline.GoToPreviousClip()
                elif command == "to_in":
                    timeline.GoToIn()
                elif command == "to_out":
                    timeline.GoToOut()
            except Exception as e:
                return {"error": f"Failed to execute command '{command}': {str(e)}"}

            # Try to get current position after command
            try:
                result["position"] = {
                    "timecode": timeline.GetCurrentTimecode(),
                    "frame": timeline.GetCurrentFrame(),
                }
            except:
                pass

            return result
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    @mcp.tool()
    def get_selected_clips() -> list:
        """Get information about the currently selected clips in the timeline."""
        try:
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()

            if not project:
                return {"error": "No project is currently open"}

            timeline = project.GetCurrentTimeline()

            if not timeline:
                return {"error": "No timeline is currently open"}

            # Get the selected clips
            selected_clips = []

            try:
                # Get all selected items on the timeline
                clips = timeline.GetCurrentSelectedItems()

                if not clips:
                    return []

                for clip in clips:
                    clip_info = {"name": clip.GetName(), "duration": clip.GetDuration()}

                    # Try to get more properties
                    try:
                        clip_info["start_frame"] = clip.GetStart()
                        clip_info["end_frame"] = clip.GetEnd()
                    except:
                        pass

                    try:
                        clip_info["track_index"] = clip.GetTrackIndex()
                    except:
                        pass

                    # Check what type of clip this is
                    try:
                        if clip.GetFusionCompCount:  # Check if this is a Fusion clip
                            clip_info["type"] = "fusion"
                        elif clip.GetStillFrameFlag:  # Check if this is a still frame
                            clip_info["type"] = "still"
                        else:
                            clip_info["type"] = "standard"
                    except:
                        clip_info["type"] = "unknown"

                    selected_clips.append(clip_info)

                return selected_clips
            except Exception as e:
                return {"error": f"Failed to get selected clips: {str(e)}"}
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    @mcp.tool()
    def add_clip_to_timeline(
        media_pool_item_name: str = "",
        track_index: int = 1,
        track_type: str = "video",
        frame_position: int = -1,
    ) -> dict:
        """Add a clip from the media pool to the timeline.

        Args:
            media_pool_item_name: The name of the media pool item to add
            track_index: The index of the track to add the clip to (1-based)
            track_type: The type of track ('video' or 'audio')
            frame_position: The frame position to add the clip (or -1 for current position)

        Returns:
            Status of the operation
        """
        try:
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()

            if not project:
                return {"error": "No project is currently open"}

            media_pool = project.GetMediaPool()
            if not media_pool:
                return {"error": "Could not access the media pool"}

            timeline = project.GetCurrentTimeline()
            if not timeline:
                return {"error": "No timeline is currently open"}

            # Validate track type
            if track_type not in ["video", "audio"]:
                return {"error": "Track type must be 'video' or 'audio'"}

            # Validate track index
            track_count = timeline.GetTrackCount(track_type)
            if track_index < 1 or track_index > track_count:
                return {"error": f"Track index must be between 1 and {track_count}"}

            # Find the media pool item by name
            root_folder = media_pool.GetRootFolder()
            if not root_folder:
                return {"error": "Could not access the root folder"}

            # Get all clips in the root folder
            clips = root_folder.GetClipList()
            target_clip = None

            for clip in clips:
                if clip.GetName() == media_pool_item_name:
                    target_clip = clip
                    break

            if not target_clip:
                return {
                    "error": f"Could not find media pool item with name '{media_pool_item_name}'"
                }

            # Set the target track
            media_pool.SetCurrentFolder(root_folder)

            # Insert options
            insert_options = {"targetTrack": track_index, "mediaType": track_type}

            if frame_position >= 0:
                insert_options["startFrame"] = frame_position

            # Add the clip to the timeline
            result = media_pool.AppendToTimeline([target_clip])

            if not result:
                # Try alternative method
                result = timeline.InsertClip(target_clip, insert_options)

            if result:
                return {
                    "status": "success",
                    "message": f"Added clip '{media_pool_item_name}' to {track_type} track {track_index}",
                }
            else:
                return {"error": "Failed to add clip to timeline"}
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    @mcp.tool()
    def get_project_list() -> list:
        """Get a list of all projects in the current database."""
        try:
            project_manager = resolve.GetProjectManager()
            if not project_manager:
                return {"error": "Could not access the project manager"}

            # Get the current project to restore it later
            current_project = project_manager.GetCurrentProject()
            current_project_name = None
            if current_project:
                current_project_name = current_project.GetName()

            # Get all projects
            project_list = []
            projects = None

            try:
                # Get the list of projects
                projects = project_manager.GetProjectListInCurrentFolder()

                if projects:
                    for project_name in projects:
                        # Try to load each project to get its details
                        project = project_manager.LoadProject(project_name)

                        if project:
                            # Get project details
                            project_info = {
                                "name": project_name,
                                "fps": project.GetSetting("timelineFrameRate"),
                                "resolution": {
                                    "width": project.GetSetting(
                                        "timelineResolutionWidth"
                                    ),
                                    "height": project.GetSetting(
                                        "timelineResolutionHeight"
                                    ),
                                },
                            }

                            # Get timeline count
                            try:
                                timeline_count = project.GetTimelineCount()
                                project_info["timeline_count"] = timeline_count
                            except:
                                pass

                            project_list.append(project_info)
            except Exception as e:
                error_msg = f"Failed to get project list: {str(e)}"

            # Always restore the original project
            if current_project_name:
                try:
                    project_manager.LoadProject(current_project_name)
                except:
                    pass

            if "error_msg" in locals():
                return {"error": error_msg}

            return project_list
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    @mcp.tool()
    def switch_to_project(project_name: str = "") -> dict:
        """Switch to a different project.

        Args:
            project_name: The name of the project to switch to

        Returns:
            Status of the operation
        """
        try:
            project_manager = resolve.GetProjectManager()
            if not project_manager:
                return {"error": "Could not access the project manager"}

            # Get the current project name
            current_project = project_manager.GetCurrentProject()
            current_project_name = (
                current_project.GetName() if current_project else "None"
            )

            if not project_name:
                return {"error": "No project name provided"}

            # Check if we're already on this project
            if current_project_name == project_name:
                return {
                    "status": "success",
                    "message": f"Already on project '{project_name}'",
                }

            # Get the list of projects
            projects = project_manager.GetProjectListInCurrentFolder()

            if not projects:
                return {"error": "No projects found in the current folder"}

            if project_name not in projects:
                return {
                    "error": f"Project '{project_name}' not found in the current folder"
                }

            # Switch to the project
            project = project_manager.LoadProject(project_name)

            if not project:
                return {"error": f"Failed to load project '{project_name}'"}

            # Get some details about the project
            project_info = {
                "name": project_name,
                "fps": project.GetSetting("timelineFrameRate"),
                "resolution": {
                    "width": project.GetSetting("timelineResolutionWidth"),
                    "height": project.GetSetting("timelineResolutionHeight"),
                },
            }

            # Get timeline count and names
            try:
                timeline_count = project.GetTimelineCount()
                project_info["timeline_count"] = timeline_count

                if timeline_count > 0:
                    timeline_names = []
                    for i in range(1, timeline_count + 1):
                        try:
                            timeline = project.GetTimelineByIndex(i)
                            if timeline:
                                timeline_names.append(timeline.GetName())
                        except:
                            pass

                    project_info["timelines"] = timeline_names
            except:
                pass

            return {
                "status": "success",
                "message": f"Switched to project '{project_name}'",
                "project_info": project_info,
            }
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    return mcp


def run_server():
    """Run the DaVinci Resolve MCP server."""
    mcp = create_server()
    port = int(os.environ.get("PORT", 8000))
    print(f"Starting DaVinci Resolve MCP server on http://localhost:{port}")
    mcp.run(port=port)


if __name__ == "__main__":
    run_server()
from mcp.server.fastmcp import FastMCP
import sys
import os


# Add DaVinci Resolve script module paths based on OS
def add_resolve_module_path():
    """Add the appropriate DaVinci Resolve API path based on the operating system."""
    if sys.platform.startswith("darwin"):
        # macOS
        resolve_api_path = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/"
        script_path = os.path.expanduser("~/") + resolve_api_path
        if not os.path.isdir(script_path):
            script_path = resolve_api_path
    elif sys.platform.startswith("win") or sys.platform.startswith("cygwin"):
        # Windows
        resolve_api_path = "C:\\ProgramData\\Blackmagic Design\\DaVinci Resolve\\Support\\Developer\\Scripting\\Modules\\"
        script_path = resolve_api_path
    elif sys.platform.startswith("linux"):
        # Linux
        resolve_api_path = "/opt/resolve/Developer/Scripting/Modules/"
        script_path = resolve_api_path
    else:
        raise ValueError(f"Unsupported platform: {sys.platform}")

    if os.path.isdir(script_path):
        sys.path.append(script_path)
        return True
    else:
        return False


# Initialize Resolve API
def init_resolve():
    """Initialize the DaVinci Resolve API and return the Resolve object."""
    if add_resolve_module_path():
        import DaVinciResolveScript as dvr_script

        resolve = dvr_script.scriptapp("Resolve")
        if not resolve:
            print(
                "Error: Unable to connect to DaVinci Resolve. Make sure Resolve is running."
            )
            return None
        return resolve
    else:
        print("Error: Could not locate DaVinci Resolve API modules.")
        return None


# Create an MCP server for DaVinci Resolve
def create_server():
    """Create and return the DaVinci Resolve MCP server."""
    # Initialize Resolve
    try:
        resolve = init_resolve()
        if not resolve:
            sys.exit(1)
    except ImportError:
        print(
            "Error: Could not import DaVinci Resolve API. Make sure Resolve is running."
        )
        sys.exit(1)

    # Create MCP server
    mcp = FastMCP("DaVinci Resolve")

    @mcp.tool()
    def get_timeline_clip_names() -> list:
        """Get the names of all clips in the current timeline."""
        try:
            # Navigate the Resolve object hierarchy to reach the timeline
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()

            if not project:
                return {"error": "No project is currently open"}

            timeline = project.GetCurrentTimeline()

            if not timeline:
                return {"error": "No timeline is currently open"}

            # Get all clips in the timeline
            clip_names = []
            video_tracks_count = timeline.GetTrackCount("video")

            for track_index in range(1, video_tracks_count + 1):
                # GetItemListInTrack returns a list of clips
                clips = timeline.GetItemListInTrack("video", track_index)
                if clips:
                    for clip in clips:
                        clip_names.append(
                            {
                                "track": f"V{track_index}",
                                "name": clip.GetName(),
                                "duration": clip.GetDuration(),
                            }
                        )

            # Also get audio clips
            audio_tracks_count = timeline.GetTrackCount("audio")
            for track_index in range(1, audio_tracks_count + 1):
                clips = timeline.GetItemListInTrack("audio", track_index)
                if clips:
                    for clip in clips:
                        clip_names.append(
                            {
                                "track": f"A{track_index}",
                                "name": clip.GetName(),
                                "duration": clip.GetDuration(),
                            }
                        )

            return clip_names
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    @mcp.tool()
    def get_project_info() -> dict:
        """Get information about the current project in DaVinci Resolve."""
        try:
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()

            if not project:
                return {"error": "No project is currently open"}

            # Get the timeline count
            timeline_count = project.GetTimelineCount()

            return {
                "name": project.GetName(),
                "frame_rate": project.GetSetting("timelineFrameRate"),
                "resolution": {
                    "width": project.GetSetting("timelineResolutionWidth"),
                    "height": project.GetSetting("timelineResolutionHeight"),
                },
                "timeline_count": timeline_count,
            }
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    @mcp.tool()
    def get_current_timeline_name() -> str:
        """Get the name of the current timeline."""
        try:
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()

            if not project:
                return "No project is currently open"

            timeline = project.GetCurrentTimeline()

            if not timeline:
                return "No timeline is currently open"

            return timeline.GetName()
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    def get_timeline_info() -> dict:
        """Get detailed information about the current timeline."""
        try:
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()

            if not project:
                return {"error": "No project is currently open"}

            timeline = project.GetCurrentTimeline()

            if not timeline:
                return {"error": "No timeline is currently open"}

            # Get timeline information - only use methods that are confirmed to work
            info = {
                "name": timeline.GetName(),
                "video_track_count": timeline.GetTrackCount("video"),
                "audio_track_count": timeline.GetTrackCount("audio"),
            }

            # Try to get additional timeline information that might be available
            try:
                info["start_frame"] = timeline.GetStartFrame()
                info["end_frame"] = timeline.GetEndFrame()

                # Only calculate frame count if both start and end frames were retrieved
                if "start_frame" in info and "end_frame" in info:
                    info["frame_count"] = info["end_frame"] - info["start_frame"] + 1
            except:
                pass

            # Try to get timecode information
            try:
                info["timecode_start"] = timeline.GetStartTimecode()
                info["timecode_end"] = timeline.GetEndTimecode()
            except:
                pass

            # Try to get additional settings from project
            try:
                info["fps"] = project.GetSetting("timelineFrameRate")
                info["resolution"] = {
                    "width": project.GetSetting("timelineResolutionWidth"),
                    "height": project.GetSetting("timelineResolutionHeight"),
                }
            except:
                pass

            return info
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    @mcp.tool()
    def get_clip_details(
        track_type: str = "video", track_index: int = 1, clip_index: int = 0
    ) -> dict:
        """Get detailed information about a specific clip in the timeline.

        Args:
            track_type: The type of track ('video' or 'audio')
            track_index: The index of the track (1-based)
            clip_index: The index of the clip in the track (0-based)

        Returns:
            A dictionary with clip details or an error message
        """
        try:
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()

            if not project:
                return {"error": "No project is currently open"}

            timeline = project.GetCurrentTimeline()

            if not timeline:
                return {"error": "No timeline is currently open"}

            # Validate track type
            if track_type not in ["video", "audio"]:
                return {"error": "Track type must be 'video' or 'audio'"}

            # Validate track index
            track_count = timeline.GetTrackCount(track_type)
            if track_index < 1 or track_index > track_count:
                return {"error": f"Track index must be between 1 and {track_count}"}

            # Get clips in the track
            clips = timeline.GetItemListInTrack(track_type, track_index)

            if not clips or len(clips) <= clip_index:
                return {
                    "error": f"Clip index {clip_index} not found in {track_type} track {track_index}"
                }

            # Get the specific clip
            clip = clips[clip_index]

            # Collect basic clip properties
            properties = {"name": clip.GetName(), "duration": clip.GetDuration()}

            # Try to get additional timeline item properties
            try:
                properties["start_frame"] = clip.GetStart()
                properties["end_frame"] = clip.GetEnd()
            except:
                pass

            try:
                properties["track"] = f"{track_type[0].upper()}{track_index}"
            except:
                pass

            # Try to access media pool item in multiple ways
            try:
                # First try the standard method
                media_item = clip.GetMediaPoolItem()
                has_media_item = media_item is not None
                properties["media_pool_item"] = has_media_item

                # If we have a valid media pool item, get its properties
                if has_media_item:
                    try:
                        media_props = {"name": media_item.GetName()}

                        # Try to get additional media properties
                        try:
                            media_props["clip_color"] = media_item.GetClipColor()
                        except:
                            pass

                        # Try to get clip properties using the GetClipProperty method
                        for prop in [
                            "Duration",
                            "FPS",
                            "File Path",
                            "Resolution",
                            "Format",
                        ]:
                            try:
                                media_props[prop.lower().replace(" ", "_")] = (
                                    media_item.GetClipProperty(prop)
                                )
                            except:
                                pass

                        properties["media"] = media_props
                    except Exception as e:
                        properties["media_error"] = str(e)
                else:
                    # Alternative approach for media properties
                    try:
                        # Try to access metadata directly from the timeline item
                        if hasattr(clip, "GetMetadata"):
                            metadata = clip.GetMetadata()
                            if metadata:
                                properties["metadata"] = metadata
                    except:
                        pass
            except Exception as e:
                properties["media_pool_error"] = str(e)

            return properties
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    @mcp.tool()
    def get_project_timelines() -> list:
        """Get a list of all timelines in the current project."""
        try:
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()

            if not project:
                return {"error": "No project is currently open"}

            # Get the number of timelines in the project
            timeline_count = project.GetTimelineCount()

            # Get information about each timeline
            timelines = []
            for i in range(1, timeline_count + 1):
                try:
                    timeline = project.GetTimelineByIndex(i)
                    if timeline:
                        timeline_info = {"index": i, "name": timeline.GetName()}

                        # Try to get additional information
                        try:
                            timeline_info["video_track_count"] = timeline.GetTrackCount(
                                "video"
                            )
                            timeline_info["audio_track_count"] = timeline.GetTrackCount(
                                "audio"
                            )
                        except:
                            pass

                        timelines.append(timeline_info)
                except:
                    continue

            return timelines
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    @mcp.tool()
    def get_timeline_markers() -> list:
        """Get all markers in the current timeline."""
        try:
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()

            if not project:
                return {"error": "No project is currently open"}

            timeline = project.GetCurrentTimeline()

            if not timeline:
                return {"error": "No timeline is currently open"}

            # Get the markers
            markers = []
            marker_list = timeline.GetMarkers()

            if marker_list:
                for frame_id, marker_info in marker_list.items():
                    marker = {
                        "frame": frame_id,
                        "name": marker_info.get("name", ""),
                        "color": marker_info.get("color", ""),
                        "duration": marker_info.get("duration", 1),
                        "note": marker_info.get("note", ""),
                    }
                    markers.append(marker)

            return markers
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    @mcp.tool()
    def get_active_track_info() -> dict:
        """Get information about the currently active track in the timeline."""
        try:
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()

            if not project:
                return {"error": "No project is currently open"}

            timeline = project.GetCurrentTimeline()

            if not timeline:
                return {"error": "No timeline is currently open"}

            # Get information about the currently active track
            track_info = {}

            # Try to get video track selection
            try:
                selected_tracks = timeline.GetHighlightedTracks()
                if selected_tracks:
                    track_info["selected_tracks"] = selected_tracks
            except:
                pass

            # Try to get current video track
            try:
                video_track_count = timeline.GetTrackCount("video")
                for i in range(1, video_track_count + 1):
                    if timeline.IsTrackEnabled("video", i):
                        clips = timeline.GetItemListInTrack("video", i)
                        if "video_tracks" not in track_info:
                            track_info["video_tracks"] = []
                        track_info["video_tracks"].append(
                            {
                                "index": i,
                                "enabled": True,
                                "clip_count": len(clips) if clips else 0,
                            }
                        )
                    else:
                        if "video_tracks" not in track_info:
                            track_info["video_tracks"] = []
                        track_info["video_tracks"].append(
                            {"index": i, "enabled": False}
                        )
            except:
                pass

            # Try to get current audio track
            try:
                audio_track_count = timeline.GetTrackCount("audio")
                for i in range(1, audio_track_count + 1):
                    if timeline.IsTrackEnabled("audio", i):
                        clips = timeline.GetItemListInTrack("audio", i)
                        if "audio_tracks" not in track_info:
                            track_info["audio_tracks"] = []
                        track_info["audio_tracks"].append(
                            {
                                "index": i,
                                "enabled": True,
                                "clip_count": len(clips) if clips else 0,
                            }
                        )
                    else:
                        if "audio_tracks" not in track_info:
                            track_info["audio_tracks"] = []
                        track_info["audio_tracks"].append(
                            {"index": i, "enabled": False}
                        )
            except:
                pass

            return track_info
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    @mcp.tool()
    def get_media_pool_items() -> list:
        """Get a list of all items in the media pool."""
        try:
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()

            if not project:
                return {"error": "No project is currently open"}

            media_pool = project.GetMediaPool()
            if not media_pool:
                return {"error": "Could not access the media pool"}

            # Get the root folder
            root_folder = media_pool.GetRootFolder()
            if not root_folder:
                return {"error": "Could not access the root folder"}

            # Get all clips in the root folder
            clips = root_folder.GetClipList()

            # Format the clip information
            media_items = []
            for clip in clips:
                # Get basic clip properties
                item = {"name": clip.GetName(), "duration": clip.GetDuration()}

                # Try to get additional clip properties
                try:
                    for prop in [
                        "FPS",
                        "Resolution",
                        "Format",
                        "File Path",
                        "Clip Color",
                    ]:
                        try:
                            value = clip.GetClipProperty(prop)
                            if value:
                                item[prop.lower().replace(" ", "_")] = value
                        except:
                            pass
                except:
                    pass

                media_items.append(item)

            return media_items
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    @mcp.tool()
    def get_media_pool_structure() -> dict:
        """Get the folder structure of the media pool."""
        try:
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()

            if not project:
                return {"error": "No project is currently open"}

            media_pool = project.GetMediaPool()
            if not media_pool:
                return {"error": "Could not access the media pool"}

            # Get the root folder
            root_folder = media_pool.GetRootFolder()
            if not root_folder:
                return {"error": "Could not access the root folder"}

            # Helper function to process a folder recursively
            def process_folder(folder):
                folder_data = {"name": folder.GetName(), "clips": [], "subfolders": []}

                # Get clips in the folder
                clips = folder.GetClipList()
                if clips:
                    for clip in clips:
                        clip_info = {
                            "name": clip.GetName(),
                            "duration": clip.GetDuration(),
                        }
                        folder_data["clips"].append(clip_info)

                # Get subfolders
                subfolders = folder.GetSubFolderList()
                if subfolders:
                    for subfolder in subfolders:
                        folder_data["subfolders"].append(process_folder(subfolder))

                return folder_data

            # Start with the root folder
            media_structure = process_folder(root_folder)

            return media_structure
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    @mcp.tool()
    def get_playhead_position() -> dict:
        """Get the current playhead position in the timeline."""
        try:
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()

            if not project:
                return {"error": "No project is currently open"}

            timeline = project.GetCurrentTimeline()

            if not timeline:
                return {"error": "No timeline is currently open"}

            # Get the current position
            position = {}

            # Try to get frame number
            try:
                current_frame = timeline.GetCurrentVideoItem().GetStart()
                position["frame"] = current_frame
            except:
                try:
                    # Alternative method
                    current_frame = timeline.GetCurrentFrame()
                    position["frame"] = current_frame
                except:
                    pass

            # Try to get timecode
            try:
                current_timecode = timeline.GetCurrentTimecode()
                position["timecode"] = current_timecode
            except:
                pass

            # Calculate time in seconds if possible
            if "frame" in position and timeline.GetSetting("fps"):
                try:
                    fps = float(timeline.GetSetting("fps"))
                    if fps > 0:
                        seconds = position["frame"] / fps
                        position["seconds"] = seconds
                except:
                    pass

            return position
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    @mcp.tool()
    def control_playback(command: str = "play") -> dict:
        """Control the playback of the timeline.

        Args:
            command: The playback command to execute.
                     Options: play, stop, pause, forward, reverse, next_frame, prev_frame,
                     next_clip, prev_clip, to_in, to_out, toggle_play

        Returns:
            Status of the operation
        """
        try:
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()

            if not project:
                return {"error": "No project is currently open"}

            # Get the current timeline
            timeline = project.GetCurrentTimeline()
            if not timeline:
                return {"error": "No timeline is currently open"}

            # Access the playback controls
            valid_commands = [
                "play",
                "stop",
                "pause",
                "forward",
                "reverse",
                "next_frame",
                "prev_frame",
                "next_clip",
                "prev_clip",
                "to_in",
                "to_out",
                "toggle_play",
            ]

            if command not in valid_commands:
                return {
                    "error": f"Invalid command. Valid options are: {', '.join(valid_commands)}"
                }

            # Apply the requested command
            result = {"command": command, "status": "executed"}

            try:
                if command == "play":
                    timeline.Play()
                elif command == "stop":
                    timeline.Stop()
                elif command == "pause":
                    timeline.Pause()
                elif command == "toggle_play":
                    # This is a custom command that toggles between play and pause
                    if timeline.IsPlaying():
                        timeline.Pause()
                        result["new_state"] = "paused"
                    else:
                        timeline.Play()
                        result["new_state"] = "playing"
                elif command == "forward":
                    timeline.SetPlaybackSpeed(2.0)  # Play forward at 2x speed
                elif command == "reverse":
                    timeline.SetPlaybackSpeed(-1.0)  # Play in reverse
                elif command == "next_frame":
                    timeline.GoToNextFrame()
                elif command == "prev_frame":
                    timeline.GoToPreviousFrame()
                elif command == "next_clip":
                    timeline.GoToNextClip()
                elif command == "prev_clip":
                    timeline.GoToPreviousClip()
                elif command == "to_in":
                    timeline.GoToIn()
                elif command == "to_out":
                    timeline.GoToOut()
            except Exception as e:
                return {"error": f"Failed to execute command '{command}': {str(e)}"}

            # Try to get current position after command
            try:
                result["position"] = {
                    "timecode": timeline.GetCurrentTimecode(),
                    "frame": timeline.GetCurrentFrame(),
                }
            except:
                pass

            return result
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    @mcp.tool()
    def get_selected_clips() -> list:
        """Get information about the currently selected clips in the timeline."""
        try:
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()

            if not project:
                return {"error": "No project is currently open"}

            timeline = project.GetCurrentTimeline()

            if not timeline:
                return {"error": "No timeline is currently open"}

            # Get the selected clips
            selected_clips = []

            try:
                # Get all selected items on the timeline
                clips = timeline.GetCurrentSelectedItems()

                if not clips:
                    return []

                for clip in clips:
                    clip_info = {"name": clip.GetName(), "duration": clip.GetDuration()}

                    # Try to get more properties
                    try:
                        clip_info["start_frame"] = clip.GetStart()
                        clip_info["end_frame"] = clip.GetEnd()
                    except:
                        pass

                    try:
                        clip_info["track_index"] = clip.GetTrackIndex()
                    except:
                        pass

                    # Check what type of clip this is
                    try:
                        if clip.GetFusionCompCount:  # Check if this is a Fusion clip
                            clip_info["type"] = "fusion"
                        elif clip.GetStillFrameFlag:  # Check if this is a still frame
                            clip_info["type"] = "still"
                        else:
                            clip_info["type"] = "standard"
                    except:
                        clip_info["type"] = "unknown"

                    selected_clips.append(clip_info)

                return selected_clips
            except Exception as e:
                return {"error": f"Failed to get selected clips: {str(e)}"}
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    @mcp.tool()
    def add_clip_to_timeline(
        media_pool_item_name: str = "",
        track_index: int = 1,
        track_type: str = "video",
        frame_position: int = -1,
    ) -> dict:
        """Add a clip from the media pool to the timeline.

        Args:
            media_pool_item_name: The name of the media pool item to add
            track_index: The index of the track to add the clip to (1-based)
            track_type: The type of track ('video' or 'audio')
            frame_position: The frame position to add the clip (or -1 for current position)

        Returns:
            Status of the operation
        """
        try:
            project_manager = resolve.GetProjectManager()
            project = project_manager.GetCurrentProject()

            if not project:
                return {"error": "No project is currently open"}

            media_pool = project.GetMediaPool()
            if not media_pool:
                return {"error": "Could not access the media pool"}

            timeline = project.GetCurrentTimeline()
            if not timeline:
                return {"error": "No timeline is currently open"}

            # Validate track type
            if track_type not in ["video", "audio"]:
                return {"error": "Track type must be 'video' or 'audio'"}

            # Validate track index
            track_count = timeline.GetTrackCount(track_type)
            if track_index < 1 or track_index > track_count:
                return {"error": f"Track index must be between 1 and {track_count}"}

            # Find the media pool item by name
            root_folder = media_pool.GetRootFolder()
            if not root_folder:
                return {"error": "Could not access the root folder"}

            # Get all clips in the root folder
            clips = root_folder.GetClipList()
            target_clip = None

            for clip in clips:
                if clip.GetName() == media_pool_item_name:
                    target_clip = clip
                    break

            if not target_clip:
                return {
                    "error": f"Could not find media pool item with name '{media_pool_item_name}'"
                }

            # Set the target track
            media_pool.SetCurrentFolder(root_folder)

            # Insert options
            insert_options = {"targetTrack": track_index, "mediaType": track_type}

            if frame_position >= 0:
                insert_options["startFrame"] = frame_position

            # Add the clip to the timeline
            result = media_pool.AppendToTimeline([target_clip])

            if not result:
                # Try alternative method
                result = timeline.InsertClip(target_clip, insert_options)

            if result:
                return {
                    "status": "success",
                    "message": f"Added clip '{media_pool_item_name}' to {track_type} track {track_index}",
                }
            else:
                return {"error": "Failed to add clip to timeline"}
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    @mcp.tool()
    def get_project_list() -> list:
        """Get a list of all projects in the current database."""
        try:
            project_manager = resolve.GetProjectManager()
            if not project_manager:
                return {"error": "Could not access the project manager"}

            # Get the current project to restore it later
            current_project = project_manager.GetCurrentProject()
            current_project_name = None
            if current_project:
                current_project_name = current_project.GetName()

            # Get all projects
            project_list = []
            projects = None

            try:
                # Get the list of projects
                projects = project_manager.GetProjectListInCurrentFolder()

                if projects:
                    for project_name in projects:
                        # Try to load each project to get its details
                        project = project_manager.LoadProject(project_name)

                        if project:
                            # Get project details
                            project_info = {
                                "name": project_name,
                                "fps": project.GetSetting("timelineFrameRate"),
                                "resolution": {
                                    "width": project.GetSetting(
                                        "timelineResolutionWidth"
                                    ),
                                    "height": project.GetSetting(
                                        "timelineResolutionHeight"
                                    ),
                                },
                            }

                            # Get timeline count
                            try:
                                timeline_count = project.GetTimelineCount()
                                project_info["timeline_count"] = timeline_count
                            except:
                                pass

                            project_list.append(project_info)
            except Exception as e:
                error_msg = f"Failed to get project list: {str(e)}"

            # Always restore the original project
            if current_project_name:
                try:
                    project_manager.LoadProject(current_project_name)
                except:
                    pass

            if "error_msg" in locals():
                return {"error": error_msg}

            return project_list
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    @mcp.tool()
    def switch_to_project(project_name: str = "") -> dict:
        """Switch to a different project.

        Args:
            project_name: The name of the project to switch to

        Returns:
            Status of the operation
        """
        try:
            project_manager = resolve.GetProjectManager()
            if not project_manager:
                return {"error": "Could not access the project manager"}

            # Get the current project name
            current_project = project_manager.GetCurrentProject()
            current_project_name = (
                current_project.GetName() if current_project else "None"
            )

            if not project_name:
                return {"error": "No project name provided"}

            # Check if we're already on this project
            if current_project_name == project_name:
                return {
                    "status": "success",
                    "message": f"Already on project '{project_name}'",
                }

            # Get the list of projects
            projects = project_manager.GetProjectListInCurrentFolder()

            if not projects:
                return {"error": "No projects found in the current folder"}

            if project_name not in projects:
                return {
                    "error": f"Project '{project_name}' not found in the current folder"
                }

            # Switch to the project
            project = project_manager.LoadProject(project_name)

            if not project:
                return {"error": f"Failed to load project '{project_name}'"}

            # Get some details about the project
            project_info = {
                "name": project_name,
                "fps": project.GetSetting("timelineFrameRate"),
                "resolution": {
                    "width": project.GetSetting("timelineResolutionWidth"),
                    "height": project.GetSetting("timelineResolutionHeight"),
                },
            }

            # Get timeline count and names
            try:
                timeline_count = project.GetTimelineCount()
                project_info["timeline_count"] = timeline_count

                if timeline_count > 0:
                    timeline_names = []
                    for i in range(1, timeline_count + 1):
                        try:
                            timeline = project.GetTimelineByIndex(i)
                            if timeline:
                                timeline_names.append(timeline.GetName())
                        except:
                            pass

                    project_info["timelines"] = timeline_names
            except:
                pass

            return {
                "status": "success",
                "message": f"Switched to project '{project_name}'",
                "project_info": project_info,
            }
        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    return mcp


def run_server():
    """Run the DaVinci Resolve MCP server."""
    mcp = create_server()
    print("Starting DaVinci Resolve MCP server on http://localhost:8000")
    mcp.run()


if __name__ == "__main__":
    run_server()
