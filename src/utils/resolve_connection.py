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


def _try_bridge_fallback():
    """Last-resort bridge attempt after a direct transport has already failed.

    Returns a proxy, or None when there is no bridge to reach. Unlike the
    explicitly-requested path this swallows `BridgeUnavailable`: nobody asked for
    the bridge, so "no bridge running" is simply "no Resolve" — the same answer
    the caller got before this fallback existed.
    """
    if bridge_client is None:
        return None
    try:
        proxy = bridge_client.connect(require_enabled=False)
    except bridge_client.BridgeUnavailable as exc:
        logger.debug("no in-app bridge to fall back to: %s", exc)
        return None
    logger.info(
        "external scripting unavailable; automatically using the in-app bridge "
        "(set %s=1 to require it and surface bridge faults directly)",
        bridge_client.ENV_ENABLE,
    )
    return proxy


def connect_resolve(dvr_script):
    """Create a Resolve handle. Three modes, tried in order of directness.

    1. **Bridge** (forced, `DAVINCI_RESOLVE_BRIDGE=1`) — a proxy over the
       authenticated loopback bridge running inside Resolve. This is the only
       mode that works on the **free edition**, whose external scripting API
       refuses foreign processes. Tried first *and exclusively* when the env var
       is set, because if a user has asked for it, silently using a different
       transport would hide a broken bridge.
    2. **Network** (`RESOLVE_SCRIPT_HOST`) — Studio's remote scripting.
    3. **Local** — Studio's local scripting. The default.

    If a direct transport yields nothing, the bridge is tried once more as a
    **fallback**, without the env var. That cannot mask a broken bridge the way
    an unconditional bridge-first order would: it only runs on a path that has
    already failed, so the env var stays meaningful as "require the bridge and
    tell me when it breaks" while the free edition works with no configuration
    beyond starting the in-Resolve script.

    `dvr_script` may be None: the bridge does not need Blackmagic's module at
    all, which is precisely why it reaches editions the module cannot — so a
    missing module is a reason to try the bridge, not to give up.
    """
    if bridge_client is not None and bridge_client.bridge_enabled():
        try:
            return bridge_client.connect()
        except bridge_client.BridgeUnavailable as exc:
            # Explicitly requested and unavailable: say so instead of quietly
            # falling through to a transport the user did not ask for.
            logger.error("in-app bridge requested but unavailable: %s", exc)
            raise
    resolve = None
    if dvr_script is not None:
        host = os.environ.get("RESOLVE_SCRIPT_HOST")
        if host:
            resolve = dvr_script.scriptapp("Resolve", host, _network_timeout())
        else:
            resolve = dvr_script.scriptapp("Resolve")
    if resolve is not None:
        return resolve
    return _try_bridge_fallback()


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
