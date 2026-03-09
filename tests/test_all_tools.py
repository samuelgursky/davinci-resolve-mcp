#!/usr/bin/env python3
"""
Comprehensive test of ALL DaVinci Resolve API methods used by MCP tools.
Tests every API call against live Resolve to verify the methods work.
Run with: python3 tests/test_all_tools.py

Requires DaVinci Resolve to be running with a project open and at least
one timeline with at least one clip.
"""

import sys
import os
import json
import traceback
import tempfile

sys.path.insert(0, '/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules')
import DaVinciResolveScript as dvr

resolve = dvr.scriptapp('Resolve')
if not resolve:
    print("FATAL: Cannot connect to DaVinci Resolve")
    sys.exit(1)

print(f"Connected to {resolve.GetProductName()} {resolve.GetVersionString()}")

pm = resolve.GetProjectManager()
project = pm.GetCurrentProject()
mp = project.GetMediaPool()
root = mp.GetRootFolder()
ms = resolve.GetMediaStorage()
gallery = project.GetGallery()
tl = project.GetCurrentTimeline()
clips = root.GetClipList() or []
tl_items = tl.GetItemListInTrack("video", 1) if tl else []

print(f"Project: {project.GetName()}")
print(f"Clips in root: {len(clips)}")
print(f"Timeline: {tl.GetName() if tl else 'None'}")
print(f"Timeline items: {len(tl_items or [])}")
print("=" * 70)

results = {"pass": [], "fail": [], "skip": [], "error": []}

def test(name, fn=None, skip_reason=None):
    """Run a test and record result."""
    if skip_reason or fn is None:
        results["skip"].append((name, skip_reason or "no function"))
        return None
    try:
        result = fn()
        val = str(result)[:80] if result is not None else "None"
        results["pass"].append((name, val))
        return result
    except Exception as e:
        results["error"].append((name, f"{type(e).__name__}: {str(e)[:100]}"))
        return None

# ===========================
# RESOLVE OBJECT (21 methods)
# ===========================
print("\n--- Resolve (21 methods) ---")
test("Resolve.Fusion", lambda: resolve.Fusion() is not None)
test("Resolve.GetMediaStorage", lambda: resolve.GetMediaStorage() is not None)
test("Resolve.GetProjectManager", lambda: resolve.GetProjectManager() is not None)
test("Resolve.OpenPage", lambda: resolve.OpenPage("edit"))
test("Resolve.GetCurrentPage", lambda: resolve.GetCurrentPage())
test("Resolve.GetProductName", lambda: resolve.GetProductName())
test("Resolve.GetVersion", lambda: resolve.GetVersion())
test("Resolve.GetVersionString", lambda: resolve.GetVersionString())
test("Resolve.SaveLayoutPreset", lambda: resolve.SaveLayoutPreset("_test_api"))
test("Resolve.LoadLayoutPreset", lambda: resolve.LoadLayoutPreset("_test_api"))
test("Resolve.UpdateLayoutPreset", lambda: resolve.UpdateLayoutPreset("_test_api"))
test("Resolve.ExportLayoutPreset", lambda: resolve.ExportLayoutPreset("_test_api", os.path.join(tempfile.mkdtemp(), "test.preset")))
test("Resolve.ImportLayoutPreset", skip_reason="no preset file to import")
test("Resolve.DeleteLayoutPreset", lambda: resolve.DeleteLayoutPreset("_test_api"))
test("Resolve.ImportRenderPreset", skip_reason="no preset file")
test("Resolve.ExportRenderPreset", skip_reason="needs valid preset name")
test("Resolve.ImportBurnInPreset", skip_reason="no preset file")
test("Resolve.ExportBurnInPreset", skip_reason="needs valid preset name")
test("Resolve.GetKeyframeMode", lambda: resolve.GetKeyframeMode())
test("Resolve.SetKeyframeMode", lambda: resolve.SetKeyframeMode(0))
test("Resolve.Quit", skip_reason="would quit Resolve")

