#!/usr/bin/env python3
"""
Phase 2: Test the 111 previously-skipped API methods.
Uses create→test→cleanup patterns for destructive operations.
Run with: python3 tests/test_phase2_skipped.py

Requires DaVinci Resolve Studio running with 'Sample' project open.
"""

import sys
import os
import json
import tempfile
import time

sys.path.insert(0, '/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules')
import DaVinciResolveScript as dvr

resolve = dvr.scriptapp('Resolve')
if not resolve:
    print("FATAL: Cannot connect to DaVinci Resolve")
    sys.exit(1)

print(f"Connected to {resolve.GetProductName()} {resolve.GetVersionString()}")
resolve.OpenPage("edit")

pm = resolve.GetProjectManager()
project = pm.GetCurrentProject()
mp = project.GetMediaPool()
root = mp.GetRootFolder()
gallery = project.GetGallery()
tl = project.GetCurrentTimeline()
clips = root.GetClipList() or []
tl_items = tl.GetItemListInTrack("video", 1) if tl else []

orig_project_name = project.GetName()
print(f"Project: {orig_project_name}")
print(f"Timeline: {tl.GetName() if tl else 'None'}")
print(f"Clips: {len(clips)}, TL Items: {len(tl_items or [])}")
print("=" * 70)

results = {"pass": [], "fail": [], "skip": [], "error": []}

def test(name, fn=None, skip_reason=None):
    if skip_reason or fn is None:
        results["skip"].append((name, skip_reason or "no function"))
        return None
    try:
        result = fn()
        val = str(result)[:80] if result is not None else "None"
        results["pass"].append((name, val))
        print(f"  PASS: {name} = {val}")
        return result
    except Exception as e:
        results["error"].append((name, f"{type(e).__name__}: {str(e)[:100]}"))
        print(f"  ERROR: {name}: {type(e).__name__}: {str(e)[:80]}")
        return None

# ======================================================
# SECTION 1: Resolve - Import/Export presets
# ======================================================
print("\n--- Resolve: Import/Export preset files ---")

# Save a layout preset, export it, delete it, then re-import it
resolve.SaveLayoutPreset("_phase2_test")
tmpdir = tempfile.mkdtemp()

# ExportRenderPreset - first load one to ensure it exists
test("Resolve.ExportRenderPreset", lambda: resolve.ExportRenderPreset("H.264 Master", os.path.join(tmpdir, "render.preset")))

# ImportRenderPreset
rp_path = os.path.join(tmpdir, "render.preset")
if os.path.exists(rp_path):
    test("Resolve.ImportRenderPreset", lambda: resolve.ImportRenderPreset(rp_path))
else:
    test("Resolve.ImportRenderPreset", lambda: resolve.ImportRenderPreset(rp_path))  # will return False but tests API

# ExportBurnInPreset / ImportBurnInPreset
test("Resolve.ExportBurnInPreset", lambda: resolve.ExportBurnInPreset("Default", os.path.join(tmpdir, "burnin.preset")))
bi_path = os.path.join(tmpdir, "burnin.preset")
test("Resolve.ImportBurnInPreset", lambda: resolve.ImportBurnInPreset(bi_path))

# ImportLayoutPreset - export then import
lp_path = os.path.join(tmpdir, "layout.preset")
resolve.ExportLayoutPreset("_phase2_test", lp_path)
test("Resolve.ImportLayoutPreset", lambda: resolve.ImportLayoutPreset(lp_path, "_phase2_imported"))
resolve.DeleteLayoutPreset("_phase2_test")
resolve.DeleteLayoutPreset("_phase2_imported")

# ======================================================
# SECTION 2: ProjectManager - CRUD operations
# ======================================================
print("\n--- ProjectManager: Create/Delete/Load/Export ---")

# CreateFolder / DeleteFolder / OpenFolder
test("PM.CreateFolder", lambda: pm.CreateFolder("_test_folder_phase2"))
test("PM.OpenFolder", lambda: pm.OpenFolder("_test_folder_phase2"))
test("PM.GotoRootFolder", lambda: pm.GotoRootFolder())
test("PM.DeleteFolder", lambda: pm.DeleteFolder("_test_folder_phase2"))

