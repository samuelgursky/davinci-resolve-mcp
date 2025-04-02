#!/usr/bin/env python3
"""
DaVinci Resolve Delivery Page Operations
"""

import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("davinci-resolve-mcp.delivery")


def get_render_presets(resolve) -> List[Dict[str, Any]]:
    """Get all available render presets in the current project.

    Args:
        resolve: DaVinci Resolve instance

    Returns:
        List of dictionaries containing preset information
    """
    if not resolve:
        logger.error("No connection to DaVinci Resolve")
        return {"error": "No connection to DaVinci Resolve"}

    project_manager = resolve.GetProjectManager()
    if not project_manager:
        logger.error("Failed to get Project Manager")
        return {"error": "Failed to get Project Manager"}

    current_project = project_manager.GetCurrentProject()
    if not current_project:
        logger.error("No project is currently open")
        return {"error": "No project is currently open"}

    # Switch to the Deliver page
    page = resolve.GetCurrentPage()
    if page != "deliver":
        logger.info(f"Switching from {page} page to deliver page")
        resolve.OpenPage("deliver")

    render_settings = current_project.GetRenderSettings()
    if not render_settings:
        logger.error("Failed to get render settings")
        return {"error": "Failed to get render settings"}

    presets = []

    # Get project presets
    try:
        project_presets = render_settings.GetRenderPresetList()
        for preset in project_presets:
            preset_info = {"name": preset, "type": "project", "details": {}}

            # Try to get detailed information about the preset
            try:
                if render_settings.SetRenderSettings({"SelectPreset": preset}):
                    format_info = render_settings.GetCurrentRenderFormatAndCodec()
                    if format_info:
                        preset_info["details"]["format"] = format_info["format"]
                        preset_info["details"]["codec"] = format_info["codec"]

                    resolution = render_settings.GetCurrentRenderResolution()
                    if resolution:
                        preset_info["details"]["resolution"] = resolution

                    frame_rate = render_settings.GetCurrentRenderFrameRate()
                    if frame_rate:
                        preset_info["details"]["frame_rate"] = frame_rate
            except Exception as e:
                logger.warning(
                    f"Could not get detailed information for preset {preset}: {str(e)}"
                )

            presets.append(preset_info)
    except Exception as e:
        logger.warning(f"Could not get project presets: {str(e)}")

    # Get system presets
    try:
        system_presets = render_settings.GetSystemPresetList()
        for preset in system_presets:
            preset_info = {"name": preset, "type": "system", "details": {}}

            # Similar detailed information retrieval could be added here
            presets.append(preset_info)
    except Exception as e:
        logger.warning(f"Could not get system presets: {str(e)}")

    return presets


