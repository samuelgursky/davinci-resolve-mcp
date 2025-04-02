#!/usr/bin/env python3
"""
DaVinci Resolve MCP Server - Application Control Utilities

This module provides functions for controlling DaVinci Resolve application:
- Quitting the application
- Checking application state
- Handling basic application functions
"""

import os
import logging
import time
import sys
import platform
import subprocess
from typing import Dict, Any, Optional, Union, List

# Configure logging
logger = logging.getLogger("davinci-resolve-mcp.app_control")


def quit_resolve_app(
    resolve_obj, force: bool = False, save_project: bool = True
) -> bool:
    """
    Quit DaVinci Resolve application.

    Args:
        resolve_obj: DaVinci Resolve API object
        force: Whether to force quit even if unsaved changes (potentially dangerous)
        save_project: Whether to save the project before quitting

    Returns:
        True if the quit command was sent successfully
    """
    try:
        logger.info("Attempting to quit DaVinci Resolve")

        # Check if a project is open
        pm = resolve_obj.GetProjectManager()
        if pm:
            project = pm.GetCurrentProject()
            if project and save_project:
                logger.info("Saving project before quitting")
                # Try to save the project
                try:
                    project.SaveProject()
                except Exception as e:
                    logger.error(f"Failed to save project: {str(e)}")
                    if not force:
                        logger.error("Aborting quit due to save failure")
                        return False

        # Attempt to quit using the API
        if hasattr(resolve_obj, "Quit") and callable(getattr(resolve_obj, "Quit")):
            logger.info("Using Resolve.Quit() API")
            resolve_obj.Quit()
            return True

        # If Quit method isn't available or fails, use platform-specific methods
        sys_platform = platform.system().lower()

        if sys_platform == "darwin":
            # macOS - use AppleScript
            logger.info("Using AppleScript to quit Resolve on macOS")
            cmd = ["osascript", "-e", 'tell application "DaVinci Resolve" to quit']
            if force:
                # Add force option if requested
                cmd = [
                    "osascript",
                    "-e",
                    'tell application "DaVinci Resolve" to quit with saving',
                ]

            subprocess.run(cmd)
            return True

        elif sys_platform == "windows":
            # Windows - use taskkill
            logger.info("Using taskkill to quit Resolve on Windows")
            if force:
                subprocess.run(["taskkill", "/F", "/IM", "Resolve.exe"])
            else:
                subprocess.run(["taskkill", "/IM", "Resolve.exe"])
            return True

        elif sys_platform == "linux":
            # Linux - use pkill
            logger.info("Using pkill to quit Resolve on Linux")
            if force:
                subprocess.run(["pkill", "-9", "resolve"])
            else:
                subprocess.run(["pkill", "resolve"])
            return True

        # If all methods fail, return False
        logger.error("Failed to quit Resolve via any method")
        return False

    except Exception as e:
        logger.error(f"Error quitting DaVinci Resolve: {str(e)}")
        return False


def get_app_state(resolve_obj) -> Dict[str, Any]:
    """
    Get DaVinci Resolve application state information.

    Args:
        resolve_obj: DaVinci Resolve API object

    Returns:
        Dictionary with application state information
    """
    state = {
        "connected": resolve_obj is not None,
        "version": "Unknown",
        "product_name": "Unknown",
        "platform": platform.system(),
        "python_version": sys.version,
    }

    if resolve_obj:
        try:
            state["version"] = resolve_obj.GetVersionString()
        except:
            pass

        try:
            state["product_name"] = resolve_obj.GetProductName()
        except:
            pass

        try:
            state["current_page"] = resolve_obj.GetCurrentPage()
        except:
            state["current_page"] = "Unknown"

        # Get project manager and project information
        try:
            pm = resolve_obj.GetProjectManager()
            if pm:
                state["project_manager_available"] = True

                current_project = pm.GetCurrentProject()
                if current_project:
                    state["project_open"] = True
                    state["project_name"] = current_project.GetName()

                    # Check if timeline is open
                    current_timeline = current_project.GetCurrentTimeline()
                    if current_timeline:
                        state["timeline_open"] = True
                        state["timeline_name"] = current_timeline.GetName()
                    else:
                        state["timeline_open"] = False
                else:
                    state["project_open"] = False
            else:
                state["project_manager_available"] = False
        except Exception as e:
            state["project_error"] = str(e)

    return state