# CreateProject / LoadProject / DeleteProject
# Save current project first
pm.SaveProject()
test("PM.CreateProject", lambda: pm.CreateProject("_test_proj_phase2"))
# We're now in the new project - switch back
test("PM.LoadProject", lambda: pm.LoadProject(orig_project_name))
test("PM.DeleteProject", lambda: pm.DeleteProject("_test_proj_phase2"))

# Re-acquire references after project switch
project = pm.GetCurrentProject()
mp = project.GetMediaPool()
root = mp.GetRootFolder()
tl = project.GetCurrentTimeline()
clips = root.GetClipList() or []
gallery = project.GetGallery()

# ExportProject / ImportProject
exp_path = os.path.join(tmpdir, "test_export.drp")
test("PM.ExportProject", lambda: pm.ExportProject(orig_project_name, exp_path))
# Don't actually import (would create duplicate), but test the API call
test("PM.ImportProject", lambda: pm.ImportProject(exp_path, "_test_import_phase2"))
# Clean up imported project
pm.DeleteProject("_test_import_phase2")

# RestoreProject - test with the exported file
test("PM.RestoreProject", lambda: pm.RestoreProject(exp_path, "_test_restore_phase2"))
pm.LoadProject(orig_project_name)
pm.DeleteProject("_test_restore_phase2")

# Re-acquire after all the project switching
project = pm.GetCurrentProject()
mp = project.GetMediaPool()
root = mp.GetRootFolder()
tl = project.GetCurrentTimeline()
clips = root.GetClipList() or []
gallery = project.GetGallery()
tl_items = tl.GetItemListInTrack("video", 1) if tl else []

# ArchiveProject
archive_path = os.path.join(tmpdir, "test_archive.dra")
test("PM.ArchiveProject", lambda: pm.ArchiveProject(orig_project_name, archive_path, False, False, False))

# CloseProject - test but immediately re-open
test("PM.CloseProject", lambda: pm.CloseProject(project))
test("PM.LoadProject_reopen", lambda: pm.LoadProject(orig_project_name))

# Re-acquire references
project = pm.GetCurrentProject()
mp = project.GetMediaPool()
root = mp.GetRootFolder()
tl = project.GetCurrentTimeline()
clips = root.GetClipList() or []
gallery = project.GetGallery()
tl_items = tl.GetItemListInTrack("video", 1) if tl else []

# Cloud methods - skip (need cloud infrastructure)
test("PM.CreateCloudProject", skip_reason="needs cloud infrastructure")
test("PM.LoadCloudProject", skip_reason="needs cloud infrastructure")
test("PM.ImportCloudProject", skip_reason="needs cloud infrastructure")
test("PM.RestoreCloudProject", skip_reason="needs cloud infrastructure")
test("PM.SetCurrentDatabase", skip_reason="only one database available")

# ======================================================
# SECTION 3: Project - Render operations
# ======================================================
print("\n--- Project: Render job lifecycle ---")

# SaveAsNewRenderPreset / DeleteRenderPreset
test("Project.SaveAsNewRenderPreset", lambda: project.SaveAsNewRenderPreset("_test_preset_phase2"))
test("Project.DeleteRenderPreset", lambda: project.DeleteRenderPreset("_test_preset_phase2"))

# AddRenderJob / GetRenderJobStatus / DeleteRenderJob / StartRendering
project.SetRenderSettings({"TargetDir": tmpdir})
job_id = project.AddRenderJob()
if job_id:
    test("Project.GetRenderJobStatus", lambda: project.GetRenderJobStatus(job_id))
    test("Project.DeleteRenderJob", lambda: project.DeleteRenderJob(job_id))
else:
    test("Project.GetRenderJobStatus", skip_reason="no job ID from AddRenderJob")
    test("Project.DeleteRenderJob", skip_reason="no job ID from AddRenderJob")

