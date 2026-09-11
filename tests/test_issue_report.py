"""report_issue: chat-drafted bug reports and feature requests.

The action must never file anything, never connect to Resolve, and never let a
local path, username or secret into a link that is about to be pasted into a
public issue tracker.
"""
import re
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

import src.server as s
from src.utils import issue_report as ir

REPO_ROOT = Path(__file__).resolve().parents[1]

POSIX_ID = {"home": "/Users/jdoe", "names": ["jdoe", "Jane Doe", "Janes-MacBook-Pro"]}
WINDOWS_ID = {"home": "C:\\Users\\jdoe", "names": ["jdoe"]}


def _query(url):
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


class RedactPathsTest(unittest.TestCase):
    def redact(self, text, identity=POSIX_ID):
        return ir.redact(text, identity)[0]

    def test_path_with_spaces_keeps_only_extension(self):
        out = self.redact("Import failed for /Volumes/CLIENT X/Acme Spot/A001 take 2.mov: not found")
        self.assertEqual(out, "Import failed for <path>.mov: not found")

    def test_two_paths_in_one_sentence_stay_two(self):
        self.assertEqual(self.redact("copied /tmp/a to /tmp/b and it broke."),
                         "copied <path> to <path> and it broke.")

    def test_comma_ends_a_path(self):
        out = self.redact("log at /Users/jdoe/Library/Logs/x.log, see ~/.davinci-resolve-mcp/bridge.json")
        self.assertEqual(out, "log at <path>.log, see ~/.davinci-resolve-mcp/bridge.json")

    def test_install_paths_are_kept(self):
        text = "API at /Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules"
        self.assertEqual(self.redact(text), text)

    def test_home_is_folded_before_the_keep_check(self):
        self.assertEqual(self.redact("see /Users/jdoe/.davinci-resolve-mcp/bridge.json"),
                         "see ~/.davinci-resolve-mcp/bridge.json")

    def test_windows_home_path_is_redacted_not_folded_to_tilde(self):
        # Folding C:\Users\jdoe to ~ across the whole text first would leave
        # "~\Videos\Client Reel\..." — no longer path-shaped, so it would leak.
        out = self.redact(r"C:\Users\jdoe\Videos\Client Reel\shot_010.mxf", WINDOWS_ID)
        self.assertEqual(out, "<path>.mxf")

    def test_windows_install_path_is_kept(self):
        text = r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"
        self.assertEqual(self.redact(text, WINDOWS_ID), text)

    def test_unc_path(self):
        self.assertEqual(self.redact("\\\\nas01\\share\\Job 42\\edit.drp"), "<path>.drp")

    def test_urls_and_slash_prose_are_not_paths(self):
        text = ("https://github.com/samuelgursky/davinci-resolve-mcp/issues/203 "
                "timeline/append_clips and/or 29.97/30 at 01:00:00:00")
        self.assertEqual(self.redact(text, {"home": "/Users/x", "names": []}), text)


class RedactSecretsAndIdentityTest(unittest.TestCase):
    def test_panel_token_fragment(self):
        out, counts = ir.redact("open http://127.0.0.1:8765/#token=abc123XYZ now", POSIX_ID)
        self.assertEqual(out, "open http://127.0.0.1:8765/#token=<redacted> now")
        self.assertEqual(counts["secrets"], 1)

    def test_keys_bearer_assignments_and_email(self):
        out, counts = ir.redact(
            "jane@acme.com sk-ant-api03-abcdefghijklmnopqrstuv api_key=hunter2 Bearer eyJhbGciOi.xx",
            POSIX_ID,
        )
        for leaked in ("jane@acme.com", "abcdefghijklmnop", "hunter2", "eyJhbGciOi"):
            self.assertNotIn(leaked, out)
        self.assertEqual(counts["emails"], 1)
        self.assertEqual(counts["secrets"], 3)

    def test_identity_uses_letter_boundaries_not_word_boundaries(self):
        # \b would miss jdoe_project: `_` is a word character.
        out = ir.redact("jdoe_project and jdoe2 failed for Jane Doe on Janes-MacBook-Pro", POSIX_ID)[0]
        self.assertEqual(out, "<user>_project and <user>2 failed for <user> on <user>")

    def test_identity_does_not_eat_longer_words(self):
        out = ir.redact("a sample of samples", {"home": "", "names": ["sam"]})[0]
        self.assertEqual(out, "a sample of samples")

    def test_common_account_names_are_left_alone(self):
        out = ir.redact("the user opened the editor", {"home": "", "names": ["user", "editor"]})[0]
        self.assertEqual(out, "the user opened the editor")


