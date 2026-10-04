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

from src.utils.resolve_probe import has_method

# Configure logging
logger = logging.getLogger("davinci-resolve-mcp.app_control")
APP_CONTROL_TIMEOUT_SECONDS = 10


def _run_app_command(
    cmd: List[str],
    description: str,
    timeout: int = APP_CONTROL_TIMEOUT_SECONDS,
) -> bool:
    """Run a platform app-control command with a bounded wait."""
    try:
        result = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logger.error("%s timed out after %ss: %s", description, timeout, cmd)
        return False
    except OSError as exc:
        logger.error("%s failed to launch: %s", description, exc)
        return False

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        logger.warning(
            "%s exited with code %s%s",
            description,
            result.returncode,
            f": {stderr}" if stderr else "",
        )
        return False
    return True


def quit_resolve_app(resolve_obj, force: bool = False, save_project: bool = True) -> bool:
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
                # Only the exception was handled. SaveProject also reports a
                # refusal with a bare False -- which is what a project attached
                # to no database returns -- and quitting on that throws the
                # session away silently.
                try:
                    saved = project.SaveProject()
                except Exception as e:
                    logger.error(f"Failed to save project: {str(e)}")
                    if not force:
                        logger.error("Aborting quit due to save failure")
                        return False
                else:
                    if saved is False:
                        logger.error("SaveProject returned False; the project was NOT saved")
                        if not force:
                            logger.error("Aborting quit due to save failure")
                            return False
        
        # Attempt to quit using the API
        if hasattr(resolve_obj, 'Quit') and callable(getattr(resolve_obj, 'Quit')):
            logger.info("Using Resolve.Quit() API")
            resolve_obj.Quit()
            return True
        
        # If Quit method isn't available or fails, use platform-specific methods
        sys_platform = platform.system().lower()
        
        if sys_platform == 'darwin':
            # macOS - use AppleScript
            logger.info("Using AppleScript to quit Resolve on macOS")
            cmd = [
                'osascript',
                '-e', 'tell application "DaVinci Resolve" to quit'
            ]
            if force:
                # Add force option if requested
                cmd = [
                    'osascript',
                    '-e', 'tell application "DaVinci Resolve" to quit with saving'
                ]
            
            return _run_app_command(cmd, "macOS Resolve quit command")
            
        elif sys_platform == 'windows':
            # Windows - use taskkill
            logger.info("Using taskkill to quit Resolve on Windows")
            if force:
                return _run_app_command(
                    ['taskkill', '/F', '/IM', 'Resolve.exe'],
                    "Windows Resolve force-quit command",
                )
            else:
                return _run_app_command(
                    ['taskkill', '/IM', 'Resolve.exe'],
                    "Windows Resolve quit command",
                )
            
        elif sys_platform == 'linux':
            # Linux - use pkill
            logger.info("Using pkill to quit Resolve on Linux")
            if force:
                return _run_app_command(
                    ['pkill', '-9', 'resolve'],
                    "Linux Resolve force-quit command",
                )
            else:
                return _run_app_command(
                    ['pkill', 'resolve'],
                    "Linux Resolve quit command",
                )
            
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
        except Exception:
            logger.debug("Could not read Resolve version string", exc_info=True)
            
        try:
            state["product_name"] = resolve_obj.GetProductName()
        except Exception:
            logger.debug("Could not read Resolve product name", exc_info=True)
            
        try:
            state["current_page"] = resolve_obj.GetCurrentPage()
        except Exception:
            logger.debug("Could not read Resolve current page", exc_info=True)
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
        if platform.system().lower() == 'darwin':
            resolve_path = '/Applications/DaVinci Resolve/DaVinci Resolve.app'
        elif platform.system().lower() == 'windows':
            # Default path, may need to be customized
            resolve_path = r'C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe'
        elif platform.system().lower() == 'linux':
            # Default path, may need to be customized
            resolve_path = '/opt/resolve/bin/resolve'
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
        
        if platform.system().lower() == 'darwin':
            subprocess.Popen(['open', resolve_path], stdin=subprocess.DEVNULL)
        elif platform.system().lower() == 'windows':
            subprocess.Popen([resolve_path], stdin=subprocess.DEVNULL)
        elif platform.system().lower() == 'linux':
            subprocess.Popen([resolve_path], stdin=subprocess.DEVNULL)
        
        return True
    except Exception as e:
        logger.error(f"Error restarting DaVinci Resolve: {str(e)}")
        return False

def _open_dialog(resolve_obj, method_name: str, label: str) -> Dict[str, Any]:
    """Ask Resolve to open a dialog, and say what actually happened.

    Returns {"success", "supported", "message"}.

    The route this module has always used is Resolve.GetUIManager() and then a
    method on the manager. Neither half exists on any build measured so far.
    On Studio 19.1.3.7 (2026-09-30): dir(resolve) lists 23 methods and
    GetUIManager is not one of them; Fusion().UIManager is real but offers
    neither OpenProjectSettings nor OpenPreferences; and none of the three
    names appears in the 21.1 typed API. So the old code raised "'NoneType'
    object is not callable" on its first line, caught it, logged an error and
    returned a bare False — a tool that could never work, reporting that as an
    ordinary failure with no reason.

    `hasattr` cannot make this distinction: it is True for every name on a
    Resolve object (see src/utils/resolve_probe.py). `has_method` can, so the
    route is probed with it, and a build that does grow these calls is used
    and its answer reported instead of assumed.
    """
    if not has_method(resolve_obj, "GetUIManager"):
        return {
            "success": False,
            "supported": False,
            "message": (
                f"Not supported: DaVinci Resolve's scripting API has no call that opens the "
                f"{label} dialog. Resolve.GetUIManager does not exist on this build."
            ),
        }
    ui_manager = resolve_obj.GetUIManager()
    if not has_method(ui_manager, method_name):
        return {
            "success": False,
            "supported": False,
            "message": (
                f"Not supported: DaVinci Resolve's scripting API has no call that opens the "
                f"{label} dialog. UIManager.{method_name} does not exist on this build."
            ),
        }
    try:
        opened = getattr(ui_manager, method_name)()
    except Exception as exc:
        logger.error("UIManager.%s raised: %s", method_name, exc)
        return {
            "success": False,
            "supported": True,
            "message": f"Failed to open the {label} dialog: UIManager.{method_name} raised {exc}",
        }
    if opened is False:
        return {
            "success": False,
            "supported": True,
            "message": f"Failed to open the {label} dialog: UIManager.{method_name} returned False",
        }
    return {"success": True, "supported": True, "message": f"{label} dialog opened"}


def open_project_settings(resolve_obj) -> Dict[str, Any]:
    """Open the Project Settings dialog. See `_open_dialog` for the result shape."""
    return _open_dialog(resolve_obj, "OpenProjectSettings", "Project Settings")


def open_preferences(resolve_obj) -> Dict[str, Any]:
    """Open the Preferences dialog. See `_open_dialog` for the result shape."""
    return _open_dialog(resolve_obj, "OpenPreferences", "Preferences")
