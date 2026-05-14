import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from src.server import _media_analysis_records_from_target
from src.utils.media_analysis import (
    analysis_request_signature,
    build_plan,
    cleanup_artifacts,
    detect_capabilities,
    execute_plan,
    execute_plan_async,
    load_report,
    resolve_output_root,
    summarize_reports,
    stable_clip_directory,
)


class ClipStub:
    def __init__(self, name, clip_id, file_path, media_id=None):
        self.name = name
        self.clip_id = clip_id
        self.file_path = file_path
        self.media_id = media_id or f"media-{clip_id}"

    def GetName(self):
        return self.name

    def GetUniqueId(self):
        return self.clip_id

    def GetMediaId(self):
        return self.media_id

    def GetClipProperty(self, key=""):
        props = {
            "File Path": self.file_path,
            "Type": "Video + Audio",
            "Duration": "00:00:04:00",
            "FPS": "24",
            "Resolution": "1920x1080",
        }
        if key:
            return props.get(key)
        return props


class FolderStub:
    def __init__(self, name, clips=None, subfolders=None):
        self.name = name
        self.clips = clips or []
        self.subfolders = subfolders or []

    def GetName(self):
        return self.name

    def GetUniqueId(self):
        return f"folder-{self.name}"

    def GetClipList(self):
        return self.clips

    def GetSubFolderList(self):
        return self.subfolders


class MediaPoolStub:
    def __init__(self, root, selected=None):
        self.root = root
        self.selected = selected or []

    def GetRootFolder(self):
        return self.root

    def GetSelectedClips(self):
        return self.selected


