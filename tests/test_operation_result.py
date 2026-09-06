"""The operation envelope, and the domain keys it must never touch.

Adapted from PR #181. The design there merged the envelope into the top level
of every return, which silently destroyed five domain key names that already
existed here — `status` most damagingly of all. The `DomainKeysSurvive` class
below is the regression suite for that: each case is a real return shape from
`src/server.py` whose meaning the flat envelope changed.
"""

import json
import os
import tempfile
import unittest
from unittest import mock

from src.utils import operation_result as opres
from src.utils.operation_result import (
    ENVELOPE_KEY,
    build_operation_envelope,
    extract_changes,
    extract_verification,
    extract_warnings,
    normalize_status,
)
from src.utils.readback import as_verification_dict


def envelope_of(result):
    return result[ENVELOPE_KEY]


class ModeSelection(unittest.TestCase):
    def setUp(self):
        self.addCleanup(opres.set_envelope_mode, opres.get_envelope_mode())

    def test_dual_is_the_default(self):
        self.assertEqual(opres.DEFAULT_MODE, "dual")

    def test_dual_leaves_the_payload_untouched(self):
        raw = {"success": True, "frame": 42}
        out = build_operation_envelope("timeline_markers", "add", {}, dict(raw))
        self.assertEqual({k: v for k, v in out.items() if k != ENVELOPE_KEY}, raw)

    def test_pure_nests_the_payload_under_result(self):
        raw = {"success": True, "frame": 42}
        out = build_operation_envelope(
            "timeline_markers", "add", {"envelope": "pure"}, dict(raw))
        self.assertEqual(out["result"], raw)
        self.assertNotIn("frame", out)

    def test_legacy_adds_nothing(self):
        raw = {"success": True, "status": "done"}
        out = build_operation_envelope("resolve_control", "job_status", {"envelope": "legacy"}, dict(raw))
        self.assertEqual(out, raw)

    def test_a_per_call_mode_overrides_the_default(self):
        opres.set_envelope_mode("legacy")
        out = build_operation_envelope("timeline", "get", {"envelope": "pure"}, {"a": 1})
        self.assertEqual(out["result"], {"a": 1})

    def test_an_unknown_mode_falls_back_rather_than_raising(self):
        out = build_operation_envelope("timeline", "get", {"envelope": "nonsense"}, {"a": 1})
        self.assertIn(ENVELOPE_KEY, out)

    def test_set_envelope_mode_rejects_unknown_values(self):
        opres.set_envelope_mode("pure")
        self.assertEqual(opres.set_envelope_mode("banana"), "pure")

    def test_the_env_var_seeds_the_default(self):
        with mock.patch.dict(os.environ, {"RESOLVE_MCP_RESULT_ENVELOPE": "pure"}):
            import importlib
            reloaded = importlib.reload(opres)
            try:
                self.assertEqual(reloaded.get_envelope_mode(), "pure")
            finally:
                importlib.reload(opres)


class DomainKeysSurvive(unittest.TestCase):
    """Real return shapes whose meaning a flattened envelope destroyed.

    Every case here is a live payload from `src/server.py`, not a hypothetical.
    """

    def assert_intact(self, raw, **expected):
        out = build_operation_envelope("tool", "action", {}, dict(raw))
        for key, value in expected.items():
            self.assertEqual(out[key], value, f"{key} was clobbered")
        return out

    def test_a_background_jobs_status_still_says_done(self):
        # resolve_control("job_status") — an agent polls this until it reads
        # "done". Rewriting it to "success" means the job never appears to end.
        self.assert_intact({"id": "j1", "status": "done"}, status="done")

    def test_a_confirm_gate_keeps_its_own_status(self):
        # _issue_confirm_token is the single producer of these. The envelope
        # reports "blocked" in its own namespace; the wire signal every client
        # already checks stays exactly as it was.
        out = self.assert_intact(
            {"status": "confirmation_required", "confirm_token": "t"},
            status="confirmation_required", confirm_token="t")
        self.assertEqual(envelope_of(out)["status"], "blocked")

    def test_a_transcription_status_is_resolves_own_word(self):
        self.assert_intact(
            {"has_transcription": True, "status": "Transcribed"}, status="Transcribed")

    def test_a_domain_warnings_list_is_not_replaced(self):
        self.assert_intact({"warnings": ["a", "b"]}, warnings=["a", "b"])

    def test_a_clean_payload_gains_no_warnings_key(self):
        # render set_settings has a test asserting exactly this absence.
        out = build_operation_envelope("render", "set_settings", {}, {"success": True})
        self.assertNotIn("warnings", out)
        self.assertNotIn("warnings", envelope_of(out))

    def test_a_domain_changes_block_is_not_replaced(self):
        # setup("set_defaults") returns per-store change reports under `changes`.
        raw = {"success": True, "changes": {"media_analysis": {"changed": True}}}
        self.assert_intact(raw, changes=raw["changes"])

    def test_a_domain_operation_key_is_not_replaced(self):
        self.assert_intact({"operation": "bulk_match_to_hero"}, operation="bulk_match_to_hero")

    def test_a_domain_result_key_is_not_replaced(self):
        self.assert_intact({"result": [1, 2, 3]}, result=[1, 2, 3])

    def test_nothing_is_dropped_from_any_payload(self):
        raw = {"status": "x", "operation": "y", "warnings": ["w"], "result": 1,
               "changes": {"c": 1}, "verification": {"v": 1}, "success": True}
        out = build_operation_envelope("tool", "action", {}, dict(raw))
        self.assertEqual(set(raw) - set(out), set())


