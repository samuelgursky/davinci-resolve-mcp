#!/usr/bin/env python3
"""
Script to get the source directories of all clips in the DaVinci Resolve media pool.
"""

import os
import sys
import json
from pathlib import Path

# Set up environment variables for DaVinci Resolve API
resolve_api_path = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
resolve_module_path = os.path.join(resolve_api_path, "Modules")

# Add module path to sys.path
if resolve_module_path not in sys.path:
    sys.path.append(resolve_module_path)

try:
    import DaVinciResolveScript as dvr_script
except ImportError:
    print("Could not find DaVinciResolveScript module, check the install location.")
    sys.exit(1)

def get_resolve_instance():
    """Get the resolve instance."""
    return dvr_script.scriptapp("Resolve")

def process_clips_in_folder(folder, output_list, include_sub_folders=True):
    """Process all clips in a folder and optionally its subfolders."""
    # Get clips in current folder
    clips = folder.GetClipList()
    
    if clips:
        for clip in clips:
            try:
                file_path = clip.GetClipProperty("File Path")
                if file_path:
                    source_dir = os.path.dirname(file_path)
                    output_list.append({
                        "clip_name": clip.GetName(),
                        "source_path": file_path,
                        "source_directory": source_dir,
                        "folder_name": folder.GetName()
                    })
            except Exception as e:
                print(f"Error processing clip {clip.GetName()}: {e}")
    
    # Process subfolders if requested
    if include_sub_folders:
        sub_folders = folder.GetSubFolderList()
        if sub_folders:
            for sub_folder in sub_folders:
                process_clips_in_folder(sub_folder, output_list, True)

def main():
    """Main function to get all clip source directories."""
    resolve = get_resolve_instance()
    if not resolve:
        print("Error: Could not connect to DaVinci Resolve.")
        return
    
    project_manager = resolve.GetProjectManager()
    project = project_manager.GetCurrentProject()
    
    if not project:
        print("Error: No project is currently open.")
        return
    
    print(f"Current project: {project.GetName()}")
    
    media_pool = project.GetMediaPool()
    if not media_pool:
        print("Error: Could not access media pool.")
        return
    
    root_folder = media_pool.GetRootFolder()
    if not root_folder:
        print("Error: Could not access the root folder.")
        return
    
    # Get all clips and their source directories
    all_clips = []
    process_clips_in_folder(root_folder, all_clips)
    
    # Organize results by source directory
    source_dirs = {}
    for clip in all_clips:
        source_dir = clip["source_directory"]
        if source_dir not in source_dirs:
            source_dirs[source_dir] = []
        source_dirs[source_dir].append(clip["clip_name"])
    
    # Print results
    print("\nSource directories and clips:")
    print("=============================\n")
    
    for source_dir, clips in source_dirs.items():
        print(f"Source Directory: {source_dir}")
        print(f"Number of clips: {len(clips)}")
        print("Clips:")
        for clip in clips:
            print(f"  - {clip}")
        print("\n")
    
    # Output as JSON for programmatic use
    with open("media_sources.json", "w") as f:
        json.dump(
            {
                "source_directories": [
                    {"path": path, "clip_count": len(clips), "clips": clips}
                    for path, clips in source_dirs.items()
                ]
            },
            f,
            indent=2
        )
    
    print(f"Results saved to media_sources.json")
    
    # Summary
    print(f"\nSummary:")
    print(f"Total unique source directories: {len(source_dirs)}")
    print(f"Total clips: {len(all_clips)}")

if __name__ == "__main__":
    main() 