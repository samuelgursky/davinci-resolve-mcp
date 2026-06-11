#!/usr/bin/env python3
"""Live validation for marker parameter handling.

Requires DaVinci Resolve Studio running with Preferences > General >
"External scripting using" set to Local. This creates a disposable project,
adds timeline markers through the compound server wrappers, verifies them
through Resolve's marker API, and deletes the disposable project.

Frame convention (verified VISUALLY on Resolve Studio 21, 2026-06-11):
Timeline.AddMarker frameIds are RELATIVE to the timeline start — frame 0 is
the first frame of the timeline, even when the timeline starts at
01:00:00:00. GetMarkers() echoes back whatever frameId was passed without
validating or normalizing, so add/get round-trips pass even for markers
stored at absolute frames that display past the end of the timeline
(invisible in the UI). This harness therefore asserts the RELATIVE
convention — returned frames must fit within the timeline's visible length —
instead of trusting round-trips to prove display position. Use --keep-open
to confirm placement visually.
"""

from __future__ import annotations

import argparse
import base64
import sys
import tempfile
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
        raise RuntimeError("stdio_server is not used by the live marker harness")

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


def _require_marker(label, result):
    if not isinstance(result, dict) or not result:
        raise AssertionError(f"{label}: marker lookup returned {result!r}")
    return result


PNG_1X1 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR4nGNgYGD4DwABBAEA"
    "ghO+9wAAAABJRU5ErkJggg=="
)


