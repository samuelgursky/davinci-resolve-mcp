"""The offline stand-ins that keep the suite away from a real DaVinci Resolve.

This used to live in `conftest.py`, which meant it only ever ran under pytest.
The release process runs the suite with `python -m unittest`, where conftest is
never loaded — so on that path the guard did not exist and the suite connected
to whatever Resolve happened to be open. Measured on a machine with Resolve
running: `test_audio_fairlight_probe` reached `_safe_auto_sync_audio`, which
calls `get_resolve()` for the `AUDIO_SYNC_*` attributes, connected for real, and
cached the live handle in `server.resolve`. Every later test inherited it, and
the three `NeverLaunchARunningResolveTests` cases then asserted against a live
object instead of their own mocks.

Worse than the failures: with Resolve *closed*, that same call reaches
`_launch_resolve()` and opens the application — the exact behaviour this guard
was written to stop, on the runner the release checklist actually uses.

So the stand-ins live here, both runners install them, and installation is
idempotent — installing twice would capture the first stub as the "real"
function, leaving `_get_resolve_unpatched` pointing at a stub and silently
hollowing out the tests that call it on purpose.

Swapping `src.server` alone left a second server wide open. `src/granular/common.py`
connected at *import* time, `import DaVinciResolveScript` then `connect_resolve()`,
so `import src.granular.media_pool` called `scriptapp("Resolve")` on the real
`fusionscript.so`. Confirmed with Resolve open: `connect_resolve` received
`<module 'fusionscript' from '/Applications/DaVinci Resolve/...'>`. Its own
`get_resolve()` falls through to its own `_launch_resolve()`, and nothing here
swapped either. Whether the real module loaded at all came down to import order,
because the handful of test modules that `sys.modules.setdefault()` a stub only
win when they happen to run first.

The compound server had a hole the swaps never covered either. Its
execution-lifecycle state provider calls `server._try_connect()` directly before
tool calls. A full `unittest discover` run of the previous guard, with a
tripwire standing in for the library, recorded 1,162 connections from there
alone.

So the guard now closes the door at the module as well as at the call sites.
`DaVinciResolveScript` and `fusionscript` are answered by an empty stand-in from
a `sys.meta_path` finder, and the granular server's entry points are swapped
the same way as the compound server's.

None of that reaches a child process, and some tests start real Python
children. `server._open_control_panel` runs `src/analysis_dashboard.py`, which
imported Blackmagic's module and called `scriptapp("Resolve")` on whatever was
open. On v4.8.4 that was 6 calls from 3 panel children in one full run. So the
guard also exports an environment for children. `offline_child_site` goes first
on PYTHONPATH, and its `sitecustomize.py` answers the scripting modules with the
same kind of stand-in inside every Python child that inherits the environment.
The bridge redirect below reaches children through the environment as well.

A stand-in that is reached still means a test asked for a real Resolve, and
until v4.8.8 nothing failed when it happened. The launches went into
`LAUNCH_ATTEMPTS`, which pytest printed in its summary and `unittest` never
read, labelled "<unknown test>". On v4.8.4, with the granular launcher replaced
by a counting stub, one full `unittest discover` run reached it 10 times, all
from `test_granular_destructive_op.McpSchema`. That test asked `hasattr` of
every global in the granular modules, and ten of those globals are a
`ResolveProxy` that connects on attribute access. So every `unittest.TestCase`
now runs under a check that fails it when a launcher was reached during it, or
since the previous test finished (at import, or in a class fixture). Plain
pytest functions get the same check from `conftest.py`.
"""

from __future__ import annotations

import functools
import importlib.abc
import importlib.machinery
import os
import shutil
import sys
import tempfile
import unittest

#: Every launch the suite attempted, so a failure names the test rather than
#: leaving an application open with no explanation. Entries are `LaunchAttempt`s.
#: A test that calls a stand-in on purpose deletes its own entry, and the check
#: below then has nothing to fail it for.
LAUNCH_ATTEMPTS: list = []

