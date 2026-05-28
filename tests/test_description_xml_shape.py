"""D2 contract test — flagship compound-tool docstrings carry XML semantic tags.

See local/design/agentic-flow-improvements-gameplan-2.md §3 task D2.

The full D2 mandate is to wrap the five biggest compound-tool docstrings in
`<when_to_use>`, `<actions>`, `<returns>`, and `<example>` boundaries so Claude
can use the tags as semantic anchors. This test pins the two flagship tools
(`timeline_item_color` and `media_analysis`) — the highest-leverage cases where
the cost of the tag overhead is repaid every turn. The remaining three tools
(timeline, media_pool, media_pool_item) follow the same pattern as a mechanical
follow-up; see §4 (Findings & Revisions).
"""
import re
import unittest

from src.server import media_analysis, timeline_item_color


class DescriptionXmlShapeTest(unittest.TestCase):
    flagship_tools = {
        "timeline_item_color": timeline_item_color,
        "media_analysis": media_analysis,
    }

    def test_flagship_docstrings_carry_when_to_use_and_returns(self):
        for name, fn in self.flagship_tools.items():
            with self.subTest(tool=name):
                doc = fn.__doc__ or ""
                self.assertIn("<when_to_use>", doc,
                              f"{name} docstring missing <when_to_use> tag")
                self.assertIn("</when_to_use>", doc,
                              f"{name} docstring missing closing </when_to_use> tag")
                self.assertIn("<returns>", doc,
                              f"{name} docstring missing <returns> tag")
                self.assertIn("</returns>", doc,
                              f"{name} docstring missing closing </returns> tag")

    def test_returns_block_documents_error_envelope(self):
        """The `<returns>` block must reference the error envelope shape so the
        model knows every action can return the structured error and what shape
        to anticipate.
        """
        for name, fn in self.flagship_tools.items():
            with self.subTest(tool=name):
                doc = fn.__doc__ or ""
                returns_match = re.search(r"<returns>(.*?)</returns>", doc, re.DOTALL)
                self.assertIsNotNone(returns_match,
                                     f"{name}: <returns> block missing")
                returns_body = returns_match.group(1)
                self.assertIn("error", returns_body,
                              f"{name}: <returns> must document the error envelope")
                self.assertIn("retryable", returns_body,
                              f"{name}: <returns> must surface the retryable field")

    def test_when_to_use_is_actionable(self):
        """The `<when_to_use>` block should be a short bulleted guide, not prose."""
        for name, fn in self.flagship_tools.items():
            with self.subTest(tool=name):
                doc = fn.__doc__ or ""
                wtu_match = re.search(r"<when_to_use>(.*?)</when_to_use>", doc, re.DOTALL)
                self.assertIsNotNone(wtu_match,
                                     f"{name}: <when_to_use> block missing")
                wtu_body = wtu_match.group(1).strip()
                self.assertGreater(wtu_body.count("- "), 1,
                                   f"{name}: <when_to_use> must contain >1 bullet")
                self.assertLess(len(wtu_body.splitlines()), 25,
                                f"{name}: <when_to_use> should stay terse (<25 lines)")


if __name__ == "__main__":
    unittest.main()