class StatusNormalization(unittest.TestCase):
    def test_plain_success(self):
        self.assertEqual(normalize_status({"success": True}), "success")

    def test_explicit_failure(self):
        self.assertEqual(normalize_status({"success": False}), "failed")

    def test_an_error_envelope_is_failed(self):
        self.assertEqual(normalize_status({"error": {"message": "no"}}), "failed")

    def test_confirmation_required_is_blocked(self):
        self.assertEqual(normalize_status({"status": "confirmation_required"}), "blocked")
        self.assertEqual(normalize_status({"confirmation_required": True}), "blocked")

    def test_a_domain_blocked_list_is_not_a_gate(self):
        # `blocked` here is the list of targets that could not be resolved —
        # timeline_item_color.bulk_match_to_hero returns a non-empty one on a
        # perfectly successful dry run. Reading it as a gate reports a
        # confirmation that was never requested.
        self.assertEqual(
            normalize_status({"success": True, "dry_run": True,
                              "blocked": [{"id": "c2", "reason": "unresolved"}],
                              "proposals": [{"id": "c1"}]}),
            "success")

    def test_explicit_partial(self):
        self.assertEqual(normalize_status({"partial": True}), "partial")

    def test_mixed_bulk_counts_are_partial(self):
        self.assertEqual(normalize_status({"succeeded": 3, "failed": 2}), "partial")

    def test_a_clean_bulk_run_is_success(self):
        self.assertEqual(normalize_status({"succeeded": 3, "failed": 0}), "success")

    def test_a_non_dict_return(self):
        self.assertEqual(normalize_status([1, 2]), "success")
        self.assertEqual(normalize_status(None), "failed")


class Verification(unittest.TestCase):
    def test_no_evidence_reads_unverified(self):
        self.assertEqual(extract_verification({"success": True})["status"], "unverified")

    def test_a_clean_readback_passes(self):
        v = extract_verification({"readback": {"missing": []}})
        self.assertEqual(v["status"], "passed")
        self.assertEqual(v["checks"][0]["missing_items"], 0)

    def test_a_readback_with_missing_items_fails(self):
        v = extract_verification({"readback": {"missing": [{"start": 1}]}})
        self.assertEqual(v["status"], "failed")
        self.assertEqual(v["checks"][0]["missing_items"], 1)

    def test_a_contradiction_is_not_flattened_into_failure(self):
        # "the API said yes and the post-state says no" is a different thing to
        # act on than "the call failed" — this repo's most valuable signal.
        v = extract_verification({"verified": False, "contradiction": True, "observed": None})
        self.assertEqual(v["status"], "contradiction")
        self.assertTrue(v["contradiction"])

    def test_property_restore_failures_downgrade_a_pass_to_partial(self):
        v = extract_verification({
            "readback": {"missing": []},
            "property_restore_failures": 2, "properties_restored_items": 5})
        self.assertEqual(v["status"], "partial")

    def test_bulk_counts_become_a_check(self):
        v = extract_verification({"succeeded": 2, "failed": 1})
        self.assertEqual(v["status"], "partial")
        self.assertEqual(v["checks"][0]["check"], "bulk_operations")

    def test_an_impl_that_already_speaks_the_shape_wins(self):
        v = extract_verification({"verification": {"status": "passed", "checks": [{"check": "x"}]}})
        self.assertEqual(v["checks"], [{"check": "x"}])

    def test_readback_helper_renders_the_envelope_shape(self):
        v = as_verification_dict({"verified": True, "success_raw": True, "contradiction": False})
        self.assertEqual(v["status"], "passed")
        self.assertEqual(v["checks"][0]["check"], "readback_verification")

    def test_readback_helper_keeps_a_contradiction_distinct(self):
        v = as_verification_dict({"verified": False, "success_raw": True, "contradiction": True})
        self.assertEqual(v["status"], "contradiction")