#: The tests running right now, innermost last. A test that runs another test,
#: as the launch-check tests do, nests.
_running_tests: list = []

#: Set on the `TestCase.run` wrapper, so a second install does not wrap it again.
_LAUNCH_CHECK_FLAG = "_offline_guard_launch_check"

#: Set on `src.server` once the swap is in place, so a second install is a no-op
#: rather than a stub-wrapping-a-stub.
_INSTALLED_FLAG = "_offline_guard_installed"

#: Mirrors `src.server._MEDIA_ANALYSIS_PREFS_ENV`. Named here rather than
#: imported so installing the guard cannot depend on importing the server.
_PREFS_ENV = "DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS"

#: Mirrors `src.utils.resolve_bridge_client.ENV_CONFIG_PATH`, for the same reason.
_BRIDGE_CONFIG_ENV = "DAVINCI_RESOLVE_BRIDGE_CONFIG"

#: Blackmagic's scripting modules. `DaVinciResolveScript.py` is only a loader: it
#: tries `import fusionscript`, then loads the native library from
#: `RESOLVE_SCRIPT_LIB` or the install path. Both names are answered here, so
#: neither route reaches the real library.
SCRIPTING_MODULES = ("DaVinciResolveScript", "fusionscript")

#: Set on every stand-in module, so a test can tell the guard's stub apart from
#: the real library and from a stub of its own.
STUB_MARKER = "__resolve_offline_guard_stub__"

#: Holds only `sitecustomize.py`, which stands in for the scripting modules in a
#: child process. That file repeats `SCRIPTING_MODULES` and `STUB_MARKER` because
#: it cannot import this one, and a test keeps the copies equal.
CHILD_SITE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "offline_child_site")

#: The granular server's copies of the entry points swapped on `src.server`.
GRANULAR_ENTRY_POINTS = ("_try_connect", "_launch_resolve", "get_resolve")

#: The originals, kept for `uninstall`.
_originals: dict = {}

#: Set when `src.server` could not be imported because a third-party runtime
#: dependency is absent. Read by tests that need to tell "guard installed" apart
#: from "there was nothing to guard".
SKIPPED_REASON: str | None = None

#: The same, for `src.granular.common`. Kept separate so a granular-only gap
#: cannot make the bootstrap test skip its check on `src.server`.
GRANULAR_SKIPPED_REASON: str | None = None


def _missing_third_party(exc: ModuleNotFoundError) -> str:
    """The absent package's top-level name, or re-raise when it is our own code."""
    missing = (exc.name or "").split(".")[0]
    if missing in ("src", "tests", ""):
        raise exc
    return missing


def _import_server():
    """Import `src.server`, or return None when its runtime deps are absent.

    The static guard tests are pure AST readers and deliberately run without the
    runtime stack installed — the publish workflow installs only pyflakes. But
    `tests/__init__.py` calls `install()` before *any* test module loads, so an
    ImportError here does not fail one test, it fails the whole run: six module
    arguments produced six `_FailedTest` errors and took the npm publish down
    with them.

    Narrowly scoped on purpose. A missing third-party package means there is no
    live Resolve entry point to neuter, so the guard is vacuously satisfied and
    skipping is honest. A failure originating inside `src/` is a real breakage
    and still raises — swallowing that would hide exactly the class of bug the
    static guards exist to catch.
    """
    global SKIPPED_REASON
    try:
        from src import server
    except ModuleNotFoundError as exc:
        missing = _missing_third_party(exc)
        SKIPPED_REASON = (
            f"src.server not importable: no module named {missing!r}. The "
            "offline guard has nothing to swap; this is expected when running "
            "the static guards without the runtime stack installed."
        )
        return None
    SKIPPED_REASON = None
    return server


