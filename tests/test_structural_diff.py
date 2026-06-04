"""Unit tests for the reusable structural diff engine (Phase A)."""
import unittest

from src.utils import structural_diff as sd


class StructuralDiffTest(unittest.TestCase):
    def test_identical_is_empty(self):
        a = {"x": 1, "list": [{"id": 1, "v": "a"}]}
        diff = sd.compare(a, dict(a, list=[{"id": 1, "v": "a"}]))
        self.assertTrue(diff.is_empty())
        self.assertEqual(diff.summary()["total"], 0)

    def test_scalar_change(self):
        diff = sd.compare({"fps": 24}, {"fps": 25})
        self.assertEqual(diff.summary(), {"added": 0, "removed": 0, "changed": 1, "total": 1})
        self.assertEqual(diff.changed()[0].before, 24)
        self.assertEqual(diff.changed()[0].after, 25)
        self.assertEqual(diff.changed()[0].path, "fps")

    def test_added_and_removed_keys(self):
        diff = sd.compare({"a": 1}, {"b": 2})
        ops = {c.op for c in diff.changes}
        self.assertEqual(ops, {"added", "removed"})

    def test_list_keyed_alignment_detects_reorder_as_no_change(self):
        # Same elements, different order, keyed by media_pool_item_id → no change.
        left = [{"media_pool_item_id": "A", "v": 1}, {"media_pool_item_id": "B", "v": 2}]
        right = [{"media_pool_item_id": "B", "v": 2}, {"media_pool_item_id": "A", "v": 1}]
        diff = sd.compare({"clips": left}, {"clips": right})
        self.assertTrue(diff.is_empty(), diff.to_dict())

    def test_list_keyed_alignment_detects_field_change(self):
        left = [{"id": "A", "grade": "x"}]
        right = [{"id": "A", "grade": "y"}]
        diff = sd.compare({"clips": left}, {"clips": right})
        self.assertEqual(diff.summary()["changed"], 1)
        self.assertIn("[id=A]", diff.changed()[0].path)

    def test_list_keyed_add_remove(self):
        left = [{"id": "A"}]
        right = [{"id": "A"}, {"id": "B"}]
        diff = sd.compare(left, right)
        self.assertEqual(diff.summary()["added"], 1)
        self.assertEqual(diff.added()[0].after, {"id": "B"})

    def test_positional_fallback_when_no_shared_key(self):
        diff = sd.compare([1, 2, 3], [1, 9, 3])
        self.assertEqual(diff.summary()["changed"], 1)
        self.assertEqual(diff.changed()[0].path, "[1]")

    def test_clip_hash_takes_precedence_over_name(self):
        # Renamed clip (same hash) is a change, not delete+add.
        left = [{"clip_hash": "h1", "name": "old"}]
        right = [{"clip_hash": "h1", "name": "new"}]
        diff = sd.compare(left, right)
        self.assertEqual(diff.summary()["changed"], 1)
        self.assertIn("[clip_hash=h1]", diff.changed()[0].path)

    def test_to_dict_shape(self):
        d = sd.compare({"a": 1}, {"a": 2}).to_dict()
        self.assertEqual(set(d), {"left_label", "right_label", "summary", "changes"})
        self.assertEqual(d["changes"][0]["op"], "changed")


if __name__ == "__main__":
    unittest.main()
