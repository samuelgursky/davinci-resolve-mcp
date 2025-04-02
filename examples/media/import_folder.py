#!/usr/bin/env python3
"""
Script to import folder content, organize in a bin, and add to timeline
"""

import os
import sys
import glob

# Set environment variables for DaVinci Resolve scripting
RESOLVE_API_PATH = (
    "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
)
RESOLVE_LIB_PATH = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
RESOLVE_MODULES_PATH = os.path.join(RESOLVE_API_PATH, "Modules")

os.environ["RESOLVE_SCRIPT_API"] = RESOLVE_API_PATH
os.environ["RESOLVE_SCRIPT_LIB"] = RESOLVE_LIB_PATH

# Add the module path to Python's path if it's not already there
if RESOLVE_MODULES_PATH not in sys.path:
    sys.path.append(RESOLVE_MODULES_PATH)

import DaVinciResolveScript as dvr_script


def main():
    # Source folder path
    source_folder = "/Users/samuelgursky/Desktop/20250326"
    bin_name = os.path.basename(source_folder)

    print(f"Importing from folder: {source_folder}")
    print(f"Creating bin: {bin_name}")

    # Connect to Resolve
    print("Connecting to DaVinci Resolve...")
    resolve = dvr_script.scriptapp("Resolve")
    if not resolve:
        print("Error: Failed to connect to DaVinci Resolve")
        return

    print(f"Connected to: {resolve.GetProductName()} {resolve.GetVersionString()}")

    # Get project manager and current project
    project_manager = resolve.GetProjectManager()
    if not project_manager:
        print("Error: Failed to get Project Manager")
        return

    current_project = project_manager.GetCurrentProject()
    if not current_project:
        print("Error: No project currently open")
        return

    print(f"Current project: {current_project.GetName()}")

    # Get media pool
    media_pool = current_project.GetMediaPool()
    if not media_pool:
        print("Error: Failed to get Media Pool")
        return

    # Create a bin for the imported content
    root_folder = media_pool.GetRootFolder()
    print(f"Creating bin '{bin_name}'...")

    # Check if bin already exists
    existing_bins = root_folder.GetSubFolderList()
    target_bin = None

    for bin in existing_bins:
        if bin.GetName() == bin_name:
            target_bin = bin
            print(f"Bin '{bin_name}' already exists, using it")
            break

    # Create the bin if it doesn't exist
    if not target_bin:
        target_bin = media_pool.AddSubFolder(root_folder, bin_name)
        if not target_bin:
            print(f"Failed to create bin '{bin_name}', using root folder")
            target_bin = root_folder

    # Set the bin as the active folder
    media_pool.SetCurrentFolder(target_bin)

    # Import media from the folder
    print(f"Importing media from {source_folder}...")

    # Find all media files in the folder
    media_extensions = [
        ".mov",
        ".mp4",
        ".avi",
        ".mxf",
        ".wav",
        ".mp3",
        ".jpg",
        ".png",
        ".tif",
        ".exr",
    ]
    media_files = []

    for ext in media_extensions:
        media_files.extend(glob.glob(os.path.join(source_folder, f"*{ext}")))
        media_files.extend(glob.glob(os.path.join(source_folder, f"*{ext.upper()}")))

    if not media_files:
        print(f"No media files found in {source_folder}")
        # Try importing the folder directly
        print("Trying to import the folder directly...")
        imported_clips = media_pool.ImportMedia([source_folder])
        if not imported_clips or len(imported_clips) == 0:
            print("Failed to import any media")
            return
    else:
        print(f"Found {len(media_files)} media files")
        imported_clips = media_pool.ImportMedia(media_files)

        if not imported_clips or len(imported_clips) == 0:
            print("Failed to import media files")
            return

    print(f"Successfully imported {len(imported_clips)} clips")

    # Create a new timeline named after the folder
    timeline_name = f"{bin_name}_Timeline"
    print(f"Creating timeline '{timeline_name}'...")

    timeline = media_pool.CreateEmptyTimeline(timeline_name)
    if not timeline:
        print(f"Failed to create timeline '{timeline_name}'")
        return

    # Make sure the timeline is set as current
    current_project.SetCurrentTimeline(timeline)

    # Add all imported clips to the timeline
    print("Adding clips to timeline...")
    result = media_pool.AppendToTimeline(imported_clips)

    if result and len(result) > 0:
        print(f"Successfully added {len(result)} clips to timeline")
    else:
        print("Failed to add clips to timeline")

    print("Import process complete!")


if __name__ == "__main__":
    main()