def _import_granular_common():
    """Import `src.granular.common`, or return None when its runtime deps are absent.

    Same rule as `_import_server`, and the same statement form, so a test that
    fakes `__import__` reaches both.
    """
    global GRANULAR_SKIPPED_REASON
    try:
        from src.granular import common
    except ModuleNotFoundError as exc:
        missing = _missing_third_party(exc)
        GRANULAR_SKIPPED_REASON = (
            f"src.granular.common not importable: no module named {missing!r}. "
            "There is no granular server to guard."
        )
        return None
    GRANULAR_SKIPPED_REASON = None
    return common


class LaunchAttempt(str):
    """One `LAUNCH_ATTEMPTS` entry: which test reached a launcher, and from where.

    A `str`, so the pytest summary and the tests that count entries read it as
    before. `reported` is set once a test has failed for it, so each attempt
    fails exactly one test.
    """

    reported = False


def _current_test_label() -> str:
    if _running_tests:
        return _running_tests[-1].id()
    # pytest sets this for plain test functions, which never pass through
    # `TestCase.run`. Outside any test, nothing names the caller.
    return os.environ.get("PYTEST_CURRENT_TEST") or "<outside any test>"


def _blocked_launch(*_args, **_kwargs):
    # One stand-in serves both servers. The caller's module says which launcher
    # it stood in for: `get_resolve` in `src.server` or `src.granular.common`.
    caller = sys._getframe(1).f_globals.get("__name__", "<unknown module>")
    LAUNCH_ATTEMPTS.append(LaunchAttempt(f"{_current_test_label()} (called from {caller})"))
    return False


def unreported_launch_attempts() -> list:
    """The attempts no test has failed for yet, now marked as reported."""
    pending = [
        attempt
        for attempt in LAUNCH_ATTEMPTS
        if isinstance(attempt, LaunchAttempt) and not attempt.reported
    ]
    for attempt in pending:
        attempt.reported = True
    return pending


def launch_failure_message(pending) -> str:
    listed = "\n".join(f"  - {attempt}" for attempt in pending)
    return (
        f"A DaVinci Resolve launcher was reached:\n{listed}\n"
        "The offline guard's stand-in answered. Without the guard this opens "
        "Resolve, or connects to the one already open. Give the code under test a "
        "Resolve stub it controls instead. A test that calls the stand-in on "
        "purpose deletes its own entry from `offline_guard.LAUNCH_ATTEMPTS`."
    )


def _fail_on_launch_attempts() -> None:
    pending = unreported_launch_attempts()
    if pending:
        raise AssertionError(launch_failure_message(pending))


def _install_launch_check() -> None:
    """Fail every `unittest.TestCase` that reaches a launcher, under either runner.

    A cleanup rather than a check after `run` returns: unittest reports an
    exception in a cleanup as a failure of that test, and pytest's unittest
    integration drives the same `run`. Registered before the test's own
    cleanups, so it runs after them.
    """
    current = unittest.TestCase.run
    if getattr(current, _LAUNCH_CHECK_FLAG, False):
        return
    _originals["TestCase.run"] = current

    @functools.wraps(current)
    def run(self, result=None):
        self.addCleanup(_fail_on_launch_attempts)
        _running_tests.append(self)
        try:
            return current(self, result)
        finally:
            _running_tests.pop()

    setattr(run, _LAUNCH_CHECK_FLAG, True)
    unittest.TestCase.run = run


def launch_check_installed() -> bool:
    return bool(getattr(unittest.TestCase.run, _LAUNCH_CHECK_FLAG, False))


def _uninstall_launch_check() -> None:
    original = _originals.pop("TestCase.run", None)
    if original is not None:
        unittest.TestCase.run = original


def _offline_resolve_is_running():
    # False, so error messages derived from it are the same on every machine.
    # Without this a test asserting on the "no Resolve" message passed or failed
    # according to whether the developer happened to have Resolve open — which
    # is exactly the host dependence this file exists to remove.
    return False


