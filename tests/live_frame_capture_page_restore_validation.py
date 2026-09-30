#!/usr/bin/env python3
"""Live validation: a frame capture puts Resolve back on the page it started on.

Issue #270 (reported on Studio 21.1.0.17, reproduced on 19.1.3.7):
timeline_frame(action="capture") through the render route left Resolve on the
Deliver page. Cause, measured on 19.1.3.7: Project.GetCurrentRenderMode() — a
getter — switches Resolve to Deliver, and the capture read "the page the user
is on" after calling it, so it recorded 'deliver' and restored nothing.

Requires DaVinci Resolve Studio running with Preferences > General >
"External scripting using" set to Local. Creates a disposable project with a
generator-only timeline, then:

  0. Control: calls the raw getter from the Edit page and prints whether this
     build switches page on it. Informational — either answer is a finding.
  A. Captures once while the project has never had a render output folder.
     There is nothing to read back then (AddRenderJob returns ''), and the
     capture must still work and say nothing.
  B. Gives the project a user's render settings — a .mov format, an output
     folder and a custom file name — and records what a render job queued
     now would inherit.
  1. For each starting page: parks the playhead, captures a DIFFERENT frame
     through the render route, and reads the page, playhead and current
     timeline back. The Media and Fusion pages are included; if a capture is
     refused there the page must still be where it started.
  2. After each capture, queues a throwaway render job and compares what IT
     inherits with the record from B: output folder, file name, range, and the
     render format. The render queue must be as empty as it was.
  3. render(action="get_mode") from the Edit page must leave the page alone.
  4. One capture with the project in Individual-clips render mode: the mode,
     and everything in B, must come back.

A pass needs every page read back to be the starting page, every job readback
to match B, AND no capture to carry a warnings block. The harness also prints
how many OpenPage attempts each restore needed on this build.

The project that was open beforehand is saved before the switch and loaded
again at the end.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

PAGES = ("edit", "color", "fairlight", "cut", "media", "fusion", "deliver")
PARK_TC = "01:00:02:00"
USER_NAME = "user reel A"
# Captured frame, as an offset from the timeline start. Deliberately NOT the
# parked frame: if the capture renders the frame the playhead is already on, a
# playhead left on the rendered frame is indistinguishable from one put back.
CAPTURE_OFFSET = 120


def _install_mcp_stubs() -> None:
    """Stand in for the MCP SDK only when it is genuinely absent.

    Delegates to the shared installer so this harness cannot drift behind the
    imports `src.server` actually makes; see `src/utils/mcp_import_stubs.py`.
    """
    repo_root = str(Path(__file__).resolve().parents[1])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from src.utils.mcp_import_stubs import install_mcp_stubs

    install_mcp_stubs(stdio_note="stdio_server is not used by this live harness")


def _require_success(label, result):
    if not isinstance(result, dict):
        raise AssertionError(f"{label}: expected dict, got {result!r}")
    if result.get("error"):
        raise AssertionError(f"{label}: {result['error']}")
    if "success" in result and result["success"] is not True:
        raise AssertionError(f"{label}: expected success=True, got {result!r}")
    return result


def _park(tl) -> None:
    """Park the playhead and wait until a readback agrees, twice.

    Observed twice on Studio 19.1.3.7 while building this harness: a
    SetCurrentTimecode issued immediately after OpenPage away from the Deliver
    page returned True and did not move the playhead. Not characterised
    further, so the harness does not lean on a single call.
    """
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        tl.SetCurrentTimecode(PARK_TC)
        if tl.GetCurrentTimecode() == PARK_TC:
            time.sleep(0.5)
            if tl.GetCurrentTimecode() == PARK_TC:
                return
        time.sleep(0.1)
    raise AssertionError(
        f"could not park the playhead at {PARK_TC}; it reads {tl.GetCurrentTimecode()!r}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Live frame-capture page-restore validation harness (issue #270)"
    )
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="Leave the disposable project open for manual inspection.",
    )
    parser.add_argument(
        "--repeat", type=int, default=2,
        help="Captures per starting page (default 2).",
    )
    args = parser.parse_args()

    _install_mcp_stubs()

    import src.server as server

    project_name = f"_mcp_capture_page_live_{int(time.time())}"
    timeline_name = "capture_page_restore_validation"
    created_project = False
    delete_result = None
    previous_project = None
    failures = []
    rows = []
    user_root = tempfile.mkdtemp(prefix="mcp-capture-live-")
    user_target = os.path.join(user_root, "user deliveries")
    os.makedirs(user_target)

    try:
        version = _require_success("resolve_control.get_version", server.resolve_control("get_version"))
        print(f"Connected to {version['product']} {version['version_string']}")

        previous_project = (server.project_manager("get_current") or {}).get("name")
        if previous_project:
            # With a UI, switching away from a project with unsaved changes
            # raises a dialog no script can dismiss. Save first, and stop here
            # when that is refused (the never-saved "Untitled Project" is) —
            # a harness must not be the thing that loses someone's work.
            saved = server.project_manager("save")
            if saved.get("success") is not True:
                raise AssertionError(
                    f"could not save the open project {previous_project!r} before switching "
                    "away from it; save or close it by hand, then re-run"
                )
            print(f"Saved the open project before switching: {previous_project}")

        _require_success("project_manager.create", server.project_manager("create", {"name": project_name}))
        created_project = True
        print(f"Created disposable project: {project_name}")

        resolve = server.get_resolve()
        proj = resolve.GetProjectManager().GetCurrentProject()
        _require_success("resolve_control.open_page", server.resolve_control("open_page", {"page": "edit"}))
        _require_success(
            "media_pool.create_timeline",
            server.media_pool("create_timeline", {"name": timeline_name}),
        )
        for _ in range(2):
            _require_success(
                "timeline.insert_generator",
                server.timeline("insert_generator", {"name": "10 Step"}),
            )
        tl = proj.GetCurrentTimeline()
        tl_start, tl_end = int(tl.GetStartFrame()), int(tl.GetEndFrame())

        # 0. Control: does the raw getter move the page on this build?
        resolve.OpenPage("edit")
        raw_mode = proj.GetCurrentRenderMode()
        after_getter = resolve.GetCurrentPage()
        print(
            f"Control: raw GetCurrentRenderMode() -> {raw_mode!r} from 'edit' left Resolve on "
            f"{after_getter!r} ({'SWITCHES page' if after_getter != 'edit' else 'does not switch page'})"
        )

        def _inherits():
            """What a render job queued right now would inherit, or None."""
            job = proj.AddRenderJob()
            if not job:
                return None
            try:
                for entry in proj.GetRenderJobList() or []:
                    if entry.get("JobId") == job:
                        return {
                            "TargetDir": entry.get("TargetDir"),
                            "OutputFilename": entry.get("OutputFilename"),
                            "MarkIn": entry.get("MarkIn"),
                            "MarkOut": entry.get("MarkOut"),
                            "format": proj.GetCurrentRenderFormatAndCodec(),
                        }
                return None
            finally:
                proj.DeleteRenderJob(job)

        def _image_of(result):
            """(image or error dict, warnings) from a capture result."""
            if isinstance(result, list):
                return result[0], result[1].get("warnings")
            return result, None

        # A. Never had an output folder: nothing to read, nothing to say.
        resolve.OpenPage("edit")
        unset = _inherits()
        first, first_warnings = _image_of(server.timeline_frame(
            "capture", {"quality": "frame", "format": "jpg", "frame": tl_start + CAPTURE_OFFSET}))
        print(
            f"A. no output folder yet: a job queues -> {unset is not None}; capture -> "
            f"{type(first).__name__}, warnings {first_warnings}"
        )
        if unset is not None:
            failures.append("A: expected a fresh project to refuse a render job (no TargetDir)")
        if isinstance(first, dict) or first_warnings:
            failures.append(f"A: capture with no output folder: {first if isinstance(first, dict) else first_warnings}")

        # B. A user's render settings, and what a job inherits from them.
        mov_codecs = proj.GetRenderCodecs("mov") or {}
        if not proj.SetCurrentRenderFormatAndCodec("mov", list(mov_codecs.values())[0]):
            raise AssertionError("could not select the mov render format")
        if not proj.SetRenderSettings({"TargetDir": user_target, "CustomName": USER_NAME,
                                       "SelectAllFrames": True}):
            raise AssertionError("could not apply the user's render settings")
        baseline = _inherits()
        queue_baseline = len(proj.GetRenderJobList() or [])
        print(f"B. a job inherits: {baseline}")
        if not baseline or baseline["TargetDir"] != user_target \
                or not baseline["OutputFilename"].startswith(USER_NAME):
            raise AssertionError(f"the user's render settings did not read back: {baseline}")
        if (baseline["MarkIn"], baseline["MarkOut"]) != (tl_start, tl_end - 1):
            raise AssertionError(f"expected the whole timeline as the starting range: {baseline}")

        # Record what the restore actually did, without changing it.
        outcomes = []
        real_restore = server._restore_page

        def _recording_restore(*a, **k):
            outcome = real_restore(*a, **k)
            outcomes.append(outcome)
            return outcome

        with mock.patch.object(server, "_restore_page", side_effect=_recording_restore):
            for page in PAGES:
                for run in range(1, max(1, args.repeat) + 1):
                    # Park from the Edit page: SetCurrentTimecode returns False
                    # on the Media and Fusion pages (measured on 19.1.3.7).
                    resolve.OpenPage("edit")
                    _park(tl)
                    if not resolve.OpenPage(page):
                        print(f"  {page:<9} skipped: OpenPage({page!r}) refused on this build")
                        break
                    started = resolve.GetCurrentPage()
                    del outcomes[:]
                    t0 = time.monotonic()
                    result = server.timeline_frame(
                        "capture",
                        {"quality": "frame", "format": "jpg", "frame": tl_start + CAPTURE_OFFSET},
                    )
                    elapsed = time.monotonic() - t0
                    ended = resolve.GetCurrentPage()
                    time.sleep(0.5)  # a late move must not pass as a restore
                    playhead = tl.GetCurrentTimecode()
                    if playhead is None:
                        # The Media and Fusion pages have no timeline playhead
                        # to read (None on 19.1.3.7). Read it from Edit instead;
                        # the page has already been recorded above.
                        resolve.OpenPage("edit")
                        time.sleep(0.5)
                        playhead = tl.GetCurrentTimecode()
                    current = proj.GetCurrentTimeline()

                    image, warnings = _image_of(result)
                    if isinstance(image, dict):
                        message = (image.get("error") or {}).get("message")
                        print(f"  {page:<9} #{run}: capture refused ({message}); page {ended!r}")
                        if page in ("edit", "color", "fairlight", "cut", "deliver"):
                            failures.append(f"{page} #{run}: capture failed: {message}")
                        if ended != started:
                            failures.append(
                                f"{page} #{run}: refused capture ended on {ended!r}, started on {started!r}"
                            )
                        continue
                    attempts = outcomes[-1]["attempts"] if outcomes else None
                    rows.append((page, run, started, ended, attempts, round(elapsed, 2), warnings))
                    print(
                        f"  {page:<9} #{run}: started {started!r}, ended {ended!r}, "
                        f"OpenPage attempts {attempts}, {elapsed:.2f}s, "
                        f"{len(getattr(image, 'data', b'') or b'')} bytes, warnings {warnings}"
                    )
                    if ended != started:
                        failures.append(f"{page} #{run}: ended on {ended!r}, started on {started!r}")
                    if warnings:
                        failures.append(f"{page} #{run}: capture carried warnings {warnings}")
                    if started == "deliver" and outcomes:
                        failures.append(f"{page} #{run}: a Deliver-page caller was switched")
                    if playhead != PARK_TC:
                        failures.append(f"{page} #{run}: playhead at {playhead!r}, parked at {PARK_TC}")
                    if not current or current.GetName() != timeline_name:
                        failures.append(f"{page} #{run}: current timeline changed")
                    # 2. Read last: queuing a job moves the page by itself.
                    inherited = _inherits()
                    if inherited != baseline:
                        failures.append(
                            f"{page} #{run}: a job queued after the capture would inherit "
                            f"{inherited}, not {baseline}"
                        )
                    queued = len(proj.GetRenderJobList() or [])
                    if queued != queue_baseline:
                        failures.append(
                            f"{page} #{run}: render queue holds {queued} job(s), was {queue_baseline}"
                        )

        # 3. The render-mode read on its own must not move the user.
        resolve.OpenPage("edit")
        mode = server.render("get_mode")
        after_read = resolve.GetCurrentPage()
        print(f"  render.get_mode -> {mode.get('mode')!r}, page afterwards {after_read!r}")
        if after_read != "edit":
            failures.append(f"render.get_mode left Resolve on {after_read!r}")

        # 4. Individual-clips mode: the capture forces single clip, and the
        # output folder is read only once it has.
        resolve.OpenPage("edit")
        _park(tl)
        if not proj.SetCurrentRenderMode(0):
            raise AssertionError("could not select Individual-clips render mode")
        resolve.OpenPage("edit")
        image, warnings = _image_of(server.timeline_frame(
            "capture", {"quality": "frame", "format": "jpg", "frame": tl_start + CAPTURE_OFFSET}))
        page_after = resolve.GetCurrentPage()
        mode_after = proj.GetCurrentRenderMode()
        proj.SetCurrentRenderMode(1)
        inherited = _inherits()
        print(
            f"  individual-clips mode: capture {type(image).__name__}, warnings {warnings}, "
            f"mode afterwards {mode_after!r}, page {page_after!r}, job inherits baseline: "
            f"{inherited == baseline}"
        )
        if isinstance(image, dict) or warnings:
            failures.append(f"mode 0: capture {image if isinstance(image, dict) else warnings}")
        if mode_after != 0:
            failures.append(f"mode 0: render mode came back as {mode_after!r}")
        if page_after != "edit":
            failures.append(f"mode 0: ended on {page_after!r}")
        if inherited != baseline:
            failures.append(f"mode 0: a job would inherit {inherited}, not {baseline}")
        queued = len(proj.GetRenderJobList() or [])
        if queued != queue_baseline:
            failures.append(f"mode 0: render queue holds {queued} job(s), was {queue_baseline}")

        if not rows:
            failures.append("no capture ran")

        if args.keep_open:
            _require_success("project_manager.save", server.project_manager("save"))
            print(f"LEFT PROJECT OPEN FOR INSPECTION: {project_name}")
            created_project = False

    finally:
        if created_project:
            server.resolve_control("open_page", {"page": "edit"})
            server.project_manager("save")
            server.project_manager("close")
            delete_result = server.project_manager("delete", {"name": project_name})
            print(f"Deleted disposable project: {delete_result}")
            if previous_project and previous_project != project_name:
                reloaded = server.project_manager("load", {"name": previous_project})
                print(f"Reloaded the project that was open before: {reloaded.get('success')}")
        shutil.rmtree(user_root, ignore_errors=True)

    if delete_result and delete_result.get("success") is not True:
        raise AssertionError(f"Cleanup failed for {project_name}: {delete_result!r}")
    if failures:
        raise AssertionError("page restore did not hold:\n  " + "\n  ".join(failures))

    worst = max((r[4] or 0) for r in rows)
    print(f"Worst case: {worst} OpenPage attempt(s) to get back")
    print("LIVE FRAME CAPTURE PAGE RESTORE VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
