"""Detect an engaged transport before calls that can hang Resolve during playback.

Measured on Studio 19.1.3.7 (2026-10-20): with playback running, a visit to
the Color page followed by `resolve_control restore_state` timed out, and from
then on EVERY scripting call hung, including a brand-new `scriptapp()`
connection. Resolve's main thread was stuck in a viewer render loop, and the
only way out was in the GUI. The scripting API has no transport control on 19.x
(no Play, Stop or IsPlaying), so the server cannot stop playback itself. What it
can do is notice playback and refuse to switch pages into it.

Playback is detected by the playhead advancing between two reads of
`Timeline.GetCurrentTimecode()`. That read is cheap and does not touch the
viewer. A playhead that cannot be read (the Media and Fusion pages report None)
gives `None`, meaning "unknown", and callers proceed: refusing every call that
cannot be measured would block the Fusion page outright.
"""
import time
from typing import Any, Dict, Optional

#: Long enough for a 23.976 fps transport to advance about four frames, short
#: enough not to make a page switch feel slow. Slow shuttle (J/K at a fraction
#: of real time) can stay inside one frame for this long and go unseen.
SAMPLE_INTERVAL = 0.18

#: The param that overrides a refusal. One name everywhere it is accepted.
OVERRIDE_PARAM = "allow_during_playback"


def _read_timecode(tl) -> Optional[str]:
    try:
        tc = tl.GetCurrentTimecode()
    except Exception:
        return None
    return tc if isinstance(tc, str) and tc else None


def playhead_moving(tl, *, interval: float = SAMPLE_INTERVAL) -> Dict[str, Any]:
    """Whether the playhead on `tl` is advancing on its own.

    Returns {"playing": True|False|None, "timecodes": [first, second]}.
    `playing` is None when either read failed or there is no timeline.
    """
    if tl is None:
        return {"playing": None, "timecodes": []}
    first = _read_timecode(tl)
    if first is None:
        return {"playing": None, "timecodes": [None]}
    time.sleep(interval)
    second = _read_timecode(tl)
    if second is None:
        return {"playing": None, "timecodes": [first, None]}
    return {"playing": first != second, "timecodes": [first, second]}


def current_timeline(resolve):
    """The current project's current timeline, or None. Never raises."""
    try:
        pm = resolve.GetProjectManager() if resolve is not None else None
        proj = pm.GetCurrentProject() if pm else None
        return proj.GetCurrentTimeline() if proj else None
    except Exception:
        return None


def refusal_detail(what: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """The pieces of a PLAYBACK_ACTIVE error, for the caller's own _err()."""
    return {
        "message": (
            f"Playback is running in Resolve, so {what} was not attempted. A page "
            "switch while the transport is engaged has hung Resolve's main thread "
            "(Studio 19.1.3.7): every later scripting call, even a fresh connection, "
            "blocked until playback was stopped in the GUI."
        ),
        "remediation": (
            "Stop playback in Resolve (Space or K) and retry. The scripting API has no "
            f"call that stops it. Pass {OVERRIDE_PARAM}=true to go ahead anyway."
        ),
        "state": state,
    }
