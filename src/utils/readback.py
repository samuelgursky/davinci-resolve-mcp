"""Readback verification for unreliable Resolve API mutations.

The Resolve scripting API frequently returns a success value that does not
reflect what actually happened: ``AutoSyncAudio`` returns a boolean unrelated to
whether clips linked, ``AppendToTimeline`` may not hand back the new item id,
many setters return ``True`` regardless of effect, and Fusion ``Paste()`` can
report nothing while creating nothing. The defense is to **verify by reading the
real post-state back** instead of trusting the return value.

``verify_by_readback`` is the small primitive every mutating op can use. A
mutation that reports success while the readback disagrees is a *contradiction*
— the single most valuable reliability signal — and is logged.
"""
import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("davinci-resolve-mcp")

# Process-level tally of verification outcomes — lightweight observability into
# how often the Resolve API's self-reported success matches reality. A rising
# `contradicted` count is the signal worth watching.
_STATS = {"total": 0, "verified": 0, "contradicted": 0, "unverified": 0}


def verification_stats():
    """Return a copy of the process-level verification tally."""
    return dict(_STATS)


def reset_verification_stats():
    for k in _STATS:
        _STATS[k] = 0


def verify_by_readback(
    mutate: Callable[[], Any],
    observe: Callable[[], Any],
    *,
    snapshot: Optional[Callable[[], Any]] = None,
    compare: Optional[Callable[[Any, Any], Dict[str, Any]]] = None,
    intent: Optional[Dict[str, Any]] = None,
    label: Optional[str] = None,
) -> Dict[str, Any]:
    """Run a mutation and verify it by reading actual state back.

    Args:
        mutate:   performs the Resolve call; its return value is the unreliable
                  ``success_raw``.
        observe:  reads the relevant state AFTER the mutation.
        snapshot: optional — captures pre-state for delta comparisons (passed to
                  ``compare`` as ``before``).
        compare:  ``(before, observed) -> dict`` merged into the result. It should
                  set ``verified: bool``. Defaults to ``verified = truthy(observed)``.
        intent:   optional description of what we meant to do (for the ledger).
        label:    optional op name, used in the contradiction log line.

    Returns a dict with at least ``success_raw`` and ``verified``, plus whatever
    ``compare`` contributed and (if given) ``intent``.
    """
    before = snapshot() if snapshot is not None else None
    raw = mutate()
    observed = observe()

    result: Dict[str, Any] = {"success_raw": bool(raw), "observed": observed}
    if compare is not None:
        result.update(compare(before, observed))
    else:
        result["verified"] = bool(observed)
    if intent is not None:
        result["intent"] = intent

    # A contradiction — reported success but the readback disagrees — is the
    # signal worth surfacing loudly.
    _STATS["total"] += 1
    if result.get("success_raw") and not result.get("verified"):
        logger.warning(
            "readback contradiction%s: API reported success but post-state "
            "verification failed%s",
            f" [{label}]" if label else "",
            f" (intent={intent})" if intent else "",
        )
        result["contradiction"] = True
        _STATS["contradicted"] += 1
    else:
        result["contradiction"] = False
        if result.get("verified"):
            _STATS["verified"] += 1
        else:
            _STATS["unverified"] += 1

    return result