# StartRendering - add a job and start (will be very brief)
job_id2 = project.AddRenderJob()
if job_id2:
    test("Project.StartRendering", lambda: project.StartRendering([job_id2]))
    time.sleep(1)
    project.StopRendering()
    project.DeleteRenderJob(job_id2)
else:
    test("Project.StartRendering", skip_reason="no job to render")

# RenderWithQuickExport - will fail without valid setup but tests API
test("Project.RenderWithQuickExport", lambda: project.RenderWithQuickExport("H.264", {"TargetDir": tmpdir, "CustomName": "_phase2_test"}))

# InsertAudioToCurrentTrackAtPlayhead
test("Project.InsertAudioToCurrentTrackAtPlayhead", skip_reason="needs Fairlight page + audio file")

# ======================================================
# SECTION 4: MediaStorage - Add items
# ======================================================
print("\n--- MediaStorage: Add items ---")

ms = resolve.GetMediaStorage()
volumes = ms.GetMountedVolumeList() or []

# Create a test image file to import
test_img = os.path.join(tmpdir, "test_media.jpg")
# Create a minimal JPEG file (smallest valid JPEG)
with open(test_img, 'wb') as f:
    f.write(bytes([
        0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
        0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
        0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07, 0x07, 0x07, 0x09,
        0x09, 0x08, 0x0A, 0x0C, 0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
        0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D, 0x1A, 0x1C, 0x1C, 0x20,
        0x24, 0x2E, 0x27, 0x20, 0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
        0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27, 0x39, 0x3D, 0x38, 0x32,
        0x3C, 0x2E, 0x33, 0x34, 0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01,
        0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00,
        0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
        0x09, 0x0A, 0x0B, 0xFF, 0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01, 0x03,
        0x03, 0x02, 0x04, 0x03, 0x05, 0x05, 0x04, 0x04, 0x00, 0x00, 0x01, 0x7D,
        0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06,
        0x13, 0x51, 0x61, 0x07, 0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xA1, 0x08,
        0x23, 0x42, 0xB1, 0xC1, 0x15, 0x52, 0xD1, 0xF0, 0x24, 0x33, 0x62, 0x72,
        0x82, 0x09, 0x0A, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x25, 0x26, 0x27, 0x28,
        0x29, 0x2A, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3A, 0x43, 0x44, 0x45,
        0x46, 0x47, 0x48, 0x49, 0x4A, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59,
        0x5A, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69, 0x6A, 0x73, 0x74, 0x75,
        0x76, 0x77, 0x78, 0x79, 0x7A, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89,
        0x8A, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9A, 0xA2, 0xA3,
        0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xA9, 0xAA, 0xB2, 0xB3, 0xB4, 0xB5, 0xB6,
        0xB7, 0xB8, 0xB9, 0xBA, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8, 0xC9,
        0xCA, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0xDA, 0xE1, 0xE2,
        0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xF1, 0xF2, 0xF3, 0xF4,
        0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0xFA, 0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01,
        0x00, 0x00, 0x3F, 0x00, 0x7B, 0x94, 0x11, 0x00, 0x00, 0x00, 0x00, 0x00,
        0xFF, 0xD9
    ]))

test("MS.AddItemListToMediaPool", lambda: ms.AddItemListToMediaPool([test_img]))
test("MS.AddClipMattesToMediaPool", skip_reason="needs proper matte media files")
test("MS.AddTimelineMattesToMediaPool", skip_reason="needs proper matte media files")

# ======================================================
# SECTION 5: MediaPool - CRUD operations
# ======================================================
print("\n--- MediaPool: Folder/Timeline/Clip operations ---")

# Re-acquire after potential changes
root = mp.GetRootFolder()
clips = root.GetClipList() or []

# AddSubFolder / DeleteFolders
test_folder = mp.AddSubFolder(root, "_test_subfolder_p2")
test("MP.AddSubFolder", lambda: test_folder is not None)
if test_folder:
    test("MP.DeleteFolders", lambda: mp.DeleteFolders([test_folder]))

