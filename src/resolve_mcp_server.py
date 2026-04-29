#!/usr/bin/env python3
"""DaVinci Resolve MCP Server (granular tools)."""

import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.dirname(current_dir)

for path in (project_dir, current_dir):
    if path not in sys.path:
        sys.path.insert(0, path)

from src.utils.platform import get_resolve_paths

paths = get_resolve_paths()
api_path = os.environ.get("RESOLVE_SCRIPT_API") or paths["api_path"]
lib_path = os.environ.get("RESOLVE_SCRIPT_LIB") or paths["lib_path"]
modules_path = os.path.join(api_path, "Modules") if api_path else paths["modules_path"]

if api_path:
    os.environ["RESOLVE_SCRIPT_API"] = api_path
if lib_path:
    os.environ["RESOLVE_SCRIPT_LIB"] = lib_path
if modules_path and modules_path not in sys.path:
    sys.path.append(modules_path)

from src.granular import VERSION, mcp
from src.granular.common import logger
from src.utils.mcp_stdio import run_fastmcp_stdio


if __name__ == "__main__":
    try:
        logger.info(f"Starting DaVinci Resolve MCP Server v{VERSION} (354 granular tools)")
        run_fastmcp_stdio(mcp)
    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
    except Exception as exc:
        logger.error(f"Server error: {exc}")
        sys.exit(1)
