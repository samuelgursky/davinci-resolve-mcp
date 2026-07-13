"""Tests for story beats (plan/commit/list) + strata_query + timeline_strata."""

from __future__ import annotations

import shutil
import tempfile
import unittest

from src.utils import analysis_store, strata, strata_queries, strata_story, timeline_brain_db
from tests.test_analysis_store import make_report
from tests.test_strata import make_report_with_words


def _beat(start, end, beat_type="topic", label="a label", summary="what it is"):
    return {
        "start_seconds": start,
        "end_seconds": end,
        "beat_type": beat_type,
        "label": label,
        "summary": summary,
    }


class StoryBeatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="strata-story-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(timeline_brain_db.close_all)
        result = analysis_store.ingest_report(
            self.root, make_report_with_words(), clip_dir="story-clip"
        )
        self.clip_uuid = result["clip_uuid"]

    def test_plan_carries_digest_schema_and_evidence(self) -> None:
        with timeline_brain_db.transaction(self.root) as conn:
            strata.replace_track_events(
                conn, self.clip_uuid, "pause",
                [{"time_seconds": 1.5, "duration_seconds": 1.0}],
                source="prosody_v1", analyzer_version="1.0",
            )
        plan = strata_story.plan_story_beats(self.root, self.clip_uuid)
        self.assertTrue(plan["success"], plan)
        self.assertEqual(plan["status"], "pending_host_story_beats")
        self.assertEqual(len(plan["digest"]["segments"]), 2)
        self.assertEqual(plan["digest"]["segments"][0]["pauses"][0]["seconds"], 1.0)
        self.assertIn("beats", plan["schema"]["properties"])
        self.assertEqual(plan["commit_action"]["action"], "commit_story_beats")

    def test_plan_refuses_without_transcript(self) -> None:
        report = make_report()
        report["clip"]["clip_id"] = "no-transcript-id"
        report["clip"]["media_id"] = "no-transcript-media"
        report["clip"]["clip_name"] = "NoTranscript.mp4"
        report["clip"]["file_path"] = "/media/no transcript.mp4"
        report["transcription"] = {}
        result = analysis_store.ingest_report(self.root, report, clip_dir="wordless")
        plan = strata_story.plan_story_beats(self.root, result["clip_uuid"])
        self.assertFalse(plan["success"])
        self.assertIn("transcript", plan["error"])

    def test_commit_validates_and_lists(self) -> None:
        result = strata_story.commit_story_beats(
            self.root,
            self.clip_uuid,
            {
                "beats": [
                    _beat(0.0, 4.0, "topic", "the greeting", "Opening pleasantries."),
                    _beat(4.0, 9.5, "revelation", "the reply", "The response lands.", ),
                    _beat(9.5, 8.0),  # invalid: end < start
                    {"start_seconds": 1.0, "end_seconds": 2.0, "beat_type": "nope", "label": "x", "summary": "y"},
                ]
            },
            source_model="test-model",
        )
        self.assertTrue(result["success"], result)
        self.assertEqual(result["beats_committed"], 2)
        self.assertEqual(len(result["problems"]), 2)
        listed = strata_story.list_story_beats(self.root, self.clip_uuid)
        self.assertEqual(len(listed["beats"]), 2)
        self.assertEqual(listed["beats"][0]["beat_type"], "topic")

    def test_machine_recommit_supersedes_machine_not_human(self) -> None:
        strata_story.commit_story_beats(
            self.root, self.clip_uuid, [_beat(0.0, 4.0, label="machine v1")]
        )
        now = strata_story._now()
        conn = timeline_brain_db.connect(self.root)
        conn.execute(
            """
            INSERT INTO story_beats
                (beat_uuid, clip_uuid, start_seconds, end_seconds, beat_type,
                 label, summary, source, author, timestamp)
            VALUES ('humanbeat0001', ?, 2.0, 3.0, 'emotional', 'human note', 'Sam marked this.', 'human', 'sam', ?)
            """,
            (self.clip_uuid, now),
        )
        conn.commit()
        strata_story.commit_story_beats(
            self.root, self.clip_uuid, [_beat(0.0, 4.0, label="machine v2")]
        )
        listed = strata_story.list_story_beats(self.root, self.clip_uuid)
        labels = {b["label"] for b in listed["beats"]}
        self.assertEqual(labels, {"machine v2", "human note"})

    def test_commit_rejects_garbage(self) -> None:
        out = strata_story.commit_story_beats(self.root, self.clip_uuid, "not a list")
        self.assertFalse(out["success"])
        out = strata_story.commit_story_beats(self.root, self.clip_uuid, [{"nope": 1}])
        self.assertFalse(out["success"])
        self.assertTrue(out["problems"])


class StrataQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="strata-query-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(timeline_brain_db.close_all)
        result = analysis_store.ingest_report(
            self.root, make_report_with_words(), clip_dir="query-clip"
        )
        self.clip_uuid = result["clip_uuid"]
        with timeline_brain_db.transaction(self.root) as conn:
            strata.replace_track_events(
                conn, self.clip_uuid, "pause",
                [{"time_seconds": 1.1, "duration_seconds": 3.0}],
                source="prosody_v1", analyzer_version="1.0",
            )
            strata.write_curve(
                conn, self.clip_uuid, "vocal_energy", [0.1] * 20 + [0.9] * 20,
                sample_rate=10.0, source="prosody_v1", analyzer_version="1.0",
            )
        strata_story.commit_story_beats(
            self.root, self.clip_uuid, [_beat(3.5, 6.0, "claim", "the kenobi claim", "He names him.")]
        )

    def test_clip_window_bundle_joins_tracks(self) -> None:
        out = strata_queries.strata_query(
            self.root, clip_ref=self.clip_uuid, start_seconds=0.0, end_seconds=5.0
        )
        self.assertTrue(out["success"], out)
        self.assertEqual(out["mode"], "clip_window")
        self.assertEqual(len(out["words"]), 4)
        self.assertEqual(len(out["events"]["pause"]), 1)
        self.assertIn("vocal_energy", out["curves"])
        self.assertIn("window_stats", out["curves"]["vocal_energy"])
        self.assertEqual(out["story_beats"][0]["label"], "the kenobi claim")

    def test_word_find_returns_context(self) -> None:
        out = strata_queries.strata_query(self.root, match_word="kenobi")
        self.assertTrue(out["success"], out)
        self.assertEqual(len(out["hits"]), 1)
        hit = out["hits"][0]
        self.assertEqual(hit["word"], "kenobi")
        self.assertAlmostEqual(hit["time_seconds"], 4.8)
        self.assertIn("pause", hit["context"]["events"])
        self.assertTrue(hit["context"]["story_beats"])

    def test_curve_values_included_on_request(self) -> None:
        out = strata_queries.strata_query(
            self.root, clip_ref=self.clip_uuid, start_seconds=0.0, end_seconds=2.0,
            include_curve_values=True,
        )
        self.assertIn("values", out["curves"]["vocal_energy"])
        self.assertEqual(len(out["curves"]["vocal_energy"]["values"]), 21)

    def test_query_needs_a_mode(self) -> None:
        out = strata_queries.strata_query(self.root)
        self.assertFalse(out["success"])


class TimelineStrataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="strata-timeline-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(timeline_brain_db.close_all)
        result = analysis_store.ingest_report(
            self.root, make_report_with_words(), clip_dir="tl-clip"
        )
        self.clip_uuid = result["clip_uuid"]
        # The report's media_id is an alias for the clip; place it on a timeline.
        with timeline_brain_db.transaction(self.root) as conn:
            conn.execute(
                """
                INSERT INTO timeline_clip_usage
                    (media_pool_item_id, timeline_name, timeline_version,
                     track_type, track_index, in_frame, out_frame, observed_at)
                VALUES ('aaaa-bbbb', 'Cut 01', 3, 'video', 1, 240, 480, '2026-07-12T00:00:00Z')
                """
            )
            conn.execute(
                """
                INSERT INTO timeline_clip_usage
                    (media_pool_item_id, timeline_name, timeline_version,
                     track_type, track_index, in_frame, out_frame, observed_at)
                VALUES ('unknown-media', 'Cut 01', 3, 'video', 1, 480, 600, '2026-07-12T00:00:00Z')
                """
            )

    def test_projection_resolves_placements(self) -> None:
        out = strata_queries.timeline_strata(self.root, "Cut 01", fps=24.0)
        self.assertTrue(out["success"], out)
        self.assertEqual(out["timeline_version"], 3)
        self.assertEqual(len(out["placements"]), 2)
        placed = out["placements"][0]
        self.assertEqual(placed["record_in_seconds"], 10.0)
        self.assertEqual(placed["strata"]["clip_uuid"], self.clip_uuid)
        self.assertEqual(len(placed["strata"]["words"]), 4)
        self.assertEqual(out["unresolved_media_ids"], ["unknown-media"])

    def test_record_window_filter(self) -> None:
        out = strata_queries.timeline_strata(
            self.root, "Cut 01", record_start_frame=500, record_end_frame=560
        )
        self.assertEqual(len(out["placements"]), 1)
        self.assertEqual(out["placements"][0]["media_pool_item_id"], "unknown-media")

    def test_unknown_timeline_is_honest(self) -> None:
        out = strata_queries.timeline_strata(self.root, "Nope")
        self.assertFalse(out["success"])


if __name__ == "__main__":
    unittest.main()
