"""The offline suite must never open DaVinci Resolve, or connect to one.

Two things kept happening, both invisible in a green run:

1. **The suite launched Resolve.** `get_resolve()` falls through to
   `_launch_resolve()` when nothing answers, which runs `open` on the
   application. A test that only meant to exercise stub-based helpers therefore
   started Resolve — repeatedly, unprompted, and on a machine with both editions
   installed it started the wrong one.
2. **The suite connected to whatever was running.** `_safe_auto_sync_audio` and
   `_transcription_capabilities` reach for `AUDIO_SYNC_*`, which are attributes on
   the live Resolve object, so a stub-only test still called `get_resolve()`. Its
   result then depended on whether Resolve happened to be open — the same test
   taking a different path on two machines, with nothing to say so.

Both are closed here rather than test by test, because the next test to reach for
a live Resolve would otherwise reintroduce them. Anything that genuinely wants a
Resolve-shaped object patches `get_resolve` itself with a stub it controls; that
is what `test_tool_argument_validation.py` does, and it keeps working because
these are plain attribute swaps, not restrictions.

Live validation lives in `tests/live_*.py`, which pytest does not collect.
"""

from __future__ import annotations

import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

#: Every launch the suite attempted, so a failure names the test rather than
#: leaving an application open with no explanation.
LAUNCH_ATTEMPTS: list = []


@pytest.fixture(autouse=True, scope="session")
def _never_touch_a_real_resolve():
    from src import server

    real_launch = server._launch_resolve
    real_get = server.get_resolve

    def blocked_launch():
        LAUNCH_ATTEMPTS.append(os.environ.get("PYTEST_CURRENT_TEST", "<unknown test>"))
        return False

    def offline_get_resolve():
        # None is the honest answer for an offline suite: it is exactly what a
        # machine with Resolve closed reports, so actions take their
        # "not connected" path deterministically instead of depending on what
        # happens to be running.
        return None

    # Kept reachable so the tests that *assert on this very behaviour* can call the
    # real thing. `getattr` with a fallback at the callsite means they also work
    # under plain unittest, where conftest never loads.
    #
    # Without this, a test asserting "a genuinely absent Resolve is still launched"
    # silently exercises the stub above and passes for the wrong reason — which is
    # how one of them was caught.
    server._launch_resolve_unpatched = real_launch
    server._get_resolve_unpatched = real_get
    server._launch_resolve = blocked_launch
    server.get_resolve = offline_get_resolve
    try:
        yield
    finally:
        server._launch_resolve = real_launch
        server.get_resolve = real_get


@pytest.fixture(autouse=True)
def _no_cached_resolve_handle_between_tests():
    """Clear the module-global handle `get_resolve()` memoises.

    `_try_connect` assigns to `server.resolve`, and `get_resolve` returns that
    early whenever `_is_resolve_handle_live` accepts it. A MagicMock passes that
    check — every attribute is truthy — so a test that installs one leaves it
    cached for every test after it, which then never reaches the code it meant to
    exercise. Found the honest way: a test asserting Resolve *is* launched when
    absent passed alone and failed in its own file.
    """
    from src import server

    server.resolve = None
    try:
        yield
    finally:
        server.resolve = None


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if LAUNCH_ATTEMPTS:
        terminalreporter.write_line("")
        terminalreporter.write_line(
            "offline suite tried to launch DaVinci Resolve %d time(s):" % len(LAUNCH_ATTEMPTS),
            red=True,
        )
        for where in dict.fromkeys(LAUNCH_ATTEMPTS):
            terminalreporter.write_line("  " + where, red=True)
