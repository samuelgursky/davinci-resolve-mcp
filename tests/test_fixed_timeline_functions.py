#!/usr/bin/env python3
"""
Test Script for Fixed Timeline Functions

This script tests the improved timeline deletion and duplication functions,
validating their ability to handle different scenarios and errors.
"""

import sys
import os
import time
import json
import logging
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f"timeline_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Add parent directory to path
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
sys.path.append(parent_dir)

# Import the fixed functions
try:
    from src.fixed_timeline_functions import (
        get_resolve_instance, get_project_manager, get_current_project,
        list_all_timelines, fixed_delete_timeline, fixed_duplicate_timeline
    )
except ImportError:
    logger.error("Could not import fixed timeline functions")
    sys.exit(1)

def print_result(result):
    """Print a result dictionary with consistent formatting"""
    if isinstance(result, dict):
        logger.info(json.dumps(result, indent=2))
    else:
        logger.info(result)

def create_test_timeline(name="Test Timeline"):
    """Create a new timeline for testing"""
    logger.info(f"Creating test timeline: {name}")
    
    project = get_current_project()
    if not project:
        logger.error("No project is open")
        return None
    
    media_pool = project.GetMediaPool()
    if not media_pool:
        logger.error("Could not access media pool")
        return None
    
    # Check if timeline with this name already exists
    timelines = list_all_timelines(project)
    for timeline in timelines:
        if timeline["name"] == name:
            logger.info(f"Timeline '{name}' already exists, using existing timeline")
            return timeline["object"]
    
    # Create new timeline
    new_timeline = media_pool.CreateEmptyTimeline(name)
    if not new_timeline:
        logger.error(f"Failed to create timeline: {name}")
        return None
    
    logger.info(f"Successfully created timeline: {name}")
    return new_timeline

def test_duplicate_timeline():
    """Test the duplicate timeline function"""
    logger.info("\n=== TESTING TIMELINE DUPLICATION ===")
    
    # Create a test timeline
    source_name = f"Source Timeline {datetime.now().strftime('%H%M%S')}"
    source_timeline = create_test_timeline(source_name)
    if not source_timeline:
        logger.error("Could not create source timeline for duplication test")
        return False
    
    # Wait for a moment to ensure the timeline is properly created
    time.sleep(1)
    
    # Test duplicate with a new name
    dup_name = f"Duplicated Timeline {datetime.now().strftime('%H%M%S')}"
    logger.info(f"Duplicating timeline '{source_name}' to '{dup_name}'")
    
    result = fixed_duplicate_timeline(source_name, dup_name)
    print_result(result)
    
    success = result.get("status") == "success" or result.get("status") == "partial_success"
    
    # List timelines after duplication
    timelines = list_all_timelines()
    timeline_names = [t["name"] for t in timelines]
    logger.info(f"Timelines after duplication: {timeline_names}")
    
    # Check if the duplicate exists
    duplicate_exists = dup_name in timeline_names
    logger.info(f"Duplicate timeline exists: {duplicate_exists}")
    
    return success and duplicate_exists

def test_delete_timeline():
    """Test the delete timeline function"""
    logger.info("\n=== TESTING TIMELINE DELETION ===")
    
    # Create a test timeline
    del_name = f"Timeline to Delete {datetime.now().strftime('%H%M%S')}"
    timeline_to_delete = create_test_timeline(del_name)
    if not timeline_to_delete:
        logger.error("Could not create timeline for deletion test")
        return False
    
    # Wait for a moment to ensure the timeline is properly created
    time.sleep(1)
    
    # List timelines before deletion
    timelines_before = list_all_timelines()
    timeline_names_before = [t["name"] for t in timelines_before]
    logger.info(f"Timelines before deletion: {timeline_names_before}")
    
    # Test deletion
    logger.info(f"Deleting timeline: {del_name}")
    result = fixed_delete_timeline(del_name)
    print_result(result)
    
    success = result.get("status") == "success"
    
    # List timelines after deletion
    timelines_after = list_all_timelines()
    timeline_names_after = [t["name"] for t in timelines_after]
    logger.info(f"Timelines after deletion: {timeline_names_after}")
    
    # Check if the timeline is gone
    timeline_deleted = del_name not in timeline_names_after
    logger.info(f"Timeline was deleted: {timeline_deleted}")
    
    return success and timeline_deleted

def test_edge_cases():
    """Test edge cases like deleting non-existent timelines"""
    logger.info("\n=== TESTING EDGE CASES ===")
    
    # Test deleting a non-existent timeline
    non_existent = "ThisTimelineDoesNotExist12345"
    logger.info(f"Attempting to delete non-existent timeline: {non_existent}")
    result = fixed_delete_timeline(non_existent)
    print_result(result)
    
    # Test duplicating a non-existent timeline
    logger.info(f"Attempting to duplicate non-existent timeline: {non_existent}")
    result = fixed_duplicate_timeline(non_existent, "NewName")
    print_result(result)
    
    # Test duplicating to an existing name
    # First create two timelines
    name1 = f"First Timeline {datetime.now().strftime('%H%M%S')}"
    name2 = f"Second Timeline {datetime.now().strftime('%H%M%S')}"
    
    timeline1 = create_test_timeline(name1)
    timeline2 = create_test_timeline(name2)
    
    if timeline1 and timeline2:
        # Try to duplicate timeline1 with name2
        logger.info(f"Attempting to duplicate '{name1}' to existing name '{name2}'")
        result = fixed_duplicate_timeline(name1, name2)
        print_result(result)
        
        # Clean up these test timelines
        fixed_delete_timeline(name1)
        fixed_delete_timeline(name2)
    
    return True

def main():
    """Main test function"""
    logger.info("Starting test of fixed timeline functions")
    
    # Check if Resolve is running
    resolve = get_resolve_instance()
    if not resolve:
        logger.error("DaVinci Resolve is not running. Please open Resolve and try again.")
        return
    
    # Check if a project is open
    project = get_current_project()
    if not project:
        logger.error("No project is open in DaVinci Resolve. Please open a project and try again.")
        return
    
    logger.info(f"Current project: {project.GetName()}")
    
    # List current timelines
    timelines = list_all_timelines()
    timeline_names = [t["name"] for t in timelines]
    logger.info(f"Initial timelines: {timeline_names}")
    
    # Run tests
    duplicate_success = test_duplicate_timeline()
    logger.info(f"Duplication test {'PASSED' if duplicate_success else 'FAILED'}")
    
    delete_success = test_delete_timeline()
    logger.info(f"Deletion test {'PASSED' if delete_success else 'FAILED'}")
    
    edge_case_success = test_edge_cases()
    logger.info(f"Edge case tests {'PASSED' if edge_case_success else 'FAILED'}")
    
    # Overall results
    if duplicate_success and delete_success and edge_case_success:
        logger.info("All tests PASSED!")
    else:
        logger.warning("Some tests FAILED!")
    
    logger.info("Testing completed.")

if __name__ == "__main__":
    main() 