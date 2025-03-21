#!/usr/bin/env python3
"""
Example script to get and export a source timecode report for the current timeline.
"""

import sys
import os
import json

# Add the project directory to the sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.dirname(script_dir)
sys.path.append(project_dir)

try:
    # Import the timecode functions
    from src.timecode_functions.source_timecode import (
        get_resolve_instance,
        get_current_timeline,
        mcp_get_source_timecode_report,
        mcp_export_source_timecode_report
    )
except ImportError as e:
    print(f"Error importing timecode functions: {e}")
    sys.exit(1)

def main():
    """Main function that retrieves and exports source timecode report"""
    print("DaVinci Resolve Source Timecode Report")
    print("--------------------------------------")
    
    # Check if DaVinci Resolve is running
    resolve = get_resolve_instance()
    if not resolve:
        print("Error: DaVinci Resolve is not running.")
        return
    
    # Check if a timeline is open
    timeline = get_current_timeline()
    if not timeline:
        print("Error: No timeline is currently open in DaVinci Resolve.")
        return
    
    print(f"Current timeline: {timeline.GetName()}")
    print()
    
    # Get the source timecode report
    print("Generating source timecode report...")
    report = mcp_get_source_timecode_report()
    if "error" in report:
        print(f"Error: {report['error']}")
        return
    
    print(f"Timeline: {report['timeline_name']}")
    print(f"Number of clips: {len(report['clips'])}")
    print()
    
    # Create exports directory if it doesn't exist
    exports_dir = os.path.join(project_dir, "exports")
    if not os.path.exists(exports_dir):
        os.makedirs(exports_dir)
    
    # Export the report in different formats
    for format in ["csv", "json", "edl"]:
        export_path = os.path.join(exports_dir, f"source_timecode_report.{format}")
        print(f"Exporting report as {format.upper()} to: {export_path}")
        
        result = mcp_export_source_timecode_report(export_path, format)
        if "error" in result:
            print(f"  Error: {result['error']}")
        else:
            print(f"  Success: {result['message']}")
    
    print("\nReport generation complete!")

if __name__ == "__main__":
    main() 