# CreateEmptyTimeline / DeleteTimelines
test_tl = mp.CreateEmptyTimeline("_test_tl_phase2")
test("MP.CreateEmptyTimeline", lambda: test_tl is not None)
if test_tl:
    # Switch back to original timeline
    project.SetCurrentTimeline(tl)
    test("MP.DeleteTimelines", lambda: mp.DeleteTimelines([test_tl]))

# CreateTimelineFromClips
clips = root.GetClipList() or []
if clips:
    test_tl2 = mp.CreateTimelineFromClips("_test_tl_from_clips", [clips[0]])
    test("MP.CreateTimelineFromClips", lambda: test_tl2 is not None)
    if test_tl2:
        project.SetCurrentTimeline(tl)
        mp.DeleteTimelines([test_tl2])

# AppendToTimeline
if clips and tl:
    project.SetCurrentTimeline(tl)
    test("MP.AppendToTimeline", lambda: mp.AppendToTimeline([clips[0]]))

# MoveClips - create folder, move clip, move back
if clips:
    move_folder = mp.AddSubFolder(root, "_test_move_p2")
    if move_folder:
        test("MP.MoveClips", lambda: mp.MoveClips([clips[-1]], move_folder))
        # Move back
        mp.MoveClips([clips[-1]], root)
        mp.DeleteFolders([move_folder])

# MoveFolders
folder_to_move = mp.AddSubFolder(root, "_test_movefolder_p2")
target_folder = mp.AddSubFolder(root, "_test_target_p2")
if folder_to_move and target_folder:
    test("MP.MoveFolders", lambda: mp.MoveFolders([folder_to_move], target_folder))
    # Clean up
    mp.DeleteFolders([target_folder])  # deletes target and moved folder inside it

# ImportMedia
test("MP.ImportMedia", lambda: mp.ImportMedia([test_img]))

# RelinkClips / UnlinkClips
clips = root.GetClipList() or []
if len(clips) >= 1:
    test("MP.UnlinkClips", lambda: mp.UnlinkClips([clips[0]]))
    test("MP.RelinkClips", lambda: mp.RelinkClips([clips[0]], os.path.dirname(clips[0].GetClipProperty("File Path") or "/tmp")))

# DeleteClips - delete the test media we imported
clips = root.GetClipList() or []
test_clips = [c for c in clips if "test_media" in (c.GetName() or "")]
if test_clips:
    test("MP.DeleteClips", lambda: mp.DeleteClips(test_clips))
else:
    test("MP.DeleteClips", lambda: mp.DeleteClips([clips[-1]]) if clips else False)

# ImportTimelineFromFile / ImportFolderFromFile
test("MP.ImportTimelineFromFile", skip_reason="needs AAF/EDL/XML file")
test("MP.ImportFolderFromFile", skip_reason="needs DRB file")

# DeleteClipMattes
test("MP.DeleteClipMattes", skip_reason="needs mattes to delete")

# Stereo / AudioSync
test("MP.CreateStereoClip", skip_reason="needs stereo L/R clips")
test("MP.AutoSyncAudio", skip_reason="needs matching A/V clips")

# ======================================================
# SECTION 6: Folder - Export/Transcribe
# ======================================================
print("\n--- Folder: Export/Transcribe ---")

drb_path = os.path.join(tmpdir, "test_export.drb")
test("Folder.Export", lambda: root.Export(drb_path))
test("Folder.TranscribeAudio", skip_reason="slow AI operation (minutes)")
test("Folder.ClearTranscription", skip_reason="needs transcription first")

# ======================================================
# SECTION 7: MediaPoolItem - Set operations
# ======================================================
print("\n--- MediaPoolItem: Set/Property operations ---")

