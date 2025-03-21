#!/usr/bin/env python3
"""
Unit tests for advanced media pool functions
"""
import os
import sys
import unittest
import json
from pathlib import Path

# Add the parent directory to sys.path to allow imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import the advanced media pool functions module
from src.media_pool_functions.advanced_media_pool import (
    get_folder_hierarchy,
    get_folder_by_path,
    create_folder_path,
    set_current_folder,
    get_current_folder,
    move_clips_between_folders,
    create_smart_bin,
    get_smart_bins,
    delete_smart_bin,
    bulk_set_clip_property,
    import_files_to_folder
)

# Mock configuration
USE_MOCKS = True  # Set to False to run tests against actual DaVinci Resolve

class MockClip:
    """Mock Clip for testing"""
    def __init__(self, name, clip_type="Video", duration=100):
        self.name = name
        self.type = clip_type
        self.duration = duration
        self.properties = {
            "Type": clip_type,
            "Resolution": "1920x1080",
            "Format": "H.264",
            "FrameRate": "24",
            "IsTimeline": "False",
            "Flags": "",
            "Keywords": "",
            "Comments": ""
        }
    
    def GetName(self):
        return self.name
    
    def GetDuration(self):
        return self.duration
    
    def GetClipProperty(self, name):
        return self.properties.get(name, "")
    
    def SetClipProperty(self, name, value):
        self.properties[name] = value
        return True

class MockFolder:
    """Mock Folder for testing"""
    def __init__(self, name, is_smart_bin=False):
        self.name = name
        self.is_smart_bin = is_smart_bin
        self.clips = []
        self.subfolders = []
    
    def GetName(self):
        return self.name
    
    def GetClipList(self):
        return self.clips
    
    def GetSubFolderList(self):
        return self.subfolders
    
    def AddClip(self, clip):
        self.clips.append(clip)
    
    def AddSubFolder(self, subfolder):
        self.subfolders.append(subfolder)
    
    def RemoveClip(self, clip):
        if clip in self.clips:
            self.clips.remove(clip)
            return True
        return False

class MockMediaPool:
    """Mock MediaPool for testing"""
    def __init__(self):
        self.root_folder = MockFolder("Master")
        self.current_folder = self.root_folder
        
        # Create some default folders
        self.footage_folder = MockFolder("Footage")
        self.audio_folder = MockFolder("Audio")
        self.root_folder.AddSubFolder(self.footage_folder)
        self.root_folder.AddSubFolder(self.audio_folder)
        
        # Create some default smart bins
        self.smart_bins = [
            MockFolder("All Clips", True),
            MockFolder("All Video Clips", True)
        ]
    
    def GetRootFolder(self):
        return self.root_folder
    
    def GetCurrentFolder(self):
        return self.current_folder
    
    def SetCurrentFolder(self, folder):
        self.current_folder = folder
        return True
    
    def AddSubFolder(self, parent_folder, name):
        new_folder = MockFolder(name)
        parent_folder.AddSubFolder(new_folder)
        return new_folder
    
    def GetFolderByName(self, name):
        # Check if smart bin
        for smart_bin in self.smart_bins:
            if smart_bin.GetName() == name:
                return smart_bin
        
        # Check if root folder
        if self.root_folder.GetName() == name:
            return self.root_folder
            
        # Check subfolders recursively
        def find_folder(folder, target_name):
            if folder.GetName() == target_name:
                return folder
                
            for subfolder in folder.GetSubFolderList():
                result = find_folder(subfolder, target_name)
                if result:
                    return result
                    
            return None
            
        return find_folder(self.root_folder, name)
    
    def MoveClips(self, clips, destination_folder):
        for clip in clips:
            # Remove from current location
            for folder in self._get_all_folders():
                folder.RemoveClip(clip)
            
            # Add to destination
            destination_folder.AddClip(clip)
        
        return True
    
    def CreateSmartBin(self, name, search_string):
        smart_bin = MockFolder(name, True)
        self.smart_bins.append(smart_bin)
        return True
    
    def DeleteSmartBin(self, name):
        for i, smart_bin in enumerate(self.smart_bins):
            if smart_bin.GetName() == name:
                del self.smart_bins[i]
                return True
        return False
    
    def DeleteFolder(self, folder):
        # Only handle deleting smart bins for simplicity
        if folder in self.smart_bins:
            self.smart_bins.remove(folder)
            return True
        return False
    
    def ImportMedia(self, file_paths):
        imported_clips = []
        for path in file_paths:
            clip_name = os.path.basename(path)
            clip = MockClip(clip_name)
            self.current_folder.AddClip(clip)
            imported_clips.append(clip)
        return imported_clips
    
    def _get_all_folders(self):
        """Helper to get all folders recursively"""
        all_folders = [self.root_folder]
        
        def collect_folders(folder):
            subfolders = folder.GetSubFolderList()
            all_folders.extend(subfolders)
            for subfolder in subfolders:
                collect_folders(subfolder)
        
        collect_folders(self.root_folder)
        return all_folders

