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

All six write paths the v2.98.5 fix touched are covered. Four of them are
genuinely broken by the lock; two escape, and the reason is now known.

    set_input            Blur XBlurSize          scalar write
    safe_set_inputs      Blur XBlurSize          bulk scalar write
    set_text_plus        Text+ StyledText        string write, composited
    bulk_set_expressions Blur XBlurSize          expression write
    bulk_set_inputs      Blur XBlurSize          scalar write, undo-wrapped
    add_fusion_mask      RectangleMask W/H       scalar writes after AddTool

WHICH OF THESE THE LOCK ACTUALLY BREAKS (each mutation-checked on 19.1.3.7 by
reintroducing the lock and re-rendering):

    set_input             lock -> PSNR inf    SUPPRESSED
    safe_set_inputs       lock -> PSNR inf    SUPPRESSED
    set_text_plus         lock -> PSNR inf    SUPPRESSED
    add_fusion_mask       lock -> PSNR inf    SUPPRESSED
    bulk_set_inputs       lock -> unchanged   escapes
    bulk_set_expressions  lock -> unchanged   escapes

The two that escape are the two that wrap their write in StartUndo/EndUndo.

MECHANISM, isolated 2026-08-22 with raw-API probes:

  PRECONDITION  The suppression only reproduces on a graph BUILT through
                lock-wrapped AddTool/ConnectInput. The identical locked write
                against a graph wired by plain attribute assignment renders
                normally - so "a lock around a value write" is necessary but not
                sufficient. (This is why raw-API repro attempts kept coming back
                green.)

  TRIGGER       The locked write is lost when it is the FIRST value write to the
                comp since that build.

  PRIMES IT     ANY unlocked value write anywhere in the comp clears the
                condition permanently - even writing a DEFAULT value to an
                unrelated tool. So does StartUndo/EndUndo around the write.

  DOES NOT      A structural ConnectInput inside the same lock, and a GetInput
                readback after the Unlock.

*** WHY THIS MATTERS FOR WRITING CASES HERE ***

Priming makes false negatives trivially easy, and it already caused one: the
first versions of the set_text_plus and add_fusion_mask cases set up their graphs
with plain SetInput calls (a text Size, a blur amount) before the call under
test. Those setup writes primed the comp, both cases passed with the lock
reintroduced, and v2.98.6 published the conclusion that those two code paths were
unaffected. They are not - once the priming was removed both fail exactly like
the others.

So: a case in this file must perform NO value write of any kind before the call
it is testing. Where a tool needs to be visible to measure at all, choose one
that is visible at its defaults - that is why the mask case composites a
Background rather than making a Blur visible by first writing XBlurSize.

