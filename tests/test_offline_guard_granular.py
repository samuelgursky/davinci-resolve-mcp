"""The offline guard must hold for the granular server and for Blackmagic's module.

`src/granular/common.py` used to connect at import time, and the guard only
swapped `src.server`. So any test that imported a granular module called
`scriptapp("Resolve")` on the real `fusionscript.so` whenever Resolve was
installed and open.

These tests put a module shaped exactly like Blackmagic's loader first on
`sys.path`, where a path-based import would pick it up, and assert that it is
never executed. That covers a fresh import of `src.granular.common` and the
startup connection the launchers now make explicitly. They also check that
every granular tool module holds the stand-ins, not only `common`, and that
the in-app bridge has nothing to connect to.

Nothing here needs, or reaches, a real Resolve. The real-looking module writes
each call to a file instead of connecting.
"""

from __future__ import annotations

import importlib
import importlib.machinery
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from tests import offline_guard

GRANULAR_COMMON = "src.granular.common"

#: A stand-in for Blackmagic's loader. Importable by name from `sys.path`, it
#: has a `scriptapp` and leaves a trace when it is executed or called.
FAKE_LOADER = '''\
_TRACE = {trace!r}


def _record(line):
    with open(_TRACE, "a", encoding="utf-8") as handle:
        handle.write(line + "\\n")


_record("imported " + __name__)


def scriptapp(*args):
    _record("scriptapp " + repr(args))
    return None
'''


def _skip_reason() -> str | None:
    return offline_guard.SKIPPED_REASON or offline_guard.GRANULAR_SKIPPED_REASON


class RealLookingScriptingModules(unittest.TestCase):
    """Real-looking `DaVinciResolveScript` / `fusionscript` files first on `sys.path`."""

    def setUp(self) -> None:
        reason = _skip_reason()
        if reason:
            self.skipTest(reason)
        self.directory = tempfile.mkdtemp(prefix="fake-resolve-scripting-")
        self.addCleanup(shutil.rmtree, self.directory, True)
        self.trace = os.path.join(self.directory, "trace.log")
        for name in offline_guard.SCRIPTING_MODULES:
            path = os.path.join(self.directory, name + ".py")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(FAKE_LOADER.format(trace=self.trace))
        sys.path.insert(0, self.directory)
        self.addCleanup(sys.path.remove, self.directory)
        # Removed from the cache, the way a test that pops them leaves them, so
        # the next import is resolved from scratch.
        saved = {
            name: sys.modules.pop(name)
            for name in offline_guard.SCRIPTING_MODULES
            if name in sys.modules
        }
        self.addCleanup(self._restore_scripting_modules, saved)

    @staticmethod
    def _restore_scripting_modules(saved: dict) -> None:
        for name in offline_guard.SCRIPTING_MODULES:
            sys.modules.pop(name, None)
        sys.modules.update(saved)

    def trace_lines(self) -> list:
        if not os.path.exists(self.trace):
            return []
        with open(self.trace, encoding="utf-8") as handle:
            return handle.read().splitlines()

    def assert_the_fake_would_be_imported(self) -> None:
        """The precondition that makes a passing test mean something."""
        for name in offline_guard.SCRIPTING_MODULES:
            spec = importlib.machinery.PathFinder.find_spec(name)
            self.assertIsNotNone(spec, f"{name} is not importable from sys.path")
            self.assertEqual(
                os.path.realpath(os.path.dirname(spec.origin)),
                os.path.realpath(self.directory),
            )


class ImportingGranularCommonNeverConnectsTests(RealLookingScriptingModules):
    def setUp(self) -> None:
        super().setUp()
        # A fresh execution of the module, not the copy the guard already
        # imported. Put back afterwards, because every granular tool module and
        # the tests that imported one hold references into the original.
        original = sys.modules.pop(GRANULAR_COMMON)
        package = sys.modules["src.granular"]

        def restore() -> None:
            sys.modules[GRANULAR_COMMON] = original
            package.common = original

        self.addCleanup(restore)

    def test_a_fresh_import_never_reaches_scriptapp(self) -> None:
        self.assert_the_fake_would_be_imported()

        common = importlib.import_module(GRANULAR_COMMON)

        self.assertEqual(self.trace_lines(), [], "the real-looking module was executed")
        self.assertFalse(hasattr(common.dvr_script, "scriptapp"))
        self.assertTrue(offline_guard.is_scripting_stub(common.dvr_script))
        self.assertIsNone(common.resolve)

    def test_the_startup_connection_never_reaches_scriptapp_either(self) -> None:
        """What used to run at import now runs when a launcher asks for it.
        Under the guard it must still stop at the stub."""
        self.assert_the_fake_would_be_imported()

        common = importlib.import_module(GRANULAR_COMMON)

        self.assertIsNone(common.connect_at_startup())
        self.assertEqual(self.trace_lines(), [], "the real-looking module was executed")