def restart_resolve_app(resolve_obj, wait_seconds: int = 5) -> bool:
    """
    Restart DaVinci Resolve application.

    Args:
        resolve_obj: DaVinci Resolve API object
        wait_seconds: Seconds to wait between quit and restart

    Returns:
        True if restart was initiated successfully
    """
    try:
        # Get Resolve executable path for restart
        if platform.system().lower() == "darwin":
            resolve_path = "/Applications/DaVinci Resolve/DaVinci Resolve.app"
        elif platform.system().lower() == "windows":
            # Default path, may need to be customized
            resolve_path = (
                r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe"
            )
        elif platform.system().lower() == "linux":
            # Default path, may need to be customized
            resolve_path = "/opt/resolve/bin/resolve"
        else:
            return False

        # Quit Resolve
        if not quit_resolve_app(resolve_obj, force=False, save_project=True):
            logger.error("Failed to quit Resolve for restart")
            return False

        # Wait for the app to close
        logger.info(f"Waiting {wait_seconds} seconds for Resolve to close")
        time.sleep(wait_seconds)

        # Start Resolve again
        logger.info("Attempting to start Resolve")

        if platform.system().lower() == "darwin":
            subprocess.Popen(["open", resolve_path])
        elif platform.system().lower() == "windows":
            subprocess.Popen([resolve_path])
        elif platform.system().lower() == "linux":
            subprocess.Popen([resolve_path])

        return True
    except Exception as e:
        logger.error(f"Error restarting DaVinci Resolve: {str(e)}")
        return False


def open_project_settings(resolve_obj) -> bool:
    """
    Open the Project Settings dialog in DaVinci Resolve.

    Args:
        resolve_obj: DaVinci Resolve API object

    Returns:
        True if successful, False otherwise
    """
    try:
        # Check if UI Manager is available
        ui_manager = resolve_obj.GetUIManager()
        if not ui_manager:
            logger.error("Failed to get UI Manager")
            return False

        # Open Project Settings dialog
        if hasattr(ui_manager, "OpenProjectSettings") and callable(
            getattr(ui_manager, "OpenProjectSettings")
        ):
            ui_manager.OpenProjectSettings()
            return True

        # Alternative method - send keyboard shortcut based on platform
        current_page = resolve_obj.GetCurrentPage()

        # Ensure we're on a page that supports project settings
        if current_page not in [
            "media",
            "cut",
            "edit",
            "fusion",
            "color",
            "fairlight",
            "deliver",
        ]:
            logger.error(f"Can't open settings from page: {current_page}")
            return False

        return False  # Keyboard shortcuts not implemented yet
    except Exception as e:
        logger.error(f"Error opening project settings: {str(e)}")
        return False


def open_preferences(resolve_obj) -> bool:
    """
    Open the Preferences dialog in DaVinci Resolve.

    Args:
        resolve_obj: DaVinci Resolve API object

    Returns:
        True if successful, False otherwise
    """
    try:
        # Check if UI Manager is available
        ui_manager = resolve_obj.GetUIManager()
        if not ui_manager:
            logger.error("Failed to get UI Manager")
            return False

        # Open Preferences dialog
        if hasattr(ui_manager, "OpenPreferences") and callable(
            getattr(ui_manager, "OpenPreferences")
        ):
            ui_manager.OpenPreferences()
            return True

        # Alternative method - send keyboard shortcut based on platform
        return False  # Keyboard shortcuts not implemented yet
    except Exception as e:
        logger.error(f"Error opening preferences: {str(e)}")
        return False