# ===========================
# PROJECT MANAGER (25 methods)
# ===========================
print("\n--- ProjectManager (25 methods) ---")
test("PM.ArchiveProject", skip_reason="slow/creates archive file")
test("PM.CreateProject", skip_reason="would create project")
test("PM.DeleteProject", skip_reason="would delete project")
test("PM.LoadProject", skip_reason="would switch project")
test("PM.GetCurrentProject", lambda: pm.GetCurrentProject() is not None)
test("PM.SaveProject", lambda: pm.SaveProject())
test("PM.CloseProject", skip_reason="would close project")
test("PM.CreateFolder", skip_reason="would create folder")
test("PM.DeleteFolder", skip_reason="would delete folder")
test("PM.GetProjectListInCurrentFolder", lambda: pm.GetProjectListInCurrentFolder())
test("PM.GetFolderListInCurrentFolder", lambda: pm.GetFolderListInCurrentFolder())
test("PM.GotoRootFolder", lambda: pm.GotoRootFolder())
test("PM.GotoParentFolder", lambda: pm.GotoParentFolder())
test("PM.GetCurrentFolder", lambda: pm.GetCurrentFolder())
test("PM.OpenFolder", skip_reason="would change folder")
test("PM.ImportProject", skip_reason="needs project file")
test("PM.ExportProject", skip_reason="would export/slow")
test("PM.RestoreProject", skip_reason="needs backup file")
test("PM.GetCurrentDatabase", lambda: pm.GetCurrentDatabase())
test("PM.GetDatabaseList", lambda: pm.GetDatabaseList())
test("PM.SetCurrentDatabase", skip_reason="would change database")
test("PM.CreateCloudProject", skip_reason="needs cloud setup")
test("PM.LoadCloudProject", skip_reason="needs cloud setup")
test("PM.ImportCloudProject", skip_reason="needs cloud setup")
test("PM.RestoreCloudProject", skip_reason="needs cloud setup")

# ===========================
# PROJECT (42 methods)
# ===========================
print("\n--- Project (42 methods) ---")
test("Project.GetMediaPool", lambda: project.GetMediaPool() is not None)
test("Project.GetTimelineCount", lambda: project.GetTimelineCount())
test("Project.GetTimelineByIndex", lambda: project.GetTimelineByIndex(1) is not None if project.GetTimelineCount() > 0 else "no timelines")
test("Project.GetCurrentTimeline", lambda: project.GetCurrentTimeline() is not None)
test("Project.SetCurrentTimeline", lambda: project.SetCurrentTimeline(tl) if tl else "no timeline")
test("Project.GetGallery", lambda: project.GetGallery() is not None)
test("Project.GetName", lambda: project.GetName())
test("Project.SetName", lambda: project.SetName(project.GetName()))
test("Project.GetPresetList", lambda: project.GetPresetList())
test("Project.SetPreset", lambda: project.SetPreset("nonexistent"))  # Will return False but tests API
test("Project.AddRenderJob", lambda: project.AddRenderJob())
test("Project.DeleteRenderJob", skip_reason="needs valid job ID")
test("Project.DeleteAllRenderJobs", lambda: project.DeleteAllRenderJobs())
test("Project.GetRenderJobList", lambda: project.GetRenderJobList())
test("Project.GetRenderPresetList", lambda: project.GetRenderPresetList())
test("Project.StartRendering", skip_reason="would start render")
test("Project.StopRendering", lambda: project.StopRendering())
test("Project.IsRenderingInProgress", lambda: project.IsRenderingInProgress())
test("Project.LoadRenderPreset", lambda: project.LoadRenderPreset("H.264 Master"))
test("Project.SaveAsNewRenderPreset", skip_reason="would create preset")
test("Project.DeleteRenderPreset", skip_reason="would delete preset")
test("Project.SetRenderSettings", lambda: project.SetRenderSettings({"TargetDir": "/tmp"}))
test("Project.GetRenderJobStatus", skip_reason="needs valid job ID")
test("Project.GetQuickExportRenderPresets", lambda: project.GetQuickExportRenderPresets())
test("Project.RenderWithQuickExport", skip_reason="would start render")
test("Project.GetSetting", lambda: project.GetSetting(""))
test("Project.SetSetting", lambda: project.SetSetting("timelineFrameRate", "23.976"))
test("Project.GetRenderFormats", lambda: project.GetRenderFormats())
test("Project.GetRenderCodecs", lambda: project.GetRenderCodecs("mp4"))
test("Project.GetCurrentRenderFormatAndCodec", lambda: project.GetCurrentRenderFormatAndCodec())
test("Project.SetCurrentRenderFormatAndCodec", lambda: project.SetCurrentRenderFormatAndCodec("mov", "H264"))
test("Project.GetCurrentRenderMode", lambda: project.GetCurrentRenderMode())
test("Project.SetCurrentRenderMode", lambda: project.SetCurrentRenderMode(1))
test("Project.GetRenderResolutions", lambda: project.GetRenderResolutions("mp4", "H.264"))
test("Project.RefreshLUTList", lambda: project.RefreshLUTList())
test("Project.GetUniqueId", lambda: project.GetUniqueId())
test("Project.InsertAudioToCurrentTrackAtPlayhead", skip_reason="needs audio file on Fairlight page")
test("Project.LoadBurnInPreset", lambda: project.LoadBurnInPreset("nonexistent"))
test("Project.ExportCurrentFrameAsStill", lambda: project.ExportCurrentFrameAsStill(os.path.join(tempfile.mkdtemp(), "still.png")))
test("Project.GetColorGroupsList", lambda: project.GetColorGroupsList())
test("Project.AddColorGroup", lambda: project.AddColorGroup("_test_cg"))
# Clean up
for g in (project.GetColorGroupsList() or []):
    try:
        if g.GetName() == "_test_cg":
            test("Project.DeleteColorGroup", lambda: project.DeleteColorGroup(g))
            break
    except:
        pass

