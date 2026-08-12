#!/usr/bin/env python3
"""Live validation for the timeline_markers playhead/marker timecode contract.

Requires DaVinci Resolve Studio running with Preferences > General >
"External scripting using" set to Local. Creates a disposable project with a
timeline starting at 00:59:50:00 @ 24 fps, then verifies the documented
elapsed-timecode conversion on both surfaces that claim it:

- set_current_timecode: Timeline.SetCurrentTimecode itself REFUSES elapsed
  timecodes (measured on Studio 19.1.3.7: '00:00:21:03' -> False with no
  error info while '01:00:11:03' -> True), so the wrapper must lift sub-start
  timecodes by the start frame before calling Resolve.
- add: marker timecodes below the start timecode are elapsed time and must
  land at the matching relative frame ('00:00:21:03' -> frame 507, the frame
  displayed at 01:00:11:03).

The raw-refusal control runs first so this harness fails loudly if a future
Resolve starts converting elapsed timecodes itself.
"""

from __future__ import annotations

import argparse
import sys
import time
import types
from pathlib import Path

START_TC = "00:59:50:00"
ELAPSED_TC = "00:00:21:03"
ABSOLUTE_TC = "01:00:11:03"
RELATIVE_FRAME = 507
MIN_VISIBLE_FRAMES = 520


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
        raise RuntimeError("stdio_server is not used by this harness")

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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Live playhead/marker elapsed-timecode validation harness"
    )
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="Leave the disposable project open for manual inspection.",
    )
    args = parser.parse_args()

    _install_mcp_stubs()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    import src.server as server

    project_name = f"_mcp_playhead_tc_live_{int(time.time())}"
    timeline_name = "u22_playhead_tc_validation"
    created_project = False
    delete_result = None

    try:
        version = _require_success("resolve_control.get_version", server.resolve_control("get_version"))
        print(f"Connected to {version['product']} {version['version_string']}")

        _require_success("project_manager.create", server.project_manager("create", {"name": project_name}))
        created_project = True
        print(f"Created disposable project: {project_name}")

        proj = server.get_resolve().GetProjectManager().GetCurrentProject()
        if not proj.SetSetting("timelineFrameRate", "24"):
            raise AssertionError("Could not set project timelineFrameRate to 24")

        _require_success("resolve_control.open_page", server.resolve_control("open_page", {"page": "edit"}))
        _require_success(
            "media_pool.create_timeline",
            server.media_pool("create_timeline", {"name": timeline_name}),
        )
        _require_success(
            "timeline.set_start_timecode",
            server.timeline("set_start_timecode", {"timecode": START_TC}),
        )

        current = _require_success("timeline.get_current", server.timeline("get_current"))
        if current["start_timecode"] != START_TC:
            raise AssertionError(
                f"start timecode did not stick: wanted {START_TC}, got {current['start_timecode']!r}"
            )
        start_frame = int(current["start_frame"])
        print(f"Timeline starts at {current['start_timecode']} (frame {start_frame})")

        # Give the timeline enough visible length that frame 507 exists.
        for _ in range(12):
            current = _require_success("timeline.get_current", server.timeline("get_current"))
            visible = int(current["end_frame"]) - int(current["start_frame"])
            if visible >= MIN_VISIBLE_FRAMES:
                break
            _require_success(
                "timeline.insert_generator",
                server.timeline("insert_generator", {"name": "10 Step"}),
            )
        else:
            raise AssertionError(
                f"Could not grow timeline to {MIN_VISIBLE_FRAMES} visible frames (at {visible})"
            )
        print(f"Timeline visible length: {visible} frames")

        tl_obj = proj.GetCurrentTimeline()

        # Control: Resolve itself must still refuse the elapsed timecode.
        # If this starts returning True, Resolve has begun converting elapsed
        # timecodes natively and both the wrapper and its doc need re-scoping.
        raw = tl_obj.SetCurrentTimecode(ELAPSED_TC)
        if raw:
            raise AssertionError(
                f"CONTRACT CHANGED: raw Timeline.SetCurrentTimecode({ELAPSED_TC!r}) "
                "returned True on a timeline starting "
                f"{START_TC} — re-measure before trusting the elapsed-TC lift"
            )
        print(f"Control holds: raw SetCurrentTimecode({ELAPSED_TC!r}) -> False")

        # The wrapper must lift the elapsed timecode and land the playhead.
        _require_success(
            "timeline_markers.set_current_timecode (elapsed)",
            server.timeline_markers("set_current_timecode", {"timecode": ELAPSED_TC}),
        )
        landed = server.timeline_markers("get_current_timecode").get("timecode")
        if landed != ABSOLUTE_TC:
            raise AssertionError(
                f"elapsed lift landed wrong: wanted {ABSOLUTE_TC}, got {landed!r}"
            )
        print(f"Elapsed {ELAPSED_TC} lifted -> playhead at {landed}")

        # Absolute timecodes must keep passing through untouched.
        absolute_probe = "01:00:01:00"
        _require_success(
            "timeline_markers.set_current_timecode (absolute)",
            server.timeline_markers("set_current_timecode", {"timecode": absolute_probe}),
        )
        landed = server.timeline_markers("get_current_timecode").get("timecode")
        if landed != absolute_probe:
            raise AssertionError(
                f"absolute pass-through landed wrong: wanted {absolute_probe}, got {landed!r}"
            )
        print(f"Absolute {absolute_probe} passed through -> playhead at {landed}")

        # U22a: marker add() makes the same elapsed-TC claim.
        add_elapsed = _require_success(
            "timeline_markers.add (elapsed timecode)",
            server.timeline_markers("add", {"timecode": ELAPSED_TC, "color": "Red"}),
        )
        if int(add_elapsed["frame"]) != RELATIVE_FRAME:
            raise AssertionError(
                f"elapsed marker landed at frame {add_elapsed['frame']}, wanted {RELATIVE_FRAME}"
            )
        absolute_next = "01:00:11:04"  # RELATIVE_FRAME + 1, as absolute TC
        add_absolute = _require_success(
            "timeline_markers.add (absolute timecode)",
            server.timeline_markers("add", {"timecode": absolute_next, "color": "Blue"}),
        )
        if int(add_absolute["frame"]) != RELATIVE_FRAME + 1:
            raise AssertionError(
                f"absolute marker landed at frame {add_absolute['frame']}, wanted {RELATIVE_FRAME + 1}"
            )
        markers = server.timeline_markers("get_all").get("markers") or {}
        marker_keys = {int(k) for k in markers}
        missing = {RELATIVE_FRAME, RELATIVE_FRAME + 1} - marker_keys
        if missing:
            raise AssertionError(f"markers missing from GetMarkers(): {sorted(missing)}")
        for frame in (RELATIVE_FRAME, RELATIVE_FRAME + 1):
            if not 0 <= frame <= visible:
                raise AssertionError(
                    f"marker frame {frame} outside visible timeline (0..{visible})"
                )
        print(
            f"Markers landed at relative frames {RELATIVE_FRAME} (from {ELAPSED_TC}) "
            f"and {RELATIVE_FRAME + 1} (from {absolute_next})"
        )

        if args.keep_open:
            _require_success("project_manager.save", server.project_manager("save"))
            print(f"LEFT PROJECT OPEN FOR INSPECTION: {project_name}")
            created_project = False

    finally:
        if created_project:
            server.project_manager("save")
            server.project_manager("close")
            delete_result = server.project_manager("delete", {"name": project_name})
            print(f"Deleted disposable project: {delete_result}")

    if delete_result and delete_result.get("success") is not True:
        raise AssertionError(f"Cleanup failed for {project_name}: {delete_result!r}")

    print("LIVE PLAYHEAD TIMECODE VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
