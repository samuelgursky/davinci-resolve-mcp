"""The offline suite must not write into the operator's logs/server.log.

Importing src.server attaches the root logger's FileHandler. The suite imports
src.server, so until v2.214.4 every MagicMock "connection" and lifecycle
warning the tests provoked was appended to the real server log — the file a
live debugging session reads. `tests/__init__.py` now points RESOLVE_MCP_LOG_FILE
at a temporary file before any test module runs; this test is the tripwire
that fails if that redirect stops happening, or if the server grows a second
handler that ignores it.
"""

from __future__ import annotations

import logging
import os
import unittest
from pathlib import Path

import src.server as server

REPO = Path(__file__).resolve().parents[1]
REAL_LOG = (REPO / "logs" / "server.log").resolve()


def _file_handlers(*loggers):
    for lg in loggers:
        for handler in lg.handlers:
            if isinstance(handler, logging.FileHandler):
                yield Path(handler.baseFilename).resolve()


class LogIsolationTests(unittest.TestCase):
    def test_the_suite_redirects_the_log_before_the_server_is_imported(self) -> None:
        target = os.environ.get(server.ENV_LOG_FILE)
        self.assertTrue(target, "tests/__init__.py did not set RESOLVE_MCP_LOG_FILE")
        self.assertNotEqual(Path(target).resolve(), REAL_LOG)

    def test_no_handler_targets_the_real_server_log(self) -> None:
        targets = list(_file_handlers(logging.getLogger(), logging.getLogger("resolve-mcp")))
        self.assertNotIn(REAL_LOG, targets,
                         "a handler on the root or resolve-mcp logger writes to logs/server.log "
                         "during the offline suite")

    def test_unset_means_the_real_server_log(self) -> None:
        """The live server's behaviour is unchanged: no variable, same file."""
        self.assertEqual(Path(server._log_file_from_env({})).resolve(), REAL_LOG)

    def test_a_path_is_honoured_and_empty_means_no_file(self) -> None:
        self.assertEqual(server._log_file_from_env({server.ENV_LOG_FILE: "/tmp/x/y.log"}),
                         "/tmp/x/y.log")
        self.assertEqual(server._log_file_from_env({server.ENV_LOG_FILE: ""}), "")
        self.assertEqual(server._log_file_from_env({server.ENV_LOG_FILE: "  "}), "")


if __name__ == "__main__":
    unittest.main()
