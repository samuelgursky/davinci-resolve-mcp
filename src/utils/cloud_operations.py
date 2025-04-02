#!/usr/bin/env python3
"""
DaVinci Resolve MCP Server - Cloud Project Operations

This module provides functions for working with DaVinci Resolve cloud projects:
- Creating cloud projects
- Importing cloud projects
- Restoring cloud projects
- Managing cloud project settings and metadata
"""

import os
import logging
import json
from typing import Dict, List, Any, Optional, Union

# Configure logging
logger = logging.getLogger("davinci-resolve-mcp.cloud_operations")


def create_cloud_project(
    resolve_obj, project_name: str, folder_path: str = None
) -> Dict[str, Any]:
    """
    Create a new cloud project.

    Args:
        resolve_obj: DaVinci Resolve API object
        project_name: Name for the new cloud project
        folder_path: Optional path for the cloud project folder

    Returns:
        Dictionary with result and project information
    """
    if resolve_obj is None:
        return {"success": False, "error": "Not connected to DaVinci Resolve"}

    try:
        # Get project manager
        project_manager = resolve_obj.GetProjectManager()
        if not project_manager:
            return {"success": False, "error": "Failed to get Project Manager"}

        # Check if method exists in the API
        if not hasattr(project_manager, "CreateCloudProject"):
            return {
                "success": False,
                "error": "CreateCloudProject method not available in this version of DaVinci Resolve",
            }

        # Create the cloud project
        result = None
        if folder_path:
            # Create in specified folder
            result = project_manager.CreateCloudProject(project_name, folder_path)
        else:
            # Create in default location
            result = project_manager.CreateCloudProject(project_name)

        if result:
            # Try to get the newly created project
            new_project = project_manager.LoadProject(project_name)

            if new_project:
                return {
                    "success": True,
                    "message": f"Successfully created cloud project '{project_name}'",
                    "project_name": project_name,
                    "project_id": new_project.GetUniqueId()
                    if hasattr(new_project, "GetUniqueId")
                    else None,
                }
            else:
                return {
                    "success": True,
                    "message": f"Created cloud project '{project_name}' but failed to load it",
                    "project_name": project_name,
                }
        else:
            return {
                "success": False,
                "error": f"Failed to create cloud project '{project_name}'",
            }

    except Exception as e:
        logger.error(f"Error creating cloud project: {str(e)}")
        return {"success": False, "error": f"Error creating cloud project: {str(e)}"}


def import_cloud_project(
    resolve_obj, cloud_id: str, project_name: str = None
) -> Dict[str, Any]:
    """
    Import a project from DaVinci Resolve cloud.

    Args:
        resolve_obj: DaVinci Resolve API object
        cloud_id: Cloud ID or reference of the project to import
        project_name: Optional custom name for the imported project (uses original name if None)

    Returns:
        Dictionary with result and project information
    """
    if resolve_obj is None:
        return {"success": False, "error": "Not connected to DaVinci Resolve"}

    try:
        # Get project manager
        project_manager = resolve_obj.GetProjectManager()
        if not project_manager:
            return {"success": False, "error": "Failed to get Project Manager"}

        # Check if method exists in the API
        if not hasattr(project_manager, "ImportCloudProject"):
            return {
                "success": False,
                "error": "ImportCloudProject method not available in this version of DaVinci Resolve",
            }

        # Import the cloud project
        imported_project = None
        if project_name:
            # Import with custom name
            imported_project = project_manager.ImportCloudProject(
                cloud_id, project_name
            )
        else:
            # Import with original name
            imported_project = project_manager.ImportCloudProject(cloud_id)

        if imported_project:
            return {
                "success": True,
                "message": f"Successfully imported cloud project",
                "project_name": imported_project.GetName(),
                "project_id": imported_project.GetUniqueId()
                if hasattr(imported_project, "GetUniqueId")
                else None,
            }
        else:
            return {
                "success": False,
                "error": f"Failed to import cloud project with ID '{cloud_id}'",
            }

    except Exception as e:
        logger.error(f"Error importing cloud project: {str(e)}")
        return {"success": False, "error": f"Error importing cloud project: {str(e)}"}


