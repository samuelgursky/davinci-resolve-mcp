"""
DaVinci Resolve Rendering Operations MCP Functions

This module provides functions to manage rendering in DaVinci Resolve.
"""

import sys
import os
import json
from typing import Dict, Any, Optional, Union, List

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


def mcp_get_render_presets() -> Dict[str, Any]:
    """
    Get a list of all available render presets.

    Returns:
        A dictionary with render presets
    """
    try:
        resolve = get_resolve_instance()
        if not resolve:
            return {"error": "DaVinci Resolve not found"}

        project_manager = resolve.GetProjectManager()
        if not project_manager:
            return {"error": "Could not get Project Manager"}

        current_project = project_manager.GetCurrentProject()
        if not current_project:
            return {"error": "No project is currently open"}

        # Get render presets
        presets = current_project.GetRenderPresets()

        return {"presets": presets}

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}


def mcp_get_render_formats() -> Dict[str, Any]:
    """
    Get a list of all available render formats.

    Returns:
        A dictionary with render formats
    """
    try:
        resolve = get_resolve_instance()
        if not resolve:
            return {"error": "DaVinci Resolve not found"}

        project_manager = resolve.GetProjectManager()
        if not project_manager:
            return {"error": "Could not get Project Manager"}

        current_project = project_manager.GetCurrentProject()
        if not current_project:
            return {"error": "No project is currently open"}

        # Get render formats
        formats = current_project.GetRenderFormats()

        return {"formats": formats}

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}


def mcp_get_render_codecs(format_name: str) -> Dict[str, Any]:
    """
    Get a list of all available render codecs for a specific format.

    Args:
        format_name: The name of the render format

    Returns:
        A dictionary with render codecs
    """
    try:
        resolve = get_resolve_instance()
        if not resolve:
            return {"error": "DaVinci Resolve not found"}

        project_manager = resolve.GetProjectManager()
        if not project_manager:
            return {"error": "Could not get Project Manager"}

        current_project = project_manager.GetCurrentProject()
        if not current_project:
            return {"error": "No project is currently open"}

        # Get render codecs
        codecs = current_project.GetRenderCodecs(format_name)

        return {"format": format_name, "codecs": codecs}

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}


def mcp_get_render_jobs() -> Dict[str, Any]:
    """
    Get a list of all render jobs in the current project.

    Returns:
        A dictionary with render jobs
    """
    try:
        resolve = get_resolve_instance()
        if not resolve:
            return {"error": "DaVinci Resolve not found"}

        project_manager = resolve.GetProjectManager()
        if not project_manager:
            return {"error": "Could not get Project Manager"}

        current_project = project_manager.GetCurrentProject()
        if not current_project:
            return {"error": "No project is currently open"}

        # Get render jobs
        jobs = current_project.GetRenderJobList()

        return {"jobs": jobs}

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}