def _offline_get_resolve():
    # None is the honest answer for an offline suite: it is exactly what a
    # machine with Resolve closed reports, so actions take their
    # "not connected" path deterministically instead of depending on what
    # happens to be running.
    return None


def _offline_try_connect():
    return None


def install() -> bool:
    """Swap the live-Resolve entry points for offline stand-ins.

    Returns True if this call did the swap, False if it was already in place or
    there was nothing to swap (see `_import_server`). The scripting-module stub
    and the children's PYTHONPATH go in on every path. Neither needs a
    third-party package, and they protect the code that none of the swaps below
    can reach.
    """
    # First, because importing `src.server` imports DaVinciResolveScript.
    _install_scripting_stub()
    _guard_child_processes()

    server = _import_server()
    if server is None:
        return False

    if getattr(server, _INSTALLED_FLAG, False):
        return False

    _originals["_launch_resolve"] = server._launch_resolve
    _originals["get_resolve"] = server.get_resolve
    _originals["resolve_is_running"] = server.resolve_is_running

    # Kept reachable so the tests that *assert on this very behaviour* can call the
    # real thing. `getattr` with a fallback at the callsite means they also work
    # when this guard is absent.
    #
    # Without this, a test asserting "a genuinely absent Resolve is still launched"
    # silently exercises the stub above and passes for the wrong reason — which is
    # how one of them was caught.
    server._launch_resolve_unpatched = _originals["_launch_resolve"]
    server._get_resolve_unpatched = _originals["get_resolve"]
    server._resolve_is_running_unpatched = _originals["resolve_is_running"]

    server._launch_resolve = _blocked_launch
    server.get_resolve = _offline_get_resolve
    server.resolve_is_running = _offline_resolve_is_running

    _guard_granular_server()
    _install_launch_check()
    _redirect_security_audit_log()
    _redirect_operation_log()
    _redirect_media_analysis_preferences()
    _redirect_bridge_config()

    setattr(server, _INSTALLED_FLAG, True)
    return True


