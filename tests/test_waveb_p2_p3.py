"""Tests for the final batch: Wave B (EX11 track-index), P2 read-back
(delete_timelines count), P3 (raw set_cdl validation)."""
import unittest
from unittest import mock

import src.server as s


class AudioTrackProbeEX11Test(unittest.TestCase):
    def _tl(self, count):
        tl = mock.Mock()
        tl.GetTrackCount.return_value = count
        # getters return benign values
        for m in ("GetTrackSubType", "GetTrackName", "GetIsTrackEnabled", "GetIsTrackLocked"):
            getattr(tl, m).return_value = "x"
        tl.GetVoiceIsolationState.return_value = {"isEnabled": False, "amount": 0}
        return tl

    def test_index_zero_is_unavailable(self):
        out = s._audio_track_probe(self._tl(3), {"track_index": 0})
        self.assertFalse(out["available"])  # was True under the old <= check

    def test_negative_index_unavailable(self):
        out = s._audio_track_probe(self._tl(3), {"track_index": -1})
        self.assertFalse(out["available"])

    def test_valid_index_available(self):
        out = s._audio_track_probe(self._tl(3), {"track_index": 2})
        self.assertTrue(out["available"])


class DeleteTimelinesReadbackTest(unittest.TestCase):
    def test_verified_true_when_count_drops(self):
        fake_tl = mock.Mock()
        fake_tl.GetUniqueId.return_value = "tid"
        fake_tl.GetName.return_value = "T"
        fake_proj = mock.Mock()
        fake_proj.GetTimelineByIndex.return_value = fake_tl
        fake_mp = mock.Mock()
        fake_mp.DeleteTimelines.return_value = True
        # GetTimelineCount: once to build the list (1), then before(2), then after(1).
        fake_proj.GetTimelineCount.side_effect = [1, 2, 1]
        with mock.patch.object(s, "_check", return_value=(mock.Mock(), fake_proj, None)), \
             mock.patch.object(s, "_get_mp", return_value=(mock.Mock(), fake_proj, fake_mp, None)), \
             mock.patch.object(s, "_confirm_token_required", return_value=False):
            fake_mp.GetRootFolder.return_value = mock.Mock()
            out = s.media_pool("delete_timelines", {"timeline_ids": ["tid"]})
        self.assertTrue(out["success"])
        self.assertTrue(out["verified"])
        self.assertLess(out["timelines_after"], out["timelines_before"])


class RawSetCdlValidationTest(unittest.TestCase):
    def test_malformed_cdl_rejected(self):
        fake_item = mock.Mock()
        # _validate_cdl_payload should reject a non-dict / malformed cdl.
        with mock.patch.object(s, "_check", return_value=(mock.Mock(), mock.Mock(), None)), \
             mock.patch.object(s, "_get_item", return_value=(mock.Mock(), fake_item, None)):
            out = s.timeline_item_color("set_cdl", {"cdl": "not-a-cdl"})
        self.assertIn("error", out)
        fake_item.SetCDL.assert_not_called()


if __name__ == "__main__":
    unittest.main()
