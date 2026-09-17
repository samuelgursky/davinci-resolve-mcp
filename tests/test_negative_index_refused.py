"""A negative index must be refused, not read from the end of the list.

EX5 (3a48d00) taught the compound `_get_item` that `items[-1]` is the LAST clip,
so an item_index of -1 acted on a clip nobody named. Its granular twin
`_get_timeline_item`, which 85 granular tools go through, kept the old
`item_index >= len(items)` check, and so did every album/still lookup in both
gallery surfaces. `delete_stills` was the sharpest case: `still_indices=[-1]`
deleted the album's last still, and an out-of-range index was dropped silently
while the rest were deleted.

Offline: fake Resolve objects, no live Resolve needed.
"""

from __future__ import annotations

import inspect
import os
import sys
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import src.server as server  # noqa: E402
import src.granular.common as gcommon  # noqa: E402
import src.granular.gallery as ggallery  # noqa: E402


class _Album:
    def __init__(self, name, stills):
        self.name = name
        self.stills = list(stills)
        self.deleted = []
        self.labels = []

    def GetStills(self):
        return list(self.stills)

    def DeleteStills(self, stills):
        self.deleted.extend(stills)
        return True

    def GetLabel(self, still):
        return f"label:{still}"

    def SetLabel(self, still, label):
        self.labels.append((still, label))
        return True


class _Gallery:
    def __init__(self, albums):
        self.albums = albums
        self.current = None
        self.renamed = []

    def GetGalleryStillAlbums(self):
        return list(self.albums)

    def GetCurrentStillAlbum(self):
        return self.albums[0]

    def SetCurrentStillAlbum(self, album):
        self.current = album
        return True

    def GetAlbumName(self, album=None):
        return album.name if album else ""

    def SetAlbumName(self, album, name):
        self.renamed.append((album, name))
        return True


def _fixture():
    first = _Album("first", ["s0", "s1", "s2"])
    last = _Album("last", ["t0", "t1"])
    gallery = _Gallery([first, last])
    project = mock.Mock()
    project.GetGallery.return_value = gallery
    return gallery, project, first, last


def _undecorated(fn):
    # The granular destructive hook audits and may gate on safe mode; the index
    # check under test lives in the body, so call the body directly.
    return inspect.unwrap(fn)


class CompoundGalleryNegativeIndex(unittest.TestCase):
    def _call(self, tool, action, params):
        gallery, project, first, last = _fixture()
        with mock.patch.object(server, "_check", return_value=(mock.Mock(), project, None)):
            out = _undecorated(tool)(action=action, params=params)
        return out, gallery, first, last

    def test_delete_stills_refuses_a_negative_index(self):
        out, _, first, _ = self._call(server.gallery_stills, "delete_stills",
                                      {"still_indices": [-1]})
        self.assertIn("error", out, out)
        self.assertEqual(first.deleted, [], "a negative index deleted the last still")

    def test_delete_stills_refuses_an_out_of_range_index_instead_of_dropping_it(self):
        out, _, first, _ = self._call(server.gallery_stills, "delete_stills",
                                      {"still_indices": [0, 7]})
        self.assertIn("error", out, out)
        self.assertEqual(first.deleted, [])

    def test_delete_stills_still_deletes_valid_indices(self):
        out, _, first, _ = self._call(server.gallery_stills, "delete_stills",
                                      {"still_indices": [0, 2]})
        self.assertEqual(out, {"success": True})
        self.assertEqual(first.deleted, ["s0", "s2"])

    def test_negative_album_index_is_refused(self):
        out, _, _, last = self._call(server.gallery_stills, "delete_stills",
                                     {"album_index": -1, "still_indices": [0]})
        self.assertIn("error", out, out)
        self.assertEqual(last.deleted, [])

    def test_negative_still_index_is_refused_for_labels(self):
        out, _, first, _ = self._call(server.gallery_stills, "set_label",
                                      {"still_index": -1, "label": "x"})
        self.assertIn("error", out, out)
        self.assertEqual(first.labels, [])
        out, _, _, _ = self._call(server.gallery_stills, "get_label", {"still_index": -1})
        self.assertIn("error", out, out)

    def test_negative_album_index_is_refused_by_gallery(self):
        for action, params in (("get_album_name", {"album_index": -1}),
                               ("set_album_name", {"album_index": -1, "name": "x"}),
                               ("set_current_album", {"album_index": -1})):
            with self.subTest(action=action):
                out, gallery, _, _ = self._call(server.gallery, action, params)
                self.assertIn("error", out, out)
                self.assertEqual(gallery.renamed, [])
                self.assertIsNone(gallery.current)


class GranularGalleryNegativeIndex(unittest.TestCase):
    def _call(self, fn, **kwargs):
        gallery, project, first, last = _fixture()
        resolve = mock.Mock()
        resolve.GetProjectManager.return_value.GetCurrentProject.return_value = project
        with mock.patch.object(ggallery, "get_resolve", return_value=resolve):
            out = _undecorated(fn)(**kwargs)
        return out, gallery, first, last

    def test_delete_stills_from_album_refuses_a_negative_index(self):
        out, _, first, _ = self._call(ggallery.delete_stills_from_album,
                                      album_index=0, still_indices=[-1])
        self.assertIn("error", out, out)
        self.assertEqual(first.deleted, [])

    def test_delete_stills_from_album_refuses_an_out_of_range_index(self):
        out, _, first, _ = self._call(ggallery.delete_stills_from_album,
                                      album_index=0, still_indices=[1, 9])
        self.assertIn("error", out, out)
        self.assertEqual(first.deleted, [])

    def test_delete_stills_from_album_still_deletes_valid_indices(self):
        out, _, first, _ = self._call(ggallery.delete_stills_from_album,
                                      album_index=0, still_indices=[1])
        self.assertEqual(out, {"success": True})
        self.assertEqual(first.deleted, ["s1"])

    def test_negative_album_and_still_indices_are_refused(self):
        cases = (
            (ggallery.delete_stills_from_album, {"album_index": -1, "still_indices": [0]}),
            (ggallery.set_current_still_album, {"album_index": -1}),
            (ggallery.get_album_stills, {"album_index": -1}),
            (ggallery.set_still_label, {"album_index": 0, "still_index": -1, "label": "x"}),
            (ggallery.get_still_label, {"album_index": 0, "still_index": -1}),
        )
        for fn, kwargs in cases:
            with self.subTest(tool=fn.__name__, **kwargs):
                out, gallery, first, last = self._call(fn, **kwargs)
                self.assertIn("error", out, out)
                self.assertEqual(last.deleted, [])
                self.assertEqual(first.labels, [])
                self.assertIsNone(gallery.current)


class GranularTimelineItemNegativeIndex(unittest.TestCase):
    def _lookup(self, item_index):
        timeline = mock.Mock()
        timeline.GetItemListInTrack.return_value = ["clip0", "clip1", "clip2"]
        with mock.patch.object(gcommon, "_get_timeline", return_value=(None, timeline, None)):
            return gcommon._get_timeline_item("video", 1, item_index)

    def test_negative_item_index_is_refused(self):
        for index in (-1, -3):
            with self.subTest(item_index=index):
                item, err = self._lookup(index)
                self.assertIsNone(item, f"item_index={index} resolved to {item!r}")
                self.assertIn("error", err)

    def test_valid_item_index_still_resolves(self):
        self.assertEqual(self._lookup(2), ("clip2", None))


if __name__ == "__main__":
    unittest.main()
