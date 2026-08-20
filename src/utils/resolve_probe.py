"""Capability probes for DaVinci Resolve API objects, because `hasattr` lies.

Measured on Studio 19.1.3.7, direct connection, 42 checks across Resolve,
ProjectManager, Project, MediaPool, Timeline, Folder and TimelineItem: bare
`hasattr(obj, name)` returns **True for every name** — real, borrowed from
another object type, or entirely invented — while `getattr(obj, name)` returns
`None` for the ones that do not exist. The full record is in `api_truth` under
"hasattr() / getattr() on Resolve API objects (attribute fabrication)".

So `hasattr` on a Resolve object is a constant `True`. It carries no
information, and it fails in two directions that look nothing alike:

    if not hasattr(clip, "RemoveMotionBlur"):        # never taken
        return {"error": "requires Resolve 21+"}     # dead branch
    clip.RemoveMotionBlur(...)                       # AttributeError on 19.x

    etype = getattr(r, name) if hasattr(r, name) else name   # else never taken
    # -> etype is None on a build without that constant, not the string
    #    fallback the author wrote, and None flows on into the export call.

The second shape is the dangerous one: no exception, no refusal, just a `None`
travelling further from the mistake with every line.

Use `has_method` where the intent is "can I call this", and `api_constant`
where the intent is "does this build define this constant, else use my
fallback". Both take the form that agreed with `dir()` in all 42 checks.

One caveat worth keeping: those 42 checks were on the DIRECT connection. The
21.0.0 record of the in-app bridge fabricating callables for any name was never
re-run, so on a bridge build `callable(getattr(...))` may still over-report.
`dir()` membership is the form unaffected either way — but it is not free on
every object, and switching to it wholesale would change behaviour on a path we
have not measured. That trade is recorded here rather than made silently.
"""

from typing import Any, Optional

__all__ = ["has_method", "api_constant", "MISSING"]

#: Sentinel for "no attribute", distinct from a legitimately-None attribute.
MISSING = object()


def has_method(obj: Any, name: str) -> bool:
    """True when `name` is a callable on `obj`. The replacement for `hasattr`.

    Returns False for a missing object rather than raising, because every
    caller here is asking "is this reachable" and a None handle is one of the
    ways it is not.
    """
    if obj is None or not name:
        return False
    return callable(getattr(obj, name, None))


def api_constant(obj: Any, name: str, default: Optional[Any] = None) -> Any:
    """The Resolve constant `name`, or `default` when this build lacks it.

    Resolve exposes export/audio type constants as plain attributes
    (`resolve.EXPORT_AAF`), and callers pass the string name through unchanged
    when the constant is absent. `getattr` returning None is exactly the signal
    `hasattr` destroys, so the fallback is driven off the value, not off a
    presence test.
    """
    if obj is None or not name:
        return default
    value = getattr(obj, name, None)
    return default if value is None else value