class ScriptingModuleStubTests(RealLookingScriptingModules):
    def test_both_names_resolve_to_the_stub(self) -> None:
        self.assert_the_fake_would_be_imported()
        for name in offline_guard.SCRIPTING_MODULES:
            with self.subTest(name=name):
                module = importlib.import_module(name)
                self.assertTrue(offline_guard.is_scripting_stub(module))
                self.assertFalse(hasattr(module, "scriptapp"))
        self.assertEqual(self.trace_lines(), [])

    def test_the_finder_is_installed_once(self) -> None:
        offline_guard._install_scripting_stub()
        finders = [f for f in sys.meta_path if getattr(f, "resolve_offline_guard", False)]
        self.assertEqual(len(finders), 1)

    def test_connect_resolve_on_the_stub_never_reaches_the_bridge(self) -> None:
        """The reason the stub has no `scriptapp` at all. One that returned None
        would send `connect_resolve` on to its bridge fallback."""
        from src.utils import resolve_connection

        stub = importlib.import_module("DaVinciResolveScript")
        with mock.patch.dict(os.environ, {"DAVINCI_RESOLVE_BRIDGE": ""}), mock.patch.object(
            resolve_connection, "_try_bridge_fallback"
        ) as fallback:
            with self.assertRaises(AttributeError):
                resolve_connection.connect_resolve(stub)
        fallback.assert_not_called()


class GranularStandInTests(unittest.TestCase):
    def setUp(self) -> None:
        reason = _skip_reason()
        if reason:
            self.skipTest(reason)
        self.common = sys.modules[GRANULAR_COMMON]

    def test_every_granular_module_holds_the_stand_ins(self) -> None:
        """`src/granular/__init__.py` imports every tool module, and each
        `from src.granular.common import *` binds its own copy of the entry
        points before the guard can swap `common`. Swapping only `common` left
        `resolve_211.get_resolve()` connecting."""
        real = {
            name: getattr(self.common, f"_{name.lstrip('_')}_unpatched")
            for name in offline_guard.GRANULAR_ENTRY_POINTS
        }
        holders = set()
        for module in offline_guard._loaded_granular_modules():
            for name in offline_guard.GRANULAR_ENTRY_POINTS:
                if not hasattr(module, name):
                    continue
                holders.add(module.__name__)
                with self.subTest(module=module.__name__, name=name):
                    self.assertIsNot(getattr(module, name), real[name])
        # The check has to have looked at the modules that matter.
        self.assertIn("src.granular.resolve_211", holders)
        self.assertIn("src.granular.media_pool", holders)

    def test_the_real_entry_points_stay_reachable(self) -> None:
        for name in offline_guard.GRANULAR_ENTRY_POINTS:
            with self.subTest(name=name):
                real = getattr(self.common, f"_{name.lstrip('_')}_unpatched")
                self.assertEqual(real.__module__, GRANULAR_COMMON)
                self.assertEqual(real.__name__, name)

    def test_the_stand_ins_neither_connect_nor_launch(self) -> None:
        self.assertIsNone(self.common.get_resolve())
        self.assertIsNone(self.common._try_connect())
        before = len(offline_guard.LAUNCH_ATTEMPTS)
        self.assertFalse(self.common._launch_resolve())
        self.assertEqual(len(offline_guard.LAUNCH_ATTEMPTS), before + 1)
        # Deliberate, so it must not show up in the pytest launch report.
        del offline_guard.LAUNCH_ATTEMPTS[before:]

    def test_a_tool_module_reaching_for_resolve_finds_none(self) -> None:
        from src.granular import media_storage

        # `resolve` there is a ResolveProxy, which calls `get_resolve()` on every use.
        self.assertFalse(bool(media_storage.resolve))


class BridgeConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        if offline_guard.SKIPPED_REASON:
            self.skipTest(offline_guard.SKIPPED_REASON)

    def test_the_bridge_has_no_config_to_connect_with(self) -> None:
        from src.utils import resolve_bridge_client

        path = resolve_bridge_client.config_path()
        self.assertNotEqual(path, resolve_bridge_client.DEFAULT_CONFIG_PATH)
        self.assertFalse(path.exists())
        with mock.patch.dict(os.environ, {"DAVINCI_RESOLVE_BRIDGE": "1"}), mock.patch(
            "socket.create_connection", side_effect=AssertionError("opened a socket")
        ):
            with self.assertRaises(resolve_bridge_client.BridgeUnavailable):
                resolve_bridge_client.connect()


if __name__ == "__main__":
    unittest.main()
