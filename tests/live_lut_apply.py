"""Live proof that an installed LUT is applied: install -> set_lut -> get_lut -> render.

Run from the repo root with Resolve open on the disposable project below:
    python tests/live_lut_apply.py

This settles the one claim `lut` rests on: that the `set_lut_path` returned by
`install` is resolved by Graph.SetLUT on a live node. It uses a constant-green
3D LUT on a solid-red clip, so application is unmistakable in decoded pixels.

The compound `graph set_lut` has a relocation fallback for LUTs outside the
master root. A fallback success would hide whether the installed path itself
resolved, so the harness records `resolved_lut`: absent means the direct
SetLUT on the installed path succeeded.

Refuses to run unless the open project is the disposable one. Installed LUTs
and render jobs are removed afterwards.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROJECT = "MCP LUT Apply Probe 20260911"
FIXTURE = Path(__file__).resolve().parents[2] / "lut-live-fixture" / "constant_green.cube"
# `source: "item"` targets the clip's node graph. The compound graph tool
# defaults to the TIMELINE graph, so omitting it tests the wrong node.
LOCATION = {"source": "item", "track_type": "video", "track_index": 1, "item_index": 0}


def centre_rgb(path):
    """Decode the rendered frame and return the centre pixel as 8-bit RGB."""
    raw = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", path, "-vf", "crop=2:2", "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True).stdout
    return list(raw[:3])


def render_frame(project, timeline, out_dir, name):
    frame = int(timeline.GetStartFrame())
    for job in project.GetRenderJobList() or []:
        project.DeleteRenderJob(job["JobId"])
    codecs = project.GetRenderCodecs("tif") or {}
    codec = next(iter(codecs.values())) if codecs else None
    if not codec or not project.SetCurrentRenderFormatAndCodec("tif", codec):
        raise SystemExit("Could not select a TIFF render format")
    project.SetRenderSettings({
        "SelectAllFrames": False, "MarkIn": frame, "MarkOut": frame,
        "TargetDir": out_dir, "CustomName": name,
        "ExportVideo": True, "ExportAudio": False,
    })
    job = project.AddRenderJob()
    if not job or not project.StartRendering([job]):
        raise SystemExit(f"Render did not start for {name}")
    deadline = time.time() + 90
    while project.IsRenderingInProgress() and time.time() < deadline:
        time.sleep(0.5)
    status = project.GetRenderJobStatus(job) or {}
    project.DeleteRenderJob(job)
    files = sorted(f for f in os.listdir(out_dir) if f.startswith(name))
    if not files:
        raise SystemExit(f"No rendered file for {name}; status {status}")
    return os.path.join(out_dir, files[-1]), status.get("JobStatus")


def main():
    import src.server as s
    from src.granular import graph as g

    resolve = s.get_resolve()
    project = resolve.GetProjectManager().GetCurrentProject() if resolve else None
    if project is None or project.GetName() != PROJECT:
        raise SystemExit(f"Refusing: open the disposable project {PROJECT!r} first.")
    timeline = project.GetCurrentTimeline()
    item = timeline.GetItemListInTrack("video", 1)[0]
    graph = item.GetNodeGraph()

    rows = []
    installed = []
    with tempfile.TemporaryDirectory() as out_dir:
        try:
            path, status = render_frame(project, timeline, out_dir, "baseline")
            rows.append({"case": "baseline render, no LUT", "status": status,
                         "centre_rgb": centre_rgb(path)})

            for label in ("compound", "granular"):
                name = f"mcp_apply_probe_{label}.cube"
                if label == "compound":
                    inst = s.lut("install", {"name": name, "source_path": str(FIXTURE)})
                    refreshed = s.project_settings("refresh_luts", {})
                    applied = s.graph("set_lut", dict(LOCATION, node_index=1,
                                                      lut_path=inst.get("set_lut_path")))
                    readback = s.graph("get_lut", dict(LOCATION, node_index=1))
                else:
                    inst = g.install_lut_file(name, source_path=str(FIXTURE))
                    from src.granular import project as gp
                    refreshed = gp.refresh_lut_list()
                    applied = g.graph_set_lut(1, inst.get("set_lut_path"))
                    readback = g.graph_get_lut(1)
                if inst.get("success"):
                    installed.append((label, name))
                path, status = render_frame(project, timeline, out_dir, f"with_{label}")
                rows.append({
                    "case": f"{label}: install -> refresh -> set_lut -> get_lut -> render",
                    "set_lut_path": inst.get("set_lut_path"),
                    "refresh_success": refreshed.get("success"),
                    "set_lut_success": applied.get("success"),
                    "direct_resolution": "resolved_lut" not in applied,
                    # Compound answers {"lut": ...}; granular answers {"lut_path": ...}.
                    "get_lut_readback": readback.get("lut", readback.get("lut_path")),
                    "render_status": status,
                    "centre_rgb": centre_rgb(path),
                })
                # Clear the node so the next interface starts from the baseline.
                graph.SetLUT(1, "")
        finally:
            for label, name in installed:
                removed = (s.lut("remove", {"name": name}) if label == "compound"
                           else g.remove_lut_file(name))
                rows.append({"case": f"cleanup {label}", "removed": removed.get("removed")})

    def is_red(rgb): return rgb[0] > 200 and rgb[1] < 60 and rgb[2] < 60
    def is_green(rgb): return rgb[1] > 200 and rgb[0] < 60 and rgb[2] < 60

    print(json.dumps({"resolve_version": resolve.GetVersionString(), "rows": rows}, indent=2))
    applied_rows = rows[1:3]
    ok = (is_red(rows[0]["centre_rgb"])
          and all(r["set_lut_success"] and r["direct_resolution"]
                  and r["get_lut_readback"] == r["set_lut_path"]
                  and is_green(r["centre_rgb"]) for r in applied_rows)
          and all(r.get("removed") for r in rows[3:]))
    print("RESULT:", "pass" if ok else "review the rows above")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
