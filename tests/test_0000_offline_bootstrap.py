"""Install the offline bootstrap on the one runner that skips `tests/__init__.py`.

`tests/__init__.py` sets `RESOLVE_MCP_LOG_FILE` and installs `offline_guard`
before any test module loads, and that holds for `python -m unittest
tests.test_x` (a dotted name imports its parent package first) and for pytest
(via `conftest.py`). It does **not** hold for `python -m unittest discover -s
tests`: `discover` given a *path* leaves `top_level_dir` at that path, inserts
`tests/` on `sys.path`, and imports every module under its bare name —
`test_clip_colors`, not `tests.test_clip_colors` — so the package `__init__` is
never executed. Measured on this repo: the first module to `import src.server`
attached the root logger's FileHandler to the operator's real `logs/server.log`
(1.8 MB of suite output in one run), the guard was absent for the whole run, and
the suite reached for a live Resolve. `tests/test_log_isolation.py` is the
tripwire that caught it.

Discovery imports modules in `sorted(os.listdir(...))` order, so a module whose
name sorts before every other `test_*.py` runs first — digits sort before
letters and underscores. Importing the `tests` package here is the whole fix;
everything else in this file is the assertion that it worked, plus a guard on
the ordering this trick depends on.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# The import itself is the bootstrap: `tests/__init__.py` redirects the log file
# and installs the guard. Idempotent, so the runners that already imported it
# pay nothing here.
import tests  # noqa: E402,F401 - imported for its side effects
from tests import offline_guard  # noqa: E402

THIS_MODULE = Path(__file__).name


class OfflineBootstrapTests(unittest.TestCase):
    def test_the_log_file_is_redirected(self) -> None:
        target = os.environ.get("RESOLVE_MCP_LOG_FILE")
        self.assertTrue(target, "tests/__init__.py did not set RESOLVE_MCP_LOG_FILE")
        self.assertNotEqual(
            Path(target).resolve(), (REPO_ROOT / "logs" / "server.log").resolve()
        )

    def test_the_offline_guard_is_installed(self) -> None:
        if offline_guard.SKIPPED_REASON:
            self.skipTest(offline_guard.SKIPPED_REASON)
        server = sys.modules.get("src.server")
        self.assertIsNotNone(server, "the bootstrap did not import src.server")
        self.assertTrue(
            getattr(server, "_offline_guard_installed", False),
            "offline_guard.install() did not run before the test modules loaded",
        )

    def test_blackmagics_module_and_the_granular_server_are_guarded(self) -> None:
        if offline_guard.SKIPPED_REASON:
            self.skipTest(offline_guard.SKIPPED_REASON)
        self.assertTrue(
            offline_guard.scripting_stub_installed(),
            "no finder is answering `import DaVinciResolveScript` with the stub",
        )
        # `src.server` imports the module at import time, so this also shows the
        # finder went in before the server was imported, not after.
        self.assertTrue(offline_guard.is_scripting_stub(sys.modules["src.server"].dvr_script))
        if offline_guard.GRANULAR_SKIPPED_REASON:
            self.skipTest(offline_guard.GRANULAR_SKIPPED_REASON)
        common = sys.modules.get("src.granular.common")
        self.assertIsNotNone(common, "the bootstrap did not import src.granular.common")
        self.assertTrue(getattr(common, "_offline_guard_installed", False))

    def test_this_module_still_sorts_first(self) -> None:
        """The bootstrap only runs first while its name sorts first.

        `unittest discover` imports `sorted(os.listdir(start_dir))`. A new
        `test_*.py` sorting ahead of this one would import `src.server` before
        the redirect and silently restore the bug.
        """
        modules = sorted(
            p.name for p in Path(__file__).parent.glob("test_*.py")
        )
        self.assertEqual(
            modules[0],
            THIS_MODULE,
            f"{modules[0]} now loads before the offline bootstrap; rename it or "
            "rename the bootstrap so the bootstrap sorts first",
        )


if __name__ == "__main__":
    unittest.main()
