"""Live Resolve validation for the delete_keyframe fix (issue #155).

The reported root cause -- `inp.RemoveKeyFrame(time)` is not a member of the
Fusion Input object -- is confirmable by inspection. The REPLACEMENT call is
not: the spline method name and signature have to be checked against a real
build before the fix can be claimed to work. That is what this script does.

It is self-contained: it creates a scratch project, inserts an empty Fusion
composition clip (no media required), and works only inside that comp. Nothing
of the user's is touched.

What it reports:
  1. The live Resolve product name and version, so any claim names a build.
  2. Whether `RemoveKeyFrame` really resolves to None on an Input (the bug's
     silent-lookup premise).
  3. Which keyframe-removal methods the connected spline actually exposes.
  4. Whether DeleteKeyFrames(time) removes the key, verified by reading the
     keyframe list back.

Run:  venv/bin/python tests/live_fusion_delete_keyframe_validation.py
"""

import os
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)

from src.utils.platform import get_resolve_paths

paths = get_resolve_paths()
os.environ["RESOLVE_SCRIPT_API"] = paths["api_path"]
os.environ["RESOLVE_SCRIPT_LIB"] = paths["lib_path"]
sys.path.insert(0, paths["modules_path"])

import DaVinciResolveScript as dvr_script  # noqa: E402

SCRATCH_PROJECT = "MCP_ISSUE155_SCRATCH"
TOOL_NAME = "MCPDeleteKeyTest"


def probe(obj, names):
    """Which of `names` are callable on `obj` -- the bridge answers None, not raise."""
    return {n: callable(getattr(obj, n, None)) for n in names}


def main():
    resolve = dvr_script.scriptapp("Resolve")
    if resolve is None:
        print("FATAL: cannot connect to Resolve")
        return 1

    print(f"product = {resolve.GetProductName()!r}  version = {resolve.GetVersionString()!r}")

    pm = resolve.GetProjectManager()
    project = pm.LoadProject(SCRATCH_PROJECT) or pm.CreateProject(SCRATCH_PROJECT)
    if project is None:
        print(f"FATAL: could not open or create {SCRATCH_PROJECT!r}")
        return 1
    print(f"project = {project.GetName()!r}")

    timeline = project.GetCurrentTimeline()
    if timeline is None:
        timeline = project.GetMediaPool().CreateEmptyTimeline("issue155")
    if timeline is None:
        print("FATAL: could not create a timeline")
        return 1
    resolve.OpenPage("edit")

    item = None
    for clip in timeline.GetItemListInTrack("video", 1) or []:
        if clip.GetFusionCompCount() > 0:
            item = clip
            break
    if item is None:
        item = timeline.InsertFusionCompositionIntoTimeline()
    if item is None:
        print("FATAL: InsertFusionCompositionIntoTimeline returned nothing")
        return 1

    comp = item.GetFusionCompByIndex(1)
    if comp is None:
        print("FATAL: no Fusion comp on the inserted item")
        return 1

    # --- Arrange: a Transform with two keyframes on Size, via add_keyframe's technique.
    comp.Lock()
    try:
        tool = comp.FindTool(TOOL_NAME) or comp.AddTool("Transform", -1, -1)
        try:
            tool.SetAttrs({"TOOLS_Name": TOOL_NAME})
        except Exception:
            pass
        inp = tool["Size"]
        if inp.GetConnectedOutput() is None:
            tool.AddModifier("Size", "BezierSpline")
        tool["Size"][0] = 1.0
        tool["Size"][75] = 1.4
    finally:
        comp.Unlock()

    inp = tool["Size"]
    before = inp.GetKeyFrames()
    print(f"keyframes before        = {before}")
    if not before or len(before) < 2:
        print("FATAL: setup failed -- expected two keyframes to delete from")
        return 1

    # --- 1. The bug's premise: RemoveKeyFrame is absent AND resolves to None.
    raw = getattr(inp, "RemoveKeyFrame", "ATTRIBUTE_ERROR")
    print(f"Input.RemoveKeyFrame    = {raw!r}   (the silent-None lookup)")
    print(f"Input methods           = {probe(inp, ['RemoveKeyFrame', 'DeleteKeyFrames', 'GetKeyFrames', 'GetConnectedOutput'])}")

    # --- 2. Reach the spline the way the fix does.
    connected = inp.GetConnectedOutput()
    print(f"GetConnectedOutput()    = {connected!r}")
    if connected is None:
        print("FATAL: input is not animated after AddModifier")
        return 1
    spline = connected.GetTool()
    spline_attrs = spline.GetAttrs() or {}
    print(f"spline tool             = {spline_attrs.get('TOOLS_Name')!r} "
          f"type={spline_attrs.get('TOOLS_RegID')!r}")
    print(f"spline methods          = {probe(spline, ['DeleteKeyFrames', 'RemoveKeyFrame', 'SetKeyFrames', 'GetKeyFrames'])}")

    if not callable(getattr(spline, "DeleteKeyFrames", None)):
        print("RESULT: FAIL -- DeleteKeyFrames is not the right method on this build")
        return 1

    # --- 3. Does the single-argument form actually remove the key?
    comp.Lock()
    try:
        try:
            rv = spline.DeleteKeyFrames(75)
            print(f"DeleteKeyFrames(75)     -> {rv!r}")
        except Exception as exc:
            print(f"DeleteKeyFrames(75) raised: {type(exc).__name__}: {exc}")
            print("RESULT: FAIL -- single-arg signature rejected")
            return 1
    finally:
        comp.Unlock()

    after = inp.GetKeyFrames()
    print(f"keyframes after         = {after}")

    remaining = sorted(float(f) for f in (after or {}).values())
    removed = not any(abs(f - 75.0) < 1e-6 for f in remaining)
    kept_other = any(abs(f - 0.0) < 1e-6 for f in remaining)
    ok = removed and kept_other

    print(f"removed frame 75        = {removed}")
    print(f"kept frame 0            = {kept_other}")
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