class BuildIssueTest(unittest.TestCase):
    ENV = {"MCP server": "9.9.9", "DaVinci Resolve": "not connected", "OS": "macOS 26.5 (arm64)"}

    def test_bug_layout_labels_and_link_round_trip(self):
        draft = ir.build_issue(
            "bug", "append_clips drops audio", "Audio tracks vanish",
            steps=["open project", "append /Users/jdoe/Movies/a.mov"],
            expected="audio kept", actual="audio gone",
            tool="timeline", tool_action="append_clips", error="Traceback: boom",
            environment=self.ENV, identity=POSIX_ID,
        )
        self.assertEqual(draft["labels"], ["bug"])
        self.assertFalse(draft["url_truncated"])
        body = draft["body"]
        for heading in ("### What happened", "### Steps to reproduce", "### Expected",
                        "### Actual", "### Failing call", "### Environment"):
            self.assertIn(heading, body)
        self.assertIn("2. append <path>.mov", body)
        self.assertIn("`timeline` → `append_clips`", body)
        self.assertIn("```\nTraceback: boom\n```", body)
        self.assertIn("| MCP server | 9.9.9 |", body)
        self.assertIn("<!-- filed-via: davinci-resolve-mcp report_issue -->", body)
        self.assertEqual(draft["redactions"]["paths"], 1)

        url = urlparse(draft["url"])
        self.assertEqual(url.netloc, "github.com")
        self.assertEqual(url.path, f"/{ir.DEFAULT_REPO}/issues/new")
        q = _query(draft["url"])
        self.assertEqual(q["title"], "append_clips drops audio")
        self.assertEqual(q["body"], body)
        self.assertEqual(q["labels"], "bug")
        self.assertEqual(q["template"], "bug_report.md")

    def test_feature_layout(self):
        draft = ir.build_issue("feature", "Batch rename", "Rename clips in bulk",
                               use_case="200 clips", proposal="a rename action",
                               identity=POSIX_ID)
        self.assertEqual(draft["labels"], ["enhancement"])
        self.assertIn("### What I'd like", draft["body"])
        self.assertIn("### How it could work", draft["body"])
        self.assertNotIn("### Environment", draft["body"])
        self.assertEqual(_query(draft["url"])["template"], "feature_request.md")

    def test_error_containing_a_fence_cannot_break_out(self):
        draft = ir.build_issue("bug", "t", "s", error="a\n```\n## injected", identity=POSIX_ID)
        self.assertIn("````\na\n```\n## injected\n````", draft["body"])

    def test_long_report_is_shortened_in_the_link_but_keeps_the_environment(self):
        # Spaces percent-encode to three characters, so this overflows the link.
        draft = ir.build_issue("bug", "t", "x " * 1500, error="y " * 1900,
                               environment=self.ENV, identity=POSIX_ID)
        self.assertTrue(draft["url_truncated"])
        self.assertLessEqual(len(draft["url"]), ir.MAX_URL_CHARS)
        linked = _query(draft["url"])["body"]
        self.assertIn("truncated to fit the link", linked)
        self.assertIn("| MCP server | 9.9.9 |", linked)
        self.assertIn("filed-via", linked)
        # The chat still gets the whole thing.
        self.assertIn("y " * 1899 + "y", draft["body"])

    def test_title_is_one_line_and_redacted(self):
        draft = ir.build_issue("bug", "fails on\n/Volumes/Acme/x.mov", "s", identity=POSIX_ID)
        self.assertEqual(draft["title"], "fails on <path>.mov")

    def test_kind_aliases(self):
        self.assertEqual(ir.normalize_kind("Feature Request"), "feature")
        self.assertEqual(ir.normalize_kind("bug-report"), "bug")
        self.assertIsNone(ir.normalize_kind("question"))


class ReportIssueActionTest(unittest.TestCase):
    def setUp(self):
        self._resolve = s.resolve
        s.resolve = None

    def tearDown(self):
        s.resolve = self._resolve

    def test_drafts_without_connecting_and_files_nothing(self):
        with mock.patch.object(s, "_try_connect", side_effect=AssertionError("connected")), \
             mock.patch.object(s, "_launch_resolve", side_effect=AssertionError("launched")):
            out = s.resolve_control("report_issue", {
                "kind": "bug", "title": "Bridge never answers",
                "summary": "Connection error on free 21.1",
            })
        self.assertTrue(out["success"])
        self.assertFalse(out["submitted"])
        self.assertIn("Nothing has been filed", out["next_step"])
        self.assertIn(f"| MCP server | {s.VERSION} |", out["body"])
        self.assertIn("| DaVinci Resolve | not connected |", out["body"])
        self.assertTrue(out["url"].startswith("https://github.com/"))

    def test_connected_handle_reports_build_and_mode(self):
        handle = mock.Mock()
        handle.GetProductName.return_value = "DaVinci Resolve Studio"
        handle.GetVersionString.return_value = "21.0.4.5"
        s.resolve = handle
        out = s.resolve_control("report_issue", {"kind": "bug", "title": "t", "summary": "s"})
        self.assertIn("| DaVinci Resolve | DaVinci Resolve Studio 21.0.4.5 |", out["body"])
        self.assertIn("| Connection | local scripting |", out["body"])

    def test_include_environment_false(self):
        out = s.resolve_control("report_issue", {
            "kind": "feature", "title": "t", "summary": "s", "include_environment": False,
        })
        self.assertNotIn("### Environment", out["body"])

    def test_rejects_unknown_kind(self):
        out = s.resolve_control("report_issue", {"kind": "question", "title": "t", "summary": "s"})
        self.assertEqual(out["error"]["code"], "INVALID_KIND")

    def test_requires_title_and_summary(self):
        out = s.resolve_control("report_issue", {"kind": "bug", "title": "t"})
        self.assertEqual(out["error"]["code"], "MISSING_FIELDS")

    def test_server_instructions_point_at_the_action(self):
        self.assertIn("report_issue", s.mcp.instructions)


class IssueTemplatesTest(unittest.TestCase):
    def test_every_kind_has_a_template_carrying_its_label(self):
        for kind, spec in ir.KINDS.items():
            path = REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / spec["template"]
            self.assertTrue(path.is_file(), f"{kind}: {path} missing")
            front = path.read_text(encoding="utf-8").split("---")[1]
            self.assertRegex(front, rf"(?m)^labels:\s*{re.escape(spec['label'])}\s*$")


if __name__ == "__main__":
    unittest.main()
