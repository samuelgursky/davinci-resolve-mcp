"""Live Resolve validation for the add_keyframe BezierSpline fix (PR #56).

Connects to a running DaVinci Resolve, finds the disposable "Fusion
Composition" clip on the current timeline, adds a Transform tool, and applies
the EXACT technique used by the fixed `fusion_comp(action="add_keyframe")`
handler:

    if not inp.GetConnectedOutput():
        tool.AddModifier(input_name, "BezierSpline")
    tool[input_name][time] = value

Then it reads the interpolated value at several frames and the keyframe list.
This validates the Fusion technique against the live app, independent of the
long-running MCP server process (which may still be serving pre-fix code).

Run AFTER setting up a timeline whose video track 1 holds a Fusion Composition
clip. Pass --tool-name to target a specific Transform (default: a fresh one).
Read-only against source media; touches only the disposable comp.
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


def main():
    resolve = dvr_script.scriptapp("Resolve")
    if resolve is None:
        print("FATAL: cannot connect to Resolve")
        return 1

    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    timeline = project.GetCurrentTimeline()
    print(f"project={project.GetName()!r} timeline={timeline.GetName()!r}")

    # Find the Fusion Composition clip on video track 1.
    item = None
    for clip in timeline.GetItemListInTrack("video", 1) or []:
        if clip.GetFusionCompCount() > 0:
            item = clip
            break
    if item is None:
        print("FATAL: no timeline item with a Fusion comp on V1")
        return 1

    comp = item.GetFusionCompByIndex(1)
    tool_name = "MCPKeyTestLive"

    comp.Lock()
    try:
        tool = comp.FindTool(tool_name) or comp.AddTool("Transform", -1, -1)
        try:
            tool.SetAttrs({"TOOLS_Name": tool_name})
        except Exception:
            pass

        inp = tool["Size"]
        # The fix: attach a spline the first time, then key it.
        already = False
        try:
            already = inp.GetConnectedOutput() is not None
        except Exception:
            already = False
        if not already:
            tool.AddModifier("Size", "BezierSpline")
        tool["Size"][0] = 1.0
        tool["Size"][75] = 1.4
    finally:
        comp.Unlock()

    v0 = tool.GetInput("Size", 0)
    v37 = tool.GetInput("Size", 37)
    v75 = tool.GetInput("Size", 75)
    kfs = tool["Size"].GetKeyFrames()

    print(f"get_input(Size, 0)  = {v0}")
    print(f"get_input(Size, 37) = {v37}")
    print(f"get_input(Size, 75) = {v75}")
    print(f"GetKeyFrames()      = {kfs}  (raw {{index: frame}})")

    # Mirror the fixed get_keyframes handler: frame positions are the VALUES of
    # GetKeyFrames(); read each keyframed value back via GetInput(frame).
    serialized = [
        {"time": kfs[idx], "value": tool.GetInput("Size", kfs[idx])}
        for idx in sorted(kfs)
    ]
    print(f"get_keyframes()     = {serialized}")

    ok = (
        abs(v0 - 1.0) < 1e-6
        and abs(v75 - 1.4) < 1e-6
        and 1.0 < v37 < 1.4  # genuine interpolation between the keyframes
        and bool(kfs)
        and serialized == [
            {"time": 0.0, "value": 1.0},
            {"time": 75.0, "value": 1.4},
        ]
    )
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
