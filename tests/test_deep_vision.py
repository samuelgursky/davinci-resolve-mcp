"""Unit tests for src/utils/deep_vision.py (Phase B — deep shot-level vision).

No Resolve required. Covers the estimate→confirm→payload flow, token
validation, commit (rows + blob + lockstep export, human preservation),
caps refusal, the pending-vision sweep, and the deep-depth payload schema
injection + confirm gate in the analyze flow.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from src.utils import analysis_store, deep_vision, timeline_brain_db
from src.utils import media_analysis as ma

from tests.test_analysis_store import make_report


class DeepVisionBase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="deep-vision-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(timeline_brain_db.close_all)
        self.clip_dir_name = "sample-clip-mp4-abcdef123456"
        self.clip_dir = os.path.join(self.root, "clips", self.clip_dir_name)
        os.makedirs(os.path.join(self.clip_dir, "frames"), exist_ok=True)

    def _frame_file(self, name: str) -> str:
        path = os.path.join(self.clip_dir, "frames", name)
        with open(path, "wb") as handle:
            handle.write(b"\xff\xd8\xff\xdbfake-jpeg")
        return path

    def _report_with_frames(self):
        report = make_report()
        for kf in report["motion"]["analysis_keyframes"]:
            kf["frame_path"] = self._frame_file(f"sampled_{kf['index']:04d}.jpg")
        return report

    def _ingest(self, report=None):
        report = report or self._report_with_frames()
        with open(os.path.join(self.clip_dir, "analysis.json"), "w", encoding="utf-8") as handle:
            json.dump(report, handle)
        result = analysis_store.ingest_report(self.root, report, clip_dir=self.clip_dir)
        self.assertTrue(result["success"], result)
        return result["clip_uuid"], report


class DeepenFlowTests(DeepVisionBase):
    def test_estimate_first_then_payload(self) -> None:
        clip_uuid, _ = self._ingest()
        first = deep_vision.deepen_clip(self.root, clip_ref=self.clip_dir_name)
        self.assertTrue(first["success"])
        self.assertEqual(first["status"], "confirmation_required")
        self.assertGreater(first["estimate"]["estimated_vision_tokens"], 0)
        token = first["confirm_token"]

        second = deep_vision.deepen_clip(
            self.root, clip_ref=self.clip_dir_name, confirm_token=token
        )
        self.assertTrue(second["success"], second)
        self.assertEqual(second["status"], "pending_host_analysis")
        self.assertEqual(second["mode"], "deep_shots")
        self.assertEqual(len(second["shot_table"]), 3)
        self.assertIn("deep_shot_schema", second)
        self.assertIn("visual", second["deep_shot_schema"])
        self.assertEqual(second["commit_action"]["action"], "commit_shot_vision")
        self.assertTrue(second["frame_paths"])
        for entry in second["shot_table"]:
            self.assertTrue(entry["frame_indices"], f"shot {entry['shot_index']} has no frames")

    def test_shot_selection_and_missing_index(self) -> None:
        self._ingest()
        result = deep_vision.deepen_clip(
            self.root, clip_ref=self.clip_dir_name, shot_indices=[2]
        )
        self.assertEqual(result["estimate"]["shot_count"], 1)
        bad = deep_vision.deepen_clip(
            self.root, clip_ref=self.clip_dir_name, shot_indices=[9]
        )
        self.assertFalse(bad["success"])
        self.assertIn("9", bad["error"])

    def test_caps_refusal_blocks_payload(self) -> None:
        self._ingest()
        refusal = {"success": False, "error": "over_day_cap", "caps_refusal": True}
        with mock.patch.object(ma, "_check_caps_pre_call", return_value=refusal):
            result = deep_vision.deepen_clip(self.root, clip_ref=self.clip_dir_name)
        self.assertEqual(result, refusal)

    def test_unknown_clip_suggests_db_ingest(self) -> None:
        result = deep_vision.deepen_clip(self.root, clip_ref="missing-clip")
        self.assertFalse(result["success"])
        self.assertIn("db_ingest", result["error"])

    def test_pre_v9_report_auto_ingests(self) -> None:
        report = self._report_with_frames()
        with open(os.path.join(self.clip_dir, "analysis.json"), "w", encoding="utf-8") as handle:
            json.dump(report, handle)
        # No analysis_store.ingest_report — deepen should ingest on demand.
        result = deep_vision.deepen_clip(self.root, clip_ref=self.clip_dir_name)
        self.assertTrue(result["success"], result)
        self.assertEqual(result["status"], "confirmation_required")


def deep_entry(shot_index: int, description: str = "") -> dict:
    return {
        "shot_index": shot_index,
        "visual": {"shot_size": "medium", "framing": "single", "lighting": "natural"},
        "content": {"action": "Subject talks to camera.", "audio_character": "sync_dialogue"},
        "production": {"composite_shot": False, "vfx_present": "none"},
        "editorial": {"editorial_role": "coverage", "select_potential": "high",
                      "best_moment_present": False, "best_moment": None, "pacing": "moderate"},
        "cuttability": {"cut_in": {"quality": "clean", "notes": ""},
                        "cut_out": {"quality": "ok", "notes": "tail trails off"},
                        "match_action_in": False, "match_action_out": False,
                        "cut_compatibility_hints": "cuts well to interiors"},
        "confidence": {"visual": "high", "content": "medium", "audio": "low",
                       "editorial": "medium", "cuttability": "medium"},
        **({"description": description} if description else {}),
    }


class CommitShotVisionTests(DeepVisionBase):
    def test_commit_writes_rows_blob_and_export(self) -> None:
        clip_uuid, _ = self._ingest()
        shots_payload = [deep_entry(2, "Deep: tight medium with direct address.")]
        token = deep_vision._vision_token_for(
            clip_uuid,
            [analysis_store.shot_uuid_for(clip_uuid, 5.2, 13.9)],
        )
        result = deep_vision.commit_shot_vision(
            self.root, shots=shots_payload, vision_token=token, clip_ref=self.clip_dir_name
        )
        self.assertTrue(result["success"], result)
        self.assertEqual(result["shots_updated"], 1)
        self.assertEqual(result["source"], "vision_deep_v1")

        # Rows: deep fields landed with the deep source label.
        conn = timeline_brain_db.connect(self.root)
        row = conn.execute(
            """
            SELECT value_json, source FROM subjective_fields
            WHERE field_path = 'editorial.select_potential' AND superseded_at IS NULL
            """
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(json.loads(row["value_json"]), "high")
        self.assertEqual(row["source"], "vision_deep_v1")

        # Blob + lockstep export carry the groups.
        exported = analysis_store.export_report(self.root, clip_uuid)
        shot2 = exported["visual"]["shot_descriptions"][1]
        self.assertEqual(shot2["editorial"]["select_potential"], "high")
        self.assertEqual(shot2["description"], "Deep: tight medium with direct address.")
        with open(os.path.join(self.clip_dir, "analysis.json"), "r", encoding="utf-8") as handle:
            on_disk = json.load(handle)
        self.assertEqual(
            on_disk["visual"]["shot_descriptions"][1]["editorial"]["select_potential"], "high"
        )

    def test_commit_token_mismatch_rejected(self) -> None:
        self._ingest()
        result = deep_vision.commit_shot_vision(
            self.root, shots=[deep_entry(2)], vision_token="bogus", clip_ref=self.clip_dir_name
        )
        self.assertFalse(result["success"])
        self.assertIn("vision_token mismatch", result["error"])

    def test_commit_preserves_human_correction(self) -> None:
        clip_uuid, _ = self._ingest()
        analysis_store.record_human_correction(
            self.root, clip_ref=clip_uuid, entity_type="shot", entity_uuid=2,
            field_path="editorial.select_potential", value="low",
            author="sam", reason="editor disagrees",
        )
        token = deep_vision._vision_token_for(
            clip_uuid, [analysis_store.shot_uuid_for(clip_uuid, 5.2, 13.9)]
        )
        result = deep_vision.commit_shot_vision(
            self.root, shots=[deep_entry(2)], vision_token=token, clip_ref=self.clip_dir_name
        )
        self.assertTrue(result["success"], result)
        self.assertGreaterEqual(result["subjective_fields_preserved_human"], 1)
        exported = analysis_store.export_report(self.root, clip_uuid)
        self.assertEqual(
            exported["visual"]["shot_descriptions"][1]["editorial"]["select_potential"], "low"
        )

    def test_commit_records_caps_usage(self) -> None:
        clip_uuid, _ = self._ingest()
        token = deep_vision._vision_token_for(
            clip_uuid, [analysis_store.shot_uuid_for(clip_uuid, 5.2, 13.9)]
        )
        with mock.patch.object(ma, "_record_caps_usage") as record:
            deep_vision.commit_shot_vision(
                self.root, shots=[deep_entry(2)], vision_token=token,
                clip_ref=self.clip_dir_name,
            )
        record.assert_called_once()
        self.assertGreater(record.call_args.kwargs["vision_tokens"], 0)


class VisionPendingSweepTests(DeepVisionBase):
    def _pending_report(self):
        report = self._report_with_frames()
        report["vision_status"] = "pending_host_analysis"
        report["vision_token"] = "tok123"
        report["analyzed_at"] = "2026-05-26T00:00:00Z"
        report["visual"] = {
            "status": "pending_host_analysis",
            "vision_token": "tok123",
            "frame_paths": [kf["frame_path"] for kf in report["motion"]["analysis_keyframes"]],
            "prompt": "analyze",
            "commit_action": {"tool": "media_analysis", "action": "commit_vision"},
        }
        return report

    def test_sweep_lists_pending(self) -> None:
        self._ingest(self._pending_report())
        result = deep_vision.vision_pending_sweep(self.root)
        self.assertTrue(result["success"])
        self.assertEqual(result["pending_count"], 1)
        row = result["pending"][0]
        self.assertTrue(row["reofferable"])
        self.assertGreater(row["age_days"], 1)

    def test_sweep_reoffer_returns_stored_payload(self) -> None:
        self._ingest(self._pending_report())
        result = deep_vision.vision_pending_sweep(self.root, reoffer=True)
        self.assertEqual(len(result["reoffers"]), 1)
        payload = result["reoffers"][0]["payload"]
        self.assertEqual(payload["status"], "pending_host_analysis")
        self.assertTrue(payload["frame_paths"])

    def test_sweep_expire_stamps_report(self) -> None:
        clip_uuid, _ = self._ingest(self._pending_report())
        result = deep_vision.vision_pending_sweep(self.root, expire=True)
        self.assertEqual(result["expired"], [self.clip_dir_name])
        exported = analysis_store.export_report(self.root, clip_uuid)
        self.assertEqual(exported["vision_status"], "expired_host_analysis")
        with open(os.path.join(self.clip_dir, "analysis.json"), "r", encoding="utf-8") as handle:
            on_disk = json.load(handle)
        self.assertEqual(on_disk["vision_status"], "expired_host_analysis")
        # A second sweep finds nothing pending.
        again = deep_vision.vision_pending_sweep(self.root)
        self.assertEqual(again["pending_count"], 0)

    def test_sweep_expire_respects_max_age(self) -> None:
        self._ingest(self._pending_report())
        result = deep_vision.vision_pending_sweep(self.root, expire=True, max_age_days=10000)
        self.assertEqual(result["expired"], [])
        self.assertEqual(result["pending_count"], 1)


class DeepDepthAnalyzeFlowTests(DeepVisionBase):
    def test_payload_includes_deep_schema_for_deep_depth(self) -> None:
        report = self._report_with_frames()
        record = dict(report["clip"])
        motion = dict(report["motion"])
        motion["cut_analysis"] = {
            "shot_ranges": [
                {"index": 1, "start": 0.0, "end": 5.2},
                {"index": 2, "start": 5.2, "end": 13.9},
                {"index": 3, "start": 13.9, "end": 20.0},
            ]
        }
        artifacts = {"clip_dir": self.clip_dir}
        options = {"vision": {"enabled": True, "provider": "host_chat_paths"}, "depth": "deep"}
        payload = ma.build_host_chat_paths_payload(record, motion, options, artifacts)
        self.assertEqual(payload["status"], "pending_host_analysis")
        self.assertIn("deep_shot_schema", payload)
        self.assertIn("DEEP PASS", payload["instructions"])

        options_std = {"vision": {"enabled": True, "provider": "host_chat_paths"}, "depth": "standard"}
        payload_std = ma.build_host_chat_paths_payload(record, motion, options_std, artifacts)
        self.assertNotIn("deep_shot_schema", payload_std)

    def test_execute_plan_deep_requires_confirmation(self) -> None:
        plan = {
            "success": True,
            "depth": "deep",
            "output_root": {"project_root": self.root},
            "clips": [
                {
                    "record": {"clip_name": "a.mp4", "file_path": "/nonexistent/a.mp4"},
                    "artifacts": {"analysis_json": os.path.join(self.clip_dir, "analysis.json")},
                    "analysis_keyframe_budget": 24,
                }
            ],
        }
        params = {"vision": {"enabled": True, "provider": "host_chat_paths"}}
        result = asyncio.run(ma.execute_plan_async(plan, params=params))
        self.assertEqual(result["status"], "confirmation_required")
        self.assertEqual(result["reason"], "deep_depth_cost_estimate")
        self.assertEqual(result["estimate"]["estimated_frames"], 24)
        # confirm_deep proceeds past the gate (and then fails on the missing file,
        # which proves the gate no longer blocks).
        params["confirm_deep"] = True
        result = asyncio.run(ma.execute_plan_async(plan, params=params))
        self.assertNotEqual(result.get("status"), "confirmation_required")


if __name__ == "__main__":
    unittest.main()
