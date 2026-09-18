"""Sync-event timecodes on drop-frame media.

`detect_sync_events_for_file` reports each event at `start_timecode + offset`,
where `start_timecode` is whatever ffprobe read off the media's own timecode
track. On an NTSC deliverable that is routinely DROP-FRAME, spelled
`HH:MM:SS;FF`.

`timecode_to_frames` honours drop-frame: `01:00:00;00` at 29.97 is frame
107892, not 108000. The trip back out did not, so the head of a drop-frame clip
came back as `00:59:56:12` — 3.6 seconds early per hour, in the marker note
Resolve stores and on the one number an assistant uses to line two cameras up.

These tests drive `_timecode_for_event`, the function the detector calls, so
they describe the reported timecode rather than a helper signature.
"""

import unittest

from src.utils.sync_detection import _timecode_for_event


NTSC = 29.97
NTSC_60 = 59.94


class DropFrameSyncEventTimecode(unittest.TestCase):
    def test_head_of_a_drop_frame_clip_reports_its_own_timecode(self):
        self.assertEqual(_timecode_for_event(0.0, NTSC, "01:00:00;00"), "01:00:00;00")

    def test_drop_frame_head_round_trips_across_the_ten_minute_pattern(self):
        # Every minute in the first ten, plus the boundaries where the pattern
        # restarts: minute 0 keeps :00 and :01, minutes 1-9 do not.
        heads = [f"01:{minute:02d}:00;{2 if minute % 10 else 0:02d}" for minute in range(12)]
        heads += ["00:00:00;00", "00:09:59;29", "00:10:00;00", "02:59:59;29"]
        for head in heads:
            with self.subTest(head=head):
                self.assertEqual(_timecode_for_event(0.0, NTSC, head), head)

    def test_drop_frame_head_round_trips_at_59_94(self):
        for head in ("01:00:00;00", "01:01:00;04", "00:10:00;00", "00:09:59;59"):
            with self.subTest(head=head):
                self.assertEqual(_timecode_for_event(0.0, NTSC_60, head), head)

    def test_an_offset_advances_by_the_frames_that_actually_elapsed(self):
        # 1798 frames is one short minute of drop-frame timecode, so the event
        # lands exactly on the next minute, which starts at ;02.
        elapsed = 1798 / NTSC
        self.assertEqual(_timecode_for_event(elapsed, NTSC, "01:00:00;02"), "01:01:00;02")

    def test_non_drop_frame_timecode_is_unchanged(self):
        # 29.97 non-drop timecode legitimately lags the wall clock; frame 107892
        # is 00:59:56:12 and stays that way.
        self.assertEqual(_timecode_for_event(0.0, NTSC, "01:00:00:00"), "01:00:00:00")
        self.assertEqual(_timecode_for_event(3600.0, NTSC, "00:00:00:00"), "00:59:56:12")
        self.assertEqual(_timecode_for_event(0.0, 24.0, "01:00:00:00"), "01:00:00:00")

    def test_semicolon_is_ignored_where_drop_frame_is_not_defined(self):
        # `timecode_to_frames` drops nothing at 23.976, so neither does the way
        # back; the separator follows the arithmetic, not the input spelling.
        self.assertEqual(_timecode_for_event(0.0, 23.976, "01:00:00;00"), "01:00:00:00")

    def test_inverse_agrees_with_the_forward_conversion(self):
        from src.utils.multicam import frames_to_timecode, timecode_to_frames

        for head in ("01:00:00;00", "01:05:29;17", "00:10:00;00"):
            with self.subTest(head=head):
                frame = timecode_to_frames(head, NTSC)
                self.assertEqual(frames_to_timecode(frame, NTSC, drop_frame=True), head)

    def test_frames_to_timecode_refuses_what_it_cannot_read(self):
        from src.utils.multicam import frames_to_timecode

        self.assertIsNone(frames_to_timecode(0, "not a rate"))
        self.assertIsNone(frames_to_timecode("not a frame", NTSC))
        self.assertEqual(frames_to_timecode(-5, NTSC), "00:00:00:00")


if __name__ == "__main__":
    unittest.main()
