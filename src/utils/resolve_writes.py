"""Resolve mutators whose return value must not be discarded.

Every write in the DaVinci Resolve scripting API reports itself with a bare
boolean and nothing else. Dropping that boolean turns a failed write into a
successful-looking no-op, which is the only failure shape worse than a crash:
the tool reports what it meant to do, and the project does not have it.

`SetCurrentTimeline` is the sharpest case in this repo, which is why it lives
here. `AppendToTimeline`, `GetCurrentTimeline` and every other "current
timeline" call writes to whatever the PROJECT believes is current, never to the
handle in scope, so a discarded `False` sends an assembly to the timeline the
editor was looking at while the caller reports the new timeline's name and id.
"""

from typing import Any, Dict, Optional, Tuple


def unique_id(obj: Any) -> Optional[str]:
    """`obj.GetUniqueId()`, or None. Never raises."""
    if obj is None:
        return None
    try:
        return obj.GetUniqueId()
    except Exception:
        return None


def set_current_timeline(project: Any, timeline: Any) -> Tuple[bool, Dict[str, Any]]:
    """Switch the project's current timeline. Returns (ok, detail).

    The bare bool is not trusted on its own. A Resolve attached to no database
    answers version queries normally while every project mutation returns False
    or None, and a `True` that did not take has been observed there, so the
    switch is confirmed by reading the current timeline back.

    When the readback is unavailable (a build or transport that does not answer
    `GetCurrentTimeline`) the bool is the only evidence there is, and it is
    used. That is a weaker check, not a reason to refuse the work.

    `detail` always carries `returned`, `wanted_timeline_id`,
    `current_timeline_id` and, on an exception, `exception`.
    """
    detail: Dict[str, Any] = {
        "returned": None,
        "wanted_timeline_id": unique_id(timeline),
        "current_timeline_id": None,
    }
    try:
        detail["returned"] = project.SetCurrentTimeline(timeline)
    except Exception as exc:
        detail["exception"] = str(exc)
        return False, detail

    try:
        detail["current_timeline_id"] = unique_id(project.GetCurrentTimeline())
    except Exception:
        detail["current_timeline_id"] = None

    wanted = detail["wanted_timeline_id"]
    current = detail["current_timeline_id"]
    if wanted is not None and current is not None:
        return wanted == current, detail
    return bool(detail["returned"]), detail


def describe_switch_failure(detail: Dict[str, Any], what: str) -> str:
    """One line naming what did not happen, for a log or an error envelope."""
    if "exception" in detail:
        return (
            f"Could not switch the current timeline before {what}: "
            f"{detail['exception']}. Nothing was written."
        )
    return (
        f"Could not switch the current timeline before {what}. "
        f"SetCurrentTimeline returned {detail.get('returned')!r} and the current "
        f"timeline is still {detail.get('current_timeline_id')!r}, not "
        f"{detail.get('wanted_timeline_id')!r}. Continuing would write to the "
        "wrong timeline while reporting success."
    )
