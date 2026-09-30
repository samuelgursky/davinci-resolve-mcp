"""timeline_frame — capture what Resolve renders at the playhead, as an image.

Covers the four things the tool promises beyond the old
timeline_markers(action="get_thumbnail_image"): a timecode/frame target, the
Color-page switch, max_width, and a named timeline — plus the invariant that a
capture is a *read*: page, playhead, current timeline, gallery, and the temp
directory all come back the way the caller left them.
"""
import asyncio
import base64
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from mcp.server.fastmcp import Image

import src.server as s
from src.utils import page_lock


class _FakeResolve:
    def __init__(self, page="edit", switch_ok=True):
        self.page = page
        self.switch_ok = switch_ok
        self.opened = []

    def GetCurrentPage(self):
        return self.page

    def OpenPage(self, page):
        self.opened.append(page)
        if self.switch_ok:
            self.page = page
        return self.switch_ok


class _SettlingResolve(_FakeResolve):
    """A Resolve whose page switch does not take straight away (issue #270).

    `refusals` OpenPage calls return False and change nothing before the switch
    starts working; `lies=True` makes OpenPage return True while staying put.
    """

    def __init__(self, page="edit", refusals=0, lies=False):
        super().__init__(page=page)
        self.refusals = refusals
        self.lies = lies

    def OpenPage(self, page):
        self.opened.append(page)
        if self.lies:
            return True
        if self.refusals > 0:
            self.refusals -= 1
            return False
        self.page = page
        return True


def _fake_timeline(resolve, width=4, height=2, name="TL"):
    """A timeline whose thumbnail exists only while Resolve is on the Color page."""
    tl = mock.Mock()
    tl.GetName.return_value = name
    tl.current_tc = "01:00:00:00"
    tl.GetCurrentTimecode.side_effect = lambda: tl.current_tc

    def _set_tc(tc):
        tl.current_tc = tc
        return True

    tl.SetCurrentTimecode.side_effect = _set_tc
    raw = bytes([10, 20, 30] * (width * height))
    tl.GetCurrentClipThumbnailImage.side_effect = lambda: (
        {
            "width": width,
            "height": height,
            "noOfComponents": 3,
            "depth": 8,
            "data": base64.b64encode(raw).decode("ascii"),
        }
        if resolve.page == "color" else None
    )
    return tl


def _png_dimensions(png: bytes):
    """(width, height) from the IHDR chunk."""
    import struct
    offset = png.index(b"IHDR") + 4
    return struct.unpack(">II", png[offset:offset + 8])


class BoxDownscaleTest(unittest.TestCase):
    def test_no_op_when_already_within_max_width(self):
        raw = bytes([1, 2, 3] * 4)
        self.assertEqual(s._box_downscale_rgb(2, 2, raw, 10), (2, 2, raw))

    def test_averages_rather_than_dropping_pixels(self):
        # 2x1 of black and white; halving must yield the mean, not either source
        # pixel — nearest-neighbour would return 0 or 255.
        raw = bytes([0, 0, 0, 254, 254, 254])
        width, height, out = s._box_downscale_rgb(2, 1, raw, 1)
        self.assertEqual((width, height), (1, 1))
        self.assertEqual(out, bytes([127, 127, 127]))

    def test_preserves_aspect_ratio(self):
        raw = bytes([0, 0, 0] * (8 * 4))
        width, height, _ = s._box_downscale_rgb(8, 4, raw, 4)
        self.assertEqual((width, height), (4, 2))


