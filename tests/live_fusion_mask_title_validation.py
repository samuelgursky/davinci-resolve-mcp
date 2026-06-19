#!/usr/bin/env python3
"""Live validation for the v2.57.0 Fusion convenience actions (issue #73).

Requires DaVinci Resolve Studio running with Preferences > General >
"External scripting using" set to Local. This creates a disposable project,
inserts a Fusion title (which yields a comp with a Text+ tool and a MediaOut),
and exercises the three new ``fusion_comp`` actions end-to-end, then deletes
the disposable project.

Verified on Resolve Studio 21.0.0.47 (2026-06-19):
  - ``get_text_plus`` auto-finds the Text+ tool and reads its StyledText.
  - ``set_text_plus`` writes StyledText; the readback matches.
  - ``add_fusion_mask`` adds a Rectangle/Ellipse mask and sets its params. The
    Center Point-input is set with the [x, y] list form and reads back as a
    1-indexed table {1: x, 2: y, 3: 0} (z defaults to 0).
  - ``connect_to`` reports connection.success=False against a node with NO mask
    input (MediaOut is the output node) and True against a real Mask input (the
    Text+ tool's EffectMask). This is the correct/honest behavior, so the
    harness asserts BOTH outcomes.

Run:
  env RESOLVE_SCRIPT_API=... RESOLVE_SCRIPT_LIB=... PYTHONPATH=.../Modules \
    venv/bin/python tests/live_fusion_mask_title_validation.py [--keep-open]
"""

from __future__ import annotations

import argparse
import sys
import time
import types
from pathlib import Path


def _install_mcp_stubs() -> None:
    """Let us import src.server without installing MCP deps in this Python."""

    try:
        import mcp.server.fastmcp  # noqa: F401
        return  # real SDK available — stubs would shadow it
    except ImportError:
        pass

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

    class Context:
        pass

    class Image:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    def stdio_server(*args, **kwargs):
        raise RuntimeError("stdio_server is not used by the live Fusion mask/title harness")

    anyio = types.ModuleType("anyio")
    anyio.run = lambda func: func()

    mcp = types.ModuleType("mcp")
    server = types.ModuleType("mcp.server")
    fastmcp = types.ModuleType("mcp.server.fastmcp")
    stdio = types.ModuleType("mcp.server.stdio")

    fastmcp.FastMCP = FastMCP
    fastmcp.Context = Context
    fastmcp.Image = Image
    stdio.stdio_server = stdio_server

    sys.modules.setdefault("anyio", anyio)
    sys.modules.setdefault("mcp", mcp)
    sys.modules.setdefault("mcp.server", server)
    sys.modules.setdefault("mcp.server.fastmcp", fastmcp)
    sys.modules.setdefault("mcp.server.stdio", stdio)


def _require_success(label, result):
    if not isinstance(result, dict):
        raise AssertionError(f"{label}: expected dict, got {result!r}")
    if result.get("error"):
        raise AssertionError(f"{label}: {result['error']}")
    if "success" in result and result["success"] is not True:
        raise AssertionError(f"{label}: expected success=True, got {result!r}")
    return result


# Default Fusion-title clip scope: first item on video track 1.
# NOTE the two tools take this scope differently:
#   - timeline_item_fusion uses FLAT track_type/track_index/item_index params.
#   - fusion_comp wants them NESTED under a "timeline_item" key (or clip_id /
#     timeline_item_id). Passing the flat fields to fusion_comp leaves it with no
#     timeline scope, so it falls back to the Fusion-page current comp.
ITEM = {"track_type": "video", "track_index": 1, "item_index": 0}
SCOPE = {"timeline_item": ITEM}