# ===========================
# MEDIA STORAGE (7 methods)
# ===========================
print("\n--- MediaStorage (7 methods) ---")
volumes = ms.GetMountedVolumeList() or []
test("MS.GetMountedVolumeList", lambda: ms.GetMountedVolumeList())
test("MS.GetSubFolderList", lambda: ms.GetSubFolderList(volumes[0]) if volumes else "no volumes")
test("MS.GetFileList", lambda: ms.GetFileList(volumes[0]) if volumes else "no volumes")
test("MS.RevealInStorage", lambda: ms.RevealInStorage(volumes[0]) if volumes else "no volumes")
test("MS.AddItemListToMediaPool", skip_reason="would import media")
test("MS.AddClipMattesToMediaPool", skip_reason="needs matte files")
test("MS.AddTimelineMattesToMediaPool", skip_reason="needs matte files")

# ===========================
# MEDIA POOL (27 methods)
# ===========================
print("\n--- MediaPool (27 methods) ---")
test("MP.GetRootFolder", lambda: mp.GetRootFolder() is not None)
test("MP.AddSubFolder", skip_reason="would create folder")
test("MP.RefreshFolders", lambda: mp.RefreshFolders())
test("MP.CreateEmptyTimeline", skip_reason="would create timeline")
test("MP.AppendToTimeline", skip_reason="would modify timeline")
test("MP.CreateTimelineFromClips", skip_reason="would create timeline")
test("MP.ImportTimelineFromFile", skip_reason="needs file")
test("MP.DeleteTimelines", skip_reason="would delete timeline")
test("MP.GetCurrentFolder", lambda: mp.GetCurrentFolder() is not None)
test("MP.SetCurrentFolder", lambda: mp.SetCurrentFolder(root))
test("MP.DeleteClips", skip_reason="would delete clips")
test("MP.ImportFolderFromFile", skip_reason="needs DRB file")
test("MP.DeleteFolders", skip_reason="would delete folders")
test("MP.MoveClips", skip_reason="would move clips")
test("MP.MoveFolders", skip_reason="would move folders")
test("MP.GetClipMatteList", lambda: mp.GetClipMatteList(clips[0]) if clips else "no clips")
test("MP.GetTimelineMatteList", lambda: mp.GetTimelineMatteList(root))
test("MP.DeleteClipMattes", skip_reason="would delete mattes")
test("MP.RelinkClips", skip_reason="would relink clips")
test("MP.UnlinkClips", skip_reason="would unlink clips")
test("MP.ImportMedia", skip_reason="would import media")
test("MP.ExportMetadata", lambda: mp.ExportMetadata(os.path.join(tempfile.mkdtemp(), "meta.csv")))
test("MP.GetUniqueId", lambda: mp.GetUniqueId())
test("MP.CreateStereoClip", skip_reason="needs stereo clips")
test("MP.AutoSyncAudio", skip_reason="needs matching clips")
test("MP.GetSelectedClips", lambda: mp.GetSelectedClips())
test("MP.SetSelectedClip", lambda: mp.SetSelectedClip(clips[0]) if clips else "no clips")

