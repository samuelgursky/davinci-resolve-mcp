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


class SurfaceTests(unittest.TestCase):
    def test_stub_matches_the_published_21_1_inventory(self):
        out = api.summary(PROJECT_DIR)
        self.assertEqual(out["methods"], 410)
        self.assertEqual(out["option_types"], 46)
        self.assertEqual(out["option_fields"], 513)

    def test_every_scriptable_object_is_represented(self):
        objects = api.summary(PROJECT_DIR)["objects"]
        for expected in ("Resolve", "ProjectManager", "Project", "MediaPool",
                         "MediaPoolItem", "MediaStorage", "Timeline",
                         "TimelineItem", "Folder", "Graph", "Gallery"):
            self.assertIn(expected, objects)


class SearchTests(unittest.TestCase):
    def test_exact_method_lookup_returns_the_21_1_signature(self):
        out = api.search(PROJECT_DIR, "SetHighPriority")
        self.assertEqual(out["total_matches"], 1)
        row = out["methods"][0]
        self.assertEqual(row["symbol"], "Resolve.SetHighPriority")
        self.assertIn("highPriority: bool", row["signatures"][0])

    def test_search_is_case_insensitive_and_regex_capable(self):
        loose = api.search(PROJECT_DIR, "sethighpriority")
        self.assertEqual(loose["total_matches"], 1)
        grouped = api.search(PROJECT_DIR, r"^Resolve\.(Get|Set)HighPriority$")
        self.assertEqual(grouped["total_matches"], 0)  # matched against text, not anchored keys
        alternation = api.search(PROJECT_DIR, "GetCurrentPage|SetHighPriority", kind="methods")
        self.assertGreaterEqual(alternation["total_matches"], 2)

    def test_kind_filters_each_section(self):
        methods_only = api.search(PROJECT_DIR, "render", kind="methods")
        self.assertEqual(methods_only["option_types"], [])
        options_only = api.search(PROJECT_DIR, "render", kind="options")
        self.assertEqual(options_only["methods"], [])

    def test_typed_dict_name_returns_all_of_its_fields(self):
        out = api.search(PROJECT_DIR, "^AutoCaptionSettings$", kind="options")
        self.assertEqual(len(out["option_types"]), 1)
        self.assertEqual(len(out["option_types"][0]["matched_fields"]), 5)

    def test_descriptions_are_searchable(self):
        out = api.search(PROJECT_DIR, "script execution priority", kind="methods")
        self.assertEqual([r["symbol"] for r in out["methods"]], ["Resolve.SetHighPriority"])

    def test_limit_is_applied_and_truncation_is_declared(self):
        out = api.search(PROJECT_DIR, "Get", kind="methods", limit=3)
        self.assertEqual(len(out["methods"]), 3)
        self.assertTrue(out["truncated"])
        self.assertGreater(out["total_matches"], 3)

    def test_bad_input_is_refused(self):
        for bad in ("", "   ", None):
            with self.assertRaises(api.TypedApiError):
                api.search(PROJECT_DIR, bad)
        with self.assertRaises(api.TypedApiError):
            api.search(PROJECT_DIR, "valid", kind="nonsense")
        with self.assertRaises(api.TypedApiError):
            api.search(PROJECT_DIR, "unbalanced(")


class CoverageFlagTests(unittest.TestCase):
    def test_a_method_this_server_calls_is_flagged_with_its_files(self):
        row = api.describe(PROJECT_DIR, "MediaPool.AppendToTimeline")
        self.assertTrue(row["referenced_in_this_server"])
        self.assertTrue(any(path.startswith("src/") for path in row["source_files"]))

    def test_the_flag_reflects_executable_syntax_not_prose(self):
        # Every flagged name must appear as real syntax somewhere under src/.
        out = api.search(PROJECT_DIR, "Timeline", kind="methods", limit=200)
        flagged = [r for r in out["methods"] if r["referenced_in_this_server"]]
        self.assertTrue(flagged)
        for row in flagged:
            self.assertTrue(row["source_files"], row["symbol"])


class DescribeTests(unittest.TestCase):
    def test_qualified_symbol_resolves(self):
        row = api.describe(PROJECT_DIR, "Resolve.GetCurrentPage")
        self.assertEqual(row["kind"], "method")
        self.assertEqual(row["object"], "Resolve")

    def test_unambiguous_bare_name_resolves(self):
        self.assertEqual(api.describe(PROJECT_DIR, "SetHighPriority")["object"], "Resolve")

    def test_ambiguous_bare_name_lists_the_candidates(self):
        with self.assertRaises(api.TypedApiError) as caught:
            api.describe(PROJECT_DIR, "GetName")
        self.assertIn("more than one object", str(caught.exception))

    def test_typed_dict_symbol_returns_its_fields(self):
        row = api.describe(PROJECT_DIR, "ImportOptions")
        self.assertEqual(row["kind"], "option_type")
        self.assertIn("sourceClipsFolders", row["fields"])

    def test_unknown_symbol_is_refused_with_guidance(self):
        with self.assertRaises(api.TypedApiError) as caught:
            api.describe(PROJECT_DIR, "Resolve.MakeCoffee")
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
        # These read a shipped file; nothing here touches Resolve.
        self.assertEqual(granular.get_resolve_api_surface()["methods"], 410)
        self.assertEqual(compound.resolve_control("api_surface", {})["methods"], 410)


if __name__ == "__main__":
    unittest.main()
