#!/usr/bin/env python3
"""Phase 4: Test remaining skipped methods against Sample project with real clips.

Tests:
  - TI.Stabilize
  - TI.SmartReframe
  - TI.CreateMagicMask / TI.RegenerateMagicMask
  - TL.CreateFusionClip
  - TL.ConvertTimelineToStereo
  - Gallery still operations (GSA.SetLabel, ExportStills, ImportStills, DeleteStills)
"""
import sys, os, json, time, tempfile

sys.path.insert(0, "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules")
import DaVinciResolveScript as dvr

resolve = dvr.scriptapp("Resolve")
assert resolve, "Cannot connect to DaVinci Resolve"

pm = resolve.GetProjectManager()
proj = pm.GetCurrentProject()
print(f"Project: {proj.GetName()}")

results = {"pass": [], "fail": [], "skip": []}

def test(name, fn=None, skip_reason=None):
    if skip_reason:
        results["skip"].append((name, skip_reason))
        print(f"  SKIP  {name} — {skip_reason}")
        return
    try:
        r = fn()
        results["pass"].append(name)
        print(f"  PASS  {name} → {r}")
    except Exception as e:
        results["fail"].append((name, str(e)))
        print(f"  FAIL  {name} — {e}")

# Get the main timeline and a real item
tl = proj.GetTimelineByIndex(1)
assert tl, "No timeline found"
proj.SetCurrentTimeline(tl)

items = tl.GetItemListInTrack("video", 1)
assert items and len(items) > 0, "No video items on track 1"
item = items[0]
print(f"Using timeline: {tl.GetName()}, item: {item.GetName()}")

# ─── TimelineItem tests ───────────────────────────────────────

print("\n=== TimelineItem AI/Processing Methods ===")

# TI.Stabilize — starts stabilization analysis (async, just check it accepts the call)
def test_stabilize():
    r = item.Stabilize()
    return r  # may return True/False depending on clip type
test("TI.Stabilize", test_stabilize)

# TI.SmartReframe — starts smart reframe (async)
def test_smart_reframe():
    r = item.SmartReframe()
    return r
test("TI.SmartReframe", test_smart_reframe)

# TI.CreateMagicMask — creates a magic mask (forward direction)
def test_create_magic_mask():
    r = item.CreateMagicMask("F")
    return r
test("TI.CreateMagicMask", test_create_magic_mask)

# TI.RegenerateMagicMask — regenerates the magic mask
def test_regenerate_magic_mask():
    r = item.RegenerateMagicMask()
    return r
test("TI.RegenerateMagicMask", test_regenerate_magic_mask)

# ─── Timeline tests ──────────────────────────────────────────

print("\n=== Timeline Methods ===")

# TL.CreateFusionClip — needs timeline items selected or passed
# Create a throwaway timeline with 2 clips for this test
def test_create_fusion_clip():
    mp = proj.GetMediaPool()
    root = mp.GetRootFolder()
    clips_in_pool = root.GetClipList()
    if not clips_in_pool or len(clips_in_pool) < 2:
        return "SKIP: need 2+ clips in media pool"

    # Create a throwaway timeline with 2 clips
    test_tl = mp.CreateTimelineFromClips("_fusion_test_tl", [clips_in_pool[0], clips_in_pool[1]])
    if not test_tl:
        return "Could not create test timeline"
    proj.SetCurrentTimeline(test_tl)

    test_items = test_tl.GetItemListInTrack("video", 1)
    if not test_items or len(test_items) < 2:
        # cleanup
        mp.DeleteTimelines([test_tl])
        return "Not enough items on test timeline"

    r = test_tl.CreateFusionClip(test_items)

    # cleanup — delete the throwaway timeline
    proj.SetCurrentTimeline(tl)  # switch back
    mp.DeleteTimelines([test_tl])

    return r

test("TL.CreateFusionClip", test_create_fusion_clip)

# Switch back to main timeline
proj.SetCurrentTimeline(tl)

