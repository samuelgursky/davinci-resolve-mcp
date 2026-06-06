"""Tests for the read/write symmetry audit logic."""
import importlib.util
import os
import unittest

_SPEC = importlib.util.spec_from_file_location(
    "audit_rw",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "scripts", "audit_readwrite_symmetry.py"),
)
audit_rw = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(audit_rw)


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
        # set_track_enable should be covered by get_track_enabled (stem rstrip).
        src = 'return _unknown(action, ["set_track_enabled","get_track_enabled"])'
        _, _, high, _low = audit_rw.audit(src)
        self.assertEqual(high, [])


if __name__ == "__main__":
    unittest.main()
