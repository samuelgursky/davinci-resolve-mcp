"""The knowledge tool: index, resolution, sections, search, and the corpus drift guard.

Two failure modes drove most of these. The first is a topic that resolves to a pointer
instead of prose — the whole reason the tool exists is that a client with no checkout
cannot follow `docs/guides/x.md`. The second is silent scope loss: a section that does
not exist quietly returning the whole document, or a knowledge file added later that
never reaches the index.
"""
from __future__ import annotations

import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.utils import knowledge  # noqa: E402


class TestIndex(unittest.TestCase):
    def test_every_topic_resolves_to_content(self):
        for record in knowledge.topics():
            with self.subTest(topic=record["topic"]):
                resolved = knowledge.get(record["topic"])
                self.assertTrue(resolved["content"].strip(),
                                f"{record['topic']} resolved to nothing")

    def test_every_topic_has_a_summary(self):
        for record in knowledge.topics():
            with self.subTest(topic=record["topic"]):
                self.assertTrue(record["summary"].strip(),
                                f"{record['topic']} has no summary to rank or display")

    def test_categories_are_declared(self):
        for record in knowledge.topics():
            self.assertIn(record["category"], knowledge.CATEGORIES)

    def test_category_filter_narrows(self):
        everything = knowledge.topics()
        workflow = knowledge.topics(category="workflow")
        self.assertLess(len(workflow), len(everything))
        self.assertTrue(all(item["category"] == "workflow" for item in workflow))

    def test_unknown_category_raises(self):
        with self.assertRaises(knowledge.KnowledgeError):
            knowledge.topics(category="not-a-category")


class TestCorpusDrift(unittest.TestCase):
    """Knowledge added to the repo must not be silently unreachable over MCP."""

    def test_every_skill_is_indexed(self):
        indexed = set(knowledge.index())
        for skill in sorted(knowledge.SKILLS_DIR.glob("*/SKILL.md")):
            self.assertIn(
                skill.parent.name, indexed,
                f"{skill.parent.name} is a skill but is not served by the knowledge tool",
            )

    def test_every_guide_and_kernel_is_indexed(self):
        indexed = set(knowledge.index())
        for directory in (knowledge.GUIDES_DIR, knowledge.KERNELS_DIR):
            for doc in sorted(directory.glob("*.md")):
                if doc.name in knowledge._DOC_SKIPLIST:
                    continue
                self.assertIn(
                    doc.stem, indexed,
                    f"{doc.relative_to(knowledge.REPO_ROOT)} is not served by the knowledge tool",
                )

    def test_extra_docs_still_exist(self):
        for topic, reference in knowledge._EXTRA_DOCS.items():
            with self.subTest(topic=topic):
                self.assertTrue((knowledge.REPO_ROOT / reference).is_file(),
                                f"{topic} points at {reference}, which is gone")

    def test_every_alias_resolves(self):
        for alias in knowledge._ALIASES:
            with self.subTest(alias=alias):
                self.assertIsNotNone(knowledge.resolve_alias(alias),
                                     f"alias '{alias}' points at a topic that does not exist")


class TestResolution(unittest.TestCase):
    def test_referenced_guide_is_inlined_as_prose(self):
        """`resolve-color` points at the colour decision guide; the guide must arrive."""
        resolved = knowledge.get("resolve-color")
        self.assertIn("docs/guides/color-decision-guide.md", resolved["inlined"])
        guide_body = (knowledge.REPO_ROOT / "docs/guides/color-decision-guide.md").read_text(encoding="utf-8")
        # A distinctive line from the guide, not the path that pointed at it.
        sample = [line for line in guide_body.splitlines() if line.startswith("## ")][0]
        self.assertIn(sample.lstrip("# ").strip(), resolved["content"])

    def test_inlining_stops_at_one_level(self):
        """A doc referenced BY an inlined doc must not be dragged in as well."""
        resolved = knowledge.get("resolve-media-pool")["content"]
        first_level = set(knowledge._doc_references(knowledge.index()["resolve-media-pool"]["body"]))
        second_level = set()
        for reference in first_level:
            path = knowledge.REPO_ROOT / reference
            if path.is_file():
                second_level |= set(knowledge._doc_references(path.read_text(encoding="utf-8")))
        for reference in second_level - first_level:
            self.assertNotIn(
                f"_Source: `{reference}`_", resolved,
                f"{reference} was inlined at the second level",
            )

    def test_inline_false_returns_the_bare_body(self):
        with_inline = knowledge.get("resolve-color")
        without = knowledge.get("resolve-color", inline=False)
        self.assertEqual(without["inlined"], [])
        self.assertLess(len(without["content"]), len(with_inline["content"]))

    def test_reference_topics_do_not_inline(self):
        """Exhaustive ledgers are terminal — inlining from them doubles a whole doc."""
        resolved = knowledge.get("mcp-operating-reference")
        self.assertEqual(resolved["category"], "reference")
        self.assertEqual(resolved["inlined"], [])

    def test_oversized_reference_is_summarised_not_truncated(self):
        """Over the budget the agent gets sections + a fetch instruction, not a prefix."""
        resolved = knowledge.get("resolve-mcp")["content"]
        self.assertIn("summarised here rather than inlined", resolved)
        self.assertIn('get(topic="mcp-operating-reference")', resolved)

    def test_canonical_titles_are_client_neutral(self):
        for record in knowledge.index().values():
            with self.subTest(topic=record["topic"]):
                self.assertNotIn("Claude Code Skill", record["title"])

    def test_aliases_reach_the_right_topic(self):
        self.assertEqual(knowledge.get("dead air")["topic"], "resolve-tighten-recording")
        self.assertEqual(knowledge.get("grading")["topic"], "resolve-color")
        self.assertEqual(knowledge.get("DEAD_AIR")["topic"], "resolve-tighten-recording")

    def test_unknown_topic_names_near_matches(self):
        with self.assertRaises(knowledge.KnowledgeError) as caught:
            knowledge.get("colour-guide")
        self.assertIn("color-decision-guide", str(caught.exception))


