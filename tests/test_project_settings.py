#!/usr/bin/env python
"""
Test script for DaVinci Resolve Project Settings Functions

This script tests the fixed project and timeline settings functions:
- mcp_get_project_setting
- mcp_set_project_setting
- mcp_get_timeline_setting
- mcp_set_timeline_setting
"""

import sys
import os
import time
from typing import Dict, Any, Optional

# Add the src directory to the Python path
src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
sys.path.append(src_dir)

# Import the project settings functions
try:
    from davinci_resolve_project_settings import (
        get_resolve_instance,
        mcp_get_project_setting,
        mcp_set_project_setting,
        mcp_get_timeline_setting,
        mcp_set_timeline_setting
    )
except ImportError as e:
    print(f"Error importing project settings functions: {e}")
    sys.exit(1)

def print_result(function_name: str, result: Dict[str, Any]) -> None:
    """Print the result of a function call in a formatted way"""
    print("\n" + "=" * 70)
    print(f"FUNCTION: {function_name}")
    print("-" * 70)
    
    if "error" in result:
        print(f"ERROR: {result['error']}")
        
        # Print debug info if available
        if "debug_info" in result:
            print("\nDEBUG INFO:")
            for key, value in result["debug_info"].items():
                print(f"  {key}: {value}")
                
    elif "status" in result and result["status"] == "success":
        print(f"SUCCESS: {result.get('message', 'Operation completed successfully')}")
        
        # Print additional information if available
        if "old_value" in result and "new_value" in result:
            print(f"\nOld value: {result['old_value']}")
            print(f"New value: {result['new_value']}")
        elif "value" in result:
            print(f"\nValue: {result['value']}")
    else:
        print("RESULT:")
        for key, value in result.items():
            if key == "settings" and isinstance(value, dict):
                print("\nSETTINGS:")
                for setting_key, setting_value in value.items():
                    print(f"  {setting_key}: {setting_value}")
            else:
                print(f"  {key}: {value}")
    
    print("=" * 70)

def test_project_setting(setting_name: str, test_value: Any) -> None:
    """Test getting and setting a project setting"""
    print(f"\nTESTING PROJECT SETTING: {setting_name}")
    
    # Get current value
    get_result = mcp_get_project_setting(setting_name)
    print_result(f"mcp_get_project_setting({setting_name})", get_result)
    
    # Store current value to restore later
    current_value = get_result.get(setting_name)
    
    if current_value is None:
        print(f"WARNING: Could not retrieve current value for {setting_name}, skipping set test")
        return
    
    # Don't test if current value matches test value
    if str(current_value) == str(test_value):
        alternate_value = "24" if str(test_value) == "29.97" else "29.97"
        test_value = alternate_value
        print(f"Current value matches test value, using alternate test value: {test_value}")
    
    # Set to test value
    print(f"Setting {setting_name} to {test_value}...")
    set_result = mcp_set_project_setting(setting_name, test_value)
    print_result(f"mcp_set_project_setting({setting_name}, {test_value})", set_result)
    
    # Verify change
    verify_result = mcp_get_project_setting(setting_name)
    new_value = verify_result.get(setting_name)
    print(f"Verification: {setting_name} = {new_value}")
    
    # Restore original value
    print(f"Restoring {setting_name} to {current_value}...")
    restore_result = mcp_set_project_setting(setting_name, current_value)
    print_result(f"mcp_set_project_setting({setting_name}, {current_value}) (restore)", restore_result)

def test_timeline_setting(setting_name: str, test_value: Any, timeline_name: Optional[str] = None) -> None:
    """Test getting and setting a timeline setting"""
    print(f"\nTESTING TIMELINE SETTING: {setting_name}" + (f" on timeline '{timeline_name}'" if timeline_name else ""))
    
    # Get current value
    get_result = mcp_get_timeline_setting(timeline_name, setting_name)
    print_result(f"mcp_get_timeline_setting({timeline_name}, {setting_name})", get_result)
    
    # Store current value to restore later
    current_value = get_result.get(setting_name)
    
    if current_value is None:
        print(f"WARNING: Could not retrieve current value for {setting_name}, skipping set test")
        return
    
    # Don't test if current value matches test value
    if str(current_value) == str(test_value):
        if setting_name in ["useRollingShutter", "useSmoothOpticalFlow", "useSmartcache"]:
            # For boolean settings
            test_value = "0" if current_value == "1" else "1"
        else:
            # For other settings
            alternate_value = "24" if str(test_value) == "29.97" else "29.97"
            test_value = alternate_value
        print(f"Current value matches test value, using alternate test value: {test_value}")
    
    # Set to test value
    print(f"Setting {setting_name} to {test_value}...")
    set_result = mcp_set_timeline_setting(setting_name, test_value, timeline_name)
    print_result(f"mcp_set_timeline_setting({setting_name}, {test_value}, {timeline_name})", set_result)
    
    # Verify change
    verify_result = mcp_get_timeline_setting(timeline_name, setting_name)
    new_value = verify_result.get(setting_name)
    print(f"Verification: {setting_name} = {new_value}")
    
    # Restore original value
    print(f"Restoring {setting_name} to {current_value}...")
    restore_result = mcp_set_timeline_setting(setting_name, current_value, timeline_name)
    print_result(f"mcp_set_timeline_setting({setting_name}, {current_value}, {timeline_name}) (restore)", restore_result)

def get_current_timelines() -> list:
    """Get a list of current timeline names"""
    resolve = get_resolve_instance()
    if not resolve:
        return []
    
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return []
    
    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return []
    
    timeline_count = current_project.GetTimelineCount()
    timelines = []
    
    for i in range(1, timeline_count + 1):
        timeline = current_project.GetTimelineByIndex(i)
        if timeline:
            timelines.append(timeline.GetName())
    
    return timelines

def run_tests():
    """Run tests for the project settings functions"""
    # Check if DaVinci Resolve is running
    resolve = get_resolve_instance()
    if not resolve:
        print("ERROR: DaVinci Resolve is not running. Please start DaVinci Resolve and try again.")
        sys.exit(1)
    
    print("DaVinci Resolve is running. Starting tests...\n")
    
    # Get project settings
    print("Getting all project settings...")
    all_project_settings = mcp_get_project_setting()
    
    # Project settings to test
    project_settings_to_test = [
        ("timelineFrameRate", "29.97"),  # Numeric setting
        ("timelineUseCustomSettings", "1"),  # Boolean setting
        ("colorScienceMode", "davinciYRGB")  # Enum setting
    ]
    
    # Test project settings
    for setting_name, test_value in project_settings_to_test:
        test_project_setting(setting_name, test_value)
    
    # Get current timelines
    timelines = get_current_timelines()
    print(f"\nFound timelines: {timelines}")
    
    # Get current timeline
    current_timeline = None
    if timelines:
        current_timeline = timelines[0]
    
    # Timeline settings to test
    timeline_settings_to_test = [
        ("frameRate", "24"),  # Numeric setting 
        ("useRollingShutter", "1"),  # Boolean setting
        ("superscaleMethod", "Sharp")  # Enum setting (may not work)
    ]
    
    # Test timeline settings
    if current_timeline:
        for setting_name, test_value in timeline_settings_to_test:
            test_timeline_setting(setting_name, test_value, current_timeline)
    else:
        print("\nWARNING: No timeline found, skipping timeline setting tests")
    
    print("\nAll tests completed.")

if __name__ == "__main__":
    run_tests() 