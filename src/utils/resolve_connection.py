#!/usr/bin/env python3
"""
DaVinci Resolve Connection Utilities
"""

import os
import logging
from .platform import get_platform, get_resolve_paths, setup_environment

logger = logging.getLogger("davinci-resolve-mcp.connection")


def initialize_resolve():
    """Initialize connection to DaVinci Resolve application."""
    try:
        # Import the DaVinci Resolve scripting module
        import DaVinciResolveScript as dvr_script

        # Get the resolve object
        resolve = dvr_script.scriptapp("Resolve")

        if resolve is None:
            logger.error("Failed to get Resolve object. Is DaVinci Resolve running?")
            return None

        logger.info(
            f"Connected to DaVinci Resolve: {resolve.GetProductName()} {resolve.GetVersionString()}"
        )
        return resolve

    except ImportError:
        platform_name = get_platform()
        paths = get_resolve_paths()

        logger.error(
            "Failed to import DaVinciResolveScript. Check environment variables."
        )
        logger.error(
            "RESOLVE_SCRIPT_API, RESOLVE_SCRIPT_LIB, and PYTHONPATH must be set correctly."
        )

        if platform_name == "darwin":
            logger.error("On macOS, typically:")
            logger.error(f'export RESOLVE_SCRIPT_API="{paths["api_path"]}"')
            logger.error(f'export RESOLVE_SCRIPT_LIB="{paths["lib_path"]}"')
            logger.error(f'export PYTHONPATH="$PYTHONPATH:{paths["modules_path"]}"')
        elif platform_name == "windows":
            logger.error("On Windows, typically:")
            logger.error(f'set RESOLVE_SCRIPT_API={paths["api_path"]}')
            logger.error(f'set RESOLVE_SCRIPT_LIB={paths["lib_path"]}')
            logger.error(f'set PYTHONPATH=%PYTHONPATH%;{paths["modules_path"]}')
        elif platform_name == "linux":
            logger.error("On Linux, typically:")
            logger.error(f'export RESOLVE_SCRIPT_API="{paths["api_path"]}"')
            logger.error(f'export RESOLVE_SCRIPT_LIB="{paths["lib_path"]}"')
            logger.error(f'export PYTHONPATH="$PYTHONPATH:{paths["modules_path"]}"')

        return None

    except Exception as e:
        logger.error(f"Unexpected error initializing Resolve: {str(e)}")
        return None


def check_environment_variables():
    """Check if the required environment variables are set."""
    resolve_script_api = os.environ.get("RESOLVE_SCRIPT_API")
    resolve_script_lib = os.environ.get("RESOLVE_SCRIPT_LIB")

    missing_vars = []
    if not resolve_script_api:
        missing_vars.append("RESOLVE_SCRIPT_API")
    if not resolve_script_lib:
        missing_vars.append("RESOLVE_SCRIPT_LIB")

    return {
        "all_set": len(missing_vars) == 0,
        "missing": missing_vars,
        "resolve_script_api": resolve_script_api,
        "resolve_script_lib": resolve_script_lib,
    }


def set_default_environment_variables():
    """Set the default environment variables based on platform."""
    return setup_environment()
