"""Read EBU R128 figures out of ffmpeg's `ebur128` output, and nothing else out of it.

One parser, imported by both callers. There were two: `media_analysis` measures loudness
during analysis and `mix_plan` measures the premix it just rendered, and they carried
copies of the same three regexes on the reasoning that `mix_plan` should stay importable
without pulling in the analysis engine. That reasoning still holds for the *engine*; it
does not justify two copies of the parsing rule, which is the part that has to be right.

## The rule

`ebur128` prints a progress line per frame carrying its own `I:`, `LRA:` and peak fields,
then a `Summary:` block at the end. A last-match-wins read over the whole stream picks
the summary only because the summary happens to print last. Nothing enforces that, and
when it does not hold the numbers still parse — they are simply a single frame's reading
presented as a programme measurement. There is no error to notice.

So the summary block is *bounded*, not merely located:

1. Seek the last `Summary:`.
2. Take lines until the next ffmpeg log line — the block's body is indented plain text,
   while every log line carries a `[component @ address]` prefix. That ends the block at
   `[out#0/null …]`, at a trailing progress line, and at anything else ffmpeg appends.
3. Drop any remaining `TARGET:` line, which is the field on every progress line and on
   nothing in the summary. This is what protects the fallback path when no summary was
   printed at all: there, reading a progress line would be the worst possible answer, so
   the result is `None`.

Absent a summary the answer is `None` rather than a best guess. "No measurement" and
"a measurement of one frame" are different, and only one of them is safe to deliver on.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Optional

INTEGRATED_RE = r"I:\s*(-?\d+(?:\.\d+)?)\s*LUFS"
LRA_RE = r"LRA:\s*(-?\d+(?:\.\d+)?)\s*LU"
PEAK_RE = r"Peak:\s*(-?\d+(?:\.\d+)?)\s*dBFS"

#: ffmpeg prefixes every log line with `[component @ 0xaddr]`. The summary body does not
#: carry one, so this is where the block ends.
_LOG_LINE_PREFIX = "["


def summary_block(stderr: str) -> str:
    """The `ebur128` summary block alone, or "" when none was printed."""
    marker = stderr.rfind("Summary:")
    if marker < 0:
        return ""
    # Back up to the line start: `Summary:` sits at the end of an ffmpeg log line, and a
    # block that begins mid-line would make the "first line is the header" rule below
    # depend on where the word happened to fall.
    line_start = stderr.rfind("\n", 0, marker) + 1
    lines = stderr[line_start:].splitlines()
    block = [lines[0]] if lines else []
    for line in lines[1:]:
        if line.startswith(_LOG_LINE_PREFIX):
            break
        block.append(line)
    return "\n".join(line for line in block if "TARGET:" not in line)


def parse_loudness(
    stderr: str, *, to_float: Optional[Callable[[Any], Optional[float]]] = None
) -> Dict[str, Optional[float]]:
    """Integrated LUFS, loudness range, and true peak from the summary block.

    `to_float` lets a caller supply its own lenient conversion; the default is `float`
    with a `None` on failure.
    """
    convert = to_float or _default_float
    scope = summary_block(stderr)

    def latest(pattern: str) -> Optional[float]:
        matches = re.findall(pattern, scope)
        return convert(matches[-1]) if matches else None

    return {
        "integrated_lufs": latest(INTEGRATED_RE),
        "loudness_range_lu": latest(LRA_RE),
        "true_peak_dbtp": latest(PEAK_RE),
    }


def _default_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
