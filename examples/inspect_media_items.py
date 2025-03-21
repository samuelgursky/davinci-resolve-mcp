#!/usr/bin/env python

import sys
import os
import json

# Add the current directory to the path so we can import modules
sys.path.append('.')

# Import functions from src.resolve_mcp
from src.resolve_mcp import get_current_project, get_media_pool, get_media_pool_items

def inspect_media_items():
    """Inspect media items in the media pool in more detail"""
    try:
        # Get the current project
        project = get_current_project()
        if not project:
            print("Error: No project is currently open")
            return
            
        # Get the media pool
        media_pool = get_media_pool()
        if not media_pool:
            print("Error: Could not access media pool")
            return
            
        # Get all media items
        media_items = get_media_pool_items()
        if not media_items:
            print("No media items found in the media pool")
            return
            
        print(f"Found {len(media_items)} media items:")
        
        # Print detailed information about each item
        for index, item in enumerate(media_items):
            print(f"\nItem {index+1}:")
            for key, value in item.items():
                if isinstance(value, dict):
                    print(f"  {key}:")
                    for subkey, subvalue in value.items():
                        print(f"    {subkey}: {subvalue}")
                else:
                    print(f"  {key}: {value}")
        
        # Also try to get media pool items directly from the Resolve API
        root_folder = media_pool.GetRootFolder()
        if not root_folder:
            print("\nCould not access root folder")
            return
            
        clip_list = root_folder.GetClipList()
        print(f"\nDirect API - Found {len(clip_list) if clip_list else 0} clips in root folder:")
        
        if clip_list:
            for index, clip in enumerate(clip_list):
                try:
                    print(f"Clip {index+1}:")
                    print(f"  Name: {clip.GetName()}")
                    print(f"  Duration: {clip.GetDuration()}")
                    
                    # Try to get clip properties
                    try:
                        properties = clip.GetClipProperty()
                        if properties:
                            print("  Properties:")
                            for prop_key, prop_value in properties.items():
                                print(f"    {prop_key}: {prop_value}")
                    except Exception as prop_e:
                        print(f"  Error getting properties: {str(prop_e)}")
                        
                except Exception as clip_e:
                    print(f"  Error inspecting clip {index+1}: {str(clip_e)}")
        
        # Get all timelines
        timelines = project.GetTimelineCount()
        print(f"\nFound {timelines} timelines in project")
        
        for i in range(timelines):
            timeline = project.GetTimelineByIndex(i+1)
            if timeline:
                print(f"Timeline {i+1}: {timeline.GetName()}")
        
    except Exception as e:
        print(f"Error inspecting media items: {str(e)}")

if __name__ == "__main__":
    inspect_media_items() 