"""Drift guard: named third parties stay out of the committed tree entirely.

The craft principles this codebase encodes come from named practitioners. The
attributions are accurate and they belong in the **design notes under `local/`**,
which are gitignored — not in shipped source, docstrings, comments, identifiers
or documentation.

The substance survives the removal without loss. "A long-standing observation in
sound editing, not a measured constant" carries exactly the caution the
attributed version carried; what it no longer does is ship somebody's name in a
library that people import.

## Why the names are stored as hashes

This file has to recognise the names in order to forbid them, which would make
it the one committed file containing them — defeating the point. So it stores
**SHA-256 digests of the lowercased tokens** instead. The detector tokenises
each candidate, hashes each token, and compares. Nothing here reveals a name,
and the guard works on a fresh clone with no external state.

To add a name, print its digest and paste it in:

    python -c "import hashlib;print(hashlib.sha256('surname'.encode()).hexdigest())"

`SENTINEL_TOKEN` is a fake name that exists purely so the self-tests can prove
the detector fires. Without it, testing the positive case would require putting
a real name back into this file.

## What is checked

Every committed Python file, in full — strings, docstrings, comments and
identifiers alike. There is no exemption, because "zero outside gitignored
files" is the policy.

## Known limitation, stated rather than hidden

Detection is per-token, so multi-word titles are not caught. A single-token
check for a word like "blink" would fire on `blink point`, which is legitimate
craft vocabulary used throughout this codebase — a guard that cries wolf gets
switched off, so the narrower check is the correct trade. Multi-word titles are
handled by review, not by this test.
"""

from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path
from typing import List, Set, Tuple

REPO = Path(__file__).resolve().parents[1]

#: Directories to scan. `local/` is gitignored and deliberately excluded — that
#: is where the attributions are supposed to live.
SCAN_DIRS = ("src", "tests", "scripts")
SCAN_DOCS = ("docs", ".agents", ".claude", ".codex")

#: A fake surname, present only so the self-tests below can demonstrate a real
#: detection without reintroducing a genuine name into this file.
SENTINEL_TOKEN = "attributiondriftsentinel"

def _digest(token: str) -> str:
    return hashlib.sha256(token.lower().encode("utf-8")).hexdigest()


#: SHA-256 of each lowercased forbidden token, plus the test sentinel.
#: Opaque on purpose — this file must not be the one place the names survive.
#: Six practitioner/work tokens; regenerate with the one-liner in the docstring.
FORBIDDEN_DIGESTS: Set[str] = {
    "1c237e5d4f3ce724191607fec67ae149eeb6b41cc1bc6867fa43709856460f1a",
    "737df29ac89cfb86f9b3ff7e34a89ffe584caa4fb7e90f9d0f2ea82f1d962a9b",
    "377ec3ee5d4cb03b8770aa6bdfdb5c665ad6bc644e89bb4c7bc960177bae1053",
    "c023b7b07742e120d8a6b04143594cac2ea04491b8f9f71fddd0ffd942bae1e5",
    "00937616de1f95d61cc69485ec5bdd344951b7ea892815d0d5ffa089d83b49af",
    "3eafe348466df2e0daf0eb20835816f41e55ad45acd5a01a0fc7e635dfe838aa",
    _digest(SENTINEL_TOKEN),
}


_TOKEN_RE = re.compile(r"[A-Za-z]+")


