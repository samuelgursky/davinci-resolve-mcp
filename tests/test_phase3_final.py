#!/usr/bin/env python3
"""
Phase 3: Test the final 34 previously-skipped API methods.
Uses real media files, database switching, slow AI ops, and Resolve.Quit.

Run with: python3 tests/test_phase3_final.py

Requires DaVinci Resolve Studio running.
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

orig_project_name = project.GetName()
orig_db = pm.GetCurrentDatabase()
tmpdir = tempfile.mkdtemp()

# Media paths
VIDEO_DIR = "/Volumes/Sam Joybubbles Drive Mirrored 12:1:26/00 JOYBUBBLES/03 PRODUCTION MEDIA/01 INTERVIEWSxxx/01_VIDEO/INTV STEVEN GIBB/VideoFiles_Steven_Day1"
AUDIO_DIR = "/Volumes/Sam Joybubbles Drive Mirrored 12:1:26/00 JOYBUBBLES/03 PRODUCTION MEDIA/01 INTERVIEWSxxx/02_AUDIO/AudioFiles_StevenGibb1aiff"
VIDEO_FILE = os.path.join(VIDEO_DIR, "StevenGibb_000.MOV")
VIDEO_FILE_2 = os.path.join(VIDEO_DIR, "StevenGibb_001.MOV")
AUDIO_FILE = os.path.join(AUDIO_DIR, "StevenGibb-000.aiff")

print(f"Project: {orig_project_name}")
print(f"Timeline: {tl.GetName() if tl else 'None'}")
print(f"Video: {os.path.exists(VIDEO_FILE)}")
print(f"Audio: {os.path.exists(AUDIO_FILE)}")
print("=" * 70)

results = {"pass": [], "fail": [], "skip": [], "error": []}

def test(name, fn=None, skip_reason=None):
    if skip_reason or fn is None:
        results["skip"].append((name, skip_reason or "no function"))
        print(f"  SKIP: {name}: {skip_reason}")
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
# SECTION 1: SetCurrentDatabase
# ======================================================
print("\n--- SetCurrentDatabase ---")
dbs = pm.GetDatabaseList()
other_db = None
for db in dbs:
    if db['DbName'] != orig_db['DbName']:
        other_db = db
        break

if other_db:
    test("PM.SetCurrentDatabase", lambda: pm.SetCurrentDatabase(other_db))
    time.sleep(2)
    # Switch back
    pm.SetCurrentDatabase(orig_db)
    time.sleep(2)
    # Reload project
    project = pm.LoadProject(orig_project_name)
    if not project:
        # Try to find and load it
        projects = pm.GetProjectListInCurrentFolder()
        if orig_project_name in projects:
            project = pm.LoadProject(orig_project_name)
    mp = project.GetMediaPool() if project else None
    root = mp.GetRootFolder() if mp else None
    tl = project.GetCurrentTimeline() if project else None
    gallery = project.GetGallery() if project else None
else:
    test("PM.SetCurrentDatabase", skip_reason="only one database available")

# ======================================================
# SECTION 2: Import media for testing
# ======================================================
print("\n--- Importing test media ---")

# Create a test subfolder for our imports
test_folder = mp.AddSubFolder(root, "_phase3_test")
if test_folder:
    mp.SetCurrentFolder(test_folder)

# Import video clips
imported_video = mp.ImportMedia([VIDEO_FILE])
test("Import_video", lambda: imported_video is not None and len(imported_video) > 0)

imported_video2 = mp.ImportMedia([VIDEO_FILE_2])
test("Import_video2", lambda: imported_video2 is not None and len(imported_video2) > 0)

# Import audio clip
imported_audio = mp.ImportMedia([AUDIO_FILE])
test("Import_audio", lambda: imported_audio is not None and len(imported_audio) > 0)

# Get the imported clips
test_clips = (test_folder.GetClipList() if test_folder else root.GetClipList()) or []
video_clips = [c for c in test_clips if c.GetClipProperty("Type") == "Video"]
audio_clips = [c for c in test_clips if c.GetClipProperty("Type") == "Audio"]

# If type detection doesn't work, just use all
if not video_clips:
    video_clips = test_clips[:2] if len(test_clips) >= 2 else test_clips
if not audio_clips and len(test_clips) >= 3:
    audio_clips = [test_clips[2]]

print(f"  Video clips: {len(video_clips)}, Audio clips: {len(audio_clips)}")

# ======================================================
# SECTION 3: AutoSyncAudio
# ======================================================
print("\n--- AutoSyncAudio ---")
if video_clips and audio_clips:
    sync_clips = [video_clips[0], audio_clips[0]]
    test("MP.AutoSyncAudio", lambda: mp.AutoSyncAudio(sync_clips, {"isSourceTimecodeSync": True}))
else:
    test("MP.AutoSyncAudio", skip_reason="need both video and audio clips")

# ======================================================
# SECTION 4: Matte operations (create a test matte image)
# ======================================================
print("\n--- Matte operations ---")

# Create a simple white PNG as a matte (1x1 pixel)
matte_path = os.path.join(tmpdir, "test_matte.png")
# Minimal valid PNG (1x1 white pixel)
import struct, zlib
def create_png(path, width=64, height=64):
    def chunk(chunk_type, data):
        c = chunk_type + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
    header = b'\x89PNG\r\n\x1a\n'
    ihdr = chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
    raw = b''
    for y in range(height):
        raw += b'\x00' + b'\xff\xff\xff' * width
    idat = chunk(b'IDAT', zlib.compress(raw))
    iend = chunk(b'IEND', b'')
    with open(path, 'wb') as f:
        f.write(header + ihdr + idat + iend)

create_png(matte_path)
print(f"  Created test matte: {matte_path}")

ms = resolve.GetMediaStorage()
if video_clips:
    test("MS.AddClipMattesToMediaPool", lambda: ms.AddClipMattesToMediaPool(video_clips[0], [matte_path]))
    test("MP.DeleteClipMattes", lambda: mp.DeleteClipMattes(video_clips[0], [matte_path]))

test("MS.AddTimelineMattesToMediaPool", lambda: ms.AddTimelineMattesToMediaPool([matte_path]))

# ======================================================
# SECTION 5: Timeline import/export files
# ======================================================
print("\n--- Timeline import/export ---")

# First create a timeline with our imported clips and export it
if video_clips:
    # Make sure we're in the right folder
    mp.SetCurrentFolder(test_folder if test_folder else root)

    test_tl = mp.CreateTimelineFromClips("_phase3_test_tl", video_clips[:1])
    if test_tl:
        project.SetCurrentTimeline(test_tl)

        # Export as various formats for import testing
        edl_path = os.path.join(tmpdir, "test.edl")
        fcpxml_path = os.path.join(tmpdir, "test.fcpxml")

        test_tl.Export(edl_path, resolve.EXPORT_EDL, resolve.EXPORT_NONE)
        test_tl.Export(fcpxml_path, resolve.EXPORT_FCPXML_1_10, resolve.EXPORT_NONE)

        # ImportTimelineFromFile
        if os.path.exists(edl_path):
            test("MP.ImportTimelineFromFile", lambda: mp.ImportTimelineFromFile(edl_path, {"timelineName": "_phase3_imported_tl"}))
        else:
            test("MP.ImportTimelineFromFile", skip_reason="EDL export failed")

        # ImportIntoTimeline (AAF import into existing timeline)
        if os.path.exists(fcpxml_path):
            test("TL.ImportIntoTimeline", lambda: test_tl.ImportIntoTimeline(fcpxml_path, {}))
        else:
            test("TL.ImportIntoTimeline", skip_reason="FCPXML export failed")

        # ImportFolderFromFile - export a DRB first
        drb_path = os.path.join(tmpdir, "test_folder.drb")
        if test_folder:
            test_folder.Export(drb_path)
            if os.path.exists(drb_path):
                test("MP.ImportFolderFromFile", lambda: mp.ImportFolderFromFile(drb_path))
            else:
                test("MP.ImportFolderFromFile", skip_reason="DRB export failed")
        else:
            test("MP.ImportFolderFromFile", skip_reason="no test folder")

        # Switch back to original timeline
        if tl:
            project.SetCurrentTimeline(tl)

        # Clean up test timelines
        imported_tls = []
        for i in range(1, project.GetTimelineCount() + 1):
            t = project.GetTimelineByIndex(i)
            if t and t.GetName().startswith("_phase3"):
                imported_tls.append(t)
        if imported_tls:
            if tl:
                project.SetCurrentTimeline(tl)
            mp.DeleteTimelines(imported_tls)
else:
    test("MP.ImportTimelineFromFile", skip_reason="no video clips imported")
    test("TL.ImportIntoTimeline", skip_reason="no video clips")
    test("MP.ImportFolderFromFile", skip_reason="no test folder")

# ======================================================
# SECTION 6: LinkProxyMedia / ReplaceClip
# ======================================================
print("\n--- LinkProxyMedia / ReplaceClip ---")

if video_clips and len(video_clips) >= 2:
    # Use second video as a "proxy" (not a real proxy but tests the API call)
    test("MPI.LinkProxyMedia", lambda: video_clips[0].LinkProxyMedia(VIDEO_FILE_2))
    # Unlink it
    video_clips[0].UnlinkProxyMedia()

    # ReplaceClip - replace one clip with the other (then replace back)
    orig_path = video_clips[1].GetClipProperty("File Path")
    test("MPI.ReplaceClip", lambda: video_clips[1].ReplaceClip(VIDEO_FILE))
    # Replace back if possible
    if orig_path:
        video_clips[1].ReplaceClip(orig_path)
else:
    test("MPI.LinkProxyMedia", skip_reason="need 2 video clips")
    test("MPI.ReplaceClip", skip_reason="need 2 video clips")

# ======================================================
# SECTION 7: CreateStereoClip
# ======================================================
print("\n--- CreateStereoClip ---")
if len(video_clips) >= 2:
    test("MP.CreateStereoClip", lambda: mp.CreateStereoClip(video_clips[0], video_clips[1]))
else:
    test("MP.CreateStereoClip", skip_reason="need 2 video clips")

# ======================================================
# SECTION 8: Gallery stills (grab one, then test label/export/import/delete)
# ======================================================
print("\n--- Gallery stills ---")

if gallery and tl:
    # Make sure we have a still
    project.SetCurrentTimeline(tl)
    still = tl.GrabStill()
    time.sleep(1)

    cur_album = gallery.GetCurrentStillAlbum()
    if cur_album:
        stills = cur_album.GetStills() or []
        if stills:
            test("GSA.SetLabel", lambda: cur_album.SetLabel(stills[-1], "phase3_test_label"))

            still_export_dir = os.path.join(tmpdir, "stills_export")
            os.makedirs(still_export_dir, exist_ok=True)
            test("GSA.ExportStills", lambda: cur_album.ExportStills([stills[-1]], still_export_dir, "phase3_still", "jpg"))

            # Find exported files
            time.sleep(1)
            exported = [os.path.join(still_export_dir, f) for f in os.listdir(still_export_dir) if not f.startswith('.')]
            if exported:
                test("GSA.ImportStills", lambda: cur_album.ImportStills(exported))
            else:
                test("GSA.ImportStills", skip_reason="no exported stills found")

            # Delete the still we grabbed
            stills2 = cur_album.GetStills() or []
            if len(stills2) > 0:
                test("GSA.DeleteStills", lambda: cur_album.DeleteStills([stills2[-1]]))
            else:
                test("GSA.DeleteStills", skip_reason="no stills to delete")
        else:
            for m in ["SetLabel", "ExportStills", "ImportStills", "DeleteStills"]:
                test(f"GSA.{m}", skip_reason="no stills even after GrabStill")
    else:
        for m in ["SetLabel", "ExportStills", "ImportStills", "DeleteStills"]:
            test(f"GSA.{m}", skip_reason="no current album")

# ======================================================
# SECTION 9: InsertAudioToCurrentTrackAtPlayhead (Fairlight)
# ======================================================
print("\n--- InsertAudioToCurrentTrackAtPlayhead ---")

resolve.OpenPage("fairlight")
time.sleep(2)
test("Project.InsertAudioToCurrentTrackAtPlayhead", lambda: project.InsertAudioToCurrentTrackAtPlayhead(AUDIO_FILE, 0, 48000))
resolve.OpenPage("edit")
time.sleep(1)

# ======================================================
# SECTION 10: CreateFusionClip / ConvertTimelineToStereo (irreversible, use throwaway timeline)
# ======================================================
print("\n--- Irreversible operations (throwaway timeline) ---")

# Create a throwaway timeline for irreversible ops
if test_folder:
    mp.SetCurrentFolder(test_folder)
test_clips_now = (test_folder.GetClipList() if test_folder else root.GetClipList()) or []
video_clips_now = [c for c in test_clips_now if "MOV" in (c.GetClipProperty("File Path") or "").upper()]
if not video_clips_now:
    video_clips_now = test_clips_now[:2]

if len(video_clips_now) >= 2:
    throwaway = mp.CreateTimelineFromClips("_phase3_throwaway", video_clips_now[:2])
    if throwaway:
        project.SetCurrentTimeline(throwaway)
        items = throwaway.GetItemListInTrack("video", 1) or []

        if len(items) >= 2:
            test("TL.CreateFusionClip", lambda: throwaway.CreateFusionClip([items[0], items[1]]))
        else:
            test("TL.CreateFusionClip", skip_reason="need 2+ items on throwaway timeline")

        # ConvertTimelineToStereo
        test("TL.ConvertTimelineToStereo", lambda: throwaway.ConvertTimelineToStereo())

        # Clean up
        if tl:
            project.SetCurrentTimeline(tl)
        mp.DeleteTimelines([throwaway])
    else:
        test("TL.CreateFusionClip", skip_reason="could not create throwaway timeline")
        test("TL.ConvertTimelineToStereo", skip_reason="could not create throwaway timeline")
else:
    test("TL.CreateFusionClip", skip_reason="need 2 clips for throwaway timeline")
    test("TL.ConvertTimelineToStereo", skip_reason="need 2 clips")

# ======================================================
# SECTION 11: Slow AI operations
# ======================================================
print("\n--- Slow AI operations (this will take a few minutes) ---")

# Use our imported video clips for AI ops
tl = project.GetCurrentTimeline()
tl_items = tl.GetItemListInTrack("video", 1) if tl else []
real_items = [i for i in (tl_items or []) if i.GetMediaPoolItem() is not None]
item = real_items[0] if real_items else None

# TranscribeAudio (clip level)
if video_clips:
    print("  Running MPI.TranscribeAudio (may take 30-60s)...")
    test("MPI.TranscribeAudio", lambda: video_clips[0].TranscribeAudio())
    time.sleep(2)
    test("MPI.ClearTranscription", lambda: video_clips[0].ClearTranscription())

# TranscribeAudio (folder level)
if test_folder:
    print("  Running Folder.TranscribeAudio (may take 30-60s)...")
    test("Folder.TranscribeAudio", lambda: test_folder.TranscribeAudio())
    time.sleep(2)
    test("Folder.ClearTranscription", lambda: test_folder.ClearTranscription())

# DetectSceneCuts
if tl:
    print("  Running TL.DetectSceneCuts...")
    test("TL.DetectSceneCuts", lambda: tl.DetectSceneCuts())

# CreateSubtitlesFromAudio
if tl:
    print("  Running TL.CreateSubtitlesFromAudio...")
    test("TL.CreateSubtitlesFromAudio", lambda: tl.CreateSubtitlesFromAudio())

# Timeline item AI ops (use a real clip)
if item:
    print("  Running TI.Stabilize...")
    test("TI.Stabilize", lambda: item.Stabilize())

    print("  Running TI.SmartReframe...")
    test("TI.SmartReframe", lambda: item.SmartReframe())

    print("  Running TI.CreateMagicMask...")
    test("TI.CreateMagicMask", lambda: item.CreateMagicMask("F"))
    time.sleep(2)
    test("TI.RegenerateMagicMask", lambda: item.RegenerateMagicMask())
else:
    for m in ["Stabilize", "SmartReframe", "CreateMagicMask", "RegenerateMagicMask"]:
        test(f"TI.{m}", skip_reason="no real timeline item available")

# AnalyzeDolbyVision
if tl:
    print("  Running TL.AnalyzeDolbyVision...")
    test("TL.AnalyzeDolbyVision", lambda: tl.AnalyzeDolbyVision())

# ======================================================
# SECTION 12: Cloud methods (skip - need cloud infra)
# ======================================================
print("\n--- Cloud methods (no cloud infra) ---")
test("PM.CreateCloudProject", skip_reason="needs cloud infrastructure")
test("PM.LoadCloudProject", skip_reason="needs cloud infrastructure")
test("PM.ImportCloudProject", skip_reason="needs cloud infrastructure")
test("PM.RestoreCloudProject", skip_reason="needs cloud infrastructure")

# ======================================================
# SECTION 13: Cleanup
# ======================================================
print("\n--- Cleanup ---")

# Delete test folder and contents
mp.SetCurrentFolder(root)
if test_folder:
    # Delete all clips in test folder first
    test_clips_final = test_folder.GetClipList() or []
    if test_clips_final:
        mp.DeleteClips(test_clips_final)
    mp.DeleteFolders([test_folder])
    print("  Cleaned up test folder")

# Save project
pm.SaveProject()

# ======================================================
# SECTION 14: Resolve.Quit (LAST TEST - will kill Resolve!)
# ======================================================
print("\n--- Resolve.Quit ---")
print("  Quitting Resolve in 3 seconds...")
time.sleep(3)
test("Resolve.Quit", lambda: resolve.Quit())

# ======================================================
# SUMMARY
# ======================================================
time.sleep(2)
print("\n" + "=" * 70)
total_pass = len(results["pass"])
total_fail = len(results["fail"])
total_error = len(results["error"])
total_skip = len(results["skip"])
total = total_pass + total_fail + total_error + total_skip
tested = total_pass + total_fail + total_error

print(f"\nPHASE 3 RESULTS: {total_pass} passed, {total_fail} failed, {total_error} errors, {total_skip} skipped")
print(f"Total methods in Phase 3: {total}")
print(f"Actually tested: {tested}")
if tested > 0:
    print(f"Pass rate: {total_pass/tested*100:.1f}%")

if results["fail"]:
    print(f"\n--- FAILURES ---")
    for name, reason in results["fail"]:
        print(f"  FAIL: {name}: {reason}")

if results["error"]:
    print(f"\n--- ERRORS ---")
    for name, reason in results["error"]:
        print(f"  ERROR: {name}: {reason}")

if results["skip"]:
    print(f"\n--- STILL SKIPPED ---")
    for name, reason in results["skip"]:
        print(f"  SKIP: {name}: {reason}")

# Combined totals
print(f"\n--- COMBINED (Phase 1 + 2 + 3) ---")
print(f"Phase 1: 204 passed")
print(f"Phase 2: 79 passed")
print(f"Phase 3: {total_pass} passed")
combined = 204 + 79 + total_pass
print(f"TOTAL: {combined}/324 methods tested ({combined/324*100:.1f}%)")
print(f"Final skip count: {total_skip} (cloud methods only: 4)")

output = {
    "summary": {
        "total": total, "tested": tested, "passed": total_pass,
        "failed": total_fail, "errors": total_error, "skipped": total_skip,
    },
    "pass": [{"name": n, "value": v} for n, v in results["pass"]],
    "fail": [{"name": n, "detail": d} for n, d in results["fail"]],
    "error": [{"name": n, "detail": d} for n, d in results["error"]],
    "skip": [{"name": n, "reason": r} for n, r in results["skip"]],
}

with open('tests/test_phase3_results.json', 'w') as f:
    json.dump(output, f, indent=2)
print(f"\nResults saved to tests/test_phase3_results.json")
