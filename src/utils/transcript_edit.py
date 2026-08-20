"""Word-level transcript editing: cut plans with a reason per cut, and search.

Silence-based tightening (`silence_ripple`) can only remove the quiet. It cannot
remove an "um" that lands mid-phrase, a stammered restart, or a trailing "you
know" — those are *audible*, so no gate finds them. This module works on the
words themselves and is complementary, not a replacement.

What already existed and is reused rather than reimplemented:

- `transcript_words` — word-level timings in the strata DB.
- `detect_hesitations` — filler words (uh/um/er...), already an event track.
- `pause` events — already detected from the energy curve.

What is new here:

- **False-start detection.** Immediate self-repetition ("I— I think we", "we we
  went"), which nothing upstream models.
- **Cut-plan assembly.** Turning those signals into `keep_ranges` with a
  human-readable reason attached to every removal, so a plan can be argued with
  rather than only accepted or rejected.
- **Cross-clip spoken search.** `query_transcript_words` matches a substring
  within one clip; this searches phrases, word sets, or regex across a whole
  shoot and returns hits with surrounding context.

## Why every cut carries a reason

A keep-range list is not reviewable. "Removed 4.2s" tells an editor nothing;
"removed 'um' at 12.4s" and "removed a false start: 'I think— I think'" tells
them whether the pass understood the material. Reasons are the difference
between a plan a human can approve and one they have to re-derive.

## Honest limits

False-start detection is a heuristic and is flagged as such. It cannot tell
rhetorical repetition ("no, no, no") from a stammer, so it only fires on tight
repeats — emphasis is spoken evenly, a stammer truncates. It will still
occasionally take a deliberate repetition; that is why nothing here executes,
it only proposes.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: Filler words. Shared with the strata analyzer's set so the two agree; kept as
#: a local import to avoid a heavy module-level dependency.
try:
    from src.utils.strata_analyzers import HESITATION_WORDS as _HESITATION_WORDS
except Exception:  # pragma: no cover - defensive; the set is small enough to inline
    _HESITATION_WORDS = {"uh", "um", "er", "erm", "uhm", "hmm", "mm", "mhm", "ah", "eh"}

FILLER_WORDS = frozenset(_HESITATION_WORDS)

#: Trailing verbal tics — removable only at a phrase end, where they are padding.
#: Mid-phrase they usually carry meaning ("you know what I mean").
TRAILING_TICS = frozenset({"you know", "i mean", "sort of", "kind of", "right"})

#: Two identical tokens closer than this read as a stammer; wider apart they
#: read as deliberate emphasis, which must survive.
FALSE_START_MAX_GAP_S = 0.6
#: Longest repeated run treated as a restart. Beyond this it is a real re-take
#: and a human should choose.
FALSE_START_MAX_NGRAM = 4
#: Pauses longer than this are candidates for collapsing.
DEFAULT_MAX_PAUSE_S = 0.6
#: ...leaving this much either side, so speech does not butt against a cut.
DEFAULT_HANDLE_S = 0.15
#: Removals shorter than this are not worth an edit point.
DEFAULT_MIN_CUT_S = 0.15

_PUNCT_RE = re.compile(r"^[^\w']+|[^\w']+$")


def normalize_token(word: Any) -> str:
    return _PUNCT_RE.sub("", str(word or "").strip().lower())


def _word_span(word: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    start = word.get("start_seconds", word.get("start"))
    end = word.get("end_seconds", word.get("end"))
    if not isinstance(start, (int, float)):
        return None
    if not isinstance(end, (int, float)) or end < start:
        end = start
    return float(start), float(end)


# ── detection ────────────────────────────────────────────────────────────────


def detect_false_starts(words: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Immediate self-repetition — the first run of the pair is the discard.

    Scans longest-run-first (4 words down to 1) so "I think that / I think that"
    is reported as one restart rather than three separate word repeats.

    Heuristic, and deliberately tight: both runs must be adjacent in the word
    stream and the gap between them under `FALSE_START_MAX_GAP_S`. Evenly-spaced
    repetition is rhetorical and is left alone.
    """
    tokens = [normalize_token(w.get("word")) for w in words]
    spans = [_word_span(w) for w in words]
    found: List[Dict[str, Any]] = []
    consumed: set[int] = set()

    for size in range(FALSE_START_MAX_NGRAM, 0, -1):
        for i in range(len(tokens) - 2 * size + 1):
            idx_first = range(i, i + size)
            idx_second = range(i + size, i + 2 * size)
            if any(j in consumed for j in list(idx_first) + list(idx_second)):
                continue
            first = tokens[i : i + size]
            second = tokens[i + size : i + 2 * size]
            if not all(first) or first != second:
                continue
            span_a, span_b = spans[i], spans[i + size]
            if span_a is None or span_b is None:
                continue
            gap = span_b[0] - spans[i + size - 1][1]
            if gap > FALSE_START_MAX_GAP_S:
                continue  # evenly spaced — emphasis, not a stammer
            end_of_first = spans[i + size - 1][1]
            found.append({
                "start_seconds": round(span_a[0], 3),
                "end_seconds": round(end_of_first, 3),
                "words": " ".join(words[j].get("word", "") for j in idx_first).strip(),
                "repeated_as": " ".join(words[j].get("word", "") for j in idx_second).strip(),
                "gap_seconds": round(gap, 3),
                "confidence": "low" if size == 1 else "medium",
            })
            consumed.update(idx_first)
    found.sort(key=lambda item: item["start_seconds"])
    return found


