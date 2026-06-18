"""Unit tests for media_pool_changes logger + hook branching (C6 hardening)."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from src.utils import destructive_hook, media_pool_changes, timeline_brain_db


class MediaPoolChanges(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="mpc_test_")
        self.project_root = os.path.join(self.tmp, "project")
        os.makedirs(self.project_root, exist_ok=True)

    def tearDown(self) -> None:
        timeline_brain_db.reset_for_test(self.project_root)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_log_and_retrieve(self) -> None:
        result = media_pool_changes.log_media_pool_change(
            project_root=self.project_root,
            analysis_run_id="run_mp1",
            action="delete_media_pool_clips",
            params={"clip_ids": ["clip_a", "clip_b"]},
            initiator="user.explicit",
        )
        self.assertTrue(result["success"])

        history = media_pool_changes.get_media_pool_change_history(project_root=self.project_root)
        self.assertEqual(len(history), 1)
        row = history[0]
        self.assertEqual(row["action"], "delete_media_pool_clips")
        self.assertIn("clip_a", row["target_id"])
        self.assertEqual(row["initiator"], "user.explicit")

    def test_filter_by_action(self) -> None:
        for action in ("delete_media_pool_clips", "replace_clip", "delete_media_pool_clips"):
            media_pool_changes.log_media_pool_change(
                project_root=self.project_root,
                analysis_run_id="run_mp",
                action=action,
            )
        only_deletes = media_pool_changes.get_media_pool_change_history(
            project_root=self.project_root, action="delete_media_pool_clips",
        )
        self.assertEqual(len(only_deletes), 2)


class HookBranchesMediaPool(unittest.TestCase):
    """Wrapper for tool_name='media_pool' should NOT archive a timeline."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="mpc_hook_test_")
        self.project_root = os.path.join(self.tmp, "project")
        os.makedirs(self.project_root, exist_ok=True)
        self.saved_provider = destructive_hook._PROVIDER

        # Synthetic provider — returns dummy project handles plus our project_root.
        class _DummyTimeline:
            def GetName(self): return "Edit"
        class _DummyProject:
            def GetCurrentTimeline(self): return _DummyTimeline()
            def GetMediaPool(self): return None  # not used in the media_pool branch
        destructive_hook.register_project_root_provider(
            lambda: (None, _DummyProject(), self.project_root, "project")
        )

    def tearDown(self) -> None:
        destructive_hook._PROVIDER = self.saved_provider
        timeline_brain_db.reset_for_test(self.project_root)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_media_pool_destructive_call_logs_change_not_archive(self) -> None:
        called: list[str] = []

        @destructive_hook.destructive_op("media_pool")
        def fake_media_pool(action: str, params=None):
            called.append(action)
            return {"success": True, "deleted": 2}

        # Use the REAL compound action string (EX2 fixed the registry, which had
        # listed the granular name delete_media_pool_clips that the compound tool
        # never dispatches). delete_clips is now confirm-token gated (EX3); pass a
        # confirm_token to simulate the confirmed call so the wrapper proceeds to
        # the media_pool change-logging branch instead of the token-issuance skip.
        result = fake_media_pool("delete_clips", {"clip_ids": ["a", "b"], "confirm_token": "x"})
        self.assertTrue(result["success"])
        self.assertEqual(called, ["delete_clips"])
        self.assertEqual(result["_versioning"]["category"], "media_pool")

        # No timeline_versions row should have been written.
        conn = timeline_brain_db.connect(self.project_root)
        tv_count = conn.execute("SELECT COUNT(*) AS c FROM timeline_versions").fetchone()
        self.assertEqual(tv_count["c"], 0)
        # But media_pool_changes should have one row.
        mpc_count = conn.execute("SELECT COUNT(*) AS c FROM media_pool_changes").fetchone()
        self.assertEqual(mpc_count["c"], 1)


if __name__ == "__main__":
    unittest.main()
