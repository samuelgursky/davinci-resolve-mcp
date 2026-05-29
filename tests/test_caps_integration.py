"""Integration tests for caps enforcement in media_analysis.

Verifies the helpers added in the caps push:
- _check_caps_pre_call returns a clean refusal dict when over budget
- _record_caps_usage gracefully no-ops without a project_root
- _resolve_active_caps reads the registered providers
- Job_id threading: options.job_id propagates into recorded rows

No Resolve required.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from src.utils import analysis_caps, media_analysis, timeline_brain_db


class PreCallRefusal(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="caps_integration_test_")
        self.project_root = os.path.join(self.tmp, "project")
        os.makedirs(self.project_root, exist_ok=True)
        # Install a minimal-preset provider so the test deterministically caps.
        self._saved_preset = media_analysis._CAPS_PRESET_PROVIDER
        self._saved_overrides = media_analysis._CAPS_OVERRIDES_PROVIDER
        media_analysis.register_caps_preset_provider(lambda: analysis_caps.PRESET_MINIMAL)
        media_analysis.register_caps_overrides_provider(lambda: None)

    def tearDown(self) -> None:
        media_analysis._CAPS_PRESET_PROVIDER = self._saved_preset
        media_analysis._CAPS_OVERRIDES_PROVIDER = self._saved_overrides
        timeline_brain_db.reset_for_test(self.project_root)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_pre_call_check_allows_when_within_budget(self) -> None:
        # Brand-new project — zero usage, ask for a small chunk.
        result = media_analysis._check_caps_pre_call(
            project_root=self.project_root,
            estimated_vision_tokens=500,
            clip_id="c1",
        )
        self.assertIsNone(result, msg=f"unexpected refusal: {result}")

    def test_pre_call_check_refuses_when_over_clip_cap(self) -> None:
        # minimal preset = 16_000 tokens per clip; record 15500 then ask 1000.
        analysis_caps.record_usage(
            project_root=self.project_root, scope=analysis_caps.SCOPE_CLIP,
            scope_key="c1", vision_tokens=15_500,
        )
        result = media_analysis._check_caps_pre_call(
            project_root=self.project_root,
            estimated_vision_tokens=1000,
            clip_id="c1",
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "caps_exhausted")
        self.assertEqual(result["reason"], "over_clip_cap")
        self.assertIn("remediation", result)

    def test_pre_call_check_no_project_root_returns_none(self) -> None:
        # Without a project_root we can't reach the caps DB; should silently allow.
        result = media_analysis._check_caps_pre_call(
            project_root=None,
            estimated_vision_tokens=10_000_000,
            clip_id="c1",
        )
        self.assertIsNone(result)

    def test_pre_call_check_no_estimated_tokens_returns_none(self) -> None:
        # 0 tokens means "we don't know"; default to allow so the pipeline
        # isn't blocked when token estimation isn't available.
        result = media_analysis._check_caps_pre_call(
            project_root=self.project_root,
            estimated_vision_tokens=0,
            clip_id="c1",
        )
        self.assertIsNone(result)


class JobIdThreading(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="job_id_test_")
        self.project_root = os.path.join(self.tmp, "project")
        os.makedirs(self.project_root, exist_ok=True)

    def tearDown(self) -> None:
        timeline_brain_db.reset_for_test(self.project_root)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_record_caps_usage_writes_job_scope(self) -> None:
        media_analysis._record_caps_usage(
            project_root=self.project_root,
            clip_id="c1",
            job_id="j_abc",
            vision_tokens=1000,
        )
        conn = timeline_brain_db.connect(self.project_root)
        scopes = conn.execute(
            "SELECT scope, scope_key FROM analysis_token_usage ORDER BY scope"
        ).fetchall()
        scope_keys = sorted({(r["scope"], r["scope_key"]) for r in scopes})
        # Expect rows for clip, day, job
        self.assertIn(("clip", "c1"), scope_keys)
        self.assertIn(("job", "j_abc"), scope_keys)
        self.assertIn(("day", None), scope_keys)

    def test_record_caps_usage_skips_job_when_not_provided(self) -> None:
        media_analysis._record_caps_usage(
            project_root=self.project_root,
            clip_id="c1",
            vision_tokens=500,
        )
        conn = timeline_brain_db.connect(self.project_root)
        scopes = {r["scope"] for r in conn.execute(
            "SELECT scope FROM analysis_token_usage"
        ).fetchall()}
        self.assertNotIn("job", scopes)
        self.assertIn("clip", scopes)
        self.assertIn("day", scopes)


class VisionAnalysisRefusalPropagation(unittest.TestCase):
    """End-to-end: when caps refuse, `_vision_analysis` must return the
    caps_exhausted payload — not overwrite it with the no-frames "skipped"
    fallback. Regression for the V3 live-test bug where
    `if not payload.get("frame_paths")` discarded the refusal envelope.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="vision_refusal_test_")
        # Lay out a plausible clip dir: project_root/clips/<clip_dir>
        self.project_root = os.path.join(self.tmp, "project")
        self.clip_dir = os.path.join(self.project_root, "clips", "clip_a")
        self.frames_dir = os.path.join(self.clip_dir, "frames")
        os.makedirs(self.frames_dir, exist_ok=True)
        self.frame_path = os.path.join(self.frames_dir, "frame_001.jpg")
        with open(self.frame_path, "wb") as fh:
            fh.write(b"\xff\xd8\xff\xd9")  # minimal JPEG SOI/EOI

        self._saved_preset = media_analysis._CAPS_PRESET_PROVIDER
        self._saved_overrides = media_analysis._CAPS_OVERRIDES_PROVIDER
        # Force a refusal: day cap = 1 token, so any non-zero estimate exceeds it.
        media_analysis.register_caps_preset_provider(lambda: analysis_caps.PRESET_MINIMAL)
        media_analysis.register_caps_overrides_provider(lambda: {"vision_tokens_per_day": 1})

    def tearDown(self) -> None:
        media_analysis._CAPS_PRESET_PROVIDER = self._saved_preset
        media_analysis._CAPS_OVERRIDES_PROVIDER = self._saved_overrides
        timeline_brain_db.reset_for_test(self.project_root)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_vision_analysis_returns_caps_refusal_payload(self) -> None:
        record = {"clip_id": "clip_a", "clip_name": "fixture.mp4", "file_path": "/tmp/fixture.mp4"}
        motion = {"analysis_keyframes": [{"frame_path": self.frame_path, "time_seconds": 0.0}]}
        options = {"vision": {"enabled": True, "provider": "host_chat_paths"}}
        artifacts = {
            "clip_dir": self.clip_dir,
            "visual_json": os.path.join(self.clip_dir, "visual.json"),
        }
        capabilities = {"vision": {"provider": "host_chat_paths"}}

        payload = media_analysis._vision_analysis(record, motion, options, artifacts, capabilities)

        # Pre-fix this was {success: False, status: "skipped", reason: "No sampled..."}.
        # Post-fix the refusal envelope from build_host_chat_paths_payload propagates.
        self.assertFalse(payload["success"])
        self.assertEqual(payload["status"], "caps_exhausted")
        self.assertEqual(payload["reason"], "over_day_cap")
        self.assertEqual(payload["preset"], "minimal")
        self.assertIn("remediation", payload)