def restore_cloud_project(
    resolve_obj, cloud_id: str, project_name: str = None
) -> Dict[str, Any]:
    """
    Restore a project from DaVinci Resolve cloud.

    Args:
        resolve_obj: DaVinci Resolve API object
        cloud_id: Cloud ID or reference of the project to restore
        project_name: Optional custom name for the restored project (uses original name if None)

    Returns:
        Dictionary with result and project information
    """
    if resolve_obj is None:
        return {"success": False, "error": "Not connected to DaVinci Resolve"}

    try:
        # Get project manager
        project_manager = resolve_obj.GetProjectManager()
        if not project_manager:
            return {"success": False, "error": "Failed to get Project Manager"}

        # Check if method exists in the API
        if not hasattr(project_manager, "RestoreCloudProject"):
            return {
                "success": False,
                "error": "RestoreCloudProject method not available in this version of DaVinci Resolve",
            }

        # Restore the cloud project
        restored_project = None
        if project_name:
            # Restore with custom name
            restored_project = project_manager.RestoreCloudProject(
                cloud_id, project_name
            )
        else:
            # Restore with original name
            restored_project = project_manager.RestoreCloudProject(cloud_id)

        if restored_project:
            return {
                "success": True,
                "message": f"Successfully restored cloud project",
                "project_name": restored_project.GetName(),
                "project_id": restored_project.GetUniqueId()
                if hasattr(restored_project, "GetUniqueId")
                else None,
            }
        else:
            return {
                "success": False,
                "error": f"Failed to restore cloud project with ID '{cloud_id}'",
            }

    except Exception as e:
        logger.error(f"Error restoring cloud project: {str(e)}")
        return {"success": False, "error": f"Error restoring cloud project: {str(e)}"}


def get_cloud_project_list(resolve_obj) -> Dict[str, Any]:
    """
    Get list of available cloud projects.

    Args:
        resolve_obj: DaVinci Resolve API object

    Returns:
        Dictionary with result and list of cloud projects
    """
    if resolve_obj is None:
        return {"success": False, "error": "Not connected to DaVinci Resolve"}

    try:
        # Get project manager
        project_manager = resolve_obj.GetProjectManager()
        if not project_manager:
            return {"success": False, "error": "Failed to get Project Manager"}

        # Check if method exists in the API
        if not hasattr(project_manager, "GetCloudProjectList"):
            return {
                "success": False,
                "error": "GetCloudProjectList method not available in this version of DaVinci Resolve",
            }

        # Get the cloud project list
        cloud_projects = project_manager.GetCloudProjectList()

        if cloud_projects is not None:
            # Convert to Python structure if needed
            # The exact format of the return value may vary depending on the API version
            if hasattr(cloud_projects, "keys") or hasattr(cloud_projects, "__iter__"):
                # It's likely some form of dictionary or list
                return {"success": True, "projects": cloud_projects}
            else:
                # It's something else, probably a custom type
                return {
                    "success": True,
                    "message": "Cloud projects retrieved but format is not standard",
                    "data": str(cloud_projects),
                }
        else:
            return {
                "success": False,
                "error": "Failed to get cloud project list or none available",
            }

    except Exception as e:
        logger.error(f"Error getting cloud project list: {str(e)}")
        return {
            "success": False,
            "error": f"Error getting cloud project list: {str(e)}",
        }