def _write_synthetic_png() -> str:
    media_dir = Path(tempfile.mkdtemp(prefix="issue34_marker_media_"))
    image_path = media_dir / "issue34_marker_source.png"
    image_path.write_bytes(base64.b64decode(PNG_1X1))
    return str(image_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Live marker validation harness")
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="Leave the disposable project open with markers in place for manual inspection.",
    )
    args = parser.parse_args()

    _install_mcp_stubs()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    import src.server as server

    project_name = f"_mcp_marker_visible_{int(time.time())}" if args.keep_open else f"_mcp_marker_live_{int(time.time())}"
    timeline_name = "issue_34_marker_validation"
    created_project = False
    delete_result = None
    synthetic_media_path = None

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

        synthetic_media_path = _write_synthetic_png()
        proj = server.get_resolve().GetProjectManager().GetCurrentProject()
        mp = proj.GetMediaPool()
        imported = mp.ImportMedia([synthetic_media_path])
        if not imported:
            raise AssertionError(f"Failed to import synthetic media: {synthetic_media_path}")
        media_pool_clip = imported[0]
        media_pool_clip_id = media_pool_clip.GetUniqueId()
        print(f"Imported synthetic media pool clip: {media_pool_clip.GetName()}")

        _require_success(
            "timeline.insert_generator",
            server.timeline("insert_generator", {"name": "10 Step"}),
        )
        print("Inserted 10 Step generator for visible timeline duration")

        current = _require_success("timeline.get_current", server.timeline("get_current"))
        start_frame = int(current["start_frame"])
        timeline_length = int(current["end_frame"]) - start_frame
        if timeline_length <= 0:
            raise AssertionError(f"Timeline has no visible length: {current!r}")
        tl_obj = proj.GetCurrentTimeline()
        fps, fps_err = server._timeline_fps(tl_obj)
        if fps_err:
            raise AssertionError(f"Could not read timeline fps: {fps_err!r}")
        nominal_fps = int(round(fps))
        print(
            f"Timeline starts at {current['start_timecode']} "
            f"(frame {start_frame}), visible length {timeline_length} frames"
        )

        def _require_visible(label, frame):
            # GetMarkers() echoes any frameId back, so round-trips cannot
            # prove display position. Marker frames are relative to the
            # timeline start; a frame past the visible length means the
            # absolute-frame bug has regressed.
            if not 0 <= int(frame) <= timeline_length:
                raise AssertionError(
                    f"{label}: marker frame {frame} is outside the visible "
                    f"timeline (0..{timeline_length}) — frameIds must be "
                    "relative to the timeline start"
                )

        frame_id_marker = f"issue34-frame-id-{int(time.time())}"
        current_marker = f"issue34-current-{int(time.time())}"
        timecode_marker = f"issue34-timecode-{int(time.time())}"

        add_frame_id = _require_success(
            "timeline_markers.add frame_id",
            server.timeline_markers(
                "add",
                {
                    "frame_id": "12",
                    "color": "blue",
                    "note": "Issue #34 frame_id alias live test",
                    "customData": frame_id_marker,
                },
            ),
        )
        if int(add_frame_id["frame"]) != 12:
            raise AssertionError(
                f"frame_id marker: raw frames must pass through unchanged, got {add_frame_id['frame']!r}"
            )
        _require_visible("frame_id marker", add_frame_id["frame"])
        print(f"Added frame_id marker at frame {add_frame_id['frame']}")

        add_current = _require_success(
            "timeline_markers.add current playhead",
            server.timeline_markers(
                "add",
                {
                    "color": "green",
                    "name": "Issue #34 current playhead",
                    "custom_data": current_marker,
                },
            ),
        )
        _require_visible("current-playhead marker", add_current["frame"])
        print(f"Added current-playhead marker at frame {add_current['frame']}")

        # Two seconds past the timeline start, expressed as the absolute
        # timecode the Resolve UI displays (non-drop arithmetic; the
        # disposable project uses a non-drop frame rate).
        start_abs_frame, tc_err = server._timecode_to_frame_id(current["start_timecode"], fps)
        if tc_err:
            raise AssertionError(f"Could not parse start timecode: {tc_err!r}")
        marker_timecode = server._frame_id_to_timecode(start_abs_frame + 2 * nominal_fps, fps)

        add_timecode = _require_success(
            "timeline_markers.add timecode",
            server.timeline_markers(
                "add",
                {
                    "timecode": marker_timecode,
                    "color": "red",
                    "name": "Issue #34 timecode",
                    "custom_data": timecode_marker,
                },
            ),
        )
        if int(add_timecode["frame"]) != 2 * nominal_fps:
            raise AssertionError(
                f"timecode marker: expected {marker_timecode} to land at relative frame "
                f"{2 * nominal_fps}, got {add_timecode['frame']!r}"
            )
        _require_visible("timecode marker", add_timecode["frame"])
        print(f"Added timecode marker {marker_timecode} at frame {add_timecode['frame']}")

        _require_marker(
            "frame_id marker lookup",
            server.timeline_markers("get_by_custom_data", {"customData": frame_id_marker}).get("markers"),
        )
        _require_marker(
            "current marker lookup",
            server.timeline_markers("get_by_custom_data", {"custom_data": current_marker}).get("markers"),
        )
        _require_marker(
            "timecode marker lookup",
            server.timeline_markers("get_by_custom_data", {"custom_data": timecode_marker}).get("markers"),
        )
        print("Verified all markers by custom data")

        timeline_updated_marker = f"issue34-updated-{int(time.time())}"
        _require_success(
            "timeline_markers.update_custom_data frameId",
            server.timeline_markers(
                "update_custom_data",
                {"frameId": add_frame_id["frame"], "customData": timeline_updated_marker},
            ),
        )
        timeline_custom_data = server.timeline_markers(
            "get_custom_data",
            {"frame_id": add_frame_id["frame"]},
        ).get("data")
        if timeline_custom_data != timeline_updated_marker:
            raise AssertionError(
                "timeline_markers.get/update alias mismatch: "
                f"expected {timeline_updated_marker!r}, got {timeline_custom_data!r}"
            )
        print("Verified timeline marker get/update frame aliases")

        mpi_marker = f"issue34-mpi-{int(time.time())}"
        mpi_updated_marker = f"{mpi_marker}-updated"
        _require_success(
            "media_pool_item_markers.add frameId",
            server.media_pool_item_markers(
                "add",
                {
                    "clip_id": media_pool_clip_id,
                    "frameId": "0",
                    "color": "purple",
                    "name": "Issue #34 media pool item",
                    "customData": mpi_marker,
                },
            ),
        )
        _require_marker(
            "media_pool_item marker lookup",
            server.media_pool_item_markers(
                "get_by_custom_data",
                {"clip_id": media_pool_clip_id, "customData": mpi_marker},
            ).get("markers"),
        )
        _require_success(
            "media_pool_item_markers.update_custom_data frame_id",
            server.media_pool_item_markers(
                "update_custom_data",
                {"clip_id": media_pool_clip_id, "frame_id": 0, "customData": mpi_updated_marker},
            ),
        )
        mpi_custom_data = server.media_pool_item_markers(
            "get_custom_data",
            {"clip_id": media_pool_clip_id, "frameId": 0},
        ).get("data")
        if mpi_custom_data != mpi_updated_marker:
            raise AssertionError(
                "media_pool_item_markers.get/update alias mismatch: "
                f"expected {mpi_updated_marker!r}, got {mpi_custom_data!r}"
            )
        _require_success(
            "media_pool_item_markers.delete_at_frame frameId",
            server.media_pool_item_markers(
                "delete_at_frame",
                {"clip_id": media_pool_clip_id, "frameId": 0},
            ),
        )
        print("Verified media pool item marker add/get/update/delete aliases")

        item_marker = f"issue34-ti-{int(time.time())}"
        item_updated_marker = f"{item_marker}-updated"
        _require_success(
            "timeline_item_markers.add frameId",
            server.timeline_item_markers(
                "add",
                {
                    "frameId": "2",
                    "color": "cyan",
                    "name": "Issue #34 timeline item",
                    "customData": item_marker,
                    "track_type": "video",
                    "track_index": 1,
                    "item_index": 0,
                },
            ),
        )
        _require_marker(
            "timeline_item marker lookup",
            server.timeline_item_markers(
                "get_by_custom_data",
                {
                    "customData": item_marker,
                    "track_type": "video",
                    "track_index": 1,
                    "item_index": 0,
                },
            ).get("markers"),
        )
        _require_success(
            "timeline_item_markers.update_custom_data frameId",
            server.timeline_item_markers(
                "update_custom_data",
                {
                    "frameId": 2,
                    "customData": item_updated_marker,
                    "track_type": "video",
                    "track_index": 1,
                    "item_index": 0,
                },
            ),
        )
        item_custom_data = server.timeline_item_markers(
            "get_custom_data",
            {
                "frame_id": 2,
                "track_type": "video",
                "track_index": 1,
                "item_index": 0,
            },
        ).get("data")
        if item_custom_data != item_updated_marker:
            raise AssertionError(
                "timeline_item_markers.get/update alias mismatch: "
                f"expected {item_updated_marker!r}, got {item_custom_data!r}"
            )
        _require_success(
            "timeline_item_markers.delete_at_frame frameId",
            server.timeline_item_markers(
                "delete_at_frame",
                {
                    "frameId": 2,
                    "track_type": "video",
                    "track_index": 1,
                    "item_index": 0,
                },
            ),
        )
        print("Verified timeline item marker add/get/update/delete aliases")

        if args.keep_open:
            _require_success("resolve_control.open_page", server.resolve_control("open_page", {"page": "edit"}))
            _require_success("project_manager.save", server.project_manager("save"))
            print(f"LEFT PROJECT OPEN FOR INSPECTION: {project_name}")
            created_project = False
        else:
            for custom_data in (timeline_updated_marker, current_marker, timecode_marker):
                _require_success(
                    f"timeline_markers.delete_by_custom_data {custom_data}",
                    server.timeline_markers("delete_by_custom_data", {"custom_data": custom_data}),
                )
            print("Removed test markers")

    finally:
        if created_project:
            server.project_manager("save")
            server.project_manager("close")
            delete_result = server.project_manager("delete", {"name": project_name})
            print(f"Deleted disposable project: {delete_result}")

    if delete_result and delete_result.get("success") is not True:
        raise AssertionError(f"Cleanup failed for {project_name}: {delete_result!r}")

    print("LIVE MARKER VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
