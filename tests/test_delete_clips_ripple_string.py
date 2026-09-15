"""timeline.delete_clips must read ripple the way a caller meant it.

Several MCP clients send booleans as strings. A bare bool() test turns
ripple="false" into a ripple delete: Resolve closes the gap and shifts every
downstream item, for a caller who explicitly declined that. The handler, the
lift_range path, the confirm-token gate, the strict-archive rule and the risk
classifier all have to agree on the same coerced value.
"""
import unittest
from unittest import mock

import src.server as s
from src.utils import destructive_hook
from src.utils.execution_lifecycle import classify_operation_risk


class FakeItem:
    def __init__(self, uid):
        self.uid = uid

    def GetUniqueId(self):
        return self.uid

    def GetName(self):
        return f"clip-{self.uid}"

    def GetStart(self):
        return 0

    def GetEnd(self):
        return 24


class RecordingTimeline:
    def __init__(self, items):
        self.video = list(items)
        self.ripples = []

    def GetTrackCount(self, track_type):
        return 1 if track_type == "video" else 0

    def GetItemListInTrack(self, track_type, index):
        return list(self.video) if (track_type, index) == ("video", 1) else []

    def DeleteClips(self, items, ripple):
        self.ripples.append(ripple)
        gone = {id(it) for it in items}
        self.video = [it for it in self.video if id(it) not in gone]
        return True


class RippleStringTest(unittest.TestCase):
    def _delete(self, params):
        tl = RecordingTimeline([FakeItem("a")])
        fake_proj = mock.Mock()
        fake_proj.GetCurrentTimeline.return_value = tl
        with mock.patch.object(s, "get_resolve", return_value=None), \
             mock.patch.object(s, "_check", return_value=(mock.Mock(), fake_proj, None)), \
             mock.patch.object(s, "_confirm_token_required", return_value=False),              mock.patch.object(destructive_hook, "is_strict_required", return_value=False):
            # No project is open offline, so the strict-archive refusal is
            # taken out of the way; its own ripple reading is tested below.
            return s.timeline("delete_clips", params), tl

    def test_string_false_is_not_a_ripple_delete(self):
        res, tl = self._delete({"clip_ids": ["a"], "ripple": "false"})
        self.assertTrue(res["success"])
        self.assertEqual(tl.ripples, [False])

    def test_string_true_is_still_a_ripple_delete(self):
        res, tl = self._delete({"clip_ids": ["a"], "ripple": "true"})
        self.assertTrue(res["success"])
        self.assertEqual(tl.ripples, [True])

    def test_lift_range_string_false_is_not_a_ripple_delete(self):
        tl = RecordingTimeline([FakeItem("a")])
        res = s._timeline_lift_range_impl(tl, {"start_frame": 0, "end_frame": 24, "ripple": "false"})
        self.assertTrue(res["success"])
        self.assertEqual(tl.ripples, [False])

    def test_string_false_is_not_gated_as_ripple(self):
        params = {"clip_ids": ["a"], "ripple": "false"}
        with mock.patch.object(s, "_confirm_token_required", return_value=True):
            self.assertFalse(s._action_will_gate_pending_confirm("timeline", "delete_clips", params))
        self.assertFalse(destructive_hook.is_strict_required("timeline", "delete_clips", params))
        reasons = classify_operation_risk("timeline", "delete_clips", params).reasons
        self.assertNotIn("Ripple mode alters downstream timeline synchronization", reasons)


if __name__ == "__main__":
    unittest.main()
