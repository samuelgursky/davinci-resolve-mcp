"""
Fixed DaVinci Resolve Timeline Functions

This module provides improved versions of the timeline deletion and duplication functions
with better error handling, validation, and multiple approaches to avoid 'NoneType' errors.
"""

import sys
import os
import time
from typing import Dict, Any, Optional, List, Union

# Try to import the DaVinci Resolve scripting module
try:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    resolve_api_path = os.environ.get(
        "RESOLVE_SCRIPT_API",
        "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting",
    )
    resolve_module_path = os.path.join(resolve_api_path, "Modules")
    sys.path.append(resolve_module_path)
    import DaVinciResolveScript as dvr
except ImportError:
    print("Error: Could not import DaVinci Resolve scripting modules")


def get_resolve_instance():
    """Get the current instance of DaVinci Resolve"""
    try:
        resolve = dvr.scriptapp("Resolve")
        return resolve
    except NameError:
        print("Error: DaVinci Resolve not found")
        return None


def get_project_manager():
    """Get the project manager object"""
    resolve = get_resolve_instance()
    if resolve:
        return resolve.GetProjectManager()
    return None


def get_current_project():
    """Get the current project object"""
    project_manager = get_project_manager()
    if project_manager:
        return project_manager.GetCurrentProject()
    return None


def get_current_timeline():
    """Get the current timeline object"""
    project = get_current_project()
    if project:
        return project.GetCurrentTimeline()
    return None


def get_media_pool():
    """Get the media pool object"""
    project = get_current_project()
    if project:
        return project.GetMediaPool()
    return None


def list_all_timelines(project=None):
    """List all timelines in the project and return them as a list of dicts"""
    if project is None:
        project = get_current_project()

    if not project:
        return []

    timeline_count = project.GetTimelineCount()
    timelines = []

    for i in range(1, timeline_count + 1):
        try:
            timeline = project.GetTimelineByIndex(i)
            if timeline:
                timelines.append(
                    {"index": i, "name": timeline.GetName(), "object": timeline}
                )
        except:
            continue

    return timelines


def find_timeline_by_name(timeline_name, project=None):
    """Find a timeline by name and return its object"""
    if project is None:
        project = get_current_project()

    if not project or not timeline_name:
        return None

    timelines = list_all_timelines(project)

    for timeline in timelines:
        if timeline["name"] == timeline_name:
            return timeline["object"]

    return None


def retry_function(func, max_attempts=3, delay=0.5, *args, **kwargs):
    """Retry a function multiple times with a delay between attempts"""
    for attempt in range(max_attempts):
        try:
            result = func(*args, **kwargs)
            if result:
                return result
        except Exception as e:
            if attempt == max_attempts - 1:
                raise e

        # Wait before retrying
        time.sleep(delay)

    return None


def fixed_delete_timeline(timeline_name: str) -> Dict[str, Any]:
    """
    Improved function to delete a timeline from the current project.

    Args:
        timeline_name: The name of the timeline to delete

    Returns:
        A dictionary with the status of the operation
    """
    try:
        # Get required objects
        resolve = get_resolve_instance()
        if not resolve:
            return {"error": "DaVinci Resolve not found"}

        project_manager = resolve.GetProjectManager()
        if not project_manager:
            return {"error": "Could not get Project Manager"}

        current_project = project_manager.GetCurrentProject()
        if not current_project:
            return {"error": "No project is currently open"}

        # Find the timeline by name
        timeline_count = current_project.GetTimelineCount()
        if timeline_count == 0:
            return {"error": "No timelines in the current project"}

        # Find the timeline among all timelines
        timelines = list_all_timelines(current_project)
        target_timeline = None
        for t in timelines:
            if t["name"] == timeline_name:
                target_timeline = t["object"]
                break

        if not target_timeline:
            return {"error": f"Timeline '{timeline_name}' not found"}

        # Check if it's the current timeline
        current_timeline = current_project.GetCurrentTimeline()
        is_current = current_timeline and current_timeline.GetName() == timeline_name

        # If we're deleting the current timeline and there are other timelines,
        # switch to another timeline first
        if is_current and timeline_count > 1:
            # Find another timeline to switch to
            other_timeline = None
            for t in timelines:
                if t["name"] != timeline_name:
                    other_timeline = t["object"]
                    break

            if other_timeline:
                # Try to set as current timeline
                success = current_project.SetCurrentTimeline(other_timeline)

                # If we couldn't switch, wait a moment and try again
                if not success:
                    time.sleep(0.5)
                    success = current_project.SetCurrentTimeline(other_timeline)

        # Approach 1: Try using the project's DeleteTimeline method
        delete_success = False
        try:
            delete_success = current_project.DeleteTimeline(target_timeline)
        except Exception:
            delete_success = False

        # If successful, verify the timeline is gone
        if delete_success:
            # Verify the timeline is gone
            remaining_timelines = list_all_timelines(current_project)
            still_exists = any(t["name"] == timeline_name for t in remaining_timelines)

            if not still_exists:
                return {
                    "status": "success",
                    "message": f"Timeline '{timeline_name}' deleted successfully",
                }

        # Approach 2: Try using the media pool's DeleteTimelines method
        try:
            media_pool = current_project.GetMediaPool()
            if media_pool:
                # Get the timeline object again (it might have changed)
                target_timeline = find_timeline_by_name(timeline_name, current_project)

                if target_timeline:
                    delete_success = media_pool.DeleteTimelines([target_timeline])

                    # Verify the timeline is gone
                    if delete_success:
                        remaining_timelines = list_all_timelines(current_project)
                        still_exists = any(
                            t["name"] == timeline_name for t in remaining_timelines
                        )

                        if not still_exists:
                            return {
                                "status": "success",
                                "message": f"Timeline '{timeline_name}' deleted successfully via media pool",
                            }
        except Exception:
            pass

        # Approach 3: Try using alternative methods based on the Resolve version
        try:
            # Check if the timeline still exists
            target_timeline = find_timeline_by_name(timeline_name, current_project)

            if not target_timeline:
                # The timeline might have been deleted despite the error
                return {
                    "status": "success",
                    "message": f"Timeline '{timeline_name}' was deleted but the API returned an error",
                }

            # Try using the timeline object's own method if available
            if hasattr(target_timeline, "Delete") and callable(
                getattr(target_timeline, "Delete")
            ):
                delete_success = target_timeline.Delete()

                if delete_success:
                    return {
                        "status": "success",
                        "message": f"Timeline '{timeline_name}' deleted using timeline.Delete()",
                    }
        except Exception:
            pass

        return {
            "error": f"Failed to delete timeline '{timeline_name}' using multiple approaches"
        }

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}


