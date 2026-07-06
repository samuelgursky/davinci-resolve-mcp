"""Issue #84: execute_tighten's structural_diff must not embed every item id.

`_compact_structural_diff` trims a compare_usage_snapshots result to counts + a
small sample for the default response; the full diff is persisted in the plan
record and returned inline only when include_details=true.
"""
import unittest

import src.server as s


def _row(i: int) -> dict:
    return {
        "media_pool_item_id": f"mpi-{i:04d}",
        "track_type": "video",
        "track_index": 1,
        "in_frame": i * 100,
        "out_frame": i * 100 + 90,
    }


def _diff(n_added: int, n_trimmed: int = 0) -> dict:
    added = [_row(i) for i in range(n_added)]
    trimmed = [dict(_row(1000 + i), out_frame_before=i) for i in range(n_trimmed)]
    return {
        "added": added,
        "removed": [],
        "moved": [],
        "trimmed": trimmed,
        "summary": {
            "added": n_added, "removed": 0, "moved": 0, "trimmed": n_trimmed,
            "before_clip_count": 87, "after_clip_count": n_added,
        },
    }


class CompactStructuralDiffTest(unittest.TestCase):
    def test_large_diff_is_trimmed_to_summary_and_sample(self) -> None:
        diff = _diff(130)
        out = s._compact_structural_diff(diff)
        self.assertTrue(out["truncated"])
        # Counts are preserved verbatim.
        self.assertEqual(out["summary"]["added"], 130)
        # Only a small sample of rows survives (default sample_n=3 → 3 rows).
        self.assertEqual(len(out["sample"]["added"]), 3)
        self.assertEqual(out["omitted_rows"], 127)
        # The sample keeps both ends: head rows plus the final row.
        self.assertEqual(out["sample"]["added"][-1]["media_pool_item_id"], "mpi-0129")
        self.assertIn("include_details", out["detail_hint"])
        # The compact form is dramatically smaller than the full diff.
        self.assertLess(len(repr(out)), len(repr(diff)))

    def test_small_diff_passes_rows_through(self) -> None:
        diff = _diff(2, n_trimmed=1)
        out = s._compact_structural_diff(diff)
        self.assertEqual(len(out["sample"]["added"]), 2)  # <= sample_n → all kept
        self.assertEqual(len(out["sample"]["trimmed"]), 1)
        self.assertEqual(out["omitted_rows"], 0)

    def test_error_standin_passes_through(self) -> None:
        # A diff that failed to compute has no `summary` — return it untouched so
        # the caller still sees the error.
        err = {"error": "ValueError: boom"}
        self.assertEqual(s._compact_structural_diff(err), err)

    def test_non_dict_passes_through(self) -> None:
        self.assertIsNone(s._compact_structural_diff(None))


if __name__ == "__main__":
    unittest.main()
