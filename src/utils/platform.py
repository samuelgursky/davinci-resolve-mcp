#!/usr/bin/env python3
"""
Platform-specific functionality for DaVinci Resolve MCP Server
"""

import os
import sys
import platform


def get_platform():
    """Identify the current operating system platform.

    Returns:
        str: 'windows', 'darwin' (macOS), or 'linux'
    """
    system = platform.system().lower()
    if system == "darwin":
        return "darwin"
    elif system == "windows":
        return "windows"
    elif system == "linux":
        return "linux"
    return system


def get_resolve_paths():
    """Get platform-specific paths for DaVinci Resolve scripting API.

    Returns:
        dict: Dictionary containing api_path, lib_path, and modules_path
    """
    platform_name = get_platform()

    if platform_name == "darwin":  # macOS
        api_path = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
        lib_path = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
        modules_path = os.path.join(api_path, "Modules")

    elif platform_name == "windows":  # Windows
        program_files = os.environ.get("PROGRAMDATA", "C:\\ProgramData")
        program_files_64 = os.environ.get("PROGRAMFILES", "C:\\Program Files")

        api_path = os.path.join(
            program_files,
            "Blackmagic Design",
            "DaVinci Resolve",
            "Support",
            "Developer",
            "Scripting",
        )
        lib_path = os.path.join(
            program_files_64, "Blackmagic Design", "DaVinci Resolve", "fusionscript.dll"
        )
        modules_path = os.path.join(api_path, "Modules")

    elif platform_name == "linux":  # Linux (not fully implemented)
        # Default locations for Linux - these may need to be adjusted
        api_path = "/opt/resolve/Developer/Scripting"
        lib_path = "/opt/resolve/libs/fusionscript.so"
        modules_path = os.path.join(api_path, "Modules")

    else:
        # Fallback to macOS paths if unknown platform
        api_path = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
        lib_path = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
        modules_path = os.path.join(api_path, "Modules")

    return {"api_path": api_path, "lib_path": lib_path, "modules_path": modules_path}


def setup_environment():
    """Set up environment variables for DaVinci Resolve scripting.

    Returns:
        bool: True if setup was successful, False otherwise
    """
    try:
        paths = get_resolve_paths()

        os.environ["RESOLVE_SCRIPT_API"] = paths["api_path"]
        os.environ["RESOLVE_SCRIPT_LIB"] = paths["lib_path"]

        # Add modules path to Python's path if it's not already there
        if paths["modules_path"] not in sys.path:
            sys.path.append(paths["modules_path"])

        return True

    except Exception as e:
        print(f"Error setting up environment: {str(e)}")
        return False
