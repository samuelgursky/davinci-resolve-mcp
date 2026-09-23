"""include_*="false" must switch the section off at the twin sites of #268.

#268 fixed the media-pool copy (_copy_clip_annotations). The timeline copy/move
(_copy_annotations) read include_flags and include_clip_color with the same bare
truthiness, and the conform snapshot wrapped its include_* reads in bool(), which
turns "false" into True just the same.
"""
import unittest
from unittest import mock

from src import server as s

FALSE_SPELLINGS = ("false", "False", "no", "0", "off")


class AnnotatedItem:
    def __init__(self, markers=None, flags=None, color=""):
        self.markers = dict(markers or {})
        self.flags = list(flags or [])
        self.color = color
        self.set_color_calls = []

    def GetMarkers(self):
        return dict(self.markers)

    def AddMarker(self, frame, color, name, note, duration, custom_data=""):
        self.markers[frame] = {"color": color, "name": name, "note": note,
                               "duration": duration, "customData": custom_data}
        return True

    def GetFlagList(self):
        return list(self.flags)

    def AddFlag(self, flag):
        self.flags.append(flag)
        return True

    def GetClipColor(self):
        return self.color

    def SetClipColor(self, color):
        self.set_color_calls.append(color)
        self.color = color
        return True


def _copy(params):
    source = AnnotatedItem(
        markers={10: {"color": "Blue", "name": "m", "note": "", "duration": 1, "customData": ""}},
        flags=["Red"], color="Orange",
    )
    target = AnnotatedItem()
    targets = iter([(source, None), (target, None)])
    with mock.patch.object(s, "_annotation_target", lambda *a, **k: next(targets)):
        result = s._copy_annotations(object(), params)
    return result, target


class CopyAnnotationsIncludeFlagsTest(unittest.TestCase):
    def test_include_flags_false_spellings_skip_flags(self):
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                result, target = _copy({"include_flags": spelling})
                self.assertTrue(result.get("success"), result)
                self.assertEqual(target.flags, [])

    def test_include_clip_color_false_spellings_skip_color(self):
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                result, target = _copy({"include_clip_color": spelling})
                self.assertTrue(result.get("success"), result)
                self.assertEqual(target.set_color_calls, [])

    def test_omitted_flags_still_copy_everything(self):
        result, target = _copy({})
        self.assertTrue(result.get("success"), result)
        self.assertEqual(target.flags, ["Red"])
        self.assertEqual(target.set_color_calls, ["Orange"])


class EmptyTimeline:
    def GetTrackCount(self, track_type):
        return 0

    def GetMarkers(self):
        return {5: {"color": "Blue", "name": "m"}}

    def GetName(self):
        return "TL"

    def GetUniqueId(self):
        return "tl-1"

    def GetStartFrame(self):
        return 0

    def GetEndFrame(self):
        return 100

    def GetStartTimecode(self):
        return "01:00:00:00"


class ConformSnapshotIncludeMarkersTest(unittest.TestCase):
    def test_include_markers_false_spellings_omit_markers(self):
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                snap = s._timeline_conform_snapshot(EmptyTimeline(), {"include_markers": spelling})
                self.assertEqual(snap["markers"], {})

    def test_include_markers_default_reads_markers(self):
        snap = s._timeline_conform_snapshot(EmptyTimeline(), {})
        self.assertTrue(snap["markers"])


if __name__ == "__main__":
    unittest.main()
