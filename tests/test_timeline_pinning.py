"""Issue #320: a call can name its timeline, and unread params are reported.

Before, every timeline-scoped action acted on the current timeline, and a
`timeline_id` nothing read was dropped: the write landed on whichever timeline
was current (or the one the user had just clicked) and the response said
success. These tests drive the guarded tool functions against a fake project
with two timelines.
"""

from __future__ import annotations

import unittest
from unittest import mock

import src.server as server
from src.utils import operation_result


class _Item:
    def __init__(self, name):
        self.name = name

    def GetName(self):
        return self.name

    def SetName(self, name):
        self.name = name
        return True


class _Timeline:
    def __init__(self, name, uid):
        self.name, self.uid = name, uid
        self.items = [_Item(f"{name}-clip-0"), _Item(f"{name}-clip-1")]

    def GetName(self):
        return self.name

    def GetUniqueId(self):
        return self.uid

    def GetItemListInTrack(self, track_type, index):
        return list(self.items) if (track_type, index) == ("video", 1) else []


class _Project:
    def __init__(self, timelines, current):
        self.timelines = timelines
        self.current = current
        self.switches = []

    def GetTimelineCount(self):
        return len(self.timelines)

    def GetTimelineByIndex(self, index):
        return self.timelines[index - 1] if 1 <= index <= len(self.timelines) else None

    def GetCurrentTimeline(self):
        return self.current

    def SetCurrentTimeline(self, tl):
        self.switches.append(tl.GetName())
        self.current = tl
        return True


class TimelinePinningTest(unittest.TestCase):
    def setUp(self):
        self.a = _Timeline("A scratch", "uid-a")
        self.b = _Timeline("B edit", "uid-b")
        self.proj = _Project([self.a, self.b], current=self.b)
        patcher = mock.patch.object(server, "_check", return_value=(object(), self.proj, None))
        patcher.start()
        self.addCleanup(patcher.stop)

    def envelope(self, result):
        return result[operation_result.ENVELOPE_KEY]

    def test_timeline_id_targets_that_timeline_and_restores_the_current_one(self):
        result = server.timeline_item("get_name", {"item_index": 1, "timeline_id": "uid-a"})
        self.assertEqual(result["name"], "A scratch-clip-1")
        self.assertIs(self.proj.current, self.b, "the caller's current timeline must come back")
        self.assertEqual(self.proj.switches, ["A scratch", "B edit"])
        timeline = self.envelope(result)["timeline"]
        self.assertEqual(timeline["id"], "uid-a")
        self.assertTrue(timeline["pinned"])
        self.assertEqual(timeline["restored_current"]["name"], "B edit")
        self.assertNotIn("ignored_params", result)

    def test_a_write_lands_on_the_pinned_timeline(self):
        server.timeline_item("set_name", {"item_index": 0, "name": "renamed", "timeline_name": "A scratch"})
        self.assertEqual(self.a.items[0].name, "renamed")
        self.assertEqual(self.b.items[0].name, "B edit-clip-0")

    def test_pinning_the_current_timeline_switches_nothing(self):
        result = server.timeline_item("get_name", {"timeline_id": "uid-b"})
        self.assertEqual(result["name"], "B edit-clip-0")
        self.assertEqual(self.proj.switches, [])
        self.assertNotIn("restored_current", self.envelope(result)["timeline"])

    def test_unpinned_calls_name_the_timeline_they_acted_on(self):
        timeline = self.envelope(server.timeline_item("get_name", {}))["timeline"]
        self.assertEqual(timeline, {"name": "B edit", "id": "uid-b"})

    def test_an_unknown_timeline_refuses_before_anything_runs(self):
        with mock.patch.object(server, "_get_item", side_effect=AssertionError("action ran")):
            result = server.timeline_item("set_name", {"name": "x", "timeline_id": "nope"})
        self.assertEqual(result["error"]["code"], "TIMELINE_NOT_FOUND")
        self.assertEqual(self.proj.switches, [])

    def test_an_ambiguous_name_refuses(self):
        self.proj.timelines.append(_Timeline("A scratch", "uid-a2"))
        result = server.timeline_item("get_name", {"timeline_name": "A scratch"})
        self.assertEqual(result["error"]["code"], "TIMELINE_NAME_AMBIGUOUS")
        self.assertEqual(sorted(result["error"]["state"]["ids"]), ["uid-a", "uid-a2"])

    def test_id_and_name_must_agree(self):
        result = server.timeline_item("get_name", {"timeline_id": "uid-a", "timeline_name": "B edit"})
        self.assertEqual(result["error"]["code"], "TIMELINE_SELECTOR_MISMATCH")

    def test_the_current_timeline_is_restored_when_the_action_raises(self):
        with mock.patch.object(server, "_get_item", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                server.timeline_item("get_name", {"timeline_id": "uid-a"})
        self.assertIs(self.proj.current, self.b)

    def test_a_restore_that_does_not_take_is_reported(self):
        def stuck(tl):
            self.proj.switches.append(tl.GetName())
            if tl is self.a:
                self.proj.current = tl
            return True  # says True for B, stays on A

        self.proj.SetCurrentTimeline = stuck
        result = server.timeline_item("get_name", {"timeline_id": "uid-a"})
        timeline = self.envelope(result)["timeline"]
        self.assertTrue(timeline["restore_failed"])
        self.assertNotIn("restored_current", timeline)

    def test_set_current_keeps_timeline_id_as_its_own_selector(self):
        result = server.timeline("set_current", {"timeline_id": "uid-a"})
        self.assertTrue(result["success"])
        self.assertIs(self.proj.current, self.a, "set_current must not be undone by a pin restore")


class IgnoredParamsTest(unittest.TestCase):
    def setUp(self):
        self.proj = _Project([_Timeline("B edit", "uid-b")], current=None)
        self.proj.current = self.proj.timelines[0]
        patcher = mock.patch.object(server, "_check", return_value=(object(), self.proj, None))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_key_no_code_read_is_reported(self):
        result = server.timeline_item("get_name", {"item_index": 0, "timline_id": "typo"})
        self.assertEqual(result["ignored_params"], ["timline_id"])
        self.assertIn("timline_id", " ".join(result[operation_result.ENVELOPE_KEY]["warnings"]))

    def test_envelope_keys_are_not_reported(self):
        result = server.timeline_item("get_name", {"execution_id": "exec_1"})
        self.assertNotIn("ignored_params", result)

    def test_failures_carry_no_ignored_list(self):
        result = server.timeline_item("get_name", {"item_index": 99, "extra": 1})
        self.assertIn("error", result)
        self.assertNotIn("ignored_params", result)

    def test_nested_tool_calls_are_not_scoped(self):
        seen = {}

        def outer_action(action, params=None):
            seen["inner"] = server.timeline_item("get_name", {"item_index": 0, "internal_only": 1})
            return {"success": True}

        guarded = server._guard_missing_params(outer_action)
        guarded("x", {})
        self.assertNotIn("ignored_params", seen["inner"])


if __name__ == "__main__":
    unittest.main()
