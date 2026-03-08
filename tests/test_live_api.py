#!/usr/bin/env python3
"""
Live API test harness - tests actual DaVinci Resolve API calls.
Run with: python3 tests/test_live_api.py
Requires DaVinci Resolve to be running.
"""

import sys
import json
import traceback

sys.path.insert(0, '/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules')

import DaVinciResolveScript as dvr

def test_api():
    results = {}

    # Connect
    resolve = dvr.scriptapp('Resolve')
    if not resolve:
        print("FATAL: Cannot connect to Resolve")
        return

    print(f"Connected to {resolve.GetProductName()} {resolve.GetVersionString()}")
    print("=" * 60)

    # ===== RESOLVE OBJECT =====
    print("\n--- Resolve Object ---")

    tests = {
        "Resolve.GetProductName": lambda: resolve.GetProductName(),
        "Resolve.GetVersion": lambda: resolve.GetVersion(),
        "Resolve.GetVersionString": lambda: resolve.GetVersionString(),
        "Resolve.GetCurrentPage": lambda: resolve.GetCurrentPage(),
        "Resolve.GetMediaStorage": lambda: resolve.GetMediaStorage() is not None,
        "Resolve.GetProjectManager": lambda: resolve.GetProjectManager() is not None,
        "Resolve.GetKeyframeMode": lambda: resolve.GetKeyframeMode(),
        "Resolve.Fusion": lambda: resolve.Fusion(),
    }

    for name, fn in tests.items():
        try:
            result = fn()
            results[name] = {"status": "OK", "value": str(result)[:100]}
            print(f"  ✓ {name} = {str(result)[:80]}")
        except Exception as e:
            results[name] = {"status": "FAIL", "error": str(e)}
            print(f"  ✗ {name} ERROR: {e}")

    # ===== PROJECT MANAGER =====
    print("\n--- ProjectManager Object ---")
    pm = resolve.GetProjectManager()

    pm_tests = {
        "PM.GetCurrentProject": lambda: pm.GetCurrentProject() is not None,
        "PM.GetProjectListInCurrentFolder": lambda: pm.GetProjectListInCurrentFolder(),
        "PM.GetFolderListInCurrentFolder": lambda: pm.GetFolderListInCurrentFolder(),
        "PM.GetCurrentFolder": lambda: pm.GetCurrentFolder(),
        "PM.GetCurrentDatabase": lambda: pm.GetCurrentDatabase(),
        "PM.GetDatabaseList": lambda: pm.GetDatabaseList(),
    }

    for name, fn in pm_tests.items():
        try:
            result = fn()
            results[name] = {"status": "OK", "value": str(result)[:100]}
            print(f"  ✓ {name} = {str(result)[:80]}")
        except Exception as e:
            results[name] = {"status": "FAIL", "error": str(e)}
            print(f"  ✗ {name} ERROR: {e}")

    # ===== PROJECT =====
    print("\n--- Project Object ---")
    project = pm.GetCurrentProject()

    proj_tests = {
        "Project.GetName": lambda: project.GetName(),
        "Project.GetMediaPool": lambda: project.GetMediaPool() is not None,
        "Project.GetTimelineCount": lambda: project.GetTimelineCount(),
        "Project.GetSetting('')": lambda: project.GetSetting(''),
        "Project.GetRenderFormats": lambda: project.GetRenderFormats(),
        "Project.GetRenderCodecs": lambda: project.GetRenderCodecs('mp4'),
        "Project.GetCurrentRenderFormatAndCodec": lambda: project.GetCurrentRenderFormatAndCodec(),
        "Project.GetCurrentRenderMode": lambda: project.GetCurrentRenderMode(),
        "Project.GetRenderPresetList": lambda: project.GetRenderPresetList(),
        "Project.GetRenderJobList": lambda: project.GetRenderJobList(),
        "Project.IsRenderingInProgress": lambda: project.IsRenderingInProgress(),
        "Project.GetGallery": lambda: project.GetGallery() is not None,
        "Project.GetUniqueId": lambda: project.GetUniqueId(),
        "Project.GetPresetList": lambda: project.GetPresetList(),
        "Project.GetColorGroupsList": lambda: project.GetColorGroupsList(),
        "Project.RefreshLUTList": lambda: project.RefreshLUTList(),
        "Project.GetQuickExportRenderPresets": lambda: project.GetQuickExportRenderPresets(),
        "Project.GetRenderResolutions": lambda: project.GetRenderResolutions('mp4', 'H.264'),
    }

    for name, fn in proj_tests.items():
        try:
            result = fn()
            val_str = str(result)[:100]
            results[name] = {"status": "OK", "value": val_str}
            print(f"  ✓ {name} = {val_str[:80]}")
        except Exception as e:
            results[name] = {"status": "FAIL", "error": str(e)}
            print(f"  ✗ {name} ERROR: {e}")

    # ===== MEDIA STORAGE =====
    print("\n--- MediaStorage Object ---")
    ms = resolve.GetMediaStorage()

    ms_tests = {
        "MS.GetMountedVolumeList": lambda: ms.GetMountedVolumeList(),
        "MS.GetSubFolderList": lambda: ms.GetSubFolderList(ms.GetMountedVolumeList()[0]) if ms.GetMountedVolumeList() else "no volumes",
        "MS.GetFileList": lambda: ms.GetFileList(ms.GetMountedVolumeList()[0])[:5] if ms.GetMountedVolumeList() else "no volumes",
    }

    for name, fn in ms_tests.items():
        try:
            result = fn()
            val_str = str(result)[:100]
            results[name] = {"status": "OK", "value": val_str}
            print(f"  ✓ {name} = {val_str[:80]}")
        except Exception as e:
            results[name] = {"status": "FAIL", "error": str(e)}
            print(f"  ✗ {name} ERROR: {e}")

    # ===== MEDIA POOL =====
    print("\n--- MediaPool Object ---")
    mp = project.GetMediaPool()

    mp_tests = {
        "MP.GetRootFolder": lambda: mp.GetRootFolder() is not None,
        "MP.GetCurrentFolder": lambda: mp.GetCurrentFolder() is not None,
        "MP.GetUniqueId": lambda: mp.GetUniqueId(),
        "MP.GetSelectedClips": lambda: mp.GetSelectedClips(),
    }

    for name, fn in mp_tests.items():
        try:
            result = fn()
            val_str = str(result)[:100]
            results[name] = {"status": "OK", "value": val_str}
            print(f"  ✓ {name} = {val_str[:80]}")
        except Exception as e:
            results[name] = {"status": "FAIL", "error": str(e)}
            print(f"  ✗ {name} ERROR: {e}")

    # ===== FOLDER =====
    print("\n--- Folder Object ---")
    root = mp.GetRootFolder()

    folder_tests = {
        "Folder.GetName": lambda: root.GetName(),
        "Folder.GetClipList": lambda: root.GetClipList(),
        "Folder.GetSubFolderList": lambda: root.GetSubFolderList(),
        "Folder.GetIsFolderStale": lambda: root.GetIsFolderStale(),
        "Folder.GetUniqueId": lambda: root.GetUniqueId(),
    }

    for name, fn in folder_tests.items():
        try:
            result = fn()
            val_str = str(result)[:100]
            results[name] = {"status": "OK", "value": val_str}
            print(f"  ✓ {name} = {val_str[:80]}")
        except Exception as e:
            results[name] = {"status": "FAIL", "error": str(e)}
            print(f"  ✗ {name} ERROR: {e}")

    # ===== GALLERY =====
    print("\n--- Gallery Object ---")
    gallery = project.GetGallery()

    if gallery:
        gallery_tests = {
            "Gallery.GetAlbumName": lambda: gallery.GetAlbumName(),
            "Gallery.GetCurrentStillAlbum": lambda: gallery.GetCurrentStillAlbum() is not None,
            "Gallery.GetGalleryStillAlbums": lambda: gallery.GetGalleryStillAlbums(),
            "Gallery.GetGalleryPowerGradeAlbums": lambda: gallery.GetGalleryPowerGradeAlbums(),
        }

        for name, fn in gallery_tests.items():
            try:
                result = fn()
                val_str = str(result)[:100]
                results[name] = {"status": "OK", "value": val_str}
                print(f"  ✓ {name} = {val_str[:80]}")
            except Exception as e:
                results[name] = {"status": "FAIL", "error": str(e)}
                print(f"  ✗ {name} ERROR: {e}")

        # ===== GALLERY STILL ALBUM =====
        print("\n--- GalleryStillAlbum Object ---")
        album = gallery.GetCurrentStillAlbum()
        if album:
            album_tests = {
                "GSA.GetStills": lambda: album.GetStills(),
                "GSA.GetLabel": lambda: album.GetLabel(album.GetStills()[0]) if album.GetStills() else "no stills",
            }
            for name, fn in album_tests.items():
                try:
                    result = fn()
                    val_str = str(result)[:100]
                    results[name] = {"status": "OK", "value": val_str}
                    print(f"  ✓ {name} = {val_str[:80]}")
                except Exception as e:
                    results[name] = {"status": "FAIL", "error": str(e)}
                    print(f"  ✗ {name} ERROR: {e}")

    # ===== TIMELINE (if any) =====
    if project.GetTimelineCount() > 0:
        print("\n--- Timeline Object ---")
        tl = project.GetCurrentTimeline()
        if tl:
            tl_tests = {
                "TL.GetName": lambda: tl.GetName(),
                "TL.GetStartFrame": lambda: tl.GetStartFrame(),
                "TL.GetEndFrame": lambda: tl.GetEndFrame(),
                "TL.GetTrackCount('video')": lambda: tl.GetTrackCount('video'),
                "TL.GetTrackCount('audio')": lambda: tl.GetTrackCount('audio'),
                "TL.GetStartTimecode": lambda: tl.GetStartTimecode(),
                "TL.GetCurrentTimecode": lambda: tl.GetCurrentTimecode(),
                "TL.GetMarkers": lambda: tl.GetMarkers(),
                "TL.GetSetting('')": lambda: tl.GetSetting(''),
                "TL.GetUniqueId": lambda: tl.GetUniqueId(),
                "TL.GetCurrentVideoItem": lambda: tl.GetCurrentVideoItem(),
            }

            for name, fn in tl_tests.items():
                try:
                    result = fn()
                    val_str = str(result)[:100]
                    results[name] = {"status": "OK", "value": val_str}
                    print(f"  ✓ {name} = {val_str[:80]}")
                except Exception as e:
                    results[name] = {"status": "FAIL", "error": str(e)}
                    print(f"  ✗ {name} ERROR: {e}")
    else:
        print("\n--- Timeline: SKIPPED (no timelines in project) ---")
        # Create a test timeline so we can test more
        print("  Creating test timeline...")
        try:
            tl = mp.CreateEmptyTimeline("API_Test_Timeline")
            if tl:
                print(f"  ✓ Created timeline: {tl.GetName()}")
                results["MP.CreateEmptyTimeline"] = {"status": "OK", "value": tl.GetName()}

                # Now test timeline methods
                tl_tests = {
                    "TL.GetName": lambda: tl.GetName(),
                    "TL.GetStartFrame": lambda: tl.GetStartFrame(),
                    "TL.GetEndFrame": lambda: tl.GetEndFrame(),
                    "TL.GetTrackCount('video')": lambda: tl.GetTrackCount('video'),
                    "TL.GetTrackCount('audio')": lambda: tl.GetTrackCount('audio'),
                    "TL.GetStartTimecode": lambda: tl.GetStartTimecode(),
                    "TL.GetCurrentTimecode": lambda: tl.GetCurrentTimecode(),
                    "TL.GetMarkers": lambda: tl.GetMarkers(),
                    "TL.GetSetting('')": lambda: tl.GetSetting(''),
                    "TL.GetUniqueId": lambda: tl.GetUniqueId(),
                    "TL.GetNodeGraph": lambda: tl.GetNodeGraph() is not None,
                    "TL.GetMarkInOut": lambda: tl.GetMarkInOut(),
                }

                for name, fn in tl_tests.items():
                    try:
                        result = fn()
                        val_str = str(result)[:100]
                        results[name] = {"status": "OK", "value": val_str}
                        print(f"  ✓ {name} = {val_str[:80]}")
                    except Exception as e:
                        results[name] = {"status": "FAIL", "error": str(e)}
                        print(f"  ✗ {name} ERROR: {e}")
        except Exception as e:
            print(f"  ✗ Could not create timeline: {e}")

    # ===== COLOR GROUPS =====
    print("\n--- ColorGroup Object ---")
    try:
        groups = project.GetColorGroupsList()
        if groups and len(groups) > 0:
            cg = groups[0]
            cg_tests = {
                "CG.GetName": lambda: cg.GetName(),
                "CG.GetPreClipNodeGraph": lambda: cg.GetPreClipNodeGraph() is not None,
                "CG.GetPostClipNodeGraph": lambda: cg.GetPostClipNodeGraph() is not None,
            }
            for name, fn in cg_tests.items():
                try:
                    result = fn()
                    val_str = str(result)[:100]
                    results[name] = {"status": "OK", "value": val_str}
                    print(f"  ✓ {name} = {val_str[:80]}")
                except Exception as e:
                    results[name] = {"status": "FAIL", "error": str(e)}
                    print(f"  ✗ {name} ERROR: {e}")
        else:
            print("  No color groups found")
    except Exception as e:
        print(f"  ✗ GetColorGroupsList ERROR: {e}")

    # ===== SUMMARY =====
    print("\n" + "=" * 60)
    ok = sum(1 for v in results.values() if v["status"] == "OK")
    fail = sum(1 for v in results.values() if v["status"] == "FAIL")
    print(f"RESULTS: {ok} passed, {fail} failed, {ok+fail} total")
    print(f"Pass rate: {ok/(ok+fail)*100:.1f}%")

    # Save results
    with open('tests/live_api_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nDetailed results saved to tests/live_api_results.json")

if __name__ == "__main__":
    test_api()
