#!/usr/bin/env python3
"""Live validation for timeline.ripple_insert plus a Fusion render isolation probe.

Phase 1 (ripple_insert): creates a disposable project, imports synthetic media,
builds a 3 x 48-frame timeline, sets ZoomX/Y=0.5 on the tail item, then runs the
compound timeline("ripple_insert") dispatch end to end: dry-run plan, the
confirm-token round-trip, execute, full layout readback, and property survival.

Phase 2 (fusion isolation): on a second timeline, renders a baseline, then a
wired MediaIn -> Blur -> MediaOut comp, then MediaIn -> Transform -> MediaOut,
comparing each render to the baseline with ffmpeg PSNR. This isolates the
variable behind the conflicting api_truth measurements (Blur rendered on
Studio 19.1.3.7 on 2026-08-02; Transform did not render on 21.0.4 on
2026-08-20). PSNR above the threshold means the comp was ignored.

Run with Python 3.10-3.12 against a running Resolve Studio instance:

  python3.12 tests/live_ripple_insert_validation.py [--keep-open] [--media PATH]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

PSNR_IGNORED_DB = 40.0  # >= this vs baseline: the comp did not affect the render
PSNR_RENDERED_DB = 35.0  # <= this vs baseline: the comp visibly changed the render


def _install_mcp_stubs() -> None:
    """Allow importing src.server when MCP deps are absent (harness idiom)."""

    class FastMCP:
        def __init__(self, *args, **kwargs):
            pass

        def tool(self, *args, **kwargs):
            def decorate(func):
                return func

            return decorate

        def resource(self, *args, **kwargs):
            def decorate(func):
                return func

            return decorate

        def prompt(self, *args, **kwargs):
            def decorate(func):
                return func

            return decorate

    def stdio_server(*args, **kwargs):
        raise RuntimeError("stdio_server is not used by this live harness")

    anyio = types.ModuleType("anyio")
    anyio.run = lambda func: func()

    mcp = types.ModuleType("mcp")
    server = types.ModuleType("mcp.server")
    fastmcp = types.ModuleType("mcp.server.fastmcp")
    stdio = types.ModuleType("mcp.server.stdio")

    class Context:
        pass

    class Image:
        def __init__(self, *args, **kwargs):
            pass

    class ToolAnnotations:
        def __init__(self, *args, **kwargs):
            pass

    fastmcp.FastMCP = FastMCP
    fastmcp.Context = Context
    fastmcp.Image = Image
    stdio.stdio_server = stdio_server

    mcp_types = types.ModuleType("mcp.types")
    mcp_types.ToolAnnotations = ToolAnnotations
    mcp_types.ImageContent = object
    mcp_types.TextContent = object
    mcp.types = mcp_types

    sys.modules.setdefault("anyio", anyio)
    sys.modules.setdefault("mcp", mcp)
    sys.modules.setdefault("mcp.server", server)
    sys.modules.setdefault("mcp.server.fastmcp", fastmcp)
    sys.modules.setdefault("mcp.server.stdio", stdio)
    sys.modules.setdefault("mcp.types", mcp_types)


def _require(label, result, *, allow_confirm=False):
    if not isinstance(result, dict):
        raise AssertionError(f"{label}: expected dict, got {result!r}")
    if allow_confirm and result.get("status") == "confirmation_required":
        return result
    if result.get("error"):
        raise AssertionError(f"{label}: {result['error']}")
    if "success" in result and result["success"] is not True:
        raise AssertionError(f"{label}: expected success=True, got {result!r}")
    return result


def _make_media(work_dir: Path) -> Path:
    media_path = work_dir / "ripple_source.mov"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=24:duration=4",
            "-pix_fmt", "yuv420p", "-c:v", "libx264", "-g", "12",
            "-y", str(media_path),
        ],
        check=True,
    )
    return media_path


def _layout(tl, track_type="video", track_index=1):
    rows = []
    for item in tl.GetItemListInTrack(track_type, track_index) or []:
        start = int(round(float(item.GetStart())))
        rows.append((start, int(round(float(item.GetDuration())))))
    return sorted(rows)


def _render_range(project, mark_in, mark_out, target_dir: Path, name: str) -> Path:
    project.SetCurrentRenderFormatAndCodec("mov", "H264")
    ok = project.SetRenderSettings({
        "SelectAllFrames": False,
        "MarkIn": int(mark_in),
        "MarkOut": int(mark_out),
        "TargetDir": str(target_dir),
        "CustomName": name,
    })
    if not ok:
        raise AssertionError(f"SetRenderSettings failed for {name}")
    job = project.AddRenderJob()
    if not job:
        raise AssertionError(f"AddRenderJob failed for {name}")
    if not project.StartRendering([job]):
        raise AssertionError(f"StartRendering failed for {name}")
    deadline = time.time() + 300
    while time.time() < deadline:
        status = project.GetRenderJobStatus(job) or {}
        state = status.get("JobStatus")
        if state == "Complete":
            break
        if state in ("Failed", "Cancelled"):
            raise AssertionError(f"render {name}: JobStatus={state} ({status})")
        time.sleep(2)
    else:
        raise AssertionError(f"render {name}: timed out")
    project.DeleteRenderJob(job)
    matches = sorted(target_dir.glob(f"{name}*.mov"))
    if not matches:
        raise AssertionError(f"render {name}: no output file in {target_dir}")
    return matches[-1]


def _psnr(file_a: Path, file_b: Path) -> float:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(file_a), "-i", str(file_b),
         "-lavfi", "psnr", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    match = re.search(r"average:(inf|[0-9.]+)", proc.stderr)
    if not match:
        raise AssertionError(f"PSNR parse failed: {proc.stderr[-400:]}")
    value = match.group(1)
    return float("inf") if value == "inf" else float(value)


def _fusion_scope(server, clip_id, action, params):
    payload = {"clip_id": clip_id, "comp_index": 1}
    payload.update(params)
    return _require(f"fusion_comp.{action}", server.fusion_comp(action, payload))


def run(server, media_path: Path, keep_open: bool) -> int:
    project_name = f"_mcp_p0port_smoke_{int(time.time())}"
    work_dir = Path(tempfile.mkdtemp(prefix="mcp_p0port_smoke_"))
    resolve = server.get_resolve()
    if not resolve:
        raise AssertionError("could not connect to Resolve")
    pm = resolve.GetProjectManager()
    previous_project = None
    current = pm.GetCurrentProject()
    if current:
        previous_project = current.GetName()
        print(f"current project before run: {previous_project}")

    created = False
    failures = []
    fusion_results = {}
    try:
        version = _require("resolve_control.get_version", server.resolve_control("get_version"))
        print(f"Connected to {version['product']} {version['version_string']}")

        if not pm.CreateProject(project_name):
            raise AssertionError(f"CreateProject failed: {project_name}")
        created = True
        project = pm.GetCurrentProject()
        print(f"Created disposable project: {project_name}")
        _require("open_page.edit", server.resolve_control("open_page", {"page": "edit"}))

        media_pool = project.GetMediaPool()
        imported = media_pool.ImportMedia([str(media_path)])
        if not imported:
            raise AssertionError(f"ImportMedia failed: {media_path}")
        clip = imported[0]
        clip_id = clip.GetUniqueId()
        print(f"Imported {clip.GetName()} ({clip_id})")

        # ---- Phase 1: ripple_insert -------------------------------------
        tl = media_pool.CreateEmptyTimeline("RippleSmoke")
        if not tl:
            raise AssertionError("CreateEmptyTimeline failed")
        project.SetCurrentTimeline(tl)
        tl_start = int(round(float(tl.GetStartFrame())))
        infos = [
            {"mediaPoolItem": clip, "startFrame": 0, "endFrame": 48,
             "recordFrame": tl_start + i * 48, "trackIndex": 1, "mediaType": 1}
            for i in range(3)
        ]
        appended = media_pool.AppendToTimeline(infos)
        if not appended or len(appended) != 3:
            raise AssertionError(f"AppendToTimeline placed {len(appended or [])} of 3 items")
        before = _layout(tl)
        expected_before = [(tl_start, 48), (tl_start + 48, 48), (tl_start + 96, 48)]
        if before != expected_before:
            raise AssertionError(f"setup layout {before} != {expected_before}")
        tail = tl.GetItemListInTrack("video", 1)[-1]
        for key in ("ZoomX", "ZoomY"):
            if not tail.SetProperty(key, 0.5):
                raise AssertionError(f"SetProperty {key}=0.5 failed on tail item")
        print(f"timeline ready: {before}, tail ZoomX/Y=0.5")

        params = {
            "clip_infos": [{"clip_id": clip_id, "start_frame": 0, "end_frame": 24,
                            "track_index": 1, "media_type": 1}],
            "record_frame": 48,
        }
        plan = _require("ripple_insert.dry_run", server.timeline("ripple_insert", params))
        p = plan["plan"]
        assert plan["dry_run"] and p["shift_frames"] == 24, plan
        assert p["insert_frame_absolute"] == tl_start + 48, plan
        assert p["tail_item_count"] == 2 and not p["straddlers"] and not p["blockers"], plan
        print(f"dry-run plan OK: insert@{p['insert_frame_absolute']} shift={p['shift_frames']}")

        execute = dict(params, dry_run=False)
        first = _require("ripple_insert.execute", server.timeline("ripple_insert", execute),
                         allow_confirm=True)
        if first.get("status") == "confirmation_required":
            print("confirm token issued; replaying with token")
            execute["confirm_token"] = first["confirm_token"]
            result = _require("ripple_insert.confirmed", server.timeline("ripple_insert", execute))
        else:
            result = first
        assert result["success"] is True, result
        assert result["readback"]["missing"] == [], result
        after = _layout(tl)
        expected_after = [(tl_start, 48), (tl_start + 48, 24),
                          (tl_start + 72, 48), (tl_start + 120, 48)]
        if after != expected_after:
            raise AssertionError(f"post-insert layout {after} != {expected_after}")
        shifted_tail = tl.GetItemListInTrack("video", 1)[-1]
        zx = shifted_tail.GetProperty("ZoomX")
        zy = shifted_tail.GetProperty("ZoomY")
        if not (abs(float(zx) - 0.5) < 0.001 and abs(float(zy) - 0.5) < 0.001):
            raise AssertionError(f"property survival failed: ZoomX={zx} ZoomY={zy}")
        print(f"PHASE 1 PASS: layout {after}, ZoomX/Y=0.5 survived, "
              f"restored={result['properties_restored_items']} "
              f"restore_failures={result['property_restore_failures']}")

        # ---- Phase 2: Fusion render isolation ---------------------------
        tl2 = media_pool.CreateEmptyTimeline("FusionIso")
        project.SetCurrentTimeline(tl2)
        tl2_start = int(round(float(tl2.GetStartFrame())))
        if not media_pool.AppendToTimeline([
            {"mediaPoolItem": clip, "startFrame": 0, "endFrame": 96,
             "recordFrame": tl2_start, "trackIndex": 1, "mediaType": 1}]):
            raise AssertionError("FusionIso append failed")
        item = tl2.GetItemListInTrack("video", 1)[0]
        item_id = item.GetUniqueId()
        mark_in, mark_out = tl2_start, tl2_start + 47

        baseline = _render_range(project, mark_in, mark_out, work_dir, "baseline")
        print(f"baseline rendered: {baseline.name}")

        comp = item.AddFusionComp()
        if not comp:
            raise AssertionError("AddFusionComp returned nothing")
        assert item.GetFusionCompCount() >= 1, "comp count did not increase"

        blur = _fusion_scope(server, item_id, "add_tool", {"tool_type": "Blur", "name": "IsoBlur"})
        _fusion_scope(server, item_id, "connect",
                      {"target_tool": "IsoBlur", "input_name": "Input", "source_tool": "MediaIn1"})
        _fusion_scope(server, item_id, "connect",
                      {"target_tool": "MediaOut1", "input_name": "Input", "source_tool": "IsoBlur"})
        _fusion_scope(server, item_id, "set_input",
                      {"tool_name": "IsoBlur", "input_name": "XBlurSize", "value": 20})
        readback = _fusion_scope(server, item_id, "get_input",
                                 {"tool_name": "IsoBlur", "input_name": "XBlurSize"})
        print(f"Blur wired (readback XBlurSize={readback.get('value')})")

        blur_render = _render_range(project, mark_in, mark_out, work_dir, "blurcomp")
        blur_psnr = _psnr(baseline, blur_render)
        fusion_results["blur_psnr_vs_baseline"] = blur_psnr
        print(f"Blur render PSNR vs baseline: {blur_psnr}")

        transform = _fusion_scope(server, item_id, "add_tool",
                                  {"tool_type": "Transform", "name": "IsoXform"})
        _fusion_scope(server, item_id, "connect",
                      {"target_tool": "IsoXform", "input_name": "Input", "source_tool": "MediaIn1"})
        _fusion_scope(server, item_id, "connect",
                      {"target_tool": "MediaOut1", "input_name": "Input", "source_tool": "IsoXform"})
        _fusion_scope(server, item_id, "set_input",
                      {"tool_name": "IsoXform", "input_name": "Size", "value": 0.45})
        xf_render = _render_range(project, mark_in, mark_out, work_dir, "xformcomp")
        xf_psnr = _psnr(baseline, xf_render)
        fusion_results["transform_psnr_vs_baseline"] = xf_psnr
        print(f"Transform render PSNR vs baseline: {xf_psnr}")

        def verdict(name, value):
            if value >= PSNR_IGNORED_DB:
                return f"{name}: comp IGNORED at render (PSNR {value} >= {PSNR_IGNORED_DB})"
            if value <= PSNR_RENDERED_DB:
                return f"{name}: comp RENDERED (PSNR {value} <= {PSNR_RENDERED_DB})"
            return f"{name}: INCONCLUSIVE (PSNR {value})"

        print("PHASE 2 RESULT:")
        print("  " + verdict("Blur", blur_psnr))
        print("  " + verdict("Transform", xf_psnr))
        return 0
    except AssertionError as exc:
        failures.append(str(exc))
        print(f"FAILURE: {exc}", file=sys.stderr)
        return 1
    finally:
        if fusion_results:
            print(f"fusion_results={fusion_results}")
        if created and not keep_open:
            try:
                if previous_project:
                    pm.LoadProject(previous_project)
                pm.DeleteProject(project_name)
                print(f"Deleted disposable project: {project_name}")
            except Exception as exc:
                print(f"cleanup warning: {exc}", file=sys.stderr)
        elif previous_project and not keep_open:
            try:
                pm.LoadProject(previous_project)
            except Exception as exc:
                print(f"project restore warning: {exc}", file=sys.stderr)
        if previous_project:
            print(f"current project restored to: {previous_project}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--media", type=Path, default=None)
    args = parser.parse_args()

    _install_mcp_stubs()
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import src.server as server

    work_dir = Path(tempfile.mkdtemp(prefix="mcp_p0port_media_"))
    media_path = args.media if args.media else _make_media(work_dir)
    return run(server, media_path, keep_open=args.keep_open)


if __name__ == "__main__":
    raise SystemExit(main())
