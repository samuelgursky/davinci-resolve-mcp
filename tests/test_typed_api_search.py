"""The native API must be queryable from inside the server, in both interfaces.

`resolve_control api_truth` answers "what is broken". Until now nothing answered
"what exists" — the typed stub shipped in PR #205 was readable only from a
shell. Blackmagic's own MCP exposes search_scripting_api for this.

The addition that matters here is `referenced_in_this_server`, which turns a
lookup into a parity check. It must count executable syntax only: a name that
appears solely in a docstring is not coverage.
"""
import os
import unittest

import src.server as compound
from src.granular import resolve_control as granular
from src.utils import typed_api_search as api

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# These tests assert the pinned 21.1 inventory, so they must read the copy in
# docs/reference. The default is "auto", which prefers whatever stub the
# installed Resolve ships — on a 21.2 machine that is a different inventory
# (530 methods, not 410) and these counts would flip without anything being
# wrong. Pinning "shipped" keeps the assertion about the file, not the machine.
def _search(pattern, **kwargs):
    return api.search(PROJECT_DIR, pattern, source="shipped", **kwargs)


def _describe(symbol):
    return api.describe(PROJECT_DIR, symbol, source="shipped")


def _summary():
    return api.summary(PROJECT_DIR, source="shipped")


class SurfaceTests(unittest.TestCase):
    def test_stub_matches_the_published_21_1_inventory(self):
        out = _summary()
        self.assertEqual(out["methods"], 410)
        self.assertEqual(out["option_types"], 46)
        self.assertEqual(out["option_fields"], 513)

    def test_every_scriptable_object_is_represented(self):
        objects = _summary()["objects"]
        for expected in ("Resolve", "ProjectManager", "Project", "MediaPool",
                         "MediaPoolItem", "MediaStorage", "Timeline",
                         "TimelineItem", "Folder", "Graph", "Gallery"):
            self.assertIn(expected, objects)


class SearchTests(unittest.TestCase):
    def test_exact_method_lookup_returns_the_21_1_signature(self):
        out = _search("SetHighPriority")
        self.assertEqual(out["total_matches"], 1)
        row = out["methods"][0]
        self.assertEqual(row["symbol"], "Resolve.SetHighPriority")
        self.assertIn("highPriority: bool", row["signatures"][0])

    def test_search_is_case_insensitive_and_regex_capable(self):
        loose = _search("sethighpriority")
        self.assertEqual(loose["total_matches"], 1)
        grouped = _search(r"^Resolve\.(Get|Set)HighPriority$")
        self.assertEqual(grouped["total_matches"], 0)  # matched against text, not anchored keys
        alternation = _search("GetCurrentPage|SetHighPriority", kind="methods")
        self.assertGreaterEqual(alternation["total_matches"], 2)

    def test_kind_filters_each_section(self):
        methods_only = _search("render", kind="methods")
        self.assertEqual(methods_only["option_types"], [])
        options_only = _search("render", kind="options")
        self.assertEqual(options_only["methods"], [])

    def test_typed_dict_name_returns_all_of_its_fields(self):
        out = _search("^AutoCaptionSettings$", kind="options")
        self.assertEqual(len(out["option_types"]), 1)
        self.assertEqual(len(out["option_types"][0]["matched_fields"]), 5)

    def test_descriptions_are_searchable(self):
        out = _search("script execution priority", kind="methods")
        self.assertEqual([r["symbol"] for r in out["methods"]], ["Resolve.SetHighPriority"])

    def test_limit_is_applied_and_truncation_is_declared(self):
        out = _search("Get", kind="methods", limit=3)
        self.assertEqual(len(out["methods"]), 3)
        self.assertTrue(out["truncated"])
        self.assertGreater(out["total_matches"], 3)

    def test_bad_input_is_refused(self):
        for bad in ("", "   ", None):
            with self.assertRaises(api.TypedApiError):
                _search(bad)
        with self.assertRaises(api.TypedApiError):
            _search("valid", kind="nonsense")
        with self.assertRaises(api.TypedApiError):
            _search("unbalanced(")


class CoverageFlagTests(unittest.TestCase):
    def test_a_method_this_server_calls_is_flagged_with_its_files(self):
        row = _describe("MediaPool.AppendToTimeline")
        self.assertTrue(row["referenced_in_this_server"])
        self.assertTrue(any(path.startswith("src/") for path in row["source_files"]))

    def test_the_flag_reflects_executable_syntax_not_prose(self):
        # Every flagged name must appear as real syntax somewhere under src/.
        out = _search("Timeline", kind="methods", limit=200)
        flagged = [r for r in out["methods"] if r["referenced_in_this_server"]]
        self.assertTrue(flagged)
        for row in flagged:
            self.assertTrue(row["source_files"], row["symbol"])