class CapsRefusalSurfacing(unittest.TestCase):
    """The pre-call refusal must surface as a structured CAPS_REFUSAL envelope
    on both the per-clip row and the top-level manifest, so callers don't have
    to dig through `manifest.clips[*].error` to know they were budget-blocked.
    """

    def _refusal_vision(self) -> dict:
        # Shape matches what _check_caps_pre_call returns on refusal.
        return {
            "success": False,
            "status": "caps_exhausted",
            "reason": "over_day_cap",
            "estimated_vision_tokens": 4000,
            "current_usage": {"clip_vision_tokens": 0, "job_vision_tokens": 0, "day_vision_tokens": 0},
            "cap": {"clip": 5000, "job": 50000, "day": 1},
            "headroom": {"clip": 5000, "job": 50000, "day": 1},
            "preset": "minimal",
            "remediation": "Raise the cap via media_analysis.set_caps_preset...",
        }

    def test_clip_result_gets_structured_caps_refusal_error(self) -> None:
        clip_result: dict = {"clip_id": "c1", "success": True}
        media_analysis._annotate_clip_vision_failure(clip_result, self._refusal_vision())

        self.assertFalse(clip_result["success"])
        error = clip_result["error"]
        self.assertIsInstance(error, dict)
        self.assertEqual(error["code"], "CAPS_REFUSAL")
        self.assertEqual(error["category"], "budget_exhausted")
        self.assertEqual(error["reason"], "over_day_cap")
        self.assertIn("remediation", error)
        self.assertIn("message", error)

        caps_refusal = clip_result["caps_refusal"]
        self.assertEqual(caps_refusal["preset"], "minimal")
        self.assertEqual(caps_refusal["estimated_vision_tokens"], 4000)
        self.assertEqual(caps_refusal["headroom"], {"clip": 5000, "job": 50000, "day": 1})

    def test_clip_result_falls_back_to_generic_message_on_non_caps_failure(self) -> None:
        clip_result: dict = {"clip_id": "c1", "success": True}
        media_analysis._annotate_clip_vision_failure(
            clip_result, {"success": False, "status": "skipped", "reason": "no frames"},
        )
        self.assertFalse(clip_result["success"])
        self.assertEqual(
            clip_result["error"], "Visual analysis was requested but did not complete.",
        )
        self.assertNotIn("caps_refusal", clip_result)

    def test_manifest_lifts_refusal_to_top_level_error(self) -> None:
        # Two refused clips, one unrelated success.
        clip_a: dict = {"clip_id": "a", "success": True}
        clip_b: dict = {"clip_id": "b", "success": True}
        clip_ok: dict = {"clip_id": "ok", "success": True}
        media_analysis._annotate_clip_vision_failure(clip_a, self._refusal_vision())
        media_analysis._annotate_clip_vision_failure(clip_b, self._refusal_vision())

        manifest = {"clips": [clip_a, clip_b, clip_ok], "clip_count": 3}
        media_analysis._annotate_manifest_caps_refusal(manifest)

        self.assertEqual(manifest["caps_refusal_clip_count"], 2)
        error = manifest["error"]
        self.assertEqual(error["code"], "CAPS_REFUSAL")
        self.assertEqual(error["category"], "budget_exhausted")
        self.assertEqual(error["reason"], "over_day_cap")
        self.assertIn("2 of 3", error["message"])

    def test_manifest_no_error_when_no_refusals(self) -> None:
        manifest = {"clips": [{"clip_id": "x", "success": True}], "clip_count": 1}
        media_analysis._annotate_manifest_caps_refusal(manifest)
        self.assertEqual(manifest["caps_refusal_clip_count"], 0)
        self.assertNotIn("error", manifest)


