"""Refuse a subtitle clipInfo before AppendToTimeline can abort Resolve.

On Studio 21.1.2.10 (Windows), ``MediaPool.AppendToTimeline`` with a clipInfo
dict whose ``mediaPoolItem`` has ``GetClipProperty("Type") == "Subtitle"``
aborts the process: assertion at ``Sm2MpObject.cpp:546``, reproduced twice
(issue #335). The plain list form, ``AppendToTimeline([item])``, does not
crash, and on that build it also places nothing.

The same abort was then reported on free 21.0.3.7 (macOS, issue #335).
Studio 21.0.4.5 had been reported working (issue #169), one patch later and
on a different edition, which is not a narrow enough gap to keep forwarding
a call that kills Resolve. Every 21.0 build and newer is refused, and so is
a subtitle clipInfo when the connected version cannot be read.
"""

from typing import Any, Optional

from src.utils.resolve_versions import at_least

#: First build line on which the clipInfo form is refused.
FLOOR = "21.0"

MEASURED = (
    "Reported on DaVinci Resolve Studio 21.1.2.10 (Windows), reproduced 2/2: "
    "MediaPool.AppendToTimeline with a clipInfo for a Type=Subtitle MediaPoolItem "
    "aborts Resolve (Sm2MpObject.cpp:546). The plain clip list does not crash and "
    "places nothing. The same abort was reported on free 21.0.3.7 (macOS, "
    "issue #335), once with media_type and once without. ImportMedia + "
    "AppendToTimeline was reported working on Studio 21.0.4.5 (issue #169). "
    "The refusal covers that build too: it is one patch away from a crash."
)


def is_subtitle_item(item: Any) -> bool:
    """True when the MediaPoolItem reports Type Subtitle.

    A missing getter, a failed read, or a non-string (Resolve returns False
    for an unknown property) is not a subtitle. Only an explicit type match
    refuses the call.
    """
    getter = getattr(item, "GetClipProperty", None)
    if not callable(getter):
        return False
    try:
        value = getter("Type")
    except Exception:
        return False
    if not isinstance(value, str):
        return False
    return value.strip().casefold() == "subtitle"


def refuses(version: Any) -> bool:
    """True when this version must not receive a subtitle clipInfo.

    ``None`` from :func:`at_least` means the version did not parse. That is
    refused too.
    """
    affected = at_least(version, FLOOR)
    return affected is None or affected


def refusal_message(payload: Any, version: Any, index: Optional[int] = None) -> Optional[str]:
    """The refusal text, or None when the payload may be forwarded.

    ``payload`` is one clipInfo dict or a list of them. Clip objects, the
    plain ``AppendToTimeline([item])`` form, are not clipInfos and are left
    alone.
    """
    rows = [payload] if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return None
    hits = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        item = row.get("mediaPoolItem")
        if item is not None and is_subtitle_item(item):
            hits.append(i)
    if not hits or not refuses(version):
        return None
    shown = hits[0] if index is None else index
    if at_least(version, FLOOR) is None:
        return (
            f"clip_infos[{shown}] is a subtitle MediaPoolItem, and the connected "
            "Resolve version could not be read. AppendToTimeline with a clipInfo "
            "for that item aborts Resolve on Studio 21.1.2.10 (Sm2MpObject.cpp:546) "
            "and on free 21.0.3.7 (issue #335), so the call is refused."
        )
    return (
        f"clip_infos[{shown}] is a subtitle MediaPoolItem. On Resolve {version}, "
        "AppendToTimeline with a clipInfo for that item is refused: it aborts "
        "Resolve on Studio 21.1.2.10 (Sm2MpObject.cpp:546) and on free 21.0.3.7 "
        "(issue #335)."
    )