The Text+ case needs a ROOTED graph (MediaIn -> Merge -> MediaOut with the Text+
in the foreground). A comp whose MediaOut is fed only by a Text+, with no path
from MediaIn, is bypassed at render for an unrelated reason — see the
AddFusionComp entry in api_truth — and would fail here for the wrong cause.

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

        # --- Case 3: fusion_comp set_text_plus --------------------------
        # Rooted graph: MediaIn -> Merge.Background -> MediaOut, Text+ into
        # Merge.Foreground. NOTHING is written to any input before the call
        # under test - see the priming note in the header. The baseline renders
        # with the Text+ at its defaults (empty StyledText), so it is the source
        # frame, and the text is left at default Size for the same reason.
        item, mark_in, mark_out = fresh_item("set_text_plus")
        item_id = item.GetUniqueId()
        item.AddFusionComp()

        def call3(action, params):
            payload = {"clip_id": item_id, "comp_index": 1}
            payload.update(params)
            result = server.fusion_comp(action, payload)
            if isinstance(result, dict) and result.get("error"):
                raise AssertionError(f"fusion_comp.{action}: {result['error']}")
            return result

        call3("add_tool", {"tool_type": "Merge", "name": "VWMerge"})
        call3("add_tool", {"tool_type": "TextPlus", "name": "VWText"})
        call3("connect", {"target_tool": "VWMerge", "input_name": "Background",
                          "source_tool": "MediaIn1"})
        call3("connect", {"target_tool": "VWMerge", "input_name": "Foreground",
                          "source_tool": "VWText"})
        call3("connect", {"target_tool": "MediaOut1", "input_name": "Input",
                          "source_tool": "VWMerge"})
        base = _render(project, mark_in, mark_out, work_dir, "tp_base")
        call3("set_text_plus", {"tool_name": "VWText",
                                "text": "\n".join(["MMMMMMMMMMMM"] * 6)})
        check("set_text_plus",
              _psnr(base, _render(project, mark_in, mark_out, work_dir, "tp_out")))

        # --- Case 4: fusion_comp bulk_set_expressions -------------------
        # An expression that evaluates to a real blur size. Baseline is the
        # unblurred graph (XBlurSize defaults to 0).
        item, mark_in, mark_out = fresh_item("bulk_set_expressions")
        item.AddFusionComp()
        wire_blur(item, "VWBlur3")   # side effect: adds and wires the Blur
        base = _render(project, mark_in, mark_out, work_dir, "bse_base")
        result = server.fusion_comp("bulk_set_expressions", {"ops": [{
            "clip_id": item.GetUniqueId(), "comp_index": 1,
            "tool_name": "VWBlur3", "input_name": "XBlurSize",
            "expression": "20",
        }]})
        rows = result.get("results", []) if isinstance(result, dict) else []
        if not rows or rows[0].get("error"):
            raise AssertionError(f"bulk_set_expressions failed: {result}")
        check("bulk_set_expressions",
              _psnr(base, _render(project, mark_in, mark_out, work_dir, "bse_out")))

        # --- Case 5: fusion_comp bulk_set_inputs ------------------------
        # Same numeric write as safe_set_inputs, but wrapped in StartUndo/
        # EndUndo. Worth its own case: the undo wrapper was the leading
        # explanation for why some locked writes still rendered.
        item, mark_in, mark_out = fresh_item("bulk_set_inputs")
        item.AddFusionComp()
        wire_blur(item, "VWBlur4")
        base = _render(project, mark_in, mark_out, work_dir, "bsi_base")
        result = server.fusion_comp("bulk_set_inputs", {"ops": [{
            "clip_id": item.GetUniqueId(), "comp_index": 1,
            "tool_name": "VWBlur4", "input_name": "XBlurSize", "value": 20,
        }]})
        rows = result.get("results", []) if isinstance(result, dict) else []
        if not rows or rows[0].get("error"):
            raise AssertionError(f"bulk_set_inputs failed: {result}")
        check("bulk_set_inputs",
              _psnr(base, _render(project, mark_in, mark_out, work_dir, "bsi_out")))

        # --- Case 6: fusion_comp add_fusion_mask ------------------------
        # add_fusion_mask writes its inputs right after AddTool, and until
        # v2.98.5 one lock spanned both.
        #
        # Baseline/after does not discriminate here - a default-sized mask still
        # changes the render - so build the SAME graph twice, once with a default
        # mask and once with an explicitly tiny one, and require the two renders
        # to differ. If the input writes are lost both are default and the two
        # renders are identical.
        #
        # A Background over a Merge is used rather than a Blur because it is
        # fully visible at its DEFAULTS: making a Blur visible would mean writing
        # XBlurSize first, and that unlocked write would prime the comp and mask
        # the very failure this case exists to catch.
        def masked_bg_render(tag, mask_params):
            item, m_in, m_out = fresh_item(tag)
            item.AddFusionComp()
            iid = item.GetUniqueId()

            def call6(action, params):
                payload = {"clip_id": iid, "comp_index": 1}
                payload.update(params)
                out = server.fusion_comp(action, payload)
                if isinstance(out, dict) and out.get("error"):
                    raise AssertionError(f"fusion_comp.{action}: {out['error']}")
                return out

            call6("add_tool", {"tool_type": "Merge", "name": "VWM"})
            call6("add_tool", {"tool_type": "Background", "name": "VWBG"})
            call6("connect", {"target_tool": "VWM", "input_name": "Background",
                              "source_tool": "MediaIn1"})
            call6("connect", {"target_tool": "VWM", "input_name": "Foreground",
                              "source_tool": "VWBG"})
            call6("connect", {"target_tool": "MediaOut1", "input_name": "Input",
                              "source_tool": "VWM"})
            params = {"mask_type": "Rectangle", "name": "VWMask",
                      "connect_to": "VWBG", "connect_input": "EffectMask"}
            params.update(mask_params)
            out = call6("add_fusion_mask", params)
            if not out.get("success"):
                raise AssertionError(f"add_fusion_mask failed: {out}")
            return _render(project, m_in, m_out, work_dir, tag)

        default_mask = masked_bg_render("mask_default", {})
        sized_mask = masked_bg_render("mask_sized", {"width": 0.08, "height": 0.08})
        check("add_fusion_mask", _psnr(default_mask, sized_mask))

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
