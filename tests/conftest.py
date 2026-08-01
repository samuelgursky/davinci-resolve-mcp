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

Both are closed centrally rather than test by test, because the next test to
reach for a live Resolve would otherwise reintroduce them. Anything that
genuinely wants a Resolve-shaped object patches `get_resolve` itself with a stub
it controls; that is what `test_tool_argument_validation.py` does, and it keeps
working because these are plain attribute swaps, not restrictions.

The swap itself lives in `offline_guard`, and `tests/__init__.py` installs it as
well — this file is the pytest half of a guard that has to hold under
`python -m unittest` too, which is what the release checklist runs. Both call the
same idempotent installer so the two paths cannot drift apart.

Live validation lives in `tests/live_*.py`, which pytest does not collect.
"""

from __future__ import annotations

import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tests import offline_guard  # noqa: E402 - after the sys.path fix above
from tests.offline_guard import LAUNCH_ATTEMPTS  # noqa: F401 - re-exported


@pytest.fixture(autouse=True, scope="session")
def _never_touch_a_real_resolve():
    # Already installed by `tests/__init__.py` in most runs; `install()` is
    # idempotent, so this is the path for anyone invoking pytest in a way that
    # imports conftest first.
    installed_here = offline_guard.install()
    try:
        yield
    finally:
        if installed_here:
            offline_guard.uninstall()


@pytest.fixture(autouse=True)
def _no_cached_resolve_handle_between_tests():
    """Clear the module-global handle `get_resolve()` memoises.

    Found the honest way: a test asserting Resolve *is* launched when absent
    passed alone and failed in its own file. See `offline_guard` for why a stale
    handle defeats a mock.
    """
    offline_guard.clear_cached_handle()
    try:
        yield
    finally:
        offline_guard.clear_cached_handle()


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if LAUNCH_ATTEMPTS:
        terminalreporter.write_line("")
        terminalreporter.write_line(
            "offline suite tried to launch DaVinci Resolve %d time(s):" % len(LAUNCH_ATTEMPTS),
            red=True,
        )
        for where in dict.fromkeys(LAUNCH_ATTEMPTS):
            terminalreporter.write_line("  " + where, red=True)
