"""Serialize DaVinci Resolve page switches across threads and processes.

Resolve has a single globally-active page (Edit / Color / Fusion / Fairlight /
Deliver / Cut). An operation that switches the page, does work there, and reads a
result is only correct if no other operation flips the page underneath it. With a
single stdio client that never happens, but the moment two agents (threads, or
separate server processes) drive one Resolve, concurrent page switches corrupt
each other. This primitive serializes the critical section, so it must be in
place before any concurrent-agent feature ships.

- Intra-process: a reentrant lock (nested page_lock() calls are safe).
- Inter-process: a best-effort advisory file lock around the OUTERMOST section
  (fcntl). On platforms without fcntl (Windows) the inter-process guard is a
  no-op and only the intra-process lock applies.

Usage:

    with page_lock():
        resolve.OpenPage("color")
        ... do color-page work, read results ...
"""
import os
import tempfile
import threading
from contextlib import contextmanager

try:
    import fcntl  # type: ignore
    _HAS_FCNTL = True
except ImportError:  # pragma: no cover - Windows
    _HAS_FCNTL = False

_INTRA = threading.RLock()
_LOCKFILE = os.path.join(tempfile.gettempdir(), "davinci_resolve_mcp_page.lock")

# Nesting depth and the held file handle, both guarded by _INTRA. The file lock
# is taken only at the outermost level — a second fcntl.flock() on a new fd from
# the same process would block on the first, deadlocking nested page_lock()s.
_depth = 0
_fh = None


@contextmanager
def page_lock():
    """Hold the page-switch lock for the duration of the block (reentrant)."""
    global _depth, _fh
    _INTRA.acquire()
    _depth += 1
    try:
        if _depth == 1 and _HAS_FCNTL:
            try:
                _fh = open(_LOCKFILE, "w")
                fcntl.flock(_fh, fcntl.LOCK_EX)
            except OSError:
                # Advisory lock is best-effort; never block real work on it.
                if _fh is not None:
                    _fh.close()
                _fh = None
        yield
    finally:
        _depth -= 1
        if _depth == 0 and _fh is not None:
            try:
                fcntl.flock(_fh, fcntl.LOCK_UN)
            except OSError:
                pass
            _fh.close()
            _fh = None
        _INTRA.release()


def open_page_serialized(resolve, page):
    """Switch Resolve to `page` under the page lock. Returns OpenPage's result."""
    with page_lock():
        return resolve.OpenPage(page)
