"""Issue #322: `timeline.duplicate` leaves the original timeline current.

Resolve makes the copy current. A caller who duplicated "as a backup, then
edit A" was editing the backup, and the response did not say which timeline
was current.
"""

from __future__ import annotations

import unittest
from unittest import mock

import src.server as server
from tests.test_timeline_pinning import _Project, _Timeline


class _DuplicatingTimeline(_Timeline):
    def __init__(self, name, uid, project):
        super().__init__(name, uid)
        self.project = project

    def DuplicateTimeline(self, name):
        copy = _DuplicatingTimeline(name, f"{self.uid}-copy", self.project)
        self.project.timelines.append(copy)
        self.project.current = copy  # what Resolve does
        return copy


class DuplicateKeepsCurrentTest(unittest.TestCase):
    def setUp(self):
        self.proj = _Project([], current=None)
        self.a = _DuplicatingTimeline("A", "uid-a", self.proj)
        self.proj.timelines.append(self.a)
        self.proj.current = self.a
        patcher = mock.patch.object(server, "_check", return_value=(object(), self.proj, None))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_original_stays_current(self):
        result = server.timeline("duplicate", {"name": "A dup"})
        self.assertTrue(result["success"])
        self.assertEqual(result["name"], "A dup")
        self.assertEqual(result["id"], "uid-a-copy")
        self.assertEqual(result["current"], "A")
        self.assertIs(self.proj.current, self.a)

    def test_make_current_keeps_the_copy(self):
        result = server.timeline("duplicate", {"name": "A dup", "make_current": True})
        self.assertEqual(result["current"], "A dup")
        self.assertEqual(self.proj.current.GetName(), "A dup")

    def test_a_pinned_duplicate_returns_to_the_callers_timeline(self):
        b = _DuplicatingTimeline("B", "uid-b", self.proj)
        self.proj.timelines.append(b)
        self.proj.current = b
        result = server.timeline("duplicate", {"name": "A dup", "timeline_id": "uid-a"})
        self.assertEqual(result["id"], "uid-a-copy")
        self.assertIs(self.proj.current, b)


if __name__ == "__main__":
    unittest.main()