def fixed_duplicate_timeline(timeline_name: str, new_name: str) -> Dict[str, Any]:
    """
    Improved function to duplicate an existing timeline.

    Args:
        timeline_name: The name of the timeline to duplicate
        new_name: The name for the new timeline

    Returns:
        A dictionary with the status of the operation
    """
    try:
        # Get required objects
        resolve = get_resolve_instance()
        if not resolve:
            return {"error": "DaVinci Resolve not found"}

        project_manager = resolve.GetProjectManager()
        if not project_manager:
            return {"error": "Could not get Project Manager"}

        current_project = project_manager.GetCurrentProject()
        if not current_project:
            return {"error": "No project is currently open"}

        # Find the source timeline
        source_timeline = find_timeline_by_name(timeline_name, current_project)

        if not source_timeline:
            return {"error": f"Timeline '{timeline_name}' not found"}

        # Ensure new_name is a string
        new_name = str(new_name)

        # Check if a timeline with new_name already exists
        existing_timeline = find_timeline_by_name(new_name, current_project)
        if existing_timeline:
            return {"error": f"A timeline named '{new_name}' already exists"}

        # Approach 1: Try using the project's DuplicateTimeline method with retries
        new_timeline = None
        for attempt in range(3):
            try:
                new_timeline = current_project.DuplicateTimeline(
                    source_timeline, new_name
                )
                if new_timeline:
                    break
            except Exception:
                pass

            # Wait before retrying
            time.sleep(0.5)

        if new_timeline:
            # Verify the new timeline exists
            timeline_info = {"name": new_timeline.GetName()}

            # Try to get additional info
            try:
                timeline_info["start_frame"] = new_timeline.GetStartFrame()
                timeline_info["end_frame"] = new_timeline.GetEndFrame()
                timeline_info["video_tracks"] = new_timeline.GetTrackCount("video")
                timeline_info["audio_tracks"] = new_timeline.GetTrackCount("audio")
            except Exception:
                pass

            return {
                "status": "success",
                "message": f"Timeline '{timeline_name}' duplicated as '{new_name}'",
                "timeline_info": timeline_info,
            }

        # Approach 2: Try using the media pool's DuplicateTimeline method
        try:
            media_pool = current_project.GetMediaPool()
            if media_pool and hasattr(media_pool, "DuplicateTimeline"):
                new_timeline = media_pool.DuplicateTimeline(source_timeline, new_name)

                if new_timeline:
                    return {
                        "status": "success",
                        "message": f"Timeline '{timeline_name}' duplicated as '{new_name}' via media pool",
                        "timeline_info": {"name": new_timeline.GetName()},
                    }
        except Exception:
            pass

        # Approach 3: Create a new empty timeline as a fallback
        try:
            media_pool = current_project.GetMediaPool()
            if media_pool:
                new_timeline = media_pool.CreateEmptyTimeline(new_name)

                if new_timeline:
                    # Try to copy clips if possible (this will be a stub for now)
                    # A full implementation would need to copy all clips from the source timeline

                    return {
                        "status": "partial_success",
                        "message": f"Created new timeline '{new_name}', but content from '{timeline_name}' was not copied",
                        "timeline_info": {"name": new_timeline.GetName()},
                    }
        except Exception:
            pass

        return {
            "error": f"Failed to duplicate timeline '{timeline_name}' using multiple approaches"
        }

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}