# ===========================
# FOLDER (8 methods)
# ===========================
print("\n--- Folder (8 methods) ---")
test("Folder.GetClipList", lambda: root.GetClipList())
test("Folder.GetName", lambda: root.GetName())
test("Folder.GetSubFolderList", lambda: root.GetSubFolderList())
test("Folder.GetIsFolderStale", lambda: root.GetIsFolderStale())
test("Folder.GetUniqueId", lambda: root.GetUniqueId())
test("Folder.Export", skip_reason="would export DRB")
test("Folder.TranscribeAudio", skip_reason="slow AI operation")
test("Folder.ClearTranscription", skip_reason="needs transcription")

# ===========================
# MEDIA POOL ITEM (32 methods)
# ===========================
print("\n--- MediaPoolItem (32 methods) ---")
if clips:
    clip = clips[0]
    test("MPI.GetName", lambda: clip.GetName())
    test("MPI.GetMetadata", lambda: clip.GetMetadata())
    test("MPI.SetMetadata", lambda: clip.SetMetadata("Comments", "API test"))
    test("MPI.GetThirdPartyMetadata", lambda: clip.GetThirdPartyMetadata())
    test("MPI.SetThirdPartyMetadata", skip_reason="might alter metadata")
    test("MPI.GetMediaId", lambda: clip.GetMediaId())
    test("MPI.AddMarker", lambda: clip.AddMarker(0, "Green", "TestMarker", "test", 1))
    test("MPI.GetMarkers", lambda: clip.GetMarkers())
    test("MPI.GetMarkerByCustomData", lambda: clip.GetMarkerByCustomData("nonexistent"))
    test("MPI.UpdateMarkerCustomData", lambda: clip.UpdateMarkerCustomData(0, "test_data"))
    test("MPI.GetMarkerCustomData", lambda: clip.GetMarkerCustomData(0))
    test("MPI.DeleteMarkersByColor", lambda: clip.DeleteMarkersByColor("Green"))
    test("MPI.DeleteMarkerAtFrame", lambda: clip.DeleteMarkerAtFrame(0))
    test("MPI.DeleteMarkerByCustomData", lambda: clip.DeleteMarkerByCustomData("test_data"))
    test("MPI.AddFlag", lambda: clip.AddFlag("Blue"))
    test("MPI.GetFlagList", lambda: clip.GetFlagList())
    test("MPI.ClearFlags", lambda: clip.ClearFlags("All"))
    test("MPI.GetClipColor", lambda: clip.GetClipColor())
    test("MPI.SetClipColor", lambda: clip.SetClipColor("Orange"))
    test("MPI.ClearClipColor", lambda: clip.ClearClipColor())
    test("MPI.GetClipProperty", lambda: clip.GetClipProperty())
    test("MPI.SetClipProperty", skip_reason="might alter clip")
    test("MPI.LinkProxyMedia", skip_reason="needs proxy file")
    test("MPI.UnlinkProxyMedia", lambda: clip.UnlinkProxyMedia())
    test("MPI.ReplaceClip", skip_reason="would replace clip")
    test("MPI.GetUniqueId", lambda: clip.GetUniqueId())
    test("MPI.TranscribeAudio", skip_reason="slow AI operation")
    test("MPI.ClearTranscription", skip_reason="needs transcription")
    test("MPI.GetAudioMapping", lambda: clip.GetAudioMapping())
    test("MPI.GetMarkInOut", lambda: clip.GetMarkInOut())
    test("MPI.SetMarkInOut", lambda: clip.SetMarkInOut(0, 100))
    test("MPI.ClearMarkInOut", lambda: clip.ClearMarkInOut())
else:
    for m in ["GetName","GetMetadata","SetMetadata","GetThirdPartyMetadata","SetThirdPartyMetadata",
              "GetMediaId","AddMarker","GetMarkers","GetMarkerByCustomData","UpdateMarkerCustomData",
              "GetMarkerCustomData","DeleteMarkersByColor","DeleteMarkerAtFrame","DeleteMarkerByCustomData",
              "AddFlag","GetFlagList","ClearFlags","GetClipColor","SetClipColor","ClearClipColor",
              "GetClipProperty","SetClipProperty","LinkProxyMedia","UnlinkProxyMedia","ReplaceClip",
              "GetUniqueId","TranscribeAudio","ClearTranscription","GetAudioMapping",
              "GetMarkInOut","SetMarkInOut","ClearMarkInOut"]:
        results["skip"].append((f"MPI.{m}", "no clips in project"))

