"""Cut intermediate representation (Cut-IR) and the mechanical (Pass-1) detector.

The Cut-IR is the typed contract between a timestamped transcript and concrete,
governed timeline operations. Producers emit Cuts; an executor (a later phase)
consumes them as governed, versioned edits; a review UI shows them. This module
provides the schema plus the deterministic Pass-1 detector — filler words, long
pauses, and repeated lines — with no LLM. The semantic Pass-2 and the timeline
executor are separate phases (see local/design/research/r1-cut-ir.md).

A Cut:
    {
      "kind": "filler" | "long_pause" | "stammer" | "false_start" | "semantic",
      "span": {"start": <frame>, "end": <frame>},
      "action": "lift" | "ripple_delete" | "keep" | "reorder" | "swap",
      "confidence": 0.0..1.0,
      "rationale": str,
      "evidence": {...},
    }
"""
from typing import Any, Dict, List, Optional

# Common English fillers (single tokens and short phrases).
FILLER_WORDS = {
    "um", "uh", "er", "ah", "eh", "hmm", "mm", "uhh", "umm",
    "like", "so", "well", "right", "okay", "ok",
}
FILLER_PHRASES = {"you know", "i mean", "sort of", "kind of", "you see"}


def make_cut(
    kind: str,
    start: Optional[int],
    end: Optional[int],
    action: str,
    confidence: float,
    rationale: str,
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "kind": kind,
        "span": {"start": start, "end": end},
        "action": action,
        "confidence": round(float(confidence), 2),
        "rationale": rationale,
        "evidence": evidence or {},
    }


def _norm(text: str) -> str:
    return (text or "").strip().lower().strip(".,!?;:")


def _is_filler_only(text: str) -> bool:
    low = _norm(text)
    if not low:
        return False
    if low in FILLER_PHRASES:
        return True
    tokens = [t.strip(".,!?;:") for t in low.split()]
    tokens = [t for t in tokens if t]
    return bool(tokens) and all(t in FILLER_WORDS for t in tokens)


def detect_cuts_pass1(
    cues: List[Dict[str, Any]],
    *,
    long_pause_frames: int = 48,
) -> List[Dict[str, Any]]:
    """Mechanical Pass-1 detection over timestamped cues.

    cues: list of {"text", "start", "end"} in frames. Returns a list of Cuts.
    """
    cuts: List[Dict[str, Any]] = []
    for i, cue in enumerate(cues):
        text = (cue.get("text") or "").strip()
        start, end = cue.get("start"), cue.get("end")

        if _is_filler_only(text):
            cuts.append(make_cut(
                "filler", start, end, "lift", 0.8,
                f"Filler-only cue: {text!r}", {"text": text},
            ))

        if i > 0:
            prev_text = (cues[i - 1].get("text") or "").strip()
            if _norm(prev_text) and _norm(text) == _norm(prev_text):
                cuts.append(make_cut(
                    "stammer", start, end, "lift", 0.6,
                    f"Repeated line: {text!r}", {"text": text},
                ))
            prev_end = cues[i - 1].get("end")
            if (prev_end is not None and start is not None
                    and start - prev_end > long_pause_frames):
                cuts.append(make_cut(
                    "long_pause", prev_end, start, "lift", 0.5,
                    f"Pause of {start - prev_end} frames before {text!r}",
                    {"frames": start - prev_end},
                ))
    return cuts


def build_cut_list(
    cues: List[Dict[str, Any]],
    *,
    long_pause_frames: int = 48,
) -> Dict[str, Any]:
    """Run Pass-1 and wrap the result as a (dry-run) CutList."""
    cuts = detect_cuts_pass1(cues, long_pause_frames=long_pause_frames)
    return {
        "cuts": cuts,
        "cut_count": len(cuts),
        "basis_cue_count": len(cues),
        "pass": "mechanical",
        "note": "Dry-run proposal. Review before applying; no edits were made.",
    }