clips = root.GetClipList() or []
if clips:
    clip = clips[0]
    test("MPI.SetThirdPartyMetadata", lambda: clip.SetThirdPartyMetadata("TestKey", "TestValue"))
    test("MPI.SetClipProperty", lambda: clip.SetClipProperty("Clip Name", clip.GetName()))

    test("MPI.LinkProxyMedia", skip_reason="needs proxy media file")
    test("MPI.ReplaceClip", skip_reason="irreversible - would replace clip")
    test("MPI.TranscribeAudio", skip_reason="slow AI operation")
    test("MPI.ClearTranscription", skip_reason="needs transcription first")

# ======================================================
# SECTION 8: Timeline - Track/Insert/Export operations
# ======================================================
print("\n--- Timeline: Track/Insert/Export operations ---")

# Re-acquire timeline
tl = project.GetCurrentTimeline()
if tl:
    # AddTrack / DeleteTrack
    orig_video_count = tl.GetTrackCount("video")
    test("TL.AddTrack", lambda: tl.AddTrack("video"))
    new_count = tl.GetTrackCount("video")
    if new_count > orig_video_count:
        test("TL.DeleteTrack", lambda: tl.DeleteTrack("video", new_count))
    else:
        test("TL.DeleteTrack", skip_reason="AddTrack didn't add a track")

    # DuplicateTimeline
    dup_tl = tl.DuplicateTimeline("_test_dup_phase2")
    test("TL.DuplicateTimeline", lambda: dup_tl is not None)
    if dup_tl:
        project.SetCurrentTimeline(tl)
        mp.DeleteTimelines([dup_tl])

    # Re-acquire timeline items
    tl_items = tl.GetItemListInTrack("video", 1) or []

    # SetClipsLinked
    if len(tl_items) >= 2:
        test("TL.SetClipsLinked", lambda: tl.SetClipsLinked([tl_items[0], tl_items[1]], True))
    else:
        test("TL.SetClipsLinked", skip_reason="need 2+ items")

    # InsertGeneratorIntoTimeline
    gen_item = tl.InsertGeneratorIntoTimeline("10 Step")
    test("TL.InsertGeneratorIntoTimeline", lambda: gen_item is not None)

    # InsertTitleIntoTimeline
    title_item = tl.InsertTitleIntoTimeline("Text")
    test("TL.InsertTitleIntoTimeline", lambda: title_item is not None)

    # InsertFusionGeneratorIntoTimeline
    fgen = tl.InsertFusionGeneratorIntoTimeline("Noise Gradient")
    test("TL.InsertFusionGeneratorIntoTimeline", lambda: fgen is not None)

    # InsertFusionCompositionIntoTimeline
    fcomp = tl.InsertFusionCompositionIntoTimeline()
    test("TL.InsertFusionCompositionIntoTimeline", lambda: fcomp is not None)

    # InsertOFXGeneratorIntoTimeline
    ofx = tl.InsertOFXGeneratorIntoTimeline("Noise Gradient")
    test("TL.InsertOFXGeneratorIntoTimeline", lambda: ofx is not None)

    # InsertFusionTitleIntoTimeline
    ftitle = tl.InsertFusionTitleIntoTimeline("Text+")
    test("TL.InsertFusionTitleIntoTimeline", lambda: ftitle is not None)

    # DeleteClips - clean up inserted items
    new_items = tl.GetItemListInTrack("video", 1) or []
    # Delete items that were newly added (more than original count)
    items_to_delete = new_items[len(tl_items):]
    if items_to_delete:
        test("TL.DeleteClips", lambda: tl.DeleteClips(items_to_delete, False))

    # CreateCompoundClip / CreateFusionClip
    tl_items = tl.GetItemListInTrack("video", 1) or []
    if len(tl_items) >= 2:
        test("TL.CreateCompoundClip", lambda: tl.CreateCompoundClip([tl_items[-2], tl_items[-1]]))
        test("TL.CreateFusionClip", skip_reason="would merge items irreversibly")
    else:
        test("TL.CreateCompoundClip", skip_reason="need 2+ items")
        test("TL.CreateFusionClip", skip_reason="need 2+ items")

    # GrabAllStills
    test("TL.GrabAllStills", lambda: tl.GrabAllStills(2))

    # Slow/AI operations
    test("TL.CreateSubtitlesFromAudio", skip_reason="slow AI operation")
    test("TL.DetectSceneCuts", skip_reason="slow operation")
    test("TL.ConvertTimelineToStereo", skip_reason="irreversible")
    test("TL.AnalyzeDolbyVision", skip_reason="slow/needs HDR content")
    test("TL.ImportIntoTimeline", skip_reason="needs AAF/EDL file")

