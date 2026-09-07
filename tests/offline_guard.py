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
"""

from __future__ import annotations

import os
import tempfile

#: Every launch the suite attempted, so a failure names the test rather than
#: leaving an application open with no explanation.
LAUNCH_ATTEMPTS: list = []

#: Set on `src.server` once the swap is in place, so a second install is a no-op
#: rather than a stub-wrapping-a-stub.
_INSTALLED_FLAG = "_offline_guard_installed"

#: Mirrors `src.server._MEDIA_ANALYSIS_PREFS_ENV`. Named here rather than
#: imported so installing the guard cannot depend on importing the server.
_PREFS_ENV = "DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS"

#: The originals, kept for `uninstall`.
_originals: dict = {}

#: Set when `src.server` could not be imported because a third-party runtime
#: dependency is absent. Read by tests that need to tell "guard installed" apart
#: from "there was nothing to guard".
SKIPPED_REASON: str | None = None


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
        missing = (exc.name or "").split(".")[0]
        if missing in ("src", "tests", ""):
            raise
        SKIPPED_REASON = (
            f"src.server not importable: no module named {missing!r}. The "
            "offline guard has nothing to swap; this is expected when running "
            "the static guards without the runtime stack installed."
        )
        return None
    SKIPPED_REASON = None
    return server


def install() -> bool:
    """Swap the live-Resolve entry points for offline stand-ins.

    Returns True if this call did the swap, False if it was already in place or
    there was nothing to swap (see `_import_server`).
    """
    server = _import_server()
    if server is None:
        return False

    if getattr(server, _INSTALLED_FLAG, False):
        return False

    def blocked_launch():
        LAUNCH_ATTEMPTS.append(os.environ.get("PYTEST_CURRENT_TEST", "<unknown test>"))
        return False

    def offline_resolve_is_running():
        # False, so error messages derived from it are the same on every machine.
        # Without this a test asserting on the "no Resolve" message passed or failed
        # according to whether the developer happened to have Resolve open — which
        # is exactly the host dependence this file exists to remove.
        return False

    def offline_get_resolve():
        # None is the honest answer for an offline suite: it is exactly what a
        # machine with Resolve closed reports, so actions take their
        # "not connected" path deterministically instead of depending on what
        # happens to be running.
        return None

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

    server._launch_resolve = blocked_launch
    server.get_resolve = offline_get_resolve
    server.resolve_is_running = offline_resolve_is_running

    _redirect_security_audit_log()
    _redirect_media_analysis_preferences()

    setattr(server, _INSTALLED_FLAG, True)
    return True


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
    _restore_security_audit_log()
    _restore_media_analysis_preferences()
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
