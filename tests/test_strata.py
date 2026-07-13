"""Unit tests for the perception strata (schema v13 + src/utils/strata.py).

No Resolve required. Covers: the v13 migration, word-row ingest (segment
words + top-level fallback), blob backfill, machine-replace vs human-preserve
event semantics, float32 curve round-trip (incl. NaN gaps), and status.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
import unittest

from src.utils import analysis_store, strata, timeline_brain_db
from tests.test_analysis_store import make_report

REAL_SAMPLE_ROOT = os.path.expanduser(
    "~/Documents/davinci-resolve-mcp-analysis/20260517_sample-fc314309e4"
)


def make_word(word: str, start: float, end: float, probability: float = 0.9):
    return {"word": word, "start": start, "end": end, "probability": probability}


def make_report_with_words(**overrides):
    report = make_report(**overrides)
    report["transcription"] = {
        "success": True,
        "segments": [
            {
                "start": 0.0,
                "end": 4.0,
                "text": "hello there",
                "words": [make_word("hello", 0.2, 0.6), make_word("there", 0.7, 1.1)],
            },
            {
                "start": 4.0,
                "end": 9.5,
                "text": "general kenobi",
                "words": [make_word("general", 4.1, 4.6), make_word("kenobi", 4.8, 5.4, 0.75)],
            },
        ],
    }
    return report


class StrataSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="strata-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(timeline_brain_db.close_all)

    def test_v13_tables_exist(self) -> None:
        conn = timeline_brain_db.connect(self.root)
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        for table in ("events", "curves", "transcript_words", "story_beats"):
            self.assertIn(table, tables)
        self.assertGreaterEqual(timeline_brain_db._read_schema_version(conn), 13)

    def test_v12_db_migrates_clean(self) -> None:
        # Simulate a pre-v13 DB: create schema, force version back to 12,
        # drop the v13 tables, reopen — migration must recreate them.
        conn = timeline_brain_db.connect(self.root)
        for table in ("events", "curves", "transcript_words", "story_beats"):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        timeline_brain_db._write_schema_version(conn, 12)
        conn.commit()
        timeline_brain_db.close_all()
        conn = timeline_brain_db.connect(self.root)
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        for table in ("events", "curves", "transcript_words", "story_beats"):
            self.assertIn(table, tables)
        self.assertEqual(timeline_brain_db._read_schema_version(conn), timeline_brain_db.SCHEMA_VERSION)


class TranscriptWordsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="strata-words-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(timeline_brain_db.close_all)

    def _ingest(self, report):
        result = analysis_store.ingest_report(self.root, report, clip_dir="clip-abcdef123456")
        self.assertTrue(result["success"], result)
        return result

    def test_ingest_writes_word_rows(self) -> None:
        result = self._ingest(make_report_with_words())
        self.assertEqual(result["transcript_words_written"], 4)
        conn = timeline_brain_db.connect(self.root)
        words = strata.read_words(conn, result["clip_uuid"])
        self.assertEqual([w["word"] for w in words], ["hello", "there", "general", "kenobi"])
        self.assertEqual(words[0]["start_seconds"], 0.2)
        self.assertEqual(words[3]["confidence"], 0.75)

    def test_word_search_and_window(self) -> None:
        result = self._ingest(make_report_with_words())
        conn = timeline_brain_db.connect(self.root)
        hits = strata.read_words(conn, result["clip_uuid"], match="kenobi")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["start_seconds"], 4.8)
        windowed = strata.read_words(conn, result["clip_uuid"], start_seconds=0.0, end_seconds=1.0)
        self.assertEqual([w["word"] for w in windowed], ["hello", "there"])

    def test_reingest_words_idempotent(self) -> None:
        report = make_report_with_words()
        first = self._ingest(report)
        second = self._ingest(json.loads(json.dumps(report)))
        self.assertEqual(first["clip_uuid"], second["clip_uuid"])
        conn = timeline_brain_db.connect(self.root)
        self.assertEqual(len(strata.read_words(conn, first["clip_uuid"])), 4)

    def test_top_level_words_fallback_buckets_by_segment(self) -> None:
        report = make_report()
        report["transcription"] = {
            "success": True,
            "segments": [
                {"start": 0.0, "end": 4.0, "text": "hello there"},
                {"start": 4.0, "end": 9.5, "text": "general kenobi"},
            ],
            "words": [
                make_word("hello", 0.2, 0.6),
                make_word("there", 0.7, 1.1),
                make_word("general", 4.1, 4.6),
                make_word("kenobi", 4.8, 5.4),
            ],
        }
        result = self._ingest(report)
        self.assertEqual(result["transcript_words_written"], 4)
        conn = timeline_brain_db.connect(self.root)
        words = strata.read_words(conn, result["clip_uuid"])
        self.assertEqual([w["segment_index"] for w in words], [0, 0, 1, 1])

    def test_report_without_words_writes_nothing(self) -> None:
        result = self._ingest(make_report())
        self.assertEqual(result["transcript_words_written"], 0)

    def test_ingest_export_round_trip_still_exact(self) -> None:
        # Word rows are derived data; the canonical blob must be untouched.
        report = make_report_with_words()
        original = json.loads(json.dumps(report, sort_keys=True, default=str))
        result = self._ingest(report)
        exported = analysis_store.export_report(self.root, result["clip_uuid"])
        self.assertEqual(original, exported)

    def test_backfill_from_report_blobs(self) -> None:
        result = self._ingest(make_report_with_words())
        conn = timeline_brain_db.connect(self.root)
        conn.execute("DELETE FROM transcript_words")
        conn.commit()
        self.assertEqual(len(strata.read_words(conn, result["clip_uuid"])), 0)
        summary = strata.backfill_transcript_words(self.root)
        self.assertTrue(summary["success"], summary)
        self.assertEqual(summary["clips_with_words"], 1)
        self.assertEqual(summary["words_written"], 4)
        self.assertEqual(len(strata.read_words(conn, result["clip_uuid"])), 4)

    def test_backfill_real_sample_root(self) -> None:
        clips_root = os.path.join(REAL_SAMPLE_ROOT, "clips")
        if not os.path.isdir(clips_root):
            self.skipTest("real sample root not present on this machine")
        ingested = 0
        for entry in sorted(os.listdir(clips_root)):
            report_path = os.path.join(clips_root, entry, "analysis.json")
            if not os.path.isfile(report_path):
                continue
            with open(report_path, "r", encoding="utf-8") as handle:
                report = json.load(handle)
            result = analysis_store.ingest_report(self.root, report, clip_dir=entry)
            self.assertTrue(result["success"], result)
            ingested += 1
        self.assertGreater(ingested, 0)
        summary = strata.backfill_transcript_words(self.root)
        self.assertTrue(summary["success"], summary)
        self.assertEqual(summary["clips_seen"], ingested)


class EventTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="strata-events-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(timeline_brain_db.close_all)
        result = analysis_store.ingest_report(self.root, make_report(), clip_dir="clip-abcdef123456")
        self.clip_uuid = result["clip_uuid"]

    def test_machine_rerun_replaces_own_rows_only(self) -> None:
        with timeline_brain_db.transaction(self.root) as conn:
            strata.replace_track_events(
                conn, self.clip_uuid, "pause",
                [{"time_seconds": 1.0, "duration_seconds": 0.8}],
                source="prosody_v1", analyzer_version="1.0",
            )
            strata.record_human_event(conn, self.clip_uuid, "pause", 5.0, duration_seconds=2.0)
        with timeline_brain_db.transaction(self.root) as conn:
            strata.replace_track_events(
                conn, self.clip_uuid, "pause",
                [{"time_seconds": 2.0, "duration_seconds": 0.5}],
                source="prosody_v1", analyzer_version="1.1",
            )
        conn = timeline_brain_db.connect(self.root)
        events = strata.read_events(conn, self.clip_uuid, "pause")
        self.assertEqual(len(events), 2)
        by_source = {e["source"]: e for e in events}
        self.assertEqual(by_source["prosody_v1"]["time_seconds"], 2.0)
        self.assertEqual(by_source["human"]["time_seconds"], 5.0)

    def test_machine_writer_rejects_human_source(self) -> None:
        with timeline_brain_db.transaction(self.root) as conn:
            with self.assertRaises(ValueError):
                strata.replace_track_events(
                    conn, self.clip_uuid, "pause", [], source="human", analyzer_version="x",
                )

    def test_event_window_and_payload(self) -> None:
        with timeline_brain_db.transaction(self.root) as conn:
            strata.replace_track_events(
                conn, self.clip_uuid, "beat",
                [
                    {"time_seconds": float(i) * 0.5, "payload": {"tempo_bpm": 120.0}}
                    for i in range(10)
                ],
                source="beatgrid_v1", analyzer_version="1.0",
            )
        conn = timeline_brain_db.connect(self.root)
        window = strata.read_events(conn, self.clip_uuid, "beat", start_seconds=1.0, end_seconds=2.0)
        self.assertEqual([e["time_seconds"] for e in window], [1.0, 1.5])
        self.assertEqual(window[0]["payload"], {"tempo_bpm": 120.0})


class CurveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="strata-curves-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(timeline_brain_db.close_all)
        result = analysis_store.ingest_report(self.root, make_report(), clip_dir="clip-abcdef123456")
        self.clip_uuid = result["clip_uuid"]

    def test_curve_round_trip_with_nan_gaps(self) -> None:
        values = [110.0, 112.5, float("nan"), float("nan"), 98.0]
        with timeline_brain_db.transaction(self.root) as conn:
            stats = strata.write_curve(
                conn, self.clip_uuid, "pitch", values,
                sample_rate=100.0, source="prosody_v1", analyzer_version="1.0",
            )
        self.assertEqual(stats["finite_count"], 3)
        self.assertEqual(stats["max"], 112.5)
        conn = timeline_brain_db.connect(self.root)
        curve = strata.read_curve(conn, self.clip_uuid, "pitch")
        self.assertIsNotNone(curve)
        self.assertEqual(len(curve["values"]), 5)
        self.assertAlmostEqual(curve["values"][1], 112.5, places=3)
        self.assertTrue(math.isnan(curve["values"][2]))

    def test_curve_upsert_replaces(self) -> None:
        with timeline_brain_db.transaction(self.root) as conn:
            strata.write_curve(
                conn, self.clip_uuid, "motion_energy", [0.1, 0.2],
                sample_rate=10.0, source="motion_v1", analyzer_version="1.0",
            )
            strata.write_curve(
                conn, self.clip_uuid, "motion_energy", [0.3, 0.4, 0.5],
                sample_rate=10.0, source="motion_v1", analyzer_version="1.1",
            )
        conn = timeline_brain_db.connect(self.root)
        curve = strata.read_curve(conn, self.clip_uuid, "motion_energy")
        self.assertEqual(len(curve["values"]), 3)
        self.assertEqual(curve["analyzer_version"], "1.1")

    def test_curve_value_at(self) -> None:
        with timeline_brain_db.transaction(self.root) as conn:
            strata.write_curve(
                conn, self.clip_uuid, "vocal_energy", [0.0, 0.5, 1.0, float("nan")],
                sample_rate=2.0, start_seconds=1.0,
                source="prosody_v1", analyzer_version="1.0",
            )
        conn = timeline_brain_db.connect(self.root)
        curve = strata.read_curve(conn, self.clip_uuid, "vocal_energy")
        self.assertEqual(strata.curve_value_at(curve, 1.0), 0.0)
        self.assertEqual(strata.curve_value_at(curve, 2.0), 1.0)
        self.assertIsNone(strata.curve_value_at(curve, 2.5))   # NaN sample
        self.assertIsNone(strata.curve_value_at(curve, 99.0))  # off range


class StatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="strata-status-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(timeline_brain_db.close_all)

    def test_status_project_and_clip(self) -> None:
        result = analysis_store.ingest_report(
            self.root, make_report_with_words(), clip_dir="clip-abcdef123456"
        )
        clip_uuid = result["clip_uuid"]
        with timeline_brain_db.transaction(self.root) as conn:
            strata.replace_track_events(
                conn, clip_uuid, "pause",
                [{"time_seconds": 1.0, "duration_seconds": 0.8}],
                source="prosody_v1", analyzer_version="1.0",
            )
            strata.write_curve(
                conn, clip_uuid, "pitch", [100.0, 101.0],
                sample_rate=100.0, source="prosody_v1", analyzer_version="1.0",
            )
        status = strata.strata_status(self.root)
        self.assertTrue(status["success"])
        self.assertEqual(status["clips_with_words"], 1)
        self.assertEqual(status["word_count"], 4)
        self.assertEqual(status["event_tracks"][0]["track"], "pause")
        self.assertEqual(len(status["clip_rows"]), 1)
        self.assertEqual(status["clip_rows"][0]["word_count"], 4)
        self.assertEqual(status["clip_rows"][0]["event_track_count"], 1)
        self.assertEqual(status["clip_rows"][0]["curve_track_count"], 1)
        clip_status = strata.strata_status(self.root, clip_uuid)
        self.assertTrue(clip_status["success"])
        self.assertEqual(clip_status["word_count"], 4)
        self.assertEqual(len(clip_status["curves"]), 1)

    def test_status_unknown_clip(self) -> None:
        analysis_store.ingest_report(self.root, make_report(), clip_dir="clip-abcdef123456")
        status = strata.strata_status(self.root, "no-such-clip")
        self.assertFalse(status["success"])


if __name__ == "__main__":
    unittest.main()
