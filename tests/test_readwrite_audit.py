"""Tests for the read/write symmetry audit logic."""
import contextlib
import importlib.util
import io
import os
import pathlib
import tempfile
import unittest

_SPEC = importlib.util.spec_from_file_location(
    "audit_rw",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "scripts", "audit_readwrite_symmetry.py"),
)
audit_rw = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(audit_rw)
ROOT = pathlib.Path(__file__).resolve().parent.parent


class AuditTest(unittest.TestCase):
    def test_set_without_get_is_high_signal(self):
        src = 'return _unknown(action, ["get_name","set_name","set_orphan"])'
        total, covered, high, low = audit_rw.audit(src)
        self.assertIn("set_orphan", high)
        self.assertNotIn("set_name", high)  # get_name covers it

    def test_plural_read_counts_as_covered(self):
        src = 'return _unknown(action, ["add_keyframe","get_keyframes"])'
        _, covered, high, low = audit_rw.audit(src)
        self.assertEqual(high, [])
        self.assertEqual(low, [])  # add_keyframe covered by plural get_keyframes
        self.assertEqual(covered, 1)

    def test_create_is_low_signal(self):
        src = 'return _unknown(action, ["create_timeline"])'
        _, _, high, low = audit_rw.audit(src)
        self.assertEqual(high, [])
        self.assertIn("create_timeline", low)

    def test_enabled_variant_covered(self):
        src = 'return _unknown(action, ["set_track_enable","get_track_enabled"])'
        _, covered, high, _low = audit_rw.audit(src)
        self.assertEqual(high, [])
        self.assertEqual(covered, 1)

    def test_locked_variant_covered(self):
        src = 'return _unknown(action, ["set_track_lock","get_track_locked"])'
        _, covered, high, _low = audit_rw.audit(src)
        self.assertEqual(high, [])
        self.assertEqual(covered, 1)

    def test_cache_enabled_variant_covered(self):
        src = 'return _unknown(action, ["set_cache","get_cache_enabled"])'
        _, covered, high, _low = audit_rw.audit(src)
        self.assertEqual(high, [])
        self.assertEqual(covered, 1)

    def test_caps_preset_covered_by_get_caps(self):
        src = 'return _unknown(action, ["set_caps_preset","get_caps"])'
        _, covered, high, _low = audit_rw.audit(src)
        self.assertEqual(high, [])
        self.assertEqual(covered, 1)

    def test_mcp_update_policy_covered_by_status_payload(self):
        src = 'return _unknown(action, ["mcp_update_status","set_mcp_update_policy"])'
        _, covered, high, _low = audit_rw.audit(src)
        self.assertEqual(high, [])
        self.assertEqual(covered, 1)

    def test_reference_doc_matches_current_audit(self):
        """The committed report must match the current server action surface.

        This fires whenever an action is added to src/server.py, which is the
        point of it — but a bare assertEqual on two large documents says
        nothing about how to clear it, so name the regeneration command.
        """
        src = (ROOT / "src" / "server.py").read_text()
        doc = ROOT / "docs" / "reference" / "readwrite-symmetry.md"
        self.assertEqual(
            doc.read_text(),
            audit_rw.render_report(src),
            f"docs/reference/readwrite-symmetry.md is stale. "
            f"Regenerate it with: {audit_rw.REGEN_COMMAND}",
        )

    def test_check_mode_passes_against_the_committed_report(self):
        self.assertEqual(audit_rw.main(["--check"]), 0)

    def test_stdout_mode_does_not_write_the_report(self):
        doc = ROOT / "docs" / "reference" / "readwrite-symmetry.md"
        before = doc.read_text()
        original = audit_rw.DOC_PATH
        with tempfile.TemporaryDirectory() as tmp:
            audit_rw.DOC_PATH = os.path.join(tmp, "readwrite-symmetry.md")
            try:
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    self.assertEqual(audit_rw.main(["--stdout"]), 0)
            finally:
                audit_rw.DOC_PATH = original
            self.assertFalse(os.path.exists(os.path.join(tmp, "readwrite-symmetry.md")))
        self.assertIn("# Read/Write Symmetry Audit", out.getvalue())
        self.assertEqual(doc.read_text(), before)

    def test_named_action_list_is_scanned(self):
        src = '''
_ACTIONS = ["get_name", "set_name"]
def tool(action):
    return _unknown(action, _ACTIONS)
'''
        total, covered, high, low = audit_rw.audit(src)
        self.assertEqual((total, covered, high, low), (1, 1, [], []))

    def test_starred_action_list_is_expanded(self):
        src = '''
_READ_ACTIONS = ["get_name"]
def tool(action):
    return _unknown(action, ["set_name", *_READ_ACTIONS])
'''
        total, covered, high, low = audit_rw.audit(src)
        self.assertEqual((total, covered, high, low), (1, 1, [], []))

    def test_annotated_action_list_is_scanned(self):
        src = '''
_ACTIONS: tuple[str, ...] = ("get_name", "set_name")
def tool(action):
    return _unknown(action, _ACTIONS)
'''
        total, covered, high, low = audit_rw.audit(src)
        self.assertEqual((total, covered, high, low), (1, 1, [], []))

    def test_string_list_and_tuple_constants_are_scanned(self):
        src = '''
_STRING_ACTIONS = "set_string"
_LIST_ACTIONS = ["set_list"]
_TUPLE_ACTIONS = ("set_tuple",)
def string_tool(action):
    return _unknown(action, _STRING_ACTIONS)
def list_tool(action):
    return _unknown(action, _LIST_ACTIONS)
def tuple_tool(action):
    return _unknown(action, _TUPLE_ACTIONS)
'''
        total, covered, high, low = audit_rw.audit(src)
        self.assertEqual(
            (total, covered, high, low),
            (3, 0, ["set_list", "set_string", "set_tuple"], []),
        )

    def test_concatenated_action_constants_are_scanned(self):
        src = '''
_READ_ACTIONS = ["get_name"]
_WRITE_ACTIONS = ("set_name",)
_ACTIONS = _READ_ACTIONS + _WRITE_ACTIONS
def tool(action):
    return _unknown(action, _ACTIONS)
'''
        total, covered, high, low = audit_rw.audit(src)
        self.assertEqual((total, covered, high, low), (1, 1, [], []))

    def test_recursive_action_constants_are_skipped(self):
        src = '''
_FIRST = _SECOND
_SECOND = _FIRST
def tool(action):
    return _unknown(action, _FIRST)
'''
        total, covered, high, low = audit_rw.audit(src)
        self.assertEqual((total, covered, high, low), (0, 0, [], []))

    def test_partially_dynamic_action_group_is_skipped(self):
        src = '''
def dynamic_actions():
    return ["get_orphan"]
def tool(action):
    return _unknown(action, ["set_orphan", *dynamic_actions()])
'''
        total, covered, high, low = audit_rw.audit(src)
        self.assertEqual((total, covered, high, low), (0, 0, [], []))

    def test_report_labels_occurrences_and_distinct_gap_names(self):
        src = '''
def first_tool(action):
    return _unknown(action, ["set_orphan"])
def second_tool(action):
    return _unknown(action, ["set_orphan"])
'''
        report = audit_rw.render_report(src)
        self.assertIn("- write-style action occurrences scanned: **2**", report)
        self.assertIn(
            "- write-style action occurrences with a matching read: **0**",
            report,
        )
        self.assertIn(
            "- distinct high-signal `set_` actions without a direct/known readback: "
            "**1**",
            report,
        )
        self.assertIn(
            "## Low-signal (create/add/insert/apply/import — usually expected): "
            "0 distinct names",
            report,
        )


if __name__ == "__main__":
    unittest.main()
