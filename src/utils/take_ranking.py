"""Ranking takes on what can actually be measured.

Two people asked for this after watching an automated first pass — "can it
determine which takes are worse or better when it comes to the script?" — and
one answered his own question in the next comment: "I'd trust it even less to
choose the right take."

He is right, and the honest version of this feature says so out loud.

**What this measures:** fluency. Filler density, stammered restarts, how long
the speaker goes without stumbling, and — when a script is supplied — how much
of the intended line actually got said. All countable, all reproducible, none of
them a matter of opinion.

**What this cannot measure:** whether the take is any good. In the editorial
weighting every cutter works from, emotion is roughly half the decision and
story most of the rest; fluency is not on the list at all. The take that lands
is regularly the one that stumbles — the hesitation *is* the performance, the
breath before the answer *is* the beat. A ranking that put the smoothest read on
top and called it "best" would be confidently wrong in exactly the cases that
matter most, and would train its user to stop looking.

So this returns a **fluency ranking with its evidence**, never a "best take",
and every result says which one it is. Use it to find the clean safety take, to
spot the one where someone dried, or to skip the six warm-ups before the read
got going — not to choose the performance. That is the editor's call and this
module has nothing useful to say about it.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence

from src.utils import transcript_edit as _te

#: Below this, a take is too short for rate-based metrics to mean anything —
#: three fluent words is not evidence of fluency.
MIN_MEANINGFUL_SECONDS = 3.0


def _duration(words: Sequence[Mapping[str, Any]]) -> float:
    spans = [s for s in (_te._word_span(w) for w in words) if s is not None]
    if not spans:
        return 0.0
    return max(e for _, e in spans) - min(s for s, _ in spans)


def _longest_fluent_run(words: Sequence[Mapping[str, Any]], disfluent_spans: Sequence[Dict[str, Any]]) -> float:
    """Longest stretch with no filler and no restart in it."""
    spans = [s for s in (_te._word_span(w) for w in words) if s is not None]
    if not spans:
        return 0.0
    start, end = min(s for s, _ in spans), max(e for _, e in spans)
    breaks = sorted(
        (float(d["start_seconds"]), float(d["end_seconds"]))
        for d in disfluent_spans
        if d.get("start_seconds") is not None and d.get("end_seconds") is not None
    )
    longest, cursor = 0.0, start
    for b_start, b_end in breaks:
        longest = max(longest, b_start - cursor)
        cursor = max(cursor, b_end)
    return round(max(longest, end - cursor), 3)


def _script_coverage(words: Sequence[Mapping[str, Any]], script: Optional[str]) -> Optional[Dict[str, Any]]:
    """Fraction of the script's content words that appear in the take.

    Bag-of-words on purpose: word order in a delivered read legitimately differs
    from the page, and penalising that would rank paraphrase below a stumbling
    literal reading. This answers "did they get through it", not "was it
    word-perfect".
    """
    if not script or not script.strip():
        return None
    wanted = {_te.normalize_token(t) for t in script.split()}
    wanted = {t for t in wanted if t and t not in _te.FILLER_WORDS}
    if not wanted:
        return None
    said = {_te.normalize_token(w.get("word")) for w in words}
    hit = wanted & said
    return {
        "covered": len(hit),
        "script_words": len(wanted),
        "ratio": round(len(hit) / len(wanted), 3),
        "missing_sample": sorted(wanted - hit)[:12],
    }


def score_take(
    words: Sequence[Mapping[str, Any]],
    *,
    label: str,
    script: Optional[str] = None,
) -> Dict[str, Any]:
    """Countable fluency metrics for one take. No judgement of performance."""
    duration = _duration(words)
    fillers = _te.detect_fillers(words)
    false_starts = _te.detect_false_starts(words)
    per_minute = (len(fillers) / (duration / 60.0)) if duration > 0 else 0.0
    wpm = (len(words) / (duration / 60.0)) if duration > 0 else 0.0

    result: Dict[str, Any] = {
        "label": label,
        "duration_seconds": round(duration, 2),
        "word_count": len(words),
        "words_per_minute": round(wpm, 1),
        "filler_count": len(fillers),
        "fillers_per_minute": round(per_minute, 2),
        "false_start_count": len(false_starts),
        "longest_fluent_run_seconds": _longest_fluent_run(words, list(fillers) + list(false_starts)),
        "script_coverage": _script_coverage(words, script),
        "reliable": duration >= MIN_MEANINGFUL_SECONDS,
    }
    if not result["reliable"]:
        result["caveat"] = (
            f"only {result['duration_seconds']}s of speech — too short for these "
            "rates to mean anything; ranked last rather than dropped so it stays visible"
        )
    result["fluency_score"] = _fluency_score(result)
    result["evidence"] = _evidence_line(result)
    return result


def _fluency_score(m: Mapping[str, Any]) -> float:
    """0-100, higher = more fluent. Deliberately simple and explainable.

    Not tuned or learned: a weighting nobody can read is not reviewable, and the
    components are published alongside so a reader can disagree with the
    arithmetic instead of having to trust it.
    """
    if not m["reliable"]:
        return 0.0
    score = 100.0
    score -= min(40.0, float(m["fillers_per_minute"]) * 5.0)
    score -= min(30.0, float(m["false_start_count"]) * 6.0)
    coverage = m.get("script_coverage")
    if coverage:
        score -= (1.0 - float(coverage["ratio"])) * 30.0
    return round(max(0.0, score), 1)


def _evidence_line(m: Mapping[str, Any]) -> str:
    bits = [
        f"{m['filler_count']} fillers ({m['fillers_per_minute']}/min)",
        f"{m['false_start_count']} restarts",
        f"longest clean run {m['longest_fluent_run_seconds']}s",
    ]
    coverage = m.get("script_coverage")
    if coverage:
        bits.append(f"{int(coverage['ratio'] * 100)}% of script covered")
    return "; ".join(bits)


#: Attached to every ranking. Not a disclaimer to be skimmed — it is the
#: difference between a useful tool and a misleading one.
RANKING_CAVEAT = (
    "This ranks FLUENCY, not quality. It counts fillers, restarts and script "
    "coverage — all measurable. It cannot hear performance, and performance is "
    "most of what makes a take the right one. The take that plays best is "
    "regularly the least fluent one: the hesitation is often the acting. Use "
    "this to find the clean safety take or to skip the warm-ups, not to choose "
    "the read."
)


def rank_takes(
    takes: Sequence[Mapping[str, Any]],
    *,
    script: Optional[str] = None,
) -> Dict[str, Any]:
    """Rank takes by measurable fluency, with the evidence and the caveat.

    Each take: `{"label": str, "words": [transcript_words rows]}`.
    """
    if not takes:
        return {"success": False, "error": "No takes supplied"}

    scored = [
        score_take(t.get("words") or [], label=str(t.get("label") or f"take {i + 1}"), script=script)
        for i, t in enumerate(takes)
    ]
    scored.sort(key=lambda s: (-s["fluency_score"], -s["longest_fluent_run_seconds"]))
    for position, take in enumerate(scored, start=1):
        take["rank"] = position

    unreliable = [s["label"] for s in scored if not s["reliable"]]
    return {
        "success": True,
        "kind": "take_ranking",
        "ranked_by": "fluency",
        "take_count": len(scored),
        "takes": scored,
        "most_fluent": scored[0]["label"] if scored else None,
        "script_supplied": bool(script and script.strip()),
        "unreliable_takes": unreliable,
        "caveat": RANKING_CAVEAT,
        "note": (
            f"Ranked {len(scored)} takes by fluency. "
            + (f"{len(unreliable)} {'take was' if len(unreliable) == 1 else 'takes were'} "
               "too short to score reliably and sit at the bottom — not necessarily "
               "bad, just unmeasurable. "
               if unreliable else "")
            + "The top entry is the most fluent, which is NOT the same as the best."
        ),
    }
