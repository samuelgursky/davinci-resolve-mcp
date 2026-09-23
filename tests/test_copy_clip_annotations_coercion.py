"""include_markers/flags/clip_color="false" must suppress the copy.

_copy_clip_annotations read include_markers, include_flags, and
include_clip_color with bare p.get(): a string "false", "no", "0", or "off"
is truthy in Python, so a caller explicitly opting out of an annotation
type still had it copied.  Each read should go through _coerce_bool, like
the dry_run read in the same function already does.
"""
import unittest

from src.server import _copy_clip_annotations
from tests.test_media_pool_ingest_probe import FolderStub, MediaPoolItemStub

FALSE_SPELLINGS = ("false", "False", "no", "0", "off")


class TrackingClip(MediaPoolItemStub):
    """Subclass that records SetClipColor calls so tests can inspect them."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_color_calls = []

    def SetClipColor(self, color):
        self.set_color_calls.append(color)
        return True


def _tree():
    source = MediaPoolItemStub(unique_id="src-1", name="source.mov")
    target = TrackingClip(unique_id="tgt-1", name="target.mov")
    target.flags = []
    target.markers = {}
    root = FolderStub(clips=[source, target])
    return root, source, target


class CopyClipAnnotationsCoercionTest(unittest.TestCase):
    """include_*="false" must suppress each annotation type."""

    def test_include_flags_false_suppresses_flag_copy(self):
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                root, _src, tgt = _tree()
                result = _copy_clip_annotations(root, {
                    "source_clip_id": "src-1",
                    "target_clip_ids": ["tgt-1"],
                    "include_flags": spelling,
                })
                self.assertTrue(result.get("success"), result)
                self.assertEqual(tgt.flags, [],
                    f"include_flags={spelling!r} should suppress flag copy but flags were added")

    def test_include_markers_false_suppresses_marker_copy(self):
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                root, _src, tgt = _tree()
                result = _copy_clip_annotations(root, {
                    "source_clip_id": "src-1",
                    "target_clip_ids": ["tgt-1"],
                    "include_markers": spelling,
                })
                self.assertTrue(result.get("success"), result)
                self.assertEqual(tgt.markers, {},
                    f"include_markers={spelling!r} should suppress marker copy but markers were added")

    def test_include_clip_color_false_suppresses_color_copy(self):
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                root, _src, tgt = _tree()
                result = _copy_clip_annotations(root, {
                    "source_clip_id": "src-1",
                    "target_clip_ids": ["tgt-1"],
                    "include_clip_color": spelling,
                })
                self.assertTrue(result.get("success"), result)
                self.assertEqual(tgt.set_color_calls, [],
                    f"include_clip_color={spelling!r} should suppress color copy but SetClipColor was called")

    def test_true_spelling_still_copies_all(self):
        """Positive-path sanity: omitting the flags copies everything."""
        root, _src, tgt = _tree()
        result = _copy_clip_annotations(root, {
            "source_clip_id": "src-1",
            "target_clip_ids": ["tgt-1"],
        })
        self.assertTrue(result.get("success"), result)
        self.assertNotEqual(tgt.flags, [], "flags should have been copied")
        self.assertNotEqual(tgt.markers, {}, "markers should have been copied")