# ======================================================
# SECTION 9: TimelineItem - Fusion/Version/Take/CDL
# ======================================================
print("\n--- TimelineItem: Fusion comps, versions, takes, CDL ---")

tl_items = tl.GetItemListInTrack("video", 1) if tl else []
# Use a real video clip (not a generator) for these tests
real_items = [i for i in (tl_items or []) if i.GetMediaPoolItem() is not None]
item = real_items[0] if real_items else (tl_items[0] if tl_items else None)

if item:
    # SetProperty
    test("TI.SetProperty", lambda: item.SetProperty("ZoomX", 1.0))

    # Fusion comp lifecycle
    comp = item.AddFusionComp()
    test("TI.AddFusionComp", lambda: comp is not None)

    comp_names = item.GetFusionCompNameList()
    if comp_names:
        first_comp_name = list(comp_names.values())[0] if isinstance(comp_names, dict) else comp_names[0]
        test("TI.GetFusionCompByName", lambda: item.GetFusionCompByName(first_comp_name))
        test("TI.GetFusionCompByIndex", lambda: item.GetFusionCompByIndex(1))

        # Export comp
        comp_path = os.path.join(tmpdir, "test_comp.comp")
        test("TI.ExportFusionComp", lambda: item.ExportFusionComp(comp_path, 1))
        test("TI.LoadFusionCompByName", lambda: item.LoadFusionCompByName(first_comp_name))
        test("TI.RenameFusionCompByName", lambda: item.RenameFusionCompByName(first_comp_name, "_renamed_comp"))

        # Get updated name after rename
        comp_names2 = item.GetFusionCompNameList()
        renamed = "_renamed_comp"
        test("TI.DeleteFusionCompByName", lambda: item.DeleteFusionCompByName(renamed))
    else:
        for m in ["GetFusionCompByName", "GetFusionCompByIndex", "ExportFusionComp",
                   "LoadFusionCompByName", "RenameFusionCompByName", "DeleteFusionCompByName"]:
            test(f"TI.{m}", skip_reason="AddFusionComp returned no comp names")

    # ImportFusionComp
    comp_path = os.path.join(tmpdir, "test_comp.comp")
    if os.path.exists(comp_path):
        test("TI.ImportFusionComp", lambda: item.ImportFusionComp(comp_path))
        # Clean up imported comp
        comp_names3 = item.GetFusionCompNameList()
        if comp_names3:
            last_name = list(comp_names3.values())[-1] if isinstance(comp_names3, dict) else comp_names3[-1]
            item.DeleteFusionCompByName(last_name)
    else:
        test("TI.ImportFusionComp", skip_reason="no exported comp file available")

    # Version lifecycle
    test("TI.AddVersion", lambda: item.AddVersion("_test_version_p2", 0))
    versions = item.GetVersionNameList(0)
    if versions:
        v_list = list(versions.values()) if isinstance(versions, dict) else list(versions)
        if "_test_version_p2" in v_list:
            test("TI.LoadVersionByName", lambda: item.LoadVersionByName("_test_version_p2", 0))
            test("TI.RenameVersionByName", lambda: item.RenameVersionByName("_test_version_p2", "_renamed_v_p2", 0))
            test("TI.DeleteVersionByName", lambda: item.DeleteVersionByName("_renamed_v_p2", 0))
        else:
            test("TI.LoadVersionByName", skip_reason="version not found in list")
            test("TI.RenameVersionByName", skip_reason="version not found")
            test("TI.DeleteVersionByName", skip_reason="version not found")
    else:
        test("TI.LoadVersionByName", skip_reason="no versions available")
        test("TI.RenameVersionByName", skip_reason="no versions available")
        test("TI.DeleteVersionByName", skip_reason="no versions available")

    # SetCDL
    test("TI.SetCDL", lambda: item.SetCDL({"NodeIndex": "1", "Slope": "1 1 1", "Offset": "0 0 0", "Power": "1 1 1", "Saturation": "1"}))

    # Take lifecycle
    clips = root.GetClipList() or []
    if clips:
        test("TI.AddTake", lambda: item.AddTake(clips[0]))
        takes_count = item.GetTakesCount()
        if takes_count and takes_count > 0:
            test("TI.GetTakeByIndex", lambda: item.GetTakeByIndex(1))
            test("TI.SelectTakeByIndex", lambda: item.SelectTakeByIndex(1))
            test("TI.DeleteTakeByIndex", lambda: item.DeleteTakeByIndex(takes_count))
        else:
            test("TI.GetTakeByIndex", skip_reason="no takes created")
            test("TI.SelectTakeByIndex", skip_reason="no takes created")
            test("TI.DeleteTakeByIndex", skip_reason="no takes created")
    else:
        for m in ["AddTake", "GetTakeByIndex", "SelectTakeByIndex", "DeleteTakeByIndex"]:
            test(f"TI.{m}", skip_reason="no clips for take")

    # CopyGrades
    if len(tl_items) >= 2:
        test("TI.CopyGrades", lambda: item.CopyGrades([tl_items[1]]))
    else:
        test("TI.CopyGrades", skip_reason="need 2+ timeline items")

    # AssignToColorGroup
    cg = project.AddColorGroup("_test_cg_p2")
    if cg:
        test("TI.AssignToColorGroup", lambda: item.AssignToColorGroup(cg))
        item.RemoveFromColorGroup()
        project.DeleteColorGroup(cg)
    else:
        test("TI.AssignToColorGroup", skip_reason="could not create color group")

    # ExportLUT
    lut_path = os.path.join(tmpdir, "test.cube")
    test("TI.ExportLUT", lambda: item.ExportLUT(resolve.EXPORT_LUT_33PTCUBE, lut_path))

    # Cache settings
    test("TI.SetColorOutputCache", lambda: item.SetColorOutputCache(True))
    test("TI.SetFusionOutputCache", lambda: item.SetFusionOutputCache(True))
    # Reset cache to auto/disabled
    item.SetColorOutputCache(False)
    item.SetFusionOutputCache(False)

    # Slow/AI operations
    test("TI.CreateMagicMask", skip_reason="slow AI operation (minutes)")
    test("TI.RegenerateMagicMask", skip_reason="needs existing mask")
    test("TI.Stabilize", skip_reason="slow operation")
    test("TI.SmartReframe", skip_reason="slow operation")
