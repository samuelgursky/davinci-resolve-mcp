"""timeline_frame — capture what Resolve renders at the playhead, as an image.

Covers the four things the tool promises beyond the old
timeline_markers(action="get_thumbnail_image"): a timecode/frame target, the
Color-page switch, max_width, and a named timeline — plus the invariant that a
capture is a *read*: page, playhead, current timeline, gallery, and the temp
directory all come back the way the caller left them.
"""
import base64
import unittest
from unittest import mock

from mcp.server.fastmcp import Image

import src.server as s


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
        proj.SetCurrentTimeline.return_value = True
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
            out = s.timeline_frame("capture", {"quality": "full", **params})
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


class ToolSurfaceTest(unittest.TestCase):
    def test_unknown_action_lists_valid_actions(self):
        out = s.timeline_frame("screenshot")
        self.assertIn("capture", out["error"]["message"])

    def test_capabilities_reports_modes_without_a_timeline(self):
        with mock.patch.object(s, "get_resolve", return_value=_FakeResolve(page="edit")), \
             mock.patch.object(s, "_get_tl", return_value=(None, None, {"error": "no timeline"})):
            out = s.timeline_frame("capabilities")
        self.assertEqual(out["quality_modes"], ["preview", "full"])
        self.assertEqual(out["current_page"], "edit")
        self.assertIsNone(out["timeline"])

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
