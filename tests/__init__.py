"""Test package.

Exists so the offline guard is installed under `python -m unittest` too, not
only under pytest. `unittest discover -s tests` and `python -m unittest
tests.test_x` both import this module before any test module, which is the only
hook `unittest` offers that runs early enough — conftest.py is a pytest concept
and is never loaded on that path. (The `load_tests` protocol is not an option
here: unittest calls it for sub-packages it descends into, never for the start
directory itself, so a hook defined here would silently never fire.)

Without this, the runner named in the release checklist ran with no guard at
all: the suite connected to a running Resolve, and would launch one when none
was running. See `offline_guard` for the measurements.

pytest additionally clears the memoised handle between tests, and there is no
equivalent unittest hook. That asymmetry is deliberate rather than overlooked:
once the guard is installed, `get_resolve` is a stub that never reads
`server.resolve`, so a handle left cached by one test is unreachable. The only
tests that take the real path reach it through `_get_resolve_unpatched`, and
they clear the cache themselves in `setUp` — which is what they should do
regardless, since it makes them independent of run order under either runner.
"""

from __future__ import annotations

import os
import tempfile

# Before ANY import that can reach src.server: importing it attaches the root
# logger's FileHandler, and left alone that handler points at the operator's
# real logs/server.log. The suite's MagicMock "connections" and lifecycle
# warnings were landing there (240 lines in a 128 MB log). Point this process
# at a throwaway file instead; a caller who already set the variable — CI, or
# someone wanting the suite's log — keeps their choice.
if "RESOLVE_MCP_LOG_FILE" not in os.environ:
    os.environ["RESOLVE_MCP_LOG_FILE"] = os.path.join(
        tempfile.mkdtemp(prefix="resolve-mcp-test-logs-"), "server.log"
    )

from . import offline_guard  # noqa: E402 - after the log redirect above

offline_guard.install()
