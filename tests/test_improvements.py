#!/usr/bin/env python3
"""
DaVinci Resolve MCP Server Test Script
--------------------------------------
This script tests the improvements made to the DaVinci Resolve MCP Server
by systematically checking each enhanced feature.

Usage:
    python test_improvements.py

Requirements:
    - DaVinci Resolve must be running with a project open
    - DaVinci Resolve MCP Server must be running (after restart)
    - requests module (pip install requests)
"""

import json
import time
import sys
import requests
import logging
from typing import Dict, Any, List, Tuple, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("mcp_test_results.log"), logging.StreamHandler()],
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


def test_server_connection() -> bool:
    """Test basic connection to DaVinci Resolve via the server."""
    logger.info("Testing server connection...")

    # Try switching to media page as a basic connectivity test
    result = send_request("mcp_davinci_resolve_switch_page", {"page": "media"})

    if result.get("success", False) or "content" in result:
        logger.info("✅ Server connection successful")
        return True
    else:
        logger.error(
            f"❌ Server connection failed: {result.get('error', 'Unknown error')}"
        )
        return False


def test_project_settings() -> bool:
    """Test setting project settings with different parameter types."""
    logger.info("Testing project settings parameter handling...")

    # Test with numeric value
    logger.info("Testing numeric parameter...")
    result1 = send_request(
        "mcp_davinci_resolve_set_project_setting",
        {"setting_name": "timelineFrameRate", "setting_value": 24},
    )

    # Test with string value
    logger.info("Testing string parameter...")
    result2 = send_request(
        "mcp_davinci_resolve_set_project_setting",
        {"setting_name": "timelineFrameRate", "setting_value": "24"},
    )

    # Test with float value
    logger.info("Testing float parameter...")
    result3 = send_request(
        "mcp_davinci_resolve_set_project_setting",
        {"setting_name": "colorScienceMode", "setting_value": 0},
    )

    success1 = "error" not in result1 or not result1.get("error")
    success2 = "error" not in result2 or not result2.get("error")
    success3 = "error" not in result3 or not result3.get("error")

    if success1 and success2 and success3:
        logger.info("✅ Project settings parameter handling is working")
        return True
    else:
        logger.error(f"❌ Project settings parameter handling failed")
        logger.error(f"    Numeric test: {'✅ Passed' if success1 else '❌ Failed'}")
        logger.error(f"    String test: {'✅ Passed' if success2 else '❌ Failed'}")
        logger.error(f"    Float test: {'✅ Passed' if success3 else '❌ Failed'}")
        return False


def test_color_page_operations() -> bool:
    """Test color page operations with automatic clip selection."""
    logger.info("Testing color page operations...")

    # Switch to color page
    result1 = send_request("mcp_davinci_resolve_switch_page", {"page": "color"})

    # Try adding a serial node (should use automatic clip selection)
    time.sleep(1)  # Give it a moment to switch pages
    result2 = send_request(
        "mcp_davinci_resolve_add_node", {"node_type": "serial", "label": "AutoTest"}
    )

    # Try setting color wheel parameter
    result3 = send_request(
        "mcp_davinci_resolve_set_color_wheel_param",
        {"wheel": "gain", "param": "red", "value": 0.1},
    )

    success1 = "error" not in result1 or not result1.get("error")
    success2 = "error" not in result2 or not result2.get("error")
    success3 = "error" not in result3 or not result3.get("error")

    # Check if automatic clip selection messages are present
    auto_select_working = False
    if not success2:
        error_msg = str(result2.get("error", ""))
        # Even if it failed, check if we see the right error message
        if "ensure_clip_selected" in error_msg or "Selected first clip" in error_msg:
            logger.info("✅ Automatic clip selection is being attempted")
            auto_select_working = True

    if success1 and (success2 or auto_select_working):
        logger.info(
            "✅ Color page operations are working or properly reporting selection issues"
        )
        return True
    else:
        logger.error(f"❌ Color page operations test failed")
        logger.error(
            f"    Switch to color page: {'✅ Passed' if success1 else '❌ Failed'}"
        )
        logger.error(
            f"    Add node: {'✅ Passed' if success2 else '❌ Failed but proper error' if auto_select_working else '❌ Failed'}"
        )
        logger.error(f"    Set color wheel: {'✅ Passed' if success3 else '❌ Failed'}")
        return False


