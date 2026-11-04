"""Does a clip's media exist on disk, when its path names an image sequence? (#325)

Resolve reports an image sequence's `File Path` as a pattern, not a file:
`C:\\shots\\Flowers_v2.[0000-8999].jpeg`. `os.path.exists` is False for every
such pattern, so the conform probe reported Online sequences as
`file_exists: false`, and `detect_missing_media` / `build_relink_plan` treated
them as missing media to relink.

`media_exists` expands the forms Resolve and the printf-style import paths
use:

- `name.[0000-8999].ext` — Resolve's own range form. The first and last frame
  must both exist; the zero padding is the width of the bracketed numbers.
- `name.%04d.ext` and `name.####.ext` — no range, so at least one matching
  frame in the folder must exist.

A full scan for gaps inside a range would read every directory entry of a
9000-frame folder on every probe; it is not done here.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional, Tuple

_BRACKET_RANGE = re.compile(r"^(?P<head>.*)\[(?P<first>\d+)-(?P<last>\d+)\](?P<tail>[^\[\]]*)$")
_PRINTF = re.compile(r"%0?(?P<width>\d*)d")
_HASHES = re.compile(r"#+")


def _frame_path(head: str, number: int, width: int, tail: str) -> str:
    return f"{head}{number:0{width}d}{tail}"


def _any_frame_matches(pattern: str) -> bool:
    """True when the folder holds a file matching a printf/hash frame pattern."""
    folder, name = os.path.split(pattern)
    printf = _PRINTF.search(name)
    match = printf or _HASHES.search(name)
    if not match:
        return False
    width = printf.group("width") if printf else str(len(match.group(0)))
    digits = rf"\d{{{width},}}" if width else r"\d+"
    regex = re.compile(re.escape(name[:match.start()]) + digits + re.escape(name[match.end():]) + r"$")
    try:
        return any(regex.match(entry) for entry in os.listdir(folder or "."))
    except OSError:
        return False


def media_exists(path: Any) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """(exists, sequence) for a media path; `sequence` is None for a plain file."""
    if not path:
        return False, None
    text = str(path)
    if os.path.exists(text):
        return True, None
    bracket = _BRACKET_RANGE.match(text)
    if bracket:
        first_text, last_text = bracket.group("first"), bracket.group("last")
        first, last = int(first_text), int(last_text)
        width = len(first_text)
        first_path = _frame_path(bracket.group("head"), first, width, bracket.group("tail"))
        last_path = _frame_path(bracket.group("head"), last, width, bracket.group("tail"))
        sequence = {
            "first": first,
            "last": last,
            "first_exists": os.path.exists(first_path),
            "last_exists": os.path.exists(last_path),
        }
        return sequence["first_exists"] and sequence["last_exists"], sequence
    if _PRINTF.search(os.path.basename(text)) or _HASHES.search(os.path.basename(text)):
        found = _any_frame_matches(text)
        return found, {"pattern": True, "any_frame_exists": found}
    return False, None
