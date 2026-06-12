"""Unit tests for src/utils/shot_relationships.py (spec §4 — cross-shot
relationships).

No Resolve and no embedding backends required: per-shot visual vectors are
written straight into the v10 embeddings table so the pairwise heuristics,
the frame-pair confirmation payload, commit (confirm/reject/override +
supersede), listing, and the panel block are all covered offline.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from unittest import mock

from src.utils import analysis_store, embeddings, shot_relationships, timeline_brain_db
from src.utils import media_analysis as ma

from tests.test_analysis_store import make_report


class ShotRelationshipsBase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="shot-rel-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(timeline_brain_db.close_all)
        report_a = make_report()
        self.clip_a = analysis_store.ingest_report(self.root, report_a, clip_dir="clip-a-aaaaaaaaaaaa")["clip_uuid"]
        report_b = make_report()
        report_b["clip"] = dict(report_b["clip"], clip_id="22222222-0000-0000-0000-000000000002",
                                clip_name="Second Clip.mp4", file_path="/media/second clip.mp4", media_id="cccc-dddd")
        self.clip_b = analysis_store.ingest_report(self.root, report_b, clip_dir="second-clip-mp4-bbbbbbbbbbbb")["clip_uuid"]
        self.frames_dir = os.path.join(self.root, "frames-fake")
        os.makedirs(self.frames_dir, exist_ok=True)
        conn = timeline_brain_db.connect(self.root)
        self.shots = {}  # (clip_uuid, shot_index) -> shot_uuid
        for row in conn.execute("SELECT shot_uuid, clip_uuid, shot_index FROM shots"):
            self.shots[(str(row["clip_uuid"]), int(row["shot_index"]))] = str(row["shot_uuid"])
        # Every frame gets a path so frame-pair payloads resolve.
        with timeline_brain_db.transaction(self.root) as txn:
            for row in conn.execute("SELECT clip_uuid, frame_index FROM frames").fetchall():
                path = os.path.join(self.frames_dir, f"{row['clip_uuid']}_{row['frame_index']}.jpg")
                with open(path, "wb") as handle:
                    handle.write(b"fake")
                txn.execute(
                    "UPDATE frames SET frame_path = ? WHERE clip_uuid = ? AND frame_index = ?",
                    (path, row["clip_uuid"], row["frame_index"]),
                )

    def _add_shot_vector(self, clip_uuid: str, shot_index: int, vector: list) -> str:
        shot_uuid = self.shots[(clip_uuid, shot_index)]
        with timeline_brain_db.transaction(self.root) as txn:
            txn.execute(
                """
                INSERT OR REPLACE INTO embeddings
                    (entity_type, entity_uuid, embedding_kind, model_name, dimension,
                     vector, content_hash, computed_at)
                VALUES ('shot', ?, 'visual', 'fake:clip', ?, ?, 'h', '2026-06-10T00:00:00Z')
                """,
                (shot_uuid, len(vector), embeddings.pack_vector(vector)),
            )
        return shot_uuid

    def _seed_vectors(self) -> None:
        # Clip A: shots 1+3 near-identical (same_setup_as, gap 2); shot 2 at
        # cosine ~0.8 to both neighbors (continues_from band).
        self.a1 = self._add_shot_vector(self.clip_a, 1, [1.0, 0.0, 0.0, 0.0])
        self.a2 = self._add_shot_vector(self.clip_a, 2, [0.8, 0.0, 0.6, 0.0])
        self.a3 = self._add_shot_vector(self.clip_a, 3, [1.0, 0.2, 0.0, 0.0])
        # Clip B: shot 1 near-identical to A1 with comparable duration
        # (alt_take_of); shots 2+3 orthogonal (no candidates).
        self.b1 = self._add_shot_vector(self.clip_b, 1, [1.0, 0.1, 0.0, 0.0])
        self._add_shot_vector(self.clip_b, 2, [0.0, 0.0, 0.0, 1.0])
        self._add_shot_vector(self.clip_b, 3, [0.0, 1.0, 0.0, 0.0])


class DetectShotRelationshipsTests(ShotRelationshipsBase):
    def test_requires_shot_embeddings(self) -> None:
        result = shot_relationships.detect_shot_relationships(self.root)
        self.assertFalse(result["success"])
        self.assertIn("build_embeddings", result["error"])

    def test_heuristics_produce_typed_candidates(self) -> None:
        self._seed_vectors()
        result = shot_relationships.detect_shot_relationships(self.root)
        self.assertTrue(result["success"], result)
        self.assertEqual(result["status"], "pending_host_analysis")
        by_type = {}
        for candidate in result["candidates"]:
            by_type.setdefault(candidate["suggested_type"], []).append(candidate)
        self.assertIn("same_setup_as", by_type)
        self.assertIn("continues_from", by_type)
        self.assertIn("alt_take_of", by_type)
        # Every candidate carries a frame PAIR.
        for candidate in result["candidates"]:
            self.assertTrue(candidate["source_shot"]["frame_path"])
            self.assertTrue(candidate["target_shot"]["frame_path"])
        # continues_from is directional: the LATER shot is the source.
        cont = by_type["continues_from"][0]
        self.assertGreater(cont["source_shot"]["shot_index"], cont["target_shot"]["shot_index"])
        # Transcript continuity evidence: make_report has a segment 4.0-9.5s
        # spanning the shot 1|2 boundary at 5.2s.
        cont_1_2 = [c for c in by_type["continues_from"]
                    if c["target_shot"]["shot_index"] == 1 and c["source_shot"]["shot_index"] == 2]
        self.assertTrue(cont_1_2)
        self.assertTrue(any("transcript" in e for e in cont_1_2[0]["evidence"]))
        # Estimate: two frames per candidate.
        self.assertEqual(
            result["estimate"]["estimated_vision_tokens"],
            len(result["candidates"]) * 2 * ma.AVG_VISION_TOKENS_PER_FRAME,
        )
        self.assertEqual(result["commit_action"]["action"], "commit_shot_relationships")

    def test_no_rows_written_before_commit(self) -> None:
        self._seed_vectors()
        shot_relationships.detect_shot_relationships(self.root)
        conn = timeline_brain_db.connect(self.root)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM shot_relationships").fetchone()[0], 0)

    def test_caps_refusal_blocks(self) -> None:
        self._seed_vectors()
        refusal = {"success": False, "error": "over_day_cap", "caps_refusal": True}
        with mock.patch.object(ma, "_check_caps_pre_call", return_value=refusal):
            result = shot_relationships.detect_shot_relationships(self.root)
        self.assertEqual(result, refusal)

    def test_redetect_overwrites_state(self) -> None:
        self._seed_vectors()
        first = shot_relationships.detect_shot_relationships(self.root)
        second = shot_relationships.detect_shot_relationships(self.root, max_candidates=1)
        state = shot_relationships._read_state(self.root)
        self.assertEqual(state["vision_token"], second["vision_token"])
        self.assertEqual(len(state["candidates"]), 1)
        self.assertNotEqual(first["vision_token"], second["vision_token"])


class CommitShotRelationshipsTests(ShotRelationshipsBase):
    def _detect(self):
        self._seed_vectors()
        return shot_relationships.detect_shot_relationships(self.root)

    def test_commit_confirm_reject_and_override(self) -> None:
        payload = self._detect()
        candidates = payload["candidates"]
        entries = []
        for candidate in candidates:
            entries.append({
                "candidate_index": candidate["candidate_index"],
                "verdict": "confirm" if candidate["suggested_type"] != "continues_from" else "reject",
                "relationship_type": candidate["suggested_type"],
                "confidence": "high",
            })
        # Override one same_setup_as to alt_take_of to prove overrides stick.
        overridden = next(e for e in entries if e["relationship_type"] == "same_setup_as")
        overridden["relationship_type"] = "alt_take_of"
        result = shot_relationships.commit_shot_relationships(
            self.root, relationships_payload={"relationships": entries},
            vision_token=payload["vision_token"],
        )
        self.assertTrue(result["success"], result)
        self.assertGreater(result["confirmed"], 0)
        self.assertGreater(result["rejected"], 0)
        listed = shot_relationships.list_shot_relationships(self.root)
        self.assertEqual(listed["count"], result["confirmed"])
        self.assertTrue(all(r["source"] == "vision_relationship_v1" for r in listed["relationships"]))
        self.assertTrue(all(r["superseded_at"] is None for r in listed["relationships"]))

    def test_recommit_supersedes_machine_rows(self) -> None:
        payload = self._detect()
        entry = [{"candidate_index": 1, "verdict": "confirm", "confidence": "medium"}]
        shot_relationships.commit_shot_relationships(
            self.root, relationships_payload=entry, vision_token=payload["vision_token"])
        # Same candidate confirmed again (e.g. a re-run) → old row superseded.
        payload2 = shot_relationships.detect_shot_relationships(self.root)
        shot_relationships.commit_shot_relationships(
            self.root, relationships_payload=entry, vision_token=payload2["vision_token"])
        current = shot_relationships.list_shot_relationships(self.root)
        every = shot_relationships.list_shot_relationships(self.root, include_superseded=True)
        self.assertEqual(current["count"], 1)
        self.assertEqual(every["count"], 2)

    def test_token_mismatch_rejected(self) -> None:
        self._detect()
        result = shot_relationships.commit_shot_relationships(
            self.root, relationships_payload=[{"candidate_index": 1, "verdict": "confirm"}],
            vision_token="wrong-token",
        )
        self.assertFalse(result["success"])
        self.assertIn("vision_token mismatch", result["error"])

    def test_invalid_type_skipped(self) -> None:
        payload = self._detect()
        result = shot_relationships.commit_shot_relationships(
            self.root,
            relationships_payload=[{"candidate_index": 1, "verdict": "confirm",
                                    "relationship_type": "cuts_well_to"}],
            vision_token=payload["vision_token"],
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["confirmed"], 0)
        self.assertEqual(len(result["skipped"]), 1)


class ReadSurfacesTests(ShotRelationshipsBase):
    def _confirm_all(self):
        self._seed_vectors()
        payload = shot_relationships.detect_shot_relationships(self.root)
        entries = [{"candidate_index": c["candidate_index"], "verdict": "confirm"}
                   for c in payload["candidates"]]
        shot_relationships.commit_shot_relationships(
            self.root, relationships_payload=entries, vision_token=payload["vision_token"])
        return payload

    def test_list_filters_by_clip_and_type(self) -> None:
        self._confirm_all()
        alt_only = shot_relationships.list_shot_relationships(
            self.root, relationship_type="alt_take_of")
        self.assertTrue(alt_only["count"] >= 1)
        self.assertTrue(all(r["relationship_type"] == "alt_take_of" for r in alt_only["relationships"]))
        for_clip_b = shot_relationships.list_shot_relationships(
            self.root, clip_ref="22222222-0000-0000-0000-000000000002")
        self.assertTrue(for_clip_b["count"] >= 1)
        missing = shot_relationships.list_shot_relationships(self.root, clip_ref="nope")
        self.assertFalse(missing["success"])

    def test_relationships_for_shot_panel_block(self) -> None:
        self._confirm_all()
        conn = timeline_brain_db.connect(self.root)
        block_a1 = shot_relationships.relationships_for_shot(conn, self.a1)
        # A1 has same_setup_as with shot 3 (same clip → bare label) and an
        # alt take in clip B (cross-clip → clip-qualified label).
        self.assertIn("same_setup_as", block_a1)
        self.assertIn("shot 3", block_a1["same_setup_as"])
        self.assertIn("alt_take_of", block_a1)
        self.assertTrue(any("Second Clip" in label for label in block_a1["alt_take_of"]))
        # continues_from shows on the SOURCE (continuing) shot only.
        block_a2 = shot_relationships.relationships_for_shot(conn, self.a2)
        self.assertIn("continues_from", block_a2)
        self.assertIn("shot 1", block_a2["continues_from"])
        self.assertNotIn("continues_from", block_a1)

    def test_confirmed_alt_take_shot_uuids_bidirectional(self) -> None:
        self._confirm_all()
        conn = timeline_brain_db.connect(self.root)
        alts_of_a1 = shot_relationships.confirmed_alt_take_shot_uuids(conn, self.a1)
        self.assertIn(self.b1, alts_of_a1)
        alts_of_b1 = shot_relationships.confirmed_alt_take_shot_uuids(conn, self.b1)
        self.assertIn(self.a1, alts_of_b1)


if __name__ == "__main__":
    unittest.main()