def export_project_to_cloud(resolve_obj, project_name: str = None) -> Dict[str, Any]:
    """
    Export current or specified project to DaVinci Resolve cloud.

    Args:
        resolve_obj: DaVinci Resolve API object
        project_name: Optional name of project to export (uses current project if None)

    Returns:
        Dictionary with result and cloud project information
    """
    if resolve_obj is None:
        return {"success": False, "error": "Not connected to DaVinci Resolve"}

    try:
        # Get project manager
        project_manager = resolve_obj.GetProjectManager()
        if not project_manager:
            return {"success": False, "error": "Failed to get Project Manager"}

        # Get the project to export
        project = None
        if project_name:
            # Try to load the specified project
            project = project_manager.LoadProject(project_name)
            if not project:
                return {
                    "success": False,
                    "error": f"Project '{project_name}' not found",
                }
        else:
            # Use current project
            project = project_manager.GetCurrentProject()
            if not project:
                return {"success": False, "error": "No project currently open"}

        # Check if method exists in the API
        if not hasattr(project, "ExportToCloud") and not hasattr(
            project_manager, "ExportProjectToCloud"
        ):
            return {
                "success": False,
                "error": "Cloud export methods not available in this version of DaVinci Resolve",
            }

        # Try to export the project to cloud
        export_result = None

        # Try project method first
        if hasattr(project, "ExportToCloud"):
            export_result = project.ExportToCloud()
        # Then try project manager method
        elif hasattr(project_manager, "ExportProjectToCloud"):
            export_result = project_manager.ExportProjectToCloud(project)

        if export_result:
            return {
                "success": True,
                "message": f"Successfully exported project '{project.GetName()}' to cloud",
                "project_name": project.GetName(),
                "cloud_id": export_result if isinstance(export_result, str) else None,
            }
        else:
            return {
                "success": False,
                "error": f"Failed to export project '{project.GetName()}' to cloud",
            }

    except Exception as e:
        logger.error(f"Error exporting project to cloud: {str(e)}")
        return {
            "success": False,
            "error": f"Error exporting project to cloud: {str(e)}",
        }


def add_user_to_cloud_project(
    resolve_obj, cloud_id: str, user_email: str, permissions: str = "viewer"
) -> Dict[str, Any]:
    """
    Add a user to a cloud project with specified permissions.

    Args:
        resolve_obj: DaVinci Resolve API object
        cloud_id: Cloud ID of the project
        user_email: Email of the user to add
        permissions: Permission level (viewer, editor, admin)

    Returns:
        Dictionary with result information
    """
    if resolve_obj is None:
        return {"success": False, "error": "Not connected to DaVinci Resolve"}

    try:
        # Get project manager
        project_manager = resolve_obj.GetProjectManager()
        if not project_manager:
            return {"success": False, "error": "Failed to get Project Manager"}

        # Check if method exists in the API
        if not hasattr(project_manager, "AddUserToCloudProject"):
            return {
                "success": False,
                "error": "AddUserToCloudProject method not available in this version of DaVinci Resolve",
            }

        # Convert permission string to numeric value if needed
        permission_map = {
            "viewer": 0,  # May need adjustment based on actual API
            "editor": 1,
            "admin": 2,
        }

        permission_value = permission_map.get(permissions.lower(), 0)

        # Add user to cloud project
        result = project_manager.AddUserToCloudProject(
            cloud_id, user_email, permission_value
        )

        if result:
            return {
                "success": True,
                "message": f"Successfully added user '{user_email}' to cloud project with '{permissions}' permissions",
            }
        else:
            return {
                "success": False,
                "error": f"Failed to add user '{user_email}' to cloud project",
            }

    except Exception as e:
        logger.error(f"Error adding user to cloud project: {str(e)}")
        return {
            "success": False,
            "error": f"Error adding user to cloud project: {str(e)}",
        }


def remove_user_from_cloud_project(
    resolve_obj, cloud_id: str, user_email: str
) -> Dict[str, Any]:
    """
    Remove a user from a cloud project.

    Args:
        resolve_obj: DaVinci Resolve API object
        cloud_id: Cloud ID of the project
        user_email: Email of the user to remove

    Returns:
        Dictionary with result information
    """
    if resolve_obj is None:
        return {"success": False, "error": "Not connected to DaVinci Resolve"}

    try:
        # Get project manager
        project_manager = resolve_obj.GetProjectManager()
        if not project_manager:
            return {"success": False, "error": "Failed to get Project Manager"}

        # Check if method exists in the API
        if not hasattr(project_manager, "RemoveUserFromCloudProject"):
            return {
                "success": False,
                "error": "RemoveUserFromCloudProject method not available in this version of DaVinci Resolve",
            }

        # Remove user from cloud project
        result = project_manager.RemoveUserFromCloudProject(cloud_id, user_email)

        if result:
            return {
                "success": True,
                "message": f"Successfully removed user '{user_email}' from cloud project",
            }
        else:
            return {
                "success": False,
                "error": f"Failed to remove user '{user_email}' from cloud project",
            }

    except Exception as e:
        logger.error(f"Error removing user from cloud project: {str(e)}")
        return {
            "success": False,
            "error": f"Error removing user from cloud project: {str(e)}",
        }
