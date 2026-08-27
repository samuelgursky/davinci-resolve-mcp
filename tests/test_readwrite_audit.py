"""Tests for the read/write symmetry audit logic."""
import importlib.util
import os
import pathlib
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
        src = (ROOT / "src" / "server.py").read_text()
        doc = ROOT / "docs" / "reference" / "readwrite-symmetry.md"
        self.assertEqual(doc.read_text(), audit_rw.render_report(src))

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


if __name__ == "__main__":
    unittest.main()