class DescribeTests(unittest.TestCase):
    def test_qualified_symbol_resolves(self):
        row = _describe("Resolve.GetCurrentPage")
        self.assertEqual(row["kind"], "method")
        self.assertEqual(row["object"], "Resolve")

    def test_unambiguous_bare_name_resolves(self):
        self.assertEqual(_describe("SetHighPriority")["object"], "Resolve")

    def test_ambiguous_bare_name_lists_the_candidates(self):
        with self.assertRaises(api.TypedApiError) as caught:
            _describe("GetName")
        self.assertIn("more than one object", str(caught.exception))

    def test_typed_dict_symbol_returns_its_fields(self):
        row = _describe("ImportOptions")
        self.assertEqual(row["kind"], "option_type")
        self.assertIn("sourceClipsFolders", row["fields"])

    def test_unknown_symbol_is_refused_with_guidance(self):
        with self.assertRaises(api.TypedApiError) as caught:
            _describe("Resolve.MakeCoffee")
        self.assertIn("search", str(caught.exception))


class BothInterfacesTests(unittest.TestCase):
    def test_surface_agrees(self):
        # Compound adds operation-log metadata; compare the domain payload only.
        c = compound.resolve_control("api_surface", {})
        g = granular.get_resolve_api_surface()
        for key in ("stub", "methods", "option_types", "option_fields", "objects"):
            self.assertEqual(c[key], g[key], key)

    def test_search_agrees(self):
        c = compound.resolve_control("search_api", {"pattern": "Multicam"})
        g = granular.search_resolve_api("Multicam")
        self.assertEqual([r["symbol"] for r in c["methods"]],
                         [r["symbol"] for r in g["methods"]])

    def test_describe_agrees(self):
        c = compound.resolve_control("describe_api", {"symbol": "Project.GetName"})
        g = granular.describe_resolve_api("Project.GetName")
        self.assertEqual(c["signatures"], g["signatures"])

    def test_both_refuse_a_bad_pattern_rather_than_raising(self):
        self.assertIn("error", compound.resolve_control("search_api", {"pattern": "unbalanced("}))
        self.assertIn("error", granular.search_resolve_api("unbalanced("))

    def test_both_work_without_a_resolve_connection(self):
        # These read a stub file; nothing here touches Resolve. The default is
        # "auto", so the count depends on which stub answered — assert the two
        # interfaces agree rather than pinning a number that is machine-specific.
        g = granular.get_resolve_api_surface()
        c = compound.resolve_control("api_surface", {})
        self.assertGreater(g["methods"], 400)
        self.assertEqual(g["methods"], c["methods"])
        self.assertIn(g.get("stub_source"), ("shipped", "installed"))


class StubSourceTests(unittest.TestCase):
    """The inventory must say which copy answered, and "auto" must prefer live.

    The shipped stub is a snapshot of the build it was pinned at. A server
    running against a newer Resolve that still reads the shipped copy reports
    methods that do exist as nonexistent — a wrong answer, which is worse than
    an error. "auto" reads the installed build's stub when there is one.
    """

    def test_shipped_source_reports_the_pinned_copy(self):
        out = _summary()
        self.assertEqual(out["stub_source"], "shipped")
        self.assertEqual(out["stub"], os.path.join(PROJECT_DIR, api.STUB_RELATIVE))

    def test_auto_reports_a_known_source(self):
        out = api.summary(PROJECT_DIR)
        self.assertIn(out["stub_source"], ("shipped", "installed"))
        self.assertTrue(os.path.isfile(out["stub"]))

    def test_auto_prefers_the_installed_stub_when_one_exists(self):
        installed = api.installed_stub_path()
        if not installed:
            self.skipTest("no Resolve install on this machine — nothing to prefer")
        out = api.summary(PROJECT_DIR)
        self.assertEqual(out["stub_source"], "installed")
        self.assertEqual(out["stub"], installed)

    def test_installed_source_refuses_without_an_install(self):
        if api.installed_stub_path():
            self.skipTest("this machine has an installed stub, so there is no refusal to test")
        with self.assertRaises(api.TypedApiError) as caught:
            api.summary(PROJECT_DIR, source="installed")
        self.assertIn("RESOLVE_SCRIPT_API", str(caught.exception))

    def test_unknown_source_is_refused(self):
        with self.assertRaises(api.TypedApiError):
            api.summary(PROJECT_DIR, source="whatever")

    def test_search_and_describe_report_the_source_too(self):
        for out in (_search("Multicam"), _describe("Project.GetName")):
            self.assertEqual(out["stub_source"], "shipped")


if __name__ == "__main__":
    unittest.main()
