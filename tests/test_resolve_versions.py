"""Version-aware routing: parsing, gates, and the defaults that keep it honest.

The load-bearing tests here are the negative ones. A version checker that
guesses "available" for an unknown symbol is worse than none at all — it is the
mechanism behind issue #132, where an agent insisted a method existed on DR 21.
"""

import unittest

from src.utils.resolve_versions import (
    AVAILABLE,
    UNAVAILABLE,
    UNKNOWN,
    VERSION_GATES,
    annotate_facts,
    at_least,
    availability,
    compare_versions,
    gates_unavailable_on,
    measurement_relevance,
    parse_version,
)


class ParseVersionTest(unittest.TestCase):
    def test_parses_the_three_shapes_resolve_reports(self):
        # GetVersionString()
        self.assertEqual(parse_version("19.1.3.7"), (19, 1, 3, 7))
        # GetVersion() — list with a trailing build string
        self.assertEqual(parse_version([19, 1, 3, 7, ""]), (19, 1, 3, 7))
        # prose in this repo's own docs
        self.assertEqual(parse_version("DaVinci Resolve Studio 21.0.4.5 (macOS)"), (21, 0, 4, 5))

    def test_prefers_the_most_specific_run_in_a_sentence(self):
        """'Resolve 21, build 21.0.4.5' must not parse as (21,)."""
        self.assertEqual(parse_version("Resolve 21, build 21.0.4.5"), (21, 0, 4, 5))

    def test_unparseable_input_is_none_not_zero(self):
        for value in (None, "", "unknown", "Studio", [], {}, True):
            self.assertIsNone(parse_version(value), value)


class CompareTest(unittest.TestCase):
    def test_shorter_versions_compare_zero_padded(self):
        self.assertEqual(compare_versions("21.0", "21.0.0"), 0)
        self.assertEqual(compare_versions("21.0.0.0", "21.0"), 0)

    def test_patch_level_differences_are_respected(self):
        """The whole point: 21.0.2 and 21.0.4 are different APIs."""
        self.assertEqual(compare_versions("21.0.2", "21.0.4"), -1)
        self.assertEqual(compare_versions("21.0.4", "21.0.2"), 1)

    def test_comparison_with_an_unparseable_side_is_none(self):
        self.assertIsNone(compare_versions("21.0.4", "unknown"))
        self.assertIsNone(at_least("nonsense", "20.2.2"))


class AvailabilityTest(unittest.TestCase):
    def test_unknown_symbol_is_unknown_never_available(self):
        """The default that matters. An unbisected method must not read as present."""
        result = availability("Timeline.SomeMethodNobodyProbed", "21.0.4.5")
        self.assertEqual(result["status"], UNKNOWN)
        self.assertIn("Probe it", result["remediation"])

    def test_measured_gate_resolves_both_ways(self):
        old = availability("Resolve.GetFairlightPresets", "19.1.3.7")
        self.assertEqual(old["status"], UNAVAILABLE)
        self.assertEqual(old["introduced_in"], "20.2.2")
        self.assertIn("20.2.2", old["remediation"])

        new = availability("Resolve.GetFairlightPresets", "20.2.2")
        self.assertEqual(new["status"], AVAILABLE)
        self.assertIsNone(new["remediation"])

    def test_gate_records_whether_we_measured_it_or_a_reporter_did(self):
        """Relaying a fact should be able to say how strong it is."""
        measured = availability("Resolve.GetFairlightPresets", "21.0.4")
        self.assertEqual(measured["source"], "measured")

        reported = availability("Timeline.GetSelectedClips", "19.1.3.7")
        self.assertEqual(reported["source"], "reported")

    def test_unparseable_live_version_is_unknown_not_unavailable(self):
        """Failing to read the build must not be reported as 'you lack this'."""
        result = availability("Resolve.GetFairlightPresets", "who knows")
        self.assertEqual(result["status"], UNKNOWN)

    def test_every_gate_declares_evidence_and_parses(self):
        for gate in VERSION_GATES:
            self.assertIn(gate["source"], {"measured", "reported", "vendor"}, gate["symbol"])
            self.assertIsNotNone(parse_version(gate["introduced_in"]), gate["symbol"])


class GatesUnavailableTest(unittest.TestCase):
    def test_old_build_reports_every_gate_it_misses(self):
        missing = {g["symbol"] for g in gates_unavailable_on("19.1.3.7")}
        self.assertIn("Resolve.GetFairlightPresets", missing)
        self.assertIn("Timeline.GetSelectedClips", missing)

    def test_new_build_clears_everything_recorded(self):
        self.assertEqual(gates_unavailable_on("21.0.4.5"), [])

    def test_the_21_0_2_vs_21_0_4_split_is_visible(self):
        """A 'Resolve 21' label would hide this entirely."""
        missing = {g["symbol"] for g in gates_unavailable_on("21.0.2.4")}
        self.assertIn("Timeline.GetSelectedClips", missing)
        self.assertNotIn("Resolve.GetFairlightPresets", missing)


class MeasurementRelevanceTest(unittest.TestCase):
    def test_older_measurement_is_a_prior_not_a_finding(self):
        result = measurement_relevance("19.1.3.7", "21.0.4.5")
        self.assertEqual(result["relevance"], "older_measurement")
        self.assertIn("prior", result["note"])

    def test_newer_measurement_warns_the_fix_has_not_landed(self):
        result = measurement_relevance("21.0.4.5", "19.1.3.7")
        self.assertEqual(result["relevance"], "newer_measurement")

    def test_same_build_says_so(self):
        self.assertEqual(
            measurement_relevance("21.0.2", "21.0.2.0")["relevance"], "same_build"
        )


class AnnotateFactsTest(unittest.TestCase):
    def test_annotation_does_not_mutate_the_ledger(self):
        original = {"symbol": "Resolve.GetFairlightPresets", "reality": "..."}
        annotate_facts([original], "19.1.3.7", ledger_verified_on="21.0.2")
        self.assertNotIn("version_context", original)

    def test_no_live_version_annotates_nothing(self):
        out = annotate_facts([{"symbol": "X"}], None)
        self.assertNotIn("version_context", out[0])

    def test_ledger_stamp_is_never_claimed_as_a_per_fact_measurement(self):
        """Most entries state their real build in prose, not a field.

        Attributing the ledger-wide review stamp to each of them would invent a
        measurement that never happened — so an unstamped entry is `unknown`.
        """
        out = annotate_facts(
            [{"symbol": "Resolve.GetFairlightPresets", "reality": "..."}],
            "19.1.3.7",
            ledger_verified_on="DaVinci Resolve Studio 21.0.2",
        )
        context = out[0]["version_context"]
        self.assertEqual(context["relevance"], UNKNOWN)
        self.assertNotIn("measured_on", context)
        self.assertEqual(context["ledger_reviewed_on"], "DaVinci Resolve Studio 21.0.2")

    def test_a_structured_stamp_is_compared_properly(self):
        out = annotate_facts(
            [{"symbol": "X", "verified_on": "19.1.3.7"}], "21.0.4.5"
        )
        self.assertEqual(out[0]["version_context"]["relevance"], "older_measurement")

    def test_gated_symbol_gets_availability_regardless_of_stamp(self):
        out = annotate_facts([{"symbol": "Resolve.GetFairlightPresets"}], "19.1.3.7")
        self.assertEqual(
            out[0]["version_context"]["availability"]["status"], UNAVAILABLE
        )


if __name__ == "__main__":
    unittest.main()
