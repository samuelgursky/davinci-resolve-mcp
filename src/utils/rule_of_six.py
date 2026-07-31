"""The Rule of Six, as an audit that knows what it cannot see.

The classical formulation weights its own criteria, which makes them unusually
codifiable and sets
exactly one trap:

    emotion 51% · story 23% · rhythm 10% · eye-trace 7% · 2D plane 5% · 3D space 4%

**The weighting is almost perfectly inverted against measurability.** Everything
a machine can compute is the bottom four, and it sums to 26%.

Two conclusions are available and both are wrong. "Don't build it" throws away
real value — a cut that is technically clean is precisely the cut where a human
should spend attention on emotion instead of hunting for a stage-line violation.
"Approximate the top two" is far worse: face-based affect inference scoring the
51% would be confidently wrong exactly where being wrong costs most, and would
train its reader to stop looking.

So this computes the bottom four and **abstains loudly** on the top two.
Emotion and story appear in every single audit, carrying their weights, marked
`NOT_ASSESSED`, and cannot be suppressed.

## Three states that must never collapse

- `NOT_ASSESSED` — permanent. Emotion and story. No future release changes this.
- `NOT_IMPLEMENTED` — a criterion this build does not compute yet.
- `PASS` / `FLAG` — actually evaluated.

Collapsing the first two would let the tool grow *quieter* as it grew more
capable, which is backwards. Collapsing either into `PASS` is the
`unverified ≠ clean` failure this codebase has spent a lot of effort avoiding.

## Two ordering axes

The iron rule of the formulation: **always sacrifice lower priorities to preserve higher
ones.** A cut that breaks 3D continuity to serve rhythm is *correct*, and a tool
that nags about the 4% above the 10% has inverted the craft. So `CRITERION_WEIGHTS`
is the ordering key — not detectability, which is the order most editing tools
accidentally use because continuity errors are the easiest thing to find.

A second, orthogonal rule from the same tradition is just as real: **"movie first, scene
second, moment third"** — sacrifice a moment to save a scene, a scene to save
the film. That is a *scope* ranking, not a criterion ranking, and a finding that
threatens the sequence outranks one that threatens a single cut regardless of
which criterion it belongs to. Both axes are in the sort.

## No composite score

There is deliberately no field any caller could mistake for an overall cut
quality number. Averaging four criteria worth 26% into one number implies the
number describes the cut. It describes a quarter of it, and the least important
quarter. Per-criterion or nothing.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

#: The Rule of Six weights, verbatim. The ordering key for every
#: finding in this program.
CRITERION_WEIGHTS = {
    "emotion": 0.51,
    "story": 0.23,
    "rhythm": 0.10,
    "eye_trace": 0.07,
    "two_d_plane": 0.05,
    "three_d_space": 0.04,
}

#: Human-readable, in weighted order.
CRITERION_LABELS = {
    "emotion": "Emotion — what should the audience feel at this moment?",
    "story": "Story — does the cut advance the narrative?",
    "rhythm": "Rhythm — is this the rhythmically right moment?",
    "eye_trace": "Eye-trace — does the cut respect where the eye is focused?",
    "two_d_plane": "2D plane — does it honour screen geography?",
    "three_d_space": "3D space — does it maintain physical continuity?",
}

#: Permanently unmeasurable. Not a TODO. No release changes this.
UNMEASURABLE = ("emotion", "story")

#: Scope axis: sacrifice a moment to save a scene, a scene to save the
#: film. Lower sorts first.
SCOPE_RANK = {"movie": 0, "sequence": 1, "scene": 2, "moment": 3}

STATE_PASS = "PASS"
STATE_FLAG = "FLAG"
STATE_NOT_ASSESSED = "NOT_ASSESSED"
STATE_NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


def _criterion_row(name: str, state: str, *, detail: str) -> Dict[str, Any]:
    return {
        "criterion": name,
        "label": CRITERION_LABELS[name],
        "weight": CRITERION_WEIGHTS[name],
        "state": state,
        "detail": detail,
    }


def abstention_rows() -> List[Dict[str, Any]]:
    """The 74% this tool does not and will not measure.

    Present in every audit. Not suppressible — the whole design rests on the
    reader seeing them.
    """
    return [
        _criterion_row(
            "emotion", STATE_NOT_ASSESSED,
            detail=(
                "51% of this decision, and not measurable. No affect inference is "
                "performed and none is planned: a number here would be believed and "
                "would be wrong in the cases that matter most."
            ),
        ),
        _criterion_row(
            "story", STATE_NOT_ASSESSED,
            detail="23% of this decision, and not measurable.",
        ),
    ]


def coverage(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """How much of the decision this audit actually looked at."""
    assessed = [r for r in rows if r["state"] in (STATE_PASS, STATE_FLAG)]
    weight = sum(float(r["weight"]) for r in assessed)
    return {
        "assessed_criteria": len(assessed),
        "total_criteria": len(CRITERION_WEIGHTS),
        "weight_assessed": round(weight, 2),
        "weight_unmeasurable": round(sum(CRITERION_WEIGHTS[c] for c in UNMEASURABLE), 2),
        "statement": (
            f"{len(assessed)} of {len(CRITERION_WEIGHTS)} criteria assessed, covering "
            f"{round(weight * 100)}% of the decision. The remaining "
            f"{round((1 - weight) * 100)}% includes emotion (51%) and story (23%), "
            "which are not measurable and are your call."
        ),
    }


def sort_findings(findings: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Order by scope then by criterion weight, never by count.

    Sorting by how many of each kind were found — the intuitive default — would
    bury a single rhythm problem under fifty continuity nits, which is precisely
    the inversion the iron rule forbids.
    """
    return sorted(
        findings,
        key=lambda f: (
            SCOPE_RANK.get(str(f.get("scope") or "moment"), 9),
            -CRITERION_WEIGHTS.get(str(f.get("criterion") or ""), 0.0),
            str(f.get("at") or ""),
        ),
    )


