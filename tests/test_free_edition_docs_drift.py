"""Drift guard: never claim the free edition is unusable without naming the bridge.

Blackmagic gates *external* scripting to Studio, so it is true and worth saying
that `scriptapp("Resolve")` refuses a foreign process on the free edition. What
is NOT true — and what we shipped for a while — is the conclusion users drew
from it: that the free edition cannot be used at all.

v2.68.0 added the in-app bridge (`scripts/install_resolve_bridge.py`), which
reaches the free edition through the ungated Workspace > Scripts menu. The
README documented it. The README's own Requirements section, 195 lines later,
went on saying "the free edition does not support external scripting" with no
pointer to the bridge, and docs/install.md said the same with no mention of the
bridge at all.

The cost was not hypothetical: the first large public tutorial for this project
pinned a correction telling viewers the method "REQUIRES the Studio Version,"
and roughly eight commenters were turned away by a limitation we had already
solved.

This guard does not forbid stating the limitation. It requires that any file
stating it also tells the reader what to do about it, so the two halves cannot
drift apart again.
"""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: Files that speak to users about requirements. Add new user-facing docs here.
USER_FACING_DOCS = [
    REPO / "README.md",
    REPO / "docs" / "install.md",
]

#: Phrasings that assert the free edition is limited. Matched case-insensitively.
#: Deliberately broad — the point is to catch a *new* phrasing of the old claim,
#: not only the exact two sentences we already fixed.
#: `free ... edition/version` allows intervening words so "the free DaVinci
#: Resolve edition doesn't support..." is caught, not just "free edition".
#: `requires ... studio` allows an article so "REQUIRES the Studio Version" is
#: caught — that is verbatim the correction the tutorial author had to pin.
LIMITATION_PATTERNS = [
    re.compile(
        r"free\s+(?:\w+\s+){0,3}(?:edition|version)[^.\n]{0,80}"
        r"(?:does\s?n[o']t|do\s?n[o']t|cannot|can\s?not|is\s+not|are\s+not|no)\s+support",
        re.IGNORECASE,
    ),
    re.compile(r"free\s+(?:\w+\s+){0,3}(?:edition|version)[^.\n]{0,80}not\s+supported", re.IGNORECASE),
    re.compile(r"requires?\s+(?:the\s+)?(?:davinci\s+resolve\s+)?studio", re.IGNORECASE),
    re.compile(r"studio[\s-]only", re.IGNORECASE),
]

#: Evidence that the same file also points at the way through.
REMEDY_PATTERNS = [
    re.compile(r"in-app bridge", re.IGNORECASE),
    re.compile(r"free-edition-in-app-bridge", re.IGNORECASE),
    re.compile(r"install_resolve_bridge", re.IGNORECASE),
    re.compile(r"DAVINCI_RESOLVE_BRIDGE", re.IGNORECASE),
]


def _matching_lines(text, patterns):
    hits = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pattern in patterns:
            if pattern.search(line):
                hits.append((lineno, line.strip()))
                break
    return hits


class FreeEditionDocsDriftTest(unittest.TestCase):
    def test_docs_exist(self):
        for path in USER_FACING_DOCS:
            self.assertTrue(path.is_file(), f"missing user-facing doc: {path}")

    def test_limitation_claims_are_accompanied_by_the_remedy(self):
        for path in USER_FACING_DOCS:
            text = path.read_text(encoding="utf-8")
            claims = _matching_lines(text, LIMITATION_PATTERNS)
            if not claims:
                continue
            has_remedy = any(pattern.search(text) for pattern in REMEDY_PATTERNS)
            rel = path.relative_to(REPO)
            self.assertTrue(
                has_remedy,
                f"{rel} states a free-edition limitation but never mentions the "
                f"in-app bridge that works around it.\n"
                + "\n".join(f"  {rel}:{n}: {line}" for n, line in claims)
                + "\n\nEither drop the claim or link the bridge "
                "(README.md#free-edition-in-app-bridge).",
            )

    def test_bridge_section_still_exists(self):
        """The remedy the other test points at must actually be there."""
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn(
            "## Free edition (in-app bridge)",
            readme,
            "README.md lost its 'Free edition (in-app bridge)' heading; the "
            "anchor #free-edition-in-app-bridge is linked from docs/install.md "
            "and from the Requirements section.",
        )

    def test_bridge_installer_still_exists(self):
        installer = REPO / "scripts" / "install_resolve_bridge.py"
        self.assertTrue(
            installer.is_file(),
            f"missing {installer.relative_to(REPO)} — the docs promise it.",
        )


if __name__ == "__main__":
    unittest.main()
