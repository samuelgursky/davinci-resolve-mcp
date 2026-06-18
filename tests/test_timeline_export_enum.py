"""Regression test for the raw timeline.export enum-argument fix (v2.54.1).

Timeline.Export needs resolved resolve.EXPORT_* enum *values*; the raw export
action used to forward p["type"] as a string, which Resolve silently rejects (no
file written). The action must now resolve friendly format names — and EXPORT_*
constant names — to live enum values via _timeline_export_spec.
"""
import unittest
from unittest import mock

import src.server as s


class FakeResolveExport:
    EXPORT_FCPXML_1_10 = "__FCPXML__"
    EXPORT_EDL = "__EDL__"
    EXPORT_NONE = "__NONE__"


class TimelineExportSpecTest(unittest.TestCase):
    def test_friendly_format_resolves_to_enum_value(self):
        spec = s._timeline_export_spec({"type": "fcpxml"}, FakeResolveExport())
        self.assertEqual(spec["export_type"], "__FCPXML__")
        self.assertEqual(spec["export_subtype"], "__NONE__")
        # Never the raw string.
        self.assertNotEqual(spec["export_type"], "fcpxml")

    def test_export_constant_name_resolves(self):
        spec = s._timeline_export_spec({"type": "EXPORT_EDL"}, FakeResolveExport())
        self.assertEqual(spec["export_type"], "__EDL__")


class TimelineExportActionTest(unittest.TestCase):
    def _run_export(self, params):
        fake_tl = mock.Mock()
        fake_tl.Export.return_value = True
        fake_proj = mock.Mock()
        fake_proj.GetCurrentTimeline.return_value = fake_tl
        with mock.patch.object(s, "_check", return_value=(mock.Mock(), fake_proj, None)), \
             mock.patch.object(s, "get_resolve", return_value=FakeResolveExport()):
            out = s.timeline("export", params)
        return out, fake_tl

    def test_action_passes_resolved_enum_not_string(self):
        out, fake_tl = self._run_export({"path": "/tmp/out.fcpxml", "type": "fcpxml"})
        path_arg, type_arg, subtype_arg = fake_tl.Export.call_args[0]
        self.assertEqual(path_arg, "/tmp/out.fcpxml")
        self.assertEqual(type_arg, "__FCPXML__")   # resolved, not "fcpxml"
        self.assertEqual(subtype_arg, "__NONE__")
        self.assertTrue(out["success"])
        self.assertEqual(out["export_type"], "EXPORT_FCPXML_1_10")

    def test_action_edl(self):
        _, fake_tl = self._run_export({"path": "/tmp/out.edl", "type": "edl"})
        self.assertEqual(fake_tl.Export.call_args[0][1], "__EDL__")


if __name__ == "__main__":
    unittest.main()
