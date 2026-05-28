import unittest

import src.server as compound
from tests._error_envelope_helpers import err_message


def _strip_versioning(d):
    """Return a copy of a result dict with the destructive_hook _versioning key removed."""
    if not isinstance(d, dict):
        return d
    return {k: v for k, v in d.items() if k != "_versioning"}


class TimelineStub:
    def __init__(self, fps="24", current_timecode="01:00:00:12"):
        self.fps = fps
        self.current_timecode = current_timecode
        self.add_calls = []
        self.deleted_frames = []

    def GetSetting(self, name):
        if name == "timelineFrameRate":
            return self.fps
        return None

    def GetCurrentTimecode(self):
        return self.current_timecode

    def AddMarker(self, *args):
        self.add_calls.append(args)
        return True

    def GetMarkers(self):
        return {}

    def DeleteMarkerAtFrame(self, frame):
        self.deleted_frames.append(frame)
        return True


class FiveArgMarkerStub:
    def __init__(self):
        self.add_calls = []

    def AddMarker(self, *args):
        if len(args) == 6:
            raise TypeError("customData overload unavailable")
        self.add_calls.append(args)
        return True


class TimelineMarkerParamTest(unittest.TestCase):
    def setUp(self):
        self.original_get_tl = compound._get_tl
        self.timeline = TimelineStub()
        compound._get_tl = lambda: (None, self.timeline, None)

    def tearDown(self):
        compound._get_tl = self.original_get_tl

    def test_add_accepts_frame_id_alias_and_defaults_name_duration(self):
        out = compound.timeline_markers(
            "add",
            {
                "frame_id": "42",
                "color": "blue",
                "note": "Needs review",
                "customData": "marker-1",
            },
        )

        self.assertEqual(_strip_versioning(out), {"success": True, "frame": 42})
        self.assertEqual(
            self.timeline.add_calls[-1],
            (42, "Blue", "Needs review", "Needs review", 1, "marker-1"),
        )

    def test_add_defaults_to_current_playhead(self):
        out = compound.timeline_markers("add", {"color": "green"})

        self.assertEqual(_strip_versioning(out), {"success": True, "frame": 86412})
        self.assertEqual(
            self.timeline.add_calls[-1],
            (86412, "Green", "Marker", "", 1, ""),
        )

    def test_add_accepts_timecode_with_nominal_ntsc_rate(self):
        self.timeline.fps = "23.976"

        out = compound.timeline_markers(
            "add",
            {"timecode": "01:00:10:00", "color": "red", "name": "TC"},
        )

        self.assertEqual(_strip_versioning(out), {"success": True, "frame": 86640})
        self.assertEqual(
            self.timeline.add_calls[-1],
            (86640, "Red", "TC", "", 1, ""),
        )

    def test_delete_at_frame_accepts_frame_id_alias(self):
        out = compound.timeline_markers("delete_at_frame", {"frameId": 123})

        self.assertEqual(_strip_versioning(out), {"success": True})
        self.assertEqual(self.timeline.deleted_frames, [123])

    def test_invalid_timecode_returns_error(self):
        out = compound.timeline_markers("add", {"timecode": "01:00:00"})

        self.assertEqual(err_message(out), "timecode must use HH:MM:SS:FF format")

    def test_add_marker_falls_back_to_five_arg_overload_when_custom_data_empty(self):
        target = FiveArgMarkerStub()

        out = compound._add_marker(
            target,
            {
                "frame": 12,
                "color": "Blue",
                "name": "Fallback",
                "note": "",
                "duration": 1,
                "custom_data": "",
            },
        )

        self.assertEqual(out, {"success": True, "frame": 12})
        self.assertEqual(target.add_calls, [(12, "Blue", "Fallback", "", 1)])


if __name__ == "__main__":
    unittest.main()