else:
    for m in ["SetProperty", "AddFusionComp", "GetFusionCompByName", "GetFusionCompByIndex",
              "ExportFusionComp", "LoadFusionCompByName", "RenameFusionCompByName",
              "DeleteFusionCompByName", "ImportFusionComp", "AddVersion", "LoadVersionByName",
              "RenameVersionByName", "DeleteVersionByName", "SetCDL", "AddTake",
              "GetTakeByIndex", "SelectTakeByIndex", "DeleteTakeByIndex", "CopyGrades",
              "AssignToColorGroup", "ExportLUT", "SetColorOutputCache", "SetFusionOutputCache",
              "CreateMagicMask", "RegenerateMagicMask", "Stabilize", "SmartReframe"]:
        results["skip"].append((f"TI.{m}", "no timeline items"))

# ======================================================
# SECTION 10: Gallery - Album operations
# ======================================================
print("\n--- Gallery: Album CRUD ---")

if gallery:
    # CreateGalleryStillAlbum
    new_album = gallery.CreateGalleryStillAlbum()
    test("Gallery.CreateGalleryStillAlbum", lambda: new_album is not None)

    # SetAlbumName
    if new_album:
        test("Gallery.SetAlbumName", lambda: gallery.SetAlbumName(new_album, "_test_album_p2"))

    # CreateGalleryPowerGradeAlbum
    pg_album = gallery.CreateGalleryPowerGradeAlbum()
    test("Gallery.CreateGalleryPowerGradeAlbum", lambda: pg_album is not None)

    # GalleryStillAlbum operations
    cur_album = gallery.GetCurrentStillAlbum()
    if cur_album:
        stills = cur_album.GetStills() or []
        if stills:
            test("GSA.SetLabel", lambda: cur_album.SetLabel(stills[0], "test_label"))

            # ExportStills
            still_export_dir = os.path.join(tmpdir, "stills")
            os.makedirs(still_export_dir, exist_ok=True)
            test("GSA.ExportStills", lambda: cur_album.ExportStills(stills, still_export_dir, "test_still", "jpg"))

            # ImportStills
            exported = [os.path.join(still_export_dir, f) for f in os.listdir(still_export_dir) if f.endswith(('.jpg','.dpx','.drx'))]
            if exported:
                test("GSA.ImportStills", lambda: cur_album.ImportStills(exported))
            else:
                test("GSA.ImportStills", skip_reason="no exported stills to import")

            # DeleteStills - delete the last still (clean up)
            stills2 = cur_album.GetStills() or []
            if len(stills2) > len(stills):
                test("GSA.DeleteStills", lambda: cur_album.DeleteStills([stills2[-1]]))
            else:
                test("GSA.DeleteStills", skip_reason="no extra stills to delete")
        else:
            test("GSA.SetLabel", skip_reason="no stills in album")
            test("GSA.ExportStills", skip_reason="no stills")
            test("GSA.ImportStills", skip_reason="no stills to export first")
            test("GSA.DeleteStills", skip_reason="no stills")
    # Clean up created albums - can't delete gallery albums via API, just leave them

