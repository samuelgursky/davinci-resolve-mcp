"""Offline interchange authoring, and the line between offering it and claiming success.

The dangerous failure here is not a bad file — it is a *good* file reported as though the
live operation had worked. So the tests assert both halves everywhere: the connection
error stays an error, and the offer says outright that it does not complete what failed.

The second dangerous failure is silent: an OTIO whose source frames are not
timecode-absolute imports as an empty timeline with no error at all. Every event that had
to assume an origin must come back named.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.utils import offline_fallback  # noqa: E402

HAVE_NODE = shutil.which("node") is not None
AVAILABLE = offline_fallback.capabilities()["available"]


class TestPlanToEvents(unittest.TestCase):
    def test_minimal_clip(self):
        events = offline_fallback.plan_to_events(
            [{"path": "/m/A.mov", "start_frame": 10, "end_frame": 58}], fps=24)
        self.assertEqual(events[0]["source"], "/m/A.mov")
        self.assertEqual(events[0]["srcIn"], 10)
        self.assertEqual(events[0]["srcOut"], 58)
        self.assertEqual(events[0]["recIn"], 0)
        self.assertEqual(events[0]["recOut"], 48)
        self.assertEqual(events[0]["track"], "V")

    def test_end_frame_is_exclusive(self):
        """Half-open, matching AppendToTimeline. Disagreeing would be off by one everywhere."""
        events = offline_fallback.plan_to_events(
            [{"path": "/m/A.mov", "start_frame": 0, "end_frame": 24}], fps=24)
        self.assertEqual(events[0]["recOut"] - events[0]["recIn"], 24)

    def test_duration_frames_is_accepted_instead_of_end_frame(self):
        events = offline_fallback.plan_to_events(
            [{"path": "/m/A.mov", "start_frame": 5, "duration_frames": 30}], fps=24)
        self.assertEqual(events[0]["srcOut"], 35)

    def test_clips_tile_per_track(self):
        events = offline_fallback.plan_to_events([
            {"path": "/m/A.mov", "start_frame": 0, "end_frame": 24},
            {"path": "/m/B.mov", "start_frame": 0, "end_frame": 12},
            {"path": "/m/C.wav", "start_frame": 0, "end_frame": 48, "media_type": "audio"},
        ], fps=24)
        self.assertEqual(events[0]["recIn"], 0)
        self.assertEqual(events[1]["recIn"], 24)
        # Audio tiles on its own track cursor, not after the video.
        self.assertEqual(events[2]["recIn"], 0)
        self.assertEqual(events[2]["track"], "A")

    def test_explicit_record_frame_wins(self):
        events = offline_fallback.plan_to_events([
            {"path": "/m/A.mov", "start_frame": 0, "end_frame": 24},
            {"path": "/m/B.mov", "start_frame": 0, "end_frame": 24, "record_frame": 100},
        ], fps=24)
        self.assertEqual(events[1]["recIn"], 100)

    def test_media_origin_is_carried_through(self):
        events = offline_fallback.plan_to_events(
            [{"path": "/m/A.mov", "start_frame": 0, "end_frame": 24,
              "media_start_tc_frame": 86400}], fps=24)
        self.assertEqual(events[0]["mediaStartTcFrame"], 86400)

    def test_speed_and_reverse_are_carried(self):
        events = offline_fallback.plan_to_events(
            [{"path": "/m/A.mov", "start_frame": 0, "end_frame": 24,
              "speed": 50, "reverse": True}], fps=24)
        self.assertEqual(events[0]["speed"], 50.0)
        self.assertTrue(events[0]["reverse"])

    def test_zero_length_clip_is_refused(self):
        with self.assertRaises(offline_fallback.OfflineFallbackError) as caught:
            offline_fallback.plan_to_events(
                [{"path": "/m/A.mov", "start_frame": 50, "end_frame": 50}])
        self.assertIn("exclusive", str(caught.exception))

    def test_missing_range_is_refused(self):
        with self.assertRaises(offline_fallback.OfflineFallbackError):
            offline_fallback.plan_to_events([{"path": "/m/A.mov", "start_frame": 0}])

    def test_missing_path_is_refused(self):
        with self.assertRaises(offline_fallback.OfflineFallbackError):
            offline_fallback.plan_to_events([{"start_frame": 0, "end_frame": 24}])

    def test_empty_plan_is_refused(self):
        with self.assertRaises(offline_fallback.OfflineFallbackError):
            offline_fallback.plan_to_events([])

    def test_non_numeric_frame_is_refused_by_name(self):
        with self.assertRaises(offline_fallback.OfflineFallbackError) as caught:
            offline_fallback.plan_to_events(
                [{"path": "/m/A.mov", "start_frame": "soon", "end_frame": 24}])
        self.assertIn("start_frame", str(caught.exception))


@unittest.skipUnless(AVAILABLE, "node and the bundled authoring module required")
class TestAuthoring(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="offline_fallback_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.clips = [
            {"path": "/media/A001.mov", "start_frame": 10, "end_frame": 58,
             "media_start_tc_frame": 86400},
            {"path": "/media/A002.mov", "start_frame": 0, "end_frame": 48,
             "media_start_tc_frame": 86400},
        ]

    def _author(self, target, clips=None, name="Test"):
        return offline_fallback.author(
            clips if clips is not None else self.clips,
            os.path.join(self.dir, f"out.{target}"),
            target=target, name=name, fps=24)

    def test_every_target_writes_a_file(self):
        for target in offline_fallback.TARGETS:
            with self.subTest(target=target):
                result = self._author(target)
                self.assertTrue(os.path.isfile(result["output_path"]))
                self.assertGreater(result["bytes"], 0)
                self.assertEqual(result["event_count"], 2)

    def test_otio_round_trips_through_our_own_parser(self):
        """Writing a file and Resolve honouring it are different claims; this is the first."""
        result = self._author("otio")
        document = json.loads(pathlib.Path(result["output_path"]).read_text())
        self.assertEqual(document["OTIO_SCHEMA"].split(".")[0], "Timeline")
        clips = [
            child for track in document["tracks"]["children"]
            for child in track["children"]
            if child["OTIO_SCHEMA"].startswith("Clip")
        ]
        self.assertEqual(len(clips), 2)
        self.assertEqual(
            [clip["media_references"]["DEFAULT_MEDIA"]["target_url"] for clip in clips],
            ["/media/A001.mov", "/media/A002.mov"],
        )

    def test_source_frames_are_timecode_absolute(self):
        """A source_range measured from zero imports as an EMPTY timeline in Resolve."""
        result = self._author("otio")
        document = json.loads(pathlib.Path(result["output_path"]).read_text())
        clip = next(
            child for track in document["tracks"]["children"]
            for child in track["children"]
            if child["OTIO_SCHEMA"].startswith("Clip")
        )
        # media start 86400 + in-point 10.
        self.assertEqual(clip["source_range"]["start_time"]["value"], 86410)

    def test_a_missing_media_origin_is_warned_about_by_name(self):
        result = offline_fallback.author(
            [{"path": "/media/NoTc.mov", "start_frame": 0, "end_frame": 24}],
            os.path.join(self.dir, "warn.otio"), target="otio", fps=24)
        warning = next(w for w in result["warnings"] if w["id"] == "media_tc_origin_assumed")
        self.assertIn("/media/NoTc.mov", json.dumps(warning["events"]))
        self.assertTrue(warning["remedy"])

    def test_a_supplied_origin_produces_no_warning(self):
        result = self._author("otio")
        self.assertEqual(
            [w["id"] for w in result["warnings"] if w["id"] == "media_tc_origin_assumed"], [])

    def test_drt_flattens_retimes_and_says_which(self):
        """A .drt has no per-clip speed field; losing one silently would be the lie."""
        result = offline_fallback.author(
            [{"path": "/media/A.mov", "start_frame": 0, "end_frame": 48,
              "media_start_tc_frame": 86400, "speed": 50}],
            os.path.join(self.dir, "retime.drt"), target="drt", fps=24)
        warning = next(w for w in result["warnings"] if w["id"] == "retimes_flattened")
        self.assertIn("OTIO", warning["remedy"])

    def test_otio_keeps_the_retime_drt_loses(self):
        clips = [{"path": "/media/A.mov", "start_frame": 0, "end_frame": 48,
                  "media_start_tc_frame": 86400, "speed": 50}]
        otio = offline_fallback.author(
            clips, os.path.join(self.dir, "keep.otio"), target="otio", fps=24)
        self.assertEqual([w["id"] for w in otio["warnings"]], [])
        self.assertIn("LinearTimeWarp", pathlib.Path(otio["output_path"]).read_text())

    def test_drt_names_the_resolve_version_it_targets(self):
        result = self._author("drt")
        self.assertIn("21.0", result["resolve_version"]["targets"])
        self.assertIn("downgrade", result["resolve_version"]["older_builds"])

    def test_non_drt_targets_declare_no_version_gate(self):
        for target in ("otio", "edl"):
            with self.subTest(target=target):
                self.assertNotIn("project_versions", self._author(target)["resolve_version"])

    def test_every_result_says_the_timeline_is_only_a_file(self):
        for target in offline_fallback.TARGETS:
            with self.subTest(target=target):
                result = self._author(target)
                self.assertIn("not in any project", result["note"])
                self.assertTrue(result["import_with"])

    def test_unknown_target_lists_the_real_ones(self):
        with self.assertRaises(offline_fallback.OfflineFallbackError) as caught:
            self._author("fcpxml")
        self.assertIn("drt", str(caught.exception))

    def test_edl_carries_the_record_timecode(self):
        result = self._author("edl")
        text = pathlib.Path(result["output_path"]).read_text()
        self.assertIn("TITLE: Test", text)
        self.assertIn("00:00:00:00", text)


@unittest.skipUnless(HAVE_NODE, "node required")
class TestBridgeScript(unittest.TestCase):
    def _run(self, payload):
        process = subprocess.run(
            ["node", str(REPO_ROOT / "scripts" / "author_interchange.mjs")],
            input=json.dumps(payload).encode(), capture_output=True, check=False, timeout=60)
        return process.returncode, json.loads(process.stdout.decode() or "{}")

    def test_empty_events_is_an_error_not_an_empty_file(self):
        code, result = self._run({"events": [], "target": "otio", "outputPath": "/tmp/x.otio"})
        self.assertNotEqual(code, 0)
        self.assertFalse(result["ok"])
        self.assertIn("non-empty", result["error"])

    def test_missing_output_path_is_an_error(self):
        code, result = self._run({"events": [{"source": "/a.mov"}], "target": "otio"})
        self.assertNotEqual(code, 0)
        self.assertIn("outputPath", result["error"])

    def test_unknown_target_is_an_error(self):
        code, result = self._run(
            {"events": [{"source": "/a.mov"}], "target": "aaf", "outputPath": "/tmp/x"})
        self.assertNotEqual(code, 0)
        self.assertIn("aaf", result["error"])


class TestOffer(unittest.TestCase):
    def test_offer_names_what_it_does_not_do(self):
        offer = offline_fallback.offline_alternative(action="create_timeline")
        if not offer.get("available"):
            self.skipTest("offline authoring unavailable here")
        self.assertIn("does not complete the operation", offer["does_not"])
        self.assertIn("create_timeline", offer["does_not"])

    def test_unavailable_offer_says_why(self):
        original = offline_fallback.capabilities
        offline_fallback.capabilities = lambda: {"available": False, "node_path": None}
        try:
            offer = offline_fallback.offline_alternative()
        finally:
            offline_fallback.capabilities = original
        self.assertFalse(offer["available"])
        self.assertIn("reason", offer)


class TestToolSurface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import types

        fake = types.ModuleType("DaVinciResolveScript")
        fake.scriptapp = lambda *a, **k: None
        sys.modules.setdefault("DaVinciResolveScript", fake)
        from src import server

        cls.server = server

    def test_capabilities_is_served_without_a_connection(self):
        result = self.server.timeline("offline_fallback_capabilities")
        self.assertTrue(result["success"])
        self.assertIn("drt", result["targets"])

    def test_a_connection_failure_stays_a_failure(self):
        """Both halves. An offer that reads as success is worse than no offer."""
        original = self.server.get_resolve
        self.server.get_resolve = lambda *a, **k: None
        try:
            result = self.server.timeline("get_current")
        finally:
            self.server.get_resolve = original
        self.assertNotIn("success", result)
        self.assertEqual(result["error"]["category"], "not_connected")
        offer = result["error"].get("offline_alternative")
        if offer is not None:
            self.assertIn("does not complete", offer["does_not"])

    @unittest.skipUnless(AVAILABLE, "node and the bundled authoring module required")
    def test_author_offline_writes_without_a_connection(self):
        directory = tempfile.mkdtemp(prefix="surface_offline_")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        calls = []
        original = self.server.get_resolve
        self.server.get_resolve = lambda *a, **k: calls.append(1) or None
        try:
            result = self.server.timeline("author_offline", {
                "clips": [{"path": "/media/A.mov", "start_frame": 0, "end_frame": 48,
                           "media_start_tc_frame": 86400}],
                "output_path": os.path.join(directory, "t.drt"),
                "fps": 24,
            })
        finally:
            self.server.get_resolve = original
        self.assertTrue(result["success"])
        self.assertTrue(os.path.isfile(result["output_path"]))
        self.assertEqual(calls, [], "reached for Resolve while authoring offline")

    def test_missing_output_path_is_reported(self):
        result = self.server.timeline("author_offline", {"clips": []})
        self.assertIn("output_path", result["error"]["message"])

    def test_bad_plan_is_a_structured_error(self):
        result = self.server.timeline(
            "author_offline", {"clips": [], "output_path": "/tmp/nope.drt"})
        self.assertEqual(result["error"]["code"], "OFFLINE_AUTHORING_REFUSED")
        self.assertIn("EXCLUSIVE", result["error"]["remediation"])


if __name__ == "__main__":
    unittest.main()
