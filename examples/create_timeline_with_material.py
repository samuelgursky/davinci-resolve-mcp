#!/usr/bin/env python

from datetime import datetime
import sys
import os

# Add the current directory to the path so we can import modules
sys.path.append('.')

# Import functions from src.resolve_mcp
from src.resolve_mcp import get_current_project, get_media_pool, get_media_pool_items

def create_timeline_with_all_material():
    """Create a new timeline with all material and 10 seconds before each clip"""
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
            
        # Generate timeline name with today's date
        timeline_name = f"All_Material_{datetime.now().strftime('%Y-%m-%d')}"
        
        # Create a new timeline
        timeline = media_pool.CreateEmptyTimeline(timeline_name)
        if not timeline:
            print(f"Error: Failed to create timeline '{timeline_name}'")
            return
            
        print(f"Successfully created timeline: {timeline_name}")
        
        # Make sure the new timeline is the current one
        project.SetCurrentTimeline(timeline)
        
        # Get all media items
        media_items = get_media_pool_items()
        if not media_items:
            print("No media items found in the media pool")
            return
            
        print(f"Found {len(media_items)} media items")
        
        # Add media items to timeline with 10 seconds gap
        frame_position = 240  # Start at 10 seconds (24fps * 10)
        
        # Get all actual media clips (not timelines, etc.)
        actual_clips = []
        for item in media_items:
            media_item_name = item.get('name', '')
            if item.get('type') == 'clip' and media_item_name != timeline_name:
                actual_clips.append(item)
        
        print(f"Found {len(actual_clips)} actual media clips to add to timeline")
        
        # Add each clip to the timeline with 10 seconds gap
        for item in actual_clips:
            media_item_name = item.get('name', '')
            print(f"Adding clip: {media_item_name}")
            
            # Find the actual media pool item
            media_item = None
            media_pool_items = media_pool.GetRootFolder().GetClipList()
            
            for mpi in media_pool_items or []:
                if mpi.GetName() == media_item_name:
                    media_item = mpi
                    break
            
            if not media_item:
                print(f"Could not find media item: {media_item_name}")
                continue
                
            # Add the clip to the timeline
            result = timeline.AppendToTimeline([{'mediaPoolItem': media_item}])
            if not result:
                print(f"Failed to add clip: {media_item_name}")
            else:
                print(f"Successfully added clip: {media_item_name}")
            
            # Move to next position (240 frames = 10 seconds at 24fps)
            frame_position += 240
            
        print(f"Timeline creation completed: {timeline_name}")
        return timeline_name
        
    except Exception as e:
        print(f"Error creating timeline with materials: {str(e)}")
        return None

if __name__ == "__main__":
    timeline_name = create_timeline_with_all_material()
    if timeline_name:
        print(f"Successfully created and populated timeline: {timeline_name}")
    else:
        print("Failed to create timeline with materials") 