# ===========================
# TIMELINE (56 methods)
# ===========================
print("\n--- Timeline (56 methods) ---")
if tl:
    test("TL.GetName", lambda: tl.GetName())
    test("TL.SetName", lambda: tl.SetName(tl.GetName()))
    test("TL.GetStartFrame", lambda: tl.GetStartFrame())
    test("TL.GetEndFrame", lambda: tl.GetEndFrame())
    test("TL.SetStartTimecode", lambda: tl.SetStartTimecode(tl.GetStartTimecode()))
    test("TL.GetStartTimecode", lambda: tl.GetStartTimecode())
    test("TL.GetTrackCount_video", lambda: tl.GetTrackCount("video"))
    test("TL.GetTrackCount_audio", lambda: tl.GetTrackCount("audio"))
    test("TL.GetTrackCount_subtitle", lambda: tl.GetTrackCount("subtitle"))
    test("TL.AddTrack", skip_reason="would add track")
    test("TL.DeleteTrack", skip_reason="would delete track")
    test("TL.GetTrackSubType", lambda: tl.GetTrackSubType("audio", 1))
    test("TL.SetTrackEnable", lambda: tl.SetTrackEnable("video", 1, True))
    test("TL.GetIsTrackEnabled", lambda: tl.GetIsTrackEnabled("video", 1))
    test("TL.SetTrackLock", lambda: tl.SetTrackLock("video", 1, False))
    test("TL.GetIsTrackLocked", lambda: tl.GetIsTrackLocked("video", 1))
    test("TL.DeleteClips", skip_reason="would delete clips")
    test("TL.SetClipsLinked", skip_reason="would change links")
    test("TL.GetItemListInTrack", lambda: tl.GetItemListInTrack("video", 1))
    test("TL.AddMarker", lambda: tl.AddMarker(86400, "Blue", "Test", "note", 1))
    test("TL.GetMarkers", lambda: tl.GetMarkers())
    test("TL.GetMarkerByCustomData", lambda: tl.GetMarkerByCustomData("nonexistent"))
    test("TL.UpdateMarkerCustomData", lambda: tl.UpdateMarkerCustomData(86400, "test"))
    test("TL.GetMarkerCustomData", lambda: tl.GetMarkerCustomData(86400))
    test("TL.DeleteMarkersByColor", lambda: tl.DeleteMarkersByColor("Blue"))
    test("TL.DeleteMarkerAtFrame", lambda: tl.DeleteMarkerAtFrame(86400))
    test("TL.DeleteMarkerByCustomData", lambda: tl.DeleteMarkerByCustomData("test"))
    test("TL.GetCurrentTimecode", lambda: tl.GetCurrentTimecode())
    test("TL.SetCurrentTimecode", lambda: tl.SetCurrentTimecode(tl.GetCurrentTimecode()))
    test("TL.GetCurrentVideoItem", lambda: tl.GetCurrentVideoItem())
    test("TL.GetCurrentClipThumbnailImage", lambda: tl.GetCurrentClipThumbnailImage())
    test("TL.GetTrackName", lambda: tl.GetTrackName("video", 1))
    test("TL.SetTrackName", lambda: tl.SetTrackName("video", 1, "Video 1"))
    test("TL.DuplicateTimeline", skip_reason="would duplicate timeline")
    test("TL.CreateCompoundClip", skip_reason="would create compound")
    test("TL.CreateFusionClip", skip_reason="would create fusion clip")
    test("TL.ImportIntoTimeline", skip_reason="needs AAF/EDL file")
    test("TL.Export", lambda: tl.Export(os.path.join(tempfile.mkdtemp(), "test.fcpxml"), resolve.EXPORT_FCPXML_1_10, resolve.EXPORT_NONE))
    test("TL.GetSetting", lambda: tl.GetSetting(""))
    test("TL.SetSetting", lambda: tl.SetSetting("timelineFrameRate", "23.976"))
    test("TL.InsertGeneratorIntoTimeline", skip_reason="would modify timeline")
    test("TL.InsertFusionGeneratorIntoTimeline", skip_reason="would modify timeline")
    test("TL.InsertFusionCompositionIntoTimeline", skip_reason="would modify timeline")
    test("TL.InsertOFXGeneratorIntoTimeline", skip_reason="would modify timeline")
    test("TL.InsertTitleIntoTimeline", skip_reason="would modify timeline")
    test("TL.InsertFusionTitleIntoTimeline", skip_reason="would modify timeline")
    test("TL.GrabStill", lambda: tl.GrabStill())
    test("TL.GrabAllStills", skip_reason="slow operation")
    test("TL.GetUniqueId", lambda: tl.GetUniqueId())
    test("TL.CreateSubtitlesFromAudio", skip_reason="slow AI operation")
    test("TL.DetectSceneCuts", skip_reason="slow operation")
    test("TL.ConvertTimelineToStereo", skip_reason="would convert timeline")
    test("TL.GetNodeGraph", lambda: tl.GetNodeGraph() is not None)
    test("TL.AnalyzeDolbyVision", skip_reason="slow analysis")
    test("TL.GetMediaPoolItem", lambda: tl.GetMediaPoolItem())
    test("TL.GetMarkInOut", lambda: tl.GetMarkInOut())
    test("TL.SetMarkInOut", lambda: tl.SetMarkInOut(86400, 86500))
    test("TL.ClearMarkInOut", lambda: tl.ClearMarkInOut())
