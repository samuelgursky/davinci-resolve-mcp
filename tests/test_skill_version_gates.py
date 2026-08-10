"""Guard: domain skills must carry the build check, and must not misquote it.

Issue #132's remaining half. `get_version` learned to report what a connected
build is missing (v2.89.0), but the domain skills gave identical guidance
whatever they were attached to — so an agent that entered through
`/timeline_edit_workflow` rather than the session skill never asked the
question. The reporter hit exactly that hole on DR 21.

Two failure modes are pinned here, and the second is the one that rots:

1. A domain skill that routes to gated surfaces says nothing about versions.
2. A skill quotes a floor that disagrees with `resolve_versions.VERSION_GATES`
   — the ledger the server actually enforces. A skill saying "needs 20.2" for a
   symbol gated at 21.0.4 is worse than saying nothing, because it reads as
   measured.
"""
import re
import unittest
from pathlib import Path

from src.utils.resolve_versions import VERSION_GATES

SKILLS = Path(__file__).resolve().parent.parent / ".claude" / "skills"

#: Domain skills that offer at least one version-gated live surface. Skills with
#: no gated surface at all (resolve-fusion, house-style) are deliberately absent:
#: a build-check section there would be noise pretending to be diligence.
SKILLS_NEEDING_THE_BUILD_CHECK = (
    "resolve-edit",
    "resolve-color",
    "resolve-conform",
    "resolve-media-analysis",
    "resolve-media-pool",
    "resolve-audio",
    "resolve-delivery",
    "resolve-session",
)

#: The floor for a bare symbol name, e.g. "GetSelectedClips" -> "21.0.4".
#: A name gated at two different floors on two different classes is excluded
#: rather than guessed at — the drift guard in test_version_gate_drift covers
#: that case, and here it would make the lookup a coin flip.
def _floors_by_bare_name() -> dict:
    floors: dict[str, set] = {}
    for gate in VERSION_GATES:
        bare = str(gate["symbol"]).split(".")[-1].split(" ")[0]
        floors.setdefault(bare, set()).add(gate["introduced_in"])
    return {name: next(iter(vs)) for name, vs in floors.items() if len(vs) == 1}


class SkillVersionGateTests(unittest.TestCase):
    def _skill_text(self, name: str) -> str:
        path = SKILLS / name / "SKILL.md"
        self.assertTrue(path.exists(), f"missing skill: {path}")
        return path.read_text(encoding="utf-8")

    def test_gated_domains_tell_the_agent_to_ask_the_build(self):
        for name in SKILLS_NEEDING_THE_BUILD_CHECK:
            with self.subTest(skill=name):
                text = self._skill_text(name)
                self.assertTrue(
                    "unavailable_on_this_build" in text or "check_version_support" in text,
                    f"{name} offers version-gated surfaces but never tells the agent to "
                    "read the build's gate list — the #132 hole.",
                )

    def test_hasattr_warning_travels_with_the_build_check(self):
        """`hasattr` is a constant True on Resolve objects, so a probe written
        with it can only say yes. Any skill that tells an agent to probe must
        say this, or the advice actively creates the fabrication it guards."""
        for name in SKILLS_NEEDING_THE_BUILD_CHECK:
            with self.subTest(skill=name):
                text = self._skill_text(name)
                if "probe it" not in text:
                    continue
                self.assertIn(
                    "hasattr", text,
                    f"{name} says to probe but does not warn that bare hasattr cannot fail",
                )

    def test_no_skill_quotes_a_floor_the_ledger_disagrees_with(self):
        """Every "`Symbol` | 20.2"-shaped row must match VERSION_GATES.

        This is the rot guard: floors move when Blackmagic ships, and a stale
        number in a skill reads exactly as authoritative as a fresh one.
        """
        floors = _floors_by_bare_name()
        row = re.compile(r"`([A-Za-z_][A-Za-z0-9_.` /]*?)`\s*\|\s*(\d+\.\d+(?:\.\d+)?)\s*\|")
        for path in sorted(SKILLS.glob("*/SKILL.md")):
            text = path.read_text(encoding="utf-8")
            for symbol, quoted in row.findall(text):
                for candidate in re.split(r"[ /`]+", symbol):
                    bare = candidate.split(".")[-1].strip()
                    if bare not in floors:
                        continue
                    with self.subTest(skill=path.parent.name, symbol=bare):
                        self.assertEqual(
                            quoted, floors[bare],
                            f"{path.parent.name} says {bare} needs {quoted}; the ledger "
                            f"says {floors[bare]}",
                        )


if __name__ == "__main__":
    unittest.main()
