"""Tests for the long-Resolve-operation busy gate (src/utils/resolve_busy.py)."""
from __future__ import annotations

import json
import os
import threading
import time
import unittest
from unittest import mock

from src.utils import resolve_busy


class _SidecarIsolation(unittest.TestCase):
    def setUp(self):
        self._patcher = mock.patch.object(
            resolve_busy, "_SIDECAR",
            os.path.join(os.path.dirname(resolve_busy._SIDECAR), f"busy-test-{os.getpid()}-{id(self)}.json"),
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.addCleanup(self._cleanup_sidecar)

    def _cleanup_sidecar(self):
        try:
            os.remove(resolve_busy._SIDECAR)
        except OSError:
            pass


class LongResolveOpTest(_SidecarIsolation):
    def test_free_when_nothing_registered(self):
        self.assertIsNone(resolve_busy.current_long_op())
        self.assertIsNone(resolve_busy.wait_until_free(timeout_seconds=0))

    def test_registration_visible_and_cleared(self):
        with resolve_busy.long_resolve_op("timeline.export"):
            op = resolve_busy.current_long_op()
            self.assertEqual(op["label"], "timeline.export")
            self.assertTrue(op["same_process"])
            self.assertGreaterEqual(op["age_seconds"], 0)
        self.assertIsNone(resolve_busy.current_long_op())

    def test_owner_thread_is_not_gated_by_its_own_op(self):
        with resolve_busy.long_resolve_op("timeline.export"):
            self.assertIsNone(resolve_busy.wait_until_free(timeout_seconds=0))

    def test_other_thread_gets_busy_info_after_timeout(self):
        release = threading.Event()
        registered = threading.Event()

        def hold():
            with resolve_busy.long_resolve_op("timeline_ai.detect_scene_cuts"):
                registered.set()
                release.wait(timeout=10)

        worker = threading.Thread(target=hold, daemon=True)
        worker.start()
        self.assertTrue(registered.wait(timeout=5))
        try:
            op = resolve_busy.wait_until_free(timeout_seconds=0)
            self.assertIsNotNone(op)
            self.assertEqual(op["label"], "timeline_ai.detect_scene_cuts")
        finally:
            release.set()
            worker.join(timeout=5)
        self.assertIsNone(resolve_busy.wait_until_free(timeout_seconds=2))

    def test_wait_returns_none_once_op_finishes_within_timeout(self):
        release = threading.Event()
        registered = threading.Event()

        def hold():
            with resolve_busy.long_resolve_op("timeline.export"):
                registered.set()
                release.wait(timeout=10)

        worker = threading.Thread(target=hold, daemon=True)
        worker.start()
        self.assertTrue(registered.wait(timeout=5))
        threading.Timer(0.4, release.set).start()
        self.assertIsNone(resolve_busy.wait_until_free(timeout_seconds=5))
        worker.join(timeout=5)

    def test_dead_pid_record_is_ignored(self):
        with open(resolve_busy._SIDECAR, "w", encoding="utf-8") as handle:
            json.dump({"label": "crashed.op", "pid": 2 ** 22 + 12345, "thread": 1, "started_at": time.time()}, handle)
        self.assertIsNone(resolve_busy.current_long_op())

    def test_stale_record_is_ignored(self):
        with open(resolve_busy._SIDECAR, "w", encoding="utf-8") as handle:
            json.dump({
                "label": "leaked.op", "pid": os.getpid(), "thread": 1,
                "started_at": time.time() - resolve_busy.MAX_OP_AGE_SECONDS - 10,
            }, handle)
        self.assertIsNone(resolve_busy.current_long_op())

    def test_corrupt_sidecar_is_ignored(self):
        with open(resolve_busy._SIDECAR, "w", encoding="utf-8") as handle:
            handle.write('{"trunc')
        self.assertIsNone(resolve_busy.current_long_op())


class CheckBusyGateTest(_SidecarIsolation):
    def test_check_returns_structured_busy_error_from_other_thread_op(self):
        import src.server as compound

        release = threading.Event()
        registered = threading.Event()

        def hold():
            with resolve_busy.long_resolve_op("timeline.export"):
                registered.set()
                release.wait(timeout=10)

        worker = threading.Thread(target=hold, daemon=True)
        worker.start()
        self.assertTrue(registered.wait(timeout=5))
        try:
            with mock.patch.object(resolve_busy, "DEFAULT_WAIT_SECONDS", 0):
                pm, proj, err = compound._check()
        finally:
            release.set()
            worker.join(timeout=5)

        self.assertIsNone(pm)
        self.assertIsNone(proj)
        envelope = err["error"] if isinstance(err.get("error"), dict) else err
        self.assertEqual(envelope.get("code"), "RESOLVE_BUSY")
        self.assertEqual(envelope.get("state", {}).get("busy_with"), "timeline.export")


if __name__ == "__main__":
    unittest.main()
