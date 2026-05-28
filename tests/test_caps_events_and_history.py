"""Tests for v6 schema additions: caps_events table, refusal logging,
usage history rollup, day-usage reset.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest

from src.utils import analysis_caps, timeline_brain_db


class CapsEventsTable(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="caps_events_test_")
        self.project_root = os.path.join(self.tmp, "project")
        os.makedirs(self.project_root, exist_ok=True)

    def tearDown(self) -> None:
        timeline_brain_db.reset_for_test(self.project_root)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_v6_table_created_on_fresh_db(self) -> None:
        conn = timeline_brain_db.connect(self.project_root)
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='caps_events'"
        ).fetchall()
        self.assertEqual(len(rows), 1)

    def test_log_caps_event_persists(self) -> None:
        result = analysis_caps.log_caps_event(
            project_root=self.project_root,
            event_type="refusal",
            reason="over_clip_cap",
            preset="standard",
            estimated_vision_tokens=5000,
            current_usage={"clip_vision_tokens": 4500},
            cap={"clip": 5000},
            headroom={"clip": 500},
            clip_id="c1",
            job_id="j1",
        )
        self.assertTrue(result["success"])
        self.assertIsNotNone(result["row_id"])

    def test_get_caps_events_filters_by_type(self) -> None:
        for et in ("refusal", "refusal", "timeout"):
            analysis_caps.log_caps_event(
                project_root=self.project_root, event_type=et,
                reason="x", clip_id="c1",
            )
        refusals = analysis_caps.get_caps_events(
            project_root=self.project_root, event_type="refusal",
        )
        self.assertEqual(len(refusals), 2)
        self.assertTrue(all(e["event_type"] == "refusal" for e in refusals))

    def test_get_caps_events_returns_newest_first(self) -> None:
        for reason in ("first", "second", "third"):
            analysis_caps.log_caps_event(
                project_root=self.project_root, event_type="refusal", reason=reason,
            )
        events = analysis_caps.get_caps_events(project_root=self.project_root)
        self.assertEqual([e["reason"] for e in events], ["third", "second", "first"])


class UsageHistoryRollup(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="caps_history_test_")
        self.project_root = os.path.join(self.tmp, "project")
        os.makedirs(self.project_root, exist_ok=True)

    def tearDown(self) -> None:
        timeline_brain_db.reset_for_test(self.project_root)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _seed_day(self, day_bucket: str, vision_tokens: int) -> None:
        """Insert a day-scope row with a synthetic day_bucket."""
        with timeline_brain_db.transaction(self.project_root) as txn:
            txn.execute(
                """
                INSERT INTO analysis_token_usage(
                    scope, scope_key, vision_tokens, occurred_at, day_bucket
                ) VALUES ('day', NULL, ?, ?, ?)
                """,
                (vision_tokens, f"{day_bucket}T00:00:00Z", day_bucket),
            )

    def test_get_usage_history_aggregates_per_day(self) -> None:
        self._seed_day("2026-05-25", 1000)
        self._seed_day("2026-05-25", 500)  # same day → sum
        self._seed_day("2026-05-26", 2000)
        rows = analysis_caps.get_usage_history(project_root=self.project_root, days=30)
        # Newest first.
        by_day = {r["day_bucket"]: r["vision_tokens"] for r in rows}
        self.assertEqual(by_day["2026-05-25"], 1500)
        self.assertEqual(by_day["2026-05-26"], 2000)


class ResetDayUsage(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="caps_reset_test_")
        self.project_root = os.path.join(self.tmp, "project")
        os.makedirs(self.project_root, exist_ok=True)

    def tearDown(self) -> None:
        timeline_brain_db.reset_for_test(self.project_root)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reset_day_removes_today_rows_only(self) -> None:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        # Today: should be deleted.
        analysis_caps.record_usage(
            project_root=self.project_root, scope="day", scope_key=None, vision_tokens=1000,
        )
        # Different day: should be preserved.
        with timeline_brain_db.transaction(self.project_root) as txn:
            txn.execute(
                """
                INSERT INTO analysis_token_usage(scope, scope_key, vision_tokens, occurred_at, day_bucket)
                VALUES ('day', NULL, 500, '2026-05-25T00:00:00Z', '2026-05-25')
                """,
            )
        # Per-clip row: should also be preserved.
        analysis_caps.record_usage(
            project_root=self.project_root, scope="clip", scope_key="c1", vision_tokens=200,
        )

        result = analysis_caps.reset_day_usage(project_root=self.project_root)
        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["deleted"], 1)

        # Confirm yesterday's day row + the clip row survived.
        conn = timeline_brain_db.connect(self.project_root)
        rows = conn.execute("SELECT scope, day_bucket FROM analysis_token_usage").fetchall()
        scopes = {(r["scope"], r["day_bucket"]) for r in rows}
        self.assertIn(("clip", time.strftime("%Y-%m-%d", time.gmtime())), scopes)  # today's clip row
        # 2026-05-25 day row preserved (assuming we ran today != 2026-05-25; if it IS today the test is still fine because we delete today's)
        if today != "2026-05-25":
            self.assertIn(("day", "2026-05-25"), scopes)


if __name__ == "__main__":
    unittest.main()