class Changes(unittest.TestCase):
    def test_an_undeclared_delta_is_absent_not_zero(self):
        # `{}` reads as "this operation changed nothing", which is a false
        # statement about an edit that simply never declared its deltas.
        self.assertIsNone(extract_changes({"success": True}))
        out = build_operation_envelope("timeline", "append", {}, {"success": True})
        self.assertNotIn("changes", envelope_of(out))

    def test_a_declared_delta_is_authoritative(self):
        changes = extract_changes({"_changes": {"items_added": 3, "items_deleted": 0}})
        self.assertEqual(changes["items_added"], 3)
        self.assertEqual(changes["items_deleted"], 0)

    def test_verified_aliases_are_mapped(self):
        changes = extract_changes({"inserted_clips": 2, "tail_items_shifted": 17})
        self.assertEqual(changes["items_added"], 2)
        self.assertEqual(changes["items_moved"], 17)

    def test_restored_properties_are_not_reported_as_an_edit(self):
        # A ripple insert re-applies properties to items it had to move. That is
        # bookkeeping, not a change the caller asked for.
        self.assertIsNone(extract_changes({"properties_restored_items": 9}))

    def test_a_versioning_metric_delta_is_carried(self):
        changes = extract_changes({"_versioning": {
            "metric": "duration_frames", "before_value": 100, "after_value": 148}})
        self.assertEqual(changes["delta"], 48.0)

    def test_a_non_numeric_metric_does_not_raise(self):
        changes = extract_changes({"_versioning": {
            "metric": "name", "before_value": "a", "after_value": "b"}})
        self.assertNotIn("delta", changes)

    def test_an_archived_predecessor_is_reported(self):
        changes = extract_changes({"_versioning": {"archived": True, "archived_version": "v3"}})
        self.assertTrue(changes["timeline_archived"])
        self.assertEqual(changes["archived_version"], "v3")


class Warnings(unittest.TestCase):
    def test_a_list_is_flattened_to_strings(self):
        self.assertEqual(extract_warnings({"warnings": ["a", "b"]}), ["a", "b"])

    def test_a_singular_warning_is_collected(self):
        self.assertEqual(extract_warnings({"warning": "careful"}), ["careful"])

    def test_duplicates_collapse(self):
        self.assertEqual(extract_warnings({"warnings": ["x"], "warning": "x"}), ["x"])

    def test_ignored_options_become_a_warning(self):
        self.assertIn("Ignored unsupported options", extract_warnings(
            {"ignored_options": ["foo"]})[0])

    def test_an_empty_payload_yields_none(self):
        self.assertEqual(extract_warnings({"success": True}), [])


class Passthrough(unittest.TestCase):
    def test_mcp_content_objects_are_returned_unchanged(self):
        class Image:  # matches FastMCP's Image by class name
            pass

        image = Image()
        self.assertIs(build_operation_envelope("t", "a", {}, image), image)

    def test_a_non_dict_return_is_not_boxed_in_dual_mode(self):
        # Callers of an action that returns a list have never seen a dict from
        # it; wrapping one would be the breaking change dual mode exists to
        # avoid.
        self.assertEqual(build_operation_envelope("t", "a", {}, [1, 2]), [1, 2])

    def test_a_non_dict_return_is_boxed_in_pure_mode(self):
        out = build_operation_envelope("t", "a", {"envelope": "pure"}, [1, 2])
        self.assertEqual(out["result"], [1, 2])