class CapsRefusalThroughCompactTransform(unittest.TestCase):
    """The compact wire transform in server.py must preserve the caps refusal
    surfaces added by _annotate_*. Annotate runs on the un-compacted manifest
    *before* _compact_manifest_for_response is invoked, so anything not in the
    compact whitelist would be silently dropped on the wire.
    """

    def _refusal_vision(self) -> dict:
        return {
            "success": False,
            "status": "caps_exhausted",
            "reason": "over_day_cap",
            "estimated_vision_tokens": 4000,
            "current_usage": {"clip_vision_tokens": 0, "job_vision_tokens": 0, "day_vision_tokens": 0},
            "cap": {"clip": 5000, "job": 50000, "day": 1},
            "headroom": {"clip": 5000, "job": 50000, "day": 1},
            "preset": "minimal",
            "remediation": "Raise the cap via media_analysis.set_caps_preset...",
        }

    def _annotated_manifest(self) -> dict:
        clip_a: dict = {"clip_id": "a", "success": True, "record": {"clip_id": "a"}, "visual": self._refusal_vision()}
        media_analysis._annotate_clip_vision_failure(clip_a, self._refusal_vision())
        manifest = {"clips": [clip_a], "clip_count": 1}
        media_analysis._annotate_manifest_caps_refusal(manifest)
        return manifest

    def test_compact_manifest_preserves_caps_refusal_clip_count_and_error(self) -> None:
        from src import server

        manifest = self._annotated_manifest()
        compact = server._compact_manifest_for_response(manifest, verbose=False)

        self.assertEqual(compact["caps_refusal_clip_count"], 1)
        error = compact["error"]
        self.assertEqual(error["code"], "CAPS_REFUSAL")
        self.assertEqual(error["category"], "budget_exhausted")
        self.assertEqual(error["reason"], "over_day_cap")
        self.assertIn("remediation", error)

    def test_compact_clip_row_preserves_caps_refusal_block(self) -> None:
        from src import server

        manifest = self._annotated_manifest()
        compact = server._compact_manifest_for_response(manifest, verbose=False)
        clip = compact["clips"][0]

        self.assertIsInstance(clip["error"], dict)
        self.assertEqual(clip["error"]["code"], "CAPS_REFUSAL")
        caps_refusal = clip["caps_refusal"]
        self.assertEqual(caps_refusal["preset"], "minimal")
        self.assertEqual(caps_refusal["estimated_vision_tokens"], 4000)
        self.assertEqual(caps_refusal["cap"], {"clip": 5000, "job": 50000, "day": 1})
        self.assertEqual(caps_refusal["headroom"], {"clip": 5000, "job": 50000, "day": 1})

    def test_compact_clip_row_omits_caps_refusal_when_absent(self) -> None:
        from src import server

        clip: dict = {"clip_id": "ok", "success": True, "record": {"clip_id": "ok"}}
        compact = server._compact_clip_row_for_response(clip)
        self.assertNotIn("caps_refusal", compact)


if __name__ == "__main__":
    unittest.main()