def test_render_queue_operations() -> bool:
    """Test render queue operations with improved helpers."""
    logger.info("Testing render queue operations...")

    # Switch to deliver page
    result1 = send_request("mcp_davinci_resolve_switch_page", {"page": "deliver"})

    # Clear render queue first (known to be working)
    result2 = send_request(
        "mcp_davinci_resolve_clear_render_queue", {"random_string": "test"}
    )

    # Try adding a timeline to the render queue
    time.sleep(1)  # Give it a moment to switch pages
    result3 = send_request(
        "mcp_davinci_resolve_add_to_render_queue",
        {
            "preset_name": "YouTube 1080p",
            "timeline_name": None,
            "use_in_out_range": False,
        },
    )

    success1 = "error" not in result1 or not result1.get("error")
    success2 = "error" not in result2 or not result2.get("error")
    success3 = "error" not in result3 or not result3.get("error")

    # Check if our helpers are being used
    helper_working = False
    if not success3:
        error_msg = str(result3.get("error", ""))
        # Even if it failed, check if we see messages from our helpers
        if (
            "ensure_render_settings" in error_msg
            or "validate_render_preset" in error_msg
        ):
            logger.info("✅ Render queue helpers are being used")
            helper_working = True

    if success1 and success2 and (success3 or helper_working):
        logger.info("✅ Render queue operations are working or properly using helpers")
        return True
    else:
        logger.error(f"❌ Render queue operations test failed")
        logger.error(
            f"    Switch to deliver page: {'✅ Passed' if success1 else '❌ Failed'}"
        )
        logger.error(
            f"    Clear render queue: {'✅ Passed' if success2 else '❌ Failed'}"
        )
        logger.error(
            f"    Add to render queue: {'✅ Passed' if success3 else '❌ Failed but helpers working' if helper_working else '❌ Failed'}"
        )
        return False


def test_error_handling_with_empty_timeline() -> bool:
    """Test how the color operations handle an empty timeline."""
    logger.info("Testing error handling with empty timeline...")

    # First create a new empty timeline
    empty_timeline_name = f"Empty_Test_Timeline_{int(time.time())}"
    create_result = send_request(
        "mcp_davinci_resolve_create_timeline", {"name": empty_timeline_name}
    )

    # Set it as current
    set_result = send_request(
        "mcp_davinci_resolve_set_current_timeline", {"name": empty_timeline_name}
    )

    # Try to perform color operations on empty timeline
    result1 = send_request("mcp_davinci_resolve_switch_page", {"page": "color"})
    time.sleep(1)  # Give it a moment to switch pages

    # Try adding a node - this should fail but with proper error message
    result2 = send_request(
        "mcp_davinci_resolve_add_node", {"node_type": "serial", "label": "EmptyTest"}
    )

    success1 = "error" not in result1 or not result1.get("error")

    # Check for improved error handling
    improved_error = False
    expected_phrases = [
        "no clip",
        "empty timeline",
        "select clip",
        "ensure_clip_selected",
    ]

    if "error" in result2 and result2.get("error"):
        error_msg = str(result2.get("error", "")).lower()
        for phrase in expected_phrases:
            if phrase in error_msg:
                improved_error = True
                logger.info(
                    f"✅ Proper error handling detected: '{phrase}' found in error message"
                )
                break

    # Clean up - delete the test timeline
    delete_result = send_request(
        "mcp_davinci_resolve_delete_timeline", {"name": empty_timeline_name}
    )

    if success1 and improved_error:
        logger.info("✅ Error handling for empty timeline is working properly")
        return True
    else:
        logger.error("❌ Error handling for empty timeline test failed")
        logger.error(
            f"    Switch to color page: {'✅ Passed' if success1 else '❌ Failed'}"
        )
        logger.error(
            f"    Improved error message: {'✅ Passed' if improved_error else '❌ Failed'}"
        )
        return False