else:
    for i in range(56):
        results["skip"].append((f"TL.method_{i}", "no timeline"))

# ===========================
# TIMELINE ITEM (76 methods)
# ===========================
print("\n--- TimelineItem (76 methods) ---")
if tl_items:
    item = tl_items[0]
    test("TI.GetName", lambda: item.GetName())
    test("TI.GetDuration", lambda: item.GetDuration())
    test("TI.GetEnd", lambda: item.GetEnd())
    test("TI.GetSourceEndFrame", lambda: item.GetSourceEndFrame())
    test("TI.GetSourceEndTime", lambda: item.GetSourceEndTime())
    test("TI.GetFusionCompCount", lambda: item.GetFusionCompCount())
    test("TI.GetFusionCompByIndex", skip_reason="needs fusion comp")
    test("TI.GetFusionCompNameList", lambda: item.GetFusionCompNameList())
    test("TI.GetFusionCompByName", skip_reason="needs fusion comp")
    test("TI.GetLeftOffset", lambda: item.GetLeftOffset())
    test("TI.GetRightOffset", lambda: item.GetRightOffset())
    test("TI.GetStart", lambda: item.GetStart())
    test("TI.GetSourceStartFrame", lambda: item.GetSourceStartFrame())
    test("TI.GetSourceStartTime", lambda: item.GetSourceStartTime())
    test("TI.SetProperty", skip_reason="might change item")
    test("TI.GetProperty", lambda: item.GetProperty())
    test("TI.AddMarker", lambda: item.AddMarker(0, "Red", "TITest", "note", 1))
    test("TI.GetMarkers", lambda: item.GetMarkers())
    test("TI.GetMarkerByCustomData", lambda: item.GetMarkerByCustomData("nonexistent"))
    test("TI.UpdateMarkerCustomData", lambda: item.UpdateMarkerCustomData(0, "test"))
    test("TI.GetMarkerCustomData", lambda: item.GetMarkerCustomData(0))
    test("TI.DeleteMarkersByColor", lambda: item.DeleteMarkersByColor("Red"))
    test("TI.DeleteMarkerAtFrame", lambda: item.DeleteMarkerAtFrame(0))
    test("TI.DeleteMarkerByCustomData", lambda: item.DeleteMarkerByCustomData("test"))
    test("TI.AddFlag", lambda: item.AddFlag("Green"))
    test("TI.GetFlagList", lambda: item.GetFlagList())
    test("TI.ClearFlags", lambda: item.ClearFlags("All"))
    test("TI.GetClipColor", lambda: item.GetClipColor())
    test("TI.SetClipColor", lambda: item.SetClipColor("Orange"))
    test("TI.ClearClipColor", lambda: item.ClearClipColor())
    test("TI.AddFusionComp", skip_reason="would add comp")
    test("TI.ImportFusionComp", skip_reason="needs comp file")
    test("TI.ExportFusionComp", skip_reason="needs comp")
    test("TI.DeleteFusionCompByName", skip_reason="needs comp")
    test("TI.LoadFusionCompByName", skip_reason="needs comp")
    test("TI.RenameFusionCompByName", skip_reason="needs comp")
    test("TI.AddVersion", skip_reason="would add version")
    test("TI.GetCurrentVersion", lambda: item.GetCurrentVersion())
    test("TI.DeleteVersionByName", skip_reason="needs version")
    test("TI.LoadVersionByName", skip_reason="needs version")
    test("TI.RenameVersionByName", skip_reason="needs version")
    test("TI.GetVersionNameList", lambda: item.GetVersionNameList(0))
    test("TI.GetMediaPoolItem", lambda: item.GetMediaPoolItem())
    test("TI.GetStereoConvergenceValues", lambda: item.GetStereoConvergenceValues())
    test("TI.GetStereoLeftFloatingWindowParams", lambda: item.GetStereoLeftFloatingWindowParams())
    test("TI.GetStereoRightFloatingWindowParams", lambda: item.GetStereoRightFloatingWindowParams())
    test("TI.SetCDL", skip_reason="would change color")
    test("TI.AddTake", skip_reason="needs media pool item")
    test("TI.GetSelectedTakeIndex", lambda: item.GetSelectedTakeIndex())
    test("TI.GetTakesCount", lambda: item.GetTakesCount())
    test("TI.GetTakeByIndex", skip_reason="needs takes")
    test("TI.DeleteTakeByIndex", skip_reason="needs takes")
    test("TI.SelectTakeByIndex", skip_reason="needs takes")
    test("TI.FinalizeTake", lambda: item.FinalizeTake())
    test("TI.CopyGrades", skip_reason="needs target items")
    test("TI.SetClipEnabled", lambda: item.SetClipEnabled(True))
    test("TI.GetClipEnabled", lambda: item.GetClipEnabled())
    test("TI.UpdateSidecar", lambda: item.UpdateSidecar())
    test("TI.GetUniqueId", lambda: item.GetUniqueId())
    test("TI.LoadBurnInPreset", lambda: item.LoadBurnInPreset("nonexistent"))
    test("TI.CreateMagicMask", skip_reason="slow AI operation")
    test("TI.RegenerateMagicMask", skip_reason="needs mask")
    test("TI.Stabilize", skip_reason="slow operation")
    test("TI.SmartReframe", skip_reason="slow operation")
    test("TI.GetNodeGraph", lambda: item.GetNodeGraph())
    test("TI.GetColorGroup", lambda: item.GetColorGroup())
    test("TI.AssignToColorGroup", skip_reason="needs group")
    test("TI.RemoveFromColorGroup", lambda: item.RemoveFromColorGroup())
    test("TI.ExportLUT", skip_reason="needs path and enum")
    test("TI.GetLinkedItems", lambda: item.GetLinkedItems())
    test("TI.GetTrackTypeAndIndex", lambda: item.GetTrackTypeAndIndex())
    test("TI.GetSourceAudioChannelMapping", lambda: item.GetSourceAudioChannelMapping())
    test("TI.GetIsColorOutputCacheEnabled", lambda: item.GetIsColorOutputCacheEnabled())
    test("TI.GetIsFusionOutputCacheEnabled", lambda: item.GetIsFusionOutputCacheEnabled())
    test("TI.SetColorOutputCache", skip_reason="would change cache")
    test("TI.SetFusionOutputCache", skip_reason="would change cache")
