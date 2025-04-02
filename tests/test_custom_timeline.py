#!/usr/bin/env python3
"""
DaVinci Resolve MCP Server Test Script for Custom Timeline Creation
------------------------------------------------------------------
This script tests the enhanced CreateEmptyTimeline function with custom parameters.

Usage:
    python test_custom_timeline.py

Requirements:
    - DaVinci Resolve must be running with a project open
    - DaVinci Resolve MCP Server must be running (after restart)
    - requests module (pip install requests)
"""

import sys
import time
import requests
import logging
from typing import Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("custom_timeline_test.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# Server configuration
SERVER_URL = "http://localhost:8000/api"


def send_request(tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Send a request to the MCP server."""
    try:
        payload = {"tool": tool_name, "params": params}
        logger.info(f"Sending request: {tool_name} with params {params}")
        response = requests.post(SERVER_URL, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {e}")
        return {"success": False, "error": str(e)}


def test_basic_timeline_creation():
    """Test basic timeline creation."""
    logger.info("Testing basic timeline creation...")

    # Create a test timeline with default settings
    timeline_name = f"Basic_Test_Timeline_{int(time.time())}"
    result = send_request(
        "mcp_davinci_resolve_create_timeline", {"name": timeline_name}
    )

    if "error" in result and result.get("error"):
        logger.error(f"❌ Basic timeline creation failed: {result.get('error')}")
        return False
    else:
        logger.info(f"✅ Basic timeline created: {timeline_name}")
        return True


def test_custom_timeline_creation():
    """Test enhanced timeline creation with custom parameters."""
    logger.info("Testing custom timeline creation...")

    # Create a custom timeline with specific parameters
    timeline_name = f"Custom_Test_Timeline_{int(time.time())}"
    params = {
        "name": timeline_name,
        "frame_rate": "23.976",
        "resolution_width": 3840,
        "resolution_height": 2160,
        "start_timecode": "01:00:00:00",
    }

    result = send_request("mcp_davinci_resolve_create_empty_timeline", params)

    if "error" in result and result.get("error"):
        logger.error(f"❌ Custom timeline creation failed: {result.get('error')}")
        return False
    else:
        logger.info(f"✅ Custom timeline created with parameters: {params}")

        # Verify the timeline settings
        logger.info("Retrieving timeline info to verify settings...")

        # Switch to the created timeline
        switch_result = send_request(
            "mcp_davinci_resolve_set_current_timeline", {"name": timeline_name}
        )
        if "error" in switch_result and switch_result.get("error"):
            logger.error(
                f"❌ Failed to switch to timeline: {switch_result.get('error')}"
            )
            return False

        # Get timeline info
        get_timeline_result = send_request(
            "mcp_davinci_resolve_get_current_timeline", {}
        )
        if "error" in get_timeline_result or not isinstance(get_timeline_result, dict):
            logger.error(f"❌ Failed to get timeline info: {get_timeline_result}")
            return False

        # Verify settings
        resolution = get_timeline_result.get("resolution", {})

        logger.info(f"Timeline info: {get_timeline_result}")
        logger.info(f"Resolution: {resolution}")
        logger.info(f"Framerate: {get_timeline_result.get('framerate')}")
        logger.info(f"Start timecode: {get_timeline_result.get('start_timecode')}")

        return True


def main():
    """Run the timeline creation tests."""
    logger.info("Starting DaVinci Resolve MCP custom timeline creation tests")
    logger.info("=" * 60)

    # Run tests
    basic_result = test_basic_timeline_creation()
    custom_result = test_custom_timeline_creation()

    # Summary
    logger.info("=" * 60)
    logger.info(
        f"Basic timeline creation: {'✅ PASSED' if basic_result else '❌ FAILED'}"
    )
    logger.info(
        f"Custom timeline creation: {'✅ PASSED' if custom_result else '❌ FAILED'}"
    )
    logger.info("=" * 60)

    # Exit with appropriate code
    if basic_result and custom_result:
        logger.info("All tests passed!")
        sys.exit(0)
    else:
        logger.error("Some tests failed. Check the logs for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()