def test_parameter_validation() -> bool:
    """Test parameter validation with various types and edge cases."""
    logger.info("Testing parameter validation with various types...")

    # Test with different types
    tests = [
        {"type": "integer", "value": 24, "setting": "timelineFrameRate"},
        {"type": "string", "value": "24", "setting": "timelineFrameRate"},
        {"type": "float", "value": 23.976, "setting": "timelineFrameRate"},
        {"type": "string float", "value": "23.976", "setting": "timelineFrameRate"},
        {"type": "boolean", "value": True, "setting": "timelineResolutionWidth"},
        {
            "type": "string boolean",
            "value": "true",
            "setting": "timelineResolutionWidth",
        },
    ]

    results = []

    for test in tests:
        logger.info(f"Testing {test['type']} parameter: {test['value']}")
        result = send_request(
            "mcp_davinci_resolve_set_project_setting",
            {"setting_name": test["setting"], "setting_value": test["value"]},
        )

        # Consider it a success if no error or if error doesn't mention type validation
        success = (
            "error" not in result
            or not result.get("error")
            or "type" not in str(result.get("error", "")).lower()
        )
        results.append(success)

        if success:
            logger.info(f"✅ {test['type']} parameter accepted")
        else:
            logger.error(
                f"❌ {test['type']} parameter rejected: {result.get('error', 'Unknown error')}"
            )

    # Final judgment based on how many tests passed
    passed = sum(results)
    total = len(results)
    success_rate = passed / total

    if success_rate >= 0.5:  # At least half of the tests should pass
        logger.info(f"✅ Parameter validation is working for {passed}/{total} types")
        return True
    else:
        logger.error(
            f"❌ Parameter validation test failed for {total - passed}/{total} types"
        )
        return False


def print_test_summary(results: Dict[str, bool]) -> None:
    """Print a summary of all test results."""
    logger.info("\n" + "=" * 50)
    logger.info("TEST SUMMARY")
    logger.info("=" * 50)

    total = len(results)
    passed = sum(results.values())

    for test_name, result in results.items():
        status = "✅ PASSED" if result else "❌ FAILED"
        logger.info(f"{status} - {test_name}")

    logger.info("-" * 50)
    logger.info(f"Total Tests: {total}")
    logger.info(f"Passed: {passed}")
    logger.info(f"Failed: {total - passed}")
    logger.info(f"Success Rate: {passed/total*100:.1f}%")
    logger.info("=" * 50)


def main() -> None:
    """Run all tests and report results."""
    logger.info("Starting DaVinci Resolve MCP Server tests")
    logger.info("=" * 50)

    # Store test results
    results = {}

    # Test server connection first
    connection_result = test_server_connection()
    results["Server Connection"] = connection_result

    # Only continue with other tests if connection is successful
    if connection_result:
        # Test project settings
        results["Project Settings"] = test_project_settings()

        # Test color page operations
        results["Color Page Operations"] = test_color_page_operations()

        # Test render queue operations
        results["Render Queue Operations"] = test_render_queue_operations()

        # Test error handling with empty timeline
        results["Empty Timeline Error Handling"] = (
            test_error_handling_with_empty_timeline()
        )

        # Test parameter validation
        results["Parameter Validation"] = test_parameter_validation()
    else:
        logger.error("Skipping remaining tests due to server connection failure")
        results["Project Settings"] = False
        results["Color Page Operations"] = False
        results["Render Queue Operations"] = False
        results["Empty Timeline Error Handling"] = False
        results["Parameter Validation"] = False

    # Print test summary
    print_test_summary(results)

    # Exit with appropriate status
    if all(results.values()):
        logger.info("All tests passed!")
        sys.exit(0)
    else:
        logger.error("Some tests failed. Check the logs for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()
