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
            self.assertEqual(json.loads(state_path.read_text())["status"], "update_available")

    def test_check_for_updates_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = update_check.check_for_updates(
                "2.20.0",
                tmp,
                env={update_check.ENV_ENABLED: "false"},
                now=1000,
            )

        self.assertEqual(result["status"], "disabled")

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


if __name__ == "__main__":
    unittest.main()
