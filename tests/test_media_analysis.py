import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest

from src.server import (
    _apply_media_analysis_clip_markers,
    _apply_sync_event_markers,
    _media_analysis_apply_setup_defaults,
    _media_analysis_effective_preferences,
    _media_analysis_merge_metadata_field,
    _media_analysis_marker_candidates_from_report,
    _media_analysis_publish_confirmed,
    _media_analysis_timed_marker_decision,
    _media_analysis_provenance_metadata,
    _media_analysis_records_from_target,
    _media_analysis_report_metadata_candidates,
    setup,
)
from src.analysis_dashboard import DashboardState, discover_project_contexts
from src.utils import update_check
from src.utils.media_analysis import (
    analysis_request_signature,
    analysis_index_status,
    build_analysis_index,
    build_plan,
    cleanup_artifacts,
    _cut_boundary_analysis,
    detect_capabilities,
    execute_plan,
    execute_plan_async,
    load_report,
    query_analysis_index,
    resolve_output_root,
    _sample_times,
    summarize_reports,
    stable_clip_directory,
)
from src.utils.media_analysis_jobs import (
    batch_job_status,
    cancel_batch_job,
    create_batch_job,
    create_batch_job_from_paths,
    list_batch_jobs,
    resume_batch_job,
    run_batch_job_slice,
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


class MarkerClipStub:
    def __init__(self, clip_id="clip-123"):
        self.clip_id = clip_id
        self.markers = {}

    def GetUniqueId(self):
        return self.clip_id

    def AddMarker(self, frame, color, name, note, duration, custom_data=""):
        self.markers[frame] = {
            "color": color,
            "name": name,
            "note": note,
            "duration": duration,
            "customData": custom_data,
        }
        return True

    def GetMarkers(self):
        return self.markers


class MarkerFolderStub:
    def __init__(self, clips):
        self.clips = clips

    def GetClipList(self):
        return self.clips

    def GetSubFolderList(self):
        return []


class MarkerMediaPoolStub:
    def __init__(self, clips):
        self.root = MarkerFolderStub(clips)

    def GetRootFolder(self):
        return self.root


class MarkerProjectStub:
    def __init__(self, clips):
        self.media_pool = MarkerMediaPoolStub(clips)

    def GetMediaPool(self):
        return self.media_pool


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


class TimelineItemStub:
    def __init__(self, name, item_id, clip, start=0, end=24, source_start=0):
        self.name = name
        self.item_id = item_id
        self.clip = clip
        self.start = start
        self.end = end
        self.source_start = source_start

    def GetName(self):
        return self.name

    def GetUniqueId(self):
        return self.item_id

    def GetStart(self):
        return self.start

    def GetEnd(self):
        return self.end

    def GetDuration(self):
        return self.end - self.start

    def GetSourceStartFrame(self):
        return self.source_start

    def GetMediaPoolItem(self):
        return self.clip


class TimelineStub:
    def __init__(self, video_tracks=None, audio_tracks=None):
        self.tracks = {
            "video": video_tracks or {},
            "audio": audio_tracks or {},
            "subtitle": {},
        }

    def GetName(self):
        return "Edit Timeline"

    def GetUniqueId(self):
        return "timeline-123"

    def GetTrackCount(self, track_type):
        return max(self.tracks.get(track_type, {}).keys() or [0])

    def GetItemListInTrack(self, track_type, track_index):
        return self.tracks.get(track_type, {}).get(track_index, [])


class TimelineProjectStub:
    def __init__(self, timeline):
        self.timeline = timeline

    def GetCurrentTimeline(self):
        return self.timeline


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

    def test_cut_boundary_analysis_flags_flash_candidates_and_samples_boundaries(self):
        cut_analysis = _cut_boundary_analysis(
            10.0,
            [
                {"time_seconds": 2.0},
                {"time_seconds": 2.1},
                {"time_seconds": 6.0},
            ],
            24.0,
        )

        self.assertTrue(cut_analysis["success"])
        self.assertEqual(cut_analysis["cut_count"], 3)
        self.assertTrue(cut_analysis["likely_edited_sequence"])
        self.assertGreaterEqual(len(cut_analysis["flash_frame_candidates"]), 1)
        self.assertEqual(cut_analysis["flash_frame_candidates"][0]["reason"], "adjacent scene detections bound a very short segment")

        samples = _sample_times(
            10.0,
            [{"time_seconds": 2.0}, {"time_seconds": 2.1}, {"time_seconds": 6.0}],
            8,
            fps=24.0,
            cut_analysis=cut_analysis,
        )
        reasons = {row["selection_reason"] for row in samples}
        self.assertIn("flash_candidate", reasons)
        self.assertIn("cut_before", reasons)
        self.assertIn("cut_after", reasons)

    def test_output_root_uses_davinci_resolve_mcp_name(self):
        out = resolve_output_root(
            project_name="Example Project",
            project_id="project-123",
            source_paths=["/Volumes/ExampleMedia/Camera/A001/clip.mov"],
        )

        self.assertTrue(out["success"])
        self.assertIn("davinci-resolve-mcp-analysis", out["project_root"])
        self.assertIn("example-project", out["project_root"])

    def test_dashboard_context_switch_scopes_active_project_root_and_related_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            analysis_root = os.path.join(tmp, "analysis")
            previous = resolve_output_root(
                project_name="Example Project",
                project_id="version-001",
                analysis_root=analysis_root,
                create=True,
            )["project_root"]
            state = DashboardState("Example Project", "version-002", analysis_root)
            projects = discover_project_contexts(state.base_analysis_root, state.context())

            self.assertIn(previous, projects["related_project_roots"])
            self.assertIn(state.project_root, projects["related_project_roots"])

            switched = state.set_context({"project_root": previous, "project_name": "Example Project"})

        self.assertTrue(switched["success"])
        self.assertEqual(switched["active"]["project_root"], previous)
        self.assertEqual(state.project_root, previous)

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

    def test_publish_metadata_candidates_map_visual_report_to_resolve_fields(self):
        report = {
            "analysis_version": "0.1",
            "summary": "Fallback summary",
            "clip": {"clip_id": "clip-123", "clip_name": "A001_C001.mov"},
            "technical_warnings": ["interlace analysis did not complete"],
            "analysis_signature": {"signature_hash": "abc123"},
            "visual": {
                "clip_summary": "Interview shot with Taylor at the kitchen table.",
                "editorial_classification": {
                    "primary_use": "interview",
                    "select_potential": "high",
                    "reason": "Clean eye-line and usable delivery.",
                },
                "content": {
                    "people": ["Taylor"],
                    "actions": ["speaking"],
                    "objects": ["coffee mug"],
                    "visible_text": ["Scene 12A Take 3"],
                },
                "slate": {
                    "slate_visible": True,
                    "visible_text": ["Scene 12A Take 3"],
                    "confidence": {"overall": "medium"},
                },
                "editing_notes": {
                    "best_moments": ["00:00:04 strong answer"],
                    "qc_flags": ["minor background noise"],
                    "search_tags": ["kitchen", "answer"],
                },
            },
        }
        detection = {
            "files": [{
                "clip_id": "clip-123",
                "events": [{"type": "slate_clap", "time_seconds": 4.0, "frame": 96, "confidence": 0.91}],
            }],
        }

        proposal = _media_analysis_report_metadata_candidates(report, detection=detection)

        self.assertEqual(proposal["fields"]["Description"], "Interview shot with Taylor at the kitchen table.")
        self.assertIn("kitchen", proposal["fields"]["Keywords"])
        self.assertIn("slate clap", proposal["fields"]["Keywords"])
        self.assertEqual(proposal["fields"]["People"], ["Taylor"])
        self.assertIn("Confirmed slate clap", proposal["fields"]["Comments"])
        self.assertIn("minor background noise", proposal["fields"]["Comments"])

    def test_publish_metadata_candidates_require_visual_confirmation_for_slate(self):
        report = {
            "analysis_version": "0.1",
            "summary": "Fallback summary",
            "clip": {"clip_id": "clip-123", "clip_name": "A001_C001.mov"},
            "visual": {
                "success": True,
                "clip_summary": "Wide shot in a driveway.",
                "content": {"actions": ["walking"]},
                "editing_notes": {"search_tags": ["driveway"]},
            },
        }
        detection = {
            "files": [{
                "clip_id": "clip-123",
                "events": [{"type": "slate_clap", "time_seconds": 4.0, "frame": 96, "confidence": 0.91}],
            }],
        }

        audio_only = _media_analysis_report_metadata_candidates(report, detection=detection)
        self.assertNotIn("slate clap", audio_only["fields"]["Keywords"])
        self.assertNotIn("slate clap", audio_only["fields"]["Comments"])
        self.assertFalse(audio_only["evidence"]["slate_visual_confirmed"])

        confirmed = _media_analysis_report_metadata_candidates(
            report,
            detection=detection,
            slate_review={"slate_visible": True, "confidence": {"overall": "high"}},
        )
        self.assertIn("slate clap", confirmed["fields"]["Keywords"])
        self.assertIn("Confirmed slate clap", confirmed["fields"]["Comments"])
        self.assertTrue(confirmed["evidence"]["slate_visual_confirmed"])

    def test_publish_metadata_candidates_require_visual_summary_when_requested(self):
        report = {
            "analysis_version": "0.1",
            "summary": "Fallback summary",
            "clip": {"clip_id": "clip-123", "clip_name": "A001_C001.mov"},
            "visual": {
                "success": False,
                "status": "skipped",
                "reason": "Sampling unavailable.",
            },
        }

        proposal = _media_analysis_report_metadata_candidates(
            report,
            fields=["Description", "Comments"],
            require_visual_description=True,
        )

        self.assertNotIn("Description", proposal["fields"])
        self.assertNotIn("Comments", proposal["fields"])
        self.assertFalse(proposal["evidence"]["visual_analysis_succeeded"])

    def test_publish_metadata_candidates_do_not_put_transcript_in_comments(self):
        report = {
            "analysis_version": "0.1",
            "clip": {"clip_id": "clip-123", "clip_name": "A001_C001.mov"},
            "visual": {
                "success": True,
                "clip_summary": "Interview close-up with a clean answer.",
                "content": {"people": ["Taylor"]},
            },
            "transcription": {
                "success": True,
                "backend": "mock",
                "language": "en",
                "text": "This is the readable answer that should appear in metadata comments.",
                "segments": [
                    {"start": 0.0, "end": 1.2, "text": "This is the readable answer."},
                    {"start": 1.2, "end": 2.4, "text": "It should appear in metadata comments."},
                ],
            },
        }

        proposal = _media_analysis_report_metadata_candidates(report, fields=["Description", "Comments", "People"])

        self.assertEqual(proposal["fields"]["Description"], "Interview close-up with a clean answer.")
        self.assertNotIn("Transcript excerpt", proposal["fields"]["Comments"])
        self.assertNotIn("readable answer", proposal["fields"]["Comments"])
        self.assertEqual(proposal["fields"]["People"], ["Taylor"])

    def test_publish_metadata_candidates_gate_slate_fields_by_confidence(self):
        report = {
            "clip": {"clip_id": "clip-123"},
            "visual": {"clip_summary": "Slate shot."},
        }
        fields = ["Scene", "Shot", "Take", "Camera #"]
        low = _media_analysis_report_metadata_candidates(
            report,
            fields=fields,
            slate_review={
                "slate_visible": True,
                "fields": {"scene": "12A", "take": "3", "camera": "B"},
                "confidence": {"overall": "medium"},
            },
        )
        high = _media_analysis_report_metadata_candidates(
            report,
            fields=fields,
            slate_review={
                "slate_visible": True,
                "fields": {"scene": "12A", "take": "3", "camera": "B"},
                "confidence": {"overall": "high"},
            },
        )

        self.assertEqual(low["fields"]["Scene"], "")
        self.assertEqual(high["fields"]["Scene"], "12A")
        self.assertEqual(high["fields"]["Take"], "3")
        self.assertEqual(high["fields"]["Camera #"], "B")

    def test_publish_metadata_candidates_support_metadata_write_alias_fields(self):
        report = {
            "clip": {"clip_id": "clip-123"},
            "visual": {
                "clip_summary": "Slate shot.",
                "content": {"actions": ["clap"]},
                "editing_notes": {"search_tags": ["sync"]},
            },
        }
        proposal = _media_analysis_report_metadata_candidates(
            report,
            fields=["Keyword", "Roll Card #"],
            slate_review={
                "slate_visible": True,
                "fields": {"roll": "A001"},
                "confidence": {"overall": "high"},
            },
        )

        self.assertIn("sync", proposal["fields"]["Keyword"])
        self.assertEqual(proposal["fields"]["Roll Card #"], "A001")

    def test_publish_metadata_marker_writeback_is_opt_in_and_source_framed(self):
        report = {
            "clip": {"clip_id": "clip-123"},
            "visual": {
                "editing_notes": {
                    "best_moments": ["00:00:04 strong answer"],
                    "qc_flags": ["00:00:05:12 small audio pop"],
                },
            },
        }
        record = {"clip_id": "clip-123", "fps": "24"}
        sync_event = {"type": "slate_clap", "time_seconds": 1.25, "frame": 30, "confidence": 0.91}

        disabled = _media_analysis_marker_candidates_from_report(
            report,
            record,
            sync_event,
            None,
            {"timed_markers": "no"},
            slate_review={"slate_visible": True, "confidence": {"overall": "high"}},
        )
        unconfirmed = _media_analysis_marker_candidates_from_report(report, record, sync_event, "/tmp/report.json", {"write_markers": True})
        enabled = _media_analysis_marker_candidates_from_report(
            report,
            record,
            sync_event,
            "/tmp/report.json",
            {"write_markers": True},
            slate_review={"slate_visible": True, "confidence": {"overall": "high"}},
        )

        self.assertFalse(disabled["enabled"])
        self.assertEqual([marker["name"] for marker in unconfirmed["markers"]], ["Best Moment", "QC Warning"])
        self.assertEqual(unconfirmed["skipped"][0]["reason"], "slate_not_visually_confirmed")
        self.assertTrue(enabled["enabled"])
        self.assertEqual([marker["frame"] for marker in enabled["markers"]], [30, 96, 132])
        self.assertEqual(enabled["markers"][0]["name"], "Slate Clap")
        self.assertFalse(_media_analysis_publish_confirmed({"write_markers": True, "dry_run": False}))

        clip = MarkerClipStub()
        applied = _apply_media_analysis_clip_markers(clip, enabled["markers"], {})
        self.assertTrue(applied["success"])
        self.assertEqual(len(clip.GetMarkers()), 3)

    def test_sync_event_marker_write_requires_visual_slate_confirmation(self):
        clip = MarkerClipStub("clip-123")
        project = MarkerProjectStub([clip])
        slate_suggestion = {
            "scope": "media_pool_item",
            "clip_id": "clip-123",
            "clip_name": "A001_C001.mov",
            "event_type": "slate_clap",
            "event_time_seconds": 1.0,
            "event_frame": 24,
            "confidence": 0.95,
            "eligible": True,
            "requires_confirmation": True,
            "marker": {
                "frame": 24,
                "color": "Cyan",
                "name": "Sync: slate clap",
                "note": "Detected slate clap at 1.0s.",
                "duration": 1,
                "custom_data": "mcp.sync_event:clip-123:slate_clap:24",
            },
        }
        detection = {"files": [{"marker_suggestions": [slate_suggestion]}]}

        unconfirmed = _apply_sync_event_markers(project, detection, {"confirm": True})
        self.assertTrue(unconfirmed["success"])
        self.assertEqual(unconfirmed["added"], 0)
        self.assertEqual(unconfirmed["skipped"][0]["reason"], "slate_not_visually_confirmed")
        self.assertEqual(clip.GetMarkers(), {})

        confirmed_suggestion = dict(slate_suggestion)
        confirmed_suggestion["slate_review"] = {"slate_visible": True, "confidence": {"overall": "high"}}
        confirmed = _apply_sync_event_markers(
            project,
            {"files": [{"marker_suggestions": [confirmed_suggestion]}]},
            {"confirm": True},
        )
        self.assertTrue(confirmed["success"])
        self.assertEqual(confirmed["added"], 1)
        self.assertIn(24, clip.GetMarkers())

    def test_timed_marker_prompt_choices_and_defaults_are_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.environ.get("DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS")
            os.environ["DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS"] = os.path.join(tmp, "prefs.json")
            try:
                prompt = _media_analysis_timed_marker_decision({})
                self.assertTrue(prompt["prompt_required"])
                self.assertFalse(prompt["enabled"])

                yes = _media_analysis_timed_marker_decision({"timed_markers": "yes"})
                self.assertFalse(yes["prompt_required"])
                self.assertTrue(yes["enabled"])

                default_yes = _media_analysis_timed_marker_decision({"timed_markers": "default_yes"})
                self.assertTrue(default_yes["enabled"])
                self.assertEqual(default_yes["saved_default"], "yes")

                saved = _media_analysis_timed_marker_decision({})
                self.assertFalse(saved["prompt_required"])
                self.assertTrue(saved["enabled"])
                self.assertEqual(saved["source"], "saved_default")

                default_no = _media_analysis_timed_marker_decision({"timed_markers": "default_no"})
                self.assertFalse(default_no["enabled"])
                self.assertEqual(default_no["saved_default"], "no")
            finally:
                if previous is None:
                    os.environ.pop("DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS", None)
                else:
                    os.environ["DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS"] = previous

    def test_setup_tool_sets_conversation_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous_analysis = os.environ.get("DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS")
            previous_updates = os.environ.get(update_check.ENV_STATE_PATH)
            os.environ["DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS"] = os.path.join(tmp, "analysis-prefs.json")
            os.environ[update_check.ENV_STATE_PATH] = os.path.join(tmp, "update-state.json")
            try:
                configured = setup("set_defaults", {
                    "defaults": {
                        "media_analysis": {
                            "timed_markers_default": "default_yes",
                            "slate_detection_default": "yes",
                            "vision_default": "technical_only",
                            "transcription_default": "no",
                            "analysis_persistence": "keep_reports",
                            "metadata_publish_fields": ["Description", "Comments", "Scene"],
                            "metadata_overwrite_policy": "fill_empty",
                            "timed_marker_types": ["best_moments"],
                            "timed_marker_colors": {"best_moments": "Pink"},
                            "max_timed_markers_per_clip": 2,
                            "include_confidence_scores": False,
                            "include_source_time_notes": False,
                            "analysis_summary_style": "qc",
                            "report_format": "full",
                            "preferred_analysis_root": os.path.join(tmp, "analysis"),
                            "preferred_generated_media_folder": os.path.join(tmp, "generated"),
                            "default_post_operation_page": "edit",
                            "marker_custom_data": "minimal",
                            "ask_before_metadata_publish": True,
                            "dry_run_first_default": False,
                        },
                        "updates": {"mode": "notify", "check_interval_hours": 6, "snooze_hours": 3},
                    },
                })
                self.assertTrue(configured["success"])
                self.assertEqual(configured["defaults"]["media_analysis"]["timed_markers_default"], "yes")
                self.assertEqual(configured["defaults"]["media_analysis"]["slate_detection_default"], "yes")
                self.assertEqual(configured["defaults"]["media_analysis"]["vision_default"], "technical_only")
                self.assertEqual(configured["defaults"]["media_analysis"]["analysis_persistence"], "keep_reports")
                self.assertEqual(configured["defaults"]["media_analysis"]["metadata_publish_fields"], ["Description", "Comments", "Scene"])
                self.assertEqual(configured["defaults"]["media_analysis"]["metadata_overwrite_policy"], "fill_empty")
                self.assertEqual(configured["defaults"]["media_analysis"]["timed_marker_types"], ["best_moments"])
                self.assertEqual(configured["defaults"]["media_analysis"]["timed_marker_colors"]["best_moments"], "Pink")
                self.assertEqual(configured["defaults"]["media_analysis"]["max_timed_markers_per_clip"], 2)
                self.assertFalse(configured["defaults"]["media_analysis"]["include_confidence_scores"])
                self.assertEqual(configured["defaults"]["updates"]["mode"], "notify")
                self.assertEqual(configured["defaults"]["updates"]["check_interval_hours"], 6)
                self.assertEqual(configured["defaults"]["updates"]["snooze_hours"], 3)

                applied = _media_analysis_apply_setup_defaults("publish_clip_metadata", {"confirm": True})
                self.assertEqual(applied["fields"], ["Description", "Comments", "Scene"])
                self.assertEqual(applied["merge_policy"], "fill_empty")
                self.assertFalse(applied["dry_run"])
                self.assertEqual(applied["slate_detection"]["enabled"], True)
                self.assertEqual(applied["vision"]["enabled"], False)

                report = {
                    "clip": {"clip_id": "clip-123"},
                    "visual": {"editing_notes": {"best_moments": ["00:00:04 strong answer"], "qc_flags": ["00:00:05:12 pop"]}},
                }
                markers = _media_analysis_marker_candidates_from_report(report, {"clip_id": "clip-123", "fps": "24"}, {"frame": 12, "confidence": 0.8}, "/tmp/report.json", applied)
                self.assertEqual(len(markers["markers"]), 1)
                self.assertEqual(markers["markers"][0]["name"], "Best Moment")
                self.assertEqual(markers["markers"][0]["color"], "Pink")
                self.assertNotIn("analysis_report_path", markers["markers"][0]["custom_data"])

                cleared = setup("clear_defaults", {
                    "keys": ["media_analysis", "updates.mode", "updates.check_interval_hours", "updates.snooze_hours"],
                })
                self.assertTrue(cleared["success"])
                self.assertIsNone(cleared["defaults"]["media_analysis"]["timed_markers_default"])
                self.assertEqual(cleared["defaults"]["media_analysis"]["vision_default"], _media_analysis_effective_preferences()["vision_default"])
                self.assertEqual(cleared["defaults"]["updates"]["mode"], "prompt")
                self.assertEqual(cleared["defaults"]["updates"]["check_interval_hours"], 24.0)
                self.assertEqual(cleared["defaults"]["updates"]["snooze_hours"], 24.0)

                unknown = setup("set_defaults", {"defaults": {"not_a_real_default": True}})
                self.assertIn("error", unknown)
            finally:
                if previous_analysis is None:
                    os.environ.pop("DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS", None)
                else:
                    os.environ["DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS"] = previous_analysis
                if previous_updates is None:
                    os.environ.pop(update_check.ENV_STATE_PATH, None)
                else:
                    os.environ[update_check.ENV_STATE_PATH] = previous_updates

    def test_unlimited_timed_marker_limit_keeps_all_candidates(self):
        report = {
            "visual": {
                "editing_notes": {
                    "best_moments": [
                        "00:00:01 strong answer",
                        "00:00:02 useful reaction",
                        "00:00:03 clean transition",
                    ]
                }
            }
        }
        markers = _media_analysis_marker_candidates_from_report(
            report,
            {"clip_id": "clip-123", "fps": "24"},
            None,
            "/tmp/report.json",
            {"markers": {"marker_types": ["best_moments"], "max_markers": 0}},
        )
        self.assertEqual(len(markers["markers"]), 3)
        self.assertFalse([item for item in markers["skipped"] if item.get("reason") == "max_markers_reached"])

    def test_publish_metadata_merge_updates_owned_blocks_and_dedupes_lists(self):
        comments = _media_analysis_merge_metadata_field(
            "Comments",
            "Assistant note\n\n[DaVinci Resolve MCP Analysis]\nold\n[/DaVinci Resolve MCP Analysis]",
            "Summary: new analysis",
            {},
        )
        keywords = _media_analysis_merge_metadata_field(
            "Keywords",
            "kitchen, interview",
            ["Interview", "answer"],
            {},
        )
        scene = _media_analysis_merge_metadata_field("Scene", "12B", "12A", {})

        self.assertTrue(comments["changed"])
        self.assertIn("Assistant note", comments["value"])
        self.assertIn("Summary: new analysis", comments["value"])
        self.assertEqual(keywords["value"], "kitchen, interview, answer")
        self.assertEqual(keywords["added"], ["answer"])
        self.assertFalse(scene["changed"])
        self.assertEqual(scene["reason"], "preserved_existing_fill_empty_field")

    def test_publish_metadata_provenance_uses_namespaced_third_party_keys(self):
        provenance = _media_analysis_provenance_metadata(
            {
                "analysis_version": "0.1",
                "analysis_signature": {"signature_hash": "abc123"},
            },
            "/tmp/analysis.json",
            ["Description", "Keywords"],
        )

        self.assertEqual(provenance["davinci_resolve_mcp.analysis_signature"], "abc123")
        self.assertEqual(provenance["davinci_resolve_mcp.analysis_report_path"], "/tmp/analysis.json")
        self.assertIn("Description", provenance["davinci_resolve_mcp.changed_fields"])

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
        marker_artifact = plan["clips"][0]["artifacts"]["marker_plan_json"]
        self.assertTrue(marker_artifact.startswith(plan["output_root"]["project_root"]))
        self.assertTrue(marker_artifact.endswith("clip_analysis_markers.json"))
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
                    "readthrough": {"success": True, "cut_analysis": {"success": True}},
                    "motion": {"success": True, "analysis_keyframes": []},
                    "transcription": {"success": True, "status": "skipped"},
                    "visual": {"success": True, "status": "skipped"},
                    "clip_analysis_markers": {"success": True, "marker_count": 1, "markers": []},
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
                    "readthrough": {"success": True, "cut_analysis": {"success": True}},
                    "motion": {"success": True, "analysis_keyframes": []},
                    "transcription": {"success": True, "status": "skipped"},
                    "visual": {"success": True, "status": "skipped"},
                    "clip_analysis_markers": {"success": True, "marker_count": 1, "markers": []},
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

    def test_build_plan_reuses_report_from_same_name_project_version_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source", "A001_C001.mov")
            os.makedirs(os.path.dirname(source))
            with open(source, "wb") as handle:
                handle.write(b"current")
            record = {
                "clip_id": "clip-current-version",
                "clip_name": "A001_C001.mov",
                "file_path": source,
                "media_id": "media-current-version",
            }
            analysis_root = os.path.join(tmp, "analysis")
            previous_root = resolve_output_root(
                project_name="Example Project",
                project_id="version-001",
                analysis_root=analysis_root,
                source_paths=[source],
                create=True,
            )["project_root"]
            active_root = resolve_output_root(
                project_name="Example Project",
                project_id="version-002",
                analysis_root=analysis_root,
                source_paths=[source],
                create=False,
            )["project_root"]
            clip_dir = os.path.join(previous_root, "clips", stable_clip_directory(record))
            os.makedirs(clip_dir)
            signature = analysis_request_signature(record, "standard", {"transcription": {}, "vision": {}}, 8)
            with open(os.path.join(clip_dir, "analysis.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "success": True,
                    "analysis_version": "0.1",
                    "analysis_signature": signature,
                    "analyzed_at": "2026-05-17T12:00:00Z",
                    "source_file": source,
                    "clip": record,
                    "technical": {"format": {"duration_seconds": 1.0}},
                    "readthrough": {"success": True, "cut_analysis": {"success": True}},
                    "motion": {"success": True, "analysis_keyframes": []},
                    "transcription": {"success": True, "status": "skipped"},
                    "visual": {"success": True, "status": "skipped"},
                    "clip_analysis_markers": {"success": True, "marker_count": 1, "markers": []},
                }, handle)

            plan = build_plan(
                project_name="Example Project",
                project_id="version-002",
                records=[record],
                target={"type": "clips", "clip_ids": ["clip-current-version"]},
                params={
                    "analysis_root": analysis_root,
                    "depth": "standard",
                    "reuse_project_roots": [previous_root],
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
        self.assertEqual(plan["output_root"]["project_root"], active_root)
        self.assertEqual(plan["reusable_clip_count"], 1)
        self.assertTrue(plan["clips"][0]["skip_execution"])
        self.assertEqual(plan["clips"][0]["existing_report"]["project_root"], previous_root)
        self.assertTrue(plan["clips"][0]["artifacts"]["analysis_json"].startswith(active_root))

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
                    "readthrough": {"success": True, "cut_analysis": {"success": True}},
                    "motion": {"success": True, "analysis_keyframes": []},
                    "transcription": {"success": True, "status": "skipped"},
                    "visual": {"success": True, "status": "skipped"},
                    "clip_analysis_markers": {"success": True, "marker_count": 1, "markers": []},
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
                    "readthrough": {"success": True, "cut_analysis": {"success": True}},
                    "motion": {"success": True, "analysis_keyframes": []},
                    "transcription": {"success": True, "status": "skipped"},
                    "visual": {"success": True, "status": "skipped"},
                    "clip_analysis_markers": {"success": True, "marker_count": 1, "markers": []},
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

    def test_clips_target_uses_explicit_clip_ids_and_rejects_non_analyzable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path_a = os.path.join(tmp, "A001_C001.mov")
            with open(path_a, "wb") as handle:
                handle.write(b"placeholder")
            good = ClipStub("A001_C001.mov", "clip-1", path_a)
            missing = ClipStub("MISSING.mov", "clip-2", os.path.join(tmp, "missing.mov"))
            root = FolderStub("Master", clips=[good, missing])
            records, target, warnings, err = _media_analysis_records_from_target(
                MediaPoolStub(root),
                {"target": {"type": "clips", "clip_ids": ["clip-1", "clip-2"]}},
            )

        self.assertIsNone(err)
        self.assertEqual(target["type"], "clips")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["clip_id"], "clip-1")
        self.assertTrue(any("Skipping non-analyzable clip" in warning for warning in warnings))

    def test_sequence_target_collects_used_assets_and_occurrences(self):
        with tempfile.TemporaryDirectory() as tmp:
            path_a = os.path.join(tmp, "A001_C001.mov")
            path_b = os.path.join(tmp, "A001_C002.wav")
            clip_a = ClipStub("A001_C001.mov", "clip-1", path_a)
            clip_a_duplicate = ClipStub("A001_C001 copy.mov", "clip-2", path_a)
            clip_b = ClipStub("A001_C002.wav", "clip-3", path_b)
            timeline = TimelineStub(
                video_tracks={1: [
                    TimelineItemStub("A001_C001", "item-1", clip_a, start=0, end=48),
                    TimelineItemStub("A001_C001 alt", "item-2", clip_a_duplicate, start=72, end=96),
                ]},
                audio_tracks={1: [TimelineItemStub("A001_C002", "item-3", clip_b, start=0, end=96)]},
            )
            records, target, warnings, err = _media_analysis_records_from_target(
                MediaPoolStub(FolderStub("Master")),
                {"target": "sequence"},
                project=TimelineProjectStub(timeline),
            )

        self.assertIsNone(err)
        self.assertEqual(warnings, [])
        self.assertEqual(target["type"], "sequence")
        self.assertEqual(target["timeline"]["occurrence_count"], 3)
        self.assertEqual(target["timeline"]["asset_count"], 2)
        self.assertEqual(len(records), 2)
        record_a = next(record for record in records if record["file_path"] == path_a)
        self.assertEqual(len(record_a["timeline_occurrences"]), 2)
        self.assertEqual(record_a["timeline_occurrences"][0]["timeline_item_id"], "item-1")

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
                    "segments": [{
                        "start": 0,
                        "end": 1.5,
                        "text": "Synthetic tone.",
                        "words": [
                            {"start": 0.0, "end": 0.7, "word": "Synthetic"},
                            {"start": 0.7, "end": 1.2, "word": "tone."},
                        ],
                    }],
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
            manifest_report = load_report(plan["output_root"]["project_root"])
            self.assertTrue(plan["success"])
            self.assertEqual(plan["capability_gaps"], [])
            self.assertTrue(manifest["success"])
            self.assertEqual(manifest["successful_clip_count"], 1)
            self.assertTrue(manifest["index"]["success"])
            index = analysis_index_status(plan["output_root"]["project_root"])
            self.assertTrue(index["exists"])
            self.assertEqual(index["counts"]["clips"], 1)
            artifacts = manifest["clips"][0]["artifacts"]
            self.assertTrue(os.path.exists(artifacts["analysis_json"]))
            self.assertTrue(os.path.exists(artifacts["technical_json"]))
            self.assertTrue(os.path.exists(artifacts["motion_json"]))
            self.assertTrue(os.path.exists(artifacts["transcript_json"]))
            self.assertTrue(os.path.exists(artifacts["transcript_srt"]))
            self.assertTrue(os.path.exists(artifacts["transcript_vtt"]))
            self.assertTrue(os.path.exists(artifacts["visual_json"]))
            self.assertTrue(os.path.exists(artifacts["marker_plan_json"]))
            self.assertTrue(summary["success"])
            self.assertEqual(summary["clip_reports"], 1)
            self.assertTrue(manifest_report["success"])
            clip_report = load_report(plan["output_root"]["project_root"], report_path=artifacts["analysis_json"])["report"]
            self.assertEqual(clip_report["transcription"]["text"], "Synthetic tone.")
            self.assertEqual(clip_report["transcription"]["segments"][0]["text"], "Synthetic tone.")
            self.assertGreaterEqual(clip_report["clip_analysis_markers"]["marker_count"], 1)
            self.assertFalse(clip_report["clip_analysis_markers"]["write_to_resolve_default"])
            self.assertTrue(clip_report["readthrough"]["cut_analysis"]["success"])
            self.assertIn("cut_count", clip_report["cut_analysis"])
            self.assertGreaterEqual(
                clip_report["motion"]["effective_sample_budget"],
                clip_report["motion"]["requested_sample_budget"],
            )
            self.assertIn("cut_boundary_pair_coverage", clip_report["motion"])
            self.assertIn("cut_analysis", clip_report["clip_analysis_markers"])
            with open(artifacts["transcript_json"], "r", encoding="utf-8") as handle:
                transcript_json = json.load(handle)
            self.assertEqual(transcript_json["text"], "Synthetic tone.")
            self.assertEqual(transcript_json["segments"][0]["text"], "Synthetic tone.")
            self.assertEqual(transcript_json["segments"][0]["words"][0]["word"], "Synthetic")
            with open(artifacts["marker_plan_json"], "r", encoding="utf-8") as handle:
                marker_plan_json = json.load(handle)
            self.assertEqual(marker_plan_json["schema"], "davinci_resolve_mcp.clip_analysis_markers.v1")
            self.assertFalse(marker_plan_json["resolve_marker_writeback"]["enabled"])
            self.assertEqual(marker_plan_json["color_scheme"]["qc_warning"], "Red")
            with open(artifacts["transcript_srt"], "r", encoding="utf-8") as handle:
                transcript_srt = handle.read()
            self.assertIn("00:00:00,000 --> 00:00:01,500", transcript_srt)
            self.assertIn("Synthetic tone.", transcript_srt)
            with open(artifacts["transcript_vtt"], "r", encoding="utf-8") as handle:
                transcript_vtt = handle.read()
            self.assertIn("WEBVTT", transcript_vtt)
            self.assertIn("00:00:00.000 --> 00:00:01.500", transcript_vtt)
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
            self.assertIn("clip_analysis_markers", manifest["reports"][0])
            self.assertGreaterEqual(manifest["reports"][0]["clip_analysis_markers"]["marker_count"], 1)
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
                self.assertIn("cut_analysis", motion)
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

    def test_build_analysis_index_queries_reports_without_image_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = os.path.join(tmp, "source")
            os.makedirs(source_dir)
            source = os.path.join(source_dir, "A001_C001.mov")
            with open(source, "wb") as handle:
                handle.write(b"synthetic source placeholder")

            record = {
                "clip_id": "clip-index",
                "clip_name": "A001_C001.mov",
                "file_path": source,
                "media_id": "media-index",
                "bin_path": "Master/Day 01",
                "fps": "24",
                "timeline_occurrences": [
                    {
                        "timeline_id": "timeline-main",
                        "timeline_name": "Assembly",
                        "track_type": "video",
                        "track_index": 1,
                        "item_index": 0,
                        "start_frame": 100,
                        "end_frame": 196,
                    }
                ],
            }
            root = resolve_output_root(
                project_name="Example Project",
                project_id="project-index",
                analysis_root=os.path.join(tmp, "analysis"),
                source_paths=[source],
                create=True,
            )["project_root"]
            clip_dir = os.path.join(root, "clips", stable_clip_directory(record))
            os.makedirs(clip_dir)
            signature = analysis_request_signature(
                record,
                "standard",
                {
                    "transcription": {"enabled": True, "backend": "mock"},
                    "vision": {"enabled": True, "provider": "mock"},
                },
                4,
            )
            report = {
                "success": True,
                "analysis_version": "0.1",
                "analysis_signature": signature,
                "analyzed_at": "2026-05-17T12:00:00Z",
                "source_file": source,
                "clip": record,
                "summary": "Reflective kitchen interview b-roll, medium motion",
                "technical_warnings": ["Container frame rate and average frame rate differ; possible VFR media"],
                "technical": {
                    "format": {"duration_seconds": 4.0, "size_bytes": 24},
                    "video": [{"frame_rate": 24.0, "duration_seconds": 4.0}],
                    "warnings": ["Container frame rate and average frame rate differ; possible VFR media"],
                },
                "readthrough": {"success": True, "cut_analysis": {"success": True}},
                "motion": {
                    "success": True,
                    "overall_motion_level": "medium",
                    "average_frame_delta": 0.04,
                    "max_frame_delta": 0.12,
                },
                "transcription": {
                    "success": True,
                    "text": "A childhood memory is described quietly.",
                    "segments": [
                        {"start": 0.5, "end": 2.4, "text": "A childhood memory is described quietly."}
                    ],
                },
                "visual": {
                    "success": True,
                    "clip_summary": "Person moves through a kitchen in a reflective mood.",
                    "content": {
                        "locations": ["kitchen"],
                        "actions": ["walking"],
                        "objects": ["coffee mug"],
                        "visible_text": [],
                        "notable_audio_context": ["quiet room tone"],
                    },
                    "editing_notes": {
                        "best_moments": ["00:00:01.000 thoughtful pause"],
                        "qc_flags": [],
                        "search_tags": ["reflective", "kitchen"],
                    },
                },
                "analysis_keyframes": [
                    {
                        "index": 1,
                        "time_seconds": 1.0,
                        "selection_reason": "midpoint",
                        "frame_path": "/tmp/should-not-be-stored.jpg",
                        "metrics": {"mean_luma": 91.5},
                        "delta_from_previous": 0.12,
                    }
                ],
                "clip_analysis_markers": {
                    "success": True,
                    "duration_seconds": 4.0,
                    "fps": 24.0,
                    "timeline_occurrences": record["timeline_occurrences"],
                    "markers": [
                        {
                            "id": "best-moment-001",
                            "type": "best_moment",
                            "color": "Green",
                            "name": "Best Moment",
                            "start_seconds": 1.0,
                            "end_seconds": 2.0,
                            "start_frame": 24,
                            "duration_frames": 24,
                            "visual_description": "Quiet reflective moment near the kitchen counter.",
                            "sound_note": "Soft room tone.",
                            "transcript_text": "childhood memory",
                            "source": "visual_editing_notes",
                            "confidence": "model_suggested",
                        }
                    ],
                },
            }
            with open(os.path.join(clip_dir, "analysis.json"), "w", encoding="utf-8") as handle:
                json.dump(report, handle)

            built = build_analysis_index(root)
            status = analysis_index_status(root)
            transcript_results = query_analysis_index(root, "childhood memory", result_types="transcript")
            marker_results = query_analysis_index(root, "reflective kitchen", result_types=["marker", "clip"])

            self.assertTrue(built["success"])
            self.assertEqual(built["image_blob_policy"], "excluded")
            self.assertEqual(built["counts"]["clips"], 1)
            self.assertEqual(built["counts"]["markers"], 1)
            self.assertEqual(built["counts"]["transcript_segments"], 1)
            self.assertTrue(status["exists"])
            self.assertEqual(status["counts"]["analysis_keyframes"], 1)
            self.assertGreaterEqual(transcript_results["result_count"], 1)
            self.assertEqual(transcript_results["results"][0]["result_type"], "transcript")
            self.assertGreaterEqual(marker_results["result_count"], 1)

            conn = sqlite3.connect(built["index_path"])
            try:
                columns = [
                    row[1]
                    for row in conn.execute("PRAGMA table_info(analysis_keyframes)").fetchall()
                ]
                self.assertNotIn("frame_path", columns)
                self.assertIsNone(
                    conn.execute(
                        "SELECT sql FROM sqlite_master WHERE sql LIKE ?",
                        ("%should-not-be-stored%",),
                    ).fetchone()
                )
            finally:
                conn.close()

    def test_query_analysis_index_reports_missing_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = resolve_output_root(
                project_name="Example Project",
                project_id="project-missing-index",
                analysis_root=os.path.join(tmp, "analysis"),
                source_paths=[],
                create=True,
            )["project_root"]
            status = analysis_index_status(root)
            result = query_analysis_index(root, "anything")

        self.assertTrue(status["success"])
        self.assertFalse(status["exists"])
        self.assertFalse(result["success"])
        self.assertIn("Analysis index not found", result["error"])

    def test_batch_job_slice_runs_and_builds_index(self):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("ffmpeg/ffprobe not installed")
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = os.path.join(tmp, "source")
            analysis_dir = os.path.join(tmp, "analysis")
            os.makedirs(source_dir)
            source_a = os.path.join(source_dir, "job_a.mp4")
            source_b = os.path.join(source_dir, "job_b.mp4")
            self._write_synthetic_media(source_a)
            self._write_synthetic_media(source_b)
            records = [
                {"clip_id": "clip-a", "clip_name": "job_a.mp4", "file_path": source_a, "media_id": "media-a"},
                {"clip_id": "clip-b", "clip_name": "job_b.mp4", "file_path": source_b, "media_id": "media-b"},
            ]
            params = {
                "analysis_root": analysis_dir,
                "depth": "standard",
                "max_analysis_frames": 2,
                "transcription": {
                    "enabled": True,
                    "backend": "mock",
                    "segments": [{"start": 0, "end": 1.0, "text": "Batch transcript."}],
                },
                "vision": {"enabled": True, "provider": "mock"},
            }
            created = create_batch_job(
                project_name="Example Project",
                project_id="project-job",
                records=records,
                target={"type": "file_list"},
                params=params,
                name="Synthetic batch",
            )
            self.assertTrue(created["success"])
            job = created["job"]
            self.assertEqual(job["total_clips"], 2)
            self.assertEqual(job["pending_clips"], 2)

            first = run_batch_job_slice(job["project_root"], job["job_id"], max_clips=1)
            self.assertTrue(first["success"])
            self.assertEqual(first["processed_count"], 1)
            mid = batch_job_status(job["project_root"], job["job_id"])
            mid_index = analysis_index_status(job["project_root"])
            self.assertEqual(mid["succeeded_clips"], 1)
            self.assertEqual(mid["pending_clips"], 1)
            self.assertTrue(mid_index["exists"])
            self.assertEqual(mid_index["counts"]["clips"], 1)

            second = run_batch_job_slice(job["project_root"], job["job_id"], max_clips=5)
            self.assertTrue(second["success"])
            final = batch_job_status(job["project_root"], job["job_id"])
            self.assertEqual(final["status"], "completed")
            self.assertEqual(final["succeeded_clips"], 2)
            self.assertTrue(os.path.exists(final["paths"]["progress_json"]))
            self.assertTrue(os.path.exists(final["paths"]["events_jsonl"]))

            jobs = list_batch_jobs(job["project_root"])
            index = analysis_index_status(job["project_root"])
            search = query_analysis_index(job["project_root"], "Batch transcript", result_types="transcript")
            self.assertEqual(jobs["count"], 1)
            self.assertTrue(index["exists"])
            self.assertEqual(index["counts"]["clips"], 2)
            self.assertGreaterEqual(search["result_count"], 1)

    def test_batch_job_cancel_and_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = os.path.join(tmp, "source")
            analysis_dir = os.path.join(tmp, "analysis")
            os.makedirs(source_dir)
            source = os.path.join(source_dir, "job_cancel.mov")
            with open(source, "wb") as handle:
                handle.write(b"placeholder")
            created = create_batch_job_from_paths(
                project_name="Example Project",
                project_id="project-job-cancel",
                paths=[source],
                analysis_root=analysis_dir,
                params={"depth": "quick"},
                name="Cancelable batch",
            )
            self.assertTrue(created["success"])
            job = created["job"]

            canceled = cancel_batch_job(job["project_root"], job["job_id"])
            self.assertEqual(canceled["status"], "canceled")
            resumed = resume_batch_job(job["project_root"], job["job_id"])
            self.assertEqual(resumed["status"], "queued")
            self.assertEqual(resumed["pending_clips"], 1)


if __name__ == "__main__":
    unittest.main()
