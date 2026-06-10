"""Governance enforce mode + instance-level actor identity (Phase 3)."""
from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest import mock

import src.server as compound
from src.utils import actor_identity, resolve_ai_ledger, timeline_brain_db


class ActorIdentityTest(unittest.TestCase):
    def tearDown(self):
        actor_identity.set_instance("stdio")

    def test_default_instance_is_stdio(self):
        actor_identity.set_instance("stdio")
        self.assertEqual(actor_identity.current_actor()["instance"], "stdio")
        self.assertEqual(actor_identity.actor_string(), f"stdio:{os.getpid()}")

    def test_set_instance_changes_actor_string(self):
        actor_identity.set_instance("batch-cli")
        self.assertTrue(actor_identity.actor_string().startswith("batch-cli:"))

    def test_blank_instance_falls_back_to_stdio(self):
        actor_identity.set_instance("")
        self.assertEqual(actor_identity.get_instance(), "stdio")


class SchemaV8ActorColumnsTest(unittest.TestCase):
    def test_fresh_db_has_actor_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            try:
                conn = timeline_brain_db.connect(tmp)
                for table in ("resolve_ai_op_usage", "brain_edits", "timeline_versions"):
                    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                    self.assertIn("actor", cols, f"{table} missing actor column")
            finally:
                timeline_brain_db.close_all()

    def test_ledger_rows_carry_actor(self):
        with tempfile.TemporaryDirectory() as tmp:
            try:
                actor_identity.set_instance("batch-cli")
                row_id = resolve_ai_ledger.record_op(
                    project_root=tmp, op="remove_motion_blur", success=True,
                    wall_clock_ms=1200, output_bytes=2048, session_id="s1",
                )
                self.assertIsNotNone(row_id)
                rows = resolve_ai_ledger.get_usage(project_root=tmp)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["actor"], f"batch-cli:{os.getpid()}")
            finally:
                actor_identity.set_instance("stdio")
                timeline_brain_db.close_all()

    def test_record_op_explicit_actor_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            try:
                resolve_ai_ledger.record_op(
                    project_root=tmp, op="generate_speech", success=True, actor="control-panel:42",
                )
                rows = resolve_ai_ledger.get_usage(project_root=tmp)
                self.assertEqual(rows[0]["actor"], "control-panel:42")
            finally:
                timeline_brain_db.close_all()


class GovernanceEnforceGateTest(unittest.TestCase):
    EXCEEDED = {
        "applies": True, "exceeded": True, "near": True, "tier": "strict",
        "thresholds": {"deblur_runs": 5}, "usage": {"deblur_runs": 5},
        "projected": {"deblur_runs": 6},
        "warnings": ["Runs this session: 6 exceeds the strict limit of 5."],
    }

    def test_advisory_mode_never_blocks(self):
        with mock.patch.object(compound, "_ai_governance_mode", return_value="advisory"), \
             mock.patch.object(compound, "_ai_governance_check", return_value=self.EXCEEDED):
            self.assertIsNone(compound._ai_governance_gate("remove_motion_blur", {}))

    def test_enforce_mode_blocks_when_exceeded(self):
        with mock.patch.object(compound, "_ai_governance_mode", return_value="enforce"), \
             mock.patch.object(compound, "_ai_governance_check", return_value=self.EXCEEDED):
            out = compound._ai_governance_gate("remove_motion_blur", {})
        self.assertIsNotNone(out)
        envelope = out["error"]
        self.assertEqual(envelope["code"], "GOVERNANCE_BLOCKED")
        self.assertEqual(envelope["category"], "destructive_blocked")
        self.assertFalse(envelope["retryable"])
        self.assertEqual(envelope["state"]["tier"], "strict")
        self.assertEqual(envelope["state"]["mode"], "enforce")

    def test_enforce_mode_allows_within_tier(self):
        ok = dict(self.EXCEEDED, exceeded=False, warnings=[])
        with mock.patch.object(compound, "_ai_governance_mode", return_value="enforce"), \
             mock.patch.object(compound, "_ai_governance_check", return_value=ok):
            self.assertIsNone(compound._ai_governance_gate("generate_speech", {}))

    def test_override_governance_bypasses_enforce(self):
        with mock.patch.object(compound, "_ai_governance_mode", return_value="enforce"), \
             mock.patch.object(compound, "_ai_governance_check", return_value=self.EXCEEDED):
            self.assertIsNone(
                compound._ai_governance_gate("remove_motion_blur", {"override_governance": True})
            )

    def test_non_governed_op_never_blocks(self):
        not_applicable = {"applies": False, "exceeded": False}
        with mock.patch.object(compound, "_ai_governance_mode", return_value="enforce"), \
             mock.patch.object(compound, "_ai_governance_check", return_value=not_applicable):
            self.assertIsNone(compound._ai_governance_gate("perform_audio_classification", {}))


class GovernanceModePreferenceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._pref_path = os.path.join(self._tmp.name, "logs", "media-analysis-preferences.json")
        self._orig = compound._media_analysis_preferences_path
        compound._media_analysis_preferences_path = lambda: self._pref_path

    def tearDown(self):
        compound._media_analysis_preferences_path = self._orig
        self._tmp.cleanup()

    def test_mode_defaults_to_advisory(self):
        self.assertEqual(compound._ai_governance_mode(), "advisory")

    def test_set_ai_governance_mode_round_trip(self):
        out = asyncio.run(compound.media_analysis("set_ai_governance", {"mode": "enforce"}))
        self.assertTrue(out["success"])
        self.assertEqual(out["mode"], "enforce")
        self.assertEqual(compound._ai_governance_mode(), "enforce")

    def test_set_ai_governance_rejects_unknown_mode(self):
        out = asyncio.run(compound.media_analysis("set_ai_governance", {"mode": "yolo"}))
        self.assertIn("unknown mode", out["error"]["message"])

    def test_set_ai_governance_requires_some_field(self):
        out = asyncio.run(compound.media_analysis("set_ai_governance", {}))
        self.assertIn("requires at least one", out["error"]["message"])

    def test_set_preset_and_mode_together(self):
        out = asyncio.run(compound.media_analysis("set_ai_governance", {"preset": "strict", "mode": "enforce"}))
        self.assertEqual(out["tier"], "strict")
        self.assertEqual(out["mode"], "enforce")

    def test_invalid_stored_mode_falls_back_to_advisory(self):
        compound._write_media_analysis_preferences({"resolve_ai_governance_mode": "bogus"})
        self.assertEqual(compound._ai_governance_mode(), "advisory")


if __name__ == "__main__":
    unittest.main()
