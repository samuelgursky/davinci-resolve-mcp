"""Regression tests: pin readback (#344) and audio-only vision gate (#345)."""
import unittest
from unittest import mock

from src.utils import media_analysis as ma


class AudioOnlyTests(unittest.TestCase):
    def test_audio_only_detected(self):
        self.assertTrue(ma._is_audio_only({"summary": {"video": [], "audio": [{"codec": "pcm"}]}}))

    def test_video_not_audio_only(self):
        self.assertFalse(ma._is_audio_only({"summary": {"video": [{}], "audio": [{}]}}))

    def test_empty_not_audio_only(self):
        self.assertFalse(ma._is_audio_only({"summary": {"video": [], "audio": []}}))


class _TL:
    def __init__(self, uid):
        self.uid = uid

    def GetUniqueId(self):
        return self.uid

    def GetName(self):
        return self.uid


class PinReadbackTests(unittest.TestCase):
    def _scope(self, set_result, stays_put):
        from src import server

        original, target = _TL("a"), _TL("b")
        state = {"cur": original}

        class Proj:
            def GetCurrentTimeline(self):
                return state["cur"]

            def SetCurrentTimeline(self, tl):
                if not stays_put:
                    state["cur"] = tl
                return set_result

        scope = object.__new__(server._CallScope)
        scope.params = {"timeline_id": "b"}
        scope.pin = None
        with mock.patch.object(server, "_check", return_value=(None, Proj(), None)), \
             mock.patch.object(server, "_find_timeline_by_id", return_value=(target, None)):
            return scope._pin(), scope

    def test_true_but_stayed_put_is_error(self):
        err, scope = self._scope(True, True)
        self.assertEqual(err["error"]["code"] if "error" in err and isinstance(err["error"], dict) else err.get("code"), "TIMELINE_PIN_FAILED")
        self.assertIsNone(scope.pin)

    def test_real_switch_pins(self):
        err, scope = self._scope(True, False)
        self.assertIsNone(err)
        self.assertIsNotNone(scope.pin)


if __name__ == "__main__":
    unittest.main()
