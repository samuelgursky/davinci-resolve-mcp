"""thumbnail_contact_sheet must switch to the Color page and restore after.

GetCurrentClipThumbnailImage silently returns None on every page except Color,
so without the switch the tool reported "No thumbnail available at frame" for
every frame while on the Edit page.
"""
import tempfile
import unittest
from unittest import mock

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


def _run(resolve):
    tl = mock.Mock()
    tl.GetName.return_value = "TL"
    tl.GetCurrentTimecode.return_value = "01:00:00:00"
    # Thumbnails exist only while Resolve is on the Color page.
    tl.GetCurrentClipThumbnailImage.side_effect = lambda: (
        {"width": 2, "height": 2, "format": "RGB 8 bit", "data": "AAAA"}
        if resolve.page == "color" else None
    )
    proj = mock.Mock()
    root = {"success": True, "project_root": tempfile.mkdtemp(prefix="sheet_")}
    with mock.patch.object(s, "get_resolve", return_value=resolve), \
         mock.patch.object(s, "resolve_media_analysis_output_root", return_value=root), \
         mock.patch.object(s, "_timeline_frame_id_to_timecode", return_value=("01:00:00:05", None)), \
         mock.patch.object(s, "_marker_display_frame", side_effect=lambda tl, f: f), \
         mock.patch.object(s, "_thumbnail_raw_rgb", return_value=(2, 2, b"\x00" * 12)), \
         mock.patch.object(s, "_contact_sheet_png_bytes", return_value=(10, 10, b"png")):
        return s._timeline_thumbnail_contact_sheet(proj, tl, {"frames": [100]})


class ContactSheetPageSwitchTest(unittest.TestCase):
    def test_switches_to_color_and_restores_previous_page(self):
        resolve = _FakeResolve(page="edit")
        out = _run(resolve)
        self.assertTrue(out.get("success"), out)
        self.assertEqual(resolve.opened, ["color", "edit"])
        self.assertEqual(resolve.page, "edit")

    def test_already_on_color_leaves_page_alone(self):
        resolve = _FakeResolve(page="color")
        out = _run(resolve)
        self.assertTrue(out.get("success"), out)
        self.assertEqual(resolve.opened, [])

    def test_failed_switch_reports_color_page_requirement(self):
        resolve = _FakeResolve(page="edit", switch_ok=False)
        out = _run(resolve)
        self.assertFalse(out.get("success"))
        self.assertIn("Color page", out["samples"][0]["error"])


if __name__ == "__main__":
    unittest.main()