def audit(
    *,
    timeline_name: Optional[str] = None,
    criterion_results: Optional[Mapping[str, Mapping[str, Any]]] = None,
    findings: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Assemble a Rule of Six audit from whichever criteria have been computed.

    `criterion_results` maps a measurable criterion name to
    `{"state": PASS|FLAG, "detail": str}`. Anything absent is reported as
    `NOT_IMPLEMENTED` — never as a pass.
    """
    computed = dict(criterion_results or {})
    rows: List[Dict[str, Any]] = []

    for name in CRITERION_WEIGHTS:
        if name in UNMEASURABLE:
            continue
        result = computed.get(name)
        if result is None:
            rows.append(_criterion_row(
                name, STATE_NOT_IMPLEMENTED,
                detail="not computed by this build — absence of a finding is not a pass",
            ))
            continue
        state = str(result.get("state") or STATE_FLAG).upper()
        if state not in (STATE_PASS, STATE_FLAG):
            raise ValueError(
                f"criterion {name!r} returned state {state!r}; a computed criterion "
                f"must be {STATE_PASS} or {STATE_FLAG}"
            )
        rows.append(_criterion_row(name, state, detail=str(result.get("detail") or "")))

    all_rows = abstention_rows() + rows
    all_rows.sort(key=lambda r: -CRITERION_WEIGHTS[r["criterion"]])

    ordered = sort_findings(findings or [])
    return {
        "success": True,
        "kind": "rule_of_six_audit",
        "timeline_name": timeline_name,
        "criteria": all_rows,
        "coverage": coverage(all_rows),
        "findings": ordered,
        "finding_count": len(ordered),
        "ordering": (
            "Findings are ordered by scope (movie > sequence > scene > moment) then "
            "by criterion weight — never by how many of each kind were found. The "
            "established rule is to sacrifice lower priorities to preserve higher ones, "
            "so a rhythm problem (10%) always outranks a screen-geography one (5%)."
        ),
        "note": (
            "Emotion (51%) and story (23%) are NOT ASSESSED and never will be. A "
            "clean report here means the measurable quarter is clean — which is "
            "exactly the point at which the 74% that matters becomes worth your "
            "attention. There is deliberately no overall score."
        ),
    }
