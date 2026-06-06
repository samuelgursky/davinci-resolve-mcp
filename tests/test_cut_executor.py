"""Tests for the Cut-IR executor (timeline apply_cuts).

apply_cuts is DRY-RUN by default; applying is destructive (confirm-token gated,
version-archived by the hook). These tests mock the live connection so they stay
offline.
"""
import unittest
from unittest import mock

import src.server as s


def _proj_with_tl():
    proj = mock.Mock()
    proj.GetCurrentTimeline.return_value = mock.Mock()
    return proj


class ApplyCutsDryRunTest(unittest.TestCase):
    def _call(self, params):
        with mock.patch.object(s, "get_resolve", return_value=None), \
             mock.patch.object(s, "_check", return_value=(None, _proj_with_tl(), None)):
            return s.timeline("apply_cuts", params)

    def test_dry_run_default_no_mutation(self):
        cuts = [
            {"action": "lift", "span": {"start": 100, "end": 110}, "kind": "filler"},
            {"action": "lift", "span": {"start": 0, "end": 10}, "kind": "filler"},
            {"action": "keep", "span": {"start": 5, "end": 6}},
        ]
        out = self._call({"cuts": cuts})
        self.assertTrue(out["dry_run"])
        self.assertEqual(out["would_apply"], 2)  # 'keep' excluded
        # latest-first ordering
        self.assertEqual(out["plan"][0]["span"]["start"], 100)
        self.assertEqual(out["plan"][1]["span"]["start"], 0)

    def test_requires_cuts_list(self):
        out = self._call({})
        self.assertIn("error", out)

    def test_empty_cuts(self):
        out = self._call({"cuts": []})
        self.assertEqual(out["would_apply"], 0)


class ApplyCutsApplyTest(unittest.TestCase):
    def test_applies_in_reverse_order(self):
        cuts = [
            {"action": "lift", "span": {"start": 0, "end": 10}},
            {"action": "ripple_delete", "span": {"start": 100, "end": 110}},
        ]
        calls = []

        def fake_lift(tl, rp):
            calls.append(rp)
            return {"success": True, "deleted": 1}

        with mock.patch.object(s, "get_resolve", return_value=None), \
             mock.patch.object(s, "_check", return_value=(None, _proj_with_tl(), None)), \
             mock.patch.object(s, "_confirm_token_required", return_value=False), \
             mock.patch.object(s, "_timeline_lift_range_impl", side_effect=fake_lift):
            out = s.timeline("apply_cuts", {"cuts": cuts, "dry_run": False})

        self.assertTrue(out["success"])
        self.assertEqual(out["applied"], 2)
        self.assertEqual(out["total"], 2)
        # latest-first: ripple at 100 applied before lift at 0
        self.assertEqual(calls[0]["start_frame"], 100)
        self.assertTrue(calls[0]["ripple"])
        self.assertEqual(calls[1]["start_frame"], 0)
        self.assertFalse(calls[1]["ripple"])

    def test_issues_confirm_token_when_required(self):
        with mock.patch.object(s, "get_resolve", return_value=None), \
             mock.patch.object(s, "_check", return_value=(None, _proj_with_tl(), None)), \
             mock.patch.object(s, "_confirm_token_required", return_value=True):
            out = s.timeline("apply_cuts", {
                "cuts": [{"action": "lift", "span": {"start": 0, "end": 10}}],
                "dry_run": False,
            })
        # Without a token, it must return a preview/token issuance, not apply.
        self.assertNotIn("applied", out)


if __name__ == "__main__":
    unittest.main()