class MockProject:
    """Mock Project for testing"""
    def __init__(self):
        self.media_pool = MockMediaPool()
    
    def GetMediaPool(self):
        return self.media_pool

class MockProjectManager:
    """Mock ProjectManager for testing"""
    def __init__(self):
        self.project = MockProject()
    
    def GetCurrentProject(self):
        return self.project

class MockResolve:
    """Mock Resolve for testing"""
    def __init__(self):
        self.project_manager = MockProjectManager()
    
    def GetProjectManager(self):
        return self.project_manager

# Global mock objects
mock_resolve = MockResolve()
mock_project_manager = mock_resolve.GetProjectManager()
mock_project = mock_project_manager.GetCurrentProject()
mock_media_pool = mock_project.GetMediaPool()
mock_root_folder = mock_media_pool.GetRootFolder()

# Override get_resolve if using mocks
if USE_MOCKS:
    import src.media_pool_functions.advanced_media_pool as advanced_media_pool
    advanced_media_pool.get_resolve = lambda: mock_resolve

class TestAdvancedMediaPoolFunctions(unittest.TestCase):
    """Tests for advanced media pool functions"""
    
    def setUp(self):
        """Setup for tests"""
        if USE_MOCKS:
            # Reset mocks for each test
            global mock_resolve, mock_project_manager, mock_project, mock_media_pool, mock_root_folder
            mock_resolve = MockResolve()
            mock_project_manager = mock_resolve.GetProjectManager()
            mock_project = mock_project_manager.GetCurrentProject()
            mock_media_pool = mock_project.GetMediaPool()
            mock_root_folder = mock_media_pool.GetRootFolder()
            
            # Override get_resolve
            advanced_media_pool.get_resolve = lambda: mock_resolve
            
            # Add some test clips to root folder
            for i in range(3):
                clip = MockClip(f"Test Clip {i+1}")
                mock_root_folder.AddClip(clip)
    
    def test_get_folder_hierarchy(self):
        """Test getting folder hierarchy"""
        result = get_folder_hierarchy()
        
        self.assertEqual(result["status"], "success")
        self.assertIn("hierarchy", result)
        self.assertEqual(result["hierarchy"]["name"], "Master")
        self.assertEqual(len(result["hierarchy"]["subfolders"]), 2)
        
        # Test with clips included
        result = get_folder_hierarchy(include_clips=True)
        self.assertIn("clip_count", result["hierarchy"])
        self.assertEqual(result["hierarchy"]["clip_count"], 3)
    
    def test_get_folder_by_path(self):
        """Test getting folder by path"""
        # Test root folder
        result = get_folder_by_path("")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["folder"]["name"], "Master")
        
        # Test subfolder
        result = get_folder_by_path("Footage")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["folder"]["name"], "Footage")
        
        # Test non-existent folder
        result = get_folder_by_path("NonExistentFolder")
        self.assertIn("error", result)
    
    def test_create_folder_path(self):
        """Test creating folder path"""
        result = create_folder_path("Footage/Scene1/Takes")
        
        self.assertEqual(result["status"], "success")
        
        # Verify folder was created
        result = get_folder_by_path("Footage/Scene1/Takes")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["folder"]["name"], "Takes")
    
    def test_set_current_folder(self):
        """Test setting current folder"""
        # Create a test folder first
        create_folder_path("Footage/Tests")
        
        # Set it as current
        result = set_current_folder("Footage/Tests")
        self.assertEqual(result["status"], "success")
        
        # Verify current folder
        result = get_current_folder()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["folder"]["name"], "Tests")
    
    def test_move_clips_between_folders(self):
        """Test moving clips between folders"""
        # Create folders
        create_folder_path("Source")
        create_folder_path("Destination")
        
        # Add clips to source folder
        source_folder = mock_media_pool.GetFolderByName("Source")
        for i in range(3):
            clip = MockClip(f"Move Clip {i+1}")
            source_folder.AddClip(clip)
        
        # Move clips
        result = move_clips_between_folders("Source", "Destination")
        self.assertEqual(result["status"], "success")
        self.assertIn("Moved 3 clips", result["message"])
        
        # Verify clips were moved
        destination_folder = mock_media_pool.GetFolderByName("Destination")
        self.assertEqual(len(destination_folder.GetClipList()), 3)
        self.assertEqual(len(source_folder.GetClipList()), 0)
        
        # Test moving specific clips
        for i in range(2):
            clip = MockClip(f"Specific Clip {i+1}")
            destination_folder.AddClip(clip)
            
        result = move_clips_between_folders(
            "Destination", "Source", 
            clip_names=["Specific Clip 1"]
        )
        self.assertEqual(result["status"], "success")
        
        # Verify specific clip was moved
        self.assertEqual(len(source_folder.GetClipList()), 1)
        self.assertEqual(source_folder.GetClipList()[0].GetName(), "Specific Clip 1")
    
    def test_create_and_get_smart_bins(self):
        """Test creating and getting smart bins"""
        # Get initial smart bins
        result = get_smart_bins()
        self.assertEqual(result["status"], "success")
        initial_count = len(result["smart_bins"])
        
        # Create a smart bin
        result = create_smart_bin("Test Smart Bin", {
            "Resolution": "1920x1080",
            "Type": "Video"
        })
        self.assertEqual(result["status"], "success")
        
        # Get updated smart bins
        result = get_smart_bins()
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["smart_bins"]), initial_count + 1)
        
        # Verify the new bin is in the list
        bin_names = [bin["name"] for bin in result["smart_bins"]]
        self.assertIn("Test Smart Bin", bin_names)
    
    def test_delete_smart_bin(self):
        """Test deleting a smart bin"""
        # Create a smart bin
        create_smart_bin("Temp Smart Bin", {"Type": "Video"})
        
        # Delete it
        result = delete_smart_bin("Temp Smart Bin")
        self.assertEqual(result["status"], "success")
        
        # Verify it's gone
        result = get_smart_bins()
        bin_names = [bin["name"] for bin in result["smart_bins"]]
        self.assertNotIn("Temp Smart Bin", bin_names)
    
    def test_bulk_set_clip_property(self):
        """Test bulk setting clip properties"""
        # Add test clips to root folder if they don't exist
        root_folder = mock_media_pool.GetRootFolder()
        if not root_folder.GetClipList():
            for i in range(3):
                clip = MockClip(f"Bulk Test Clip {i+1}")
                root_folder.AddClip(clip)
        
        # Set property on all clips
        result = bulk_set_clip_property(
            folder_path="",  # Root folder
            property_name="Keywords",
            property_value="test,bulk,operation"
        )
        
        self.assertEqual(result["status"], "success")
        
        # Verify property was set
        for clip in root_folder.GetClipList():
            self.assertEqual(
                clip.GetClipProperty("Keywords"),
                "test,bulk,operation"
            )
    
    def test_import_files_to_folder(self):
        """Test importing files to a folder"""
        # Create mock file paths
        file_paths = [
            os.path.join(os.getcwd(), "test1.mp4"),
            os.path.join(os.getcwd(), "test2.mp4")
        ]
        
        # Create a destination folder
        create_folder_path("Import")
        
        # Import files
        result = import_files_to_folder(file_paths, "Import")
        
        # Since we're using mocks, the import should succeed regardless
        # of whether the files exist
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["imported_clip_count"], 2)
        
        # Verify the folder contains imported clips
        folder = mock_media_pool.GetFolderByName("Import")
        clip_names = [clip.GetName() for clip in folder.GetClipList()]
        self.assertEqual(len(clip_names), 2)
        self.assertIn("test1.mp4", clip_names)
        self.assertIn("test2.mp4", clip_names)

if __name__ == "__main__":
    unittest.main() 