class TestSections(unittest.TestCase):
    def test_section_returns_a_strict_subtree(self):
        full = knowledge.get("resolve-color", inline=False)
        section_name = full["sections"][0]
        section = knowledge.get("resolve-color", section=section_name)
        self.assertEqual(section["section"], section_name)
        self.assertLess(len(section["content"]), len(full["content"]))
        self.assertTrue(section["content"].startswith("## "))
        # Exactly one heading at this level: the slice stops at the next section.
        headings = [ln for ln in section["content"].splitlines() if ln.startswith("## ")]
        self.assertEqual(len(headings), 1)

    def test_unknown_section_raises_and_lists_the_real_ones(self):
        """The silent-lie guard: a wrong section must not return the whole document."""
        with self.assertRaises(knowledge.KnowledgeError) as caught:
            knowledge.get("resolve-color", section="no such section")
        message = str(caught.exception)
        self.assertIn("unknown section", message)
        self.assertIn(knowledge.get("resolve-color", inline=False)["sections"][0], message)

    def test_section_names_are_matched_case_insensitively(self):
        name = knowledge.get("resolve-color", inline=False)["sections"][0]
        self.assertEqual(
            knowledge.get("resolve-color", section=name.upper())["section"], name
        )


class TestSearch(unittest.TestCase):
    def test_exact_phrase_outranks_a_single_term(self):
        hits = knowledge.search("dead air")
        self.assertEqual(hits[0]["topic"], "resolve-tighten-recording")

    def test_terms_match_whole_words_only(self):
        """"air" must not match inside "Fairlight" — that put audio above tightening."""
        self.assertEqual(knowledge._term_count("fairlight and dead air", "air"), 1)
        self.assertEqual(knowledge._term_count("fairlight", "air"), 0)

    def test_length_does_not_decide_the_ranking(self):
        """Body hits are normalised, so the longest document cannot win on mass alone."""
        hits = knowledge.search("cut to music")
        self.assertNotEqual(hits[0]["topic"], "mcp-operating-reference")

    def test_hits_carry_an_excerpt(self):
        for hit in knowledge.search("grade"):
            self.assertTrue(hit["excerpt"].strip())

    def test_limit_is_honoured(self):
        self.assertLessEqual(len(knowledge.search("resolve", limit=2)), 2)

    def test_empty_query_raises(self):
        with self.assertRaises(knowledge.KnowledgeError):
            knowledge.search("   ")

    def test_no_match_returns_empty(self):
        self.assertEqual(knowledge.search("zzzznotawordanywhere"), [])


class TestToolSurface(unittest.TestCase):
    """The MCP envelope: success shape, error shape, and no Resolve connection."""

    @classmethod
    def setUpClass(cls):
        import types

        fake = types.ModuleType("DaVinciResolveScript")
        fake.scriptapp = lambda *a, **k: None
        sys.modules.setdefault("DaVinciResolveScript", fake)
        from src import server

        cls.server = server

    def test_topics_action(self):
        result = self.server.knowledge("topics")
        self.assertTrue(result["success"])
        self.assertEqual(result["count"], len(result["topics"]))

    def test_get_action(self):
        result = self.server.knowledge("get", {"topic": "resolve-edit"})
        self.assertTrue(result["success"])
        self.assertTrue(result["content"].strip())

    def test_search_action(self):
        result = self.server.knowledge("search", {"query": "timeline"})
        self.assertTrue(result["success"])
        self.assertTrue(result["hits"])

    def test_capabilities_action(self):
        result = self.server.knowledge("capabilities")
        self.assertTrue(result["success"])
        self.assertEqual(result["actions"], self.server._KNOWLEDGE_ACTIONS)

    def test_unknown_topic_is_a_structured_error(self):
        result = self.server.knowledge("get", {"topic": "nope"})
        self.assertNotIn("success", result)
        self.assertEqual(result["error"]["code"], "UNKNOWN_TOPIC")
        self.assertFalse(result["error"]["retryable"])

    def test_unknown_action_lists_the_valid_ones(self):
        result = self.server.knowledge("bogus")
        self.assertIn("topics", result["error"]["message"])

    def test_missing_topic_param_is_reported(self):
        result = self.server.knowledge("get", {})
        self.assertIn("topic", result["error"]["message"])

    def test_resource_mirrors_the_index(self):
        resource = self.server._resource_knowledge_topics()
        self.assertEqual(len(resource["topics"]), len(knowledge.topics()))

    def test_no_resolve_connection_is_attempted(self):
        """A knowledge call must never reach for Resolve — it is pure bundled text."""
        calls = []
        original = self.server.get_resolve
        self.server.get_resolve = lambda *a, **k: calls.append(1) or None
        try:
            self.server.knowledge("topics")
            self.server.knowledge("get", {"topic": "resolve-color"})
            self.server.knowledge("search", {"query": "grade"})
        finally:
            self.server.get_resolve = original
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