def tokens(text: str) -> List[str]:
    """Lowercased alphabetic tokens, splitting camelCase and snake_case."""
    out: List[str] = []
    for word in _TOKEN_RE.findall(text):
        out.extend(part.lower() for part in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", word) or [word])
    return out


def scan_text(text: str) -> Set[str]:
    """Digests of any forbidden token present in this text."""
    found = set()
    for token in tokens(text):
        digest = _digest(token)
        if digest in FORBIDDEN_DIGESTS:
            found.add(digest)
    return found


def scan_file(path: Path) -> List[Tuple[int, str]]:
    """Line numbers containing a forbidden token."""
    hits: List[Tuple[int, str]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return hits
    for lineno, line in enumerate(lines, start=1):
        if scan_text(line):
            hits.append((lineno, line.strip()[:100]))
    return hits


def committed_files() -> List[Path]:
    paths: List[Path] = []
    for directory in SCAN_DIRS:
        root = REPO / directory
        if root.is_dir():
            paths.extend(p for p in root.rglob("*.py") if "node_modules" not in p.parts)
    for directory in SCAN_DOCS:
        root = REPO / directory
        if root.is_dir():
            paths.extend(p for p in root.rglob("*.md") if "node_modules" not in p.parts)
    for name in ("README.md", "AGENTS.md", "CLAUDE.md"):
        candidate = REPO / name
        if candidate.is_file():
            paths.append(candidate)
    return sorted(set(paths))


class AttributionDriftTest(unittest.TestCase):
    def test_no_named_attribution_anywhere_in_the_committed_tree(self) -> None:
        offenders: List[str] = []
        for path in committed_files():
            if path.resolve() == Path(__file__).resolve():
                continue  # this file holds only digests, never names
            for lineno, line in scan_file(path):
                offenders.append(f"  {path.relative_to(REPO)}:{lineno}\n      {line}")
        self.assertFalse(
            offenders,
            "Named attributions must not appear in committed files at all.\n"
            + "\n".join(offenders)
            + "\n\nThe attribution belongs in the design notes under local/ (gitignored). "
            "Rewrite the committed text to carry the substance without the name — "
            '"a long-standing observation in sound editing" says the same thing and '
            "does not ship somebody's name in an importable library.",
        )

    def test_the_guard_can_actually_fail(self) -> None:
        """A guard that cannot fail is decoration.

        Uses the sentinel rather than a real name, so proving the detector works
        does not require putting one back into this file.
        """
        self.assertTrue(scan_text(f"{SENTINEL_TOKEN}'s observation about rhythm"))
        self.assertTrue(scan_text(f"{SENTINEL_TOKEN.upper()}_STREAM_LIMIT = 2.5"))
        self.assertTrue(scan_text(f"# {SENTINEL_TOKEN} pins a frame per setup"))

    def test_it_catches_every_syntactic_position(self) -> None:
        """Docstring, comment, runtime string and identifier all count now."""
        for sample in (
            f'"""Module docstring mentioning {SENTINEL_TOKEN}."""',
            f"#: {SENTINEL_TOKEN}'s boundary.",
            f'return {{"note": "per {SENTINEL_TOKEN}"}}',
            f"{SENTINEL_TOKEN.upper()}_WEIGHTS = {{}}",
        ):
            with self.subTest(sample=sample[:40]):
                self.assertTrue(scan_text(sample))

    def test_ordinary_craft_vocabulary_is_not_flagged(self) -> None:
        """A guard that cries wolf gets switched off."""
        for safe in (
            "the blink point is where a viewer would naturally blink",
            "rhythm is a pattern established in order to be broken",
            "a long-standing observation in sound editing",
            "CRITERION_WEIGHTS = {}",
            "the iron rule: sacrifice lower priorities",
        ):
            with self.subTest(safe=safe[:40]):
                self.assertFalse(scan_text(safe))

    def test_camel_and_snake_case_identifiers_are_tokenised(self) -> None:
        self.assertTrue(scan_text(f"{SENTINEL_TOKEN}StreamLimit"))
        self.assertTrue(scan_text(f"some_{SENTINEL_TOKEN}_limit"))

    def test_the_scan_covers_source_tests_and_docs(self) -> None:
        """If the file list silently narrowed, the guard would pass vacuously."""
        scanned = {p.relative_to(REPO).parts[0] for p in committed_files()}
        for expected in ("src", "tests", "docs"):
            self.assertIn(expected, scanned)
        self.assertGreater(len(committed_files()), 50)


if __name__ == "__main__":
    unittest.main()
