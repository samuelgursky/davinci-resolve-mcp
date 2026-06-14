import unittest

import src.server as compound
from tests._error_envelope_helpers import err_message


def _strip_versioning(d):
    """Return a copy of a result dict with the destructive_hook _versioning key removed."""
    if not isinstance(d, dict):
        return d
    return {k: v for k, v in d.items() if k != "_versioning"}


class TimelineStub:
    """Hour-start timeline by default (start TC 01:00:00:00 @ 24fps -> frame 86400).

    Timeline.AddMarker frameIds are RELATIVE to the timeline start (frame 0 ==
    first frame), while GetCurrentTimecode/SetCurrentTimecode use absolute
    timecode as displayed in the Resolve UI. Verified visually on Resolve
    Studio 21 (2026-06-11); GetMarkers() echoes back whatever frameId was
    passed, so only display-position conventions like these stubs encode can
    catch absolute/relative mixups.
    """

    def __init__(self, fps="24", current_timecode="01:00:00:12", start_frame=86400):
        self.fps = fps
        self.current_timecode = current_timecode
        self.start_frame = start_frame
        self.add_calls = []
        self.deleted_frames = []
        self.update_custom_data_calls = []

    def GetSetting(self, name):
        if name == "timelineFrameRate":
            return self.fps
        return None

    def GetCurrentTimecode(self):
        return self.current_timecode

    def GetStartFrame(self):
        if self.start_frame is None:
            raise RuntimeError("GetStartFrame unavailable")
        return self.start_frame

    def AddMarker(self, *args):
        self.add_calls.append(args)
        return True

    def GetMarkers(self):
        return {}

    def DeleteMarkerAtFrame(self, frame):
        self.deleted_frames.append(frame)
        return True

    def UpdateMarkerCustomData(self, frame, data):
        self.update_custom_data_calls.append((frame, data))
        return True

    def GetCurrentClipThumbnailImage(self):
        return None


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
        self.original_is_destructive = compound._destructive_hook.is_destructive
        self.timeline = TimelineStub()
        compound._get_tl = lambda: (None, self.timeline, None)
        compound._destructive_hook.is_destructive = lambda *args, **kwargs: False

    def tearDown(self):
        compound._get_tl = self.original_get_tl
        compound._destructive_hook.is_destructive = self.original_is_destructive

    def test_add_accepts_frame_id_alias_and_defaults_name_duration(self):
        # Raw frame params are already relative to the timeline start and must
        # not be reinterpreted, even on an hour-start timeline.
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

    def test_add_defaults_to_current_playhead_relative_to_start(self):
        # Playhead TC 01:00:00:12 on an hour-start timeline is marker frame 12.
        out = compound.timeline_markers("add", {"color": "green"})

        self.assertEqual(_strip_versioning(out), {"success": True, "frame": 12})
        self.assertEqual(
            self.timeline.add_calls[-1],
            (12, "Green", "Marker", "", 1, ""),
        )

    def test_add_accepts_timecode_with_nominal_ntsc_rate(self):
        # 01:00:10:00 @ 23.976 (nominal 24) is 86640 absolute -> 240 relative.
        self.timeline.fps = "23.976"

        out = compound.timeline_markers(
            "add",
            {"timecode": "01:00:10:00", "color": "red", "name": "TC"},
        )

        self.assertEqual(_strip_versioning(out), {"success": True, "frame": 240})
        self.assertEqual(
            self.timeline.add_calls[-1],
            (240, "Red", "TC", "", 1, ""),
        )

    def test_add_timecode_below_start_treated_as_elapsed(self):
        # A timecode before the timeline start timecode cannot be absolute;
        # treat it as elapsed time from the first frame.
        out = compound.timeline_markers(
            "add",
            {"timecode": "00:00:10:00", "color": "red", "name": "Elapsed"},
        )

        self.assertEqual(_strip_versioning(out), {"success": True, "frame": 240})

    def test_add_timecode_on_zero_start_timeline(self):
        self.timeline.start_frame = 0

        out = compound.timeline_markers(
            "add",
            {"timecode": "00:00:10:00", "color": "red", "name": "ZeroStart"},
        )

        self.assertEqual(_strip_versioning(out), {"success": True, "frame": 240})

    def test_add_playhead_without_start_frame_keeps_absolute(self):
        # If GetStartFrame is unavailable the conversion cannot be rebased;
        # fall back to the unrebased frame instead of erroring.
        self.timeline.start_frame = None

        out = compound.timeline_markers("add", {"color": "green"})

        self.assertEqual(_strip_versioning(out), {"success": True, "frame": 86412})

    def test_delete_at_frame_accepts_frame_id_alias(self):
        out = compound.timeline_markers("delete_at_frame", {"frameId": 123})

        self.assertEqual(_strip_versioning(out), {"success": True})
        self.assertEqual(self.timeline.deleted_frames, [123])

    def test_delete_at_frame_accepts_timecode_relative_to_start(self):
        # Stored marker keys are relative, so timecode lookups must rebase to
        # match the stored key.
        out = compound.timeline_markers("delete_at_frame", {"timecode": "01:00:00:12"})

        self.assertEqual(_strip_versioning(out), {"success": True})
        self.assertEqual(self.timeline.deleted_frames, [12])

    def test_update_custom_data_accepts_timecode_relative_to_start(self):
        out = compound.timeline_markers(
            "update_custom_data",
            {"timecode": "01:00:00:12", "customData": "marker-2"},
        )

        self.assertEqual(_strip_versioning(out), {"success": True})
        self.assertEqual(self.timeline.update_custom_data_calls, [(12, "marker-2")])

    def test_current_timeline_frame_id_stays_absolute(self):
        # Non-marker callers (duplicate-clip record frames) need the absolute
        # frame that matches TimelineItem.GetStart().
        frame, err = compound._current_timeline_frame_id(self.timeline)

        self.assertIsNone(err)
        self.assertEqual(frame, 86412)

    def test_marker_display_frame_rebases_stored_markers_to_absolute(self):
        # Contact sheets drive SetCurrentTimecode (absolute), so stored
        # relative marker frames must be rebased the other way.
        self.assertEqual(compound._marker_display_frame(self.timeline, 12), 86412)
        # Legacy markers stored at absolute frames still sample the intended
        # spot instead of pointing past the end of the timeline.
        self.assertEqual(compound._marker_display_frame(self.timeline, 86412), 86412)
        self.timeline.start_frame = 0
        self.assertEqual(compound._marker_display_frame(self.timeline, 12), 12)

    def test_invalid_timecode_returns_error(self):
        out = compound.timeline_markers("add", {"timecode": "01:00:00"})

        self.assertEqual(err_message(out), "timecode must use HH:MM:SS:FF format")

    def test_get_thumbnail_returns_error_dict_when_resolve_returns_nil(self):
        out = compound.timeline_markers("get_thumbnail")

        self.assertEqual(out["success"], False)
        self.assertIsNone(out["thumbnail"])
        self.assertIn("did not return a thumbnail", out["error"])

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