class EnvelopeContents(unittest.TestCase):
    def test_the_operation_names_tool_and_action(self):
        out = build_operation_envelope("timeline", "ripple_insert", {}, {"success": True})
        self.assertEqual(envelope_of(out)["operation"], "timeline.ripple_insert")

    def test_execution_ids_are_unique_per_call(self):
        a = envelope_of(build_operation_envelope("t", "a", {}, {"success": True}))
        b = envelope_of(build_operation_envelope("t", "a", {}, {"success": True}))
        self.assertNotEqual(a["execution_id"], b["execution_id"])

    def test_a_versioning_run_id_is_surfaced(self):
        out = build_operation_envelope(
            "timeline", "delete", {}, {"_versioning": {"analysis_run_id": "run-7"}})
        self.assertEqual(envelope_of(out)["run_id"], "run-7")

    def test_the_envelope_is_json_serializable(self):
        out = build_operation_envelope("timeline", "ripple_insert", {}, {
            "success": True, "inserted_clips": 1, "tail_items_shifted": 2,
            "readback": {"missing": []}, "warnings": ["w"]})
        json.loads(json.dumps(out))


class ServerIntegration(unittest.TestCase):
    """The envelope as it reaches a caller through the tool decorator."""

    def test_every_compound_tool_return_carries_the_envelope(self):
        import src.server as compound
        out = compound.setup("schema")
        self.assertIn(ENVELOPE_KEY, out)
        self.assertEqual(envelope_of(out)["operation"], "setup.schema")

    def test_a_missing_parameter_error_is_still_enveloped(self):
        import src.server as compound
        out = compound.timeline("get_item_list", {})
        self.assertIn(ENVELOPE_KEY, out)

    def test_async_tools_stay_coroutine_functions(self):
        # The guard decorator has broken this before, taking media_analysis's
        # 71 actions offline; the envelope rides in the same decorator.
        import inspect

        import src.server as compound
        self.assertTrue(inspect.iscoroutinefunction(compound.media_analysis))

    def test_the_envelope_key_stays_reserved(self):
        # The whole design rests on `_operation` never being a domain key. If a
        # tool starts returning one, dual mode begins destroying payloads the
        # way the flattened design did.
        import pathlib
        src = pathlib.Path(__file__).resolve().parents[1] / "src"
        offenders = [
            path.name for path in src.rglob("*.py")
            if f'"{ENVELOPE_KEY}":' in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [], f"{ENVELOPE_KEY} is in use as a domain key")


class PersistedDefault(unittest.TestCase):
    """A default the caller was told was saved has to survive a restart."""

    def setUp(self):
        import src.server as compound
        self.compound = compound
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "server-preferences.json")
        patcher = mock.patch.dict(os.environ, {"RESOLVE_MCP_SERVER_PREFS": self.path})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(opres.set_envelope_mode, opres.get_envelope_mode())

    def test_setting_it_writes_to_disk(self):
        self.compound.setup("set_defaults", {"result_envelope": "pure"})
        with open(self.path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["result_envelope"], "pure")

    def test_it_is_restored_on_startup(self):
        self.compound.setup("set_defaults", {"result_envelope": "pure"})
        opres.set_envelope_mode("dual")
        self.assertEqual(self.compound._apply_persisted_envelope_mode(), "pure")

    def test_an_explicit_env_override_outranks_the_saved_value(self):
        self.compound.setup("set_defaults", {"result_envelope": "pure"})
        opres.set_envelope_mode("dual")
        with mock.patch.dict(os.environ, {"RESOLVE_MCP_RESULT_ENVELOPE": "legacy"}):
            self.assertEqual(self.compound._apply_persisted_envelope_mode(), "dual")

    def test_a_dry_run_changes_nothing(self):
        self.compound.setup("set_defaults", {"result_envelope": "pure", "dry_run": True})
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual(opres.get_envelope_mode(), "dual")

    def test_an_invalid_mode_is_refused(self):
        out = self.compound.setup("set_defaults", {"result_envelope": "banana"})
        self.assertIn("error", out)
        self.assertEqual(opres.get_envelope_mode(), "dual")

    def test_it_appears_in_the_defaults_snapshot_and_schema(self):
        snapshot = self.compound.setup("get_defaults")
        self.assertEqual(snapshot["defaults"]["general"]["result_envelope"], "dual")
        schema = self.compound.setup("schema")
        self.assertIn("general.result_envelope", schema["defaults"])


if __name__ == "__main__":
    unittest.main()
