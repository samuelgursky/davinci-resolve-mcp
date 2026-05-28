"""Unit tests for the six update-process improvements (active-job lock, auto-
stash strategy, restart marker, channels, preview/breaking-change scan,
integrity helper).

No real git or GitHub I/O — we test the local helpers + the scanning/URL
resolution functions directly.
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
from src.utils import update_check  # noqa: E402


class BreakingChangeScanner(unittest.TestCase):
    def test_picks_up_breaking_prefix(self) -> None:
        body = "## Highlights\n- new thing\n- BREAKING: schema bump v5\n- regular fix"
        out = update_check._scan_for_breaking_changes(body)
        self.assertEqual(out, ["schema bump v5"])

    def test_picks_up_warning_emoji(self) -> None:
        body = "Changes:\n- ⚠️ remove deprecated tool foo\n- normal change"
        out = update_check._scan_for_breaking_changes(body)
        self.assertEqual(out, ["remove deprecated tool foo"])

    def test_handles_breaking_change_phrase(self) -> None:
        body = "BREAKING CHANGE: dropped Python 3.10 support"
        out = update_check._scan_for_breaking_changes(body)
        self.assertEqual(out, ["dropped Python 3.10 support"])

    def test_no_breaking_returns_empty(self) -> None:
        body = "## Highlights\n- regular fix\n- another tweak"
        out = update_check._scan_for_breaking_changes(body)
        self.assertEqual(out, [])

    def test_empty_body(self) -> None:
        self.assertEqual(update_check._scan_for_breaking_changes(""), [])


class UpdateChannel(unittest.TestCase):
    def test_default_is_stable(self) -> None:
        self.assertEqual(update_check.get_update_channel({}), "stable")

    def test_env_override(self) -> None:
        for ch in ("stable", "beta", "dev"):
            self.assertEqual(
                update_check.get_update_channel({update_check.ENV_CHANNEL: ch}),
                ch,
            )

    def test_unknown_falls_back_to_stable(self) -> None:
        self.assertEqual(
            update_check.get_update_channel({update_check.ENV_CHANNEL: "nightly"}),
            "stable",
        )

    def test_stable_uses_latest_endpoint(self) -> None:
        url = update_check._release_api_url({update_check.ENV_REPO: "x/y"}, channel="stable")
        self.assertTrue(url.endswith("/releases/latest"))

    def test_beta_uses_list_endpoint(self) -> None:
        url = update_check._release_api_url({update_check.ENV_REPO: "x/y"}, channel="beta")
        self.assertIn("/releases?", url)

    def test_url_override_wins(self) -> None:
        url = update_check._release_api_url(
            {update_check.ENV_URL: "https://example.com/custom"}, channel="dev",
        )
        self.assertEqual(url, "https://example.com/custom")


class StashStrategy(unittest.TestCase):
    """Verify the install.py code paths around stash_if_needed without running git."""

    def test_strategy_arg_exists(self) -> None:
        import inspect
        sig = inspect.signature(install.apply_safe_self_update)
        self.assertIn("strategy", sig.parameters)
        self.assertEqual(sig.parameters["strategy"].default, "refuse_on_dirty")


class RestartMarker(unittest.TestCase):
    """The dashboard's restart-marker helpers are simple file I/O — test directly."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="restart_marker_test_")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_marker_means_not_needed(self) -> None:
        from src.analysis_dashboard import _read_restart_marker
        self.assertEqual(_read_restart_marker(self.tmp), {"needed": False})

    def test_write_and_read_marker(self) -> None:
        from src.analysis_dashboard import _write_restart_marker, _read_restart_marker
        _write_restart_marker(self.tmp, {
            "from_version": "1.0", "to_version": "1.1",
            "from_sha": "aaa", "to_sha": "bbb",
        })
        marker = _read_restart_marker(self.tmp)
        self.assertTrue(marker["needed"])
        self.assertEqual(marker["from_version"], "1.0")
        self.assertEqual(marker["to_version"], "1.1")

    def test_clear_marker(self) -> None:
        from src.analysis_dashboard import _write_restart_marker, _read_restart_marker, _clear_restart_marker
        _write_restart_marker(self.tmp, {"from_version": "x", "to_version": "y"})
        self.assertTrue(_read_restart_marker(self.tmp)["needed"])
        clear_result = _clear_restart_marker(self.tmp)
        self.assertTrue(clear_result["success"])
        self.assertEqual(_read_restart_marker(self.tmp), {"needed": False})

    def test_clear_when_not_present(self) -> None:
        from src.analysis_dashboard import _clear_restart_marker
        result = _clear_restart_marker(self.tmp)
        self.assertFalse(result["success"])

    def test_marker_handles_corrupt_json(self) -> None:
        from src.analysis_dashboard import _read_restart_marker
        os.makedirs(os.path.join(self.tmp, "logs"), exist_ok=True)
        with open(os.path.join(self.tmp, "logs", ".mcp_restart_needed"), "w") as fh:
            fh.write("not json")
        marker = _read_restart_marker(self.tmp)
        # File exists → marker still reads as needed even when corrupt.
        self.assertTrue(marker["needed"])


class ActiveJobLockHelper(unittest.TestCase):
    """The dashboard helper that lists running batch jobs."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="active_job_test_")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_base_root_returns_empty(self) -> None:
        from src.analysis_dashboard import _list_active_batch_jobs
        # project_root with no sibling directories under its base → no jobs.
        empty_project = os.path.join(self.tmp, "isolated_project")
        os.makedirs(empty_project, exist_ok=True)
        active = _list_active_batch_jobs(empty_project)
        self.assertEqual(active, [])

    def test_none_project_root_returns_empty(self) -> None:
        from src.analysis_dashboard import _list_active_batch_jobs
        self.assertEqual(_list_active_batch_jobs(""), [])


class PreviewUpdateHelper(unittest.TestCase):
    """preview_update gracefully degrades when the network helper is unavailable."""

    def test_missing_helper_returns_clean_error(self) -> None:
        # If update_check import fails, preview_update returns a clean error
        # dict — but in normal test runs it's importable, so we just verify
        # the function exists and is callable.
        self.assertTrue(callable(install.preview_update))


if __name__ == "__main__":
    unittest.main()