def add_to_render_queue(
    resolve,
    preset_name: str,
    timeline_name: Optional[str] = None,
    use_in_out_range: bool = False,
    render_settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Add the current timeline or a specific timeline to the render queue.

    Args:
        resolve: DaVinci Resolve instance
        preset_name: Name of the render preset to use
        timeline_name: Name of the timeline to render (uses current if None)
        use_in_out_range: Whether to render only the in/out range instead of entire timeline
        render_settings: Additional render settings to apply (optional)

    Returns:
        Dictionary with status information about the added job
    """
    if not resolve:
        logger.error("No connection to DaVinci Resolve")
        return {"error": "No connection to DaVinci Resolve"}

    logger.info(f"Adding timeline to render queue with preset: {preset_name}")
    if timeline_name:
        logger.info(f"Using specified timeline: {timeline_name}")
    else:
        logger.info("Using current timeline")

    project_manager = resolve.GetProjectManager()
    if not project_manager:
        logger.error("Failed to get Project Manager")
        return {"error": "Failed to get Project Manager"}

    current_project = project_manager.GetCurrentProject()
    if not current_project:
        logger.error("No project is currently open")
        return {"error": "No project is currently open"}

    # Switch to the Deliver page
    page = resolve.GetCurrentPage()
    if page != "deliver":
        logger.info(f"Switching from {page} page to deliver page")
        resolve.OpenPage("deliver")

    # Get the timeline to render
    if timeline_name:
        timeline = current_project.GetTimelineByName(timeline_name)
        if not timeline:
            logger.error(f"Timeline '{timeline_name}' not found")
            return {"error": f"Timeline '{timeline_name}' not found"}

        # Set it as the current timeline
        current_project.SetCurrentTimeline(timeline)
    else:
        timeline = current_project.GetCurrentTimeline()
        if not timeline:
            logger.error("No timeline is currently open")
            return {"error": "No timeline is currently open"}

    # Get timeline name for reporting
    actual_timeline_name = timeline.GetName()
    logger.info(f"Using timeline: {actual_timeline_name}")

    # Use our helper function to ensure render settings are initialized
    success, render_settings_interface, message = ensure_render_settings(
        resolve, current_project
    )
    if not success or not render_settings_interface:
        logger.error(f"Failed to initialize render settings: {message}")
        return {"error": message}

    # Use our helper function to validate the preset
    preset_valid, available_presets, preset_message = validate_render_preset(
        render_settings_interface, preset_name
    )
    if not preset_valid:
        logger.error(f"Invalid preset: {preset_message}")
        return {"error": preset_message}

    # Apply the render preset
    settings_to_apply = {"SelectPreset": preset_name}
    logger.info(f"Applying render preset: {preset_name}")

    # Add any additional render settings if provided
    if render_settings:
        logger.info(f"Adding additional render settings: {render_settings}")
        settings_to_apply.update(render_settings)

    try:
        if not render_settings_interface.SetRenderSettings(settings_to_apply):
            logger.error(f"Failed to apply render preset '{preset_name}'")
            return {"error": f"Failed to apply render preset '{preset_name}'"}
        logger.info("Successfully applied render preset")
    except Exception as e:
        logger.error(f"Error applying render preset: {str(e)}")
        return {"error": f"Error applying render preset: {str(e)}"}

    # Add to render queue
    result = False
    logger.info("Adding timeline to render queue")
    try:
        if use_in_out_range:
            logger.info("Using in/out range for render")
            result = current_project.AddRenderJobToRenderQueue()
        else:
            logger.info(
                f"Adding entire timeline '{actual_timeline_name}' to render queue"
            )
            result = current_project.AddTimelineToRenderQueue(actual_timeline_name)
    except Exception as e:
        logger.error(f"Exception while adding to render queue: {str(e)}")

        # Try alternative approach - sometimes a different order helps
        try:
            logger.info("Trying alternative approach for adding to render queue")
            # Sometimes re-applying the preset helps
            render_settings_interface.SetRenderSettings(settings_to_apply)

            # Try adding again after a small delay
            import time

            time.sleep(0.5)

            if use_in_out_range:
                result = current_project.AddRenderJobToRenderQueue()
            else:
                result = current_project.AddTimelineToRenderQueue(actual_timeline_name)
        except Exception as nested_e:
            logger.error(f"Alternative approach also failed: {str(nested_e)}")
            return {
                "error": f"Failed to add to render queue: {str(e)}. Alternative approach also failed: {str(nested_e)}"
            }

    if result:
        logger.info(
            f"Successfully added '{actual_timeline_name}' to render queue with preset '{preset_name}'"
        )
        return {
            "success": True,
            "message": f"Added '{actual_timeline_name}' to render queue with preset '{preset_name}'",
            "timeline": actual_timeline_name,
            "preset": preset_name,
            "in_out_range_only": use_in_out_range,
        }
    else:
        logger.error("Failed to add to render queue")
        return {
            "error": "Failed to add to render queue",
            "timeline": actual_timeline_name,
            "preset": preset_name,
        }


def start_render(resolve) -> Dict[str, Any]:
    """Start rendering jobs in the render queue.

    Args:
        resolve: DaVinci Resolve instance

    Returns:
        Dictionary with status information about the render process
    """
    if not resolve:
        logger.error("No connection to DaVinci Resolve")
        return {"error": "No connection to DaVinci Resolve"}

    logger.info("Starting render process")

    project_manager = resolve.GetProjectManager()
    if not project_manager:
        logger.error("Failed to get Project Manager")
        return {"error": "Failed to get Project Manager"}

    current_project = project_manager.GetCurrentProject()
    if not current_project:
        logger.error("No project is currently open")
        return {"error": "No project is currently open"}

    # Switch to the Deliver page
    page = resolve.GetCurrentPage()
    if page != "deliver":
        logger.info(f"Switching from {page} page to deliver page")
        resolve.OpenPage("deliver")

    # Start rendering
    try:
        # Check if there are jobs in the queue
        logger.info("Checking for jobs in render queue")
        try:
            queue_items = current_project.GetRenderJobList()
            if queue_items:
                logger.info(f"Found {len(queue_items)} jobs in render queue")
            else:
                logger.warning("GetRenderJobList() returned None or empty list")
                queue_items = []
        except Exception as e:
            logger.error(f"Error getting render job list: {str(e)}")
            queue_items = []

        if not queue_items or len(queue_items) == 0:
            logger.warning("No jobs in render queue")
            return {"warning": "No jobs in render queue", "jobs_count": 0}

        # Start the render process
        logger.info("Starting render process")
        try:
            result = current_project.StartRendering()  # Try the newer API first
            if result is None:
                # If newer API returns None, try the older API
                logger.info(
                    "Newer StartRendering() API returned None, trying StartRenderingJob()"
                )
                result = current_project.StartRenderingJob()
        except AttributeError:
            # If newer API doesn't exist, fall back to older API
            logger.info(
                "Newer StartRendering() API not available, using StartRenderingJob()"
            )
            result = current_project.StartRenderingJob()
        except Exception as e:
            logger.error(f"Error starting render: {str(e)}")
            result = False

        if result:
            logger.info("Render started successfully")
            return {
                "success": True,
                "message": "Render started successfully",
                "jobs_count": len(queue_items),
            }
        else:
            logger.error("Failed to start rendering")
            return {
                "error": "Failed to start rendering",
                "jobs_count": len(queue_items),
            }

    except Exception as e:
        logger.error(f"Exception while starting render: {str(e)}")
        return {"error": f"Failed to start rendering: {str(e)}"}


def get_render_queue_status(resolve) -> Dict[str, Any]:
    """Get the status of jobs in the render queue.

    Args:
        resolve: DaVinci Resolve instance

    Returns:
        Dictionary with information about the render queue status
    """
    if not resolve:
        logger.error("No connection to DaVinci Resolve")
        return {"error": "No connection to DaVinci Resolve"}

    project_manager = resolve.GetProjectManager()
    if not project_manager:
        logger.error("Failed to get Project Manager")
        return {"error": "Failed to get Project Manager"}

    current_project = project_manager.GetCurrentProject()
    if not current_project:
        logger.error("No project is currently open")
        return {"error": "No project is currently open"}

    # Switch to the Deliver page
    page = resolve.GetCurrentPage()
    if page != "deliver":
        logger.info(f"Switching from {page} page to deliver page")
        resolve.OpenPage("deliver")

    try:
        # Get render queue items
        queue_items = current_project.GetRenderJobList()

        if not queue_items:
            return {"status": "empty", "message": "Render queue is empty", "jobs": []}

        # Get details for each job
        jobs = []
        is_rendering = False

        for job_id in queue_items:
            job_info = {"id": job_id, "name": "Unknown", "status": "Unknown"}

            try:
                # Try to get job name (usually timeline name)
                job_info["name"] = current_project.GetRenderJobName(job_id)

                # Try to get job status
                status = current_project.GetRenderJobStatus(job_id)
                job_info["status"] = status

                # Check if any job is currently rendering
                if status == "Rendering":
                    is_rendering = True

                # Try to get additional job properties if available
                try:
                    # Frame progress might be available for rendering jobs
                    progress = current_project.GetRenderJobFrameProgress(job_id)
                    if progress:
                        job_info["progress"] = progress

                    # Get estimated remaining time if available
                    time_remaining = current_project.GetRenderJobEstimatedTimeRemaining(
                        job_id
                    )
                    if time_remaining:
                        job_info["time_remaining"] = time_remaining
                except:
                    # Not all properties are available for all job states
                    pass

            except Exception as e:
                logger.warning(f"Could not get details for job {job_id}: {str(e)}")

            jobs.append(job_info)

        # Determine overall render queue status
        if is_rendering:
            queue_status = "rendering"
        elif any(job["status"] == "Complete" for job in jobs):
            if all(job["status"] == "Complete" for job in jobs):
                queue_status = "complete"
            else:
                queue_status = "partial_complete"
        else:
            queue_status = "ready"

        return {
            "status": queue_status,
            "jobs_count": len(jobs),
            "jobs": jobs,
            "is_rendering": is_rendering,
        }

    except Exception as e:
        logger.error(f"Exception while getting render queue status: {str(e)}")
        return {"error": f"Failed to get render queue status: {str(e)}"}


def clear_render_queue(resolve) -> Dict[str, Any]:
    """Clear all jobs from the render queue.

    Args:
        resolve: DaVinci Resolve instance

    Returns:
        Dictionary with status information about the operation
    """
    if not resolve:
        logger.error("No connection to DaVinci Resolve")
        return {"error": "No connection to DaVinci Resolve"}

    project_manager = resolve.GetProjectManager()
    if not project_manager:
        logger.error("Failed to get Project Manager")
        return {"error": "Failed to get Project Manager"}

    current_project = project_manager.GetCurrentProject()
    if not current_project:
        logger.error("No project is currently open")
        return {"error": "No project is currently open"}

    # Switch to the Deliver page
    page = resolve.GetCurrentPage()
    if page != "deliver":
        logger.info(f"Switching from {page} page to deliver page")
        resolve.OpenPage("deliver")

    try:
        # Get current jobs count for reporting
        queue_items = current_project.GetRenderJobList()
        initial_count = len(queue_items) if queue_items else 0

        if initial_count == 0:
            return {
                "success": True,
                "message": "Render queue is already empty",
                "jobs_removed": 0,
            }

        # Check if any jobs are currently rendering
        is_rendering = False
        for job_id in queue_items:
            try:
                status = current_project.GetRenderJobStatus(job_id)
                if status == "Rendering":
                    is_rendering = True
                    break
            except:
                pass

        # If jobs are rendering, we need to stop rendering first
        if is_rendering:
            logger.info("Stopping active rendering before clearing queue")
            try:
                current_project.StopRendering()
                # Small delay to allow DaVinci Resolve to update job statuses
                import time

                time.sleep(0.5)
            except Exception as e:
                logger.warning(f"Issue stopping rendering: {str(e)}")

        # Clear the render queue
        result = current_project.DeleteAllRenderJobs()

        if result:
            return {
                "success": True,
                "message": "Render queue cleared successfully",
                "jobs_removed": initial_count,
                "was_rendering": is_rendering,
            }
        else:
            return {
                "error": "Failed to clear render queue",
                "jobs_count": initial_count,
            }

    except Exception as e:
        logger.error(f"Exception while clearing render queue: {str(e)}")
        return {"error": f"Failed to clear render queue: {str(e)}"}


def ensure_render_settings(resolve, current_project) -> Tuple[bool, Optional[Any], str]:
    """Ensures render settings interface is properly initialized.

    Args:
        resolve: The DaVinci Resolve instance
        current_project: The current project

    Returns:
        Tuple containing (success, render_settings_object, message)
    """
    logger.info("Attempting to get render settings interface")
    try:
        render_settings_interface = current_project.GetRenderSettings()
        if render_settings_interface:
            logger.info("Successfully got render settings interface")
            return (
                True,
                render_settings_interface,
                "Render settings interface successfully obtained",
            )
        else:
            logger.warning("GetRenderSettings() returned None")
    except Exception as e:
        logger.error(f"Error getting render settings interface: {str(e)}")
        render_settings_interface = None

    # Alternative approach if render settings is None
    logger.warning(
        "Failed to get render settings interface, trying alternative approaches"
    )

    # Try refreshing the deliver page
    try:
        logger.info("Trying to refresh the deliver page")
        current_page = resolve.GetCurrentPage()
        if current_page != "deliver":
            resolve.OpenPage("deliver")
        else:
            # If already on deliver, try switching to another page and back
            resolve.OpenPage("edit")
            resolve.OpenPage("deliver")

        # Try getting render settings again
        render_settings_interface = current_project.GetRenderSettings()
        if render_settings_interface:
            logger.info("Successfully got render settings interface after page refresh")
            return (
                True,
                render_settings_interface,
                "Render settings interface obtained after page refresh",
            )
    except Exception as e:
        logger.error(f"Error in page refresh approach: {str(e)}")

    # Try one more approach - sometimes a delay helps
    try:
        logger.info("Trying with a small delay")
        import time

        time.sleep(1.0)  # Short delay

        render_settings_interface = current_project.GetRenderSettings()
        if render_settings_interface:
            logger.info("Successfully got render settings interface after delay")
            return (
                True,
                render_settings_interface,
                "Render settings interface obtained after delay",
            )
    except Exception as e:
        logger.error(f"Error in delay approach: {str(e)}")

    # If still no render settings, we've failed
    logger.error("Could not get render settings interface after multiple attempts")
    return (
        False,
        None,
        "Failed to access render settings. Deliver page functionality may not be fully initialized.",
    )


def validate_render_preset(
    render_settings_interface, preset_name: str
) -> Tuple[bool, List[str], str]:
    """Validates that a render preset exists and returns available presets.

    Args:
        render_settings_interface: The render settings interface
        preset_name: Name of the preset to validate

    Returns:
        Tuple containing (is_valid, available_presets, message)
    """
    logger.info("Checking if preset exists")
    try:
        project_presets = render_settings_interface.GetRenderPresetList() or []
        system_presets = render_settings_interface.GetSystemPresetList() or []

        all_presets = project_presets + system_presets
        logger.info(
            f"Found {len(project_presets)} project presets and {len(system_presets)} system presets"
        )

        if preset_name in project_presets:
            logger.info(f"Found '{preset_name}' in project presets")
            return True, all_presets, f"Valid project preset: {preset_name}"
        elif preset_name in system_presets:
            logger.info(f"Found '{preset_name}' in system presets")
            return True, all_presets, f"Valid system preset: {preset_name}"
        else:
            logger.error(f"Render preset '{preset_name}' not found")
            return (
                False,
                all_presets,
                f"Preset '{preset_name}' not found. Available presets: {', '.join(all_presets)}",
            )
    except Exception as e:
        logger.error(f"Error while checking presets: {str(e)}")
        return False, [], f"Error checking render presets: {str(e)}"
