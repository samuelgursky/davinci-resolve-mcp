"""Unit tests for src/utils/entities.py (Phase D — cross-clip entities).

No Resolve and no embedding backends required: visual vectors are written
straight into the v10 embeddings table so clustering, the confirmation
payload, commit (labels + merges), ghost pruning, and the bin-briefing flow
are all covered offline.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from src.utils import analysis_memory, analysis_store, embeddings, entities, timeline_brain_db
from src.utils import media_analysis as ma

from tests.test_analysis_store import make_report


def _vec(direction: int, jitter: float = 0.0) -> list:
    """Unit-ish vectors: same direction → cosine ~1, different → ~0."""
    base = [0.0] * 8
    base[direction] = 1.0
    if jitter:
        base[(direction + 1) % 8] = jitter
    return base


class EntitiesBase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="entities-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(timeline_brain_db.close_all)
        # Two clips so clusters can span clips.
        report_a = make_report()
        self.clip_a = analysis_store.ingest_report(self.root, report_a, clip_dir="clip-a-aaaaaaaaaaaa")["clip_uuid"]
        report_b = make_report()
        report_b["clip"] = dict(report_b["clip"], clip_id="22222222-0000-0000-0000-000000000002",
                                clip_name="Second Clip.mp4", file_path="/media/second clip.mp4", media_id="cccc-dddd")
        self.clip_b = analysis_store.ingest_report(self.root, report_b, clip_dir="second-clip-mp4-bbbbbbbbbbbb")["clip_uuid"]
        self.frames_dir = os.path.join(self.root, "frames-fake")
        os.makedirs(self.frames_dir, exist_ok=True)

    def _add_visual_vector(self, clip_uuid: str, frame_index: int, vector: list) -> str:
        ref = f"{clip_uuid}:{frame_index}"
        path = os.path.join(self.frames_dir, f"{clip_uuid}_{frame_index}.jpg")
        with open(path, "wb") as handle:
            handle.write(b"fake")
        conn = timeline_brain_db.connect(self.root)
        with timeline_brain_db.transaction(self.root) as txn:
            txn.execute(
                "UPDATE frames SET frame_path = ? WHERE clip_uuid = ? AND frame_index = ?",
                (path, clip_uuid, frame_index),
            )
            txn.execute(
                """
                INSERT OR REPLACE INTO embeddings
                    (entity_type, entity_uuid, embedding_kind, model_name, dimension,
                     vector, content_hash, computed_at)
                VALUES ('frame', ?, 'visual', 'fake:clip', ?, ?, 'h', '2026-06-10T00:00:00Z')
                """,
                (ref, len(vector), embeddings.pack_vector(vector)),
            )
        return ref

    def _seed_two_clusters(self) -> None:
        # Cluster 1: same "person" in both clips (3 frames).
        self._add_visual_vector(self.clip_a, 1, _vec(0))
        self._add_visual_vector(self.clip_a, 2, _vec(0, 0.05))
        self._add_visual_vector(self.clip_b, 1, _vec(0, 0.1))
        # Cluster 2: a "location" in clip B (2 frames).
        self._add_visual_vector(self.clip_b, 2, _vec(3))
        self._add_visual_vector(self.clip_b, 3, _vec(3, 0.05))


class DetectEntitiesTests(EntitiesBase):
    def test_requires_visual_embeddings(self) -> None:
        result = entities.detect_entities(self.root)
        self.assertFalse(result["success"])
        self.assertIn("build_embeddings", result["error"])

    def test_clusters_and_payload(self) -> None:
        self._seed_two_clusters()
        result = entities.detect_entities(self.root)
        self.assertTrue(result["success"], result)
        self.assertEqual(result["status"], "pending_host_analysis")
        self.assertEqual(result["cluster_count"], 2)
        first = result["clusters"][0]
        self.assertEqual(first["frame_count"], 3)
        self.assertEqual(first["clip_count"], 2)  # spans both clips
        self.assertEqual(len(result["frame_paths"]), 2)
        self.assertEqual(result["commit_action"]["action"], "commit_entities")
        # Provisional rows exist with appearances.
        listed = entities.list_entities(self.root)
        self.assertEqual(listed["count"], 2)
        self.assertEqual(listed["entities"][0]["source"], "clustering")
        self.assertEqual(listed["entities"][0]["clip_count"], 2)

    def test_caps_refusal_blocks(self) -> None:
        self._seed_two_clusters()
        refusal = {"success": False, "error": "over_day_cap", "caps_refusal": True}
        with mock.patch.object(ma, "_check_caps_pre_call", return_value=refusal):
            result = entities.detect_entities(self.root)
        self.assertEqual(result, refusal)

    def test_rerun_prunes_unlabeled_ghosts_keeps_labeled(self) -> None:
        self._seed_two_clusters()
        payload = entities.detect_entities(self.root)
        # Label cluster 1.
        entities.commit_entities(
            self.root,
            entities_payload=[{"entity_index": 1, "kind": "person", "label": "man in dark jacket",
                               "description": "recurring driver", "confidence": "medium"}],
            vision_token=payload["vision_token"],
        )
        # Add a vector that reshapes cluster 2 (new uuid), re-detect.
        self._add_visual_vector(self.clip_b, 2, _vec(3, 0.2))
        entities.detect_entities(self.root)
        listed = entities.list_entities(self.root)
        labels = [e.get("label") for e in listed["entities"]]
        self.assertIn("man in dark jacket", labels)
        unlabeled = [e for e in listed["entities"] if not e.get("label")]
        # Only current-run provisionals remain — no accumulated ghosts.
        self.assertLessEqual(len(unlabeled), 1)


class CommitEntitiesTests(EntitiesBase):
    def test_commit_labels_and_merge(self) -> None:
        self._seed_two_clusters()
        payload = entities.detect_entities(self.root)
        result = entities.commit_entities(
            self.root,
            entities_payload={"entities": [
                {"entity_index": 1, "kind": "person", "label": "man in dark hooded jacket",
                 "description": "Driver recurring across both clips.", "confidence": "high"},
                {"entity_index": 2, "kind": "place", "label": "roadside location",
                 "description": "Exterior road location.", "confidence": "medium"},
            ]},
            vision_token=payload["vision_token"],
        )
        self.assertTrue(result["success"], result)
        self.assertEqual(result["entities_updated"], 2)
        listed = entities.list_entities(self.root)
        by_label = {e["label"]: e for e in listed["entities"]}
        self.assertEqual(by_label["man in dark hooded jacket"]["kind"], "person")
        self.assertEqual(by_label["man in dark hooded jacket"]["source"], "vision_entity_v1")

    def test_merge_with_combines_clusters(self) -> None:
        self._seed_two_clusters()
        payload = entities.detect_entities(self.root)
        result = entities.commit_entities(
            self.root,
            entities_payload=[
                {"entity_index": 1, "kind": "person", "label": "driver", "confidence": "high"},
                {"entity_index": 2, "merge_with": 1},
            ],
            vision_token=payload["vision_token"],
        )
        self.assertTrue(result["success"], result)
        self.assertEqual(result["entities_merged"], 1)
        listed = entities.list_entities(self.root)
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["entities"][0]["cluster_size"], 5)

    def test_token_mismatch_rejected(self) -> None:
        self._seed_two_clusters()
        entities.detect_entities(self.root)
        result = entities.commit_entities(
            self.root, entities_payload=[{"entity_index": 1, "label": "x"}], vision_token="bogus"
        )
        self.assertFalse(result["success"])
        self.assertIn("vision_token mismatch", result["error"])


class BinBriefingTests(EntitiesBase):
    def test_prepare_and_commit_briefing(self) -> None:
        self._seed_two_clusters()
        payload = entities.detect_entities(self.root)
        entities.commit_entities(
            self.root,
            entities_payload=[{"entity_index": 1, "kind": "person", "label": "driver", "confidence": "high"}],
            vision_token=payload["vision_token"],
        )
        prep = entities.prepare_bin_briefing(self.root)
        self.assertTrue(prep["success"], prep)
        self.assertEqual(prep["status"], "pending_host_synthesis")
        self.assertEqual(len(prep["clips"]), 2)
        self.assertTrue(any(e["label"] == "driver" for e in prep["entities"]))

        commit = entities.commit_bin_summary(
            self.root,
            briefing="Two clips of stunt-comedy coverage; the driver recurs throughout.",
            briefing_token=prep["briefing_token"],
        )
        self.assertTrue(commit["success"], commit)
        with open(analysis_memory.bin_summary_path(self.root), "r", encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("# Bin briefing", content)
        self.assertIn("the driver recurs", content)

    def test_briefing_preserves_aggregate_appendix(self) -> None:
        path = analysis_memory.bin_summary_path(self.root)
        analysis_memory.ensure_memory_structure(self.root)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("# Bin summary — Old Aggregate\n\naggregate body\n")
        prep = entities.prepare_bin_briefing(self.root)
        entities.commit_bin_summary(
            self.root, briefing="New briefing.", briefing_token=prep["briefing_token"]
        )
        with open(path, "r", encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("New briefing.", content)
        self.assertIn("# Bin summary — Old Aggregate", content)

    def test_briefing_token_mismatch(self) -> None:
        result = entities.commit_bin_summary(self.root, briefing="x", briefing_token="bogus")
        self.assertFalse(result["success"])


if __name__ == "__main__":
    unittest.main()
