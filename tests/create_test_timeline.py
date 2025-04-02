#!/usr/bin/env python3
"""
DaVinci Resolve Test Timeline Generator
---------------------------------------
This script creates a test timeline with sample media for testing the MCP server.
It generates colored test frames as clips if no media is available.

Usage:
    python create_test_timeline.py

Requirements:
    - DaVinci Resolve must be running
    - requests module (pip install requests)
"""

import os
import sys
import time
import requests
import logging
import tempfile
import subprocess
from typing import Dict, Any, List, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# Server configuration
SERVER_URL = "http://localhost:8000/api"


def send_request(tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Send a request to the MCP server."""
    try:
        payload = {"tool": tool_name, "params": params}
        response = requests.post(SERVER_URL, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {e}")
        return {"success": False, "error": str(e)}


def create_test_media() -> List[str]:
    """Create test media files for import."""
    logger.info("Creating test media files...")

    media_files = []
    temp_dir = tempfile.gettempdir()

    try:
        # Create three colored test frames using ffmpeg if available
        colors = ["red", "green", "blue"]

        for color in colors:
            output_file = os.path.join(temp_dir, f"test_{color}.mp4")

            # Check if ffmpeg is available
            try:
                # Create a 5-second test video with the specified color
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=c={color}:s=1280x720:r=30:d=5",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    output_file,
                ]
                subprocess.run(
                    cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                media_files.append(output_file)
                logger.info(f"Created {color} test media: {output_file}")
            except (subprocess.SubprocessError, FileNotFoundError) as e:
                logger.error(f"Failed to create test media: {e}")
                # Try an alternative method if ffmpeg fails
                break
    except Exception as e:
        logger.error(f"Error creating test media: {e}")

    if not media_files:
        logger.warning("Could not create test media. The timeline will be empty.")

    return media_files


def setup_test_project() -> bool:
    """Create a test project."""
    logger.info("Setting up test project...")

    # Create a new project
    result = send_request(
        "mcp_davinci_resolve_create_project", {"name": "MCP_Test_Project"}
    )

    if "error" in result and result["error"]:
        logger.error(f"Failed to create project: {result['error']}")

        # Try opening the project if it already exists
        open_result = send_request(
            "mcp_davinci_resolve_open_project", {"name": "MCP_Test_Project"}
        )
        if "error" in open_result and open_result["error"]:
            logger.error(f"Failed to open existing project: {open_result['error']}")
            return False
        else:
            logger.info("Opened existing test project")
    else:
        logger.info("Created new test project")

    # Set project settings
    send_request(
        "mcp_davinci_resolve_set_project_setting",
        {"setting_name": "timelineFrameRate", "setting_value": 30},
    )

    return True


def create_test_timeline() -> bool:
    """Create a test timeline with imported media."""
    logger.info("Creating test timeline...")

    # Create timeline
    result = send_request(
        "mcp_davinci_resolve_create_timeline", {"name": "MCP_Test_Timeline"}
    )

    if "error" in result and result["error"]:
        logger.error(f"Failed to create timeline: {result['error']}")
        return False

    logger.info("Created test timeline")

    # Set as current timeline
    send_request(
        "mcp_davinci_resolve_set_current_timeline", {"name": "MCP_Test_Timeline"}
    )

    # Create and import test media
    media_files = create_test_media()

    # Import media files
    for media_file in media_files:
        import_result = send_request(
            "mcp_davinci_resolve_import_media", {"file_path": media_file}
        )

        if "error" not in import_result or not import_result["error"]:
            logger.info(f"Imported media: {media_file}")

            # Add to timeline (after short delay to ensure media is processed)
            time.sleep(1)
            clip_name = os.path.basename(media_file)
            add_result = send_request(
                "mcp_davinci_resolve_add_clip_to_timeline",
                {"clip_name": clip_name, "timeline_name": "MCP_Test_Timeline"},
            )

            if "error" not in add_result or not add_result["error"]:
                logger.info(f"Added clip to timeline: {clip_name}")
            else:
                logger.warning(
                    f"Failed to add clip to timeline: {add_result.get('error', 'Unknown error')}"
                )
        else:
            logger.warning(
                f"Failed to import media: {import_result.get('error', 'Unknown error')}"
            )

    return True


def main() -> None:
    """Run the test timeline creation process."""
    logger.info("Starting DaVinci Resolve test timeline setup")
    logger.info("=" * 50)

    # Set up test project
    if not setup_test_project():
        logger.error("Failed to set up test project. Exiting.")
        sys.exit(1)

    # Create test timeline with media
    if not create_test_timeline():
        logger.error("Failed to create test timeline. Exiting.")
        sys.exit(1)

    logger.info("=" * 50)
    logger.info("Test timeline setup complete!")
    logger.info("You can now use this timeline to test the MCP server features.")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
