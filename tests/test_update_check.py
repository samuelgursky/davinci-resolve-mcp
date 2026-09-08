import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils import update_check


class _FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._payload


class UpdateCheckTests(unittest.TestCase):
    def setUp(self):
        # The module keeps the last result in a process-wide cache, and several
        # tests below seed or populate it. Reset around every test so a cached
        # "update_available" from one test cannot leak into another module's
        # get_cached_update_status call later in the same run.
        self._reset_cached_status()
        self.addCleanup(self._reset_cached_status)

    @staticmethod
    def _reset_cached_status():
        with update_check._cached_lock:
            update_check._cached_status.clear()
            update_check._cached_status.update({"status": "unknown"})

    def test_compare_versions_handles_release_tags(self):
        self.assertEqual(update_check.compare_versions("2.20.0", "v2.21.0"), -1)
        self.assertEqual(update_check.compare_versions("2.20", "2.20.0"), 0)
        self.assertEqual(update_check.compare_versions("2.21.0", "v2.20.0"), 1)
        self.assertIsNone(update_check.compare_versions("dev", "v2.20.0"))

    def test_check_for_updates_detects_new_release_and_caches(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "update.json"
            env = {
                update_check.ENV_URL: "https://example.test/latest",
                update_check.ENV_STATE_PATH: str(state_path),
            }
            payload = {
                "tag_name": "v2.21.0",
                "html_url": "https://github.com/example/releases/tag/v2.21.0",
            }

            with patch.object(
                update_check.urllib.request,
                "urlopen",
                return_value=_FakeResponse(payload),
            ) as urlopen:
                result = update_check.check_for_updates(
                    "2.20.0",
                    tmp,
                    env=env,
                    now=1000,
                )
                cached = update_check.check_for_updates(
                    "2.20.0",
                    tmp,
                    env=env,
                    now=1001,
                )

            self.assertEqual(result["status"], "update_available")
            self.assertEqual(result["latest_version"], "2.21.0")
            self.assertEqual(cached["status"], "update_available")
            self.assertTrue(cached["cached"])
            self.assertEqual(urlopen.call_count, 1)
            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8"))["status"], "update_available")

    def test_check_for_updates_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "update.json"
            result = update_check.check_for_updates(
                "2.20.0",
                tmp,
                env={
                    update_check.ENV_ENABLED: "false",
                    update_check.ENV_STATE_PATH: str(state_path),
                },
                now=1000,
            )

            self.assertEqual(result["status"], "disabled")
            self.assertFalse(state_path.exists())

    def test_persisted_never_mode_disables_update_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "update.json"
            env = {update_check.ENV_STATE_PATH: str(state_path)}
            update_check.set_update_mode(tmp, "never", env=env, now=1000)

            result = update_check.check_for_updates(
                "2.20.0",
                tmp,
                env=env,
                now=1001,
            )

            self.assertEqual(result["status"], "disabled")
            self.assertEqual(result["update_mode"], "never")
            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8"))["update_mode"], "never")

    def test_update_prompt_decision_respects_ignore_snooze_and_auto(self):
        base = {
            "status": "update_available",
            "current_version": "2.20.0",
            "latest_version": "2.21.0",
            "latest_tag": "v2.21.0",
            "update_mode": "prompt",
        }

        self.assertEqual(update_check.update_prompt_decision(base, now=1000)["action"], "prompt")
        self.assertEqual(
            update_check.update_prompt_decision(
                {**base, "ignored_version": "2.21.0"},
                now=1000,
            )["reason"],
            "ignored",
        )
        self.assertEqual(
            update_check.update_prompt_decision(
                {**base, "snooze_until": 2000},
                now=1000,
            )["reason"],
            "snoozed",
        )
        self.assertEqual(
            update_check.update_prompt_decision({**base, "update_mode": "auto"}, now=1000)["action"],
            "auto",
        )

    def test_network_error_preserves_last_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "update.json"
            env = {update_check.ENV_STATE_PATH: str(state_path)}
            state_path.write_text(
                json.dumps(
                    {
                        "status": "up_to_date",
                        "current_version": "2.20.0",
                        "latest_version": "2.20.0",
                        "latest_tag": "v2.20.0",
                        "release_url": "https://github.com/example/releases/tag/v2.20.0",
                        "checked_at": 1000,
                        "checked_at_iso": "1970-01-01T00:16:40Z",
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(
                update_check.urllib.request,
                "urlopen",
                side_effect=OSError("offline"),
            ):
                result = update_check.check_for_updates(
                    "2.20.0",
                    tmp,
                    env=env,
                    now=100000,
                )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["last_success"]["status"], "up_to_date")

    def test_cached_release_is_reclassified_for_newer_running_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "update.json"
            state_path.write_text(
                json.dumps(
                    {
                        "status": "update_available",
                        "current_version": "2.135.0",
                        "latest_version": "2.210.0",
                        "latest_tag": "v2.210.0",
                        "checked_at": 1000,
                        "update_mode": "prompt",
                    }
                ),
                encoding="utf-8",
            )
            env = {update_check.ENV_STATE_PATH: str(state_path)}
            with update_check._cached_lock:
                update_check._cached_status.clear()
                update_check._cached_status.update({"status": "unknown"})

            result = update_check.get_cached_update_status(tmp, "2.212.1", env=env)

            self.assertEqual(result["current_version"], "2.212.1")
            self.assertEqual(result["status"], "current_ahead")
            self.assertEqual(
                update_check.update_prompt_decision(result, env=env)["action"],
                "none",
            )

    def test_throttled_check_reclassifies_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "update.json"
            state_path.write_text(
                json.dumps(
                    {
                        "status": "update_available",
                        "current_version": "2.135.0",
                        "latest_version": "2.210.0",
                        "latest_tag": "v2.210.0",
                        "checked_at": 1000,
                        "update_mode": "prompt",
                    }
                ),
                encoding="utf-8",
            )
            env = {
                update_check.ENV_STATE_PATH: str(state_path),
                update_check.ENV_INTERVAL_HOURS: "24",
            }

            result = update_check.check_for_updates(
                "2.212.1", tmp, env=env, now=1001, force=False
            )

            self.assertTrue(result["cached"])
            self.assertEqual(result["current_version"], "2.212.1")
            self.assertEqual(result["status"], "current_ahead")
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["status"], "current_ahead")
            self.assertEqual(persisted["current_version"], "2.212.1")

    def test_in_memory_cached_release_is_reclassified(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {update_check.ENV_STATE_PATH: str(Path(tmp) / "missing.json")}
            with update_check._cached_lock:
                update_check._cached_status.clear()
                update_check._cached_status.update(
                    {
                        "status": "update_available",
                        "current_version": "2.135.0",
                        "latest_version": "2.210.0",
                        "latest_tag": "v2.210.0",
                    }
                )

            result = update_check.get_cached_update_status(tmp, "2.212.1", env=env)

            self.assertEqual(result["status"], "current_ahead")
            self.assertEqual(result["current_version"], "2.212.1")

    def test_error_and_disabled_cached_statuses_are_preserved(self):
        for status in ("error", "disabled"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                state_path = Path(tmp) / "update.json"
                original = {
                    "status": status,
                    "current_version": "2.135.0",
                    "latest_version": "2.210.0",
                    "error": "offline" if status == "error" else None,
                }
                state_path.write_text(json.dumps(original), encoding="utf-8")
                env = {update_check.ENV_STATE_PATH: str(state_path)}
                with update_check._cached_lock:
                    update_check._cached_status.clear()
                    update_check._cached_status.update({"status": "unknown"})

                result = update_check.get_cached_update_status(tmp, "2.212.1", env=env)

                self.assertEqual(result["status"], status)
                self.assertEqual(result["current_version"], "2.135.0")
                self.assertEqual(result.get("error"), original["error"])


if __name__ == "__main__":
    unittest.main()
