#!/usr/bin/env python

from datetime import datetime
import sys
import os

# Add the current directory to the path so we can import modules
sys.path.append('.')

# Import functions from src.resolve_mcp
from src.resolve_mcp import get_current_project, get_media_pool, get_media_pool_items

def create_timeline_with_still():
    """Create a new timeline with still images, adding 10 seconds before each"""
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
        timeline_name = f"Stills_Timeline_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
        
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
        
        # Get still images
        still_images = []
        for item in media_items:
            media_item_name = item.get('name', '')
            if item.get('type') == 'Still':
                still_images.append(item)
        
        if not still_images:
            print("No still images found in the media pool")
            return
            
        print(f"Found {len(still_images)} still images to add to timeline")
        
        # Get root folder to access clips directly
        root_folder = media_pool.GetRootFolder()
        if not root_folder:
            print("Could not access root folder")
            return
            
        clip_list = root_folder.GetClipList()
        if not clip_list:
            print("Could not get clip list from root folder")
            return
            
        # Find the still image in the clip list
        still_image_clips = []
        for clip in clip_list:
            clip_name = clip.GetName()
            # Match with the names from our still_images list
            for still in still_images:
                if clip_name == still.get('name'):
                    still_image_clips.append(clip)
                    break
        
        if not still_image_clips:
            print("Could not find still image clips in the media pool")
            return
            
        print(f"Found {len(still_image_clips)} still image clips to add to timeline")
        
        # For each still image, add it multiple times with 10-second gaps
        for i, clip in enumerate(still_image_clips):
            clip_name = clip.GetName()
            print(f"Adding still image: {clip_name}")
            
            # Add the still 3 times with 10-second gaps (240 frames at 24fps)
            for j in range(3):
                # Calculate position: 10 seconds before (for first clip) + 10 seconds between clips
                frame_position = (i * 720) + (j * 240)  # 720 frames = 30 seconds per image (3 repetitions)
                
                # For the first clip of each image, add 10 seconds before
                if j == 0:
                    # Add 10 seconds of gap before the clip
                    print(f"  Adding clip {j+1} at position {frame_position + 240} (with 10s gap)")
                    result = media_pool.AppendToTimeline([{'mediaPoolItem': clip, 'startFrame': 0, 'endFrame': 1}])
                else:
                    print(f"  Adding clip {j+1} at next position")
                    result = media_pool.AppendToTimeline([{'mediaPoolItem': clip, 'startFrame': 0, 'endFrame': 1}])
                
                if not result:
                    print(f"  Failed to add clip {j+1}")
                else:
                    print(f"  Successfully added clip {j+1}")
            
        print(f"Timeline creation completed: {timeline_name}")
        return timeline_name
        
    except Exception as e:
        print(f"Error creating timeline with still images: {str(e)}")
        return None

if __name__ == "__main__":
    timeline_name = create_timeline_with_still()
    if timeline_name:
        print(f"Successfully created and populated timeline: {timeline_name}")
    else:
        print("Failed to create timeline with still images") 