class MediaAnalysisPlanningTests(unittest.TestCase):
    def _write_synthetic_media(self, source):
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=24:duration=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:duration=2",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-shortest",
            source,
        ]
        subprocess.run(cmd, check=True)

    def test_output_root_uses_davinci_resolve_mcp_name(self):
        out = resolve_output_root(
            project_name="Example Project",
            project_id="project-123",
            source_paths=["/Volumes/ExampleMedia/Camera/A001/clip.mov"],
        )

        self.assertTrue(out["success"])
        self.assertIn("davinci-resolve-mcp-analysis", out["project_root"])
        self.assertIn("example-project", out["project_root"])

    def test_output_root_rejects_source_adjacent_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = os.path.join(tmp, "camera-card")
            os.makedirs(source_dir)
            source = os.path.join(source_dir, "A001_C001.mov")
            out = resolve_output_root(
                project_name="Example Project",
                project_id="project-123",
                analysis_root=source_dir,
                source_paths=[source],
            )

        self.assertFalse(out["success"])
        self.assertIn("source media directory", out["errors"][0])

    def test_stable_clip_directory_sanitizes_clip_name(self):
        dirname = stable_clip_directory({
            "clip_name": "../A001 C001.mov",
            "clip_id": "clip-123",
            "file_path": "/Volumes/ExampleMedia/A001 C001.mov",
        })

        self.assertNotIn("..", dirname)
        self.assertNotIn("/", dirname)
        self.assertTrue(dirname.startswith("a001-c001.mov-"))

    def test_capability_detection_never_installs(self):
        caps = detect_capabilities(env={})

        self.assertTrue(caps["success"])
        self.assertTrue(caps["no_auto_install"])
        self.assertFalse(caps["vision"]["enabled_by_default"])

    def test_build_plan_reports_artifacts_under_project_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source", "A001_C001.mov")
            os.makedirs(os.path.dirname(source))
            records = [{
                "clip_id": "clip-123",
                "clip_name": "A001_C001.mov",
                "file_path": source,
                "media_id": "media-123",
            }]
            plan = build_plan(
                project_name="Example Project",
                project_id="project-123",
                records=records,
                target={"type": "clip", "clip_id": "clip-123"},
                params={"analysis_root": os.path.join(tmp, "analysis"), "depth": "standard"},
                capabilities={
                    "tools": {
                        "ffprobe": {"available": True},
                        "ffmpeg": {"available": True},
                    },
                    "transcription": {"available": False},
                    "vision": {"available": False},
                },
            )

        self.assertTrue(plan["success"])
        artifact = plan["clips"][0]["artifacts"]["analysis_json"]
        self.assertTrue(artifact.startswith(plan["output_root"]["project_root"]))
        self.assertEqual(plan["analysis_keyframe_budget_per_clip"], 8)

    def test_build_plan_allows_chat_context_vision_without_external_provider_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source", "A001_C001.mov")
            os.makedirs(os.path.dirname(source))
            records = [{
                "clip_id": "clip-123",
                "clip_name": "A001_C001.mov",
                "file_path": source,
                "media_id": "media-123",
            }]
            plan = build_plan(
                project_name="Example Project",
                project_id="project-123",
                records=records,
                target={"type": "clip", "clip_id": "clip-123"},
                params={
                    "analysis_root": os.path.join(tmp, "analysis"),
                    "depth": "standard",
                    "vision": {"enabled": True, "provider": "chat_context"},
                },
                capabilities={
                    "tools": {
                        "ffprobe": {"available": True},
                        "ffmpeg": {"available": True},
                    },
                    "transcription": {"available": False},
                    "vision": {"available": False, "provider": None},
                },
            )

        self.assertTrue(plan["success"])
        self.assertEqual(plan["capability_gaps"], [])

    def test_build_plan_hints_when_transcription_available_but_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source", "A001_C001.mov")
            os.makedirs(os.path.dirname(source))
            records = [{
                "clip_id": "clip-123",
                "clip_name": "A001_C001.mov",
                "file_path": source,
                "media_id": "media-123",
            }]
            plan = build_plan(
                project_name="Example Project",
                project_id="project-123",
                records=records,
                target={"type": "clip", "clip_id": "clip-123"},
                params={"analysis_root": os.path.join(tmp, "analysis"), "depth": "standard"},
                capabilities={
                    "tools": {
                        "ffprobe": {"available": True},
                        "ffmpeg": {"available": True},
                    },
                    "transcription": {"available": True, "backends": ["whisper_cli"]},
                    "vision": {"available": False},
                },
            )

        self.assertTrue(plan["success"])
        self.assertTrue(any("Transcription is available but disabled" in note for note in plan["notes"]))

    def test_build_plan_reuses_existing_complete_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source", "A001_C001.mov")
            os.makedirs(os.path.dirname(source))
            open(source, "wb").close()
            record = {
                "clip_id": "clip-123",
                "clip_name": "A001_C001.mov",
                "file_path": source,
                "media_id": "media-123",
            }
            root = resolve_output_root(
                project_name="Example Project",
                project_id="project-123",
                analysis_root=os.path.join(tmp, "analysis"),
                source_paths=[source],
                create=True,
            )["project_root"]
            clip_dir = os.path.join(root, "clips", stable_clip_directory(record))
            os.makedirs(clip_dir)
            report_path = os.path.join(clip_dir, "analysis.json")
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump({
                    "success": True,
                    "source_file": source,
                    "clip": record,
                    "technical": {"format": {"duration_seconds": 1.0}},
                    "readthrough": {"success": True},
                    "motion": {"success": True, "analysis_keyframes": []},
                    "transcription": {"success": True, "status": "skipped"},
                    "visual": {"success": True, "status": "skipped"},
                }, f)
            params = {
                "analysis_root": os.path.join(tmp, "analysis"),
                "depth": "standard",
                "dry_run": False,
            }
            caps = {
                "tools": {
                    "ffprobe": {"available": True},
                    "ffmpeg": {"available": True},
                },
                "transcription": {"available": False},
                "vision": {"available": False},
            }
            plan = build_plan(
                project_name="Example Project",
                project_id="project-123",
                records=[record],
                target={"type": "clip", "clip_id": "clip-123"},
                params=params,
                capabilities=caps,
            )
            manifest = execute_plan(plan, params=params, capabilities=caps)

        self.assertTrue(plan["success"])
        self.assertEqual(plan["reusable_clip_count"], 1)
        self.assertTrue(plan["clips"][0]["skip_execution"])
        self.assertEqual(plan["clips"][0]["existing_report"]["path"], report_path)
        self.assertTrue(manifest["success"])
        self.assertTrue(manifest["clips"][0]["reused"])
        self.assertEqual(manifest["clips"][0]["analysis_json"], report_path)
        self.assertEqual(manifest["clips"][0]["cache_status"], "reusable")

    def test_build_plan_detects_stale_source_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source", "A001_C001.mov")
            os.makedirs(os.path.dirname(source))
            with open(source, "wb") as f:
                f.write(b"current")
            record = {
                "clip_id": "clip-123",
                "clip_name": "A001_C001.mov",
                "file_path": source,
                "media_id": "media-123",
            }
            root = resolve_output_root(
                project_name="Example Project",
                project_id="project-123",
                analysis_root=os.path.join(tmp, "analysis"),
                source_paths=[source],
                create=True,
            )["project_root"]
            clip_dir = os.path.join(root, "clips", stable_clip_directory(record))
            os.makedirs(clip_dir)
            signature = analysis_request_signature(
                record,
                "standard",
                {"transcription": {}, "vision": {}},
                8,
            )
            signature["source_file"]["size_bytes"] = 999
            with open(os.path.join(clip_dir, "analysis.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "success": True,
                    "analysis_version": "0.1",
                    "analysis_signature": signature,
                    "analyzed_at": "2026-05-13T12:00:00Z",
                    "source_file": source,
                    "clip": record,
                    "technical": {"format": {"duration_seconds": 1.0}},
                    "readthrough": {"success": True},
                    "motion": {"success": True, "analysis_keyframes": []},
                    "transcription": {"success": True, "status": "skipped"},
                    "visual": {"success": True, "status": "skipped"},
                }, f)
            plan = build_plan(
                project_name="Example Project",
                project_id="project-123",
                records=[record],
                target={"type": "clip", "clip_id": "clip-123"},
                params={
                    "analysis_root": os.path.join(tmp, "analysis"),
                    "depth": "standard",
                },
                capabilities={
                    "tools": {
                        "ffprobe": {"available": True},
                        "ffmpeg": {"available": True},
                    },
                    "transcription": {"available": False},
                    "vision": {"available": False},
                },
            )

        self.assertTrue(plan["success"])
        self.assertEqual(plan["reusable_clip_count"], 0)
        self.assertEqual(plan["stale_or_incomplete_clip_count"], 1)
        self.assertFalse(plan["clips"][0].get("skip_execution", False))
        self.assertIn("source_size_bytes_changed", plan["clips"][0]["existing_report"]["cache_issues"])

    def test_build_plan_force_refresh_bypasses_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source", "A001_C001.mov")
            os.makedirs(os.path.dirname(source))
            open(source, "wb").close()
            record = {
                "clip_id": "clip-123",
                "clip_name": "A001_C001.mov",
                "file_path": source,
                "media_id": "media-123",
            }
            root = resolve_output_root(
                project_name="Example Project",
                project_id="project-123",
                analysis_root=os.path.join(tmp, "analysis"),
                source_paths=[source],
                create=True,
            )["project_root"]
            clip_dir = os.path.join(root, "clips", stable_clip_directory(record))
            os.makedirs(clip_dir)
            with open(os.path.join(clip_dir, "analysis.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "success": True,
                    "source_file": source,
                    "clip": record,
                    "technical": {"format": {"duration_seconds": 1.0}},
                    "readthrough": {"success": True},
                    "motion": {"success": True, "analysis_keyframes": []},
                    "transcription": {"success": True, "status": "skipped"},
                    "visual": {"success": True, "status": "skipped"},
                }, f)
            plan = build_plan(
                project_name="Example Project",
                project_id="project-123",
                records=[record],
                target={"type": "clip", "clip_id": "clip-123"},
                params={
                    "analysis_root": os.path.join(tmp, "analysis"),
                    "depth": "standard",
                    "force_refresh": True,
                },
                capabilities={
                    "tools": {
                        "ffprobe": {"available": True},
                        "ffmpeg": {"available": True},
                    },
                    "transcription": {"available": False},
                    "vision": {"available": False},
                },
            )

        self.assertTrue(plan["success"])
        self.assertEqual(plan["reusable_clip_count"], 0)
        self.assertEqual(plan["clips"][0]["cache_status"], "refresh_forced")
        self.assertNotIn("existing_report", plan["clips"][0])

    def test_build_plan_does_not_reuse_when_requested_vision_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source", "A001_C001.mov")
            os.makedirs(os.path.dirname(source))
            open(source, "wb").close()
            record = {
                "clip_id": "clip-123",
                "clip_name": "A001_C001.mov",
                "file_path": source,
                "media_id": "media-123",
            }
            root = resolve_output_root(
                project_name="Example Project",
                project_id="project-123",
                analysis_root=os.path.join(tmp, "analysis"),
                source_paths=[source],
                create=True,
            )["project_root"]
            clip_dir = os.path.join(root, "clips", stable_clip_directory(record))
            os.makedirs(clip_dir)
            with open(os.path.join(clip_dir, "analysis.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "success": True,
                    "source_file": source,
                    "clip": record,
                    "technical": {"format": {"duration_seconds": 1.0}},
                    "readthrough": {"success": True},
                    "motion": {"success": True, "analysis_keyframes": []},
                    "transcription": {"success": True, "status": "skipped"},
                    "visual": {"success": True, "status": "skipped"},
                }, f)
            plan = build_plan(
                project_name="Example Project",
                project_id="project-123",
                records=[record],
                target={"type": "clip", "clip_id": "clip-123"},
                params={
                    "analysis_root": os.path.join(tmp, "analysis"),
                    "depth": "standard",
                    "vision": {"enabled": True, "provider": "mock"},
                },
                capabilities={
                    "tools": {
                        "ffprobe": {"available": True},
                        "ffmpeg": {"available": True},
                    },
                    "transcription": {"available": False},
                    "vision": {"available": True, "provider": "mock"},
                },
            )

        self.assertTrue(plan["success"])
        self.assertEqual(plan["reusable_clip_count"], 0)
        self.assertFalse(plan["clips"][0].get("skip_execution", False))
        self.assertEqual(plan["clips"][0]["existing_report"]["missing_layers"], ["vision"])

    def test_bin_target_recurses_and_dedupes_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            path_a = os.path.join(tmp, "A001_C001.mov")
            path_b = os.path.join(tmp, "A001_C002.mov")
            root = FolderStub("Master", clips=[
                ClipStub("A001_C001.mov", "clip-1", path_a),
                ClipStub("A001_C001 duplicate.mov", "clip-2", path_a),
            ], subfolders=[
                FolderStub("Day 01", clips=[ClipStub("A001_C002.mov", "clip-3", path_b)])
            ])
            records, target, warnings, err = _media_analysis_records_from_target(
                MediaPoolStub(root),
                {"target": {"type": "bin", "path": "Master", "recursive": True}},
            )

        self.assertIsNone(err)
        self.assertEqual(target["type"], "bin")
        self.assertEqual(len(records), 2)
        self.assertTrue(any("Deduped 1" in warning for warning in warnings))

    def test_project_string_target_normalizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path_a = os.path.join(tmp, "A001_C001.mov")
            root = FolderStub("Master", clips=[ClipStub("A001_C001.mov", "clip-1", path_a)])
            records, target, warnings, err = _media_analysis_records_from_target(
                MediaPoolStub(root),
                {"target": "project"},
            )

        self.assertIsNone(err)
        self.assertEqual(warnings, [])
        self.assertEqual(target["type"], "project")
        self.assertTrue(target["recursive"])
        self.assertEqual(len(records), 1)

    def test_selected_string_target_normalizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path_a = os.path.join(tmp, "A001_C001.mov")
            selected = ClipStub("A001_C001.mov", "clip-1", path_a)
            records, target, warnings, err = _media_analysis_records_from_target(
                MediaPoolStub(FolderStub("Master"), selected=[selected]),
                {"target": "selected"},
            )

        self.assertIsNone(err)
        self.assertEqual(warnings, [])
        self.assertEqual(target["type"], "clip")
        self.assertTrue(target["selected"])
        self.assertEqual(len(records), 1)

    def test_invalid_scalar_target_returns_clean_error(self):
        records, target, warnings, err = _media_analysis_records_from_target(
            None,
            {"target": 123},
        )

        self.assertIsNone(records)
        self.assertEqual(warnings, [])
        self.assertIn("_invalid_target", target)
        self.assertIn("error", err)

    def test_execute_standard_pipeline_with_synthetic_media(self):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("ffmpeg/ffprobe not installed")
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = os.path.join(tmp, "source")
            analysis_dir = os.path.join(tmp, "davinci-resolve-mcp-analysis")
            os.makedirs(source_dir)
            source = os.path.join(source_dir, "synthetic_motion.mp4")
            self._write_synthetic_media(source)

            records = [{
                "clip_id": "clip-motion",
                "clip_name": "synthetic_motion.mp4",
                "file_path": source,
                "media_id": "media-motion",
            }]
            params = {
                "analysis_root": analysis_dir,
                "depth": "standard",
                "dry_run": False,
                "max_analysis_frames": 4,
                "transcription": {
                    "enabled": True,
                    "backend": "mock",
                    "segments": [{"start": 0, "end": 1.5, "text": "Synthetic tone."}],
                },
                "vision": {"enabled": True, "provider": "mock"},
            }
            caps = detect_capabilities(env={"DAVINCI_RESOLVE_MCP_VISION_PROVIDER": "mock"})
            plan = build_plan(
                project_name="Example Project",
                project_id="project-123",
                records=records,
                target={"type": "file", "path": source},
                params=params,
                capabilities=caps,
            )
            manifest = execute_plan(plan, params=params, capabilities=caps)
            summary = summarize_reports(plan["output_root"]["project_root"])
            report = load_report(plan["output_root"]["project_root"])
            self.assertTrue(plan["success"])
            self.assertEqual(plan["capability_gaps"], [])
            self.assertTrue(manifest["success"])
            self.assertEqual(manifest["successful_clip_count"], 1)
            artifacts = manifest["clips"][0]["artifacts"]
            self.assertTrue(os.path.exists(artifacts["analysis_json"]))
            self.assertTrue(os.path.exists(artifacts["technical_json"]))
            self.assertTrue(os.path.exists(artifacts["motion_json"]))
            self.assertTrue(os.path.exists(artifacts["transcript_json"]))
            self.assertTrue(os.path.exists(artifacts["transcript_srt"]))
            self.assertTrue(os.path.exists(artifacts["visual_json"]))
            self.assertTrue(summary["success"])
            self.assertEqual(summary["clip_reports"], 1)
            self.assertTrue(report["success"])
            cleanup = cleanup_artifacts(plan["output_root"]["project_root"])
            self.assertTrue(cleanup["success"])
            self.assertEqual(sorted(os.listdir(source_dir)), ["synthetic_motion.mp4"])

    def test_execute_session_pipeline_returns_reports_and_cleans_artifacts(self):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("ffmpeg/ffprobe not installed")
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = os.path.join(tmp, "source")
            session_root = os.path.join(tmp, "session-analysis")
            os.makedirs(source_dir)
            source = os.path.join(source_dir, "synthetic_session.mp4")
            self._write_synthetic_media(source)

            records = [{
                "clip_id": "clip-session",
                "clip_name": "synthetic_session.mp4",
                "file_path": source,
                "media_id": "media-session",
            }]
            params = {
                "analysis_root": session_root,
                "depth": "standard",
                "dry_run": False,
                "session_only": True,
                "cleanup_frames": True,
                "max_analysis_frames": 4,
                "transcription": {
                    "enabled": True,
                    "backend": "mock",
                    "segments": [{"start": 0, "end": 1.0, "text": "Session transcript."}],
                },
                "vision": {"enabled": True, "provider": "mock"},
            }
            caps = detect_capabilities(env={"DAVINCI_RESOLVE_MCP_VISION_PROVIDER": "mock"})
            plan = build_plan(
                project_name="Example Project",
                project_id="project-session",
                records=records,
                target={"type": "file", "path": source},
                params=params,
                capabilities=caps,
            )
            manifest = execute_plan(plan, params=params, capabilities=caps)

            self.assertTrue(plan["success"])
            self.assertTrue(manifest["success"])
            self.assertTrue(manifest["session_only"])
            self.assertFalse(manifest["persistent"])
            self.assertTrue(manifest["artifacts_cleaned_up"])
            self.assertEqual(manifest["successful_clip_count"], 1)
            self.assertEqual(len(manifest["reports"]), 1)
            self.assertEqual(manifest["reports"][0]["clip"]["clip_id"], "clip-session")
            self.assertEqual(manifest["project_summary"]["clip_reports"], 1)
            self.assertFalse(os.path.exists(plan["output_root"]["project_root"]))
            self.assertEqual(sorted(os.listdir(source_dir)), ["synthetic_session.mp4"])

    def test_execute_chat_context_vision_runner_writes_structured_visual_report(self):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("ffmpeg/ffprobe not installed")
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = os.path.join(tmp, "source")
            analysis_dir = os.path.join(tmp, "davinci-resolve-mcp-analysis")
            os.makedirs(source_dir)
            source = os.path.join(source_dir, "synthetic_chat_context.mp4")
            self._write_synthetic_media(source)

            records = [{
                "clip_id": "clip-chat-context",
                "clip_name": "synthetic_chat_context.mp4",
                "file_path": source,
                "media_id": "media-chat-context",
            }]
            params = {
                "analysis_root": analysis_dir,
                "depth": "standard",
                "dry_run": False,
                "session_only": True,
                "cleanup_frames": True,
                "max_analysis_frames": 3,
                "vision": {"enabled": True, "provider": "chat_context"},
            }
            caps = detect_capabilities(env={})
            plan = build_plan(
                project_name="Example Project",
                project_id="project-chat-context",
                records=records,
                target={"type": "file", "path": source},
                params=params,
                capabilities=caps,
            )

            async def fake_runner(record, motion, options, artifacts, capabilities):
                self.assertTrue(any(row.get("frame_path") for row in motion["analysis_keyframes"]))
                return {
                    "success": True,
                    "provider": "chat_context",
                    "clip_summary": "Synthetic chat-context visual report.",
                    "editorial_classification": {
                        "primary_use": "unknown",
                        "select_potential": "medium",
                        "reason": "Test runner supplied structured analysis.",
                    },
                    "content": {
                        "locations": [],
                        "people_visible": "none",
                        "actions": ["test pattern"],
                        "objects": [],
                        "visible_text": [],
                        "notable_audio_context": [],
                    },
                    "shot_and_style": {
                        "shot_sizes": [],
                        "camera_motion": ["computed"],
                        "composition_notes": "",
                        "lighting_mood": "",
                        "color_mood": "",
                    },
                    "motion": {
                        "overall_level": motion.get("overall_motion_level"),
                        "motion_events": [],
                        "quiet_regions": [],
                    },
                    "analysis_keyframes": [],
                    "editing_notes": {
                        "best_moments": [],
                        "continuity_flags": [],
                        "qc_flags": [],
                        "search_tags": ["chat-context"],
                    },
                    "confidence": {
                        "visual": "medium",
                        "motion": "computed",
                        "transcript": "unavailable",
                    },
                }

            manifest = asyncio.run(execute_plan_async(
                plan,
                params=params,
                capabilities=caps,
                vision_runner=fake_runner,
            ))

            self.assertTrue(manifest["success"])
            self.assertTrue(manifest["artifacts_cleaned_up"])
            self.assertEqual(manifest["reports"][0]["visual"]["provider"], "chat_context")
            self.assertEqual(manifest["reports"][0]["visual"]["editing_notes"]["search_tags"], ["chat-context"])
            self.assertFalse(os.path.exists(plan["output_root"]["project_root"]))
            self.assertEqual(sorted(os.listdir(source_dir)), ["synthetic_chat_context.mp4"])


if __name__ == "__main__":
    unittest.main()