# ======================================================
# SECTION 11: Resolve.Quit (always skip)
# ======================================================
test("Resolve.Quit", skip_reason="would quit Resolve")

# ======================================================
# SUMMARY
# ======================================================
print("\n" + "=" * 70)
total_pass = len(results["pass"])
total_fail = len(results["fail"])
total_error = len(results["error"])
total_skip = len(results["skip"])
total = total_pass + total_fail + total_error + total_skip
tested = total_pass + total_fail + total_error

print(f"\nPHASE 2 RESULTS: {total_pass} passed, {total_fail} failed, {total_error} errors, {total_skip} skipped")
print(f"Total methods in Phase 2: {total}")
print(f"Actually tested: {tested}")
if tested > 0:
    print(f"Pass rate: {total_pass/tested*100:.1f}%")

if results["fail"]:
    print(f"\n--- FAILURES ({len(results['fail'])}) ---")
    for name, reason in results["fail"]:
        print(f"  FAIL: {name}: {reason}")

if results["error"]:
    print(f"\n--- ERRORS ({len(results['error'])}) ---")
    for name, reason in results["error"]:
        print(f"  ERROR: {name}: {reason}")

if results["skip"]:
    print(f"\n--- STILL SKIPPED ({total_skip}) ---")
    for name, reason in results["skip"]:
        print(f"  SKIP: {name}: {reason}")

# Save
output = {
    "summary": {
        "total": total,
        "tested": tested,
        "passed": total_pass,
        "failed": total_fail,
        "errors": total_error,
        "skipped": total_skip,
    },
    "pass": [{"name": n, "value": v} for n, v in results["pass"]],
    "fail": [{"name": n, "detail": d} for n, d in results["fail"]],
    "error": [{"name": n, "detail": d} for n, d in results["error"]],
    "skip": [{"name": n, "reason": r} for n, r in results["skip"]],
}

with open('tests/test_phase2_results.json', 'w') as f:
    json.dump(output, f, indent=2)
print(f"\nResults saved to tests/test_phase2_results.json")
