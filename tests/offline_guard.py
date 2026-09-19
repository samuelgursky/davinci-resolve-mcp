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

The network is guarded here too. `install.py` checks GitHub for a newer release,
and `test_scripting_lib_discovery` runs its `main()` in-process, so every full
run sent a real request to `api.github.com/.../releases/latest` and wrote the
answer into `logs/update-check.json`. `urllib.request.urlopen` now refuses any
URL that would leave this machine; see `_install_network_guard`.
"""

from __future__ import annotations

import ipaddress
import os
import tempfile
import traceback
import urllib.error
import urllib.parse
import urllib.request

#: Every launch the suite attempted, so a failure names the test rather than
#: leaving an application open with no explanation.
LAUNCH_ATTEMPTS: list = []

#: Every outbound request the suite attempted, as `{"url", "caller", "test"}`.
#: The guard refused each one, so this lists what would have gone out, not
#: anything that did.
NETWORK_ATTEMPTS: list = []

#: Set on `src.server` once the swap is in place, so a second install is a no-op
#: rather than a stub-wrapping-a-stub.
_INSTALLED_FLAG = "_offline_guard_installed"

#: Set on the `urlopen` wrapper for the same reason. It lives on the function in
#: `urllib.request`, not in this module, so a second copy of this module (a bare
#: `import offline_guard` under `discover -s tests`) still sees it.
_NETWORK_FLAG = "_offline_guard_network"

#: Mirrors `src.server._MEDIA_ANALYSIS_PREFS_ENV`. Named here rather than
#: imported so installing the guard cannot depend on importing the server.
_PREFS_ENV = "DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS"

#: The originals, kept for `uninstall`.
_originals: dict = {}

#: Set when `src.server` could not be imported because a third-party runtime
#: dependency is absent. Read by tests that need to tell "guard installed" apart
#: from "there was nothing to guard".
SKIPPED_REASON: str | None = None

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class NetworkRefused(urllib.error.URLError):
    """Raised by the guard in place of an outbound request.

    A `URLError`, so the code under test takes the path it takes on a machine
    with no network: the update check reports `status: "error"` instead of
    raising, exactly as it does offline.
    """


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
    """Swap the live-Resolve entry points and `urlopen` for offline stand-ins.

    Returns True if this call installed anything, False if everything was
    already in place. Without `src.server` (see `_import_server`) only the
    network guard is installed, since it does not depend on `src`.
    """
    # First, so nothing `src.server` does at import time can reach the network,
    # and so a module that binds `urlopen` at import binds the guard.
    network_installed = _install_network_guard()

    server = _import_server()
    if server is None:
        return network_installed

    if getattr(server, _INSTALLED_FLAG, False):
        return network_installed

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
    _redirect_operation_log()
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


def _install_network_guard() -> bool:
    """Refuse every `urllib.request.urlopen` that would leave this machine.

    Loopback (`127.0.0.0/8`, `::1`, `localhost`) and `file:`/`data:` URLs go
    through untouched: the control-panel tests launch a real panel on the
    loopback interface, and `_control_panel_probe` reaches it through this same
    function. Anything else raises `NetworkRefused` before a socket is opened
    and is appended to `NETWORK_ATTEMPTS` with the call site and the test.

    Swapped on `urllib.request` because every caller in `src/` and `install.py`
    looks it up there at call time. Refused centrally rather than only in the
    test that was caught: the next test to reach a network-backed helper would
    otherwise make a real request too, and pass or fail with the machine's
    connection. A test that wants a response patches `urlopen` itself, which
    still works — `mock.patch` swaps this wrapper out and puts it back.
    """
    current = urllib.request.urlopen
    if getattr(current, _NETWORK_FLAG, None) is True:
        return False

    def offline_urlopen(url, *args, **kwargs):
        target = str(getattr(url, "full_url", url))
        if stays_on_this_machine(target):
            # Looked up per call, so a test can put a spy downstream of the check.
            return offline_urlopen.__wrapped__(url, *args, **kwargs)
        attempt = _describe_attempt(target)
        NETWORK_ATTEMPTS.append(attempt)
        raise NetworkRefused(
            f"offline test suite refused an outbound request to {target} "
            f"(from {attempt['caller']}, in {attempt['test']})"
        )

    offline_urlopen.__wrapped__ = current
    setattr(offline_urlopen, _NETWORK_FLAG, True)
    urllib.request.urlopen = offline_urlopen
    return True


def _uninstall_network_guard() -> None:
    current = urllib.request.urlopen
    if getattr(current, _NETWORK_FLAG, None) is True:
        urllib.request.urlopen = current.__wrapped__


def network_guard_installed() -> bool:
    return getattr(urllib.request.urlopen, _NETWORK_FLAG, None) is True


def stays_on_this_machine(url: str) -> bool:
    """True when opening `url` cannot send anything to another host."""
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
    except ValueError:
        return False
    if parts.scheme in ("file", "data"):
        return True
    if not host:
        return False
    host = host.rstrip(".")
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False  # a name, and not `localhost`: resolving it is already a request


def _describe_attempt(url: str) -> dict:
    """Name the code that asked for `url`, and the test it ran under."""
    here = os.path.abspath(__file__)
    frames = [
        frame
        for frame in traceback.extract_stack()
        if os.path.abspath(frame.filename) != here
        and f"{os.sep}urllib{os.sep}" not in frame.filename
    ]
    test = next(
        (
            frame
            for frame in reversed(frames)
            if os.path.basename(frame.filename).startswith("test_")
            and frame.name.startswith("test")
        ),
        None,
    )
    return {
        "url": url,
        "caller": _where(frames[-1] if frames else None),
        "test": _where(test)
        if test
        else os.environ.get("PYTEST_CURRENT_TEST", "<unknown test>"),
    }


def _where(frame) -> str:
    if frame is None:
        return "<unknown caller>"
    path = os.path.abspath(frame.filename)
    if path.startswith(_REPO_ROOT + os.sep):
        path = os.path.relpath(path, _REPO_ROOT)
    return f"{path}:{frame.lineno} in {frame.name}"


def uninstall() -> None:
    """Restore the originals. Safe to call when nothing was installed."""
    _uninstall_network_guard()

    server = _import_server()
    if server is None:
        return

    if not getattr(server, _INSTALLED_FLAG, False):
        return
    server._launch_resolve = _originals["_launch_resolve"]
    server.get_resolve = _originals["get_resolve"]
    server.resolve_is_running = _originals["resolve_is_running"]
    _restore_security_audit_log()
    _restore_operation_log()
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
