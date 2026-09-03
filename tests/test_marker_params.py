import unittest

import src.server as compound
from tests._envelope_helpers import domain_payload
from tests._error_envelope_helpers import err_message


def _strip_versioning(d):
    """Return a copy of a result dict with the additive private envelopes removed.

    `_versioning` (destructive hook) and `_operation` (operation envelope) both
    ride alongside the domain payload without shadowing it; these tests are
    about the domain shape.
    """
    return domain_payload(d)


class TimelineStub:
    """Hour-start timeline by default (start TC 01:00:00:00 @ 24fps -> frame 86400).

    Timeline.AddMarker frameIds are RELATIVE to the timeline start (frame 0 ==
    first frame), while GetCurrentTimecode/SetCurrentTimecode use absolute
    timecode as displayed in the Resolve UI. Verified visually on Resolve
    Studio 21 (2026-06-11); GetMarkers() echoes back whatever frameId was
    passed, so only display-position conventions like these stubs encode can
    catch absolute/relative mixups.
    """

    def __init__(
        self,
        fps="24",
        current_timecode="01:00:00:12",
        start_frame=86400,
        start_timecode="01:00:00:00",
    ):
        self.fps = fps
        self.current_timecode = current_timecode
        self.start_frame = start_frame
        self.start_timecode = start_timecode
        self.add_calls = []
        self.deleted_frames = []
        self.update_custom_data_calls = []
        self.set_timecode_calls = []

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

    def GetStartTimecode(self):
        if self.start_timecode is None:
            raise RuntimeError("GetStartTimecode unavailable")
        return self.start_timecode

    def SetCurrentTimecode(self, timecode):
        self.set_timecode_calls.append(timecode)
        return True

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

    def test_add_elapsed_and_absolute_timecode_agree_on_nonzero_start(self):
        # Same non-zero start as the measured set_current_timecode contract
        # (start 00:59:50:00 @ 24 = frame 86160): the elapsed TC 00:00:21:03
        # and the absolute TC 01:00:11:03 both mean relative frame 507.
        self.timeline.start_frame = 86160
        self.timeline.start_timecode = "00:59:50:00"

        out_elapsed = compound.timeline_markers(
            "add", {"timecode": "00:00:21:03", "color": "red"}
        )
        out_absolute = compound.timeline_markers(
            "add", {"timecode": "01:00:11:03", "color": "red"}
        )

        self.assertEqual(_strip_versioning(out_elapsed), {"success": True, "frame": 507})
        self.assertEqual(_strip_versioning(out_absolute), {"success": True, "frame": 507})

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

    def test_set_current_timecode_lifts_elapsed_below_start(self):
        # Measured on Studio 19.1.3.7 (timeline start 00:59:50:00 @ 24):
        # SetCurrentTimecode('00:00:21:03') returns False with no error info,
        # while '01:00:11:03' succeeds — so the documented elapsed-TC
        # conversion must lift sub-start timecodes before calling Resolve.
        self.timeline.start_frame = 86160
        self.timeline.start_timecode = "00:59:50:00"

        out = compound.timeline_markers(
            "set_current_timecode", {"timecode": "00:00:21:03"}
        )

        self.assertEqual(_strip_versioning(out), {"success": True})
        self.assertEqual(self.timeline.set_timecode_calls, ["01:00:11:03"])

    def test_set_current_timecode_absolute_passes_through(self):
        self.timeline.start_frame = 86160
        self.timeline.start_timecode = "00:59:50:00"

        compound.timeline_markers("set_current_timecode", {"timecode": "01:00:11:03"})

        self.assertEqual(self.timeline.set_timecode_calls, ["01:00:11:03"])

    def test_set_current_timecode_zero_start_passes_through(self):
        self.timeline.start_frame = 0
        self.timeline.start_timecode = "00:00:00:00"

        compound.timeline_markers("set_current_timecode", {"timecode": "00:00:21:03"})

        self.assertEqual(self.timeline.set_timecode_calls, ["00:00:21:03"])

    def test_set_current_timecode_unparseable_passes_through(self):
        # Resolve stays the arbiter of strings the parser cannot read.
        compound.timeline_markers("set_current_timecode", {"timecode": "chapter-3"})

        self.assertEqual(self.timeline.set_timecode_calls, ["chapter-3"])

    def test_set_current_timecode_lifts_elapsed_drop_frame(self):
        # 29.97 DF timeline starting 01:00:00;00 (frame 107892). One elapsed
        # DF minute (00:01:00;02 -> frame 1800) must land at 01:01:00;02 in
        # drop-frame notation, not at the non-drop 01:01:00;12-style TC a
        # naive divmod would produce.
        self.timeline.fps = "29.97"
        self.timeline.start_frame = 107892
        self.timeline.start_timecode = "01:00:00;00"

        compound.timeline_markers("set_current_timecode", {"timecode": "00:01:00;02"})

        self.assertEqual(self.timeline.set_timecode_calls, ["01:01:00;02"])

    def test_frame_id_to_timecode_drop_frame_round_trips(self):
        for frame in (0, 2, 1799, 1800, 3597, 3598, 17981, 17982, 107892, 109692):
            tc = compound._frame_id_to_timecode(
                frame, 29.97, separator=";", drop_frame=True
            )
            back, err = compound._timecode_to_frame_id(tc, 29.97)
            self.assertIsNone(err, tc)
            self.assertEqual(back, frame, tc)

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


class CrossLanguageTimecodePinsTest(unittest.TestCase):
    """The Node converters (editorial/media-inventory/seq-container) and this
    Python family must agree on the canonical NTSC values, measured against
    Resolve itself (GetStartFrame, Studio 19.1.3.7). The Node side pins the
    same numbers in resolve-advanced/test/ntsc-timecode.test.mjs — a change
    that moves one side must move both."""

    def test_ndf_2997_is_nominal(self):
        from src.server import _timecode_to_frame_id
        frames, err = _timecode_to_frame_id("01:00:00:00", 29.97)
        self.assertIsNone(err)
        self.assertEqual(frames, 108000)

    def test_df_2997_drops_108_per_hour(self):
        from src.server import _timecode_to_frame_id
        frames, err = _timecode_to_frame_id("01:00:00;00", 29.97)
        self.assertIsNone(err)
        self.assertEqual(frames, 107892)

    def test_ndf_23976_is_nominal_24_base(self):
        from src.server import _timecode_to_frame_id
        frames, err = _timecode_to_frame_id("01:00:00:00", 23.976)
        self.assertIsNone(err)
        self.assertEqual(frames, 86400)

    def test_multicam_util_agrees(self):
        from src.utils.multicam import timecode_to_frames
        self.assertEqual(timecode_to_frames("01:00:00:00", 29.97), 108000)
        self.assertEqual(timecode_to_frames("01:00:00;00", 29.97, drop_frame=True), 107892)
