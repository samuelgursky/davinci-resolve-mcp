"""Flag transcript words that may have swallowed an immediate retake.

When a speaker re-reads a sentence immediately — the normal way people
self-correct while recording — whisper emits the text ONCE, aligns it to the
FIRST take, and absorbs "pause + entire second take" into the duration of a
single word. The transcript then says the sentence was spoken once, cleanly.
Every transcript-reading feature downstream inherits that lie: retake
detection never fires, fluency scoring undercounts restarts, and a cut placed
on a word boundary near the swallow point lands inside speech.

Energy detection cannot catch it either. In the original measurement the
swallowed span was breathing and keyboard noise peaking at -12.1 dB, LOUDER
than the adjacent real speech at -16.7 dB, so `silencedetect` recalled 3 of 17
ground-truth instances at any threshold. See issue #125.

What this module does is deliberately small: it flags words whose duration is
implausible for a single spoken word, and stops. It does not propose a cut
point, because the data cannot support one — where inside the stretched word
the second take begins is exactly what the timestamps have destroyed.

**Why an absolute bar, after two better-sounding ideas failed.**
The reporter measured all three on English material (2026-08-06, synthetic but
acoustically matched, ground truth from a sample-accurate splice log):

- A characters-per-second gate (`>= 2.5s and < 4.5 chars/s`), which worked on
  the original Chinese material, fires on **0 of 50** English segments — the
  swallowed segment itself runs 8.81 chars/s against an English median of 14.5.
  Characters per second is not comparable across writing systems; it is retired
  here rather than made configurable.
- Scoring each word against the distribution of its OWN durations elsewhere in
  the take — self-calibrating, and the obvious language-agnostic fix — missed
  the swallow entirely and produced 8 false positives, all function words. The
  reason is structural and worth keeping: the words that absorb retakes are
  content words, and content words are naturally rare within one take, so they
  never accumulate a distribution to be scored against.
- The plain absolute bar found exactly one stretched word in 191.5s, and it was
  the swallow point.

So: one threshold, no calibration, no language assumptions.

**Confidence.** The English confirmation rests on a single genuine swallow
(n=1) in synthetic material — 13 of 15 planted retakes transcribed too cleanly
to swallow, which is itself a limit of TTS-generated speech. The Chinese
measurement it generalises from had 17 real instances. Treat the bar as a
usable default, not a tuned constant.
"""

from typing import Any, Dict, List, Mapping, Optional, Sequence

# Seconds. A single spoken word above this is implausible in any language the
# reporter measured; the one true positive ran well past it.
DEFAULT_MIN_WORD_SECONDS = 1.2

CAVEAT = (
    "A flag is not a cut point. Where inside a stretched word the second take "
    "begins is precisely what the swallow destroyed, so these need a human ear "
    "(or a re-transcription pass over the isolated window) before anything is "
    "removed. Absence of flags is not evidence of no retakes: a swallow that "
    "smeared across several words rather than one will not clear the bar."
)


def _seconds(row: Mapping[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        value = row.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _word_text(row: Mapping[str, Any]) -> str:
    for key in ("word", "text", "token"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def find_swallowed_retake_candidates(
    words: Sequence[Mapping[str, Any]],
    *,
    min_word_seconds: float = DEFAULT_MIN_WORD_SECONDS,
) -> List[Dict[str, Any]]:
    """Words whose duration exceeds the bar, in time order.

    Accepts either transcript_words DB rows (`start_seconds`/`end_seconds`) or
    raw whisper word dicts (`start`/`end`); a row missing either endpoint is
    skipped rather than guessed at.
    """
    if not words or min_word_seconds <= 0:
        return []
    out: List[Dict[str, Any]] = []
    for index, row in enumerate(words):
        if not isinstance(row, Mapping):
            continue
        start = _seconds(row, "start_seconds", "start")
        end = _seconds(row, "end_seconds", "end")
        if start is None or end is None:
            continue
        duration = end - start
        if duration < min_word_seconds:
            continue
        out.append({
            "word_index": index,
            "word": _word_text(row),
            "start_seconds": round(start, 3),
            "end_seconds": round(end, 3),
            "duration_seconds": round(duration, 3),
            "reason": (
                f"word spans {duration:.2f}s, over the {min_word_seconds:.2f}s bar — "
                "a retake may be absorbed into this word's duration"
            ),
        })
    out.sort(key=lambda row: row["start_seconds"])
    return out


def swallowed_retake_report(
    words: Sequence[Mapping[str, Any]],
    *,
    min_word_seconds: float = DEFAULT_MIN_WORD_SECONDS,
) -> Dict[str, Any]:
    """`find_swallowed_retake_candidates` plus the caveat, ready to attach."""
    candidates = find_swallowed_retake_candidates(words, min_word_seconds=min_word_seconds)
    return {
        "count": len(candidates),
        "min_word_seconds": min_word_seconds,
        "candidates": candidates,
        "caveat": CAVEAT,
        "note": (
            f"{len(candidates)} word(s) long enough to have swallowed an immediate "
            "retake. Whisper reports a re-read sentence once and absorbs the pause "
            "plus the second take into one word, so these are invisible to both the "
            "transcript and any silence threshold (issue #125)."
            if candidates
            else "No words cleared the stretched-word bar. That is weak evidence, "
                 "not proof: a swallow spread over several words will not show up here."
        ),
    }
