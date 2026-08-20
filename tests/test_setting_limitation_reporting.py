"""A refused SetSetting says why, when the ledger already knows (issue #141).

`SetSetting` reports a refusal as a bare `False`. For several keys the reason is
already measured and written down in `src/utils/api_truth.py` —
`timelinePlaybackFrameRate` cannot be written from the API at all, in any value
form, before or after a timeline exists — and the caller was getting none of it.
A bare `{"success": false}` reads as "your value was wrong", which sends a
caller into retrying value forms for a key that has no writable path.
"""
import unittest

import src.server as compound


class FakeProject:
    """A project whose SetSetting refuses whatever it is told to refuse."""

    def __init__(self, refuse=()):
        self.refuse = set(refuse)
        self.calls = []

    def SetSetting(self, name, value):
        self.calls.append((name, value))
        return name not in self.refuse


class FakeTimeline(FakeProject):
    pass


class _ProjectStubTest(unittest.TestCase):
    refuse = ("timelinePlaybackFrameRate",)

    def setUp(self):
        self.project = FakeProject(self.refuse)
        self._orig = compound._check
        compound._check = lambda: (object(), self.project, None)

    def tearDown(self):
        compound._check = self._orig


class RefusedProjectSettingTest(_ProjectStubTest):
    def test_a_refused_key_in_the_ledger_carries_its_reason(self):
        out = compound.project_settings(
            "set_setting", {"name": "timelinePlaybackFrameRate", "value": "60"})

        self.assertFalse(out["success"])
        known = out["known_limitation"]
        self.assertIn("timelinePlaybackFrameRate", known["symbol"])
        # The two things a caller cannot work out from `False` alone: that no
        # value form works, and that the way through is the UI.
        self.assertIn("cannot be set from the API", known["reality"])
        self.assertIn("Project Settings", known["recommended"])

    def test_a_refused_key_the_ledger_does_not_know_stays_bare(self):
        # Silence is correct here. Inventing an explanation for an unmeasured
        # failure is the failure mode this whole ledger exists to avoid.
        self.project.refuse.add("someUnmeasuredKey")
        out = compound.project_settings(
            "set_setting", {"name": "someUnmeasuredKey", "value": 1})

        self.assertFalse(out["success"])
        self.assertNotIn("known_limitation", out)

    def test_a_successful_write_carries_nothing_extra(self):
        out = compound.project_settings(
            "set_setting", {"name": "timelineFrameRate", "value": "60"})

        self.assertEqual(out, {"success": True})

    def test_the_write_is_still_attempted_before_the_ledger_is_consulted(self):
        # The ledger annotates a real refusal; it must never stand in for one.
        # A key that is documented as unwritable could still start working in a
        # later Resolve build, and this must report that honestly.
        compound.project_settings(
            "set_setting", {"name": "timelinePlaybackFrameRate", "value": "60"})
        self.assertEqual(self.project.calls, [("timelinePlaybackFrameRate", "60")])

    def test_a_key_that_starts_working_reports_plain_success(self):
        self.project.refuse.clear()
        out = compound.project_settings(
            "set_setting", {"name": "timelinePlaybackFrameRate", "value": "60"})
        self.assertEqual(out, {"success": True})


class RefusedTimelineSettingTest(unittest.TestCase):
    """The same treatment on `timeline set_setting`, scoped to Timeline keys."""

    def setUp(self):
        self.timeline = FakeTimeline(("timelinePlaybackFrameRate",))
        project = type("P", (), {"GetCurrentTimeline": lambda _self: self.timeline})()
        self._orig = compound._check
        compound._check = lambda: (object(), project, None)

    def tearDown(self):
        compound._check = self._orig

    def test_a_project_scoped_entry_is_not_borrowed_for_a_timeline_refusal(self):
        out = compound.timeline(
            "set_setting", {"name": "timelinePlaybackFrameRate", "value": "60"})

        self.assertFalse(out["success"])
        self.assertNotIn("known_limitation", out)


class SettingLimitationMatchTest(unittest.TestCase):
    def test_the_match_is_scoped_to_the_object(self):
        # Project and Timeline both have SetSetting and their key names overlap.
        # The ledger entry is a Project measurement, so a Timeline refusal of
        # the same key must not borrow it.
        self.assertIsNotNone(
            compound._setting_limitation("timelinePlaybackFrameRate", obj="Project"))
        self.assertIsNone(
            compound._setting_limitation("timelinePlaybackFrameRate", obj="Timeline"))

    def test_unknown_and_empty_keys_match_nothing(self):
        self.assertIsNone(compound._setting_limitation("noSuchSettingKey"))
        self.assertIsNone(compound._setting_limitation(""))
        self.assertIsNone(compound._setting_limitation(None))

    def test_a_substring_of_a_known_key_does_not_match_it(self):
        # lookup_api_truth matches substrings across the prose, so a loose
        # match would attach the playback-rate entry to unrelated keys.
        self.assertIsNone(compound._setting_limitation("timeline"))


if __name__ == "__main__":
    unittest.main()
