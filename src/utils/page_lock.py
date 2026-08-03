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
        # `_fh` is only ever set inside the `_HAS_FCNTL` branch above, so this
        # is transitively safe — but state the dependency rather than relying on
        # a reader tracing it, since a future assignment elsewhere would make
        # this an AttributeError on a platform without fcntl.
        if _depth == 0 and _fh is not None and _HAS_FCNTL:
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


@contextmanager
def color_page_for_thumbnails(resolve):
    """Hold the Color page for the block, restoring the user's page after.

    GetCurrentClipThumbnailImage returns data only "for current media in the
    Color Page" (docs/reference/resolve_scripting_api.txt) — on every other
    page it silently returns None. Yields True when Resolve is on the Color
    page for the block. If the current page can't be captured (GetCurrentPage
    returned None or raised), no switch is attempted, so a skipped restore can
    never strand the user on the Color page.

    Switching to Color is not free in the GUI: besides the visible page flash,
    Resolve may start cache/render work for the current clip.
    """
    original = None
    try:
        original = resolve.GetCurrentPage() if resolve else None
    except Exception:
        original = None
    with page_lock():
        on_color = original == "color"
        if original and not on_color:
            try:
                on_color = bool(resolve.OpenPage("color"))
            except Exception:
                pass
        try:
            yield on_color
        finally:
            if original and original != "color":
                try:
                    resolve.OpenPage(original)
                except Exception:
                    pass
