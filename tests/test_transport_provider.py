"""The external transport provider hook: fail closed when unset, pass the provider's own verdict through."""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

from src.utils import playback_guard, transport_provider as tp


def _write_provider(folder: str, body: str) -> str:
    path = os.path.join(folder, "provider.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write("#!" + sys.executable + "\nimport json, sys\nargs = sys.argv[1:]\n" + body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


class TransportProviderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def env(self, value):
        return mock.patch.dict(os.environ, {tp.ENV: value})

    def test_unset_and_empty_are_missing(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(tp.ENV, None)
            self.assertFalse(tp.available())
            self.assertEqual(tp.status()["code"], "PROVIDER_MISSING")
        with self.env("   "):
            self.assertFalse(tp.available())

    def test_nonexistent_path_is_missing(self):
        with self.env(os.path.join(self.tmp.name, "nope")):
            self.assertEqual(tp.status()["code"], "PROVIDER_MISSING")

    def test_bad_json_argv_is_missing(self):
        with self.env("[1, 2]"):
            self.assertEqual(tp.press("stop")["code"], "PROVIDER_MISSING")

    def test_unknown_action_refused_before_running(self):
        with self.env("/bin/false"):
            self.assertEqual(tp.press("rm -rf")["code"], "INVALID_ACTION")

    def test_status_passthrough(self):
        prov = _write_provider(self.tmp.name, 'print(json.dumps({"state": "paused", "verified": True, "args": args}))\n')
        with self.env(prov):
            out = tp.status()
        self.assertEqual(out["state"], "paused")
        self.assertEqual(out["args"], ["status"])

    def test_failed_verdict_is_not_upgraded(self):
        prov = _write_provider(self.tmp.name, 'print(json.dumps({"verdict": "failed", "why": "no motion"}))\nsys.exit(1)\n')
        with self.env(prov):
            out = tp.press("forward")
        self.assertEqual(out["verdict"], "failed")
        self.assertEqual(out["providerExit"], 1)

    def test_no_json_is_failure(self):
        prov = _write_provider(self.tmp.name, 'print("hello")\n')
        with self.env(prov):
            self.assertEqual(tp.status()["code"], "PROVIDER_FAILED")

    def test_capture_ok_without_file_is_downgraded(self):
        prov = _write_provider(self.tmp.name, 'print(json.dumps({"ok": True, "path": args[1]}))\n')
        with self.env(prov):
            out = tp.capture(os.path.join(self.tmp.name, "f.jpg"), "live")
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "PROVIDER_FAILED")

    def test_capture_ok_with_file(self):
        prov = _write_provider(
            self.tmp.name, 'open(args[1], "wb").write(b"x")\nprint(json.dumps({"ok": True, "path": args[1], "timelineFrame": 7}))\n')
        with self.env(prov):
            out = tp.capture(os.path.join(self.tmp.name, "f.jpg"), "live")
        self.assertTrue(out["ok"])
        self.assertEqual(out["timelineFrame"], 7)

    def test_pause_mode_passes_pause_ok(self):
        prov = _write_provider(
            self.tmp.name, 'open(args[1], "wb").write(b"x")\nprint(json.dumps({"ok": True, "path": args[1], "args": args}))\n')
        with self.env(prov):
            out = tp.capture(os.path.join(self.tmp.name, "f.png"), "pause")
        self.assertEqual(out["args"][0], "capture-exact")
        self.assertIn("--pause-ok", out["args"])

    def test_capture_naming_another_file_is_refused(self):
        elsewhere = os.path.join(self.tmp.name, "elsewhere.jpg")
        with open(elsewhere, "wb") as f:
            f.write(b"x")
        prov = _write_provider(
            self.tmp.name, 'open(args[1], "wb").write(b"x")\n'
            'print(json.dumps({"ok": True, "path": ' + json.dumps(elsewhere) + '}))\n')
        with self.env(prov):
            out = tp.capture(os.path.join(self.tmp.name, "f.jpg"), "live")
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "PROVIDER_PATH_MISMATCH")

    def test_capture_without_path_field_uses_requested_path(self):
        prov = _write_provider(self.tmp.name, 'open(args[1], "wb").write(b"x")\nprint(json.dumps({"ok": True}))\n')
        with self.env(prov):
            self.assertTrue(tp.capture(os.path.join(self.tmp.name, "f.jpg"), "live")["ok"])

    def test_error_categories(self):
        self.assertEqual(tp.error_category("INVALID_ACTION"), "invalid_input")
        self.assertEqual(tp.error_category("PROVIDER_MISSING"), "precondition")
        self.assertEqual(tp.error_category("PROVIDER_TIMEOUT"), "api_error")

    def test_refusal_hint_only_with_provider(self):
        os.environ.pop(tp.ENV, None)
        self.assertNotIn("during_playback='live'", playback_guard.refusal_detail("x", {})["remediation"])
        prov = _write_provider(self.tmp.name, 'print("{}")\n')
        with self.env(prov):
            self.assertIn("during_playback='live'", playback_guard.refusal_detail("x", {})["remediation"])



class ServerTransportTest(unittest.TestCase):
    """The server side: refusals land before the provider runs, and errors carry the right category."""

    def setUp(self):
        from src import server
        self.server = server
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ran = os.path.join(self.tmp.name, "ran")
        prov = _write_provider(self.tmp.name, "open(%r, 'w', encoding='utf-8').write(' '.join(args))\nprint(json.dumps({'ok': False}))\n" % self.ran)
        patcher = mock.patch.dict(os.environ, {tp.ENV: prov})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_bad_max_width_refused_before_provider_runs(self):
        for bad in ("wide", -5, "0"):
            out = self.server._provider_frame_capture({"max_width": bad}, "pause")
            self.assertEqual(out["error"]["code"] if isinstance(out.get("error"), dict) else out.get("code"),
                             "INVALID_PARAM", (bad, out))
        self.assertFalse(os.path.exists(self.ran))

    def test_missing_ffmpeg_refused_before_provider_pauses(self):
        with mock.patch.object(self.server.shutil, "which", return_value=None):
            out = self.server._provider_frame_capture({}, "pause")
        self.assertIn("FFMPEG_MISSING", json.dumps(out))
        self.assertFalse(os.path.exists(self.ran))

    def test_invalid_press_action_is_invalid_input(self):
        out = self.server.resolve_control("transport_press", {"transport_action": "eject"})
        text = json.dumps(out)
        self.assertIn("INVALID_ACTION", text)
        self.assertIn("invalid_input", text)
        self.assertFalse(os.path.exists(self.ran))


if __name__ == "__main__":
    unittest.main()
