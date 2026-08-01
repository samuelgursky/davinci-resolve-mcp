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

from . import offline_guard

offline_guard.install()
