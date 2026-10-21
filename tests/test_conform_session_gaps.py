"""Gaps a real conform session hit on Studio 19.1.3.7 (2026-10-20/21).

Each class pins one fix, against fakes that behave the way the build was
measured to:

- timeline_frame capture: the render route failed every call ("AddRenderJob
  returned nothing") while Project.ExportCurrentFrameAsStill after a seek and a
  timecode read-back worked every call. The export is now the default.
- Inspector keyframes: SetProperty returns True and reads back while the render
  ignores it, and 19.1 has no TimelineItem keyframe methods at all.
- Locked tracks: DeleteClips answers a bare False; SetProperty still writes.
- Slip: no API, so replace_source_range rebuilds the item.
- Edit transform units: Pan/Tilt scale with the FITTED image.
- Playback: a page switch while playing hung Resolve's main thread.
"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

from mcp.server.fastmcp import Image

import src.server as s
from src.utils import page_lock, playback_guard


# ── timeline_frame: the ExportCurrentFrameAsStill route ─────────────────────


class _Resolve:
    def __init__(self, page="edit"):
        self.page = page
        self.opened = []

    def GetCurrentPage(self):
        return self.page

    def OpenPage(self, page):
        self.opened.append(page)
        self.page = page
        return True


class _ExportTimeline:
    """A 24 fps timeline at 01:00:00:00 whose playhead is a plain string."""

    def __init__(self, tc="01:00:00:00", refuse_move=False, drift_after_export=False,
                 unreadable=False):
        self.tc = tc
        self.refuse_move = refuse_move
        self.drift_after_export = drift_after_export
        self.unreadable = unreadable
        self.seeks = []

    def GetSetting(self, key):
        return "24" if key == "timelineFrameRate" else None

    def GetStartFrame(self):
        return 86400

    def GetStartTimecode(self):
        return "01:00:00:00"

    def GetTrackCount(self, kind):
        return 0

    def GetName(self):
        return "TL"

    def GetCurrentTimecode(self):
        return None if self.unreadable else self.tc

    def SetCurrentTimecode(self, tc):
        self.seeks.append(tc)
        if not self.refuse_move:
            self.tc = tc
        return True


class _ExportProject:
    def __init__(self, tl, writes=True, returns=True):
        self.tl = tl
        self.writes = writes
        self.returns = returns
        self.exported_at = []

    def ExportCurrentFrameAsStill(self, path):
        self.exported_at.append(self.tl.tc)
        if self.writes:
            with open(path, "wb") as fh:
                fh.write(b"\xff\xd8frame@" + self.tl.tc.encode())
        if self.tl.drift_after_export:
            self.tl.tc = "01:00:00:09"
        return self.returns

    def AddRenderJob(self):  # pragma: no cover - must never be reached
        raise AssertionError("the export route must not queue a render job")

    def GetCurrentRenderMode(self):  # pragma: no cover
        raise AssertionError("the export route must not touch render settings")


class ExportCaptureTest(unittest.TestCase):
    def _capture(self, params, tl=None, proj=None, resolve=None, ffmpeg=None):
        tl = tl or _ExportTimeline()
        proj = proj or _ExportProject(tl)
        resolve = resolve or _Resolve()
        base = os.path.join(tempfile.mkdtemp(prefix="export-capture-"), "resolve-frame-captures")
        self.addCleanup(shutil.rmtree, os.path.dirname(base), True)
        self.base = base
        with mock.patch.object(s, "get_resolve", return_value=resolve), \
             mock.patch.object(s, "_get_tl", return_value=(proj, tl, None)), \
             mock.patch.object(s, "_resolve_safe_dir", return_value=base), \
             mock.patch.object(s.shutil, "which", return_value=ffmpeg), \
             mock.patch.object(s, "_ffmpeg_scale_to_bytes", return_value=(b"\xff\xd8scaled", None)), \
             mock.patch.object(s.time, "sleep"), \
             mock.patch.object(page_lock.time, "sleep"):
            out = s.timeline_frame("capture", params)
        return out, tl, proj, resolve

    def test_default_quality_exports_the_frame_without_switching_page(self):
        out, tl, proj, resolve = self._capture({})
        self.assertIsInstance(out, Image)
        self.assertEqual(out.data, b"\xff\xd8frame@01:00:00:00")
        self.assertEqual(resolve.opened, [])
        self.assertEqual(tl.seeks, [])  # no position named: nothing moved

    def test_named_frame_is_sought_exported_and_the_playhead_restored(self):
        out, tl, proj, _ = self._capture({"frame": 86424})
        self.assertIsInstance(out, Image)
        self.assertEqual(proj.exported_at, ["01:00:01:00"])
        self.assertEqual(tl.tc, "01:00:00:00")
        self.assertEqual(tl.seeks, ["01:00:01:00", "01:00:00:00"])

    def test_elapsed_timecode_is_lifted_to_absolute(self):
        out, _, proj, _ = self._capture({"timecode": "00:00:02:00"})
        self.assertIsInstance(out, Image)
        self.assertEqual(proj.exported_at, ["01:00:02:00"])

    def test_a_seek_that_does_not_land_is_refused_not_exported(self):
        tl = _ExportTimeline(refuse_move=True)
        proj = _ExportProject(tl)
        out, _, _, _ = self._capture({"frame": 86424}, tl=tl, proj=proj)
        self.assertEqual(out["error"]["code"], "SEEK_UNCONFIRMED")
        self.assertEqual(proj.exported_at, [])

    def test_a_playhead_that_moves_during_the_export_is_playback(self):
        tl = _ExportTimeline(drift_after_export=True)
        out, _, _, _ = self._capture({}, tl=tl)
        self.assertEqual(out["error"]["code"], "PLAYBACK_ACTIVE")

    def test_a_false_export_is_an_error(self):
        tl = _ExportTimeline()
        proj = _ExportProject(tl, writes=False, returns=False)
        out, _, _, _ = self._capture({}, tl=tl, proj=proj)
        self.assertEqual(out["error"]["code"], "EXPORT_FRAME_FAILED")
        self.assertIn("quality='render'", out["error"]["remediation"])

    def test_an_unreadable_playhead_names_the_page(self):
        out, _, _, _ = self._capture({}, tl=_ExportTimeline(unreadable=True))
        self.assertEqual(out["error"]["code"], "PLAYHEAD_UNREADABLE")

    def test_preview_is_the_export_bounded_through_ffmpeg(self):
        out, _, _, _ = self._capture({"quality": "preview"}, ffmpeg="/usr/bin/ffmpeg")
        self.assertIsInstance(out, Image)
        self.assertEqual(out.data, b"\xff\xd8scaled")

    def test_max_width_without_ffmpeg_is_refused(self):
        out, _, proj, _ = self._capture({"max_width": 640})
        self.assertEqual(out["error"]["code"], "FFMPEG_REQUIRED")
        self.assertEqual(proj.exported_at, [])

    def test_the_capture_folder_is_cleaned_up(self):
        out, _, _, _ = self._capture({})
        self.assertIsInstance(out, Image)
        self.assertFalse(os.path.exists(self.base))

    def test_capabilities_name_the_default_route(self):
        with mock.patch.object(s, "get_resolve", return_value=_Resolve()), \
             mock.patch.object(s, "_get_tl", return_value=(None, None, {"error": "none"})):
            out = s.timeline_frame("capabilities")
        self.assertEqual(out["default_route"], "Project.ExportCurrentFrameAsStill")
        self.assertIn("render", out["quality_modes"])
        self.assertFalse(out["switches_page"]["frame"])


# ── Playback detection and the page-switch guards ───────────────────────────


class _MovingTimeline:
    def __init__(self, codes):
        self.codes = list(codes)

    def GetCurrentTimecode(self):
        return self.codes.pop(0) if len(self.codes) > 1 else self.codes[0]


class PlaybackGuardTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(playback_guard.time, "sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_an_advancing_playhead_is_playback(self):
        probe = playback_guard.playhead_moving(_MovingTimeline(["01:00:00:00", "01:00:00:04"]))
        self.assertIs(probe["playing"], True)

    def test_a_still_playhead_is_not(self):
        self.assertIs(playback_guard.playhead_moving(_MovingTimeline(["01:00:00:00"]))["playing"], False)

    def test_an_unreadable_playhead_is_unknown(self):
        self.assertIsNone(playback_guard.playhead_moving(_MovingTimeline([None]))["playing"])
        self.assertIsNone(playback_guard.playhead_moving(None)["playing"])

    def _resolve_with(self, tl, page="edit"):
        resolve = _Resolve(page)
        pm = mock.Mock()
        pm.GetCurrentProject.return_value.GetCurrentTimeline.return_value = tl
        resolve.GetProjectManager = lambda: pm
        return resolve

    def test_open_page_refuses_while_playing(self):
        resolve = self._resolve_with(_MovingTimeline(["01:00:00:00", "01:00:00:04"]))
        with mock.patch.object(s, "get_resolve", return_value=resolve), \
             mock.patch.object(s, "_check", return_value=(resolve, None), create=True):
            out = s.resolve_control("open_page", {"page": "color"})
        self.assertEqual(out["error"]["code"], "PLAYBACK_ACTIVE")
        self.assertEqual(resolve.opened, [])

    def test_open_page_override_goes_ahead(self):
        resolve = self._resolve_with(_MovingTimeline(["01:00:00:00", "01:00:00:04"]))
        with mock.patch.object(s, "get_resolve", return_value=resolve):
            out = s.resolve_control("open_page", {"page": "color", "allow_during_playback": True})
        self.assertTrue(out["success"])
        self.assertEqual(resolve.opened, ["color"])

    def test_open_page_to_the_current_page_does_not_probe(self):
        tl = mock.Mock()
        resolve = self._resolve_with(tl, page="color")
        with mock.patch.object(s, "get_resolve", return_value=resolve):
            out = s.resolve_control("open_page", {"page": "color"})
        self.assertTrue(out["success"])
        tl.GetCurrentTimecode.assert_not_called()

    def test_restore_state_refuses_while_playing(self):
        resolve = self._resolve_with(_MovingTimeline(["01:00:00:00", "01:00:00:04"]), page="color")
        s._RESOLVE_STATE_SNAPSHOTS["tok-playback"] = {"page": "edit"}
        self.addCleanup(s._RESOLVE_STATE_SNAPSHOTS.pop, "tok-playback", None)
        with mock.patch.object(s, "get_resolve", return_value=resolve):
            out = s.resolve_control("restore_state", {"state_token": "tok-playback"})
        self.assertEqual(out["error"]["code"], "PLAYBACK_ACTIVE")
        self.assertEqual(resolve.opened, [])

    def test_grab_and_export_refuses_while_playing(self):
        tl = _MovingTimeline(["01:00:00:00", "01:00:00:04"])
        tl.GrabStill = mock.Mock()
        folder = tempfile.mkdtemp(prefix="grab-playback-")
        self.addCleanup(shutil.rmtree, folder, True)
        proj = mock.Mock()
        with mock.patch.object(s, "_check", return_value=(mock.Mock(), proj, None)), \
             mock.patch.object(s, "_get_tl", return_value=(proj, tl, None)), \
             mock.patch.object(s, "_resolve_safe_dir", side_effect=lambda path: path):
            out = s.gallery_stills("grab_and_export", {"folder_path": folder})
        self.assertEqual(out["error"]["code"], "PLAYBACK_ACTIVE")
        tl.GrabStill.assert_not_called()
        self.assertEqual(os.listdir(folder), [])  # staging directory discarded

    def test_page_switching_capture_routes_refuse_while_playing(self):
        tl = _MovingTimeline(["01:00:00:00", "01:00:00:04"])
        tl.GetName = lambda: "TL"
        proj = mock.Mock()
        with mock.patch.object(s, "get_resolve", return_value=_Resolve()), \
             mock.patch.object(s, "_get_tl", return_value=(proj, tl, None)):
            out = s.timeline_frame("capture", {"quality": "render"})
        self.assertEqual(out["error"]["code"], "PLAYBACK_ACTIVE")
        proj.AddRenderJob.assert_not_called()


# ── Keyframe API gate + override probe ─────────────────────────────────────


class _NoKeyframeItem:
    """A 19.1 TimelineItem: unknown attributes come back None, not missing."""

    def __getattr__(self, name):
        return None


class KeyframeGateTest(unittest.TestCase):
    def _call(self, action, params):
        item = _NoKeyframeItem()
        with mock.patch.object(s, "_get_item", return_value=(mock.Mock(), item, None)), \
             mock.patch.object(s, "get_resolve", return_value=mock.Mock(GetVersionString=lambda: "19.1.3.7")):
            return s.timeline_item(action, params)

    def test_every_keyframe_action_is_gated_on_a_build_without_the_methods(self):
        for action, params in (
            ("get_keyframes", {"property": "ZoomX"}),
            ("add_keyframe", {"property": "ZoomX", "frame": 0, "value": 1.2}),
            ("modify_keyframe", {"property": "ZoomX", "frame": 0, "new_value": 1.3}),
            ("delete_keyframe", {"property": "ZoomX", "frame": 0}),
            ("set_keyframe_interpolation", {"property": "ZoomX", "frame": 0, "interpolation": "Linear"}),
        ):
            with self.subTest(action=action):
                out = self._call(action, params)
                self.assertEqual(out["error"]["code"], "KEYFRAME_API_UNAVAILABLE")
                self.assertIn("19.1.3.7", out["error"]["message"])

    def test_the_granular_server_gates_the_same_methods(self):
        from src.granular import timeline_item as granular_item
        message = granular_item._keyframe_api_missing(_NoKeyframeItem(), "AddKeyframe")
        self.assertIn("not available on this Resolve build", message)
        self.assertIsNone(granular_item._keyframe_api_missing(mock.Mock(), "AddKeyframe"))

    def test_a_build_with_the_methods_still_calls_them(self):
        item = mock.Mock()
        item.AddKeyframe.return_value = True
        with mock.patch.object(s, "_get_item", return_value=(mock.Mock(), item, None)):
            out = s.timeline_item("add_keyframe", {"property": "ZoomX", "frame": 0, "value": 1.2})
        self.assertTrue(out["success"])
        item.AddKeyframe.assert_called_once_with("ZoomX", 0, 1.2)


class _ProbeItem:
    def __init__(self, keyframed):
        self.keyframed = keyframed
        self.props = {"ZoomX": 1.0}
        self.writes = []

    def GetStart(self):
        return 86400

    def GetEnd(self):
        return 86448

    def GetProperty(self, key):
        return self.props.get(key)

    def SetProperty(self, key, value):
        self.writes.append((key, value))
        self.props[key] = value
        return True


class KeyframeOverrideProbeTest(unittest.TestCase):
    def _probe(self, keyframed, frames=None, ffmpeg=True):
        item = _ProbeItem(keyframed)
        shots = list(frames) if frames else None

        def _export(proj, tl, p, teardown):
            if shots:
                return Image(data=shots.pop(0), format="png")
            zoom = item.props["ZoomX"]
            visible = 1.0 if keyframed else zoom
            return Image(data=b"zoom=%0.2f" % visible, format="png")

        def _sig(data):
            if not ffmpeg:
                return None, "ffmpeg not found on PATH"
            # A textured 64-px row whose values follow the frame bytes.
            seed = sum(data) % 97
            return bytes((seed + i * 7) % 256 for i in range(64)), None

        with mock.patch.object(s, "_playhead_frame_export", side_effect=_export), \
             mock.patch.object(s, "_still_luma_signature", side_effect=_sig), \
             mock.patch.object(s, "_playback_refusal", return_value=None):
            out = s._timeline_item_probe_keyframe_override(mock.Mock(), mock.Mock(), item, {})
        return out, item

    def test_a_write_that_never_reaches_the_frame_is_an_override(self):
        out, item = self._probe(keyframed=True)
        self.assertEqual(out["verdict"], "override")
        self.assertTrue(out["set_property_returned"])
        self.assertEqual(item.props["ZoomX"], 1.0)  # restored
        self.assertTrue(out["restored"])

    def test_a_write_that_changes_the_frame_reaches_the_render(self):
        out, item = self._probe(keyframed=False)
        self.assertEqual(out["verdict"], "writes_render")
        self.assertEqual(item.writes[-1], ("ZoomX", 1.0))

    def test_a_null_control_that_differs_is_inconclusive(self):
        out, _ = self._probe(keyframed=True, frames=[b"a", b"zzzzzz", b"a"])
        self.assertEqual(out["verdict"], "inconclusive")

    def test_without_ffmpeg_the_bytes_decide(self):
        out, _ = self._probe(keyframed=True, ffmpeg=False)
        self.assertEqual(out["compare_method"], "bytes")
        self.assertEqual(out["verdict"], "override")

    def test_an_unsupported_property_is_refused(self):
        with mock.patch.object(s, "_playback_refusal", return_value=None):
            out = s._timeline_item_probe_keyframe_override(
                mock.Mock(), mock.Mock(), _ProbeItem(False), {"property": "Volume"})
        self.assertEqual(out["error"]["code"], "INVALID_PROPERTY")


# ── Locked tracks ──────────────────────────────────────────────────────────


class LockedTrackTest(unittest.TestCase):
    def test_delete_clips_on_a_locked_track_is_refused_before_the_call(self):
        item = mock.Mock()
        item.GetUniqueId.return_value = "item-1"
        item.GetTrackTypeAndIndex.return_value = ["video", 2]
        tl = mock.Mock()
        tl.GetTrackCount.side_effect = lambda kind: 2 if kind == "video" else 0
        tl.GetItemListInTrack.side_effect = lambda kind, idx: [item] if idx == 2 else []
        tl.GetIsTrackLocked.side_effect = lambda kind, idx: idx == 2
        proj = mock.Mock()
        proj.GetCurrentTimeline.return_value = tl
        with mock.patch.object(s, "get_resolve", return_value=None), \
             mock.patch.object(s, "_check", return_value=(mock.Mock(), proj, None)):
            out = s.timeline("delete_clips", {"clip_ids": ["item-1"]})
        self.assertEqual(out["error"]["code"], "TRACK_LOCKED")
        self.assertEqual(out["error"]["state"]["locked_tracks"], ["video:2"])
        tl.DeleteClips.assert_not_called()

    def test_append_failure_names_locked_target_tracks(self):
        tl = mock.Mock()
        tl.GetIsTrackLocked.side_effect = lambda kind, idx: (kind, idx) == ("video", 3)
        proj = mock.Mock()
        proj.GetCurrentTimeline.return_value = tl
        locked = s._append_target_locked_tracks(proj, [{"trackIndex": 3, "mediaType": 1}])
        self.assertEqual(locked, ["video:3"])
        out = s._append_to_timeline_failed("Failed", None, {}, {"item_count_delta": 0}, {},
                                           locked_tracks=locked)
        self.assertEqual(out["error"]["state"]["locked_tracks"], ["video:3"])
        self.assertIn("video:3", out["error"]["remediation"])


# ── replace_source_range (slip) ────────────────────────────────────────────


class _Pool:
    def __init__(self, fps="24"):
        self.fps = fps

    def GetUniqueId(self):
        return "pool-1"

    def GetName(self):
        return "credits.mov"

    def GetClipProperty(self, key=None):
        return self.fps if key == "FPS" else None


class _SlipItem:
    count = 0

    def __init__(self, tl, track, start, duration, src_start, mpi):
        _SlipItem.count += 1
        self.uid = f"item-{_SlipItem.count}"
        self.tl, self.track = tl, track
        self.start, self.duration, self.src_start = start, duration, src_start
        self.mpi = mpi
        self.props = {"ZoomX": 1.0, "ZoomY": 1.0, "Pan": 0.0, "Tilt": 0.0, "CropLeft": 0.0,
                      "Opacity": 100.0}
        self.grade_from = None

    def GetUniqueId(self):
        return self.uid

    def GetName(self):
        return "credits.mov"

    def GetStart(self):
        return self.start

    def GetEnd(self):
        return self.start + self.duration

    def GetDuration(self):
        return self.duration

    def GetSourceStartFrame(self):
        return self.src_start

    def GetMediaPoolItem(self):
        return self.mpi

    def GetTrackTypeAndIndex(self):
        return ["video", self.track]

    def GetLinkedItems(self):
        return []

    def GetFusionCompCount(self):
        return 0

    def GetProperty(self, key=None):
        return self.props.get(key)

    def SetProperty(self, key, value):
        self.props[key] = value
        return True

    def CopyGrades(self, targets):
        for target in targets:
            target.grade_from = self.grade_from or self.uid
        return True

    def GetNodeGraph(self):
        return None

    def GetClipColor(self):
        return ""

    def SetClipColor(self, color):
        return True

    def GetClipEnabled(self):
        return True

    def SetClipEnabled(self, enabled):
        return True

    def GetMarkers(self):
        return {}

    def GetFlagList(self):
        return []


class _SlipTimeline:
    def __init__(self, locked=False):
        self.tracks = {1: []}
        self.locked = {1: locked}
        self.lock_calls = []
        self.deleted_tracks = []

    def GetSetting(self, key):
        return "24" if key == "timelineFrameRate" else None

    def GetStartFrame(self):
        return 86400

    def GetTrackCount(self, kind):
        return len(self.tracks) if kind == "video" else 0

    def GetItemListInTrack(self, kind, idx):
        return list(self.tracks.get(idx, [])) if kind == "video" else []

    def GetIsTrackLocked(self, kind, idx):
        return self.locked.get(idx, False)

    def SetTrackLock(self, kind, idx, locked):
        self.lock_calls.append((idx, locked))
        self.locked[idx] = locked
        return True

    def AddTrack(self, kind):
        self.tracks[len(self.tracks) + 1] = []
        return True

    def DeleteTrack(self, kind, idx):
        self.deleted_tracks.append(idx)
        self.tracks.pop(idx, None)
        return True

    def DeleteClips(self, items, ripple):
        if any(self.locked.get(it.track) for it in items):
            return False
        for it in items:
            self.tracks[it.track].remove(it)
        return True


class _SlipMediaPool:
    def __init__(self, tl, short_first=False):
        self.tl = tl
        self.short_first = short_first
        self.appends = []

    def AppendToTimeline(self, infos):
        out = []
        for info in infos:
            self.appends.append(dict(info))
            duration = int(info["endFrame"]) - int(info["startFrame"])
            if self.short_first:
                duration -= 1  # the mixed-fps floor: a frame short every time
            item = _SlipItem(self.tl, int(info["trackIndex"]), int(info["recordFrame"]),
                             duration, int(info["startFrame"]), info["mediaPoolItem"])
            self.tl.tracks[item.track].append(item)
            out.append(item)
        return out


class ReplaceSourceRangeTest(unittest.TestCase):
    def _fixture(self, locked=False, short_first=False):
        tl = _SlipTimeline(locked=locked)
        mpi = _Pool()
        original = _SlipItem(tl, 1, 86448, 48, 100, mpi)
        original.props.update({"ZoomX": 1.34, "ZoomY": 1.34, "Pan": -500.0, "CropLeft": 12.0})
        original.grade_from = "the-grade"
        tl.tracks[1].append(original)
        mp = _SlipMediaPool(tl, short_first=short_first)
        proj = mock.Mock()
        proj.GetMediaPool.return_value = mp
        return proj, tl, mp, original

    def _run(self, proj, tl, params):
        with mock.patch.object(s, "_confirm_token_required", return_value=False), \
             mock.patch.object(s, "_playback_refusal", return_value=None):
            return s._timeline_replace_source_range_impl(proj, tl, params)

    def test_slip_keeps_record_timing_grade_and_sizing(self):
        proj, tl, mp, original = self._fixture()
        out = self._run(proj, tl, {"timeline_item_id": original.uid, "source_start": 160})
        self.assertTrue(out["success"], out)
        self.assertTrue(out["verified"], out)
        self.assertEqual(out["timing"]["start"], 86448)
        self.assertEqual(out["timing"]["duration"], 48)
        self.assertEqual(out["timing"]["source_start"], 160)
        final = tl.tracks[1][0]
        self.assertIsNot(final, original)
        self.assertEqual(final.grade_from, "the-grade")
        self.assertEqual(final.props["Pan"], -500.0)
        self.assertEqual(final.props["CropLeft"], 12.0)
        # temp track gone, original deleted, nothing else on the track
        self.assertEqual(len(tl.tracks), 1)
        self.assertEqual(len(tl.tracks[1]), 1)
        # the first append is the temporary copy, on its own track
        self.assertEqual([a["trackIndex"] for a in mp.appends], [2, 1])

    def test_slip_frames_is_an_offset(self):
        proj, tl, _, original = self._fixture()
        out = self._run(proj, tl, {"timeline_item_id": original.uid, "slip_frames": -10})
        self.assertEqual(out["timing"]["source_start"], 90)

    def test_a_length_a_frame_short_is_corrected_and_retried(self):
        proj, tl, mp, original = self._fixture(short_first=True)
        out = self._run(proj, tl, {"timeline_item_id": original.uid, "source_start": 160})
        self.assertTrue(out["verified"], out)
        temp_attempts = out["steps"]["temp_append"]
        self.assertEqual([a["duration"] for a in temp_attempts], [47, 48])
        self.assertEqual(mp.appends[1]["endFrame"], mp.appends[0]["endFrame"] + 1)
        # the corrected endFrame carries over to the final placement
        self.assertEqual(mp.appends[2]["endFrame"], mp.appends[1]["endFrame"])

    def test_a_locked_track_is_refused_without_unlock_track(self):
        proj, tl, mp, original = self._fixture(locked=True)
        out = self._run(proj, tl, {"timeline_item_id": original.uid, "source_start": 160})
        self.assertEqual(out["error"]["code"], "TRACK_LOCKED")
        self.assertIn("unlock_track=true", out["error"]["remediation"])
        self.assertEqual(mp.appends, [])

    def test_unlock_track_unlocks_for_the_swap_and_locks_again(self):
        proj, tl, _, original = self._fixture(locked=True)
        out = self._run(proj, tl, {"timeline_item_id": original.uid, "source_start": 160,
                                   "unlock_track": True})
        self.assertTrue(out["verified"], out)
        self.assertEqual(tl.lock_calls, [(1, False), (1, True)])
        self.assertTrue(out["track_relocked"])

    def test_dry_run_returns_the_plan_and_changes_nothing(self):
        proj, tl, mp, original = self._fixture()
        out = self._run(proj, tl, {"timeline_item_id": original.uid, "source_start": 160,
                                   "dry_run": True})
        self.assertTrue(out["dry_run"])
        self.assertEqual(out["plan"]["source_after"], {"start": 160, "end_exclusive": 208})
        self.assertEqual(mp.appends, [])

    def test_execution_is_confirm_token_gated(self):
        proj, tl, mp, original = self._fixture()
        with mock.patch.object(s, "_confirm_token_required", return_value=True), \
             mock.patch.object(s, "_playback_refusal", return_value=None):
            out = s._timeline_replace_source_range_impl(
                proj, tl, {"timeline_item_id": original.uid, "source_start": 160})
        self.assertIn("confirm_token", str(out))
        self.assertEqual(mp.appends, [])

    def test_a_failed_final_append_leaves_the_temporary_copy_as_recovery(self):
        proj, tl, mp, original = self._fixture()
        real_append = mp.AppendToTimeline

        def _append(infos):
            if int(infos[0]["trackIndex"]) == 1:
                return []
            return real_append(infos)

        mp.AppendToTimeline = _append
        out = self._run(proj, tl, {"timeline_item_id": original.uid, "source_start": 160})
        self.assertEqual(out["error"]["code"], "SLIP_FINAL_APPEND_FAILED")
        recovery = out["error"]["state"]["recovery"]
        self.assertEqual(recovery["temp_track"], 2)
        self.assertEqual(len(tl.tracks[2]), 1)
        self.assertEqual(tl.tracks[2][0].grade_from, "the-grade")

    def test_registered_as_a_gated_high_risk_write(self):
        from src.utils.destructive_hook import DESTRUCTIVE_ACTIONS_BY_TOOL, NATIVE_DRY_RUN_ACTIONS
        from src.utils.execution_lifecycle import classify_operation_risk
        self.assertIn("replace_source_range", DESTRUCTIVE_ACTIONS_BY_TOOL["timeline"])
        self.assertIn(("timeline", "replace_source_range"), NATIVE_DRY_RUN_ACTIONS)
        self.assertIn(("timeline", "replace_source_range"), s._TOKEN_GATED_DESTRUCTIVE_ACTIONS)
        risk = classify_operation_risk("timeline", "replace_source_range", {}).to_dict()
        self.assertTrue(risk["recognised"])
        self.assertIn("probe_keyframe_override", DESTRUCTIVE_ACTIONS_BY_TOOL["timeline_item"])


# ── Edit transform pixel units ─────────────────────────────────────────────


class TransformPixelUnitsTest(unittest.TestCase):
    def _item(self, scaling=2, resolution="720x1280", zoom=1.0):
        item = mock.Mock()
        props = {"Scaling": scaling, "ZoomX": zoom}
        item.GetProperty.side_effect = lambda key: props.get(key)
        item.SetProperty.return_value = True
        item.GetMediaPoolItem.return_value.GetClipProperty.side_effect = (
            lambda key: resolution if key == "Resolution" else None)
        return item

    def _tl(self):
        tl = mock.Mock()
        settings = {"timelineResolutionWidth": "4096", "timelineResolutionHeight": "1716",
                    "timelineInputResScaleType": "scaleToFit"}
        tl.GetSetting.side_effect = lambda key: settings.get(key)
        return tl

    def test_the_measured_portrait_case(self):
        conv, err = s._edit_transform_pixel_units(self._tl(), self._item(), {})
        self.assertIsNone(err)
        self.assertEqual(conv["fitted_size"], [965.25, 1716.0])
        # Pan -500 moved the clip 117 px in the measured session.
        self.assertAlmostEqual(-500 * conv["pan_px_per_unit"], -117.8, places=1)
        self.assertEqual(conv["tilt_px_per_unit"], 1.0)

    def test_set_transform_converts_pixel_offsets(self):
        item, tl = self._item(), self._tl()
        with mock.patch.object(s, "_get_item", return_value=(tl, item, None)):
            out = s.timeline_item("set_transform", {"pan_px": -500 * 965.25 / 4096, "tilt_px": 50})
        pan = [c.args for c in item.SetProperty.call_args_list if c.args[0] == "Pan"][0][1]
        tilt = [c.args for c in item.SetProperty.call_args_list if c.args[0] == "Tilt"][0][1]
        self.assertAlmostEqual(pan, -500.0, places=3)
        self.assertAlmostEqual(tilt, 50.0, places=6)
        self.assertEqual(out["pixel_conversion"]["model"], "scale to fit")

    def test_project_scaling_inherits_fit(self):
        conv, err = s._edit_transform_pixel_units(self._tl(), self._item(scaling=0), {})
        self.assertIsNone(err)

    def test_an_unmeasured_scaling_mode_needs_the_fitted_size(self):
        _, err = s._edit_transform_pixel_units(self._tl(), self._item(scaling=3), {})
        self.assertEqual(err["error"]["code"], "SCALING_MODE_UNMEASURED")
        conv, err = s._edit_transform_pixel_units(
            self._tl(), self._item(scaling=3), {"fitted_width": 4096, "fitted_height": 7282})
        self.assertIsNone(err)
        self.assertEqual(conv["pan_px_per_unit"], 1.0)

    def test_a_non_unit_zoom_carries_a_caveat(self):
        conv, _ = s._edit_transform_pixel_units(self._tl(), self._item(zoom=1.5), {})
        self.assertIn("not measured", conv["caveat"])

    def test_pan_and_pan_px_together_are_refused(self):
        with mock.patch.object(s, "_get_item", return_value=(self._tl(), self._item(), None)):
            out = s.timeline_item("set_transform", {"Pan": 10, "pan_px": 5})
        self.assertEqual(out["error"]["code"], "CONFLICTING_PARAMS")


if __name__ == "__main__":
    unittest.main()
