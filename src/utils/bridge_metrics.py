"""Instrumentation for counting DaVinci Resolve bridge round-trips.

Every attribute access and method call on a Resolve object is a COM/socket
round-trip — the dominant cost of most operations. Before optimizing (or adding
a cache), you have to *measure* where the round-trips concentrate. This module
provides an opt-in counting proxy that wraps a Resolve handle and tallies
attribute accesses and method calls, so a hot path's real bridge cost is
visible instead of guessed.

This is the measurement half of the bridge-perf work. A property cache is only
worth building once measurement shows a clear, repeated-read hot spot — don't
cache blind.

Example:

    counts = {}
    rp = CountingProxy(resolve, counts)
    rp.GetProjectManager().GetCurrentProject().GetName()
    print(counts)  # {'attr_access': N, 'calls': M}
"""
from typing import Any, Dict, Optional


class CountingProxy:
    """Wrap a Resolve object, counting attribute accesses and method calls.

    Method return values that are themselves objects are wrapped too, so a whole
    call chain through the bridge is counted. Primitives are returned as-is.
    """

    __slots__ = ("_target", "_counter")

    def __init__(self, target: Any, counter: Dict[str, int]):
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_counter", counter)
        counter.setdefault("attr_access", 0)
        counter.setdefault("calls", 0)

    def __getattr__(self, name: str) -> Any:
        counter = object.__getattribute__(self, "_counter")
        target = object.__getattribute__(self, "_target")
        counter["attr_access"] += 1
        attr = getattr(target, name)
        if callable(attr):
            def wrapped(*args: Any, **kwargs: Any) -> Any:
                counter["calls"] += 1
                result = attr(*args, **kwargs)
                return _maybe_wrap(result, counter)
            return wrapped
        return _maybe_wrap(attr, counter)


_PRIMITIVE = (str, int, float, bool, bytes, type(None))


def _maybe_wrap(value: Any, counter: Dict[str, int]) -> Any:
    if isinstance(value, _PRIMITIVE):
        return value
    if isinstance(value, (list, tuple)):
        # Wrap object elements so traversals (e.g. clip lists) are counted.
        return type(value)(_maybe_wrap(v, counter) for v in value)
    if isinstance(value, dict):
        return {k: _maybe_wrap(v, counter) for k, v in value.items()}
    # Likely a Resolve API object — wrap so its further use is counted.
    return CountingProxy(value, counter)


def measure(fn, target: Any) -> Dict[str, int]:
    """Run ``fn(proxy)`` against a counting proxy of ``target``; return the counts.

    ``fn`` receives the proxy and should exercise the operation under study.
    """
    counter: Dict[str, int] = {}
    proxy = CountingProxy(target, counter)
    fn(proxy)
    return counter
