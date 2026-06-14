import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
import unittest.mock
from typing import Any, Dict, Optional

from src import server as _server_module
from src.server import (
    _apply_media_analysis_clip_markers,
    _apply_sync_event_markers,
    _media_analysis_apply_setup_defaults,
    _media_analysis_capabilities_for_request,
    _media_analysis_effective_preferences,
    _media_analysis_merge_metadata_field,
    _media_analysis_marker_candidates_from_report,
    _media_analysis_metadata_writeback_enabled,
    _media_analysis_missing_capabilities_response,
    _media_analysis_publish_confirmed,
    _media_analysis_timed_marker_decision,
    _media_analysis_provenance_metadata,
    _media_analysis_records_from_target,
    _media_analysis_report_metadata_candidates,
    _publish_clip_metadata_from_analysis,
    setup,
)
from mcp import types as mcp_types
from src.analysis_dashboard import (
    DashboardState,
    HTML,
    discover_project_contexts,
    list_analyzed_clips,
    get_analyzed_clip,
    get_analyzed_clip_shot,
    get_clip_frame_path,
    read_clip_corrections,
    _analysis_status_by_clip,
)
from src.utils import update_check
from src.utils.media_analysis import (
    HOST_CHAT_PATHS_PROVIDER,
    VISION_SCHEMA_REFERENCE,
    analysis_request_signature,
    analysis_index_status,
    analysis_root_coverage,
    build_analysis_index,
    build_coverage_report,
    build_host_chat_paths_payload,
    build_plan,
    cleanup_artifacts,
    commit_visual_analysis,
    _cut_boundary_analysis,
    detect_capabilities,
    execute_plan,
    execute_plan_async,
    executing_clips,
    plan_requires_capabilities,
    load_report,
    mark_registry_stale_for_clip,
    query_analysis_index,
    registry_entry_superseded_info,
    resolve_output_root,
    _sample_times,
    summarize_reports,
    build_clip_index,
    clip_directory_hash,
    clip_index_path,
    load_clip_index,
    resolve_clip_directory,
    stable_clip_directory,
    stable_clip_hash,
    stable_clip_match_hashes,
    update_analysis_registry,
    vision_is_pending_host_analysis,
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
    def __init__(self, name, clip_id, file_path, media_id=None, third_party=None, metadata=None):
        self.name = name
        self.clip_id = clip_id
        self.file_path = file_path
        self.media_id = media_id or f"media-{clip_id}"
        self.third_party = dict(third_party or {})
        self.metadata = dict(metadata or {})

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

    def GetThirdPartyMetadata(self, key=""):
        if key:
            return self.third_party.get(key, "")
        return dict(self.third_party)

    def GetMetadata(self, key=""):
        if key:
            return self.metadata.get(key, "")
        return dict(self.metadata)


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


class SamplingSessionStub:
    def __init__(self, sampling=False, context=False):
        self.sampling = sampling
        self.context = context

    def check_client_capability(self, capability):
        if capability.sampling is None:
            return False
        if not self.sampling:
            return False
        if capability.sampling.context is not None and not self.context:
            return False
        return True


class SamplingContextStub:
    def __init__(self, sampling=False, context=False):
        self.request_context = type(
            "RequestContextStub",
            (),
            {"session": SamplingSessionStub(sampling=sampling, context=context)},
        )()


class SamplingRequestSessionStub(SamplingSessionStub):
    def __init__(self, sampling=False, context=False, response_text=None):
        super().__init__(sampling=sampling, context=context)
        self.response_text = response_text or json.dumps({"success": True, "clip_summary": "sampled"})
        self.created = False

    async def create_message(self, *args, **kwargs):
        self.created = True
        self.create_message_args = args
        self.create_message_kwargs = kwargs
        return type(
            "SamplingResultStub",
            (),
            {"content": mcp_types.TextContent(type="text", text=self.response_text)},
        )()


class SamplingRequestContextStub:
    def __init__(self, sampling=False, context=False, response_text=None):
        self.session = SamplingRequestSessionStub(
            sampling=sampling,
            context=context,
            response_text=response_text,
        )
        self.request_context = type(
            "RequestContextStub",
            (),
            {"session": self.session},
        )()
        self.request_id = "request-123"


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
        # Flash candidates surface as their own sampled frames. cut_before/cut_after
        # candidates are emitted by _sample_times but get deduped against shot_start
        # and shot_end reservations when shot boundaries coincide with cut points
        # (which is the normal case — shots are defined by cuts). The cut-boundary
        # coverage is therefore visible as shot_start / shot_end samples here.
        self.assertIn("flash_candidate", reasons)
        self.assertIn("shot_start", reasons)
        self.assertIn("shot_end", reasons)

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

    def test_dashboard_project_navigation_uses_context_dropdown(self):
        self.assertNotIn('<button class="control-tab" data-panel-target="projects">Projects</button>', HTML)
        self.assertIn("const VIEW_ALL_PROJECTS_VALUE", HTML)
        self.assertIn(".filter(context => context.active || context.resolve_current)", HTML)
        self.assertNotIn(".filter(context => context.can_load_resolve !== false || context.active || context.resolve_current)", HTML)
        self.assertIn("View All Projects", HTML)
        self.assertIn("setPanel('projects')", HTML)

    def test_dashboard_menu_buttons_open_without_navigation(self):
        menu_branch = HTML.split("if (control.classList.contains('has-menu')) {", 1)[1].split("return;", 1)[0]
        self.assertIn("toggleNavDropdown(control);", menu_branch)
        self.assertNotIn("setPanel(", menu_branch)

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

    def test_stable_clip_hash_survives_media_pool_rename(self):
        """The folder hash is anchored to stable Resolve ids, not the display name."""
        before = {
            "clip_name": "c0001.mp4",
            "clip_id": "clip-123",
            "file_path": "/Volumes/Media/c0001.mp4",
        }
        after = dict(before, clip_name="ice_c0001.mp4")

        # The leading slug changes, but the trailing hash is identical.
        self.assertNotEqual(stable_clip_directory(before), stable_clip_directory(after))
        self.assertEqual(stable_clip_hash(before), stable_clip_hash(after))
        self.assertEqual(
            clip_directory_hash(stable_clip_directory(before)),
            clip_directory_hash(stable_clip_directory(after)),
        )

    def test_clip_directory_hash_extracts_trailing_hex_only(self):
        self.assertEqual(clip_directory_hash("c0001.mp4-c923852545ed"), "c923852545ed")
        self.assertEqual(clip_directory_hash("ice_c0001.mp4-c923852545ed"), "c923852545ed")
        # A bare hash folder (no slug) is also a valid clip report folder.
        self.assertEqual(clip_directory_hash("c923852545ed"), "c923852545ed")
        # No trailing 12-char hex token -> not a clip report folder.
        self.assertIsNone(clip_directory_hash("not-a-clip-folder"))
        self.assertIsNone(clip_directory_hash("plainname"))

    def test_canonical_hash_agrees_across_resolve_and_path_based_records(self):
        """Same media -> same canonical hash whether or not clip_id is present.

        The Resolve inventory carries clip_id; path-based batch records do not.
        Anchoring the canonical hash to the (normalized) file path removes that
        cross-basis mismatch so both surfaces agree on one folder.
        """
        resolve_record = {
            "clip_name": "c0001.mp4",
            "clip_id": "clip-123",
            "media_id": "media-9",
            "file_path": "/Volumes/Media/c0001.mp4",
        }
        path_based = {
            "clip_name": "c0001.mp4",
            "clip_id": None,
            "media_id": None,
            "file_path": "/Volumes/Media/c0001.mp4",
        }
        self.assertEqual(stable_clip_hash(resolve_record), stable_clip_hash(path_based))
        # Each record can still resolve the other's folder via the match set.
        self.assertIn(stable_clip_hash(path_based), stable_clip_match_hashes(resolve_record))
        self.assertIn(stable_clip_hash(resolve_record), stable_clip_match_hashes(path_based))

    def test_resolve_clip_directory_reuses_legacy_clip_id_folder(self):
        """Migration: a folder written under the old clip_id-first basis is
        reused on the next write instead of being orphaned under a new name."""
        with tempfile.TemporaryDirectory() as tmp:
            project_root = os.path.join(tmp, "project-root")
            record = {
                "clip_name": "c0001.mp4",
                "clip_id": "clip-123",
                "file_path": "/Volumes/Media/c0001.mp4",
            }
            # Legacy folder name: slug + hash(clip_id) (pre-canonical scheme).
            from src.utils.media_analysis import short_hash
            legacy_dir = os.path.join(
                project_root, "clips", f"c0001.mp4-{short_hash('clip-123', 12)}"
            )
            os.makedirs(legacy_dir, exist_ok=True)

            resolved = resolve_clip_directory(project_root, record)
            self.assertEqual(os.path.realpath(resolved), os.path.realpath(legacy_dir))

    def test_resolve_clip_directory_reuses_folder_after_rename(self):
        """A renamed clip writes back into its existing folder (no orphan)."""
        with tempfile.TemporaryDirectory() as tmp:
            project_root = os.path.join(tmp, "project-root")
            record = {
                "clip_name": "c0001.mp4",
                "clip_id": "clip-123",
                "file_path": "/Volumes/Media/c0001.mp4",
            }
            original = resolve_clip_directory(project_root, record)
            os.makedirs(original, exist_ok=True)

            renamed = dict(record, clip_name="ice_c0001.mp4")
            self.assertEqual(
                os.path.realpath(resolve_clip_directory(project_root, renamed)),
                os.path.realpath(original),
            )

    def test_resolve_clip_directory_mints_canonical_path_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = os.path.join(tmp, "project-root")
            record = {
                "clip_name": "c0001.mp4",
                "clip_id": "clip-123",
                "file_path": "/Volumes/Media/c0001.mp4",
            }
            resolved = resolve_clip_directory(project_root, record)
            self.assertEqual(
                os.path.basename(resolved.rstrip("/")), stable_clip_directory(record)
            )

    def _write_report(self, project_root, folder, clip_block):
        clip_dir = os.path.join(project_root, "clips", folder)
        os.makedirs(clip_dir, exist_ok=True)
        with open(os.path.join(clip_dir, "analysis.json"), "w", encoding="utf-8") as handle:
            json.dump({"clip": clip_block}, handle)
        return clip_dir

    def test_clip_index_indexes_all_stable_ids_from_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = os.path.join(tmp, "project-root")
            self._write_report(
                project_root,
                "c0001.mp4-deadbeef0001",
                {"clip_id": "clip-123", "media_id": "media-9",
                 "file_path": "/Volumes/Media/c0001.mp4", "clip_name": "c0001.mp4"},
            )
            index = build_clip_index(project_root)
            self.assertTrue(os.path.isfile(clip_index_path(project_root)))
            h2f = index["hash_to_folder"]
            # Every stable id of the clip resolves to the same folder.
            for record in (
                {"file_path": "/Volumes/Media/c0001.mp4"},
                {"clip_id": "clip-123"},
                {"media_id": "media-9"},
            ):
                hashes = stable_clip_match_hashes(record)
                self.assertTrue(any(h in h2f for h in hashes), record)
                folders = {h2f[h] for h in hashes if h in h2f}
                self.assertEqual(folders, {"c0001.mp4-deadbeef0001"})

    def test_clip_index_matches_offline_clip_without_file_path(self):
        """The edge the manifest exists for: a clip analyzed while online (folder
        hashed on file path) that the live inventory later reports offline with
        no file path, only a clip_id. The index still resolves it. #51."""
        with tempfile.TemporaryDirectory() as tmp:
            project_root = os.path.join(tmp, "project-root")
            online = {
                "clip_name": "c0001.mp4",
                "clip_id": "clip-123",
                "file_path": "/Volumes/Media/c0001.mp4",
            }
            folder = stable_clip_directory(online)
            self._write_report(project_root, folder, dict(online))

            # Live record went offline: no file_path, basis falls back to clip_id.
            offline = {"clip_name": "c0001.mp4", "clip_id": "clip-123", "file_path": None}
            offline["clip_key"] = stable_clip_directory(offline)
            self.assertNotEqual(offline["clip_key"], folder)
            self.assertNotIn(
                stable_clip_hash(online), stable_clip_match_hashes(offline)
            )  # a folder-name scan would miss it

            status = _analysis_status_by_clip(project_root, [offline])
            entry = status.get(offline["clip_key"])
            self.assertIsNotNone(entry)
            self.assertEqual(entry["analysis_status"], "analyzed")

    def test_clip_index_rebuilds_when_report_added(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = os.path.join(tmp, "project-root")
            self._write_report(
                project_root, "a-aaaaaaaa0001",
                {"clip_id": "clip-a", "file_path": "/m/a.mp4", "clip_name": "a.mp4"},
            )
            first = load_clip_index(project_root)
            self.assertEqual(len(first["hash_to_folder"]) >= 1, True)

            # Add a second report; a stale signature must trigger a rebuild.
            self._write_report(
                project_root, "b-bbbbbbbb0002",
                {"clip_id": "clip-b", "file_path": "/m/b.mp4", "clip_name": "b.mp4"},
            )
            second = load_clip_index(project_root)
            self.assertNotEqual(first["signature"], second["signature"])
            self.assertIn(stable_clip_hash({"clip_id": "clip-b", "file_path": "/m/b.mp4"}),
                          second["hash_to_folder"])

    def test_analysis_status_counts_renamed_clip_as_analyzed(self):
        """Issue #51: a clip renamed after analysis still counts as analyzed."""
        with tempfile.TemporaryDirectory() as tmp:
            project_root = os.path.join(tmp, "project-root")
            record = {
                "clip_name": "c0001.mp4",
                "clip_id": "clip-123",
                "file_path": "/Volumes/Media/c0001.mp4",
            }
            # Report was written under the ORIGINAL name.
            original_dir = os.path.join(project_root, "clips", stable_clip_directory(record))
            os.makedirs(original_dir, exist_ok=True)
            with open(os.path.join(original_dir, "analysis.json"), "w", encoding="utf-8") as handle:
                json.dump({"clip": {"clip_id": "clip-123"}}, handle)

            # The clip is now renamed in the Media Pool; clip_key is recomputed
            # from the NEW name (as resolve_media_inventory would do).
            renamed = dict(record, clip_name="ice_c0001.mp4")
            renamed["clip_key"] = stable_clip_directory(renamed)
            self.assertFalse(
                os.path.isdir(os.path.join(project_root, "clips", renamed["clip_key"]))
            )

            status = _analysis_status_by_clip(project_root, [renamed])
            entry = status.get(renamed["clip_key"])
            self.assertIsNotNone(entry)
            self.assertEqual(entry["analysis_status"], "analyzed")
            self.assertTrue(os.path.isfile(entry["analysis_report_path"]))

    def test_analysis_status_counts_renamed_clip_from_reused_job_report(self):
        """Issue #51: rename also resolves via the jobs DB when the report is
        a reused batch report living outside the local clips/ dir."""
        with tempfile.TemporaryDirectory() as tmp:
            project_root = os.path.join(tmp, "active-root")
            os.makedirs(project_root, exist_ok=True)
            record = {
                "clip_name": "c0001.mp4",
                "clip_id": "clip-123",
                "file_path": "/Volumes/Media/c0001.mp4",
            }
            old_key = stable_clip_directory(record)

            # The actual report lives in a *different* project root (batch reuse),
            # not under {project_root}/clips/.
            source_dir = os.path.join(tmp, "source-root", "clips", old_key)
            os.makedirs(source_dir, exist_ok=True)
            report_path = os.path.join(source_dir, "analysis.json")
            with open(report_path, "w", encoding="utf-8") as handle:
                json.dump({"clip": {"clip_id": "clip-123"}}, handle)

            # The jobs DB recorded the clip under its OLD clip_key.
            conn = sqlite3.connect(os.path.join(project_root, "jobs.sqlite"))
            try:
                conn.execute(
                    "CREATE TABLE jobs (job_id TEXT, name TEXT, updated_at TEXT)"
                )
                conn.execute(
                    "CREATE TABLE job_clips (job_id TEXT, clip_key TEXT, status TEXT, "
                    "cache_status TEXT, report_path TEXT, error TEXT, updated_at TEXT)"
                )
                conn.execute(
                    "INSERT INTO jobs (job_id, name, updated_at) VALUES (?, ?, ?)",
                    ("job-1", "batch", "2026-06-01T10:00:00Z"),
                )
                conn.execute(
                    "INSERT INTO job_clips (job_id, clip_key, status, cache_status, "
                    "report_path, error, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("job-1", old_key, "skipped", "reused", report_path, None,
                     "2026-06-01T10:00:00Z"),
                )
                conn.commit()
            finally:
                conn.close()

            # Clip renamed in the Media Pool -> clip_key recomputed from new name.
            renamed = dict(record, clip_name="ice_c0001.mp4")
            renamed["clip_key"] = stable_clip_directory(renamed)
            self.assertNotEqual(renamed["clip_key"], old_key)

            status = _analysis_status_by_clip(project_root, [renamed])
            entry = status.get(renamed["clip_key"])
            self.assertIsNotNone(entry)
            self.assertEqual(entry["analysis_status"], "analyzed")

    def test_capability_detection_never_installs(self):
        caps = detect_capabilities(env={})

        self.assertTrue(caps["success"])
        self.assertTrue(caps["no_auto_install"])
        self.assertTrue(caps["vision"]["enabled_by_default"])
        self.assertEqual(caps["vision"]["default_provider"], HOST_CHAT_PATHS_PROVIDER)
        self.assertTrue(caps["vision"]["available"])

    def test_request_capabilities_report_host_chat_paths_vision(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.environ.get("DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS")
            os.environ["DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS"] = os.path.join(tmp, "prefs.json")
            try:
                report = _media_analysis_capabilities_for_request(None)
                self.assertTrue(report["vision"]["enabled_by_default"])
                self.assertTrue(report["vision"]["available"])
                self.assertEqual(report["vision"]["provider"], HOST_CHAT_PATHS_PROVIDER)
                self.assertEqual(report["vision"]["availability"], "ready")
                self.assertEqual(
                    report["vision"]["host_chat_paths"]["commit_action"],
                    {"tool": "media_analysis", "action": "commit_vision"},
                )
                self.assertEqual(
                    report["vision"]["host_chat_paths"]["schema_reference"],
                    VISION_SCHEMA_REFERENCE,
                )
            finally:
                if previous is None:
                    os.environ.pop("DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS", None)
                else:
                    os.environ["DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS"] = previous

    def test_host_chat_paths_payload_emits_frame_paths_and_commit_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            frame_path = os.path.join(tmp, "frame.jpg")
            with open(frame_path, "wb") as handle:
                handle.write(b"sample-frame-bytes")

            payload = build_host_chat_paths_payload(
                record={
                    "clip_id": "clip-xyz-1",
                    "clip_name": "A001_C001.mov",
                    "file_path": "/Volumes/Media/A001_C001.mov",
                },
                motion={
                    "analysis_keyframes": [{
                        "frame_path": frame_path,
                        "time_seconds": 0.0,
                        "selection_reason": "first_usable",
                    }],
                    "effective_sample_budget": 1,
                    "overall_motion_level": "low",
                    "cut_analysis": {"cut_count": 0, "flash_frame_candidates": []},
                },
                options={"vision": {"enabled": True, "provider": HOST_CHAT_PATHS_PROVIDER}},
                artifacts={"clip_dir": os.path.join(tmp, "clips", "test")},
            )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["status"], "pending_host_analysis")
        self.assertEqual(payload["provider"], HOST_CHAT_PATHS_PROVIDER)
        self.assertEqual(payload["frame_paths"], [os.path.realpath(frame_path)])
        self.assertEqual(payload["frame_count"], 1)
        self.assertEqual(payload["schema_reference"], VISION_SCHEMA_REFERENCE)
        self.assertEqual(payload["commit_action"]["tool"], "media_analysis")
        self.assertEqual(payload["commit_action"]["action"], "commit_vision")
        self.assertEqual(payload["commit_action"]["params"]["clip_id"], "clip-xyz-1")
        self.assertEqual(payload["commit_action"]["params"]["vision_token"], payload["vision_token"])
        self.assertTrue(vision_is_pending_host_analysis(payload))

    def test_host_chat_paths_payload_emits_shot_table_keyed_to_frame_indices(self):
        """Deferred payload must list every shot range with the frame indices that fall in it.

        The host chat needs this table to author one shot_descriptions entry per shot,
        grounded in the specific frame_indices for that shot rather than nearest neighbours.
        """
        with tempfile.TemporaryDirectory() as tmp:
            frames_dir = os.path.join(tmp, "frames")
            os.makedirs(frames_dir, exist_ok=True)
            paths = []
            times = [0.5, 1.5, 4.5, 5.5, 9.0]
            for index, _ in enumerate(times, 1):
                p = os.path.join(frames_dir, f"sampled_{index:04d}.jpg")
                with open(p, "wb") as handle:
                    handle.write(b"x")
                paths.append(p)
            payload = build_host_chat_paths_payload(
                record={
                    "clip_id": "clip-shots",
                    "clip_name": "A001.mov",
                    "file_path": "/Volumes/Media/A001.mov",
                },
                motion={
                    "analysis_keyframes": [
                        {"frame_path": paths[idx], "time_seconds": t, "selection_reason": "cut_before"}
                        for idx, t in enumerate(times)
                    ],
                    "overall_motion_level": "high",
                    "cut_analysis": {
                        "cut_count": 2,
                        "shot_ranges": [
                            {"index": 1, "start": 0.0, "end": 2.0},
                            {"index": 2, "start": 2.0, "end": 6.0},
                            {"index": 3, "start": 6.0, "end": 10.0},
                        ],
                        "flash_frame_candidates": [],
                    },
                },
                options={"vision": {"enabled": True, "provider": HOST_CHAT_PATHS_PROVIDER}},
                artifacts={"clip_dir": os.path.join(tmp, "clips", "shots")},
            )

        shot_table = payload["shot_table"]
        self.assertEqual([row["shot_index"] for row in shot_table], [1, 2, 3])
        by_index = {row["shot_index"]: row for row in shot_table}
        self.assertEqual(by_index[1]["frame_indices"], [1, 2])
        self.assertEqual(by_index[2]["frame_indices"], [3, 4])
        self.assertEqual(by_index[3]["frame_indices"], [5])
        for row in shot_table:
            self.assertTrue(row["has_in_shot_frame"])
        self.assertIn("shot_descriptions", payload["prompt"])
        self.assertIn("shot_table", payload["instructions"])

    def test_commit_visual_analysis_applies_shot_descriptions_per_shot_marker(self):
        """Each shot marker must inherit its own shot_descriptions[shot_index] description.

        Regression for the bug where _visual_description_for_time copied the
        temporally-nearest analysis_keyframe's description into every adjacent shot,
        producing wrong labels for shots without a per-shot keyframe.
        """
        with tempfile.TemporaryDirectory() as tmp:
            project_root = os.path.join(tmp, "project-root")
            clip_dir = os.path.join(project_root, "clips", "shotty")
            os.makedirs(clip_dir, exist_ok=True)
            existing = {
                "success": True,
                "analysis_version": "0.2",
                "analysis_signature": {"signature_hash": "feedface"},
                "clip": {"clip_id": "clip-shots", "clip_name": "A001.mov", "file_path": "/Volumes/Media/A001.mov"},
                "technical": {"video": [{"frame_rate": 24}]},
                "readthrough": {
                    "scenes": {"items": []},
                    "cut_analysis": {
                        "cut_points": [],
                        "shot_ranges": [
                            {"index": 1, "start": 0.0, "end": 2.0},
                            {"index": 2, "start": 2.0, "end": 6.0},
                            {"index": 3, "start": 6.0, "end": 10.0},
                        ],
                        "flash_frame_candidates": [],
                    },
                },
                "motion": {"analysis_keyframes": [], "overall_motion_level": "high"},
                "transcription": {"success": True, "segments": []},
                "visual": {
                    "success": True,
                    "status": "pending_host_analysis",
                    "provider": HOST_CHAT_PATHS_PROVIDER,
                    "vision_token": "tok-shots-aaaaaaaa",
                    "frame_paths": [],
                },
                "analysis_profile": {"vision_enabled": True, "transcription_enabled": False},
                "vision_status": "pending_host_analysis",
                "vision_token": "tok-shots-aaaaaaaa",
            }
            with open(os.path.join(clip_dir, "analysis.json"), "w", encoding="utf-8") as handle:
                json.dump(existing, handle)

            result = commit_visual_analysis(
                project_root=project_root,
                clip_id="clip-shots",
                vision_token="tok-shots-aaaaaaaa",
                visual={
                    "clip_summary": "Three distinct shots: opener, B-roll, outro.",
                    "shot_descriptions": [
                        {"shot_index": 1, "time_seconds_start": 0.0, "time_seconds_end": 2.0,
                         "description": "Opening fisheye on rental car at driver door."},
                        {"shot_index": 2, "time_seconds_start": 2.0, "time_seconds_end": 6.0,
                         "description": "Aerial driveway, no subjects in frame."},
                        {"shot_index": 3, "time_seconds_start": 6.0, "time_seconds_end": 10.0,
                         "description": "Interior driver POV at the wheel."},
                    ],
                    "analysis_keyframes": [
                        {"time_seconds": 0.5, "description": "Opening fisheye keyframe."},
                    ],
                },
            )

            self.assertTrue(result["success"])
            with open(result["marker_plan_json"], "r", encoding="utf-8") as handle:
                plan = json.load(handle)
            shot_markers = [m for m in plan["markers"] if m["type"] == "shot"]
            by_index = {m["id"]: m for m in shot_markers}
            self.assertEqual(by_index["shot-001"]["visual_description"], "Opening fisheye on rental car at driver door.")
            self.assertEqual(by_index["shot-002"]["visual_description"], "Aerial driveway, no subjects in frame.")
            self.assertEqual(by_index["shot-003"]["visual_description"], "Interior driver POV at the wheel.")

    def test_commit_visual_analysis_falls_back_when_shot_description_missing(self):
        """When a shot has no shot_descriptions entry and no in-range keyframe,
        the fallback must NOT pick a far-away keyframe — it should land on the
        clip_summary-tagged fallback so the marker is honest about being unverified.
        """
        with tempfile.TemporaryDirectory() as tmp:
            project_root = os.path.join(tmp, "project-root")
            clip_dir = os.path.join(project_root, "clips", "partial")
            os.makedirs(clip_dir, exist_ok=True)
            existing = {
                "success": True,
                "analysis_version": "0.2",
                "clip": {"clip_id": "clip-partial", "clip_name": "B001.mov", "file_path": "/Volumes/Media/B001.mov"},
                "technical": {"video": [{"frame_rate": 24}]},
                "readthrough": {
                    "scenes": {"items": []},
                    "cut_analysis": {
                        "cut_points": [],
                        "shot_ranges": [
                            {"index": 1, "start": 0.0, "end": 2.0},
                            {"index": 2, "start": 2.0, "end": 6.0},
                            {"index": 3, "start": 6.0, "end": 10.0},
                        ],
                        "flash_frame_candidates": [],
                    },
                },
                "motion": {"analysis_keyframes": [], "overall_motion_level": "high"},
                "transcription": {"success": True, "segments": []},
                "visual": {"success": True, "status": "pending_host_analysis", "provider": HOST_CHAT_PATHS_PROVIDER, "vision_token": "tok-partial-cccccccc"},
                "analysis_profile": {"vision_enabled": True},
                "vision_status": "pending_host_analysis",
                "vision_token": "tok-partial-cccccccc",
            }
            with open(os.path.join(clip_dir, "analysis.json"), "w", encoding="utf-8") as handle:
                json.dump(existing, handle)

            result = commit_visual_analysis(
                project_root=project_root,
                clip_id="clip-partial",
                vision_token="tok-partial-cccccccc",
                visual={
                    "clip_summary": "Cold open: rental car gag.",
                    "shot_descriptions": [
                        {"shot_index": 1, "time_seconds_start": 0.0, "time_seconds_end": 2.0,
                         "description": "Opening fisheye on rental car."},
                    ],
                    "analysis_keyframes": [
                        {"time_seconds": 0.5, "description": "Opening fisheye keyframe."},
                    ],
                },
            )

            self.assertTrue(result["success"])
            with open(result["marker_plan_json"], "r", encoding="utf-8") as handle:
                plan = json.load(handle)
            shot_markers = {m["id"]: m for m in plan["markers"] if m["type"] == "shot"}
            self.assertEqual(shot_markers["shot-001"]["visual_description"], "Opening fisheye on rental car.")
            # Shot 2 has no per-shot description and no in-range keyframe → fallback to clip_summary
            # tagged so reviewers can tell it was inherited, not authored for this shot.
            self.assertIn("clip summary", shot_markers["shot-002"]["visual_description"].lower())
            self.assertNotIn("Opening fisheye", shot_markers["shot-002"]["visual_description"])
            self.assertIn("clip summary", shot_markers["shot-003"]["visual_description"].lower())
            self.assertNotIn("Opening fisheye", shot_markers["shot-003"]["visual_description"])

    def test_commit_visual_analysis_merges_into_existing_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = os.path.join(tmp, "project-root")
            clip_dir = os.path.join(project_root, "clips", "demo-clip")
            os.makedirs(clip_dir, exist_ok=True)
            existing = {
                "success": True,
                "analysis_version": "0.1",
                "analysis_signature": {"signature_hash": "deadbeef"},
                "clip": {"clip_id": "clip-xyz-1", "clip_name": "A001_C001.mov", "file_path": "/Volumes/Media/A001_C001.mov"},
                "technical": {"video": [{"frame_rate": 24}]},
                "readthrough": {"scenes": {"items": []}, "cut_analysis": {"cut_points": [], "shot_ranges": []}},
                "motion": {"analysis_keyframes": [], "overall_motion_level": "low"},
                "transcription": {"success": True, "segments": []},
                "visual": {
                    "success": True,
                    "status": "pending_host_analysis",
                    "provider": HOST_CHAT_PATHS_PROVIDER,
                    "vision_token": "abcdef1234567890",
                    "frame_paths": [],
                },
                "analysis_profile": {"vision_enabled": True, "transcription_enabled": False},
                "vision_status": "pending_host_analysis",
                "vision_token": "abcdef1234567890",
            }
            with open(os.path.join(clip_dir, "analysis.json"), "w", encoding="utf-8") as handle:
                json.dump(existing, handle)

            result = commit_visual_analysis(
                project_root=project_root,
                clip_id="clip-xyz-1",
                vision_token="abcdef1234567890",
                visual={
                    "clip_summary": "Static wide shot of an empty room.",
                    "editorial_classification": {"primary_use": "establishing", "select_potential": "low", "reason": "no subject"},
                    "editing_notes": {"best_moments": [], "qc_flags": [], "search_tags": ["empty", "wide"]},
                },
            )

            self.assertTrue(result["success"])
            self.assertTrue(os.path.isfile(result["analysis_json"]))
            self.assertTrue(os.path.isfile(result["visual_json"]))
            self.assertTrue(os.path.isfile(result["marker_plan_json"]))
            with open(result["analysis_json"], "r", encoding="utf-8") as handle:
                updated = json.load(handle)
            self.assertEqual(updated["visual"]["clip_summary"], "Static wide shot of an empty room.")
            self.assertEqual(updated["visual"]["provider"], HOST_CHAT_PATHS_PROVIDER)
            self.assertNotIn("vision_status", updated)
            self.assertNotIn("vision_token", updated)
            self.assertIn("vision_committed_at", updated)
            self.assertIn("empty", updated["visual"]["editing_notes"]["search_tags"])

    def test_commit_visual_analysis_rejects_mismatched_vision_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = os.path.join(tmp, "project-root")
            clip_dir = os.path.join(project_root, "clips", "demo-clip")
            os.makedirs(clip_dir, exist_ok=True)
            with open(os.path.join(clip_dir, "analysis.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "clip": {"clip_id": "clip-xyz-2"},
                    "visual": {"vision_token": "real-token-aaaaaaaa"},
                }, handle)

            result = commit_visual_analysis(
                project_root=project_root,
                clip_id="clip-xyz-2",
                vision_token="wrong-token-bbbbbbbb",
                visual={"clip_summary": "anything"},
            )

            self.assertFalse(result["success"])
            self.assertIn("vision_token mismatch", (result["error"].get("message","") if isinstance(result["error"], dict) else result["error"]))

    def test_publish_clip_metadata_uses_pre_resolved_report_path_bypassing_reanalysis(self):
        """commit_vision auto-publish must NOT re-run analysis after a successful merge.

        When the wrapper passes `_pre_resolved_report_paths={clip_id: analysis_json}`,
        `_publish_clip_metadata_from_analysis` must read the just-committed report
        directly and skip `execute_media_analysis_plan_async`. The previous behavior
        re-ran analysis, and any cache-reuse miss (path normalization drift,
        signature mismatch, record-shape difference) surfaced as a silent-lie
        `status=pending_host_vision_analysis` in the response even though the
        on-disk artifact was finalized.
        """
        class _PublishClipStub:
            def __init__(self, clip_id, clip_name, file_path):
                self._id = clip_id
                self._name = clip_name
                self._props = {
                    "File Path": file_path,
                    "Duration": "00:00:06:00",
                    "FPS": "24",
                    "Resolution": "160x90",
                    "Type": "Video",
                }
                self.metadata = {}
                self.third_party = {}
                self.markers = {}

            def GetUniqueId(self):
                return self._id

            def GetName(self):
                return self._name

            def GetClipProperty(self, key=""):
                if key in (None, ""):
                    return dict(self._props)
                return self._props.get(key, "")

            def GetMediaId(self):
                return self._id

            def GetMetadata(self, key=""):
                if key in (None, ""):
                    return dict(self.metadata)
                return self.metadata.get(key, "")

            def GetThirdPartyMetadata(self, key=""):
                if key in (None, ""):
                    return dict(self.third_party)
                return self.third_party.get(key, "")

            def SetMetadata(self, key, value):
                self.metadata[key] = value
                return True

            def SetThirdPartyMetadata(self, key, value):
                self.third_party[key] = value
                return True

            def AddMarker(self, frame, color, name, note, duration, custom_data=""):
                self.markers[frame] = {"color": color, "name": name, "note": note, "duration": duration}
                return True

            def GetMarkers(self):
                return self.markers

        with tempfile.TemporaryDirectory() as tmp:
            project_root = os.path.join(tmp, "20260517_sample-fc314309e4")
            clip_dir = os.path.join(project_root, "clips", "demo-clip")
            os.makedirs(clip_dir, exist_ok=True)
            media_file = os.path.join(tmp, "demo.mp4")
            with open(media_file, "wb") as h:
                h.write(b"\x00" * 1024)

            report = {
                "success": True,
                "analysis_version": "0.2",
                "analyzed_at": "2026-05-19T10:00:00Z",
                "source_file": media_file,
                "clip": {
                    "clip_id": "clip-pub-1",
                    "clip_name": "demo.mp4",
                    "file_path": media_file,
                    "duration_seconds": 6.0,
                    "fps": 24.0,
                },
                "technical": {"video": [{"duration_seconds": 6.0, "frame_rate": 24}]},
                "readthrough": {"scenes": {"items": []}, "cut_analysis": {"cut_points": [], "shot_ranges": []}},
                "motion": {"analysis_keyframes": [], "overall_motion_level": "low"},
                "transcription": {"success": True, "segments": []},
                "visual": {
                    "success": True,
                    "provider": HOST_CHAT_PATHS_PROVIDER,
                    "clip_summary": "Wide static shot.",
                    "editorial_classification": {"primary_use": "establishing", "select_potential": "medium", "reason": ""},
                    "content": {"locations": ["studio"], "people_visible": "unknown", "actions": [], "objects": [], "visible_text": [], "notable_audio_context": []},
                    "shot_and_style": {"shot_sizes": ["wide"], "camera_motion": ["static"], "composition_notes": "", "lighting_mood": "", "color_mood": ""},
                    "slate": {"slate_visible": False, "scene": "", "shot": "", "take": "", "camera": "", "roll": "", "date": "", "production": "", "visible_text": [], "confidence": {}},
                    "motion": {"overall_level": "low", "motion_events": [], "quiet_regions": []},
                    "cut_understanding": {"cut_count": 0, "likely_edited_sequence": False, "flash_frame_candidates": [], "notes": []},
                    "shot_descriptions": [
                        {"shot_index": 0, "description": "Wide static shot of a studio.", "time_seconds_start": 0.0, "time_seconds_end": 6.0, "qc_flags": []},
                    ],
                    "editing_notes": {"best_moments": [], "continuity_flags": [], "qc_flags": [], "search_tags": ["wide", "studio"]},
                    "confidence": {"visual": "high", "motion": "computed", "transcript": "unavailable"},
                },
                "analysis_signature": {"signature_hash": "test-abcdef"},
                "analysis_profile": {"depth": "standard", "vision_enabled": True, "transcription_enabled": False},
                "vision_committed_at": "2026-05-19T11:00:00Z",
                "clip_analysis_markers": {"markers": [], "marker_count": 0},
            }
            report_path = os.path.join(clip_dir, "analysis.json")
            with open(report_path, "w") as handle:
                json.dump(report, handle)

            clip = _PublishClipStub("clip-pub-1", "demo.mp4", media_file)
            mp = MarkerMediaPoolStub([clip])

            class _ProjectStub:
                def __init__(self, media_pool):
                    self._mp = media_pool
                def GetMediaPool(self):
                    return self._mp
                def GetName(self):
                    return "20260517_Sample"
                def GetUniqueId(self):
                    return "51657265-33d8-44d6-b000-fcdb46b72d67"

            proj = _ProjectStub(mp)

            called = {"execute_plan": False}
            async def _sentinel_execute_plan(*args, **kwargs):
                called["execute_plan"] = True
                raise AssertionError(
                    "execute_media_analysis_plan_async called despite _pre_resolved_report_paths bypass"
                )

            original_exec = _server_module.execute_media_analysis_plan_async
            _server_module.execute_media_analysis_plan_async = _sentinel_execute_plan
            try:
                publish_params = {
                    "target": {"type": "clip", "clip_id": "clip-pub-1"},
                    "analysis_root": project_root,
                    "publish_metadata": True,
                    "confirm": True,
                    "dry_run": False,
                    "timed_markers": "no",
                    "vision": {"enabled": True, "provider": HOST_CHAT_PATHS_PROVIDER},
                    "transcription": {"enabled": False},
                    "fields": ["Description"],
                    "_pre_resolved_report_paths": {"clip-pub-1": report_path},
                }
                result = asyncio.run(
                    _publish_clip_metadata_from_analysis(proj, publish_params, None)
                )
            finally:
                _server_module.execute_media_analysis_plan_async = original_exec

            self.assertFalse(called["execute_plan"], "fast path must skip execute_plan")
            self.assertNotEqual(
                result.get("status"), "pending_host_vision_analysis",
                f"auto-publish silently lied with pending_host_vision_analysis; result={result}",
            )
            self.assertTrue(result.get("success"), f"publish failed: {result}")
            self.assertTrue(
                (result.get("analysis_manifest") or {}).get("pre_resolved"),
                "manifest should be marked pre_resolved when the fast path was used",
            )

    def test_review_api_list_clip_shot_frame(self):
        """V2 Review API: bin grid + clip detail + shot detail + frame serving."""
        with tempfile.TemporaryDirectory() as tmp:
            project_root = os.path.join(tmp, "demo-project-aabbccdd")
            clip_dir = os.path.join(project_root, "clips", "demo-clip")
            os.makedirs(os.path.join(clip_dir, "frames"), exist_ok=True)
            report = {
                "clip": {"clip_id": "clip-rev-1", "clip_name": "Demo.mov"},
                "analyzed_at": "2026-05-19T10:00:00Z",
                "technical": {"video": [{"duration_seconds": 6.0}]},
                "motion": {"analysis_keyframes": [
                    {"index": 1, "time_seconds": 0.1, "selection_reason": "shot_start"},
                    {"index": 2, "time_seconds": 3.0, "selection_reason": "shot_progress"},
                ]},
                "visual": {
                    "clip_summary": "Test summary.",
                    "editorial_classification": {"primary_use": "establishing", "select_potential": "high"},
                    "editing_notes": {"search_tags": ["test"]},
                    "shot_descriptions": [
                        {
                            "shot_index": 0,
                            "description": "Wide shot.",
                            "time_seconds_start": 0.0,
                            "time_seconds_end": 6.0,
                            "frame_indices_used": [1, 2],
                            "visual": {"shot_size": "wide"},
                        },
                    ],
                },
            }
            with open(os.path.join(clip_dir, "analysis.json"), "w") as h:
                json.dump(report, h)
            jpeg = b"\xff\xd8\xff\xd9"
            with open(os.path.join(clip_dir, "frames", "sampled_0001.jpg"), "wb") as h:
                h.write(jpeg)

            listing = list_analyzed_clips(project_root)
            self.assertTrue(listing["success"])
            self.assertEqual(listing["count"], 1)
            self.assertEqual(listing["clips"][0]["clip_id"], "clip-rev-1")
            self.assertGreaterEqual(listing["clips"][0]["representative_frame_index"], 1)

            detail = get_analyzed_clip(project_root, "clip-rev-1")
            self.assertTrue(detail["success"])
            self.assertEqual(detail["shot_count"], 1)
            self.assertEqual(detail["clip_summary"], "Test summary.")

            shot = get_analyzed_clip_shot(project_root, "clip-rev-1", 0)
            self.assertTrue(shot["success"])
            self.assertEqual(shot["shot"]["description"], "Wide shot.")
            self.assertEqual(len(shot["frames"]), 2)

            self.assertIsNotNone(get_clip_frame_path(project_root, "clip-rev-1", 1))
            self.assertIsNone(get_clip_frame_path(project_root, "clip-rev-1", 99))

            corrections = read_clip_corrections(project_root, "clip-rev-1")
            self.assertTrue(corrections["success"])
            self.assertEqual(corrections["current_field_count"], 0)

    def test_review_api_follows_reusable_batch_report_paths(self):
        """Review API includes reusable reports referenced by the active project's job DB."""
        with tempfile.TemporaryDirectory() as tmp:
            active_root = os.path.join(tmp, "active-project-aabbccdd")
            source_root = os.path.join(tmp, "source-project-eeff001122")
            clip_dir = os.path.join(source_root, "clips", "reused-clip")
            os.makedirs(os.path.join(clip_dir, "frames"), exist_ok=True)
            report_path = os.path.join(clip_dir, "analysis.json")
            report = {
                "clip": {"clip_id": "clip-reused-1", "clip_name": "Reused.mov"},
                "analyzed_at": "2026-05-19T10:00:00Z",
                "technical": {"video": [{"duration_seconds": 6.0}]},
                "motion": {"analysis_keyframes": [
                    {"index": 1, "time_seconds": 0.1, "selection_reason": "shot_start"},
                ]},
                "visual": {
                    "clip_summary": "Reusable summary.",
                    "editorial_classification": {"primary_use": "b_roll", "select_potential": "medium"},
                    "editing_notes": {"search_tags": ["reused"]},
                    "shot_descriptions": [
                        {
                            "shot_index": 1,
                            "description": "Reusable shot.",
                            "time_seconds_start": 0.0,
                            "time_seconds_end": 6.0,
                            "frame_indices_used": [1],
                        },
                    ],
                },
            }
            with open(report_path, "w", encoding="utf-8") as handle:
                json.dump(report, handle)
            with open(os.path.join(clip_dir, "frames", "sampled_0001.jpg"), "wb") as handle:
                handle.write(b"\xff\xd8\xff\xd9")

            os.makedirs(active_root, exist_ok=True)
            conn = sqlite3.connect(os.path.join(active_root, "jobs.sqlite"))
            try:
                conn.execute(
                    "CREATE TABLE job_clips (clip_key TEXT, report_path TEXT, status TEXT, updated_at TEXT)"
                )
                conn.execute(
                    "INSERT INTO job_clips (clip_key, report_path, status, updated_at) VALUES (?, ?, ?, ?)",
                    ("reused-clip", report_path, "skipped", "2026-05-19T11:00:00Z"),
                )
                conn.commit()
            finally:
                conn.close()

            listing = list_analyzed_clips(active_root)
            self.assertTrue(listing["success"])
            self.assertEqual(listing["count"], 1)
            self.assertEqual(listing["clips"][0]["clip_id"], "clip-reused-1")

            detail = get_analyzed_clip(active_root, "clip-reused-1")
            self.assertTrue(detail["success"])
            self.assertEqual(detail["clip_summary"], "Reusable summary.")

            self.assertIsNotNone(get_clip_frame_path(active_root, "clip-reused-1", 1))

            index = build_analysis_index(active_root)
            self.assertTrue(index["success"])
            self.assertEqual(index["counts"]["clips"], 1)
            search = query_analysis_index(active_root, "Reusable", limit=5)
            self.assertTrue(search["success"])
            self.assertGreaterEqual(search["result_count"], 1)

    def test_commit_visual_analysis_preserves_human_corrections(self):
        """V2 trust-but-fix-optionally contract: re-analysis preserves human edits."""
        with tempfile.TemporaryDirectory() as tmp:
            project_root = os.path.join(tmp, "project-root")
            clip_dir = os.path.join(project_root, "clips", "demo-clip")
            os.makedirs(clip_dir, exist_ok=True)
            existing = {
                "success": True,
                "clip": {"clip_id": "clip-cor-1", "clip_name": "A001.mov", "file_path": "/tmp/A001.mov"},
                "technical": {"video": [{"frame_rate": 24}]},
                "readthrough": {"scenes": {"items": []}, "cut_analysis": {"cut_points": [], "shot_ranges": []}},
                "motion": {"analysis_keyframes": [], "overall_motion_level": "low"},
                "transcription": {"success": True, "segments": []},
                "visual": {
                    "success": True,
                    "status": "pending_host_analysis",
                    "provider": HOST_CHAT_PATHS_PROVIDER,
                },
                "analysis_profile": {"vision_enabled": True, "transcription_enabled": False},
            }
            with open(os.path.join(clip_dir, "analysis.json"), "w", encoding="utf-8") as handle:
                json.dump(existing, handle)

            # Editor previously corrected the editorial_classification.primary_use
            # for the clip, and a shot-level visual.shot_size for shot_index=0.
            corrections = {
                "schema_version": "2.0",
                "clip_id": "clip-cor-1",
                "current": {
                    "clip:clip-cor-1:editorial_classification.primary_use": {
                        "value": "interview",
                        "source": "human",
                        "author": "sam@bradfordoperations.com",
                        "timestamp": "2026-05-19T10:00:00Z",
                    },
                    "shot:0:visual.shot_size": {
                        "value": "medium_close",
                        "source": "human",
                        "author": "sam@bradfordoperations.com",
                        "timestamp": "2026-05-19T10:01:00Z",
                    },
                },
                "changelog": [],
            }
            with open(os.path.join(clip_dir, "corrections.json"), "w", encoding="utf-8") as handle:
                json.dump(corrections, handle)

            # Machine re-analysis tries to overwrite with different values.
            result = commit_visual_analysis(
                project_root=project_root,
                clip_id="clip-cor-1",
                visual={
                    "clip_summary": "Reanalyzed clip summary.",
                    "editorial_classification": {
                        "primary_use": "establishing",
                        "select_potential": "low",
                        "reason": "machine reread",
                    },
                    "shot_descriptions": [
                        {"shot_index": 0, "description": "Wide opening shot.", "visual": {"shot_size": "wide"}},
                    ],
                },
            )

            self.assertTrue(result["success"], msg=result.get("error"))
            metrics = result.get("corrections") or {}
            self.assertEqual(metrics.get("preserved_count"), 2)
            self.assertGreaterEqual(metrics.get("changelog_added"), 2)

            with open(result["analysis_json"], "r", encoding="utf-8") as handle:
                updated = json.load(handle)
            self.assertEqual(updated["visual"]["editorial_classification"]["primary_use"], "interview")
            shot_zero = next(
                s for s in updated["visual"]["shot_descriptions"]
                if s.get("shot_index") == 0
            )
            self.assertEqual(shot_zero["visual"]["shot_size"], "medium_close")
            # Machine description on the same shot is not a human-edited field, so it sticks
            self.assertEqual(shot_zero.get("description"), "Wide opening shot.")

            with open(os.path.join(clip_dir, "corrections.json"), "r", encoding="utf-8") as handle:
                updated_corrections = json.load(handle)
            reasons = {entry.get("change_reason") for entry in updated_corrections["changelog"]}
            self.assertIn("preserved across re-analysis", reasons)

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

    def test_publish_metadata_marker_candidates_built_but_writeback_gated_off_in_v2(self):
        prefs_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(prefs_tmp.cleanup)
        previous_prefs = os.environ.get("DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS")
        os.environ["DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS"] = os.path.join(prefs_tmp.name, "prefs.json")

        def restore_prefs_env():
            if previous_prefs is None:
                os.environ.pop("DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS", None)
            else:
                os.environ["DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS"] = previous_prefs

        self.addCleanup(restore_prefs_env)

        report = {
            "clip": {"clip_id": "clip-123"},
            "visual": {
                "editing_notes": {
                    "best_moments": ["00:00:04 strong answer"],
                    "qc_flags": ["00:00:05:12 small audio pop"],
                },
            },
            "clip_analysis_markers": {
                "markers": [
                    {
                        "id": "shot-001",
                        "type": "shot",
                        "name": "Shot 001",
                        "color": "Blue",
                        "start_frame": 0,
                        "duration_frames": 48,
                        "visual_description": "Wide shot in a driveway.",
                        "source": "scene_detection",
                    },
                    {
                        "id": "black-or-title-001",
                        "type": "qc_warning",
                        "subtype": "black_or_title",
                        "name": "QC: Black/Very Dark Range",
                        "color": "Red",
                        "start_frame": 48,
                        "duration_frames": 12,
                        "visual_description": "Detected black or very dark picture.",
                        "source": "blackdetect",
                    },
                ],
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

        # V2 architecture: machine markers (per-shot, qc_warning, best_moment) are
        # dropped from Resolve writeback entirely. The marker candidate list is
        # still built (it's persisted to clip_analysis_markers.json and consumed
        # by the DB / control panel), but the writeback gate (`enabled`) is
        # always False so nothing is added to Resolve clip markers.
        self.assertFalse(disabled["enabled"])
        self.assertFalse(unconfirmed["enabled"], "V2 gate disables writeback regardless of write_markers=True")
        self.assertFalse(enabled["enabled"], "V2 gate disables writeback even with slate visually confirmed")

        # The candidate list itself still contains the expected markers — only
        # the writeback step is gated. This keeps the DB/control-panel path
        # working while removing the Resolve-side clutter.
        self.assertIn("Shot 001", [marker["name"] for marker in unconfirmed["markers"]])
        self.assertIn("QC: Black/Very Dark Range", [marker["name"] for marker in unconfirmed["markers"]])
        self.assertIn("Best Moment", [marker["name"] for marker in unconfirmed["markers"]])
        self.assertIn("QC Warning", [marker["name"] for marker in unconfirmed["markers"]])
        self.assertEqual(unconfirmed["skipped"][0]["reason"], "slate_not_visually_confirmed")
        self.assertEqual([marker["name"] for marker in enabled["markers"]], [
            "Shot 001",
            "Slate Clap",
            "QC: Black/Very Dark Range",
            "Best Moment",
            "QC Warning",
        ])
        self.assertEqual([marker["frame"] for marker in enabled["markers"]], [0, 30, 48, 96, 132])

        # _apply_media_analysis_clip_markers is unit-callable and still works
        # when invoked directly with a marker list — it's just that the publish
        # path never calls it under V2 because the writeback gate is off.
        clip = MarkerClipStub()
        applied = _apply_media_analysis_clip_markers(clip, enabled["markers"], {})
        self.assertTrue(applied["success"])
        self.assertEqual(len(clip.GetMarkers()), 5)

        with tempfile.TemporaryDirectory() as tmp:
            previous = os.environ.get("DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS")
            os.environ["DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS"] = os.path.join(tmp, "prefs.json")
            try:
                self.assertTrue(_media_analysis_publish_confirmed({"write_markers": True, "dry_run": False}))
                setup("set_defaults", {"ask_before_metadata_publish": True})
                self.assertFalse(_media_analysis_publish_confirmed({"write_markers": True, "dry_run": False}))
            finally:
                if previous is None:
                    os.environ.pop("DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS", None)
                else:
                    os.environ["DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS"] = previous

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

    def test_timed_marker_decision_records_choice_but_v2_gate_disables_writeback(self):
        """V2 architecture drops per-shot/qc/best_moment machine markers.

        `_media_analysis_timed_marker_decision` still records the user's choice
        and saved-default preferences (so the API surface is unchanged), but
        the V2 gate (V2_MACHINE_MARKER_WRITEBACK_ENABLED=False) forces
        `enabled=False` and `prompt_required=False` regardless of the
        underlying choice. The saved-default preference is still persisted for
        forward-compat when the gate is reopened.
        """
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.environ.get("DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS")
            os.environ["DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS"] = os.path.join(tmp, "prefs.json")
            try:
                defaulted = _media_analysis_timed_marker_decision({})
                self.assertFalse(defaulted["enabled"])
                self.assertFalse(defaulted["prompt_required"])
                self.assertEqual(defaulted["source"], "v2_disabled")

                ask = _media_analysis_timed_marker_decision({"timed_markers": "ask"})
                self.assertFalse(ask["enabled"])
                self.assertFalse(ask["prompt_required"])
                self.assertEqual(ask["source"], "v2_disabled")

                yes = _media_analysis_timed_marker_decision({"timed_markers": "yes"})
                self.assertFalse(yes["enabled"])
                self.assertEqual(yes["source"], "v2_disabled")

                default_yes = _media_analysis_timed_marker_decision({"timed_markers": "default_yes"})
                self.assertFalse(default_yes["enabled"])
                self.assertEqual(default_yes["saved_default"], "yes")

                saved = _media_analysis_timed_marker_decision({})
                self.assertFalse(saved["enabled"])
                self.assertFalse(saved["prompt_required"])

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
                            "metadata_writeback_default": False,
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
                self.assertFalse(configured["defaults"]["media_analysis"]["metadata_writeback_default"])
                self.assertEqual(configured["defaults"]["updates"]["mode"], "notify")
                self.assertEqual(configured["defaults"]["updates"]["check_interval_hours"], 6)
                self.assertEqual(configured["defaults"]["updates"]["snooze_hours"], 3)

                applied = _media_analysis_apply_setup_defaults("publish_clip_metadata", {"confirm": True})
                self.assertFalse(applied["publish_metadata"])
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
                # After clear_defaults, timed_markers_default falls back to the
                # server default ("ask"), which is normalized to None in the
                # effective-prefs response (only "yes"/"no" survive).
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

    def test_media_analysis_defaults_turn_on_host_chat_paths_vision(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.environ.get("DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS")
            os.environ["DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS"] = os.path.join(tmp, "prefs.json")
            try:
                applied = _media_analysis_apply_setup_defaults("analyze_clip", {})
                self.assertEqual(applied["vision"], {"enabled": True, "provider": HOST_CHAT_PATHS_PROVIDER})
                self.assertEqual(applied["transcription"], {"enabled": True, "allow_model_download": True})
                self.assertTrue(applied["publish_metadata"])
                self.assertTrue(_media_analysis_metadata_writeback_enabled(applied))
                self.assertEqual(applied["_setup_defaults_applied"]["vision_default"], "on")
                self.assertEqual(applied["_setup_defaults_applied"]["transcription_default"], "yes")
                self.assertTrue(applied["_setup_defaults_applied"]["metadata_writeback_default"])

                with open(os.environ["DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS"], "w", encoding="utf-8") as handle:
                    json.dump({"transcription_default": "bogus"}, handle)
                self.assertEqual(_media_analysis_effective_preferences()["transcription_default"], "yes")

                writeback_off = _media_analysis_apply_setup_defaults("analyze_clip", {"publish_metadata": False})
                self.assertFalse(_media_analysis_metadata_writeback_enabled(writeback_off))

                visuals_off = _media_analysis_apply_setup_defaults("analyze_clip", {"include_visuals": False})
                self.assertEqual(visuals_off["vision"], {"enabled": False})
                self.assertFalse(visuals_off["_setup_defaults_applied"]["include_visuals"])

                visuals_on = _media_analysis_apply_setup_defaults("analyze_clip", {"includeVisuals": True})
                self.assertEqual(visuals_on["vision"], {"enabled": True, "provider": HOST_CHAT_PATHS_PROVIDER})
                self.assertTrue(visuals_on["_setup_defaults_applied"]["include_visuals"])

                vision_bool = _media_analysis_apply_setup_defaults("analyze_clip", {"vision": True})
                self.assertEqual(vision_bool["vision"], {"enabled": True, "provider": HOST_CHAT_PATHS_PROVIDER})
                self.assertTrue(vision_bool["_setup_defaults_applied"]["vision_shorthand"])

                vision_false = _media_analysis_apply_setup_defaults("analyze_clip", {"vision": False})
                self.assertEqual(vision_false["vision"], {"enabled": False})
                self.assertFalse(vision_false["_setup_defaults_applied"]["vision_shorthand"])

                transcription_on = _media_analysis_apply_setup_defaults("analyze_clip", {"include_transcription": True})
                self.assertEqual(transcription_on["transcription"], {"enabled": True, "allow_model_download": True})
                self.assertTrue(transcription_on["_setup_defaults_applied"]["include_transcription"])

                publish_defaults = _media_analysis_apply_setup_defaults("publish_clip_metadata", {})
                self.assertFalse(publish_defaults["dry_run"])
                self.assertTrue(publish_defaults["confirm"])
                self.assertEqual(publish_defaults["fields"], [
                    "Description",
                    "Comments",
                    "Keywords",
                    "People",
                    "Scene",
                    "Shot",
                    "Take",
                    "Camera #",
                    "Roll Card #",
                ])
                self.assertEqual(publish_defaults["slate_detection"]["enabled"], True)
            finally:
                if previous is None:
                    os.environ.pop("DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS", None)
                else:
                    os.environ["DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS"] = previous

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
                    "transcription": {"enabled": False},
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

    def test_build_plan_hints_when_transcription_available_but_explicitly_disabled(self):
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
                    "transcription": {"enabled": False},
                },
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

    def test_build_plan_defaults_transcription_on_for_standard_depth(self):
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
                    "transcription": {"available": True, "backends": ["mock"]},
                    "vision": {"available": False},
                },
            )

        self.assertTrue(plan["success"])
        self.assertEqual(plan["capability_gaps"], [])
        self.assertTrue(plan["clips"][0]["analysis_signature"]["layers"]["transcription"]["enabled"])
        self.assertIn("transcript_json", plan["clips"][0]["artifacts"])

    def test_build_plan_blocks_default_transcription_when_backend_missing(self):
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
                    "transcription": {"available": False, "backends": []},
                    "vision": {"available": False},
                },
            )
            response = _media_analysis_missing_capabilities_response(plan)

        self.assertTrue(plan["success"])
        self.assertIn({"capability": "transcription_backend", "required_for": ["transcription"]}, plan["capability_gaps"])
        self.assertIn("transcription", plan["install_guidance"]["missing"])
        self.assertFalse(response["success"])
        self.assertEqual(response["status"], "missing_required_capabilities")
        self.assertIn("install", response["next_step"].lower())

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
                "transcription": {"enabled": False},
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
                {"transcription": {"enabled": False}, "vision": {}},
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
                    "transcription": {"enabled": False},
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
            signature = analysis_request_signature(record, "standard", {"transcription": {"enabled": False}, "vision": {}}, 8)
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
                    "transcription": {"enabled": False},
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

    def test_build_plan_searches_related_project_roots_by_default(self):
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
            report_path = os.path.join(clip_dir, "analysis.json")
            signature = analysis_request_signature(record, "standard", {"transcription": {"enabled": False}, "vision": {}}, 8)
            with open(report_path, "w", encoding="utf-8") as handle:
                json.dump({
                    "success": True,
                    "analysis_version": "0.2",
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
                    "transcription": {"enabled": False},
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
        self.assertIn(previous_root, plan["related_project_roots"])
        self.assertIn(previous_root, plan["reuse_project_roots"])
        self.assertEqual(plan["reusable_clip_count"], 1)
        self.assertTrue(plan["clips"][0]["skip_execution"])
        self.assertEqual(plan["clips"][0]["existing_report"]["path"], report_path)

    def test_build_plan_can_disable_related_project_root_search(self):
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
            os.makedirs(os.path.join(previous_root, "clips", stable_clip_directory(record)))
            with open(os.path.join(previous_root, "clips", stable_clip_directory(record), "analysis.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "success": True,
                    "analysis_version": "0.2",
                    "analysis_signature": analysis_request_signature(record, "standard", {"transcription": {"enabled": False}, "vision": {}}, 8),
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
                    "transcription": {"enabled": False},
                    "search_related_project_roots": False,
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
        self.assertEqual(plan["related_project_roots"], [])
        self.assertEqual(plan["reusable_clip_count"], 0)
        self.assertEqual(plan["clips"][0]["cache_status"], "miss")

    def test_build_plan_reuses_report_path_from_clip_record_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source", "A001_C001.mov")
            os.makedirs(os.path.dirname(source))
            with open(source, "wb") as handle:
                handle.write(b"current")
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
            record = {
                "clip_id": "clip-current-version",
                "clip_name": "A001_C001.mov",
                "file_path": source,
                "media_id": "media-current-version",
            }
            clip_dir = os.path.join(previous_root, "clips", stable_clip_directory(record))
            os.makedirs(clip_dir)
            report_path = os.path.join(clip_dir, "analysis.json")
            signature = analysis_request_signature(record, "standard", {"transcription": {"enabled": False}, "vision": {}}, 8)
            with open(report_path, "w", encoding="utf-8") as handle:
                json.dump({
                    "success": True,
                    "analysis_version": "0.2",
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

            record_with_metadata = {
                **record,
                "analysis_report_path": report_path,
                "published_analysis_signature": signature["signature_hash"],
            }
            plan = build_plan(
                project_name="Example Project",
                project_id="version-002",
                records=[record_with_metadata],
                target={"type": "clips", "clip_ids": ["clip-current-version"]},
                params={
                    "analysis_root": analysis_root,
                    "depth": "standard",
                    "transcription": {"enabled": False},
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
        self.assertEqual(plan["clips"][0]["existing_report"]["path"], report_path)
        self.assertEqual(plan["clips"][0]["existing_report"]["project_root"], previous_root)
        self.assertEqual(plan["clips"][0]["existing_report"]["source"], "record_analysis_report_path")
        self.assertIn("Resolve clip metadata", plan["clips"][0]["reuse_reason"])

    def test_records_from_target_carries_published_analysis_report_path(self):
        clip = ClipStub(
            "A001_C001.mov",
            "clip-123",
            "/tmp/A001_C001.mov",
            third_party={
                "davinci_resolve_mcp.analysis_report_path": "/tmp/analysis/project/clips/a001/analysis.json",
                "davinci_resolve_mcp.analysis_signature": "abc123",
                "davinci_resolve_mcp.published_at": "2026-05-17T12:00:00Z",
            },
        )
        mp = MarkerMediaPoolStub([clip])

        records, target, warnings, err = _media_analysis_records_from_target(
            mp,
            {"target": {"type": "clip", "clip_id": "clip-123"}},
        )

        self.assertIsNone(err)
        self.assertEqual(warnings, [])
        self.assertEqual(target["type"], "clip")
        self.assertEqual(records[0]["analysis_report_path"], "/tmp/analysis/project/clips/a001/analysis.json")
        self.assertEqual(records[0]["published_analysis_signature"], "abc123")
        self.assertEqual(records[0]["published_analysis_at"], "2026-05-17T12:00:00Z")

    def test_records_from_target_flags_standard_metadata_provenance(self):
        clip = ClipStub(
            "A001_C001.mov",
            "clip-123",
            "/tmp/A001_C001.mov",
            metadata={
                "Comments": "Assistant note\n\n[DaVinci Resolve MCP Analysis]\nold\n[/DaVinci Resolve MCP Analysis]",
            },
        )
        mp = MarkerMediaPoolStub([clip])

        records, _, warnings, err = _media_analysis_records_from_target(
            mp,
            {"target": {"type": "clip", "clip_id": "clip-123"}},
        )

        self.assertIsNone(err)
        self.assertEqual(warnings, [])
        self.assertTrue(records[0]["analysis_metadata_present"])
        self.assertEqual(records[0]["analysis_metadata_fields"], ["Comments"])
        self.assertIn("standard_metadata_fields", records[0]["analysis_provenance"])

    def test_build_plan_reuses_global_registry_when_related_search_disabled(self):
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
            clip_dir = os.path.join(previous_root, "clips", stable_clip_directory(record))
            os.makedirs(clip_dir)
            report_path = os.path.join(clip_dir, "analysis.json")
            signature = analysis_request_signature(record, "standard", {"transcription": {"enabled": False}, "vision": {}}, 8)
            with open(report_path, "w", encoding="utf-8") as handle:
                json.dump({
                    "success": True,
                    "analysis_version": "0.2",
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
            registry = update_analysis_registry(previous_root, report_paths=[report_path])
            self.assertTrue(registry["success"])

            plan = build_plan(
                project_name="Example Project",
                project_id="version-002",
                records=[record],
                target={"type": "clips", "clip_ids": ["clip-current-version"]},
                params={
                    "analysis_root": analysis_root,
                    "depth": "standard",
                    "transcription": {"enabled": False},
                    "search_related_project_roots": False,
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
        self.assertEqual(plan["related_project_roots"], [])
        self.assertEqual(plan["reusable_clip_count"], 1)
        self.assertTrue(plan["clips"][0]["skip_execution"])
        self.assertEqual(plan["clips"][0]["existing_report"]["source"], "analysis_registry")
        self.assertEqual(plan["reuse_summary"]["sources"]["analysis_registry"], 1)

    def test_plan_blocks_silent_reanalysis_when_provenance_report_missing(self):
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
                "analysis_report_path": os.path.join(tmp, "analysis", "missing", "clips", "a001", "analysis.json"),
                "published_analysis_signature": "abc123",
            }
            plan = build_plan(
                project_name="Example Project",
                project_id="version-002",
                records=[record],
                target={"type": "clips", "clip_ids": ["clip-current-version"]},
                params={
                    "analysis_root": os.path.join(tmp, "analysis"),
                    "depth": "standard",
                    "transcription": {"enabled": False},
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
            executed = execute_plan(plan, params={"transcription": {"enabled": False}}, capabilities={
                "tools": {
                    "ffprobe": {"available": True},
                    "ffmpeg": {"available": True},
                },
                "transcription": {"available": False},
                "vision": {"available": False},
            })

        self.assertTrue(plan["success"])
        self.assertEqual(plan["reuse_blocked_clip_count"], 1)
        self.assertEqual(plan["clips"][0]["cache_status"], "reuse_blocked")
        self.assertIn("analysis_report_path_missing", plan["clips"][0]["reuse_block_issues"])
        self.assertFalse(executed["success"])
        self.assertEqual(executed["status"], "reuse_blocked")

    def test_force_refresh_bypasses_reuse_block(self):
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
                "analysis_report_path": os.path.join(tmp, "analysis", "missing", "clips", "a001", "analysis.json"),
                "published_analysis_signature": "abc123",
            }

            plan = build_plan(
                project_name="Example Project",
                project_id="version-002",
                records=[record],
                target={"type": "clips", "clip_ids": ["clip-current-version"]},
                params={
                    "analysis_root": os.path.join(tmp, "analysis"),
                    "depth": "standard",
                    "transcription": {"enabled": False},
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
        self.assertEqual(plan["reuse_blocked_clip_count"], 0)
        self.assertEqual(plan["clips"][0]["cache_status"], "refresh_forced")

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
                    "transcription": {"enabled": False},
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
            self.assertTrue(clip_report["clip_analysis_markers"]["write_to_resolve_default"])
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
            self.assertTrue(marker_plan_json["resolve_marker_writeback"]["enabled"])
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

    def test_execute_emits_pending_host_analysis_when_vision_requested(self):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("ffmpeg/ffprobe not installed")
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = os.path.join(tmp, "source")
            analysis_dir = os.path.join(tmp, "davinci-resolve-mcp-analysis")
            os.makedirs(source_dir)
            source = os.path.join(source_dir, "synthetic_requires_vision.mp4")
            self._write_synthetic_media(source)

            records = [{
                "clip_id": "clip-requires-vision",
                "clip_name": "synthetic_requires_vision.mp4",
                "file_path": source,
                "media_id": "media-requires-vision",
            }]
            params = {
                "analysis_root": analysis_dir,
                "depth": "standard",
                "dry_run": False,
                "session_only": True,
                "cleanup_frames": False,
                "max_analysis_frames": 1,
                "transcription": {"enabled": False},
                "vision": {"enabled": True, "provider": HOST_CHAT_PATHS_PROVIDER},
            }
            caps = detect_capabilities(env={})
            plan = build_plan(
                project_name="Example Project",
                project_id="project-requires-vision",
                records=records,
                target={"type": "file", "path": source},
                params=params,
                capabilities=caps,
            )

            manifest = execute_plan(plan, params=params, capabilities=caps)

            self.assertTrue(plan["success"])
            self.assertTrue(manifest["success"])
            self.assertTrue(manifest["vision_pending"])
            self.assertEqual(manifest["vision_pending_clip_count"], 1)
            self.assertEqual(manifest["successful_clip_count"], 1)
            self.assertEqual(manifest["failed_clip_count"], 0)
            self.assertEqual(manifest["pending_action"]["action"], "commit_vision")
            clip_row = manifest["clips"][0]
            self.assertEqual(clip_row["vision_status"], "pending_host_analysis")
            self.assertEqual(clip_row["visual"]["provider"], HOST_CHAT_PATHS_PROVIDER)
            self.assertTrue(clip_row["visual"]["frame_paths"])
            self.assertEqual(clip_row["visual"]["commit_action"]["action"], "commit_vision")
            self.assertEqual(sorted(os.listdir(source_dir)), ["synthetic_requires_vision.mp4"])

    def test_execute_with_custom_vision_runner_writes_structured_visual_report(self):
        """A custom vision_runner (e.g. a future provider) can short-circuit the
        host_chat_paths deferred payload and return a final visual report directly.
        The runner contract: same signature as before, return dict matches schema."""
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("ffmpeg/ffprobe not installed")
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = os.path.join(tmp, "source")
            analysis_dir = os.path.join(tmp, "davinci-resolve-mcp-analysis")
            os.makedirs(source_dir)
            source = os.path.join(source_dir, "synthetic_custom_runner.mp4")
            self._write_synthetic_media(source)

            records = [{
                "clip_id": "clip-custom-runner",
                "clip_name": "synthetic_custom_runner.mp4",
                "file_path": source,
                "media_id": "media-custom-runner",
            }]
            params = {
                "analysis_root": analysis_dir,
                "depth": "standard",
                "dry_run": False,
                "session_only": True,
                "cleanup_frames": True,
                "max_analysis_frames": 3,
                "transcription": {"enabled": False},
                "vision": {"enabled": True, "provider": HOST_CHAT_PATHS_PROVIDER},
            }
            caps = detect_capabilities(env={})
            plan = build_plan(
                project_name="Example Project",
                project_id="project-custom-runner",
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
                    "provider": "custom_test_runner",
                    "clip_summary": "Custom-runner visual report.",
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
                        "search_tags": ["custom-runner"],
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
            self.assertFalse(manifest["vision_pending"])
            self.assertTrue(manifest["artifacts_cleaned_up"])
            self.assertEqual(manifest["reports"][0]["visual"]["provider"], "custom_test_runner")
            self.assertEqual(manifest["reports"][0]["visual"]["editing_notes"]["search_tags"], ["custom-runner"])
            self.assertFalse(os.path.exists(plan["output_root"]["project_root"]))
            self.assertEqual(sorted(os.listdir(source_dir)), ["synthetic_custom_runner.mp4"])

    def test_reused_report_is_ingested_into_current_root_db(self):
        """Cross-root report reuse must land DB rows + a lockstep export in
        the CURRENT root, keyed to the CURRENT project's clip identity —
        otherwise media_ref lookups (edit_engine planners, panel readers)
        find nothing while the manifest claims success (Phase 3 pilot bug)."""
        from tests.test_analysis_store import make_report
        from src.utils import analysis_store, timeline_brain_db

        with tempfile.TemporaryDirectory() as tmp:
            source_dir = os.path.join(tmp, "source")
            os.makedirs(source_dir)
            source = os.path.join(source_dir, "sample clip.mp4")
            with open(source, "wb") as handle:
                handle.write(b"placeholder")
            # A prior report in ANOTHER project's root, under the OLD clip id.
            other_root = os.path.join(tmp, "other-root")
            other_clip_dir = os.path.join(other_root, "clips", "old-dir")
            os.makedirs(other_clip_dir)
            prior = make_report()
            prior["clip"] = dict(prior["clip"], clip_id="old-resolve-id", file_path=source)
            prior_path = os.path.join(other_clip_dir, "analysis.json")
            with open(prior_path, "w", encoding="utf-8") as handle:
                json.dump(prior, handle)

            analysis_dir = os.path.join(tmp, "analysis-root")
            record = {
                "clip_id": "new-resolve-id",
                "clip_name": "Sample Clip.mp4",
                "file_path": source,
                "media_id": "new-media-id",
            }
            plan = build_plan(
                project_name="Reuse Project",
                project_id="project-reuse-db",
                records=[record],
                target={"type": "file", "path": source},
                params={"analysis_root": analysis_dir, "depth": "standard",
                        "session_only": True},
                capabilities=detect_capabilities(env={}),
            )
            # Force the reuse path the way the registry matcher would.
            clip_plan = plan["clips"][0]
            clip_plan["skip_execution"] = True
            clip_plan["cache_status"] = "reusable"
            clip_plan["existing_report"] = {"path": prior_path}

            manifest = asyncio.run(execute_plan_async(plan, params={"depth": "standard"}))
            self.assertTrue(manifest["success"], manifest)
            row = manifest["clips"][0]
            self.assertTrue(row["reused"])
            project_root = plan["output_root"]["project_root"]
            # The export now lives in THIS root (provenance kept in reused_from).
            self.assertTrue(row["analysis_json"].startswith(project_root))
            self.assertTrue(os.path.isfile(row["analysis_json"]))
            self.assertEqual(row["reused_from"], prior_path)
            # DB rows landed under the CURRENT clip identity.
            self.addCleanup(timeline_brain_db.close_all)
            conn = timeline_brain_db.connect(project_root)
            clip_row = conn.execute(
                "SELECT resolve_clip_id, file_path FROM clips"
            ).fetchone()
            self.assertIsNotNone(clip_row)
            self.assertEqual(clip_row["resolve_clip_id"], "new-resolve-id")
            self.assertGreater(
                conn.execute("SELECT COUNT(*) FROM transcript_segments").fetchone()[0], 0)
            # The media_ref lookup the edit-engine planners depend on.
            self.assertIsNotNone(analysis_store.resolve_clip_uuid(conn, "new-resolve-id"))

    def test_executing_clips_helper_excludes_pure_reuse(self):
        """The capability gate must key off clips that still need fresh
        analysis, not the plan's requested-options gaps. A clip is exempt only
        when it both skips execution AND has an existing report path."""
        reused = {"skip_execution": True, "existing_report": {"path": "/x/a.json"}}
        fresh = {"skip_execution": False}
        # skip_execution flagged but no report path on disk -> still executes.
        no_path = {"skip_execution": True, "existing_report": {}}
        self.assertEqual(executing_clips({"clips": [reused]}), [])
        self.assertFalse(plan_requires_capabilities({"clips": [reused]}))
        self.assertEqual(executing_clips({"clips": [reused, fresh]}), [fresh])
        self.assertTrue(plan_requires_capabilities({"clips": [reused, fresh]}))
        self.assertEqual(executing_clips({"clips": [no_path]}), [no_path])
        self.assertTrue(plan_requires_capabilities({"clips": [no_path]}))
        self.assertFalse(plan_requires_capabilities({"clips": []}))

    def test_all_reused_plan_executes_despite_capability_gaps(self):
        """build_plan records capability_gaps from the requested options before
        the reuse decision runs. When every clip is satisfied by an existing
        reusable report, execution only re-keys/imports it — no fresh
        transcription/vision happens — so the missing-capability gate must NOT
        block. Regression for the gap the PR-68 inner fix left on the entry
        points (server analyze action, metadata publish, batch job creation)."""
        from tests.test_analysis_store import make_report
        from src.utils import timeline_brain_db

        with tempfile.TemporaryDirectory() as tmp:
            source_dir = os.path.join(tmp, "source")
            os.makedirs(source_dir)
            source = os.path.join(source_dir, "reuse clip.mp4")
            with open(source, "wb") as handle:
                handle.write(b"placeholder")
            prior_dir = os.path.join(tmp, "prior", "clips", "old-dir")
            os.makedirs(prior_dir)
            prior = make_report()
            prior["clip"] = dict(prior["clip"], clip_id="old-id", file_path=source)
            prior_path = os.path.join(prior_dir, "analysis.json")
            with open(prior_path, "w", encoding="utf-8") as handle:
                json.dump(prior, handle)

            record = {
                "clip_id": "new-id",
                "clip_name": "Reuse Clip.mp4",
                "file_path": source,
                "media_id": "new-media",
            }
            # Default transcription is on, but NO backend is available here ->
            # build_plan records a capability gap from the requested options.
            no_backend_caps = {
                "tools": {
                    "ffprobe": {"available": True},
                    "ffmpeg": {"available": True},
                },
                "transcription": {"available": False, "backends": []},
                "vision": {"available": False},
            }
            plan = build_plan(
                project_name="Reuse Gate",
                project_id="project-reuse-gate",
                records=[record],
                target={"type": "file", "path": source},
                params={"analysis_root": os.path.join(tmp, "analysis-root"),
                        "depth": "standard", "session_only": True},
                capabilities=no_backend_caps,
            )
            self.assertTrue(plan["capability_gaps"], plan)
            clip_plan = plan["clips"][0]
            clip_plan["skip_execution"] = True
            clip_plan["cache_status"] = "reusable"
            clip_plan["existing_report"] = {"path": prior_path}

            self.addCleanup(timeline_brain_db.close_all)
            manifest = asyncio.run(execute_plan_async(
                plan,
                params={"depth": "standard"},
                capabilities=no_backend_caps,
            ))
            self.assertTrue(manifest["success"], manifest)
            self.assertNotIn("capability_gaps", manifest)
            self.assertTrue(manifest["clips"][0]["reused"])

    def test_summarize_and_index_db_vs_json_parity(self):
        """Phase 5 — summarize_reports and build_analysis_index source from
        the DB-canonical store when the root is fully ingested, falling back
        WHOLESALE to the JSON walk otherwise. Both paths must be semantically
        identical: the export is lockstep with the DB by construction."""
        from tests.test_analysis_store import make_report
        from src.utils import analysis_store, timeline_brain_db
        from src.utils.media_analysis import (
            build_analysis_index, query_analysis_index, summarize_reports,
        )

        def _normalized(summary):
            out = json.loads(json.dumps(summary))
            out.pop("source", None)
            (out.get("provenance") or {}).pop("generated_at", None)
            out["technical_warnings"] = sorted(map(str, out.get("technical_warnings") or []))
            out["search_tags"] = sorted(out.get("search_tags") or [])
            prov = out.get("provenance") or {}
            prov["source_reports"] = sorted(
                prov.get("source_reports") or [], key=lambda r: str(r.get("clip_id")))
            prov["missing_reports"] = sorted(
                prov.get("missing_reports") or [], key=lambda r: str(r.get("report_path")))
            return out

        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "analysis-root")
            os.makedirs(root)
            self.addCleanup(timeline_brain_db.close_all)
            report = make_report()
            ingest = analysis_store.ingest_report(root, report, clip_dir="par-aaaaaaaaaaaa")
            self.assertTrue(ingest["success"], ingest)
            report_b = make_report()
            report_b["clip"] = dict(report_b["clip"], clip_id="parity-2", clip_name="B.mp4",
                                    file_path="/media/b.mp4", media_id="parity-2-m")
            ingest_b = analysis_store.ingest_report(root, report_b, clip_dir="par-bbbbbbbbbbbb")
            # The pipeline writes the lockstep export after ingest; mirror it.
            for clip_uuid, clip_dir in ((ingest["clip_uuid"], "par-aaaaaaaaaaaa"),
                                        (ingest_b["clip_uuid"], "par-bbbbbbbbbbbb")):
                target = os.path.join(root, "clips", clip_dir, "analysis.json")
                os.makedirs(os.path.dirname(target), exist_ok=True)
                self.assertTrue(analysis_store.export_report_file(root, clip_uuid, target))

            db_summary = summarize_reports(root)
            self.assertEqual(db_summary["source"], "db")
            self.assertEqual(db_summary["clip_reports"], 2)
            db_index = build_analysis_index(root)
            self.assertTrue(db_index["success"], db_index)
            self.assertEqual(db_index["report_sources"], {"db": 2, "json": 0})
            db_query = query_analysis_index(root, query="sample")

            # Force the JSON path by making the export unavailable.
            with unittest.mock.patch.object(analysis_store, "export_report", return_value=None):
                json_summary = summarize_reports(root)
                json_index = build_analysis_index(root)
            self.assertEqual(json_summary["source"], "json")
            self.assertEqual(json_index["report_sources"], {"db": 0, "json": 2})
            json_query = query_analysis_index(root, query="sample")

            self.assertEqual(_normalized(db_summary), _normalized(json_summary))
            self.assertEqual(db_index["counts"], json_index["counts"])
            self.assertEqual(
                [r.get("clip_id") for r in db_query.get("results") or []],
                [r.get("clip_id") for r in json_query.get("results") or []],
            )

    def test_summarize_mixed_root_falls_back_wholesale(self):
        from tests.test_analysis_store import make_report
        from src.utils import analysis_store, timeline_brain_db
        from src.utils.media_analysis import summarize_reports

        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "analysis-root")
            os.makedirs(root)
            self.addCleanup(timeline_brain_db.close_all)
            ingest = analysis_store.ingest_report(root, make_report(), clip_dir="mix-aaaaaaaaaaaa")
            target = os.path.join(root, "clips", "mix-aaaaaaaaaaaa", "analysis.json")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            self.assertTrue(analysis_store.export_report_file(root, ingest["clip_uuid"], target))
            # A second report on disk that was never ingested (mixed root).
            stray_dir = os.path.join(root, "clips", "mix-stray")
            os.makedirs(stray_dir)
            stray = make_report()
            stray["clip"] = dict(stray["clip"], clip_id="stray-1", clip_name="Stray.mp4",
                                 file_path="/media/stray.mp4")
            with open(os.path.join(stray_dir, "analysis.json"), "w", encoding="utf-8") as fh:
                json.dump(stray, fh)
            summary = summarize_reports(root)
            self.assertEqual(summary["source"], "json")
            self.assertEqual(summary["clip_reports"], 2)

    def test_summarize_pre_v9_root_uses_json(self):
        from tests.test_analysis_store import make_report
        from src.utils.media_analysis import summarize_reports

        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "analysis-root")
            clip_dir = os.path.join(root, "clips", "legacy-clip")
            os.makedirs(clip_dir)
            with open(os.path.join(clip_dir, "analysis.json"), "w", encoding="utf-8") as fh:
                json.dump(make_report(), fh)
            summary = summarize_reports(root)
            self.assertEqual(summary["source"], "json")
            self.assertEqual(summary["clip_reports"], 1)

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
        self.assertIn("Analysis index not found", (result["error"].get("message","") if isinstance(result["error"], dict) else result["error"]))

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
                params={"depth": "quick", "transcription": {"enabled": False}},
                name="Cancelable batch",
            )
            self.assertTrue(created["success"])
            job = created["job"]

            canceled = cancel_batch_job(job["project_root"], job["job_id"])
            self.assertEqual(canceled["status"], "canceled")
            resumed = resume_batch_job(job["project_root"], job["job_id"])
            self.assertEqual(resumed["status"], "queued")
            self.assertEqual(resumed["pending_clips"], 1)


class MediaAnalysisCoverageTests(unittest.TestCase):
    """Pre-flight coverage_report assessment used by editorial / color / online guardrails."""

    def _write_report(
        self,
        *,
        analysis_root: str,
        project_name: str,
        project_id: str,
        source: str,
        record: Dict[str, Any],
        depth: str = "standard",
        options: Optional[Dict[str, Any]] = None,
        analyzed_at: str = "2026-05-20T12:00:00Z",
        source_trust: str = "auto",
        with_transcription: bool = False,
        with_visual: bool = False,
        signature_override: Optional[Dict[str, Any]] = None,
    ) -> str:
        opts = options or {"transcription": {"enabled": with_transcription}, "vision": {"enabled": with_visual}}
        project_root = resolve_output_root(
            project_name=project_name,
            project_id=project_id,
            analysis_root=analysis_root,
            source_paths=[source],
            create=True,
        )["project_root"]
        clip_dir = os.path.join(project_root, "clips", stable_clip_directory(record))
        os.makedirs(clip_dir, exist_ok=True)
        report_path = os.path.join(clip_dir, "analysis.json")
        signature = signature_override or analysis_request_signature(record, depth, opts, 8)
        report = {
            "success": True,
            "analysis_version": "0.2",
            "analysis_signature": signature,
            "analysis_profile": {
                "depth": depth,
                "analysis_keyframe_budget": 8,
                "transcription_enabled": with_transcription,
                "vision_enabled": with_visual,
                "source_trust": source_trust,
            },
            "analyzed_at": analyzed_at,
            "source_file": source,
            "clip": record,
            "technical": {"format": {"duration_seconds": 1.0}},
            "readthrough": {"success": True, "cut_analysis": {"success": True}},
            "motion": {"success": True, "analysis_keyframes": [{"time_seconds": 0.0}], "overall_motion_level": "low"},
            "transcription": (
                {"success": True, "text": "hello world", "segments": [{"start": 0.0, "end": 1.0, "text": "hello world"}]}
                if with_transcription else {"success": True, "status": "skipped"}
            ),
            "visual": (
                {"success": True, "clip_summary": "A test clip.", "shot_descriptions": [{"shot_index": 1, "description": "Clip overview."}]}
                if with_visual else {"success": True, "status": "skipped"}
            ),
            "clip_analysis_markers": {"success": True, "marker_count": 1, "markers": []},
        }
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle)
        update_analysis_registry(project_root, report_paths=[report_path])
        return report_path

    def _base_capabilities(self) -> Dict[str, Any]:
        return {
            "tools": {"ffprobe": {"available": True}, "ffmpeg": {"available": True}},
            "transcription": {"available": False},
            "vision": {"available": False},
        }

    def test_coverage_report_empty_target_returns_zero_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            coverage = build_coverage_report(
                project_name="Empty Project",
                project_id="v1",
                records=[],
                target={"type": "bin", "path": "Master"},
                params={"analysis_root": os.path.join(tmp, "analysis"), "depth": "standard"},
                capabilities=self._base_capabilities(),
            )
        self.assertTrue(coverage["success"])
        self.assertEqual(coverage["summary"]["clips_total"], 0)
        self.assertEqual(coverage["summary"]["clips_analyzed"], 0)
        self.assertEqual(coverage["clips"], [])
        self.assertIn("evidence base: no clips in target", coverage["evidence_base"])

    def test_coverage_report_all_current_reports_100_percent(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source", "A001.mov")
            os.makedirs(os.path.dirname(source))
            with open(source, "wb") as handle:
                handle.write(b"x" * 100)
            record = {"clip_id": "clip-1", "clip_name": "A001.mov", "file_path": source, "media_id": "media-1"}
            analysis_root = os.path.join(tmp, "analysis")
            self._write_report(
                analysis_root=analysis_root,
                project_name="Current Project",
                project_id="v1",
                source=source,
                record=record,
                source_trust="medium",
            )

            coverage = build_coverage_report(
                project_name="Current Project",
                project_id="v1",
                records=[record],
                target={"type": "bin", "path": "Master"},
                params={
                    "analysis_root": analysis_root,
                    "depth": "standard",
                    "transcription": {"enabled": False},
                },
                capabilities=self._base_capabilities(),
            )
        self.assertTrue(coverage["success"])
        self.assertEqual(coverage["summary"]["clips_total"], 1)
        self.assertEqual(coverage["summary"]["clips_analyzed"], 1)
        self.assertEqual(coverage["summary"]["coverage_percent"], 100.0)
        self.assertEqual(coverage["summary"]["source_trust_distribution"], {"medium": 1})
        clip = coverage["clips"][0]
        self.assertTrue(clip["analyzed"])
        self.assertEqual(clip["cache_status"], "reusable")
        self.assertEqual(clip["source_trust"], "medium")
        self.assertIn("technical", clip["layers_present"])
        self.assertIn("motion", clip["layers_present"])
        self.assertIn("evidence base: 1/1 clips analyzed (100%)", coverage["evidence_base"])

    def test_coverage_report_flags_missing_transcription_layer(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source", "A001.mov")
            os.makedirs(os.path.dirname(source))
            with open(source, "wb") as handle:
                handle.write(b"x" * 100)
            record = {"clip_id": "clip-1", "clip_name": "A001.mov", "file_path": source, "media_id": "media-1"}
            analysis_root = os.path.join(tmp, "analysis")
            # Report exists but without transcription
            self._write_report(
                analysis_root=analysis_root,
                project_name="Missing Layer Project",
                project_id="v1",
                source=source,
                record=record,
                with_transcription=False,
            )

            # Request requires transcription — report is incomplete
            coverage = build_coverage_report(
                project_name="Missing Layer Project",
                project_id="v1",
                records=[record],
                target={"type": "bin", "path": "Master"},
                params={
                    "analysis_root": analysis_root,
                    "depth": "standard",
                    "transcription": {"enabled": True},
                },
                capabilities=self._base_capabilities(),
            )
        self.assertEqual(coverage["summary"]["clips_stale"], 1)
        clip = coverage["clips"][0]
        self.assertFalse(clip["analyzed"])
        self.assertIn("transcription", clip["missing_layers"])
        self.assertIn("missing layers", clip["recommended_action"])
        self.assertIn("transcription", clip["recommended_action"])

    def test_coverage_report_marks_signature_drift_as_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source", "A001.mov")
            os.makedirs(os.path.dirname(source))
            with open(source, "wb") as handle:
                handle.write(b"original")
            record = {"clip_id": "clip-1", "clip_name": "A001.mov", "file_path": source, "media_id": "media-1"}
            analysis_root = os.path.join(tmp, "analysis")
            # Persist report with the current signature.
            self._write_report(
                analysis_root=analysis_root,
                project_name="Signature Drift Project",
                project_id="v1",
                source=source,
                record=record,
            )
            # Now modify the source file so its mtime+size change → signature mismatch.
            import time as _time
            _time.sleep(0.05)
            with open(source, "wb") as handle:
                handle.write(b"changed bytes here change change change")

            coverage = build_coverage_report(
                project_name="Signature Drift Project",
                project_id="v1",
                records=[record],
                target={"type": "bin", "path": "Master"},
                params={
                    "analysis_root": analysis_root,
                    "depth": "standard",
                    "transcription": {"enabled": False},
                },
                capabilities=self._base_capabilities(),
            )
        clip = coverage["clips"][0]
        self.assertEqual(clip["cache_status"], "stale_or_incomplete")
        self.assertTrue(any("source_" in reason for reason in clip["staleness_reasons"]))
        self.assertEqual(coverage["summary"]["clips_stale"], 1)

    def test_coverage_report_surfaces_reuse_blocked_from_provenance_orphan(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source", "A001.mov")
            os.makedirs(os.path.dirname(source))
            with open(source, "wb") as handle:
                handle.write(b"x" * 100)
            record = {
                "clip_id": "clip-1",
                "clip_name": "A001.mov",
                "file_path": source,
                "media_id": "media-1",
                # Provenance claims a report exists, but the path is missing
                "analysis_report_path": os.path.join(tmp, "analysis", "ghost", "clips", "missing", "analysis.json"),
                "published_analysis_signature": "ghost-signature",
            }
            analysis_root = os.path.join(tmp, "analysis")

            coverage = build_coverage_report(
                project_name="Orphan Provenance Project",
                project_id="v1",
                records=[record],
                target={"type": "bin", "path": "Master"},
                params={
                    "analysis_root": analysis_root,
                    "depth": "standard",
                    "transcription": {"enabled": False},
                },
                capabilities=self._base_capabilities(),
            )
        clip = coverage["clips"][0]
        self.assertTrue(clip["reuse_blocked"])
        self.assertEqual(clip["cache_status"], "reuse_blocked")
        self.assertEqual(coverage["summary"]["clips_reuse_blocked"], 1)
        self.assertIn("force_refresh=true", clip["recommended_action"])

    def test_coverage_report_min_source_trust_filters_below_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source", "A001.mov")
            os.makedirs(os.path.dirname(source))
            with open(source, "wb") as handle:
                handle.write(b"x" * 100)
            record = {"clip_id": "clip-1", "clip_name": "A001.mov", "file_path": source, "media_id": "media-1"}
            analysis_root = os.path.join(tmp, "analysis")
            self._write_report(
                analysis_root=analysis_root,
                project_name="Trust Filter Project",
                project_id="v1",
                source=source,
                record=record,
                source_trust="low",
            )

            coverage = build_coverage_report(
                project_name="Trust Filter Project",
                project_id="v1",
                records=[record],
                target={"type": "bin", "path": "Master"},
                params={
                    "analysis_root": analysis_root,
                    "depth": "standard",
                    "transcription": {"enabled": False},
                    "min_source_trust": "high",
                },
                capabilities=self._base_capabilities(),
            )
        clip = coverage["clips"][0]
        # Report exists and is layer-complete, but trust is below threshold
        self.assertEqual(coverage["min_source_trust"], "high")
        self.assertTrue(clip["below_min_source_trust"])
        self.assertEqual(clip["source_trust"], "low")
        self.assertEqual(coverage["summary"]["clips_needs_higher_trust"], 1)
        # And it should NOT be counted as analyzed for evidence-base purposes
        self.assertEqual(coverage["summary"]["clips_analyzed"], 0)

    def test_mark_registry_stale_flags_matching_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source", "A001.mov")
            os.makedirs(os.path.dirname(source))
            with open(source, "wb") as handle:
                handle.write(b"x" * 100)
            record = {"clip_id": "clip-1", "clip_name": "A001.mov", "file_path": source, "media_id": "media-1"}
            analysis_root = os.path.join(tmp, "analysis")
            report_path = self._write_report(
                analysis_root=analysis_root,
                project_name="Relink Project",
                project_id="v1",
                source=source,
                record=record,
            )

            result = mark_registry_stale_for_clip(
                project_name="Relink Project",
                project_id="v1",
                analysis_root=analysis_root,
                clip_id="clip-1",
                reason="replace_clip",
            )
            self.assertTrue(result["success"])
            self.assertEqual(result["matched"], 1)

            superseded = registry_entry_superseded_info(
                resolve_output_root(
                    project_name="Relink Project",
                    project_id="v1",
                    analysis_root=analysis_root,
                    source_paths=[source],
                    create=False,
                )["project_root"],
                report_path,
            )
            self.assertIsNotNone(superseded)
            self.assertTrue(superseded["superseded_by_relink"])
            self.assertEqual(superseded["superseded_reason"], "replace_clip")

    def test_mark_registry_stale_survives_registry_rebuild(self):
        """update_analysis_registry must preserve superseded_by_relink across rebuilds."""
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source", "A001.mov")
            os.makedirs(os.path.dirname(source))
            with open(source, "wb") as handle:
                handle.write(b"x" * 100)
            record = {"clip_id": "clip-1", "clip_name": "A001.mov", "file_path": source, "media_id": "media-1"}
            analysis_root = os.path.join(tmp, "analysis")
            report_path = self._write_report(
                analysis_root=analysis_root,
                project_name="Rebuild Project",
                project_id="v1",
                source=source,
                record=record,
            )
            mark_registry_stale_for_clip(
                project_name="Rebuild Project",
                project_id="v1",
                analysis_root=analysis_root,
                clip_id="clip-1",
                reason="replace_clip",
            )

            project_root = resolve_output_root(
                project_name="Rebuild Project",
                project_id="v1",
                analysis_root=analysis_root,
                source_paths=[source],
                create=False,
            )["project_root"]
            # Rebuild — simulates what commit_visual_analysis does after analysis.
            update_analysis_registry(project_root, report_paths=[report_path])

            superseded = registry_entry_superseded_info(project_root, report_path)
            self.assertIsNotNone(superseded, "superseded flag must survive registry rebuild")
            self.assertEqual(superseded["superseded_reason"], "replace_clip")

    def test_coverage_report_surfaces_superseded_by_relink(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source", "A001.mov")
            os.makedirs(os.path.dirname(source))
            with open(source, "wb") as handle:
                handle.write(b"x" * 100)
            record = {"clip_id": "clip-1", "clip_name": "A001.mov", "file_path": source, "media_id": "media-1"}
            analysis_root = os.path.join(tmp, "analysis")
            self._write_report(
                analysis_root=analysis_root,
                project_name="Relink Coverage Project",
                project_id="v1",
                source=source,
                record=record,
            )
            mark_registry_stale_for_clip(
                project_name="Relink Coverage Project",
                project_id="v1",
                analysis_root=analysis_root,
                clip_id="clip-1",
                reason="replace_clip",
            )

            coverage = build_coverage_report(
                project_name="Relink Coverage Project",
                project_id="v1",
                records=[record],
                target={"type": "bin", "path": "Master"},
                params={
                    "analysis_root": analysis_root,
                    "depth": "standard",
                    "transcription": {"enabled": False},
                },
                capabilities=self._base_capabilities(),
            )
        clip = coverage["clips"][0]
        self.assertTrue(clip["superseded_by_relink"])
        self.assertFalse(clip["analyzed"])  # relink defeats reusability
        self.assertEqual(coverage["summary"]["clips_stale"], 1)
        self.assertEqual(coverage["summary"]["clips_analyzed"], 0)
        self.assertIn("replaced", clip["recommended_action"].lower() + " " + clip["recommended_action"].lower())
        self.assertIn("re-analyze", clip["recommended_action"].lower())

    def test_coverage_report_fires_reuse_blocked_on_signature_drifted_provenance(self):
        """Provenance points to a report that exists but is signature-drifted → reuse_blocked, not silent stale."""
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source", "A001.mov")
            os.makedirs(os.path.dirname(source))
            with open(source, "wb") as handle:
                handle.write(b"original")
            record_initial = {"clip_id": "clip-1", "clip_name": "A001.mov", "file_path": source, "media_id": "media-1"}
            analysis_root = os.path.join(tmp, "analysis")
            report_path = self._write_report(
                analysis_root=analysis_root,
                project_name="Signature Drift Provenance Project",
                project_id="v1",
                source=source,
                record=record_initial,
            )
            # Drift the source so signature no longer matches
            import time as _time
            _time.sleep(0.05)
            with open(source, "wb") as handle:
                handle.write(b"changed bytes here change change change")

            record_with_provenance = {
                **record_initial,
                "analysis_report_path": report_path,
                "published_analysis_signature": "any-signature-string",
            }
            coverage = build_coverage_report(
                project_name="Signature Drift Provenance Project",
                project_id="v1",
                records=[record_with_provenance],
                target={"type": "bin", "path": "Master"},
                params={
                    "analysis_root": analysis_root,
                    "depth": "standard",
                    "transcription": {"enabled": False},
                },
                capabilities=self._base_capabilities(),
            )
        clip = coverage["clips"][0]
        self.assertTrue(clip["reuse_blocked"])
        self.assertEqual(coverage["summary"]["clips_reuse_blocked"], 1)
        self.assertIn("force_refresh=true", clip["recommended_action"])

    def test_coverage_report_does_not_fire_reuse_blocked_without_provenance(self):
        """Plain stale report without Resolve-side provenance must NOT escalate to reuse_blocked."""
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source", "A001.mov")
            os.makedirs(os.path.dirname(source))
            with open(source, "wb") as handle:
                handle.write(b"original")
            record = {"clip_id": "clip-1", "clip_name": "A001.mov", "file_path": source, "media_id": "media-1"}
            analysis_root = os.path.join(tmp, "analysis")
            self._write_report(
                analysis_root=analysis_root,
                project_name="No Provenance Project",
                project_id="v1",
                source=source,
                record=record,
            )
            import time as _time
            _time.sleep(0.05)
            with open(source, "wb") as handle:
                handle.write(b"drift drift drift drift drift drift")

            coverage = build_coverage_report(
                project_name="No Provenance Project",
                project_id="v1",
                records=[record],  # no analysis_report_path field
                target={"type": "bin", "path": "Master"},
                params={
                    "analysis_root": analysis_root,
                    "depth": "standard",
                    "transcription": {"enabled": False},
                },
                capabilities=self._base_capabilities(),
            )
        clip = coverage["clips"][0]
        self.assertFalse(clip["reuse_blocked"])
        self.assertEqual(clip["cache_status"], "stale_or_incomplete")
        self.assertEqual(coverage["summary"]["clips_reuse_blocked"], 0)
        self.assertEqual(coverage["summary"]["clips_stale"], 1)

    def test_analysis_root_coverage_summarizes_disk(self):
        """Standalone coverage helper powers the control panel Readiness card."""
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source", "A001.mov")
            os.makedirs(os.path.dirname(source))
            with open(source, "wb") as handle:
                handle.write(b"x" * 100)
            record_a = {"clip_id": "clip-a", "clip_name": "A001.mov", "file_path": source, "media_id": "media-a"}
            record_b = {
                "clip_id": "clip-b",
                "clip_name": "B001.mov",
                "file_path": os.path.join(tmp, "source", "B001.mov"),
                "media_id": "media-b",
            }
            os.makedirs(os.path.dirname(record_b["file_path"]), exist_ok=True)
            with open(record_b["file_path"], "wb") as handle:
                handle.write(b"y" * 100)
            analysis_root = os.path.join(tmp, "analysis")
            self._write_report(
                analysis_root=analysis_root,
                project_name="Standalone Coverage Project",
                project_id="v1",
                source=source,
                record=record_a,
                source_trust="high",
                with_transcription=True,
            )
            self._write_report(
                analysis_root=analysis_root,
                project_name="Standalone Coverage Project",
                project_id="v1",
                source=record_b["file_path"],
                record=record_b,
                source_trust="medium",
            )
            mark_registry_stale_for_clip(
                project_name="Standalone Coverage Project",
                project_id="v1",
                analysis_root=analysis_root,
                clip_id="clip-b",
                reason="replace_clip",
            )

            project_root = resolve_output_root(
                project_name="Standalone Coverage Project",
                project_id="v1",
                analysis_root=analysis_root,
                source_paths=[source],
                create=False,
            )["project_root"]
            payload = analysis_root_coverage(project_root)

        self.assertTrue(payload["success"])
        summary = payload["summary"]
        self.assertEqual(summary["clips_total_with_reports"], 2)
        self.assertEqual(summary["clips_signed"], 2)
        self.assertEqual(summary["clips_superseded_by_relink"], 1)
        self.assertEqual(summary["source_trust_distribution"], {"high": 1, "medium": 1})
        # Transcription was enabled on clip-a only.
        self.assertEqual(summary["layer_coverage"].get("transcription"), 1)
        self.assertEqual(summary["layer_coverage"].get("technical"), 2)
        # The superseded clip should appear first in the prioritized list.
        self.assertTrue(payload["analyzed_clips"][0]["superseded_by_relink"])

    def test_coverage_report_persists_source_trust_via_analysis_profile(self):
        """source_trust persisted by _build_clip_analysis_report flows through to coverage."""
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source", "A001.mov")
            os.makedirs(os.path.dirname(source))
            with open(source, "wb") as handle:
                handle.write(b"x" * 100)
            record = {"clip_id": "clip-1", "clip_name": "A001.mov", "file_path": source, "media_id": "media-1"}
            analysis_root = os.path.join(tmp, "analysis")
            self._write_report(
                analysis_root=analysis_root,
                project_name="Trust Persistence Project",
                project_id="v1",
                source=source,
                record=record,
                source_trust="high",
            )

            coverage = build_coverage_report(
                project_name="Trust Persistence Project",
                project_id="v1",
                records=[record],
                target={"type": "bin", "path": "Master"},
                params={
                    "analysis_root": analysis_root,
                    "depth": "standard",
                    "transcription": {"enabled": False},
                },
                capabilities=self._base_capabilities(),
            )
        self.assertEqual(coverage["clips"][0]["source_trust"], "high")
        self.assertEqual(coverage["summary"]["source_trust_distribution"], {"high": 1})


class PathExistenceProbeTests(unittest.TestCase):
    """Parallel/cached file-existence probing for the Resolve media inventory."""

    def setUp(self):
        from src import analysis_dashboard as dash
        self.dash = dash
        dash._PATH_EXISTS_CACHE.clear()

    def test_fresh_probe_reports_real_and_missing_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = os.path.join(tmp, "a.mov")
            open(real, "w").close()
            missing = os.path.join(tmp, "gone.mov")
            result = self.dash._probe_paths_exist([real, missing, None, ""], probe=True)
        self.assertTrue(result[real])
        self.assertFalse(result[missing])
        # Empty/None entries are ignored, not probed.
        self.assertNotIn("", result)

    def test_background_poll_reuses_cache_without_restating(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = os.path.join(tmp, "a.mov")
            open(real, "w").close()
            # Warm the cache with a real probe, then delete the file.
            self.dash._probe_paths_exist([real], probe=True)
            os.remove(real)
            # Background poll must not stat — it trusts the cached True.
            result = self.dash._probe_paths_exist([real], probe=False)
        self.assertTrue(result[real])

    def test_background_poll_assumes_present_for_uncached_path(self):
        # No cache entry + no probe → trust Resolve's own status, assume present.
        result = self.dash._probe_paths_exist(["/nonexistent/never-probed.mov"], probe=False)
        self.assertTrue(result["/nonexistent/never-probed.mov"])

    def test_fresh_probe_restats_after_cache_cleared(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = os.path.join(tmp, "a.mov")
            open(real, "w").close()
            self.dash._probe_paths_exist([real], probe=True)
            os.remove(real)
            self.dash._PATH_EXISTS_CACHE.clear()  # simulate TTL expiry
            result = self.dash._probe_paths_exist([real], probe=True)
        self.assertFalse(result[real])

    def test_finalize_clip_record_sets_status_from_existence(self):
        rec = {"file_path": "/x/b.mov", "clip_name": "b", "media_type": "Video", "_props": {}}
        self.dash._finalize_clip_record(rec, True)
        self.assertEqual(rec["status"], "online")
        self.assertTrue(rec["file_exists"])
        self.assertNotIn("_props", rec)

        rec2 = {"file_path": "/x/c.mov", "clip_name": "c", "media_type": "Video", "_props": {}}
        self.dash._finalize_clip_record(rec2, False)
        self.assertEqual(rec2["status"], "missing_file")
        self.assertFalse(rec2["file_exists"])


class InventoryCacheReuseTests(unittest.TestCase):
    """Background-poll reuse of the cached Resolve walk + analysis overlay."""

    def setUp(self):
        from src import analysis_dashboard as dash
        self.dash = dash
        dash._INVENTORY_CACHE.clear()

    def _entry(self):
        analyzed = {"file_path": "/x/a.mov", "clip_name": "a", "media_type": "Video",
                    "status": "online", "source_clip": True, "analyzable": True,
                    "selected": True, "clip_key": "a-key"}
        plain = {"file_path": "/x/b.mov", "clip_name": "b", "media_type": "Video",
                 "status": "online", "source_clip": True, "analyzable": True,
                 "selected": False, "clip_key": "b-key"}
        return {"base_records": [analyzed, plain], "project": {"name": "P", "id": "1"},
                "selected_count": 1, "truncated": False, "limit": 500, "warnings": []}

    def test_assemble_applies_overlay_without_contaminating_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            entry = self._entry()
            payload = self.dash._assemble_inventory_payload(tmp, entry)
            self.assertTrue(payload["resolve_available"])
            self.assertEqual(payload["counts"]["total"], 2)
            self.assertEqual(payload["counts"]["analyzed"], 0)
            self.assertEqual(payload["counts"]["selected"], 1)
            # The cached base must stay free of the per-call analysis overlay.
            self.assertNotIn("analysis_status", entry["base_records"][0])

    def test_overlay_reflects_new_analysis_without_resolve(self):
        # The whole point of poll-reuse: analysis progress is picked up from disk
        # on every assemble, with no Resolve walk.
        with tempfile.TemporaryDirectory() as tmp:
            entry = self._entry()
            self.assertEqual(self.dash._assemble_inventory_payload(tmp, entry)["counts"]["analyzed"], 0)
            os.makedirs(os.path.join(tmp, "clips", "a-key"))
            with open(os.path.join(tmp, "clips", "a-key", "analysis.json"), "w") as fh:
                fh.write("{}")
            self.assertEqual(self.dash._assemble_inventory_payload(tmp, entry)["counts"]["analyzed"], 1)

    def _without_resolve(self):
        # Make the Resolve probe deterministically absent so these tests pass
        # whether or not a live Resolve instance happens to be running.
        return unittest.mock.patch.object(
            self.dash, "_connect_resolve_read_only",
            return_value=(None, "Resolve unavailable (stubbed for test)"),
        )

    def test_reuse_cached_serves_from_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.dash._store_cached_inventory(tmp, self._entry())
            with self._without_resolve():
                payload = self.dash.resolve_media_inventory(tmp, reuse_cached=True)
            self.assertTrue(payload["resolve_available"])
            self.assertEqual(payload["counts"]["total"], 2)

    def test_reuse_miss_falls_through_to_build(self):
        # No cache entry → full build; without Resolve that surfaces as unavailable
        # rather than silently returning empty cached data.
        with self._without_resolve():
            payload = self.dash.resolve_media_inventory("/no/such/cache/root", reuse_cached=True)
        self.assertFalse(payload["resolve_available"])

    def test_resolve_identity_lock_is_reentrant(self):
        # _resolve_identity is lock-decorated and calls _connect (same RLock):
        # must return, not deadlock, when Resolve is absent.
        ident = self.dash._resolve_identity()
        self.assertIn("available", ident)

    def test_reuse_serves_cache_when_project_id_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.dash._store_cached_inventory(tmp, self._entry())  # cached id == "1"
            original = self.dash._current_resolve_project_id
            self.dash._current_resolve_project_id = lambda: ("1", None)
            try:
                payload = self.dash.resolve_media_inventory(tmp, reuse_cached=True)
            finally:
                self.dash._current_resolve_project_id = original
            self.assertTrue(payload["resolve_available"])
            self.assertEqual(payload["counts"]["total"], 2)

    def test_reuse_rebuilds_when_resolve_project_switched(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.dash._store_cached_inventory(tmp, self._entry())  # cached id == "1"
            original = self.dash._current_resolve_project_id
            self.dash._current_resolve_project_id = lambda: ("2", None)  # different project
            try:
                with self._without_resolve():
                    payload = self.dash.resolve_media_inventory(tmp, reuse_cached=True)
            finally:
                self.dash._current_resolve_project_id = original
            # Confirmed mismatch → full rebuild, which is unavailable without Resolve.
            self.assertFalse(payload["resolve_available"])

    def test_reuse_keeps_cache_when_current_project_unknown(self):
        # Transient inability to read the current project must not trigger an
        # expensive rebuild on every poll — keep serving the cache.
        with tempfile.TemporaryDirectory() as tmp:
            self.dash._store_cached_inventory(tmp, self._entry())
            original = self.dash._current_resolve_project_id
            self.dash._current_resolve_project_id = lambda: (None, "Resolve unavailable")
            try:
                payload = self.dash.resolve_media_inventory(tmp, reuse_cached=True)
            finally:
                self.dash._current_resolve_project_id = original
            self.assertTrue(payload["resolve_available"])
            self.assertEqual(payload["counts"]["total"], 2)


if __name__ == "__main__":
    unittest.main()
