#!/usr/bin/env python3
"""
DaVinci Resolve Connection Utilities
"""

import logging
import math
import os

from .platform import get_platform, get_resolve_paths, setup_environment

try:  # optional: absent in minimal installs, and never required for Studio
    from . import resolve_bridge_client as bridge_client
except Exception:  # pragma: no cover - defensive
    bridge_client = None

logger = logging.getLogger("davinci-resolve-mcp.connection")

DEFAULT_RESOLVE_SCRIPT_TIMEOUT = 5.0


def _network_timeout():
    value = os.environ.get(
        "RESOLVE_SCRIPT_TIMEOUT",
        str(DEFAULT_RESOLVE_SCRIPT_TIMEOUT),
    )
    try:
        timeout = float(value)
    except ValueError as exc:
        raise ValueError(
            "RESOLVE_SCRIPT_TIMEOUT must be a positive finite number"
        ) from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError(
            "RESOLVE_SCRIPT_TIMEOUT must be a positive finite number"
        )
    return timeout


def connect_resolve(dvr_script):
    """Create a Resolve handle. Three modes, tried in order of directness.

    1. **Bridge** (opt-in, `DAVINCI_RESOLVE_BRIDGE=1`) — a proxy over the
       authenticated loopback bridge running inside Resolve. This is the only
       mode that works on the **free edition**, whose external scripting API
       refuses foreign processes. Tried first when enabled, because if a user has
       asked for it, silently using a different transport would hide a broken
       bridge.
    2. **Network** (`RESOLVE_SCRIPT_HOST`) — Studio's remote scripting.
    3. **Local** — Studio's local scripting. The default.

    `dvr_script` may be None in bridge mode: the bridge does not need Blackmagic's
    module at all, which is precisely why it reaches editions the module cannot.
    """
    if bridge_client is not None and bridge_client.bridge_enabled():
        try:
            return bridge_client.connect()
        except bridge_client.BridgeUnavailable as exc:
            # Explicitly requested and unavailable: say so instead of quietly
            # falling through to a transport the user did not ask for.
            logger.error("in-app bridge requested but unavailable: %s", exc)
            raise
    if dvr_script is None:
        return None
    host = os.environ.get("RESOLVE_SCRIPT_HOST")
    if host:
        return dvr_script.scriptapp("Resolve", host, _network_timeout())
    return dvr_script.scriptapp("Resolve")


def initialize_resolve():
    """Initialize connection to DaVinci Resolve application."""
    try:
        # Import the DaVinci Resolve scripting module
        import DaVinciResolveScript as dvr_script

        # Get the resolve object
        resolve = connect_resolve(dvr_script)

        if resolve is None:
            logger.error("Failed to get Resolve object. Is DaVinci Resolve running?")
            return None

        logger.info(f"Connected to DaVinci Resolve: {resolve.GetProductName()} {resolve.GetVersionString()}")
        return resolve

    except ImportError:
        platform_name = get_platform()
        paths = get_resolve_paths()

        logger.error("Failed to import DaVinciResolveScript. Check environment variables.")
        logger.error("RESOLVE_SCRIPT_API, RESOLVE_SCRIPT_LIB, and PYTHONPATH must be set correctly.")

        if platform_name == 'darwin':
            logger.error("On macOS, typically:")
            logger.error(f'export RESOLVE_SCRIPT_API="{paths["api_path"]}"')
            logger.error(f'export RESOLVE_SCRIPT_LIB="{paths["lib_path"]}"')
            logger.error(f'export PYTHONPATH="$PYTHONPATH:{paths["modules_path"]}"')
        elif platform_name == 'windows':
            logger.error("On Windows, typically:")
            logger.error(f'set RESOLVE_SCRIPT_API={paths["api_path"]}')
            logger.error(f'set RESOLVE_SCRIPT_LIB={paths["lib_path"]}')
            logger.error(f'set PYTHONPATH=%PYTHONPATH%;{paths["modules_path"]}')
        elif platform_name == 'linux':
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
        "resolve_script_lib": resolve_script_lib
    }


def set_default_environment_variables():
    """Set the default environment variables based on platform."""
    return setup_environment()
