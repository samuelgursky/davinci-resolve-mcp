"""Unit tests for src/utils/analysis_store.py (C1 — DB-canonical clip analysis).

No Resolve required. Includes the Phase A round-trip guard: ingest → export
must reproduce the report exactly (the export overlay only ever applies human
rows). When a real sample analysis root is present on disk, its reports are
round-tripped too (read-only: the DB used is always a temp directory).
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
import unittest

from src.utils import analysis_store, timeline_brain_db

# A real analyzed sample root (issue references: 20260517 sample). The test
# only READS its analysis.json files; rows are written to a temp DB.
REAL_SAMPLE_ROOT = os.path.expanduser(
    "~/Documents/davinci-resolve-mcp-analysis/20260517_sample-fc314309e4"
)


def make_report(**overrides):
    """A small but structurally faithful analysis report."""
    report = {
        "success": True,
        "analysis_version": "0.2",
        "analysis_signature": {"signature_hash": "abc123def456"},
        "analysis_profile": {"depth": "standard", "vision_enabled": True},
        "analyzed_at": "2026-06-10T00:00:00Z",
        "source_file": "/media/sample clip.mp4",
        "clip": {
            "clip_id": "11111111-2222-3333-4444-555555555555",
            "clip_name": "Sample Clip.mp4",
            "media_id": "aaaa-bbbb",
            "file_path": "/media/sample clip.mp4",
            "bin_path": "Master/Bin 1",
            "fps": 24.0,
            "resolution": "1920x1080",
            "media_type": "Video + Audio",
        },
        "summary": "Sample Clip.mp4, 20.0s, medium motion",
        "technical_warnings": [],
        "technical": {"format": {"duration_seconds": 20.0}},
        "cut_analysis": {"cut_count": 2, "duration_seconds": 20.0},
        "motion": {
            "overall_motion_level": "medium",
            "analysis_keyframes": [
                {"index": 1, "time_seconds": 0.5, "selection_reason": "shot_start", "motion_peak": False},
                {"index": 2, "time_seconds": 6.0, "selection_reason": "shot_representative", "motion_peak": True},
                {"index": 3, "time_seconds": 14.0, "selection_reason": "shot_start", "motion_peak": False},
            ],
        },
        "transcription": {
            "success": True,
            "segments": [
                {"start": 0.0, "end": 4.0, "text": "hello there"},
                {"start": 4.0, "end": 9.5, "text": "general kenobi"},
            ],
        },
        "visual": {
            "success": True,
            "clip_summary": "A sample clip with two cuts.",
            "clip_summary_oneliner": "Sample clip.",
            "editorial_classification": {"primary_use": "b_roll", "select_potential": "medium"},
            "content": {"locations": ["interior"], "actions": ["talking"]},
            "shot_and_style": {"shot_sizes": ["medium"], "camera_motion": ["static"]},
            "slate": {"slate_visible": False},
            "editing_notes": {"best_moments": [], "search_tags": ["sample", "talking"]},
            "shot_descriptions": [
                {
                    "shot_index": 1,
                    "time_seconds_start": 0.0,
                    "time_seconds_end": 5.2,
                    "frame_indices_used": [1],
                    "description": "Opening wide shot.",
                    "qc_flags": [],
                },
                {
                    "shot_index": 2,
                    "time_seconds_start": 5.2,
                    "time_seconds_end": 13.9,
                    "frame_indices_used": [2],
                    "description": "Medium shot, subject talks.",
                    "qc_flags": ["soft_focus"],
                },
                {
                    "shot_index": 3,
                    "time_seconds_start": 13.9,
                    "time_seconds_end": 20.0,
                    "frame_indices_used": [3],
                    "description": "Closing shot.",
                    "qc_flags": [],
                },
            ],
            "qc": {
                "warnings": ["No slate is visible."],
                "continuity_observations": [
                    {
                        "kind": "screen_direction",
                        "shot_indices": [1, 2],
                        "observation": "Direction flips between shots 1 and 2.",
                        "confidence": "medium",
                    }
                ],
                "coverage_gaps": ["No close-up coverage."],
            },
        },
        "analysis_keyframes": [],
        "clip_analysis_markers": {"marker_count": 0, "duration_seconds": 20.0},
    }
    report.update(overrides)
    return report


class AnalysisStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="analysis-store-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(timeline_brain_db.close_all)

    # ── schema ──────────────────────────────────────────────────────────────

    def test_v9_tables_exist(self) -> None:
        conn = timeline_brain_db.connect(self.root)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for table in (
            "clips",
            "clip_aliases",
            "analysis_reports",
            "shots",
            "subjective_fields",
            "field_changelog",
            "transcript_segments",
            "frames",
            "qc_observations",
        ):
            self.assertIn(table, tables)
        self.assertGreaterEqual(timeline_brain_db._read_schema_version(conn), 9)

    # ── round-trip guard ────────────────────────────────────────────────────

    def test_ingest_export_round_trip_exact(self) -> None:
        report = make_report()
        original = json.loads(json.dumps(report, sort_keys=True, default=str))
        result = analysis_store.ingest_report(self.root, report, clip_dir="sample-clip-mp4-abcdef123456")
        self.assertTrue(result["success"], result)
        exported = analysis_store.export_report(self.root, result["clip_uuid"])
        self.assertEqual(original, exported)

    def test_round_trip_real_sample_root(self) -> None:
        clips_root = os.path.join(REAL_SAMPLE_ROOT, "clips")
        if not os.path.isdir(clips_root):
            self.skipTest("real sample root not present on this machine")
        round_tripped = 0
        for entry in sorted(os.listdir(clips_root)):
            report_path = os.path.join(clips_root, entry, "analysis.json")
            if not os.path.isfile(report_path):
                continue
            with open(report_path, "r", encoding="utf-8") as handle:
                report = json.load(handle)
            original = json.loads(json.dumps(report, sort_keys=True, default=str))
            result = analysis_store.ingest_report(self.root, report, clip_dir=entry)
            self.assertTrue(result["success"], result)
            exported = analysis_store.export_report(self.root, result["clip_uuid"])
            self.assertEqual(original, exported, f"round-trip drift for {entry}")
            round_tripped += 1
        self.assertGreater(round_tripped, 0)

    def test_reingest_is_idempotent(self) -> None:
        report = make_report()
        first = analysis_store.ingest_report(self.root, report)
        second = analysis_store.ingest_report(self.root, copy.deepcopy(report))
        self.assertEqual(first["clip_uuid"], second["clip_uuid"])
        # Second pass writes no new subjective rows (values unchanged).
        self.assertEqual(second["subjective_fields_written"], 0)
        conn = timeline_brain_db.connect(self.root)
        n = conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0]
        self.assertEqual(n, 1)

    # ── identity / lookup ───────────────────────────────────────────────────

    def test_resolve_clip_uuid_by_any_alias(self) -> None:
        report = make_report()
        result = analysis_store.ingest_report(self.root, report, clip_dir="sample-clip-mp4-abcdef123456")
        clip_uuid = result["clip_uuid"]
        conn = timeline_brain_db.connect(self.root)
        for ref in (
            clip_uuid,
            report["clip"]["clip_id"],
            report["clip"]["media_id"],
            report["clip"]["file_path"],
            "sample-clip-mp4-abcdef123456",
        ):
            self.assertEqual(
                analysis_store.resolve_clip_uuid(conn, ref), clip_uuid, f"failed for {ref!r}"
            )
        self.assertIsNone(analysis_store.resolve_clip_uuid(conn, "nope"))

    def test_shot_uuid_stable_under_boundary_jitter(self) -> None:
        a = analysis_store.shot_uuid_for("deadbeef0123", 5.2, 13.9)
        b = analysis_store.shot_uuid_for("deadbeef0123", 5.4, 14.1)
        self.assertEqual(a, b)
        c = analysis_store.shot_uuid_for("deadbeef0123", 5.2, 18.0)
        self.assertNotEqual(a, c)

    # ── corrections ─────────────────────────────────────────────────────────

    def test_human_correction_survives_reingest(self) -> None:
        report = make_report()
        result = analysis_store.ingest_report(self.root, report)
        clip_uuid = result["clip_uuid"]
        corr = analysis_store.record_human_correction(
            self.root,
            clip_ref=clip_uuid,
            entity_type="shot",
            entity_uuid=2,  # shot_index
            field_path="description",
            value="Corrected: tight medium, two cuts late.",
            author="sam@bradfordoperations.com",
            reason="fix machine description",
        )
        self.assertTrue(corr["success"], corr)
        exported = analysis_store.export_report(self.root, clip_uuid)
        self.assertEqual(
            exported["visual"]["shot_descriptions"][1]["description"],
            "Corrected: tight medium, two cuts late.",
        )
        # Machine re-ingest must not clobber the human row.
        reingest = analysis_store.ingest_report(self.root, make_report())
        self.assertGreaterEqual(reingest["subjective_fields_preserved_human"], 1)
        exported = analysis_store.export_report(self.root, clip_uuid)
        self.assertEqual(
            exported["visual"]["shot_descriptions"][1]["description"],
            "Corrected: tight medium, two cuts late.",
        )
        # Changelog recorded the correction.
        conn = timeline_brain_db.connect(self.root)
        rows = conn.execute(
            "SELECT * FROM field_changelog WHERE new_source='human'"
        ).fetchall()
        self.assertEqual(len(rows), 1)

    def test_clip_level_correction_and_clear(self) -> None:
        report = make_report()
        result = analysis_store.ingest_report(self.root, report)
        clip_uuid = result["clip_uuid"]
        analysis_store.record_human_correction(
            self.root,
            clip_ref=report["clip"]["clip_id"],
            entity_type="clip",
            entity_uuid=clip_uuid,
            field_path="editorial_classification.select_potential",
            value="high",
            author="sam",
        )
        exported = analysis_store.export_report(self.root, clip_uuid)
        self.assertEqual(
            exported["visual"]["editorial_classification"]["select_potential"], "high"
        )
        cleared = analysis_store.clear_human_field(
            self.root,
            clip_ref=clip_uuid,
            entity_type="clip",
            entity_uuid=clip_uuid,
            field_path="editorial_classification.select_potential",
            author="sam",
        )
        self.assertTrue(cleared["success"])
        self.assertEqual(cleared["cleared"], 1)
        exported = analysis_store.export_report(self.root, clip_uuid)
        self.assertEqual(
            exported["visual"]["editorial_classification"]["select_potential"], "medium"
        )

    # ── project ingest (migration path) ─────────────────────────────────────

    def test_ingest_project_with_corrections_sidecar(self) -> None:
        clip_dir = os.path.join(self.root, "clips", "sample-clip-mp4-abcdef123456")
        os.makedirs(clip_dir)
        report = make_report()
        with open(os.path.join(clip_dir, "analysis.json"), "w", encoding="utf-8") as handle:
            json.dump(report, handle)
        corrections = {
            "schema_version": "2.0",
            "clip_id": report["clip"]["clip_id"],
            "current": {
                "shot:2:description": {
                    "value": "Human-corrected description.",
                    "source": "human",
                    "author": "sam",
                    "timestamp": "2026-06-01T00:00:00Z",
                }
            },
            "changelog": [],
        }
        with open(os.path.join(clip_dir, "corrections.json"), "w", encoding="utf-8") as handle:
            json.dump(corrections, handle)

        result = analysis_store.ingest_project(self.root)
        self.assertTrue(result["success"], result)
        self.assertEqual(result["ingested_count"], 1)
        self.assertEqual(result["corrections_imported"], 1)
        clip_uuid = result["ingested"][0]["clip_uuid"]
        exported = analysis_store.export_report(self.root, clip_uuid)
        self.assertEqual(
            exported["visual"]["shot_descriptions"][1]["description"],
            "Human-corrected description.",
        )

    # ── readers / status ────────────────────────────────────────────────────

    def test_load_db_report_fallback_contract(self) -> None:
        self.assertIsNone(
            analysis_store.load_db_report(self.root, clip_dir="missing-aaaaaaaaaaaa")
        )
        report = make_report()
        analysis_store.ingest_report(self.root, report, clip_dir="sample-clip-mp4-abcdef123456")
        loaded = analysis_store.load_db_report(self.root, clip_dir="sample-clip-mp4-abcdef123456")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["clip"]["clip_name"], "Sample Clip.mp4")

    def test_db_status_counts(self) -> None:
        analysis_store.ingest_report(self.root, make_report())
        status = analysis_store.db_status(self.root)
        self.assertTrue(status["success"])
        self.assertTrue(status["canonical"])
        self.assertEqual(status["counts"]["clips"], 1)
        self.assertEqual(status["counts"]["shots"], 3)
        self.assertEqual(status["counts"]["transcript_segments"], 2)
        self.assertEqual(status["counts"]["frames"], 3)
        self.assertGreaterEqual(status["counts"]["qc_observations"], 3)

    def test_normalized_rows_match_report(self) -> None:
        report = make_report()
        result = analysis_store.ingest_report(self.root, report)
        conn = timeline_brain_db.connect(self.root)
        clip = conn.execute("SELECT * FROM clips").fetchone()
        self.assertEqual(clip["clip_name"], "Sample Clip.mp4")
        self.assertEqual(clip["overall_motion_level"], "medium")
        self.assertEqual(clip["cut_count"], 2)
        self.assertEqual(clip["shot_count"], 3)
        self.assertEqual(clip["duration_seconds"], 20.0)
        shots = conn.execute(
            "SELECT * FROM shots ORDER BY shot_index"
        ).fetchall()
        self.assertEqual([s["shot_index"] for s in shots], [1, 2, 3])
        self.assertEqual(shots[1]["description"], "Medium shot, subject talks.")
        # Frame→shot mapping derived from frame_indices_used.
        frame = conn.execute(
            "SELECT shot_uuid FROM frames WHERE frame_index=2"
        ).fetchone()
        self.assertEqual(frame["shot_uuid"], shots[1]["shot_uuid"])


if __name__ == "__main__":
    unittest.main()
