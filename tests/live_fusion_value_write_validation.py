#!/usr/bin/env python3
"""Live proof that Fusion value writes are applied at RENDER, not just readback.

This is the regression test for the comp-lock bug found on 2026-08-21: a value
write (SetInput/SetExpression) wrapped in comp.Lock()/Unlock() lands in the
graph and reads back correctly through every API the server offers, while the
delivered render ignores it completely.

Measured on Studio 19.1.3.7 when the bug was live:

    fusion_comp set_input, write inside comp.Lock()   PSNR inf      IGNORED
    same write with the lock removed                  PSNR 24.38dB  RENDERED
    raw tool.XBlurSize = 20.0                         PSNR 24.38dB  RENDERED
    raw tool.SetInput("XBlurSize", 20)                PSNR 24.38dB  RENDERED

The variable was isolated against the comp handle (AddFusionComp,
GetFusionCompByIndex and GetFusionCompByName all render), the node name, and
the write form. Only the lock around the write decided it.

Readback cannot detect this - that is the whole point - so the assertion here
is on a rendered frame. Each case renders a baseline, applies the change, and
renders again; PSNR between the two must show a real difference.

Creates and deletes its own disposable project with synthetic media, and
restores the previously open project. Run with Python 3.10-3.12 against a
running Resolve Studio:

    python3.11 tests/live_fusion_value_write_validation.py [--keep-open]
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

# A real change must move PSNR well below this; an ignored write reads as inf.
PSNR_APPLIED_MAX_DB = 35.0


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




def _sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def _make_media(work_dir: Path) -> Path:
    media = work_dir / "fusion_source.mov"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc2=size=1280x720:rate=24:duration=4",
         "-pix_fmt", "yuv420p", "-c:v", "libx264", "-g", "12", "-y", str(media)],
        check=True,
    )
    return media


def _psnr(a: Path, b: Path) -> float:
    proc = _sh(["ffmpeg", "-hide_banner", "-i", str(a), "-i", str(b),
                "-lavfi", "psnr", "-f", "null", "-"])
    match = re.search(r"average:(inf|[0-9.]+)", proc.stderr)
    if not match:
        raise AssertionError(f"PSNR parse failed: {proc.stderr[-400:]}")
    return float("inf") if match.group(1) == "inf" else float(match.group(1))


def _render(project, mark_in, mark_out, target_dir: Path, name: str) -> Path:
    project.SetCurrentRenderFormatAndCodec("mov", "H264")
    if not project.SetRenderSettings({
        "SelectAllFrames": False, "MarkIn": int(mark_in), "MarkOut": int(mark_out),
        "TargetDir": str(target_dir), "CustomName": name,
    }):
        raise AssertionError(f"SetRenderSettings failed for {name}")
    job = project.AddRenderJob()
    if not job:
        raise AssertionError(f"AddRenderJob failed for {name}")
    if not project.StartRendering([job]):
        raise AssertionError(f"StartRendering failed for {name}")
    deadline = time.time() + 300
    while time.time() < deadline:
        state = (project.GetRenderJobStatus(job) or {}).get("JobStatus")
        if state == "Complete":
            break
        if state in ("Failed", "Cancelled"):
            raise AssertionError(f"render {name}: JobStatus={state}")
        time.sleep(2)
    else:
        raise AssertionError(f"render {name}: timed out")
    project.DeleteRenderJob(job)
    matches = sorted(target_dir.glob(f"{name}*.mov"))
    if not matches:
        raise AssertionError(f"render {name}: no output in {target_dir}")
    return matches[-1]


def run(server, keep_open: bool) -> int:
    import DaVinciResolveScript as bmd

    resolve = bmd.scriptapp("Resolve")
    if not resolve:
        raise AssertionError("could not connect to Resolve")
    print(f"Connected to {resolve.GetProductName()} {resolve.GetVersionString()}")
    pm = resolve.GetProjectManager()
    current = pm.GetCurrentProject()
    previous_project = current.GetName() if current else None

    work_dir = Path(tempfile.mkdtemp(prefix="fusion_valuewrite_"))
    media = _make_media(work_dir)
    project_name = f"_mcp_fusion_valuewrite_{int(time.time())}"
    if not pm.CreateProject(project_name):
        raise AssertionError(f"CreateProject failed: {project_name}")
    project = pm.GetCurrentProject()
    print(f"Created disposable project: {project_name}")

    failures = []
    measurements = {}
    try:
        resolve.OpenPage("edit")
        media_pool = project.GetMediaPool()
        imported = media_pool.ImportMedia([str(media)])
        if not imported:
            raise AssertionError("ImportMedia failed")
        clip = imported[0]

        def fresh_item(tag):
            tl = media_pool.CreateEmptyTimeline(f"VW_{tag}")
            project.SetCurrentTimeline(tl)
            start = int(round(float(tl.GetStartFrame())))
            media_pool.AppendToTimeline([{
                "mediaPoolItem": clip, "startFrame": 0, "endFrame": 96,
                "recordFrame": start, "trackIndex": 1, "mediaType": 1}])
            item = tl.GetItemListInTrack("video", 1)[0]
            return item, start, start + 47

        def check(tag, psnr_value):
            measurements[tag] = psnr_value
            applied = psnr_value <= PSNR_APPLIED_MAX_DB
            print(f"  {tag}: PSNR {psnr_value} -> "
                  f"{'APPLIED at render' if applied else 'IGNORED at render'}")
            if not applied:
                failures.append(
                    f"{tag}: value read back but did NOT change the render "
                    f"(PSNR {psnr_value}); a comp.Lock() around the write is the "
                    f"known cause - see _FUSION_VALUE_WRITE_NOTE in src/server.py")

        def wire_blur(item, node_name):
            item_id = item.GetUniqueId()

            def call(action, params):
                payload = {"clip_id": item_id, "comp_index": 1}
                payload.update(params)
                result = server.fusion_comp(action, payload)
                if isinstance(result, dict) and result.get("error"):
                    raise AssertionError(f"fusion_comp.{action}: {result['error']}")
                return result

            call("add_tool", {"tool_type": "Blur", "name": node_name})
            call("connect", {"target_tool": node_name, "input_name": "Input",
                             "source_tool": "MediaIn1"})
            call("connect", {"target_tool": "MediaOut1", "input_name": "Input",
                             "source_tool": node_name})
            return call

        # --- Case 1: fusion_comp set_input ------------------------------
        item, mark_in, mark_out = fresh_item("set_input")
        base = _render(project, mark_in, mark_out, work_dir, "si_base")
        item.AddFusionComp()
        call = wire_blur(item, "VWBlur")
        call("set_input", {"tool_name": "VWBlur", "input_name": "XBlurSize", "value": 20})
        readback = call("get_input", {"tool_name": "VWBlur", "input_name": "XBlurSize"})
        print(f"set_input readback: {readback.get('value')} "
              f"(readback ALWAYS agrees - the render is the only witness)")
        check("set_input", _psnr(base, _render(project, mark_in, mark_out, work_dir, "si_out")))

        # --- Case 2: fusion_comp safe_set_inputs (bulk) -----------------
        item, mark_in, mark_out = fresh_item("safe_set_inputs")
        base = _render(project, mark_in, mark_out, work_dir, "sis_base")
        item.AddFusionComp()
        call = wire_blur(item, "VWBlur2")
        call("safe_set_inputs", {"tool_name": "VWBlur2", "inputs": {"XBlurSize": 20}})
        check("safe_set_inputs",
              _psnr(base, _render(project, mark_in, mark_out, work_dir, "sis_out")))

        if failures:
            for line in failures:
                print(f"FAILURE: {line}", file=sys.stderr)
            return 1
        print(f"PASS: every Fusion value write changed the delivered render "
              f"({measurements})")
        return 0
    finally:
        if not keep_open:
            try:
                if previous_project:
                    pm.LoadProject(previous_project)
                pm.DeleteProject(project_name)
                print(f"Deleted disposable project: {project_name}")
            except Exception as exc:
                print(f"cleanup warning: {exc}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()
    _install_mcp_stubs()
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import src.server as server
    return run(server, keep_open=args.keep_open)


if __name__ == "__main__":
    raise SystemExit(main())