def detect_fillers(words: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Standalone filler words. Mirrors the strata analyzer's word set."""
    out: List[Dict[str, Any]] = []
    for word in words:
        span = _word_span(word)
        if span is None:
            continue
        if normalize_token(word.get("word")) in FILLER_WORDS:
            out.append({
                "start_seconds": round(span[0], 3),
                "end_seconds": round(span[1], 3),
                "words": str(word.get("word") or "").strip(),
                "confidence": "high",
            })
    return out


#: Terminal punctuation on the *preceding* word. A pause after one of these is
#: where a thought ended, which is where an audience expects to breathe.
_SENTENCE_FINAL_PUNCT = (".", "?", "!", "…")
#: A pause here separates clauses — a real beat, but a smaller one.
_CLAUSE_FINAL_PUNCT = (",", ";", ":", "—", "–")

#: How much longer a *sentence-final* pause must be before it counts as dead air.
#:
#: A silence gate cannot tell these apart, because acoustically they are
#: identical: 900 ms of room tone after "…and that changed everything." and
#: 900 ms of room tone in the middle of "the thing is — uh — we had to leave"
#: measure the same. Editorially they are opposites. The first is the beat that
#: lets the line land; removing it is the single most common way an automated
#: tighten makes a cut feel machine-made. The second is a stumble.
#:
#: So sentence-final pauses are not exempt — a four-second hole after a full
#: stop is still dead air — they simply have to be much longer before we touch
#: them. Clause-final sits between the two.
BREATHING_ROOM_MULTIPLIER = 2.5
CLAUSE_PAUSE_MULTIPLIER = 1.5


def classify_pause(prev_word: Optional[Dict[str, Any]], next_word: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Where a pause sits syntactically, which decides whether it is craft or noise.

    Honest limit: this reads punctuation, so it is only as good as the
    transcriber's. ASR output with no punctuation at all cannot be classified —
    that returns `unpunctuated` with low confidence rather than silently
    assuming every pause is removable, which would reintroduce exactly the
    behaviour this function exists to prevent.
    """
    raw = str((prev_word or {}).get("word") or "").strip()
    if not raw:
        return {"position": "unknown", "is_breathing_room": False,
                "multiplier": 1.0, "confidence": "low",
                "reason": "no preceding word text"}
    if raw.endswith(_SENTENCE_FINAL_PUNCT):
        return {"position": "sentence_final", "is_breathing_room": True,
                "multiplier": BREATHING_ROOM_MULTIPLIER, "confidence": "high",
                "reason": f"pause follows end of sentence ({raw[-1]!r}) — breathing room"}
    if raw.endswith(_CLAUSE_FINAL_PUNCT):
        return {"position": "clause_final", "is_breathing_room": True,
                "multiplier": CLAUSE_PAUSE_MULTIPLIER, "confidence": "medium",
                "reason": f"pause follows a clause break ({raw[-1]!r})"}
    # No terminal punctuation. If nothing in the transcript is punctuated at all
    # we must not read that as "every pause is mid-sentence".
    return {"position": "intra_clause", "is_breathing_room": False,
            "multiplier": 1.0, "confidence": "high",
            "reason": "pause falls inside a phrase — not a beat the writing asked for"}


def transcript_is_punctuated(words: Sequence[Dict[str, Any]]) -> bool:
    """Whether this transcript carries sentence punctuation at all.

    Used to downgrade pause classification honestly: without punctuation every
    pause looks intra-clause, and acting on that would strip every beat in the
    programme.
    """
    for w in words:
        raw = str((w or {}).get("word") or "").strip()
        if raw.endswith(_SENTENCE_FINAL_PUNCT) or raw.endswith(_CLAUSE_FINAL_PUNCT):
            return True
    return False


def detect_long_pauses(
    words: Sequence[Dict[str, Any]],
    *,
    max_pause: float,
    handle: float,
    min_cut: float,
    preserve_breathing_room: bool = True,
) -> List[Dict[str, Any]]:
    """Gaps between words longer than `max_pause`, trimmed by a handle each side.

    Word-boundary based, so unlike a silence gate this never cuts into a word
    that merely dipped below a threshold.

    With `preserve_breathing_room` (the default), the threshold is scaled by the
    pause's syntactic position — see `classify_pause`. A pause after a full stop
    has to be markedly longer than one mid-phrase before it is proposed for
    removal, because the first is usually deliberate and the second usually is
    not. Set it False to treat every gap as equal, which is the older behaviour.
    """
    out: List[Dict[str, Any]] = []
    indexed = [(i, s) for i, s in enumerate(_word_span(w) for w in words) if s is not None]
    punctuated = transcript_is_punctuated(words) if preserve_breathing_room else False
    for (i_prev, (_, prev_end)), (_, (next_start, _)) in zip(indexed, indexed[1:]):
        gap = next_start - prev_end
        if preserve_breathing_room and punctuated:
            classification = classify_pause(words[i_prev], None)
        else:
            classification = {
                "position": "unpunctuated" if preserve_breathing_room else "unclassified",
                "is_breathing_room": False,
                "multiplier": 1.0,
                "confidence": "low" if preserve_breathing_room else "high",
                "reason": (
                    "transcript carries no punctuation, so a pause cannot be placed "
                    "syntactically — treated as removable, review before accepting"
                    if preserve_breathing_room
                    else "breathing-room preservation disabled by caller"
                ),
            }
        effective_max = max_pause * float(classification["multiplier"])
        if gap <= effective_max:
            continue
        start, end = prev_end + handle, next_start - handle
        if end - start >= min_cut:
            out.append({
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
                "pause_seconds": round(gap, 3),
                "confidence": classification["confidence"],
                "pause_position": classification["position"],
                "threshold_seconds": round(effective_max, 3),
                "classification_reason": classification["reason"],
            })
    return out


# ── plan assembly ────────────────────────────────────────────────────────────


def _merge(removals: List[Dict[str, Any]], *, bridge_gap: float = 0.0) -> List[Dict[str, Any]]:
    """Merge overlapping removals, keeping every contributing reason.

    `bridge_gap` also absorbs removals separated by less than one minimum cut.
    Two cuts either side of a 25 ms sliver do not produce an edit a human wants —
    they produce a 25 ms clip nobody can see and an extra pair of edit points.
    If the fragment that would survive is too short to be a shot, it is not
    worth keeping, so the removals either side become one.
    """
    if not removals:
        return []
    ordered = sorted(removals, key=lambda r: (r["start_seconds"], r["end_seconds"]))
    merged = [dict(ordered[0], reasons=[ordered[0]["reason"]])]
    for item in ordered[1:]:
        last = merged[-1]
        if item["start_seconds"] <= last["end_seconds"] + bridge_gap:
            last["end_seconds"] = max(last["end_seconds"], item["end_seconds"])
            if item["reason"] not in last["reasons"]:
                last["reasons"].append(item["reason"])
        else:
            merged.append(dict(item, reasons=[item["reason"]]))
    for item in merged:
        item.pop("reason", None)
        item["duration_seconds"] = round(item["end_seconds"] - item["start_seconds"], 3)
    return merged


def plan_transcript_cuts(
    words: Sequence[Dict[str, Any]],
    *,
    range_start: float = 0.0,
    range_end: Optional[float] = None,
    remove_fillers: bool = True,
    remove_false_starts: bool = True,
    collapse_pauses: bool = True,
    max_pause: float = DEFAULT_MAX_PAUSE_S,
    handle: float = DEFAULT_HANDLE_S,
    min_cut: float = DEFAULT_MIN_CUT_S,
) -> Dict[str, Any]:
    """Propose word-level removals and the keep-ranges that survive them.

    Returns `keep_ranges` in the same shape the variant assembler already takes,
    plus `removals` where every entry states *why* — see the module docstring.
    Nothing here executes; it proposes.
    """
    spans = [s for s in (_word_span(w) for w in words) if s is not None]
    if not spans:
        return {
            "success": False,
            "error": "No word timings in this transcript — run transcription first.",
            "keep_ranges": [],
            "removals": [],
        }
    end_of_speech = max(span[1] for span in spans)
    limit = float(range_end) if range_end is not None else end_of_speech

    removals: List[Dict[str, Any]] = []
    counts = {"filler": 0, "false_start": 0, "pause": 0}

    if remove_fillers:
        for hit in detect_fillers(words):
            removals.append({
                "start_seconds": max(range_start, hit["start_seconds"] - handle / 2),
                "end_seconds": min(limit, hit["end_seconds"] + handle / 2),
                "reason": f"filler word {hit['words']!r}",
            })
            counts["filler"] += 1
    if remove_false_starts:
        for hit in detect_false_starts(words):
            removals.append({
                "start_seconds": max(range_start, hit["start_seconds"]),
                "end_seconds": min(limit, hit["end_seconds"] + handle / 2),
                "reason": (
                    f"false start: {hit['words']!r} restarted as {hit['repeated_as']!r} "
                    f"after {hit['gap_seconds']}s ({hit['confidence']} confidence)"
                ),
            })
            counts["false_start"] += 1
    if collapse_pauses:
        for hit in detect_long_pauses(words, max_pause=max_pause, handle=handle, min_cut=min_cut):
            removals.append({
                "start_seconds": max(range_start, hit["start_seconds"]),
                "end_seconds": min(limit, hit["end_seconds"]),
                "reason": f"pause of {hit['pause_seconds']}s collapsed to {max_pause}s",
            })
            counts["pause"] += 1

    removals = [r for r in removals if r["end_seconds"] - r["start_seconds"] >= min_cut]
    merged = _merge(removals, bridge_gap=min_cut)

    keep: List[Dict[str, float]] = []
    cursor = float(range_start)
    for item in merged:
        if item["start_seconds"] > cursor:
            keep.append({"start": round(cursor, 3), "end": round(item["start_seconds"], 3)})
        cursor = max(cursor, item["end_seconds"])
    if limit > cursor:
        keep.append({"start": round(cursor, 3), "end": round(limit, 3)})
    if not keep:
        keep = [{"start": round(range_start, 3), "end": round(limit, 3)}]

    removed = round(sum(item["duration_seconds"] for item in merged), 3)
    return {
        "success": True,
        "keep_ranges": keep,
        "removals": merged,
        "counts": counts,
        "source_duration_seconds": round(limit - range_start, 3),
        "removed_seconds": removed,
        "tightened_duration_seconds": round((limit - range_start) - removed, 3),
        "note": (
            "Proposal only. Every removal states its reason so the pass can be argued "
            "with; false starts are a heuristic and may occasionally take a deliberate "
            "repetition."
        ),
    }


# ── search ───────────────────────────────────────────────────────────────────


def _context(words: Sequence[Dict[str, Any]], lo: int, hi: int, context_s: float) -> Dict[str, Any]:
    spans = [_word_span(w) for w in words]
    hit_start = spans[lo][0] if spans[lo] else 0.0
    hit_end = spans[hi][1] if spans[hi] else hit_start
    ctx_lo, ctx_hi = lo, hi
    while ctx_lo > 0 and spans[ctx_lo - 1] and hit_start - spans[ctx_lo - 1][0] <= context_s:
        ctx_lo -= 1
    while ctx_hi < len(words) - 1 and spans[ctx_hi + 1] and spans[ctx_hi + 1][1] - hit_end <= context_s:
        ctx_hi += 1
    return {
        "start_seconds": round(hit_start, 3),
        "end_seconds": round(hit_end, 3),
        "text": " ".join(str(w.get("word") or "").strip() for w in words[lo : hi + 1]).strip(),
        "context": " ".join(str(w.get("word") or "").strip() for w in words[ctx_lo : ctx_hi + 1]).strip(),
        "context_start_seconds": round(spans[ctx_lo][0] if spans[ctx_lo] else hit_start, 3),
        "context_end_seconds": round(spans[ctx_hi][1] if spans[ctx_hi] else hit_end, 3),
    }


def search_words(
    words: Sequence[Dict[str, Any]],
    query: str,
    *,
    mode: str = "phrase",
    context_seconds: float = 1.5,
) -> List[Dict[str, Any]]:
    """Find `query` in one clip's word stream. See `SEARCH_MODES` for modes."""
    if mode not in SEARCH_MODES:
        raise ValueError(f"unknown search mode {mode!r}; valid: {', '.join(SEARCH_MODES)}")
    tokens = [t for t in (normalize_token(t) for t in query.split()) if t]
    normalized = [normalize_token(w.get("word")) for w in words]
    hits: List[Dict[str, Any]] = []

    if mode == "phrase":
        if not tokens:
            return []
        size = len(tokens)
        for i in range(len(normalized) - size + 1):
            if normalized[i : i + size] == tokens:
                hits.append(_context(words, i, i + size - 1, context_seconds))
    elif mode == "all_words":
        # File-level AND gate: every query word must appear somewhere in this
        # clip, else the clip contributes nothing.
        present = set(normalized)
        if not tokens or not all(t in present for t in tokens):
            return []
        wanted = set(tokens)
        hits = [_context(words, i, i, context_seconds) for i, t in enumerate(normalized) if t in wanted]
    else:  # regex, matched over the running normalized text
        pattern = re.compile(query, re.IGNORECASE)
        offsets: List[Tuple[int, int, int]] = []
        pieces: List[str] = []
        cursor = 0
        for idx, token in enumerate(normalized):
            if not token:
                continue
            if pieces:
                cursor += 1
            offsets.append((cursor, cursor + len(token), idx))
            pieces.append(token)
            cursor += len(token)
        text = " ".join(pieces)
        for match in pattern.finditer(text):
            covered = [wi for (lo, hi, wi) in offsets if lo < match.end() and hi > match.start()]
            if covered:
                hits.append(_context(words, covered[0], covered[-1], context_seconds))
    return hits


SEARCH_MODES = ("phrase", "all_words", "regex")