class CapturePreviewTest(unittest.TestCase):
    def _capture(self, params, resolve=None, tl=None, proj=None):
        resolve = resolve or _FakeResolve(page="edit")
        tl = tl if tl is not None else _fake_timeline(resolve)
        proj = proj or mock.Mock()
        # quality="thumbnail" is this class's subject: the clip-thumbnail route.
        params = {"quality": "thumbnail", **params}
        with mock.patch.object(s, "get_resolve", return_value=resolve), \
             mock.patch.object(s, "_get_tl", return_value=(proj, tl, None)):
            return s.timeline_frame("capture", params), resolve, tl

    def test_returns_png_image_content(self):
        out, _, _ = self._capture({})
        self.assertIsInstance(out, Image)
        self.assertTrue(out.data.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(_png_dimensions(out.data), (4, 2))

    def test_switches_to_color_page_and_restores(self):
        out, resolve, _ = self._capture({})
        self.assertIsInstance(out, Image)
        self.assertEqual(resolve.opened, ["color", "edit"])
        self.assertEqual(resolve.page, "edit")

    def test_max_width_downscales_the_returned_png(self):
        out, _, _ = self._capture({"max_width": 2})
        self.assertIsInstance(out, Image)
        self.assertEqual(_png_dimensions(out.data), (2, 1))

    def test_timecode_moves_the_playhead_and_puts_it_back(self):
        resolve = _FakeResolve(page="color")
        tl = _fake_timeline(resolve)
        with mock.patch.object(s, "_playhead_absolute_timecode", side_effect=lambda tl, tc: tc):
            out, _, tl = self._capture({"timecode": "01:00:15:12"}, resolve=resolve, tl=tl)
        self.assertIsInstance(out, Image)
        tl.SetCurrentTimecode.assert_any_call("01:00:15:12")
        self.assertEqual(tl.current_tc, "01:00:00:00")

    def test_no_position_argument_leaves_the_playhead_untouched(self):
        out, _, tl = self._capture({})
        self.assertIsInstance(out, Image)
        tl.SetCurrentTimecode.assert_not_called()

    def test_rejected_timecode_is_an_error_not_a_wrong_frame(self):
        resolve = _FakeResolve(page="color")
        tl = _fake_timeline(resolve)
        tl.SetCurrentTimecode.side_effect = lambda tc: False
        out, _, _ = self._capture({"timecode": "99:00:00:00"}, resolve=resolve, tl=tl)
        self.assertEqual(out["error"]["code"], "SEEK_FAILED")

    def test_page_switch_failure_names_the_color_page_requirement(self):
        # Headless or page-locked: the thumbnail is None for a reason the caller
        # can act on, and must not read as "no frame here".
        resolve = _FakeResolve(page="edit", switch_ok=False)
        out, _, _ = self._capture({}, resolve=resolve)
        self.assertEqual(out["error"]["code"], "NO_THUMBNAIL")
        self.assertIn("Color page", out["error"]["message"])

    def test_invalid_quality_is_rejected(self):
        out, _, _ = self._capture({"quality": "ultra"})
        self.assertEqual(out["error"]["code"], "INVALID_QUALITY")

    def test_unknown_timeline_name_is_rejected(self):
        proj = mock.Mock()
        proj.GetTimelineCount.return_value = 1
        other = mock.Mock()
        other.GetName.return_value = "Other"
        proj.GetTimelineByIndex.return_value = other
        out, _, _ = self._capture({"timeline_name": "Missing"}, proj=proj)
        self.assertEqual(out["error"]["code"], "TIMELINE_NOT_FOUND")

    def test_named_timeline_is_restored_afterwards(self):
        resolve = _FakeResolve(page="color")
        current = _fake_timeline(resolve, name="Current")
        other = _fake_timeline(resolve, name="Other")
        proj = mock.Mock()
        proj.GetTimelineCount.return_value = 1
        proj.GetTimelineByIndex.return_value = other
        # The switch is verified by readback, so the fake has to honour it: a
        # project that says True and stays put is reported as a failed restore.
        active = {"tl": current}
        proj.GetCurrentTimeline.side_effect = lambda: active["tl"]
        proj.SetCurrentTimeline.side_effect = lambda tl: active.update(tl=tl) or True
        out, _, _ = self._capture({"timeline_name": "Other"}, resolve=resolve, tl=current, proj=proj)
        self.assertIsInstance(out, Image)
        self.assertEqual(
            [c.args[0] for c in proj.SetCurrentTimeline.call_args_list],
            [other, current],
        )


class CaptureFullTest(unittest.TestCase):
    def _capture(self, params, ffmpeg=None, export_ok=True):
        resolve = _FakeResolve(page="color")
        tl = _fake_timeline(resolve)
        still = object()
        tl.GrabStill.return_value = still
        album = mock.Mock()
        proj = mock.Mock()
        proj.GetGallery.return_value.GetCurrentStillAlbum.return_value = album

        written = {}

        def _export(stills, folder, prefix, fmt):
            if not export_ok:
                return False
            import os
            path = os.path.join(folder, f"{prefix}.{fmt}")
            with open(path, "wb") as handle:
                handle.write(b"\x89PNG\r\n\x1a\nfake")
            written["path"] = path
            return True

        album.ExportStills.side_effect = _export
        with mock.patch.object(s, "get_resolve", return_value=resolve), \
             mock.patch.object(s, "_get_tl", return_value=(proj, tl, None)), \
             mock.patch.object(s.shutil, "which", return_value=ffmpeg), \
             mock.patch.object(s, "_ffmpeg_scale_to_bytes", return_value=(b"\x89PNG\r\n\x1a\nsmall", None)):
            out = s.timeline_frame("capture", {"quality": "still", **params})
        return out, album, still, written

    def test_returns_the_exported_bytes_as_image_content(self):
        out, _, _, _ = self._capture({})
        self.assertIsInstance(out, Image)
        self.assertTrue(out.data.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_grabbed_still_is_removed_from_the_gallery(self):
        # A capture is a read; it must not leave stills in the user's gallery.
        out, album, still, _ = self._capture({})
        self.assertIsInstance(out, Image)
        album.DeleteStills.assert_called_once_with([still])

    def test_exported_file_is_cleaned_up(self):
        import os
        out, _, _, written = self._capture({})
        self.assertIsInstance(out, Image)
        self.assertFalse(os.path.exists(written["path"]))

    def test_max_width_without_ffmpeg_fails_instead_of_returning_full_size(self):
        out, _, _, _ = self._capture({"max_width": 640}, ffmpeg=None)
        self.assertEqual(out["error"]["code"], "FFMPEG_REQUIRED")

    def test_max_width_with_ffmpeg_returns_the_rescaled_bytes(self):
        out, _, _, _ = self._capture({"max_width": 640}, ffmpeg="/usr/bin/ffmpeg")
        self.assertIsInstance(out, Image)
        self.assertEqual(out.data, b"\x89PNG\r\n\x1a\nsmall")

    def test_non_displayable_format_is_rejected(self):
        out, _, _, _ = self._capture({"format": "dpx"})
        self.assertEqual(out["error"]["code"], "INVALID_FORMAT")

    def test_export_failure_is_reported(self):
        out, _, _, _ = self._capture({}, export_ok=False)
        self.assertEqual(out["error"]["code"], "EXPORT_STILL_FAILED")


def _restored_range(calls):
    """The last SetRenderSettings payload that carried a render range."""
    return [c for c in calls if "MarkIn" in c][-1]


USER_TARGET = "/Volumes/Deliveries/reel one"


class _RenderCapture:
    """Drives quality='frame' against a fake project that renders one file.

    The fake behaves the way Studio 19.1.3.7 was measured to (2026-09-30):

    - GetCurrentRenderMode — a getter — switches Resolve to the Deliver page.
    - A SetRenderSettings payload carrying an empty CustomName, or an empty
      TargetDir, is refused WHOLE: nothing in it is applied.
    - There is no GetRenderSettings. A queued job is the readback: its
      GetRenderJobList entry carries the TargetDir, file name and range it
      inherited. With no TargetDir set, AddRenderJob returns ''.
    - A render writes `<custom name, or the timeline name><frame>.<ext>`.

    `proj.render_state` is what Resolve would actually hold afterwards, which
    is what the user's next render job inherits.
    """

    def _capture(self, params, rendering=False, status="Complete",
                 write=True, ffmpeg="/usr/bin/ffmpeg", marks=None, mode=1, mode_switch=True,
                 resolve=None, range_restore_ok=True, user_target=USER_TARGET,
                 user_name="userA", target_restore_ok=True, job_delete_ok=True,
                 existing=None):
        """Returns (result, project mock, list of SetRenderSettings payloads)."""
        resolve = resolve or _FakeResolve(page="color")
        tl = _fake_timeline(resolve)
        tl.GetStartFrame.return_value = 86400
        tl.GetEndFrame.return_value = 86544
        tl.GetMarkInOut.return_value = marks if marks is not None else {}
        proj = mock.Mock()
        state = {"TargetDir": user_target, "CustomName": user_name, "range": None,
                 "jobs": {}, "queued": 0}
        proj.render_state = state
        proj.IsRenderingInProgress.side_effect = [rendering, False]

        def _mode():
            resolve.page = "deliver"
            return mode

        proj.GetCurrentRenderMode.side_effect = _mode
        proj.SetCurrentRenderMode.return_value = mode_switch
        proj.GetCurrentRenderFormatAndCodec.return_value = {"format": "mov", "codec": "H.264"}
        proj.GetRenderCodecs.return_value = {"JPEG": "YUV420_8"}
        proj.SetCurrentRenderFormatAndCodec.return_value = True
        proj.GetRenderJobStatus.return_value = (
            status if isinstance(status, dict) else {"JobStatus": status}
        )

        calls = []

        def _settings(payload):
            calls.append(dict(payload))
            if payload.get("CustomName") == "" or ("TargetDir" in payload and not payload["TargetDir"]):
                return False  # refused whole: nothing below is applied
            if "MarkIn" in payload and "TargetDir" not in payload and not range_restore_ok:
                return False
            if set(payload) == {"TargetDir"} and not target_restore_ok:
                return False
            for key in ("TargetDir", "CustomName"):
                if key in payload:
                    state[key] = payload[key]
            if "MarkIn" in payload:
                state["range"] = (payload["SelectAllFrames"], payload["MarkIn"], payload["MarkOut"])
            return True

        def _add_job():
            resolve.page = "deliver"
            if not state["TargetDir"]:
                return ""
            state["queued"] += 1
            job_id = f"job-{state['queued']}"
            state["jobs"][job_id] = {
                "JobId": job_id,
                "TargetDir": state["TargetDir"],
                "OutputFilename": f"{state['CustomName'] or 'TL'}.mov",
            }
            return job_id

        def _delete_job(job_id):
            if not job_delete_ok:
                return False
            return state["jobs"].pop(job_id, None) is not None

        def _start(jobs, interactive=False, **kwargs):
            # Rendering pulls Resolve onto the Deliver page, whatever page the
            # caller was on.
            resolve.page = "deliver"
            # Resolve writes the file during the render, named by the project:
            # the custom name or the timeline name, then the frame number.
            if write:
                folder = state["jobs"][jobs[0]]["TargetDir"]
                os.makedirs(folder, exist_ok=True)
                with open(os.path.join(folder, f"{state['CustomName'] or 'TL'}00086424.jpg"), "wb") as fh:
                    fh.write(b"\xff\xd8rendered")
            return True

        proj.SetRenderSettings.side_effect = _settings
        proj.AddRenderJob.side_effect = _add_job
        proj.GetRenderJobList.side_effect = lambda: [dict(j) for j in state["jobs"].values()]
        proj.DeleteRenderJob.side_effect = _delete_job
        proj.StartRendering.side_effect = _start
        # The shared capture folder, kept off the real ~/Documents.
        base = os.path.join(tempfile.mkdtemp(prefix="capture-test-"), "resolve-frame-captures")
        self.addCleanup(shutil.rmtree, os.path.dirname(base), True)
        self.capture_base = base
        for filename in existing or ():
            os.makedirs(base, exist_ok=True)
            with open(os.path.join(base, filename), "wb") as fh:
                fh.write(b"someone else's file")
        with mock.patch.object(s, "get_resolve", return_value=resolve), \
             mock.patch.object(s, "_get_tl", return_value=(proj, tl, None)), \
             mock.patch.object(s, "_resolve_safe_dir", return_value=base), \
             mock.patch.object(s.shutil, "which", return_value=ffmpeg), \
             mock.patch.object(s, "_ffmpeg_scale_to_bytes", return_value=(b"\xff\xd8scaled", None)), \
             mock.patch.object(page_lock.time, "sleep"):
            out = s.timeline_frame("capture", params)
        return out, proj, calls


class CaptureRenderTest(_RenderCapture, unittest.TestCase):
    """quality='frame' — the default, and the only frame-accurate route."""

    def test_render_is_the_default_quality(self):
        out, proj, _ = self._capture({})
        self.assertIsInstance(out, Image)
        proj.StartRendering.assert_called_once()

    def test_renders_a_single_frame_range(self):
        out, _, calls = self._capture({"frame": 86424})
        self.assertIsInstance(out, Image)
        # MarkIn == MarkOut is what makes this one frame rather than a clip.
        self.assertEqual(calls[0]["MarkIn"], 86424)
        self.assertEqual(calls[0]["MarkOut"], 86424)
        self.assertFalse(calls[0]["SelectAllFrames"])

    def test_render_job_is_deleted_afterwards(self):
        out, proj, _ = self._capture({})
        self.assertIsInstance(out, Image)
        # Two were queued — the output-folder readback and the capture itself —
        # and neither is left in the user's render queue.
        self.assertEqual(proj.render_state["queued"], 2)
        self.assertEqual(proj.render_state["jobs"], {})

    def test_render_format_is_restored(self):
        out, proj, _ = self._capture({})
        self.assertIsInstance(out, Image)
        self.assertEqual(
            proj.SetCurrentRenderFormatAndCodec.call_args_list[-1].args,
            ("mov", "H.264"),
        )

    def test_individual_clips_mode_is_forced_to_single_clip_and_restored(self):
        # Measured 2026-09-09: in "Individual clips" mode (0) the single-frame
        # capture rendered the WHOLE clip under Resolve's own naming and the
        # expected file never appeared ("reported success, wrote no file").
        out, proj, _ = self._capture({"frame": 86424}, mode=0)
        self.assertIsInstance(out, Image)
        modes = [c.args[0] for c in proj.SetCurrentRenderMode.call_args_list]
        self.assertEqual(modes, [1, 0])
        # the switch happens before the job is added, the restore after
        self.assertLess(
            proj.method_calls.index(mock.call.SetCurrentRenderMode(1)),
            proj.method_calls.index(mock.call.AddRenderJob()),
        )

    def test_single_clip_mode_is_left_alone(self):
        out, proj, _ = self._capture({"frame": 86424}, mode=1)
        self.assertIsInstance(out, Image)
        proj.SetCurrentRenderMode.assert_not_called()

    def test_refused_mode_switch_is_an_error_before_any_job(self):
        out, proj, _ = self._capture({"frame": 86424}, mode=0, mode_switch=False)
        self.assertEqual(out["error"]["code"], "RENDER_MODE_REFUSED")
        proj.AddRenderJob.assert_not_called()

    def test_mark_range_falls_back_to_the_whole_timeline(self):
        # No marks were set, so there is nothing to restore. It must still not be
        # left pinned to the captured frame.
        out, _, calls = self._capture({"frame": 86424})
        self.assertIsInstance(out, Image)
        self.assertTrue(_restored_range(calls)["SelectAllFrames"])
        self.assertEqual(_restored_range(calls)["MarkIn"], 86400)
        self.assertEqual(_restored_range(calls)["MarkOut"], 86544)

    def test_the_range_resolve_holds_afterwards_is_not_the_captured_frame(self):
        # The range restore used to share a payload with CustomName "", which
        # Resolve refuses whole (measured on 19.1.3.7), so the range stayed
        # pinned to the captured frame and the next render job inherited it.
        out, proj, _ = self._capture({"frame": 86424})
        self.assertIsInstance(out, Image)
        self.assertEqual(proj.render_state["range"], (True, 86400, 86544))

    def test_an_existing_mark_range_is_restored(self):
        out, _, calls = self._capture(
            {"frame": 86424}, marks={"video": {"in": 86410, "out": 86500},
                                     "audio": {"in": 86410, "out": 86500}})
        self.assertIsInstance(out, Image)
        self.assertFalse(_restored_range(calls)["SelectAllFrames"])
        self.assertEqual(_restored_range(calls)["MarkIn"], 86410)
        self.assertEqual(_restored_range(calls)["MarkOut"], 86500)

    def test_a_relative_mark_range_is_offset_by_the_timeline_start(self):
        # GetMarkInOut reports marks relative to the timeline start (Resolve's
        # own example is in=0/out=134) while SetRenderSettings takes absolute
        # record frames; on 19.1.3.7 a MarkIn below the start is silently
        # clamped to the start. A relative range must come back offset.
        out, _, calls = self._capture(
            {"frame": 86424}, marks={"video": {"in": 10, "out": 100},
                                     "audio": {"in": 10, "out": 100}})
        self.assertIsInstance(out, Image)
        self.assertFalse(_restored_range(calls)["SelectAllFrames"])
        self.assertEqual(_restored_range(calls)["MarkIn"], 86410)
        self.assertEqual(_restored_range(calls)["MarkOut"], 86500)

    def test_a_half_set_mark_range_is_not_treated_as_a_range(self):
        # Only an in point: restoring it as a range would invent an out point.
        out, _, calls = self._capture({"frame": 86424},
                                      marks={"video": {"in": 86410}})
        self.assertIsInstance(out, Image)
        self.assertTrue(_restored_range(calls)["SelectAllFrames"])
        self.assertEqual(_restored_range(calls)["MarkIn"], 86400)

    def test_an_unreadable_mark_range_does_not_break_the_capture(self):
        out, _, calls = self._capture({"frame": 86424}, marks="not a dict")
        self.assertIsInstance(out, Image)
        self.assertTrue(_restored_range(calls)["SelectAllFrames"])

    def test_refuses_while_another_render_runs(self):
        out, _, _ = self._capture({}, rendering=True)
        self.assertEqual(out["error"]["code"], "RENDER_BUSY")

    def test_failed_render_is_reported(self):
        out, _, _ = self._capture({}, status="Failed")
        self.assertEqual(out["error"]["code"], "RENDER_FAILED")

    def test_localized_complete_status_is_not_a_failure(self):
        # Issue #191: JobStatus follows the UI language ("Concluso" on an
        # Italian install), so the English literal must not decide success —
        # the job's numeric completion and the written file do.
        out, _, _ = self._capture({}, status={
            "JobStatus": "Concluso", "CompletionPercentage": 100,
            "TimeTakenToRenderInMs": 1225,
        })
        self.assertFalse(isinstance(out, dict) and out.get("error"), out)

    def test_localized_failed_status_is_still_a_failure(self):
        out, _, _ = self._capture({}, status={
            "JobStatus": "Fallito", "CompletionPercentage": 37,
            "Error": "Media a piena risoluzione non trovato",
        })
        self.assertEqual(out["error"]["code"], "RENDER_FAILED")
        self.assertIn("Media a piena risoluzione", json.dumps(out, default=str))

    def test_localized_status_short_of_100_percent_is_a_failure(self):
        # No Error field and no recognisable word: the percentage decides.
        out, _, _ = self._capture({}, status={"JobStatus": "Annullato", "CompletionPercentage": 62})
        self.assertEqual(out["error"]["code"], "RENDER_FAILED")

    def test_success_without_a_file_is_reported(self):
        out, _, _ = self._capture({}, write=False)
        self.assertEqual(out["error"]["code"], "RENDER_FAILED")

    def test_max_width_without_ffmpeg_is_refused(self):
        out, _, _ = self._capture({"max_width": 640}, ffmpeg=None)
        self.assertEqual(out["error"]["code"], "FFMPEG_REQUIRED")

    def test_preview_alias_bounds_the_width(self):
        # 'preview' from the issue's schema means a fast downscaled frame, not
        # the clip thumbnail — it must still render, just bounded.
        out, proj, _ = self._capture({"quality": "preview"})
        self.assertIsInstance(out, Image)
        proj.StartRendering.assert_called_once()
        self.assertEqual(out.data, b"\xff\xd8scaled")

    def test_full_alias_maps_to_the_render_route(self):
        out, proj, _ = self._capture({"quality": "full"})
        self.assertIsInstance(out, Image)
        proj.StartRendering.assert_called_once()


class CaptureRenderPageRestoreTest(_RenderCapture, unittest.TestCase):
    """Issue #270: a capture from the Edit page left Resolve on Deliver.

    Reported on Studio 21.1.0.17 and reproduced on 19.1.3.7, where the cause
    was measured: the page was read after GetCurrentRenderMode(), which had
    already switched to Deliver, so there was never anything to restore. The
    restore is now also read back, and reported when it does not take.
    """

    def test_page_is_put_back_after_the_render(self):
        # The regression itself. GetCurrentRenderMode switches to Deliver, so a
        # page read after it says 'deliver' and the restore is skipped as
        # "nothing to restore". The page has to be read first.
        resolve = _FakeResolve(page="edit")
        out, proj, _ = self._capture({}, resolve=resolve)
        self.assertIsInstance(out, Image)
        proj.GetCurrentRenderMode.assert_called_once()
        self.assertEqual(resolve.opened, ["edit"])
        self.assertEqual(resolve.page, "edit")

    def test_page_restore_is_retried_until_it_takes(self):
        resolve = _SettlingResolve(page="edit", refusals=page_lock.PAGE_RESTORE_ATTEMPTS - 1)
        out, _, _ = self._capture({}, resolve=resolve)
        # A restore that took on a later attempt is a clean capture: one image.
        self.assertIsInstance(out, Image)
        self.assertEqual(resolve.opened, ["edit"] * page_lock.PAGE_RESTORE_ATTEMPTS)
        self.assertEqual(resolve.page, "edit")

    def test_page_restore_that_never_takes_is_reported_with_the_image(self):
        resolve = _FakeResolve(page="edit", switch_ok=False)
        with self.assertLogs("resolve-mcp.page-lock", level="WARNING") as logs:
            out, _, _ = self._capture({}, resolve=resolve)
        self.assertIsInstance(out, list)
        image, note = out
        self.assertIsInstance(image, Image)
        self.assertEqual(len(note["warnings"]), 1)
        warning = note["warnings"][0]
        self.assertIn("'edit'", warning)
        self.assertIn("'deliver'", warning)
        self.assertIn("open_page", warning)
        self.assertEqual(len(resolve.opened), page_lock.PAGE_RESTORE_ATTEMPTS)
        self.assertIn("could not restore the 'edit' page", logs.output[0])

    def test_page_open_that_returns_true_without_moving_is_a_failure(self):
        # The return is not the evidence; the page read back is.
        resolve = _SettlingResolve(page="edit", lies=True)
        with self.assertLogs("resolve-mcp.page-lock", level="WARNING"):
            out, _, _ = self._capture({}, resolve=resolve)
        self.assertIsInstance(out, list)
        self.assertIn("returned True but Resolve is on 'deliver'", out[1]["warnings"][0])

    def test_page_failure_rides_on_an_error_result_too(self):
        resolve = _FakeResolve(page="edit", switch_ok=False)
        with self.assertLogs("resolve-mcp.page-lock", level="WARNING"):
            out, _, _ = self._capture({}, resolve=resolve, status="Failed")
        self.assertEqual(out["error"]["code"], "RENDER_FAILED")
        self.assertIn("'edit'", out["warnings"][0])

    def test_page_is_restored_even_when_the_capture_is_refused_early(self):
        # The mode getter has already moved the page by the time the mode
        # switch is refused; an error return must not strand the user either.
        resolve = _FakeResolve(page="fairlight")
        out, _, _ = self._capture({}, resolve=resolve, mode=0, mode_switch=False)
        self.assertEqual(out["error"]["code"], "RENDER_MODE_REFUSED")
        self.assertEqual(resolve.page, "fairlight")

    def test_page_is_left_alone_when_the_caller_was_on_deliver(self):
        resolve = _FakeResolve(page="deliver")
        out, _, _ = self._capture({}, resolve=resolve)
        self.assertIsInstance(out, Image)
        self.assertEqual(resolve.opened, [])

    def test_page_is_not_switched_when_the_render_never_left_it(self):
        # Refused before any job: Resolve is still where the caller left it.
        resolve = _FakeResolve(page="edit")
        out, _, _ = self._capture({}, resolve=resolve, rendering=True)
        self.assertEqual(out["error"]["code"], "RENDER_BUSY")
        self.assertEqual(resolve.opened, [])
        self.assertNotIn("warnings", out)

    def test_page_warning_reaches_the_client_as_a_block_after_the_image(self):
        resolve = _FakeResolve(page="edit", switch_ok=False)
        with self.assertLogs("resolve-mcp.page-lock", level="WARNING"):
            out, _, _ = self._capture({}, resolve=resolve)
        with mock.patch.object(s, "_playhead_frame_capture", return_value=out):
            sent = asyncio.run(s.mcp.call_tool("timeline_frame", {"action": "capture"}))
        blocks = sent[0] if isinstance(sent, tuple) else sent
        self.assertEqual([b.type for b in blocks], ["image", "text"])
        self.assertIn("open_page", json.loads(blocks[1].text)["warnings"][0])


class CaptureOutputSettingsTest(_RenderCapture, unittest.TestCase):
    """The project's output folder and file name survive a capture.

    Until v4.8.24 the capture wrote TargetDir and CustomName and put neither
    back: there is no GetRenderSettings, and an empty CustomName is refused. So
    the user's next render job inherited a temporary folder (already deleted)
    and a name like capture-1790784198. Now the folder is read off a throwaway
    render job and written back, and the name is never written at all.
    """

    def test_the_output_folder_is_put_back(self):
        out, proj, _ = self._capture({"frame": 86424})
        self.assertIsInstance(out, Image)
        self.assertEqual(proj.render_state["TargetDir"], USER_TARGET)

    def test_the_file_name_is_never_written(self):
        out, proj, calls = self._capture({"frame": 86424})
        self.assertIsInstance(out, Image)
        self.assertEqual([c for c in calls if "CustomName" in c], [])
        self.assertEqual(proj.render_state["CustomName"], "userA")

    def test_the_frame_is_found_under_the_projects_own_naming(self):
        # Custom name, or the timeline name when there is none: either way the
        # file is not named by the capture, and it is still the one returned.
        for user_name in ("userA", None):
            with self.subTest(user_name=user_name):
                out, _, _ = self._capture({"frame": 86424}, user_name=user_name)
                self.assertIsInstance(out, Image)
                self.assertEqual(out.data, b"\xff\xd8rendered")

    def test_the_render_goes_to_a_folder_of_the_captures_own(self):
        out, _, calls = self._capture({"frame": 86424})
        self.assertIsInstance(out, Image)
        staging = calls[0]["TargetDir"]
        self.assertEqual(os.path.dirname(staging), self.capture_base)
        self.assertTrue(os.path.basename(staging).startswith(s.STILL_STAGING_PREFIX))
        # ...and nothing of it is left behind, the shared parent included.
        self.assertFalse(os.path.exists(staging))
        self.assertFalse(os.path.exists(self.capture_base))

    def test_a_same_named_file_in_the_shared_folder_is_not_touched(self):
        # The render is named by the project now, so a file of that name can
        # already be sitting in the shared folder. It is neither returned as
        # the frame nor deleted.
        out, _, _ = self._capture({"frame": 86424}, existing=["userA00086424.jpg"])
        self.assertIsInstance(out, Image)
        self.assertEqual(out.data, b"\xff\xd8rendered")
        with open(os.path.join(self.capture_base, "userA00086424.jpg"), "rb") as fh:
            self.assertEqual(fh.read(), b"someone else's file")

    def test_the_folder_is_read_in_single_clip_mode_before_anything_changes(self):
        out, proj, calls = self._capture({"frame": 86424}, mode=0)
        self.assertIsInstance(out, Image)
        order = [c[0] for c in proj.method_calls]
        readback = order.index("AddRenderJob")
        self.assertLess(order.index("SetCurrentRenderMode"), readback)
        self.assertLess(readback, order.index("SetCurrentRenderFormatAndCodec"))
        self.assertLess(readback, order.index("SetRenderSettings"))
        self.assertEqual(proj.render_state["TargetDir"], USER_TARGET)

    def test_a_project_with_no_output_folder_still_captures(self):
        # AddRenderJob returns '' there, so there is nothing to read and
        # nothing to put back. That is not a failed restore.
        out, proj, calls = self._capture({"frame": 86424}, user_target=None)
        self.assertIsInstance(out, Image)
        self.assertEqual([c for c in calls if set(c) == {"TargetDir"}], [])
        self.assertEqual(proj.render_state["jobs"], {})

    def test_an_output_folder_that_is_not_put_back_is_reported(self):
        with mock.patch.object(s.logger, "warning"):
            out, proj, _ = self._capture({"frame": 86424}, target_restore_ok=False)
        self.assertIsInstance(out, list)
        self.assertIsInstance(out[0], Image)
        self.assertEqual(len(out[1]["warnings"]), 1)
        self.assertIn("output folder", out[1]["warnings"][0])
        self.assertIn(USER_TARGET, out[1]["warnings"][0])

    def test_a_readback_job_that_cannot_be_removed_is_reported(self):
        with mock.patch.object(s.logger, "warning"):
            out, proj, _ = self._capture({"frame": 86424}, job_delete_ok=False)
        self.assertIsInstance(out, list)
        self.assertIn("job-1", out[1]["warnings"][0])
        self.assertIn("render queue", out[1]["warnings"][0])

    def test_an_early_refusal_does_not_rewrite_the_output_folder(self):
        # Refused before the capture's settings went in: TargetDir is still the
        # user's, so writing it "back" would be a write with nothing behind it.
        out, proj, calls = self._capture({"frame": 86424}, mode=0, mode_switch=False)
        self.assertEqual(out["error"]["code"], "RENDER_MODE_REFUSED")
        self.assertEqual([c for c in calls if "TargetDir" in c], [])
        self.assertEqual(proj.render_state["TargetDir"], USER_TARGET)


class CaptureTeardownReportTest(_RenderCapture, unittest.TestCase):
    """Every restore the render route already detected as failed is reported."""

    def test_teardown_reports_a_render_mode_that_was_not_put_back(self):
        modes = iter([True, False])  # switch to single clip works, restore does not
        with mock.patch.object(s.logger, "warning"):
            resolve = _FakeResolve(page="color")
            tl = _fake_timeline(resolve)
            tl.GetStartFrame.return_value = 86400
            tl.GetEndFrame.return_value = 86544
            tl.GetMarkInOut.return_value = {}
            proj = mock.Mock()
            proj.IsRenderingInProgress.return_value = False
            proj.GetCurrentRenderMode.return_value = 0
            proj.SetCurrentRenderMode.side_effect = lambda mode: next(modes)
            proj.GetCurrentRenderFormatAndCodec.return_value = {"format": "mov", "codec": "H.264"}
            proj.GetRenderCodecs.return_value = {"JPEG": "YUV420_8"}
            proj.SetCurrentRenderFormatAndCodec.return_value = True
            proj.SetRenderSettings.return_value = False  # refused: an error result
            teardown = []
            out = s._playhead_frame_render(proj, tl, {"frame": 86424}, teardown)
        self.assertEqual(out["error"]["code"], "RENDER_SETTINGS_REFUSED")
        self.assertEqual(len(teardown), 1)
        self.assertIn("render mode", teardown[0])

    def test_teardown_reports_a_playhead_that_was_not_put_back(self):
        resolve = _FakeResolve(page="color")
        tl = _fake_timeline(resolve)
        tl.GetStartFrame.return_value = 86400
        tl.GetEndFrame.return_value = 86544
        tl.GetMarkInOut.return_value = {}
        tl.SetCurrentTimecode.side_effect = lambda tc: False
        proj = mock.Mock()
        proj.IsRenderingInProgress.return_value = False
        proj.GetCurrentRenderMode.return_value = 1
        proj.GetCurrentRenderFormatAndCodec.return_value = {"format": "mov", "codec": "H.264"}
        proj.GetRenderCodecs.return_value = {"JPEG": "YUV420_8"}
        proj.SetCurrentRenderFormatAndCodec.return_value = True
        proj.SetRenderSettings.return_value = False
        teardown = []
        with mock.patch.object(s, "get_resolve", return_value=resolve), \
             mock.patch.object(s.logger, "warning"):
            s._playhead_frame_render(proj, tl, {"frame": 86424}, teardown)
        self.assertEqual(len(teardown), 1)
        self.assertIn("playhead", teardown[0])
        self.assertIn("01:00:00:00", teardown[0])

    def test_teardown_reports_a_render_range_that_was_not_put_back(self):
        with mock.patch.object(s.logger, "warning"):
            out, proj, _ = self._capture({"frame": 86424}, range_restore_ok=False)
        self.assertIsInstance(out, list)
        self.assertIsInstance(out[0], Image)
        self.assertIn("render range", out[1]["warnings"][0])
        self.assertIn("86424", out[1]["warnings"][0])
        self.assertEqual(proj.render_state["range"], (False, 86424, 86424))

    def test_teardown_is_empty_for_a_clean_capture(self):
        out, _, _ = self._capture({})
        self.assertIsInstance(out, Image)


class ToolSurfaceTest(unittest.TestCase):
    def test_unknown_action_lists_valid_actions(self):
        out = s.timeline_frame("screenshot")
        self.assertIn("capture", out["error"]["message"])

    def test_capabilities_reports_modes_without_a_timeline(self):
        with mock.patch.object(s, "get_resolve", return_value=_FakeResolve(page="edit")), \
             mock.patch.object(s, "_get_tl", return_value=(None, None, {"error": "no timeline"})):
            out = s.timeline_frame("capabilities")
        self.assertEqual(out["default_quality"], "frame")
        self.assertEqual(out["current_page"], "edit")
        self.assertIsNone(out["timeline"])

    def test_capabilities_says_which_render_settings_come_back(self):
        # The docstring has long advertised this key; issue #270 asked that the
        # TargetDir/CustomName reset be readable without opening the source.
        with mock.patch.object(s, "get_resolve", return_value=_FakeResolve(page="edit")), \
             mock.patch.object(s, "_get_tl", return_value=(None, None, {"error": "no timeline"})):
            out = s.timeline_frame("capabilities")
        restorable = out["render_settings_restorable"]
        self.assertEqual(set(restorable.values()), {True})
        self.assertEqual(
            set(restorable),
            {"render_mode", "format_codec", "mark_range", "TargetDir", "CustomName"},
        )
        self.assertIn("never had a render TargetDir", out["render_settings_caveat"])

    def test_legacy_get_thumbnail_image_still_returns_an_image(self):
        resolve = _FakeResolve(page="edit")
        tl = _fake_timeline(resolve)
        with mock.patch.object(s, "get_resolve", return_value=resolve), \
             mock.patch.object(s, "_get_tl", return_value=(mock.Mock(), tl, None)):
            out = s.timeline_markers("get_thumbnail_image")
        self.assertIsInstance(out, Image)

    def test_legacy_get_thumbnail_switches_to_color_page(self):
        # The raw-data variant had the same silent-None-off-Color bug.
        resolve = _FakeResolve(page="edit")
        tl = _fake_timeline(resolve)
        with mock.patch.object(s, "get_resolve", return_value=resolve), \
             mock.patch.object(s, "_get_tl", return_value=(mock.Mock(), tl, None)):
            out = s.timeline_markers("get_thumbnail")
        self.assertEqual(resolve.opened, ["color", "edit"])
        self.assertNotEqual(out.get("success"), False)


if __name__ == "__main__":
    unittest.main()