class _ScriptingModuleStub(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Answer `import DaVinciResolveScript` / `import fusionscript` with an empty module.

    A finder rather than a `sys.modules` entry, because an entry lasts only
    until a test removes it. `test_dashboard_bridge_connect` pops it to
    simulate the free edition, which leaves the next `import` to walk
    `sys.path` to the real library. A finder answers every import that `sys.modules` misses,
    whenever it happens. A test that installs its own module, or its own finder,
    still wins: this sits behind `sys.modules`, and a later finder goes in front.

    Empty on purpose, with no `scriptapp`. `connect_resolve()` calls
    `dvr_script.scriptapp(...)` before its bridge fallback, so on this stub it
    raises AttributeError. Every caller already catches that as "not connected",
    and the call never gets as far as the bridge. A `scriptapp` that returned
    None would fall through to the bridge instead.
    """

    #: Checked instead of `isinstance`, which would miss an instance made by a
    #: second copy of this file (`offline_guard` vs `tests.offline_guard`).
    resolve_offline_guard = True

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in SCRIPTING_MODULES:
            return None
        return importlib.machinery.ModuleSpec(fullname, self, origin="tests.offline_guard stub")

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        module.__doc__ = "Offline stand-in for Blackmagic's scripting module; no scriptapp."
        setattr(module, STUB_MARKER, True)


def is_scripting_stub(module) -> bool:
    return bool(getattr(module, STUB_MARKER, False))


def scripting_stub_installed() -> bool:
    return any(getattr(finder, "resolve_offline_guard", False) for finder in sys.meta_path)


def _install_scripting_stub() -> None:
    if scripting_stub_installed():
        return
    # Anything imported before the guard existed would be served straight from
    # `sys.modules` and never reach the finder. On the first install that can
    # only be the real library, so it goes.
    for name in SCRIPTING_MODULES:
        if name in sys.modules and not is_scripting_stub(sys.modules[name]):
            del sys.modules[name]
    sys.meta_path.insert(0, _ScriptingModuleStub())


def _uninstall_scripting_stub() -> None:
    sys.meta_path[:] = [f for f in sys.meta_path if not getattr(f, "resolve_offline_guard", False)]
    for name in SCRIPTING_MODULES:
        if is_scripting_stub(sys.modules.get(name)):
            del sys.modules[name]


def _loaded_granular_modules() -> list:
    return [
        module
        for name, module in list(sys.modules.items())
        if module is not None and (name == "src.granular" or name.startswith("src.granular."))
    ]


def _guard_granular_server() -> None:
    """Swap the granular server's entry points, in every module that holds one.

    Swapping the attribute on `common` is not enough. `src/granular/__init__.py`
    imports every tool module, and each one runs `from src.granular.common import *`.
    So by the time `import src.granular.common` returns here, every tool module
    already holds its own binding of the real functions, and
    `resolve_211.get_resolve()` would still connect. Every binding that is the
    original function object gets the stand-in. Tool modules imported later
    bind from `common`, which is swapped by then.
    """
    common = _import_granular_common()
    if common is None or getattr(common, _INSTALLED_FLAG, False):
        return

    stand_ins = {
        "_try_connect": _offline_try_connect,
        "_launch_resolve": _blocked_launch,
        "get_resolve": _offline_get_resolve,
    }
    rebound = []
    for name in GRANULAR_ENTRY_POINTS:
        real = getattr(common, name)
        # Reachable for the same reason as on `src.server`.
        setattr(common, f"_{name.lstrip('_')}_unpatched", real)
        for module in _loaded_granular_modules():
            if getattr(module, name, None) is real:
                setattr(module, name, stand_ins[name])
                rebound.append((module, name, real))
    # A handle cached before the guard ran is unreachable once `get_resolve` is
    # stubbed, but a test reading `common.resolve` directly would still find it.
    common.resolve = None

    _originals["granular_rebound"] = rebound
    _originals["granular_common"] = common
    setattr(common, _INSTALLED_FLAG, True)


def _unguard_granular_server() -> None:
    for module, name, real in _originals.pop("granular_rebound", ()):
        setattr(module, name, real)
    common = _originals.pop("granular_common", None)
    if common is not None:
        setattr(common, _INSTALLED_FLAG, False)


def _redirect_bridge_config() -> None:
    """Point the in-app bridge client at a config file that does not exist.

    The bridge is the third transport `connect_resolve()` takes, and the stub
    above does not close it on its own. With `DAVINCI_RESOLVE_BRIDGE=1` in the
    developer's shell, or a caller passing `dvr_script=None`, the client reads
    `~/.config/davinci-resolve-mcp/bridge.json` and opens a socket to the script
    running inside Resolve. Without a config file there is no token and no port,
    so `connect()` raises BridgeUnavailable before it touches the network.

    Unlike the preferences redirect, this replaces an inherited value instead of
    deferring to it. A path exported in the shell points at the operator's real
    bridge. Tests that exercise the bridge set their own path with
    `mock.patch.dict`, and that still wins inside their scope.

    Child processes inherit the variable. That includes the doctor probe, which
    replaces PYTHONPATH and so never loads `offline_child_site`, and which calls
    `connect_resolve(None)`, the bridge's own route.
    """
    _originals["_bridge_config_env"] = os.environ.get(_BRIDGE_CONFIG_ENV)
    directory = tempfile.mkdtemp(prefix="resolve-bridge-offline-")
    _originals["_bridge_config_dir"] = directory
    os.environ[_BRIDGE_CONFIG_ENV] = os.path.join(directory, "bridge.json")


def _restore_bridge_config() -> None:
    if "_bridge_config_dir" not in _originals:
        return
    previous = _originals.pop("_bridge_config_env", None)
    if previous is None:
        os.environ.pop(_BRIDGE_CONFIG_ENV, None)
    else:
        os.environ[_BRIDGE_CONFIG_ENV] = previous
    shutil.rmtree(_originals.pop("_bridge_config_dir"), ignore_errors=True)


def _guard_child_processes() -> None:
    """Put `CHILD_SITE_DIR` first on PYTHONPATH, for every child this run starts.

    A Python child that inherits the environment then runs its `sitecustomize.py`
    at startup, before any code of its own. That file answers
    `DaVinciResolveScript` and `fusionscript` with an empty stand-in, refuses a
    `subprocess` launch of the application, and still runs the `sitecustomize` it
    shadows. See its docstring for the measurements and for the children it cannot
    reach. The existing entries keep their order behind it.

    Idempotent across copies of this module (`offline_guard` and
    `tests.offline_guard` can both be imported in one run). The state lives in the
    environment, and a copy that finds the directory already in front changes
    nothing and records nothing to restore.
    """
    current = os.environ.get("PYTHONPATH")
    entries = current.split(os.pathsep) if current else []
    if entries[:1] == [CHILD_SITE_DIR]:
        return
    _originals["_child_pythonpath"] = current
    os.environ["PYTHONPATH"] = os.pathsep.join(
        [CHILD_SITE_DIR] + [entry for entry in entries if entry != CHILD_SITE_DIR]
    )


def _unguard_child_processes() -> None:
    if "_child_pythonpath" not in _originals:
        return
    previous = _originals.pop("_child_pythonpath")
    if previous is None:
        os.environ.pop("PYTHONPATH", None)
    else:
        os.environ["PYTHONPATH"] = previous


def _redirect_security_audit_log() -> None:
    """Send destructive-op audit records to a temp file for the duration.

    The audit log defaults to `logs/security-audit.jsonl` under the repo, which
    is the right default for a real install and the wrong one for a test run:
    exercising a `@destructive_op`-wrapped handler appends a genuine-looking
    record. `test_tool_argument_validation` walks every tool, so one suite run
    wrote 24 fabricated `delete_timelines` / `reset_all_grades` / `apply_cuts`
    events into the operator's trail, and repeated runs accumulated 216.

    A security log is read to answer "what actually happened here", so synthetic
    entries in it are worse than a missing feature — they are indistinguishable
    from real ones at the point someone needs to trust the file. Redirected
    centrally rather than per test, because the next test to wrap a destructive
    handler would otherwise reintroduce it.
    """
    try:
        from src.utils import destructive_hook
    except Exception:
        return

    original = destructive_hook._audit_log_path
    _originals["_audit_log_path"] = original
    handle = tempfile.NamedTemporaryFile(
        prefix="security-audit-test-", suffix=".jsonl", delete=False
    )
    handle.close()
    _originals["_audit_log_tempfile"] = handle.name

    def audit_log_path_offline() -> str:
        # Only the *default* is replaced. A test that configures
        # `destructive.audit_log_path` — the audit tests do, to read back what
        # they wrote — must still get its own path, or this guard would break
        # the tests covering the feature it is protecting.
        if destructive_hook._read_preference("destructive.audit_log_path", None):
            return original()
        return handle.name

    destructive_hook._audit_log_path = audit_log_path_offline


def _redirect_operation_log() -> None:
    """Send synthetic mutating-operation records to a temp file during tests."""
    try:
        from src.utils import operation_log
    except Exception:
        return

    original = operation_log.operation_log_path
    _originals["operation_log_path"] = original
    handle = tempfile.NamedTemporaryFile(
        prefix="operation-log-test-", suffix=".jsonl", delete=False
    )
    handle.close()
    _originals["operation_log_tempfile"] = handle.name

    def operation_log_path_offline() -> str:
        if operation_log._read_preference("destructive.operation_log_path", None):
            return original()
        return handle.name

    operation_log.operation_log_path = operation_log_path_offline


def _redirect_media_analysis_preferences() -> None:
    """Point setup's persisted defaults at a temp file for the duration.

    `logs/media-analysis-preferences.json` holds the operator's real `setup`
    defaults, including `destructive.safe_mode`. Tests that call `setup` already
    override the path, but the other three thousand read it, so a preference
    saved on disk decided what the suite did: with `safe_mode` true, seventeen
    tests across `test_cut_executor`, `test_keyed_param_guards` and
    `test_media_pool_delete_governance` failed with
    "Safe mode blocked critical-risk action" — a red suite caused by a setting,
    not by the code under test.

    A suite whose verdict depends on the developer's saved preferences is not
    reporting on the code. Redirected here so it holds for every entry point.
    """
    env = os.environ.get(_PREFS_ENV)
    if env:
        return  # An outer harness already chose a path; don't fight it.
    handle = tempfile.NamedTemporaryFile(
        prefix="media-analysis-preferences-test-", suffix=".json", delete=False
    )
    handle.write(b"{}")
    handle.close()
    _originals["_prefs_env_tempfile"] = handle.name
    os.environ[_PREFS_ENV] = handle.name


def _restore_media_analysis_preferences() -> None:
    path = _originals.pop("_prefs_env_tempfile", None)
    if not path:
        return
    os.environ.pop(_PREFS_ENV, None)
    if os.path.exists(path):
        try:
            os.unlink(path)
        except OSError:
            pass


def _restore_security_audit_log() -> None:
    if "_audit_log_path" not in _originals:
        return
    try:
        from src.utils import destructive_hook

        destructive_hook._audit_log_path = _originals.pop("_audit_log_path")
    except Exception:
        _originals.pop("_audit_log_path", None)
    path = _originals.pop("_audit_log_tempfile", None)
    if path and os.path.exists(path):
        try:
            os.unlink(path)
        except OSError:
            pass


def _restore_operation_log() -> None:
    if "operation_log_path" not in _originals:
        return
    try:
        from src.utils import operation_log

        operation_log.operation_log_path = _originals.pop("operation_log_path")
    except Exception:
        _originals.pop("operation_log_path", None)
    path = _originals.pop("operation_log_tempfile", None)
    if path and os.path.exists(path):
        try:
            os.unlink(path)
        except OSError:
            pass


def uninstall() -> None:
    """Restore the originals. Safe to call when nothing was installed."""
    server = _import_server()
    if server is None:
        return

    if not getattr(server, _INSTALLED_FLAG, False):
        return
    server._launch_resolve = _originals["_launch_resolve"]
    server.get_resolve = _originals["get_resolve"]
    server.resolve_is_running = _originals["resolve_is_running"]
    _unguard_granular_server()
    _uninstall_launch_check()
    _restore_security_audit_log()
    _restore_operation_log()
    _restore_media_analysis_preferences()
    _restore_bridge_config()
    # Only on this path: a call that found nothing to restore, such as the one
    # `test_offline_guard` makes with `src` unimportable, must not strip the stub
    # or the children's PYTHONPATH from under the rest of the run.
    _uninstall_scripting_stub()
    _unguard_child_processes()
    setattr(server, _INSTALLED_FLAG, False)


def clear_cached_handle() -> None:
    """Drop the module-global handle `get_resolve()` memoises.

    `_try_connect` assigns to `server.resolve`, and `get_resolve` returns that
    early whenever `_is_resolve_handle_live` accepts it — before consulting
    anything a test has mocked. A MagicMock passes that check too (every
    attribute is truthy), so a test that installs one leaves it cached for every
    test after it, which then never reaches the code it meant to exercise.
    """
    server = _import_server()
    if server is None:
        return

    server.resolve = None
    common = sys.modules.get("src.granular.common")
    if common is not None:
        common.resolve = None
