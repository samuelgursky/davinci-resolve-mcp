"""Confirmation-token coverage for raw timeline_item_color.copy_grades."""

import unittest
from unittest import mock

import src.server as compound


class _TimelineItemStub:
    def __init__(self, uid):
        self._uid = uid
        self.copy_grades_calls = []

    def GetUniqueId(self):
        return self._uid

    def CopyGrades(self, targets):
        self.copy_grades_calls.append([target.GetUniqueId() for target in targets])
        return True


class _TimelineStub:
    def __init__(self, items):
        self._items = items

    def GetTrackCount(self, track_type):
        return 1 if track_type == "video" else 0

    def GetItemListInTrack(self, track_type, index):
        if track_type != "video" or index != 1:
            return []
        return self._items


class RawCopyGradesConfirmationTest(unittest.TestCase):
    def setUp(self):
        self.source = _TimelineItemStub("source-1")
        self.target = _TimelineItemStub("target-1")
        self.timeline = _TimelineStub([self.source, self.target])
        compound._CONFIRM_TOKENS.clear()
        self.patches = [
            mock.patch.object(compound, "_check", return_value=(mock.Mock(), mock.Mock(), None)),
            mock.patch.object(compound, "_get_item", return_value=(self.timeline, self.source, None)),
            mock.patch.object(compound, "_get_tl", return_value=(mock.Mock(), self.timeline, None)),
            mock.patch.object(compound, "_confirm_token_required", return_value=True),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        compound._CONFIRM_TOKENS.clear()

    def _params(self, **extra):
        return {
            "target_ids": ["target-1"],
            "acknowledge_trap": True,
            **extra,
        }

    def test_raw_copy_grades_without_token_returns_confirmation_required(self):
        out = compound.timeline_item_color("copy_grades", self._params())

        self.assertEqual(out["status"], "confirmation_required")
        self.assertEqual(out["error"]["code"], "CONFIRMATION_REQUIRED")
        self.assertEqual(out["preview"]["operation"], "timeline_item_color.copy_grades")
        self.assertEqual(out["preview"]["target_ids"], ["target-1"])
        self.assertEqual(self.source.copy_grades_calls, [])

    def test_raw_copy_grades_with_token_mutates_once(self):
        first = compound.timeline_item_color("copy_grades", self._params())
        token = first["confirm_token"]

        second = compound.timeline_item_color(
            "copy_grades",
            self._params(confirm_token=token),
        )

        self.assertTrue(second["success"])
        self.assertEqual(self.source.copy_grades_calls, [["target-1"]])

    def test_raw_copy_grades_rejects_token_when_params_change(self):
        first = compound.timeline_item_color("copy_grades", self._params())
        token = first["confirm_token"]

        changed = compound.timeline_item_color(
            "copy_grades",
            {
                "target_ids": ["target-1", "missing-1"],
                "acknowledge_trap": True,
                "confirm_token": token,
            },
        )

        self.assertEqual(changed["error"]["code"], "CONFIRM_TOKEN_FINGERPRINT_MISMATCH")
        self.assertEqual(self.source.copy_grades_calls, [])

    def test_trap_acknowledgement_is_still_required_before_confirmation(self):
        out = compound.timeline_item_color("copy_grades", {"target_ids": ["target-1"]})

        self.assertEqual(out["retry_with"], {"acknowledge_trap": True})
        self.assertNotIn("confirm_token", out)
        self.assertEqual(self.source.copy_grades_calls, [])


if __name__ == "__main__":
    unittest.main()