else:
    for i in range(76):
        results["skip"].append((f"TI.method_{i}", "no timeline items"))

# ===========================
# GALLERY (8 methods)
# ===========================
print("\n--- Gallery (8 methods) ---")
if gallery:
    albums = gallery.GetGalleryStillAlbums() or []
    test("Gallery.GetAlbumName", lambda: gallery.GetAlbumName(albums[0]) if albums else "no albums")
    test("Gallery.SetAlbumName", skip_reason="would rename album")
    test("Gallery.GetCurrentStillAlbum", lambda: gallery.GetCurrentStillAlbum())
    test("Gallery.SetCurrentStillAlbum", lambda: gallery.SetCurrentStillAlbum(albums[0]) if albums else "no albums")
    test("Gallery.GetGalleryStillAlbums", lambda: gallery.GetGalleryStillAlbums())
    test("Gallery.GetGalleryPowerGradeAlbums", lambda: gallery.GetGalleryPowerGradeAlbums())
    test("Gallery.CreateGalleryStillAlbum", skip_reason="would create album")
    test("Gallery.CreateGalleryPowerGradeAlbum", skip_reason="would create album")

# ===========================
# GALLERY STILL ALBUM (6 methods)
# ===========================
print("\n--- GalleryStillAlbum (6 methods) ---")
if gallery:
    album = gallery.GetCurrentStillAlbum()
    if album:
        test("GSA.GetStills", lambda: album.GetStills())
        stills = album.GetStills() or []
        test("GSA.GetLabel", lambda: album.GetLabel(stills[0]) if stills else "no stills")
        test("GSA.SetLabel", skip_reason="would change label")
        test("GSA.ImportStills", skip_reason="needs still files")
        test("GSA.ExportStills", skip_reason="needs stills")
        test("GSA.DeleteStills", skip_reason="would delete stills")