def mcp_add_render_job(
    preset_name: Optional[str] = None,
    output_directory: Optional[str] = None,
    custom_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Add a new render job to the render queue.

    Args:
        preset_name: The name of the render preset to use, or None for current settings
        output_directory: The output directory, or None for default
        custom_name: A custom name for the render job, or None for default

    Returns:
        A dictionary with the status of the operation
    """
    try:
        resolve = get_resolve_instance()
        if not resolve:
            return {"error": "DaVinci Resolve not found"}

        project_manager = resolve.GetProjectManager()
        if not project_manager:
            return {"error": "Could not get Project Manager"}

        current_project = project_manager.GetCurrentProject()
        if not current_project:
            return {"error": "No project is currently open"}

        # Configure render settings if provided
        if preset_name:
            presets = current_project.GetRenderPresets()
            if preset_name not in presets:
                return {"error": f"Render preset '{preset_name}' not found"}

            current_project.LoadRenderPreset(preset_name)

        # Set custom output directory and name if provided
        render_settings = {}

        if output_directory:
            render_settings["TargetDir"] = output_directory

        if custom_name:
            render_settings["CustomName"] = custom_name

        if render_settings:
            current_project.SetRenderSettings(render_settings)

        # Add render job
        job_id = current_project.AddRenderJob()

        if job_id:
            return {
                "status": "success",
                "message": "Render job added successfully",
                "job_id": job_id,
            }
        else:
            return {"error": "Failed to add render job"}

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}


def mcp_delete_render_job(job_id: str) -> Dict[str, Any]:
    """
    Delete a render job from the render queue.

    Args:
        job_id: The ID of the render job to delete

    Returns:
        A dictionary with the status of the operation
    """
    try:
        resolve = get_resolve_instance()
        if not resolve:
            return {"error": "DaVinci Resolve not found"}

        project_manager = resolve.GetProjectManager()
        if not project_manager:
            return {"error": "Could not get Project Manager"}

        current_project = project_manager.GetCurrentProject()
        if not current_project:
            return {"error": "No project is currently open"}

        # Delete render job
        success = current_project.DeleteRenderJob(job_id)

        if success:
            return {
                "status": "success",
                "message": f"Render job '{job_id}' deleted successfully",
            }
        else:
            return {"error": f"Failed to delete render job '{job_id}'"}

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}


def mcp_start_rendering(
    job_ids: Optional[List[str]] = None, interactive: bool = False
) -> Dict[str, Any]:
    """
    Start rendering the specified jobs or all jobs.

    Args:
        job_ids: List of job IDs to render, or None for all jobs
        interactive: Whether to show the render dialog (True) or render in the background (False)

    Returns:
        A dictionary with the status of the operation
    """
    try:
        resolve = get_resolve_instance()
        if not resolve:
            return {"error": "DaVinci Resolve not found"}

        project_manager = resolve.GetProjectManager()
        if not project_manager:
            return {"error": "Could not get Project Manager"}

        current_project = project_manager.GetCurrentProject()
        if not current_project:
            return {"error": "No project is currently open"}

        # Start rendering
        success = False

        if job_ids:
            if interactive:
                # Interactive render with specific jobs
                success = current_project.StartRendering(job_ids, interactive)
            else:
                # Background render with specific jobs
                success = current_project.StartRendering(job_ids)
        else:
            # Get all jobs and start rendering
            jobs = current_project.GetRenderJobList()
            job_ids = [job["JobId"] for job in jobs]

            if interactive:
                # Interactive render with all jobs
                success = current_project.StartRendering(job_ids, interactive)
            else:
                # Background render with all jobs
                success = current_project.StartRendering(job_ids)

        if success:
            return {
                "status": "success",
                "message": "Rendering started successfully",
                "job_ids": job_ids,
                "interactive": interactive,
            }
        else:
            return {"error": "Failed to start rendering"}

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}


def mcp_stop_rendering() -> Dict[str, Any]:
    """
    Stop the current rendering process.

    Returns:
        A dictionary with the status of the operation
    """
    try:
        resolve = get_resolve_instance()
        if not resolve:
            return {"error": "DaVinci Resolve not found"}

        project_manager = resolve.GetProjectManager()
        if not project_manager:
            return {"error": "Could not get Project Manager"}

        current_project = project_manager.GetCurrentProject()
        if not current_project:
            return {"error": "No project is currently open"}

        # Stop rendering
        success = current_project.StopRendering()

        if success:
            return {"status": "success", "message": "Rendering stopped successfully"}
        else:
            return {"error": "Failed to stop rendering"}

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}


def mcp_get_render_job_status(job_id: str) -> Dict[str, Any]:
    """
    Get the status of a specific render job.

    Args:
        job_id: The ID of the render job

    Returns:
        A dictionary with the job status
    """
    try:
        resolve = get_resolve_instance()
        if not resolve:
            return {"error": "DaVinci Resolve not found"}

        project_manager = resolve.GetProjectManager()
        if not project_manager:
            return {"error": "Could not get Project Manager"}

        current_project = project_manager.GetCurrentProject()
        if not current_project:
            return {"error": "No project is currently open"}

        # Get job status
        status = current_project.GetRenderJobStatus(job_id)

        return {"job_id": job_id, "status": status}

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}
