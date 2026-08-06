"""Resolve build comparison, and the API surfaces that are gated on a build.

The scripting API changes per **patch** release, not per major one. "Resolve 21"
is not a fine enough label to route on: `GetFairlightPresets` exists on 20.2.2
and not on 19.1.3, and issue #131 reports three surfaces that appear only in
21.0.4. An agent given the same guidance regardless of the build it is connected
to will confidently describe a method that is not there — which is exactly the
report in issue #132.

Two separate questions live here, and conflating them is the trap:

1. **Does this build have the method?** Answered from `VERSION_GATES` below,
   which records only gates we can point at evidence for.
2. **Was a recorded quirk measured on a build like mine?** Answered by comparing
   an `api_truth` entry's stamp against the live build. A fact measured on
   19.1.3.7 is a *prior* on 21.0.4, not a finding.

Neither question is answered by guessing. A symbol absent from `VERSION_GATES`
returns `unknown`, never `available` — the registry records what we know, and
most of the API has never been version-bisected. `unknown` means "probe it",
which is the honest instruction; a false `available` is how an agent ends up
insisting a method exists.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

# ── Version parsing ─────────────────────────────────────────────────────────
# Resolve reports versions three ways depending on where you ask:
#   Resolve.GetVersion()       -> [19, 1, 3, 7, ""]   (list, trailing build str)
#   Resolve.GetVersionString() -> "19.1.3.7"
#   and prose in this repo says things like "Studio 19.1.3.7 (macOS)".


def parse_version(value: Any) -> Optional[Tuple[int, ...]]:
    """Best-effort parse to a comparable tuple. None when nothing numeric is found.

    Accepts the list form, the dotted string, or a sentence containing one. Only
    leading numeric components are kept, so "21.0.4.5" -> (21, 0, 4, 5) and the
    trailing build-name string Resolve appends is dropped rather than coerced.
    """
    # bool is a subclass of int, so True would otherwise parse as version (1,) —
    # a truthy flag leaking in must not become a plausible-looking build number.
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (list, tuple)):
        parts: List[int] = []
        for item in value:
            if isinstance(item, bool):
                break
            if isinstance(item, int):
                parts.append(item)
            elif isinstance(item, str) and item.strip().isdigit():
                parts.append(int(item.strip()))
            else:
                break
        return tuple(parts) or None
    if isinstance(value, (int, float)):
        return (int(value),)
    if not isinstance(value, str):
        return None

    best: Optional[Tuple[int, ...]] = None
    token: List[str] = []
    for char in list(value) + [" "]:
        if char.isdigit() or char == ".":
            token.append(char)
            continue
        if token:
            parts = [p for p in "".join(token).split(".") if p.isdigit()]
            if parts:
                candidate = tuple(int(p) for p in parts)
                # Prefer the most specific run, so "Studio 19.1.3.7" beats a bare
                # "19" appearing earlier in the same sentence.
                if best is None or len(candidate) > len(best):
                    best = candidate
            token = []
    return best


def compare_versions(a: Any, b: Any) -> Optional[int]:
    """-1/0/1 for a<b, a==b, a>b. None when either side will not parse.

    Shorter tuples compare as though zero-padded: 21.0 == 21.0.0.
    """
    va, vb = parse_version(a), parse_version(b)
    if va is None or vb is None:
        return None
    width = max(len(va), len(vb))
    pa = va + (0,) * (width - len(va))
    pb = vb + (0,) * (width - len(vb))
    return (pa > pb) - (pa < pb)


def at_least(live: Any, required: Any) -> Optional[bool]:
    """True when `live` >= `required`. None when either will not parse."""
    result = compare_versions(live, required)
    return None if result is None else result >= 0


# ── Version gates ───────────────────────────────────────────────────────────
# Only surfaces with evidence behind them. `source` separates what this repo
# measured from what a reporter measured, because the two carry different
# weight and an agent relaying the fact should be able to say which it is.
#
#   measured  — probed live by this project
#   reported  — a user's live probe, credited, not independently reproduced
#   vendor    — stated by Blackmagic's shipped Developer/Scripting/README.txt

VERSION_GATES: List[Dict[str, Any]] = [
    {
        "symbol": "Resolve.GetFairlightPresets",
        "introduced_in": "20.2.2",
        "source": "measured",
        "note": "Absent on 19.1.3 (confirmed live). Without it the per-parameter "
                "Fairlight gap is the whole story, because the whole-mix preset "
                "workaround is unavailable.",
        "issue": 128,
    },
    {
        "symbol": "Timeline.ApplyFairlightPresetToCurrentTimeline",
        "introduced_in": "20.2.2",
        "source": "measured",
        "note": "Same gate as GetFairlightPresets; the two are only useful together.",
        "issue": 128,
    },
    {
        "symbol": "Timeline.GetSelectedClips",
        "introduced_in": "21.0.4",
        "source": "reported",
        "note": "Reported against 21.0.4.5 and listed in the shipped scripting "
                "README. This repo's selection helper duck-probes three names and "
                "reaches it by luck on builds that have it, so an absence here "
                "degrades rather than errors.",
        "issue": 131,
    },
    {
        "symbol": "MediaPoolItem.GetTimeline",
        "introduced_in": "21.0.4",
        "source": "reported",
        "note": "Reported against 21.0.4.5. Not reachable through this server yet.",
        "issue": 131,
    },
    {
        "symbol": "Project.SetRenderSettings UseFullExtents",
        "introduced_in": "21.0.4",
        "source": "vendor",
        "note": "New SetRenderSettings key per the shipped scripting README. "
                "SetRenderSettings ignores unknown keys silently, so on an older "
                "build this is dropped with no signal rather than refused.",
        "issue": 131,
    },
    {
        "symbol": "Project.SetRenderSettings AddFrameHandles",
        "introduced_in": "21.0.4",
        "source": "vendor",
        "note": "New SetRenderSettings key; ignored when full extents is enabled, "
                "so it can do nothing for two different reasons.",
        "issue": 131,
    },
    {
        "symbol": "Project.SetRenderSettings DataBurnIn",
        "introduced_in": "21.0.4",
        "source": "vendor",
        "note": "New SetRenderSettings key per the shipped scripting README.",
        "issue": 131,
    },
]

_GATES_BY_SYMBOL = {gate["symbol"].lower(): gate for gate in VERSION_GATES}

AVAILABLE = "available"
UNAVAILABLE = "unavailable"
UNKNOWN = "unknown"


def gate_for(symbol: str) -> Optional[Dict[str, Any]]:
    """The recorded gate for `symbol`, matched loosely. None if we have none."""
    if not symbol:
        return None
    needle = symbol.strip().lower()
    if needle in _GATES_BY_SYMBOL:
        return _GATES_BY_SYMBOL[needle]
    for key, gate in _GATES_BY_SYMBOL.items():
        if needle in key or key in needle:
            return gate
    return None


def availability(symbol: str, live_version: Any) -> Dict[str, Any]:
    """Is `symbol` present on `live_version`? Says `unknown` unless it knows.

    The default matters more than the positive cases. Most of the API has never
    been version-bisected, so anything outside VERSION_GATES is unknown — and an
    agent should probe rather than assert.
    """
    gate = gate_for(symbol)
    if gate is None:
        return {
            "status": UNKNOWN,
            "symbol": symbol,
            "reason": "No version gate is recorded for this symbol.",
            "remediation": (
                "Probe it on the live build with `name in dir(obj)` rather than "
                "assuming either way. Do NOT use hasattr: on a Resolve API object "
                "hasattr returns True for EVERY name, real or invented (measured on "
                "Studio 19.1.3.7), so it can only ever say yes. "
                "`callable(getattr(obj, name, None))` also works on the direct "
                "connection, but dir() membership is the form unaffected by the "
                "attribute-fabrication question — see the api_truth entry "
                "'hasattr() / getattr() on Resolve API objects'. Most of the "
                "scripting API has never been version-bisected here."
            ),
        }
    ok = at_least(live_version, gate["introduced_in"])
    if ok is None:
        return {
            "status": UNKNOWN,
            "symbol": gate["symbol"],
            "introduced_in": gate["introduced_in"],
            "source": gate["source"],
            "reason": f"Could not parse the live version ({live_version!r}).",
            "remediation": "Read resolve_control get_version and pass version_string.",
        }
    return {
        "status": AVAILABLE if ok else UNAVAILABLE,
        "symbol": gate["symbol"],
        "introduced_in": gate["introduced_in"],
        "live_version": str(live_version),
        "source": gate["source"],
        "note": gate.get("note"),
        "issue": gate.get("issue"),
        "reason": (
            f"{gate['symbol']} is recorded as introduced in {gate['introduced_in']} "
            f"({gate['source']}); this build is {live_version}."
        ),
        "remediation": None if ok else (
            f"Not present on this build. Do not offer it — say the build is too old "
            f"and name {gate['introduced_in']} as the floor."
        ),
    }


def gates_unavailable_on(live_version: Any) -> List[Dict[str, Any]]:
    """Every recorded gate this build does NOT clear, for a session preflight."""
    out = []
    for gate in VERSION_GATES:
        if at_least(live_version, gate["introduced_in"]) is False:
            out.append({
                "symbol": gate["symbol"],
                "introduced_in": gate["introduced_in"],
                "source": gate["source"],
                "issue": gate.get("issue"),
                "note": gate.get("note"),
            })
    return out


# ── Applying a recorded fact to the live build ──────────────────────────────

def measurement_relevance(verified_on: Any, live_version: Any) -> Dict[str, Any]:
    """How much weight does a fact measured on `verified_on` carry here?

    Deliberately three-valued. A fact measured on an older build is not wrong,
    it is unconfirmed — and saying so is different from both "applies" and
    "does not apply".
    """
    result = compare_versions(verified_on, live_version)
    if result is None:
        return {
            "relevance": UNKNOWN,
            "note": "Could not compare the measurement stamp with the live build.",
        }
    if result == 0:
        return {
            "relevance": "same_build",
            "note": "Measured on this exact build.",
        }
    if result < 0:
        return {
            "relevance": "older_measurement",
            "note": (
                f"Measured on {verified_on}, older than this build ({live_version}). "
                "Treat it as a prior, not a finding — Blackmagic changes the "
                "scripting API per patch release. Re-confirm before relying on it."
            ),
        }
    return {
        "relevance": "newer_measurement",
        "note": (
            f"Measured on {verified_on}, NEWER than this build ({live_version}). "
            "The behaviour described may not exist here yet, and a fix recorded "
            "there has certainly not landed here."
        ),
    }


def annotate_facts(
    facts: Sequence[Dict[str, Any]],
    live_version: Any,
    *,
    ledger_verified_on: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Copy `facts` with a `version_context` block against the live build.

    `ledger_verified_on` is the module-wide stamp — when the ledger as a whole
    was last reviewed. It is deliberately NOT used as a per-fact measurement:
    most entries record the build they were actually measured on in their prose
    (19.1.3.7, 21.0.0, 21.0.2.4 …), and attributing the ledger-wide stamp to
    each of them would invent a measurement that never happened. An entry with
    no structured `verified_on` therefore reports relevance `unknown` and says
    where to look — which is true, and points at the real gap.

    Non-destructive: entries are copied, so the ledger is never mutated.
    """
    if not live_version:
        return [dict(fact) for fact in facts]
    out = []
    for fact in facts:
        annotated = dict(fact)
        context: Dict[str, Any] = {"live_version": str(live_version)}
        stamp = fact.get("verified_on")
        if stamp:
            context.update(measurement_relevance(stamp, live_version))
            context["measured_on"] = stamp
        else:
            context["relevance"] = UNKNOWN
            context["note"] = (
                "This entry carries no structured measurement stamp; the build it "
                "was verified on is stated in its `reality` text. Read it there "
                "before relying on the fact."
            )
            if ledger_verified_on:
                context["ledger_reviewed_on"] = ledger_verified_on
        if gate_for(fact.get("symbol", "")) or fact.get("min_version"):
            context["availability"] = availability(fact.get("symbol", ""), live_version)
        annotated["version_context"] = context
        out.append(annotated)
    return out