# ===========================
# GRAPH (11 methods)
# ===========================
print("\n--- Graph (11 methods) ---")
if tl_items:
    graph = tl_items[0].GetNodeGraph()
    if graph:
        test("Graph.GetNumNodes", lambda: graph.GetNumNodes())
        test("Graph.SetLUT", skip_reason="would change LUT")
        test("Graph.GetLUT", lambda: graph.GetLUT(1))
        test("Graph.SetNodeCacheMode", skip_reason="would change cache")
        test("Graph.GetNodeCacheMode", lambda: graph.GetNodeCacheMode(1))
        test("Graph.GetNodeLabel", lambda: graph.GetNodeLabel(1))
        test("Graph.GetToolsInNode", lambda: graph.GetToolsInNode(1))
        test("Graph.SetNodeEnabled", skip_reason="would change node")
        test("Graph.ApplyGradeFromDRX", skip_reason="needs DRX file")
        test("Graph.ApplyArriCdlLut", lambda: graph.ApplyArriCdlLut())
        test("Graph.ResetAllGrades", skip_reason="would reset grades")

# ===========================
# COLOR GROUP (5 methods)
# ===========================
print("\n--- ColorGroup (5 methods) ---")
# Create a temporary color group for testing
cg = project.AddColorGroup("_test_cg_api")
if cg:
    test("CG.GetName", lambda: cg.GetName())
    test("CG.SetName", lambda: cg.SetName("_test_cg_api_renamed"))
    test("CG.GetClipsInTimeline", lambda: cg.GetClipsInTimeline())
    test("CG.GetPreClipNodeGraph", lambda: cg.GetPreClipNodeGraph())
    test("CG.GetPostClipNodeGraph", lambda: cg.GetPostClipNodeGraph())
    # Clean up
    cg.SetName("_test_cg_api_renamed")
    project.DeleteColorGroup(cg)
else:
    for m in ["GetName", "SetName", "GetClipsInTimeline", "GetPreClipNodeGraph", "GetPostClipNodeGraph"]:
        results["skip"].append((f"CG.{m}", "could not create color group"))

# ===========================
# SUMMARY
# ===========================
print("\n" + "=" * 70)
total_pass = len(results["pass"])
total_fail = len(results["fail"])
total_error = len(results["error"])
total_skip = len(results["skip"])
total = total_pass + total_fail + total_error + total_skip
tested = total_pass + total_fail + total_error

print(f"RESULTS: {total_pass} passed, {total_fail} failed, {total_error} errors, {total_skip} skipped")
print(f"Total API methods accounted for: {total}")
print(f"Actually tested: {tested}")
print(f"Pass rate (of tested): {total_pass/max(tested,1)*100:.1f}%")

if results["fail"]:
    print(f"\n--- FAILURES ({len(results['fail'])}) ---")
    for name, reason in results["fail"]:
        print(f"  FAIL: {name}: {reason}")

if results["error"]:
    print(f"\n--- ERRORS ({len(results['error'])}) ---")
    for name, reason in results["error"]:
        print(f"  ERROR: {name}: {reason}")

print(f"\n--- PASSED ({total_pass}) ---")
for name, val in results["pass"]:
    print(f"  OK: {name} = {val}")

print(f"\n--- SKIPPED ({total_skip}) ---")
for name, reason in results["skip"]:
    print(f"  SKIP: {name}: {reason}")

# Save results
output = {
    "summary": {
        "total_methods": total,
        "tested": tested,
        "passed": total_pass,
        "failed": total_fail,
        "errors": total_error,
        "skipped": total_skip,
        "pass_rate": f"{total_pass/max(tested,1)*100:.1f}%"
    },
    "pass": [{"name": n, "value": v} for n, v in results["pass"]],
    "fail": [{"name": n, "detail": d} for n, d in results["fail"]],
    "error": [{"name": n, "detail": d} for n, d in results["error"]],
    "skip": [{"name": n, "reason": r} for n, r in results["skip"]],
}

with open('tests/test_all_tools_results.json', 'w') as f:
    json.dump(output, f, indent=2)
print(f"\nResults saved to tests/test_all_tools_results.json")
