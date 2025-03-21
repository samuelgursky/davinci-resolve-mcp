#!/usr/bin/env python
"""
Test script for DaVinci Resolve Timeline Functions

This script tests the fixed timeline functions:
- mcp_create_timeline
- mcp_duplicate_timeline 
- mcp_delete_timeline
"""

import sys
import os
import time
from typing import Dict, Any

# Add the src directory to the Python path
src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
sys.path.append(src_dir)

# Import the timeline functions
try:
    from davinci_resolve_timeline import (
        get_resolve_instance,
        mcp_create_timeline,
        mcp_duplicate_timeline,
        mcp_delete_timeline,
        mcp_set_current_timeline
    )
except ImportError as e:
    print(f"Error importing timeline functions: {e}")
    sys.exit(1)

def print_result(function_name: str, result: Dict[str, Any]) -> None:
    """Print the result of a function call in a formatted way"""
    print("\n" + "=" * 50)
    print(f"FUNCTION: {function_name}")
    print("-" * 50)
    
    if "error" in result:
        print(f"ERROR: {result['error']}")
    elif "status" in result and result["status"] == "success":
        print(f"SUCCESS: {result.get('message', 'Operation completed successfully')}")
        
        # Print additional information if available
        if "timeline_info" in result:
            print("\nTIMELINE INFO:")
            for key, value in result["timeline_info"].items():
                print(f"  {key}: {value}")
    else:
        print("RESULT:")
        for key, value in result.items():
            print(f"  {key}: {value}")
    
    print("=" * 50)

def run_tests():
    """Run tests for the timeline functions"""
    # Check if DaVinci Resolve is running
    resolve = get_resolve_instance()
    if not resolve:
        print("ERROR: DaVinci Resolve is not running. Please start DaVinci Resolve and try again.")
        sys.exit(1)
    
    print("DaVinci Resolve is running. Starting tests...\n")
    
    # Test timeline names
    base_name = "Test Timeline"
    test_timeline_name = f"{base_name} {int(time.time())}"
    duplicate_timeline_name = f"{test_timeline_name} - Copy"
    
    # Test 1: Create a new timeline
    print("TEST 1: Creating a new timeline...")
    create_result = mcp_create_timeline(test_timeline_name)
    print_result("mcp_create_timeline", create_result)
    
    if "error" in create_result:
        print("Failed to create timeline. Stopping tests.")
        return
    
    # Wait a moment to allow Resolve to process
    time.sleep(1)
    
    # Test 2: Duplicate the timeline
    print("\nTEST 2: Duplicating the timeline...")
    duplicate_result = mcp_duplicate_timeline(test_timeline_name, duplicate_timeline_name)
    print_result("mcp_duplicate_timeline", duplicate_result)
    
    # Wait a moment to allow Resolve to process
    time.sleep(1)
    
    # Test 3: Delete the duplicate timeline
    print("\nTEST 3: Deleting the duplicate timeline...")
    delete_duplicate_result = mcp_delete_timeline(duplicate_timeline_name)
    print_result("mcp_delete_timeline", delete_duplicate_result)
    
    # Wait a moment to allow Resolve to process
    time.sleep(1)
    
    # Test 4: Delete the original timeline
    print("\nTEST 4: Deleting the original timeline...")
    delete_original_result = mcp_delete_timeline(test_timeline_name)
    print_result("mcp_delete_timeline", delete_original_result)
    
    print("\nAll tests completed.")

if __name__ == "__main__":
    run_tests() 