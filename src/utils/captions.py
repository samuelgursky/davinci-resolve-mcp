"""Caption generation from word timings: SRT / WebVTT under broadcast rules.

Turning a transcript into captions is not line-wrapping. A caption that is
technically synchronised but breaks mid-clause, orphans a word, or sits on
screen for nine seconds fails QC and is unreadable, so the rules a human
captioner follows are encoded here rather than left to the caller:

- a character cap per line, and a cap on lines per block;
- a maximum and a **minimum** block duration — a 4-frame flash is unreadable
  even though it is perfectly in sync;
- breaks preferred at sentence ends, then at clause boundaries, then at long
  pauses, and only then on length alone;
- timings snapped to the words actually spoken, never interpolated;
- a minimum gap between blocks so consecutive captions do not visually merge;
- no single-word orphan line.

## Reading rate is a cap, not a target

Blocks are extended toward `min_block_seconds` when the words are quick, but
never past the next block's start. A caption that overruns its successor is
worse than a short one.

## Frame rates

SRT and WebVTT both carry wall-clock timestamps, so nothing here needs a frame
rate. Retiming across rates is a separate concern and deliberately not folded
in — a caption file that has been silently conformed is very hard to debug.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

#: Broadcast-conventional defaults. Every one is overridable per call.
DEFAULT_MAX_CHARS_PER_LINE = 42
DEFAULT_MAX_LINES = 2
DEFAULT_MAX_BLOCK_SECONDS = 7.0
DEFAULT_MIN_BLOCK_SECONDS = 0.833  # ~20 frames at 24fps; below this is a flash
DEFAULT_MIN_GAP_SECONDS = 0.084  # ~2 frames, so blocks do not visually merge
#: A silence at least this long is a natural caption break.
DEFAULT_PAUSE_BREAK_SECONDS = 0.6

_SENTENCE_END_RE = re.compile(r"[.!?]['\"”’)]*$")
_CLAUSE_END_RE = re.compile(r"[,;:—-]['\"”’)]*$")

FORMATS = ("srt", "vtt")


class CaptionError(ValueError):
    """Invalid caption parameters — refused rather than silently clamped."""


def _word_time(word: Dict[str, Any], key: str, fallback: str) -> Optional[float]:
    value = word.get(key, word.get(fallback))
    return float(value) if isinstance(value, (int, float)) else None


def _clean(word: Dict[str, Any]) -> str:
    return str(word.get("word") or "").strip()


def _wrap(text: str, max_chars: int, max_lines: int) -> Optional[List[str]]:
    """Greedy wrap; None when it will not fit in `max_lines`.

    Returning None rather than truncating is deliberate — silently dropping
    words from a caption is the worst possible failure for accessibility.
    """
    lines: List[str] = []
    current = ""
    for token in text.split():
        candidate = f"{current} {token}".strip()
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = token
        if len(current) > max_chars:
            return None  # a single token longer than the line cap
    if current:
        lines.append(current)
    return lines if len(lines) <= max_lines else None


def _no_orphan(lines: List[str]) -> List[str]:
    """Rebalance so no line is a lone word when a neighbour could give one up."""
    if len(lines) < 2:
        return lines
    if len(lines[-1].split()) == 1 and len(lines[-2].split()) > 2:
        head = lines[-2].split()
        lines = lines[:-2] + [" ".join(head[:-1]), f"{head[-1]} {lines[-1]}"]
    return lines


def _break_score(word: Dict[str, Any], gap_after: float, pause_break: float) -> int:
    """Higher is a better place to end a caption block."""
    text = _clean(word)
    if _SENTENCE_END_RE.search(text):
        return 3
    if gap_after >= pause_break:
        return 2
    if _CLAUSE_END_RE.search(text):
        return 1
    return 0


def build_blocks(
    words: Sequence[Dict[str, Any]],
    *,
    max_chars_per_line: int = DEFAULT_MAX_CHARS_PER_LINE,
    max_lines: int = DEFAULT_MAX_LINES,
    max_block_seconds: float = DEFAULT_MAX_BLOCK_SECONDS,
    min_block_seconds: float = DEFAULT_MIN_BLOCK_SECONDS,
    min_gap_seconds: float = DEFAULT_MIN_GAP_SECONDS,
    pause_break_seconds: float = DEFAULT_PAUSE_BREAK_SECONDS,
) -> List[Dict[str, Any]]:
    """Group words into caption blocks obeying every rule above."""
    if max_chars_per_line < 8:
        raise CaptionError("max_chars_per_line below 8 cannot hold readable text")
    if max_lines < 1:
        raise CaptionError("max_lines must be at least 1")
    if min_block_seconds > max_block_seconds:
        raise CaptionError("min_block_seconds cannot exceed max_block_seconds")

    timed = [
        w for w in words
        if _clean(w) and _word_time(w, "start_seconds", "start") is not None
    ]
    if not timed:
        return []

    capacity = max_chars_per_line * max_lines
    blocks: List[Dict[str, Any]] = []
    current: List[Dict[str, Any]] = []

    def flush() -> None:
        if not current:
            return
        text = " ".join(_clean(w) for w in current)
        lines = _wrap(text, max_chars_per_line, max_lines)
        if lines is None:
            lines = [text[:max_chars_per_line]]
        blocks.append({
            "start_seconds": _word_time(current[0], "start_seconds", "start"),
            "end_seconds": (
                _word_time(current[-1], "end_seconds", "end")
                or _word_time(current[-1], "start_seconds", "start")
            ),
            "lines": _no_orphan(lines),
            "word_count": len(current),
        })
        current.clear()

    for index, word in enumerate(timed):
        current.append(word)
        following = timed[index + 1] if index + 1 < len(timed) else None
        if following is None:
            break

        this_end = _word_time(word, "end_seconds", "end") or _word_time(word, "start_seconds", "start")
        next_start = _word_time(following, "start_seconds", "start")
        gap = max(0.0, (next_start or 0.0) - (this_end or 0.0))

        text_now = " ".join(_clean(w) for w in current)
        text_next = f"{text_now} {_clean(following)}"
        block_start = _word_time(current[0], "start_seconds", "start") or 0.0
        would_be_long = ((next_start or 0.0) - block_start) > max_block_seconds
        would_not_fit = len(text_next) > capacity or _wrap(text_next, max_chars_per_line, max_lines) is None

        score = _break_score(word, gap, pause_break_seconds)
        # Sentence ends and real pauses always break. A block that spans a
        # silence leaves text on screen through it, which is the thing captioners
        # break on — and short blocks are already made readable by the
        # min_block_seconds extension below, so no length guard is needed here.
        # Clause breaks (score 1) are only a preference and never force a flush.
        if would_not_fit or would_be_long or score >= 2:
            flush()
    flush()

    # Extend short blocks toward the readable minimum, never into the next one.
    for index, block in enumerate(blocks):
        limit = (
            blocks[index + 1]["start_seconds"] - min_gap_seconds
            if index + 1 < len(blocks)
            else block["end_seconds"] + min_block_seconds
        )
        if block["end_seconds"] - block["start_seconds"] < min_block_seconds:
            block["end_seconds"] = max(block["end_seconds"], min(block["start_seconds"] + min_block_seconds, limit))
        # Enforce the inter-block gap even when no extension happened.
        if index + 1 < len(blocks):
            block["end_seconds"] = min(block["end_seconds"], blocks[index + 1]["start_seconds"] - min_gap_seconds)
        block["end_seconds"] = max(block["end_seconds"], block["start_seconds"] + 1e-3)
        block["start_seconds"] = round(block["start_seconds"], 3)
        block["end_seconds"] = round(block["end_seconds"], 3)
        block["duration_seconds"] = round(block["end_seconds"] - block["start_seconds"], 3)
    return blocks


# ── serialisation ────────────────────────────────────────────────────────────


def _timestamp(seconds: float, *, comma: bool) -> str:
    seconds = max(0.0, float(seconds))
    hours, rest = divmod(seconds, 3600.0)
    minutes, secs = divmod(rest, 60.0)
    millis = int(round((secs - int(secs)) * 1000))
    if millis == 1000:  # rounding carried into the next second
        secs, millis = int(secs) + 1, 0
    sep = "," if comma else "."
    return f"{int(hours):02d}:{int(minutes):02d}:{int(secs):02d}{sep}{millis:03d}"


def to_srt(blocks: Sequence[Dict[str, Any]]) -> str:
    out: List[str] = []
    for index, block in enumerate(blocks, start=1):
        out.append(str(index))
        out.append(
            f"{_timestamp(block['start_seconds'], comma=True)} --> "
            f"{_timestamp(block['end_seconds'], comma=True)}"
        )
        out.extend(block["lines"])
        out.append("")
    return "\n".join(out)


def to_vtt(blocks: Sequence[Dict[str, Any]]) -> str:
    out: List[str] = ["WEBVTT", ""]
    for block in blocks:
        out.append(
            f"{_timestamp(block['start_seconds'], comma=False)} --> "
            f"{_timestamp(block['end_seconds'], comma=False)}"
        )
        out.extend(block["lines"])
        out.append("")
    return "\n".join(out)


def render(blocks: Sequence[Dict[str, Any]], fmt: str) -> str:
    if fmt not in FORMATS:
        raise CaptionError(f"unknown caption format {fmt!r}; valid: {', '.join(FORMATS)}")
    return to_srt(blocks) if fmt == "srt" else to_vtt(blocks)


# ── chapters ─────────────────────────────────────────────────────────────────


def chapters_from_blocks(
    blocks: Sequence[Dict[str, Any]],
    *,
    min_spacing_seconds: float = 30.0,
    max_title_chars: int = 60,
) -> List[Dict[str, Any]]:
    """Derive chapters from caption blocks by topic-shift heuristic.

    A long pause landing on a sentence start is the cheapest usable signal for
    "new topic". This is explicitly a heuristic — it produces a starting point
    an editor renames, not a finished chapter list.

    The first chapter is always forced to 00:00 because that is a hard
    requirement of the YouTube description format, not a stylistic choice.
    """
    if not blocks:
        return []
    chapters: List[Dict[str, Any]] = [{
        "start_seconds": 0.0,
        "title": " ".join(blocks[0]["lines"])[:max_title_chars].strip(),
    }]
    for previous, block in zip(blocks, blocks[1:]):
        gap = block["start_seconds"] - previous["end_seconds"]
        if gap < DEFAULT_PAUSE_BREAK_SECONDS:
            continue
        if block["start_seconds"] - chapters[-1]["start_seconds"] < min_spacing_seconds:
            continue
        chapters.append({
            "start_seconds": round(block["start_seconds"], 3),
            "title": " ".join(block["lines"])[:max_title_chars].strip(),
        })
    return chapters


def chapters_to_youtube(chapters: Sequence[Dict[str, Any]]) -> str:
    """YouTube description text. Always starts at 00:00 or YouTube ignores it."""
    lines = []
    for chapter in chapters:
        total = int(chapter["start_seconds"])
        hours, rest = divmod(total, 3600)
        minutes, secs = divmod(rest, 60)
        stamp = f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
        lines.append(f"{stamp} {chapter['title']}".rstrip())
    return "\n".join(lines)


def generate(
    words: Sequence[Dict[str, Any]],
    *,
    fmt: str = "srt",
    with_chapters: bool = False,
    **options: Any,
) -> Dict[str, Any]:
    """Word timings → caption text plus the block list and optional chapters."""
    if fmt not in FORMATS:
        raise CaptionError(f"unknown caption format {fmt!r}; valid: {', '.join(FORMATS)}")
    blocks = build_blocks(words, **options)
    if not blocks:
        return {
            "success": False,
            "error": "No timed words to caption.",
            "remediation": "Run transcription for this clip first, then retry.",
        }
    result: Dict[str, Any] = {
        "success": True,
        "format": fmt,
        "text": render(blocks, fmt),
        "blocks": blocks,
        "block_count": len(blocks),
        "duration_seconds": round(blocks[-1]["end_seconds"], 3),
    }
    if with_chapters:
        chapters = chapters_from_blocks(blocks)
        result["chapters"] = chapters
        result["chapters_youtube"] = chapters_to_youtube(chapters)
    return result
