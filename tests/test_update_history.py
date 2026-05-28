"""Unit tests for install.py update history + rollback helpers.

No git operations performed — we test the JSON-recorder helpers directly.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
import install  # noqa: E402


class UpdateHistoryRecording(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="update_history_test_")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _history_path(self) -> str:
        return os.path.join(self.tmp, "logs", "update_history.json")

    def test_record_attempt_creates_file(self) -> None:
        install._record_attempt(
            self.tmp, kind="update", success=True,
            from_version="1.0", to_version="1.1",
            from_sha="aaa", to_sha="bbb", initiator="test",
        )
        path = self._history_path()
        self.assertTrue(os.path.isfile(path))
        with open(path, "r") as fh:
            payload = json.load(fh)
        self.assertEqual(len(payload["entries"]), 1)
        entry = payload["entries"][0]
        self.assertEqual(entry["from_version"], "1.0")
        self.assertEqual(entry["to_version"], "1.1")
        self.assertTrue(entry["success"])
        self.assertEqual(entry["initiator"], "test")

    def test_read_update_history_returns_newest_first(self) -> None:
        for i in range(3):
            install._record_attempt(
                self.tmp, kind="update", success=True,
                from_version=f"1.{i}", to_version=f"1.{i+1}",
                from_sha=f"sha{i}", to_sha=f"sha{i+1}", initiator="test",
            )
        result = install.read_update_history(self.tmp, limit=10)
        self.assertTrue(result["success"])
        self.assertEqual(len(result["entries"]), 3)
        # newest first → 1.3 / 1.2 / 1.1
        self.assertEqual(result["entries"][0]["to_version"], "1.3")
        self.assertEqual(result["entries"][2]["to_version"], "1.1")

    def test_history_trims_at_200_entries(self) -> None:
        for i in range(220):
            install._record_attempt(
                self.tmp, kind="update", success=True,
                from_version="x", to_version=str(i), initiator="test",
            )
        with open(self._history_path(), "r") as fh:
            payload = json.load(fh)
        self.assertEqual(len(payload["entries"]), 200)
        # Oldest should be entry 20 (220 - 200), newest 219
        self.assertEqual(payload["entries"][0]["to_version"], "20")
        self.assertEqual(payload["entries"][-1]["to_version"], "219")

    def test_history_survives_corrupt_file(self) -> None:
        os.makedirs(os.path.join(self.tmp, "logs"), exist_ok=True)
        with open(self._history_path(), "w") as fh:
            fh.write("{not json")
        # Should not crash; corrupted file is replaced with a fresh history.
        install._record_attempt(
            self.tmp, kind="update", success=True,
            from_version="x", to_version="y", initiator="test",
        )
        with open(self._history_path(), "r") as fh:
            payload = json.load(fh)
        self.assertEqual(len(payload["entries"]), 1)

    def test_read_handles_missing_file(self) -> None:
        result = install.read_update_history(self.tmp)
        self.assertTrue(result["success"])
        self.assertEqual(result["entries"], [])


class RollbackContractGuards(unittest.TestCase):
    """Verify rollback's pre-conditions surface clean error reasons."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="rollback_test_")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_history_returns_clear_reason(self) -> None:
        result = install.rollback_to_previous_build(self.tmp)
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "no_history")

    def test_no_successful_update_in_history(self) -> None:
        # Record only failed attempts.
        install._record_attempt(self.tmp, kind="update", success=False, reason="local_changes")
        result = install.rollback_to_previous_build(self.tmp)
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "no_target")


if __name__ == "__main__":
    unittest.main()
