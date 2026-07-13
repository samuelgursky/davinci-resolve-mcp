"""Unit tests for the generic background-job registry and the
_run_maybe_background adapter. No Resolve connection is exercised."""
import threading
import time
import unittest

import src.server as s
from src.utils import background_jobs


def _wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class BackgroundJobsRegistryTest(unittest.TestCase):
    def test_start_returns_id_immediately_while_fn_still_running(self):
        gate = threading.Event()
        job_id = background_jobs.start_job("test.slow", lambda: gate.wait(3.0))

        self.assertIsInstance(job_id, str)
        self.assertTrue(job_id)
        # The worker is blocked on the gate, so the job is still running.
        self.assertEqual(background_jobs.job_status(job_id)["status"], "running")
        gate.set()
        self.assertTrue(_wait_for(lambda: background_jobs.job_status(job_id)["status"] == "done"))

    def test_status_transitions_running_to_done_with_result(self):
        gate = threading.Event()

        def fn():
            gate.wait(3.0)
            return {"value": 7}

        job_id = background_jobs.start_job("test.done", fn)
        self.assertEqual(background_jobs.job_status(job_id)["status"], "running")
        gate.set()
        self.assertTrue(_wait_for(lambda: background_jobs.job_status(job_id)["status"] == "done"))
        status = background_jobs.job_status(job_id)
        self.assertEqual(status["result"], {"value": 7})
        self.assertIsNone(status["error"])
        self.assertIsNotNone(status["ended_at"])

    def test_error_is_captured(self):
        def fn():
            raise ValueError("boom")

        job_id = background_jobs.start_job("test.error", fn)
        self.assertTrue(_wait_for(lambda: background_jobs.job_status(job_id)["status"] == "error"))
        status = background_jobs.job_status(job_id)
        self.assertIn("boom", status["error"])
        self.assertIn("ValueError", status["error"])
        self.assertIsNone(status["result"])

    def test_unknown_id_returns_none(self):
        self.assertIsNone(background_jobs.job_status("does-not-exist"))

    def test_runs_off_the_calling_thread(self):
        seen = {}

        def fn():
            seen["thread"] = threading.get_ident()

        job_id = background_jobs.start_job("test.thread", fn)
        self.assertTrue(_wait_for(lambda: background_jobs.job_status(job_id)["status"] == "done"))
        self.assertNotEqual(seen["thread"], threading.get_ident())

    def test_list_jobs_reports_known_jobs_compactly(self):
        job_id = background_jobs.start_job("test.list", lambda: None)
        self.assertTrue(_wait_for(lambda: background_jobs.job_status(job_id)["status"] == "done"))
        entry = next((j for j in background_jobs.list_jobs() if j["id"] == job_id), None)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["label"], "test.list")
        self.assertNotIn("result", entry)


class RunMaybeBackgroundTest(unittest.TestCase):
    def test_default_path_calls_fn_and_returns_result(self):
        called = []

        def fn():
            called.append(True)
            return {"success": True, "value": 42}

        out = s._run_maybe_background("test.sync", {}, fn)
        self.assertEqual(out, {"success": True, "value": 42})
        self.assertEqual(called, [True])

    def test_background_returns_job_id_without_calling_fn_synchronously(self):
        gate = threading.Event()
        called = []

        def fn():
            gate.wait(3.0)
            called.append(True)
            return {"success": True}

        out = s._run_maybe_background("test.bg", {"background": True}, fn)
        self.assertTrue(out["success"])
        self.assertIn("job_id", out)
        self.assertEqual(out["status"], "running")
        self.assertEqual(out["label"], "test.bg")
        self.assertEqual(called, [])  # not invoked on the calling thread
        gate.set()
        self.assertTrue(
            _wait_for(lambda: background_jobs.job_status(out["job_id"])["status"] == "done")
        )

    def test_async_job_alias_also_backgrounds(self):
        out = s._run_maybe_background("test.alias", {"async_job": True}, lambda: {"success": True})
        self.assertIn("job_id", out)
        self.assertEqual(out["status"], "running")


class ResolveControlPollingTest(unittest.TestCase):
    def test_job_status_action_returns_status_dict(self):
        job_id = background_jobs.start_job("test.control", lambda: {"ok": 1})
        self.assertTrue(_wait_for(lambda: background_jobs.job_status(job_id)["status"] == "done"))
        out = s.resolve_control("job_status", {"job_id": job_id})
        self.assertEqual(out["id"], job_id)
        self.assertEqual(out["status"], "done")
        self.assertEqual(out["result"], {"ok": 1})

    def test_job_status_unknown_id_errors(self):
        out = s.resolve_control("job_status", {"job_id": "nope"})
        self.assertIn("error", out)
        self.assertEqual(out["error"]["category"], "invalid_input")

    def test_job_status_missing_id_errors(self):
        out = s.resolve_control("job_status", {})
        self.assertIn("error", out)

    def test_list_jobs_action_returns_jobs(self):
        job_id = background_jobs.start_job("test.control_list", lambda: None)
        self.assertTrue(_wait_for(lambda: background_jobs.job_status(job_id)["status"] == "done"))
        out = s.resolve_control("list_jobs", {})
        self.assertIn("jobs", out)
        self.assertTrue(any(j["id"] == job_id for j in out["jobs"]))


if __name__ == "__main__":
    unittest.main()
