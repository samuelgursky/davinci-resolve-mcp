"""Tests for auto-sync audio normalization + the get_resolve() fix.

The enum-constant source must be get_resolve(), not the module global `resolve`
(which can be None and silently degrade AutoSyncAudio to string keys).
"""
import unittest
from unittest import mock

import src.server as s


class FakeResolve:
    AUDIO_SYNC_MODE = "__MODE__"
    AUDIO_SYNC_WAVEFORM = "__WAVEFORM__"
    AUDIO_SYNC_TIMECODE = "__TIMECODE__"
    AUDIO_SYNC_CHANNEL_NUMBER = "__CHAN__"
    AUDIO_SYNC_CHANNEL_AUTOMATIC = -1
    AUDIO_SYNC_CHANNEL_MIX = -2
    AUDIO_SYNC_RETAIN_EMBEDDED_AUDIO = "__RET_EMB__"
    AUDIO_SYNC_RETAIN_VIDEO_METADATA = "__RET_META__"


class NormalizeTest(unittest.TestCase):
    def test_string_mode_resolves_to_enum_with_resolve(self):
        out = s._normalize_auto_sync_settings({"mode": "waveform"}, FakeResolve())
        self.assertEqual(out["__MODE__"], "__WAVEFORM__")

    def test_timecode_mode_resolves(self):
        out = s._normalize_auto_sync_settings({"mode": "timecode"}, FakeResolve())
        self.assertEqual(out["__MODE__"], "__TIMECODE__")

    def test_missing_resolve_falls_back_to_string_keys(self):
        # The bug condition: with no resolve object the enum constant can't be
        # resolved, so we fall back to the literal string key/value — which
        # AutoSyncAudio silently rejects (returns False).
        out = s._normalize_auto_sync_settings({"mode": "waveform"}, None)
        self.assertIn("syncMode", out)
        self.assertEqual(out["syncMode"], "waveform")


class SafeAutoSyncTest(unittest.TestCase):
    def test_dry_run_uses_get_resolve_for_constants(self):
        fake_mp = mock.Mock()
        with mock.patch.object(s, "get_resolve", return_value=FakeResolve()), \
             mock.patch.object(s, "_clips_from_params", return_value=((["c1"], []), None)), \
             mock.patch.object(s, "_clip_summaries", return_value=[]):
            out = s._safe_auto_sync_audio(
                fake_mp, {"settings": {"mode": "waveform"}, "dry_run": True}
            )
        # Resolved enum constant present => get_resolve() supplied constants (#4 fix).
        self.assertEqual(out["settings"]["__MODE__"], "__WAVEFORM__")

    def test_non_dry_run_calls_api_with_normalized_settings(self):
        captured = {}
        fake_mp = mock.Mock()
        fake_mp.AutoSyncAudio.side_effect = (
            lambda clips, settings: captured.update(settings=settings, clips=clips) or True
        )
        with mock.patch.object(s, "get_resolve", return_value=FakeResolve()), \
             mock.patch.object(s, "_clips_from_params", return_value=((["c1"], []), None)):
            out = s._safe_auto_sync_audio(
                fake_mp, {"settings": {"mode": "timecode"}, "dry_run": False}
            )
        self.assertTrue(out["success"])
        self.assertEqual(captured["settings"]["__MODE__"], "__TIMECODE__")

    def test_readback_reports_newly_and_already_linked(self):
        # The readback verification must report linkage by reading "Synced Audio"
        # before/after, not by trusting AutoSyncAudio's boolean.
        class SyncClip:
            def __init__(self, name, synced):
                self.name = name
                self._synced = synced

            def GetName(self):
                return self.name

            def GetClipProperty(self, key):
                if key == "Synced Audio":
                    return "linked.wav" if self._synced else ""
                return ""

        c_new = SyncClip("v_new", synced=False)   # becomes linked
        c_old = SyncClip("v_old", synced=True)     # already linked
        clips = [c_new, c_old]
        fake_mp = mock.Mock()

        def do_sync(cs, settings):
            for c in cs:
                c._synced = True
            return True

        fake_mp.AutoSyncAudio.side_effect = do_sync
        with mock.patch.object(s, "get_resolve", return_value=FakeResolve()), \
             mock.patch.object(s, "_clips_from_params", return_value=((clips, []), None)):
            out = s._safe_auto_sync_audio(fake_mp, {"settings": {}, "dry_run": False})
        self.assertEqual(out["newly_linked"], ["v_new"])
        self.assertEqual(out["already_linked"], ["v_old"])
        self.assertEqual(set(out["linked"]), {"v_new", "v_old"})

    def test_readback_unlinked_stays_out(self):
        class SyncClip:
            def __init__(self, name):
                self.name = name

            def GetName(self):
                return self.name

            def GetClipProperty(self, key):
                return ""  # never links

        clips = [SyncClip("v1")]
        fake_mp = mock.Mock()
        fake_mp.AutoSyncAudio.return_value = True  # lies: says success
        with mock.patch.object(s, "get_resolve", return_value=FakeResolve()), \
             mock.patch.object(s, "_clips_from_params", return_value=((clips, []), None)):
            out = s._safe_auto_sync_audio(fake_mp, {"settings": {}, "dry_run": False})
        # success boolean is True but readback shows nothing actually linked
        self.assertTrue(out["success"])
        self.assertEqual(out["linked"], [])
        self.assertEqual(out["newly_linked"], [])

    def test_regression_module_global_resolve_none_does_not_degrade(self):
        # Even if the module global `resolve` is None, the fix routes through
        # get_resolve(), so constants still resolve.
        fake_mp = mock.Mock()
        with mock.patch.object(s, "resolve", None), \
             mock.patch.object(s, "get_resolve", return_value=FakeResolve()), \
             mock.patch.object(s, "_clips_from_params", return_value=((["c1"], []), None)), \
             mock.patch.object(s, "_clip_summaries", return_value=[]):
            out = s._safe_auto_sync_audio(
                fake_mp, {"settings": {"mode": "waveform"}, "dry_run": True}
            )
        self.assertEqual(out["settings"]["__MODE__"], "__WAVEFORM__")


if __name__ == "__main__":
    unittest.main()
