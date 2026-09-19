"""The offline suite must not write into the repo's logs/ directory.

`test_log_isolation` covers `logs/server.log`. The server writes three more
files there by default, and the suite wrote all three. One
`python -m unittest discover -s tests -t .` from a fresh checkout left 1,865
fabricated tool-call records (672 KB) in `logs/execution-traces.jsonl`, an
audit report in `logs/execution-reports/`, and `logs/update-check.json`. In an
operator's main checkout the trace records go into the file
`list_recent_executions` points at, and nothing tells them apart from real ones.

`offline_guard` now points each default at a temp directory through the
variable the server already reads. This is the tripwire. It fails if that
redirect is missing, if an earlier test removed it, or if the traced tool-call
path stops honouring it.
"""

from __future__ import annotations

import json
import os
import unittest
import uuid
from pathlib import Path

import src.server as server
from src.utils import execution_trace, update_check
from tests import offline_guard

REPO = Path(__file__).resolve().parents[1]
REPO_LOGS = (REPO / "logs").resolve()

#: Where each redirected variable ends up being read, through the same call the
#: server makes before it writes.
RESOLVERS = {
    "RESOLVE_MCP_TRACE_FILE": execution_trace.trace_log_path,
    "RESOLVE_MCP_TRACE_REPORT_DIR": execution_trace.execution_report_dir,
    "DAVINCI_RESOLVE_MCP_UPDATE_STATE": lambda: update_check.update_state_path(
        server.project_dir, server._setup_update_env()
    ),
}


def _inside_repo_logs(path) -> bool:
    return Path(path).resolve().is_relative_to(REPO_LOGS)


class RepoLogsIsolationTests(unittest.TestCase):
    def test_the_guard_and_this_tripwire_cover_the_same_files(self) -> None:
        self.assertEqual(set(offline_guard.RUN_STATE_ENVS), set(RESOLVERS))
        self.assertIn(update_check.ENV_STATE_PATH, offline_guard.RUN_STATE_ENVS)

    def test_every_default_is_redirected_out_of_the_repo_logs(self) -> None:
        for name, resolve in RESOLVERS.items():
            with self.subTest(name):
                target = os.environ.get(name)
                self.assertTrue(
                    target,
                    f"{name} is unset: the offline guard's redirect is missing, or a "
                    "test removed it with a bare os.environ.pop instead of "
                    "mock.patch.dict",
                )
                self.assertFalse(
                    _inside_repo_logs(target), f"{name} points into the repo's logs/: {target}"
                )
                # The server reads the variable the guard sets. A misspelt name
                # would leave the server on its default, inside the repo's logs/.
                self.assertEqual(Path(resolve()).resolve(), Path(target).resolve())

    def test_a_traced_tool_call_and_its_report_stay_out_of_the_repo_logs(self) -> None:
        # A unique id, so a live server appending to the same log from this
        # checkout cannot make the check pass or fail.
        exec_id = f"exec_tripwire_{uuid.uuid4().hex}"
        server.resolve_control(
            "begin_execution", {"request": "offline suite tripwire", "execution_id": exec_id}
        )
        try:
            server.setup("get_defaults")  # an ordinary traced call
        finally:
            server.resolve_control("end_execution", {"execution_id": exec_id})
        report = server.resolve_control("export_execution_report", {"execution_id": exec_id})

        for name in ("execution-traces.jsonl", "execution-traces.jsonl.1"):
            real = REPO_LOGS / name
            if real.is_file():
                self.assertNotIn(
                    exec_id,
                    real.read_text(encoding="utf-8", errors="replace"),
                    f"the suite traced into the real {real}",
                )
        self.assertTrue(report.get("success"), report)
        self.assertFalse(
            _inside_repo_logs(report["path"]),
            f"the suite wrote an audit report into the real {report['path']}",
        )

        # And the records did land somewhere: an empty redirect would mean the
        # traced path stopped writing at all, which is its own bug.
        redirect = Path(os.environ.get("RESOLVE_MCP_TRACE_FILE") or os.devnull)
        events = {
            json.loads(line)["event"]
            for line in redirect.read_text(encoding="utf-8").splitlines()
            if exec_id in line
        }
        self.assertLessEqual({"begin", "step", "end"}, events, "the trace missed the redirect")


if __name__ == "__main__":
    unittest.main()
