"""Unit tests for src/utils/embeddings.py (Phase C — embeddings + similarity).

No Resolve and no embedding backends required: backend calls are mocked with
deterministic keyword vectors, so these cover the store/search plumbing —
v10 schema, idempotent builds, content-hash staleness, cosine ranking,
self-exclusion, and the deep-field text builder.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from src.utils import analysis_store, embeddings, timeline_brain_db

from tests.test_analysis_store import make_report

_KEYWORDS = ("kenobi", "talks", "title", "closing")


def fake_vector(text: str) -> list:
    lowered = text.lower()
    return [float(lowered.count(k)) for k in _KEYWORDS] + [1.0]


def fake_embed_texts(texts, *, backend=None):
    return {
        "success": True,
        "vectors": [fake_vector(t) for t in texts],
        "model": "fake:test-embed",
        "backend": "fake",
    }


class EmbeddingsBase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="embeddings-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(timeline_brain_db.close_all)
        result = analysis_store.ingest_report(self.root, make_report(), clip_dir="sample-clip-mp4-abcdef123456")
        self.clip_uuid = result["clip_uuid"]


class SchemaAndPackingTests(EmbeddingsBase):
    def test_v10_embeddings_table_exists(self) -> None:
        conn = timeline_brain_db.connect(self.root)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("embeddings", tables)
        self.assertGreaterEqual(timeline_brain_db._read_schema_version(conn), 10)

    def test_pack_unpack_round_trip(self) -> None:
        vec = [0.25, -1.5, 3.125, 0.0]
        self.assertEqual(embeddings.unpack_vector(embeddings.pack_vector(vec)), vec)

    def test_cosine_similarity(self) -> None:
        self.assertAlmostEqual(embeddings.cosine_similarity([1, 0], [1, 0]), 1.0)
        self.assertAlmostEqual(embeddings.cosine_similarity([1, 0], [0, 1]), 0.0)
        self.assertEqual(embeddings.cosine_similarity([0, 0], [1, 1]), 0.0)

    def test_detect_capabilities_shape(self) -> None:
        caps = embeddings.detect_embedding_capabilities()
        self.assertIn("text", caps)
        self.assertIn("visual", caps)
        self.assertTrue(caps["no_auto_install"])
        if not caps["text"]["available"]:
            self.assertIn("text", caps["install_guidance"])


class BuildEmbeddingsTests(EmbeddingsBase):
    def test_build_text_embeddings_and_idempotency(self) -> None:
        with mock.patch.object(embeddings, "embed_texts", side_effect=fake_embed_texts):
            first = embeddings.build_embeddings(self.root, kinds=("text",))
            self.assertTrue(first["success"], first)
            # 1 clip + 3 shots + 2 segments
            self.assertEqual(first["text"]["embedded"], 6)
            second = embeddings.build_embeddings(self.root, kinds=("text",))
            self.assertEqual(second["text"]["embedded"], 0)
        self.assertEqual(first["totals"]["text"], 6)

    def test_content_change_triggers_reembed(self) -> None:
        with mock.patch.object(embeddings, "embed_texts", side_effect=fake_embed_texts):
            embeddings.build_embeddings(self.root, kinds=("text",))
            analysis_store.record_human_correction(
                self.root, clip_ref=self.clip_uuid, entity_type="shot", entity_uuid=2,
                field_path="description", value="A corrected description.", author="sam",
            )
            # The shots table row text comes from ingest; re-ingest the exported
            # report so the human description lands in the shots table.
            exported = analysis_store.export_report(self.root, self.clip_uuid)
            analysis_store.ingest_report(self.root, exported, clip_dir="sample-clip-mp4-abcdef123456")
            result = embeddings.build_embeddings(self.root, kinds=("text",))
            self.assertEqual(result["text"]["embedded"], 1)

    def test_no_backend_fails_soft(self) -> None:
        with mock.patch.object(
            embeddings, "embed_texts",
            return_value={"success": False, "error": "No text-embedding backend available"},
        ):
            result = embeddings.build_embeddings(self.root, kinds=("text",))
        self.assertFalse(result["success"])
        self.assertIn("error", result["text"])

    def test_shot_embed_text_includes_deep_groups(self) -> None:
        shot = {
            "description": "Wide drive-by.",
            "extra_json": json.dumps({
                "visual": {"shot_size": "wide", "camera_motion": "handheld"},
                "editorial": {"select_potential": "high"},
            }),
        }
        text = embeddings._shot_embed_text(shot)
        self.assertIn("Wide drive-by.", text)
        self.assertIn("shot_size", text)
        self.assertIn("select_potential", text)

    def test_build_visual_embeddings_with_mock(self) -> None:
        # Put fake frame files on disk and point the frames table at them.
        frames_dir = os.path.join(self.root, "clips", "sample-clip-mp4-abcdef123456", "frames")
        os.makedirs(frames_dir, exist_ok=True)
        report = make_report()
        for kf in report["motion"]["analysis_keyframes"]:
            path = os.path.join(frames_dir, f"sampled_{kf['index']:04d}.jpg")
            with open(path, "wb") as handle:
                handle.write(b"fake")
            kf["frame_path"] = path
        analysis_store.ingest_report(self.root, report, clip_dir="sample-clip-mp4-abcdef123456")

        def fake_embed_images(paths):
            return {
                "success": True,
                "vectors": [[1.0, float(i)] for i, _ in enumerate(paths)],
                "model": "fake:clip",
            }

        with mock.patch.object(embeddings, "embed_images", side_effect=fake_embed_images):
            result = embeddings.build_embeddings(self.root, kinds=("visual",))
        self.assertTrue(result["success"], result)
        # 3 frames + 3 per-shot mean vectors (each shot has one frame).
        self.assertEqual(result["visual"]["embedded"], 6)
        conn = timeline_brain_db.connect(self.root)
        kinds = conn.execute(
            "SELECT entity_type, COUNT(*) AS n FROM embeddings WHERE embedding_kind='visual' GROUP BY entity_type"
        ).fetchall()
        counts = {r["entity_type"]: r["n"] for r in kinds}
        self.assertEqual(counts, {"frame": 3, "shot": 3})


class FindSimilarTests(EmbeddingsBase):
    def setUp(self) -> None:
        super().setUp()
        with mock.patch.object(embeddings, "embed_texts", side_effect=fake_embed_texts):
            embeddings.build_embeddings(self.root, kinds=("text",))

    def test_text_query_ranks_matching_segment_first(self) -> None:
        with mock.patch.object(embeddings, "embed_texts", side_effect=fake_embed_texts):
            result = embeddings.find_similar(self.root, text="general kenobi", limit=3)
        self.assertTrue(result["success"], result)
        top = result["results"][0]
        self.assertEqual(top["entity_type"], "segment")
        self.assertIn("kenobi", top["text"])

    def test_clip_query_excludes_itself(self) -> None:
        result = embeddings.find_similar(self.root, clip_ref=self.clip_uuid, limit=10)
        self.assertTrue(result["success"], result)
        for hit in result["results"]:
            self.assertFalse(
                hit["entity_type"] == "clip" and hit["entity_uuid"] == self.clip_uuid,
                "query entity leaked into its own results",
            )

    def test_shot_query_by_index(self) -> None:
        result = embeddings.find_similar(self.root, clip_ref=self.clip_uuid, shot_index=2, limit=5)
        self.assertTrue(result["success"], result)
        self.assertTrue(result["results"])

    def test_missing_embedding_says_build_first(self) -> None:
        result = embeddings.find_similar(self.root, clip_ref=self.clip_uuid, kind="visual")
        self.assertFalse(result["success"])
        self.assertIn("build_embeddings", result["error"])

    def test_entity_type_filter(self) -> None:
        with mock.patch.object(embeddings, "embed_texts", side_effect=fake_embed_texts):
            result = embeddings.find_similar(
                self.root, text="talks", entity_types=["shot"], limit=10
            )
        self.assertTrue(result["success"])
        self.assertTrue(all(r["entity_type"] == "shot" for r in result["results"]))


def fake_embed_audio_windows(file_path, windows):
    # One deterministic vector per window, keyed by the window start.
    return {
        "success": True,
        "vectors": [[1.0, float(start), 0.5] for start, _end in windows],
        "model": "fake:clap",
    }


class AudioEmbeddingsTests(EmbeddingsBase):
    """CLAP audio embeddings (Phase 6) — backend mocked; covers the build
    plumbing, graceful skip, missing media, and audio similarity search."""

    def _ingest_with_real_media(self) -> str:
        media = os.path.join(self.root, "fake-media.mp4")
        with open(media, "wb") as handle:
            handle.write(b"not really media")
        report = make_report()
        report["clip"] = dict(report["clip"], file_path=media)
        result = analysis_store.ingest_report(self.root, report, clip_dir="sample-clip-mp4-abcdef123456")
        return result["clip_uuid"]

    def test_capabilities_include_audio_block(self) -> None:
        caps = embeddings.detect_embedding_capabilities()
        self.assertIn("audio", caps)
        self.assertIn("backends", caps["audio"])
        if not caps["audio"]["available"]:
            self.assertIn("audio", caps["install_guidance"])

    def test_build_audio_embeddings_and_idempotency(self) -> None:
        clip_uuid = self._ingest_with_real_media()
        available = {"audio": {"available": True, "backends": ["transformers_clap"],
                               "model": "fake", "ffmpeg": True}, "install_guidance": {}}
        with mock.patch.object(embeddings, "detect_embedding_capabilities", return_value=available), \
             mock.patch.object(embeddings, "embed_audio_windows", side_effect=fake_embed_audio_windows):
            first = embeddings.build_embeddings(self.root, kinds=("audio",))
            self.assertTrue(first["success"], first)
            # 3 shot windows + 1 clip-level mean vector.
            self.assertEqual(first["audio"]["embedded"], 4)
            second = embeddings.build_embeddings(self.root, kinds=("audio",))
            self.assertEqual(second["audio"]["embedded"], 0)
        conn = timeline_brain_db.connect(self.root)
        counts = {
            r["entity_type"]: r["n"] for r in conn.execute(
                "SELECT entity_type, COUNT(*) AS n FROM embeddings "
                "WHERE embedding_kind='audio' GROUP BY entity_type"
            )
        }
        self.assertEqual(counts, {"shot": 3, "clip": 1})
        row = conn.execute(
            "SELECT vector FROM embeddings WHERE embedding_kind='audio' AND entity_type='clip' AND entity_uuid=?",
            (clip_uuid,),
        ).fetchone()
        self.assertIsNotNone(row)

    def test_build_audio_graceful_skip_without_backend(self) -> None:
        self._ingest_with_real_media()
        unavailable = {"audio": {"available": False, "backends": [], "model": None, "ffmpeg": True},
                       "install_guidance": {"audio": "pip install transformers"}}
        with mock.patch.object(embeddings, "detect_embedding_capabilities", return_value=unavailable):
            result = embeddings.build_embeddings(self.root, kinds=("audio",))
        self.assertFalse(result["success"])
        self.assertTrue(result["audio"]["skipped"])
        self.assertEqual(result["audio"]["install_guidance"], "pip install transformers")

    def test_missing_media_is_reported_not_fatal(self) -> None:
        # make_report's file_path (/media/sample clip.mp4) does not exist.
        available = {"audio": {"available": True, "backends": ["transformers_clap"],
                               "model": "fake", "ffmpeg": True}, "install_guidance": {}}
        with mock.patch.object(embeddings, "detect_embedding_capabilities", return_value=available), \
             mock.patch.object(embeddings, "embed_audio_windows", side_effect=fake_embed_audio_windows):
            result = embeddings.build_embeddings(self.root, kinds=("audio",))
        self.assertTrue(result["success"], result)
        self.assertEqual(result["audio"]["embedded"], 0)
        self.assertEqual(len(result["audio"]["skipped_missing_media"]), 1)

    def test_find_similar_audio_by_shot_and_text(self) -> None:
        media_clip_uuid = self._ingest_with_real_media()
        available = {"audio": {"available": True, "backends": ["transformers_clap"],
                               "model": "fake", "ffmpeg": True}, "install_guidance": {}}
        with mock.patch.object(embeddings, "detect_embedding_capabilities", return_value=available), \
             mock.patch.object(embeddings, "embed_audio_windows", side_effect=fake_embed_audio_windows):
            embeddings.build_embeddings(self.root, kinds=("audio",))
        result = embeddings.find_similar(
            self.root, clip_ref=media_clip_uuid, shot_index=1, kind="audio", limit=5)
        self.assertTrue(result["success"], result)
        self.assertTrue(result["results"])
        with mock.patch.object(
            embeddings, "embed_text_for_audio_query",
            return_value={"success": True, "vector": [1.0, 0.0, 0.5], "model": "fake:clap"},
        ):
            text_result = embeddings.find_similar(self.root, text="engine revving", kind="audio")
        self.assertTrue(text_result["success"], text_result)
        self.assertTrue(text_result["results"])

    def test_find_similar_rejects_unknown_kind(self) -> None:
        result = embeddings.find_similar(self.root, text="x", kind="smell")
        self.assertFalse(result["success"])
        self.assertIn("audio", result["error"])

    def test_embed_audio_windows_requires_backend(self) -> None:
        result = embeddings.embed_audio_windows("/no/such/file.mp4", [(0.0, 5.0)])
        if not embeddings.detect_embedding_capabilities()["audio"]["available"]:
            self.assertFalse(result["success"])
            self.assertIn("install_guidance", result)


if __name__ == "__main__":
    unittest.main()
