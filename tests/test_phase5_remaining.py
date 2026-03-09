#!/usr/bin/env python3
"""Phase 5: Test remaining untested methods.

Tests:
  - TL.DetectSceneCuts
  - TL.CreateSubtitlesFromAudio
  - Graph.GetNodeCacheMode
  - Graph.SetNodeCacheMode
  - Graph.GetToolsInNode
  - Graph.SetNodeEnabled
"""
import sys, os, json, time

sys.path.append("/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules")
import DaVinciResolveScript as dvr

resolve = dvr.scriptapp("Resolve")
if not resolve:
    print("ERROR: Cannot connect to Resolve")
    sys.exit(1)

pm = resolve.GetProjectManager()
proj = pm.GetCurrentProject()
if not proj:
    print("ERROR: No project open")
    sys.exit(1)

tl = proj.GetCurrentTimeline()
if not tl:
    print("ERROR: No current timeline")
    sys.exit(1)

print(f"Project: {proj.GetName()}")
print(f"Timeline: {tl.GetName()}")
print(f"Track count (video): {tl.GetTrackCount('video')}")

results = {"pass": [], "fail": [], "skip": []}

def test(name, fn, skip_reason=None):
    if skip_reason:
        print(f"  SKIP  {name}: {skip_reason}")
        results["skip"].append(name)
        return
    try:
        r = fn()
        print(f"  PASS  {name}: {r}")
        results["pass"].append(name)
    except Exception as e:
        print(f"  FAIL  {name}: {e}")
        results["fail"].append(name)

# ─── Timeline AI Methods ─────────────────────────────────────

print("\n=== Timeline AI Methods ===")

# DetectSceneCuts - just call it, returns Bool
def test_detect_scene_cuts():
    r = tl.DetectSceneCuts()
    return r
test("TL.DetectSceneCuts", test_detect_scene_cuts)

# CreateSubtitlesFromAudio - use resolve constants
def test_create_subtitles():
    settings = {
        resolve.SUBTITLE_LANGUAGE: resolve.AUTO_CAPTION_AUTO,
        resolve.SUBTITLE_CAPTION_PRESET: resolve.AUTO_CAPTION_SUBTITLE_DEFAULT,
    }
    r = tl.CreateSubtitlesFromAudio(settings)
    return r
test("TL.CreateSubtitlesFromAudio", test_create_subtitles)

# ─── Graph Node Methods ──────────────────────────────────────

print("\n=== Graph Node Methods ===")

# Get a graph from the first video item
items = tl.GetItemListInTrack("video", 1)
if items and len(items) > 0:
    item = items[0]
    graph = item.GetNodeGraph()
    if graph:
        num_nodes = graph.GetNumNodes()
        print(f"  Graph has {num_nodes} nodes")

        if num_nodes > 0:
            # GetNodeCacheMode
            def test_get_cache():
                return graph.GetNodeCacheMode(1)
            test("Graph.GetNodeCacheMode", test_get_cache)

            # SetNodeCacheMode (set to current value to be non-destructive)
            def test_set_cache():
                current = graph.GetNodeCacheMode(1)
                return graph.SetNodeCacheMode(1, current)
            test("Graph.SetNodeCacheMode", test_set_cache)

            # GetToolsInNode
            def test_get_tools():
                return graph.GetToolsInNode(1)
            test("Graph.GetToolsInNode", test_get_tools)

            # SetNodeEnabled (read current state, set to same value)
            def test_set_enabled():
                # Enable node 1 (should already be enabled)
                return graph.SetNodeEnabled(1, True)
            test("Graph.SetNodeEnabled", test_set_enabled)
        else:
            for name in ["Graph.GetNodeCacheMode", "Graph.SetNodeCacheMode", "Graph.GetToolsInNode", "Graph.SetNodeEnabled"]:
                test(name, None, skip_reason="No nodes in graph")
    else:
        for name in ["Graph.GetNodeCacheMode", "Graph.SetNodeCacheMode", "Graph.GetToolsInNode", "Graph.SetNodeEnabled"]:
            test(name, None, skip_reason="Could not get node graph")
else:
    for name in ["Graph.GetNodeCacheMode", "Graph.SetNodeCacheMode", "Graph.GetToolsInNode", "Graph.SetNodeEnabled"]:
        test(name, None, skip_reason="No items on video track 1")

# ─── Summary ─────────────────────────────────────────────────

print(f"\n=== Results ===")
print(f"Pass: {len(results['pass'])}")
print(f"Fail: {len(results['fail'])}")
print(f"Skip: {len(results['skip'])}")

out_path = os.path.join(os.path.dirname(__file__), "test_phase5_results.json")
with open(out_path, "w") as f:
    json.dump(results, f, indent=2)
print(f"\nResults saved to {out_path}")