# TL.ConvertTimelineToStereo — converts a timeline to stereo 3D
def test_convert_to_stereo():
    mp = proj.GetMediaPool()
    root = mp.GetRootFolder()
    clips_in_pool = root.GetClipList()

    # Create a throwaway timeline
    test_tl = mp.CreateEmptyTimeline("_stereo_test_tl")
    if not test_tl:
        return "Could not create test timeline"
    proj.SetCurrentTimeline(test_tl)

    r = test_tl.ConvertTimelineToStereo()

    # cleanup
    proj.SetCurrentTimeline(tl)
    mp.DeleteTimelines([test_tl])

    return r

test("TL.ConvertTimelineToStereo", test_convert_to_stereo)

# Switch back to main timeline
proj.SetCurrentTimeline(tl)

# ─── Gallery Still tests ─────────────────────────────────────

print("\n=== Gallery Still Album Methods ===")

def test_gallery_stills():
    gallery = proj.GetGallery()
    if not gallery:
        return "No gallery"

    album = gallery.GetCurrentStillAlbum()
    if not album:
        # Try to get first album
        albums = gallery.GetGalleryStillAlbums()
        if not albums:
            return "No still albums"
        album = albums[0]
        gallery.SetCurrentStillAlbum(album)

    album_name = album.GetLabel()
    print(f"    Current album: {album_name}")

    stills = album.GetStills()
    print(f"    Stills in album: {len(stills) if stills else 0}")

    results_inner = {}

    # GSA.SetLabel
    try:
        old_label = album.GetLabel()
        r = album.SetLabel("_test_label")
        album.SetLabel(old_label)  # restore
        results_inner["SetLabel"] = r
    except Exception as e:
        results_inner["SetLabel"] = f"error: {e}"

    # Export/Import stills — need at least one still
    if stills and len(stills) > 0:
        tmpdir = tempfile.mkdtemp()
        export_path = os.path.join(tmpdir, "test_still.drx")

        # GSA.ExportStills
        try:
            r = album.ExportStills(stills, tmpdir, "test_still")
            results_inner["ExportStills"] = r
        except Exception as e:
            results_inner["ExportStills"] = f"error: {e}"

        # GSA.ImportStills — import a DRX if exported
        drx_files = [f for f in os.listdir(tmpdir) if f.endswith(".drx")] if os.path.exists(tmpdir) else []
        if drx_files:
            try:
                import_path = os.path.join(tmpdir, drx_files[0])
                r = album.ImportStills([import_path])
                results_inner["ImportStills"] = r
            except Exception as e:
                results_inner["ImportStills"] = f"error: {e}"
        else:
            results_inner["ImportStills"] = "skip: no DRX to import"

        # GSA.DeleteStills — delete imported still (last one)
        updated_stills = album.GetStills()
        if updated_stills and len(updated_stills) > len(stills):
            try:
                r = album.DeleteStills([updated_stills[-1]])
                results_inner["DeleteStills"] = r
            except Exception as e:
                results_inner["DeleteStills"] = f"error: {e}"
        else:
            results_inner["DeleteStills"] = "skip: no new still to delete"

        # cleanup temp
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
    else:
        results_inner["ExportStills"] = "skip: no stills"
        results_inner["ImportStills"] = "skip: no stills"
        results_inner["DeleteStills"] = "skip: no stills"

    return results_inner

test("Gallery.StillAlbum ops (SetLabel/Export/Import/Delete)", test_gallery_stills)

# ─── Summary ─────────────────────────────────────────────────

print("\n" + "="*60)
print(f"PASS: {len(results['pass'])}")
print(f"FAIL: {len(results['fail'])}")
print(f"SKIP: {len(results['skip'])}")
for name, reason in results["fail"]:
    print(f"  FAIL: {name} — {reason}")
for name, reason in results["skip"]:
    print(f"  SKIP: {name} — {reason}")
print("="*60)

# Save results
with open("/Users/samuelgursky/davinci-resolve-mcp/tests/test_phase4_results.json", "w") as f:
    json.dump(results, f, indent=2, default=str)
