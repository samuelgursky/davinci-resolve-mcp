#!/usr/bin/env python3
"""
DaVinci Resolve MCP Server
A server that connects to DaVinci Resolve via the Model Context Protocol (MCP)
"""

import sys
import logging
from mcp.server.fastmcp import FastMCP

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("davinci-resolve-mcp")

# Create MCP server instance
mcp = FastMCP("DaVinciResolveMCP")


# Initialize connection to DaVinci Resolve
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
        logger.error(
            "Failed to import DaVinciResolveScript. Check environment variables."
        )
        logger.error(
            "RESOLVE_SCRIPT_API, RESOLVE_SCRIPT_LIB, and PYTHONPATH must be set correctly."
        )
        logger.error("On macOS, typically:")
        logger.error(
            'export RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"'
        )
        logger.error(
            'export RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"'
        )
        logger.error('export PYTHONPATH="$PYTHONPATH:$RESOLVE_SCRIPT_API/Modules/"')
        return None

    except Exception as e:
        logger.error(f"Unexpected error initializing Resolve: {str(e)}")
        return None


# Initialize Resolve once at startup
resolve = initialize_resolve()

# ------------------
# MCP Tools/Resources
# ------------------


@mcp.resource("resolve://version")
def get_resolve_version() -> str:
    """Get DaVinci Resolve version information."""
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    return f"{resolve.GetProductName()} {resolve.GetVersionString()}"


@mcp.resource("resolve://current-page")
def get_current_page() -> str:
    """Get the current page open in DaVinci Resolve (Edit, Color, Fusion, etc.)."""
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"
    return resolve.GetCurrentPage()


@mcp.tool()
def switch_page(page: str) -> str:
    """Switch to a specific page in DaVinci Resolve.

    Args:
        page: The page to switch to. Options: 'media', 'cut', 'edit', 'fusion', 'color', 'fairlight', 'deliver'
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"

    valid_pages = ["media", "cut", "edit", "fusion", "color", "fairlight", "deliver"]
    page = page.lower()

    if page not in valid_pages:
        return f"Error: Invalid page. Choose from {', '.join(valid_pages)}"

    resolve.OpenPage(page.capitalize())
    return f"Successfully switched to {page} page"


# Start the server
if __name__ == "__main__":
    try:
        if resolve is None:
            logger.error("Server started but not connected to DaVinci Resolve.")
            logger.error(
                "Make sure DaVinci Resolve is running and environment variables are correctly set."
            )
        else:
            logger.info("Successfully connected to DaVinci Resolve.")

        logger.info("Starting DaVinci Resolve MCP Server")
        mcp.run()
    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
    except Exception as e:
        logger.error(f"Server error: {str(e)}")
        sys.exit(1)