def main() -> int:
    parser = argparse.ArgumentParser(description="Live Fusion mask/title validation harness (issue #73)")
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="Leave the disposable project open with the comp in place for manual inspection.",
    )
    args = parser.parse_args()

    _install_mcp_stubs()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    import src.server as server

    project_name = f"_mcp_fusion_mask_title_{int(time.time())}"
    timeline_name = "issue_73_fusion_validation"
    created_project = False
    delete_result = None

    try:
        version = server.resolve_control("get_version")
        _require_success("resolve_control.get_version", version)
        print(f"Connected to {version['product']} {version['version_string']}")

        _require_success("project_manager.create", server.project_manager("create", {"name": project_name}))
        created_project = True
        print(f"Created disposable project: {project_name}")

        _require_success("resolve_control.open_page", server.resolve_control("open_page", {"page": "edit"}))
        timeline = _require_success(
            "media_pool.create_timeline",
            server.media_pool("create_timeline", {"name": timeline_name}),
        )
        print(f"Created timeline: {timeline['name']}")

        _require_success(
            "timeline.insert_fusion_title",
            server.timeline("insert_fusion_title", {"name": "Text+"}),
        )
        print("Inserted Fusion title clip")

        comp_count = _require_success(
            "timeline_item_fusion.get_comp_count",
            server.timeline_item_fusion("get_comp_count", ITEM),
        )
        if int(comp_count.get("count", 0)) < 1:
            raise AssertionError(f"Fusion title clip has no comp: {comp_count!r}")

        tools = _require_success(
            "fusion_comp.get_tool_list",
            server.fusion_comp("get_tool_list", {**SCOPE}),
        )
        tool_types = {t["type"] for t in tools.get("tools", [])}
        if "TextPlus" not in tool_types:
            raise AssertionError(f"Expected a TextPlus tool in the comp, got {tools!r}")
        media_out = next((t["name"] for t in tools["tools"] if t["type"] == "MediaOut"), None)
        print(f"Comp tools: {[ (t['name'], t['type']) for t in tools['tools'] ]}")

        # --- get_text_plus (auto-find the Text+ tool) ---
        got = _require_success("fusion_comp.get_text_plus", server.fusion_comp("get_text_plus", {**SCOPE}))
        if got.get("input_name") != "StyledText" or "text" not in got:
            raise AssertionError(f"get_text_plus unexpected shape: {got!r}")
        print(f"get_text_plus -> {got['tool_name']!r}: {got['text']!r}")

        # --- set_text_plus (write + readback) ---
        new_text = f"issue73 live {int(time.time())}"
        sett = _require_success(
            "fusion_comp.set_text_plus",
            server.fusion_comp("set_text_plus", {**SCOPE, "text": new_text, "readback": True}),
        )
        if sett.get("readback") != new_text:
            raise AssertionError(f"set_text_plus readback mismatch: wrote {new_text!r}, read {sett.get('readback')!r}")
        reread = _require_success("fusion_comp.get_text_plus(after)", server.fusion_comp("get_text_plus", {**SCOPE}))
        if reread.get("text") != new_text:
            raise AssertionError(f"Independent re-read mismatch: {reread.get('text')!r} != {new_text!r}")
        print(f"set_text_plus + re-read confirmed: {new_text!r}")

        text_tool = sett["tool_name"]

        # --- add_fusion_mask: Rectangle, all friendly params ---
        rect = _require_success(
            "fusion_comp.add_fusion_mask(Rectangle)",
            server.fusion_comp("add_fusion_mask", {
                **SCOPE,
                "mask_type": "Rectangle",
                "name": "RoundedCorners",
                "corner_radius": 0.445,
                "width": 0.3,
                "height": 0.964,
                "center_x": 0.5,
                "center_y": 0.5,
                "readback": True,
            }),
        )
        if rect.get("tool_type") != "RectangleMask":
            raise AssertionError(f"Expected RectangleMask, got {rect!r}")
        by_input = {r["input"]: r for r in rect.get("inputs_set", [])}
        for needed in ("Center", "CornerRadius", "Width", "Height"):
            r = by_input.get(needed)
            if not r or not r.get("success"):
                raise AssertionError(f"Rectangle mask input {needed} not set: {rect!r}")
        # Center is a Point input — its readback should carry both coordinates.
        center_rb = by_input["Center"].get("readback")
        if not center_rb:
            raise AssertionError(f"Center readback missing: {by_input['Center']!r}")
        print(f"add_fusion_mask Rectangle OK; Center readback = {center_rb!r}")

        # --- add_fusion_mask: Ellipse, center list form + connect into Text+ EffectMask ---
        ell = _require_success(
            "fusion_comp.add_fusion_mask(Ellipse)",
            server.fusion_comp("add_fusion_mask", {
                **SCOPE,
                "mask_type": "Ellipse",
                "name": "OvalMask",
                "width": 0.4,
                "height": 0.4,
                "center": [0.25, 0.75],
                "connect_to": text_tool,
                "connect_input": "EffectMask",
                "readback": True,
            }),
        )
        if ell.get("tool_type") != "EllipseMask":
            raise AssertionError(f"Expected EllipseMask, got {ell!r}")
        conn = ell.get("connection") or {}
        if conn.get("success") is not True:
            raise AssertionError(f"Expected mask to wire into {text_tool}.EffectMask: {ell!r}")
        print(f"add_fusion_mask Ellipse wired into {text_tool}.EffectMask OK")

        # --- Honest-failure check: connecting to a node with NO mask input ---
        if media_out:
            no_mask = _require_success(
                "fusion_comp.add_fusion_mask(no-mask-target)",
                server.fusion_comp("add_fusion_mask", {
                    **SCOPE,
                    "mask_type": "Rectangle",
                    "name": "MaskToOutput",
                    "width": 0.5,
                    "connect_to": media_out,            # MediaOut has no EffectMask input
                    "connect_input": "EffectMask",
                }),
            )
            conn2 = no_mask.get("connection") or {}
            if conn2.get("success") is not False:
                raise AssertionError(
                    f"Expected connection.success=False against {media_out} (no mask input): {no_mask!r}"
                )
            # The mask itself must still have been created.
            if not no_mask.get("tool_name"):
                raise AssertionError(f"Mask should still be created even when wiring fails: {no_mask!r}")
            print(f"add_fusion_mask correctly reported connection.success=False against {media_out}")

        if args.keep_open:
            _require_success("resolve_control.open_page", server.resolve_control("open_page", {"page": "fusion"}))
            _require_success("project_manager.save", server.project_manager("save"))
            print(f"LEFT PROJECT OPEN FOR INSPECTION: {project_name}")
            created_project = False

    finally:
        if created_project:
            server.project_manager("save")
            server.project_manager("close")
            delete_result = server.project_manager(
                "delete", {"name": project_name}
            )
            print(f"Deleted disposable project: {delete_result}")

    if delete_result and delete_result.get("success") is not True:
        raise AssertionError(f"Cleanup failed for {project_name}: {delete_result!r}")

    print("LIVE FUSION MASK/TITLE VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
