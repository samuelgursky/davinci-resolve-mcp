"""The offline guard must not take the whole run down with it.

`tests/__init__.py` calls `offline_guard.install()` before any test module is
imported, so anything it raises is not one test failing — it is every module
argument failing to load. That is exactly what happened: the publish workflow
installs only pyflakes, `src.server` imports `anyio`, and six module arguments
turned into six `_FailedTest` errors that failed the npm publish.

The static guards are pure AST readers and are *meant* to run without the
runtime stack. So a missing third-party package means there is no live-Resolve
entry point to neuter and skipping is honest — while a failure originating
inside `src/` is a real breakage that must still raise, since hiding it would
defeat the guards this file protects.
"""

from __future__ import annotations

import builtins
import unittest
from unittest import mock

from tests import offline_guard


def _raising_import(exc: BaseException):
    """Stand-in for __import__ that fails only for `src`."""
    real = builtins.__import__

    def fake(name, *args, **kwargs):
        if name == "src" or name.startswith("src."):
            raise exc
        return real(name, *args, **kwargs)

    return fake


class ImportClassificationTests(unittest.TestCase):
    def tearDown(self) -> None:
        offline_guard.SKIPPED_REASON = None

    def test_a_missing_third_party_dep_skips_rather_than_raises(self) -> None:
        exc = ModuleNotFoundError("No module named 'anyio'", name="anyio")
        with mock.patch.object(builtins, "__import__", _raising_import(exc)):
            self.assertIsNone(offline_guard._import_server())
        self.assertIsNotNone(offline_guard.SKIPPED_REASON)
        self.assertIn("anyio", offline_guard.SKIPPED_REASON)

    def test_a_failure_inside_src_still_raises(self) -> None:
        """The guards exist to catch broken imports in src/; swallowing one
        here would make them silently vacuous."""
        exc = ModuleNotFoundError("No module named 'src.utils.gone'", name="src.utils.gone")
        with mock.patch.object(builtins, "__import__", _raising_import(exc)):
            with self.assertRaises(ModuleNotFoundError):
                offline_guard._import_server()

    def test_a_non_import_error_is_never_swallowed(self) -> None:
        exc = RuntimeError("server module blew up at import time")
        with mock.patch.object(builtins, "__import__", _raising_import(exc)):
            with self.assertRaises(RuntimeError):
                offline_guard._import_server()

    def test_a_successful_import_clears_any_previous_skip(self) -> None:
        offline_guard.SKIPPED_REASON = "stale"
        self.assertIsNotNone(offline_guard._import_server())
        self.assertIsNone(offline_guard.SKIPPED_REASON)


class NoEntryPointToGuardTests(unittest.TestCase):
    """install/uninstall/clear must all no-op rather than explode, since
    `tests/__init__.py` calls install() at import time on every run."""

    def tearDown(self) -> None:
        offline_guard.SKIPPED_REASON = None

    def test_the_public_helpers_survive_an_unimportable_server(self) -> None:
        exc = ModuleNotFoundError("No module named 'anyio'", name="anyio")
        with mock.patch.object(builtins, "__import__", _raising_import(exc)):
            self.assertFalse(offline_guard.install())
            offline_guard.uninstall()
            offline_guard.clear_cached_handle()


if __name__ == "__main__":
    unittest.main()
