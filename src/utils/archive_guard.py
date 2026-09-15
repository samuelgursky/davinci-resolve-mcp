"""`ProjectManager.ArchiveProject` on Resolve 21.1: a silent no-op or a crash.

Measured on Studio 21.1.0.14 against a disposable local project holding one
synthetic clip, archived by name. Every row is one isolated call.

=================================  ========  ====================================
include flags                      returns   effect
=================================  ========  ====================================
all off (project open or closed)   ``False`` nothing written, instantly
render cache only                  ``False`` nothing written, instantly
source media                       ``None``  empty directory at the target, then
                                             Resolve crashes (SIGSEGV)
proxy media                        ``None``  same crash
=================================  ========  ====================================

Four crashes, one of them inside a Blackmagic Cloud library, share identical top
stack frames, in Fusion script-symbol teardown on the UI thread. A crashing call
comes back through the bridge as ``None`` rather than a bool, and every handle
after it is dead. A file already at the target survived every case byte for
byte, including the crash, so the destination is never the casualty. Unsaved
work in whatever project is open is.

On 19.1.3.7 this repo's mode matrix already recorded ``False`` for both a ``.dra``
and a folder-style path with every flag off. No scriptable call on either build
has produced an archive.

So the native defaults, ``isArchiveSrcMedia=True`` and ``isArchiveRenderCache=
True``, crash Resolve 21.1.0.14, and so did both wrappers here, which inherited
them. These helpers default every flag to off, refuse the two crashing flags
unless the caller says ``acknowledge_trap``, and report what the native call
actually returned rather than a bare bool.
"""

from typing import Any, Dict, Optional, Tuple

#: Flags measured to crash Resolve 21.1.0.14 when set.
CRASH_FLAGS = ("src_media", "proxy_media")
FLAG_NAMES = ("src_media", "render_cache", "proxy_media")

_MEASURED = ("Measured on DaVinci Resolve Studio 21.1.0.14; the full table is in "
             "src/utils/archive_guard.py and the ProjectManager.ArchiveProject "
             "api_truth entry.")


def read_flags(params: Dict[str, Any]) -> Tuple[Optional[Dict[str, bool]], Optional[str]]:
    """Every include flag, defaulting to off. Only real booleans are accepted.

    A JSON caller sending ``"false"`` would have turned a flag ON through a bare
    ``bool()``, and two of these flags crash Resolve.
    """
    flags: Dict[str, bool] = {}
    for name in FLAG_NAMES:
        value = params.get(name, False)
        if not isinstance(value, bool):
            return None, (f"{name} must be true or false, got {value!r}. Two of the "
                          "archive flags crash Resolve 21.1, so a non-boolean is "
                          "refused rather than guessed at.")
        flags[name] = value
    return flags, None


def crash_refusal(tool: str, action: str, flags: Dict[str, bool]) -> Optional[Dict[str, Any]]:
    """Refuse the crashing flags unless the caller explicitly accepts the risk."""
    crashing = [f for f in CRASH_FLAGS if flags.get(f)]
    if not crashing:
        return None
    return {
        "success": False,
        "error": (f"'{tool}.{action}' is refused: with {' and '.join(crashing)} on, "
                  "ProjectManager.ArchiveProject crashes Resolve 21.1.0.14 before "
                  "writing anything but an empty directory, and unsaved work in the "
                  "open project is lost. Re-send with acknowledge_trap=true only on a "
                  "build you have verified."),
        "known_limitation": [_MEASURED],
        "crash_flags": crashing,
        "retry_with": {"acknowledge_trap": True},
    }


def outcome(native: Any, flags: Dict[str, bool], **extra: Any) -> Dict[str, Any]:
    """Report the native return as an observation, never as an assumption."""
    out: Dict[str, Any] = {"flags": dict(flags), "native_returned": native}
    out.update(extra)
    if native is True:
        out["success"] = True
    elif native is None:
        out["success"] = False
        out["error"] = ("ArchiveProject returned no result. On 21.1.0.14 that is what a "
                        "crashed Resolve looks like through the bridge; check whether "
                        "Resolve is still running.")
    else:
        out["success"] = False
        out["error"] = ("Resolve returned False and wrote nothing. With source media and "
                        "proxies off this is the measured result on 21.1.0.14 whether the "
                        "project is open or closed; no scriptable call has produced an "
                        "archive on 21.1.0.14 or 19.1.3.7.")
    return out
