"""`grab_and_export` must delete only what `grab_and_export` produced.

Reported in #151: the cleanup step did not remove the exported files, it removed
the *difference* between a listing of the caller's folder taken before the export
and one taken after. Anything that appeared in that window — a background render,
a copy, a cloud sync, a second `grab_and_export` — was attributed to the call,
inlined into the response, and deleted. It then finished with
`os.rmdir(folder_path)`, removing a directory the caller had chosen and the
server had not created.

`_resolve_safe_dir` makes the overlap concrete rather than theoretical: every
sandbox/temp path is redirected to one shared `~/Documents/resolve-stills`, so
two concurrent calls pointed at different temp folders land in the same place.

These tests run the real action against a real temp filesystem, with a fake
album whose `ExportStills` writes files the way Resolve does — because the defect
was in what the filesystem ended up looking like, not in any return value.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import src.server as server  # noqa: E402


class _Album:
    """Resolve's still album, as far as this action is concerned.

    `ExportStills` writes an image plus the companion .drx, and — this is the
    point of the fixture — a `bystander` hook lets a test drop a file into the
    caller's folder *during* the export, which is exactly when a background
    render or a sync would.
    """

    def __init__(self, bystander=None):
        self.bystander = bystander
        self.deleted = []

    def ExportStills(self, stills, folder, prefix, fmt):
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, f"{prefix}_1.{fmt}"), "wb") as fh:
            fh.write(b"\x00image-bytes")
        with open(os.path.join(folder, f"{prefix}_1.drx"), "w", encoding="utf-8") as fh:
            fh.write("<DRX/>")
        if self.bystander:
            self.bystander()
        return True

    def DeleteStills(self, stills):
        self.deleted.extend(stills)
        return True


class _Gallery:
    def __init__(self, album):
        self._album = album

    def GetCurrentStillAlbum(self):
        return self._album

    def GetGalleryStillAlbums(self):
        return [self._album]


class GrabAndExportCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = os.path.join(self.tmp.name, "stills")

    def _run(self, params, bystander=None):
        album = _Album(bystander=bystander)
        project = mock.Mock()
        project.GetGallery.return_value = _Gallery(album)
        timeline = mock.Mock()
        timeline.GrabStill.return_value = mock.Mock(name="GalleryStill")
        with mock.patch.object(server, "_check", return_value=(mock.Mock(), project, None)), \
                mock.patch.object(server, "_get_tl", return_value=(project, timeline, None)), \
                mock.patch.object(server, "_resolve_safe_dir", side_effect=lambda path: path), \
                mock.patch.object(server.time, "sleep", lambda *_: None):
            result = server.gallery_stills(action="grab_and_export", params=params)
        return result, album

    def test_a_file_written_during_the_export_is_not_swept_up(self) -> None:
        """The report, reproduced: a bystander file must survive, and must not
        come back inlined in the response either — deleting a stranger's file is
        the worse half, but reading it into an assistant's context is the other
        half of the same mistake."""
        os.makedirs(self.folder)
        bystander = os.path.join(self.folder, "render_00042.exr")

        def write_bystander():
            with open(bystander, "wb") as fh:
                fh.write(b"someone else's render")

        result, _ = self._run({"folder_path": self.folder, "format": "jpg"},
                              bystander=write_bystander)

        self.assertNotIn("error", result, result)
        self.assertTrue(os.path.exists(bystander), "a file written during the export was deleted")
        with open(bystander, "rb") as fh:
            self.assertEqual(fh.read(), b"someone else's render")
        names = {f["name"] for f in result["files"]}
        self.assertEqual(names, {"still_1.jpg", "still_1.drx"})
        blobs = " ".join(str(f.get("data", "")) + str(f.get("data_base64", "")) for f in result["files"])
        self.assertNotIn("c29tZW9uZSBlbHNl", blobs, "bystander bytes were inlined into the response")

    def test_a_folder_the_caller_already_had_is_not_removed(self) -> None:
        """`os.rmdir(folder_path)` ran whenever the folder ended up empty. The
        caller chose that folder; this server did not create it."""
        os.makedirs(self.folder)
        result, _ = self._run({"folder_path": self.folder})
        self.assertNotIn("error", result, result)
        self.assertTrue(os.path.isdir(self.folder), "a pre-existing folder was removed")
        self.assertEqual(os.listdir(self.folder), [], "cleanup left the exported files behind")

    def test_a_folder_this_call_created_is_still_cleaned_up(self) -> None:
        """The no-litter half of the old behaviour is kept, narrowed to the case
        where there was nothing to lose."""
        self.assertFalse(os.path.exists(self.folder))
        result, _ = self._run({"folder_path": self.folder})
        self.assertNotIn("error", result, result)
        self.assertFalse(os.path.exists(self.folder))

    def test_cleanup_false_leaves_the_files_in_the_caller_s_folder(self) -> None:
        os.makedirs(self.folder)
        result, _ = self._run({"folder_path": self.folder, "format": "jpg", "cleanup": False})
        self.assertNotIn("error", result, result)
        self.assertEqual(sorted(os.listdir(self.folder)), ["still_1.drx", "still_1.jpg"])
        for entry in result["files"]:
            self.assertEqual(os.path.dirname(entry["path"]), self.folder)
            self.assertTrue(os.path.exists(entry["path"]))

    def test_cleanup_false_does_not_overwrite_a_file_already_there(self) -> None:
        """Resolve numbers stills per export, so a second call collides with the
        first. Overwriting would destroy the earlier export."""
        os.makedirs(self.folder)
        keep = os.path.join(self.folder, "still_1.jpg")
        with open(keep, "wb") as fh:
            fh.write(b"the earlier export")
        result, _ = self._run({"folder_path": self.folder, "format": "jpg", "cleanup": False})
        self.assertNotIn("error", result, result)
        with open(keep, "rb") as fh:
            self.assertEqual(fh.read(), b"the earlier export")
        self.assertIn("still_1_1.jpg", os.listdir(self.folder))

    def test_no_staging_directory_survives_the_call(self) -> None:
        for params in ({"folder_path": self.folder, "cleanup": False},
                       {"folder_path": self.folder, "cleanup": True}):
            with self.subTest(cleanup=params["cleanup"]):
                os.makedirs(self.folder, exist_ok=True)
                self._run(params)
                leftovers = [n for n in os.listdir(self.folder)
                             if n.startswith(server.STILL_STAGING_PREFIX)] if os.path.isdir(self.folder) else []
                self.assertEqual(leftovers, [])

    def test_a_failed_export_leaves_the_folder_as_it_found_it(self) -> None:
        """The early returns are the easy place to leak a staging directory."""
        os.makedirs(self.folder)
        album = _Album()
        album.ExportStills = lambda *a, **k: False
        project = mock.Mock()
        project.GetGallery.return_value = _Gallery(album)
        timeline = mock.Mock()
        timeline.GrabStill.return_value = mock.Mock()
        with mock.patch.object(server, "_check", return_value=(mock.Mock(), project, None)), \
                mock.patch.object(server, "_get_tl", return_value=(project, timeline, None)), \
                mock.patch.object(server, "_resolve_safe_dir", side_effect=lambda path: path), \
                mock.patch.object(server.time, "sleep", lambda *_: None):
            result = server.gallery_stills(action="grab_and_export", params={"folder_path": self.folder})
        self.assertIn("error", result)
        self.assertEqual(os.listdir(self.folder), [])

    def test_a_grab_failure_leaves_no_staging_directory(self) -> None:
        os.makedirs(self.folder)
        album = _Album()
        project = mock.Mock()
        project.GetGallery.return_value = _Gallery(album)
        timeline = mock.Mock()
        timeline.GrabStill.return_value = None
        with mock.patch.object(server, "_check", return_value=(mock.Mock(), project, None)), \
                mock.patch.object(server, "_get_tl", return_value=(project, timeline, None)), \
                mock.patch.object(server, "_resolve_safe_dir", side_effect=lambda path: path), \
                mock.patch.object(server.time, "sleep", lambda *_: None):
            result = server.gallery_stills(action="grab_and_export", params={"folder_path": self.folder})
        self.assertIn("error", result)
        self.assertEqual(os.listdir(self.folder), [])


class DiscardStagingTests(unittest.TestCase):
    """The one helper allowed to delete refuses anything it did not name."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_a_directory_that_is_not_ours_is_left_alone(self) -> None:
        for name in ("Documents", "resolve-stills", "", "resolve-mcp-stills"):
            with self.subTest(name=name):
                target = os.path.join(self.tmp.name, name) if name else self.tmp.name
                os.makedirs(target, exist_ok=True)
                server._discard_still_staging(target)
                self.assertTrue(os.path.isdir(target))

    def test_our_own_staging_directory_goes_with_its_contents(self) -> None:
        staging = os.path.join(self.tmp.name, server.STILL_STAGING_PREFIX + "abc123")
        os.makedirs(staging)
        with open(os.path.join(staging, "still_1.dpx"), "wb") as fh:
            fh.write(b"x")
        server._discard_still_staging(staging)
        self.assertFalse(os.path.exists(staging))


if __name__ == "__main__":
    unittest.main()
