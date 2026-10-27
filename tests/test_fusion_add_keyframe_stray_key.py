"""add_keyframe removes the key Fusion drops when it attaches a spline.

Measured on Studio 21.0.2.4 (api_truth "BezierSpline attach (stray key at the
current time)"): AddModifier(input, "BezierSpline") adds a key at the comp's
current time holding the input's old value. Keying frames 10 and 20 on a Blur
left keys [0, 10, 20], so the value ramped from the old 1.0 instead of holding
the first intended key. DeleteKeyFrames(time) removes it once a real key exists.
"""
import unittest
from unittest.mock import patch

from src import server


class _Spline:
    def __init__(self):
        self.keys = {}
        self.deleted = []

    def DeleteKeyFrames(self, time):
        self.deleted.append(time)
        self.keys.pop(float(time), None)


class _Output:
    def __init__(self, spline):
        self._spline = spline

    def GetTool(self):
        return self._spline


class _Input:
    def __init__(self, old_value=1.0, spline_cls=_Spline):
        self.old_value = old_value
        self.spline_cls = spline_cls
        self.spline = None

    def GetAttrs(self):
        return {"INPS_ID": "XBlurSize", "INPID_InputControl": "SliderControl"}

    def GetConnectedOutput(self):
        return _Output(self.spline) if self.spline is not None else None

    def GetKeyFrames(self):
        # Fusion's Input.GetKeyFrames: {1-based index: frame}.
        if self.spline is None:
            return None
        return {i: f for i, f in enumerate(sorted(self.spline.keys), start=1)}

    def __setitem__(self, time, value):
        if self.spline is not None:
            self.spline.keys[float(time)] = value


class _Tool:
    def __init__(self, inp, current_time):
        self.inp = inp
        self.current_time = current_time

    def __getitem__(self, name):
        return self.inp if name == "XBlurSize" else None

    def GetInputList(self):
        return {1: self.inp}

    def AddModifier(self, input_name, modifier_id):
        # What Fusion does: attaching an empty spline keys the current time.
        self.inp.spline = self.inp.spline_cls()
        self.inp.spline.keys[float(self.current_time)] = self.inp.old_value
        return True


class _Comp:
    def __init__(self, tool):
        self._tool = tool

    def FindTool(self, name):
        return self._tool if name == "Blur1" else None

    def StartUndo(self, name):
        pass

    def EndUndo(self, keep):
        pass


def _keyframe(tool, time, value):
    with patch.object(server, "_resolve_fusion_comp", return_value=(_Comp(tool), None)):
        return server.fusion_comp("add_keyframe", {"tool_name": "Blur1", "input_name": "XBlurSize",
                                                   "time": time, "value": value})


class StrayKeyTests(unittest.TestCase):
    def test_first_key_away_from_current_time_removes_the_stray_key(self):
        tool = _Tool(_Input(old_value=1.0), current_time=0)
        out = _keyframe(tool, 10, 5.0)
        self.assertTrue(out.get("success"), out)
        self.assertEqual(tool.inp.spline.keys, {10.0: 5.0})
        self.assertEqual(out["removed_stray_keys"], [0.0])

    def test_second_key_keeps_both_real_keys(self):
        tool = _Tool(_Input(), current_time=0)
        _keyframe(tool, 10, 5.0)
        out = _keyframe(tool, 20, 9.0)
        self.assertTrue(out.get("success"), out)
        self.assertEqual(tool.inp.spline.keys, {10.0: 5.0, 20.0: 9.0})
        self.assertNotIn("removed_stray_keys", out)

    def test_first_key_at_current_time_overwrites_instead(self):
        tool = _Tool(_Input(old_value=1.0), current_time=12)
        out = _keyframe(tool, 12, 3.0)
        self.assertTrue(out.get("success"), out)
        self.assertEqual(tool.inp.spline.keys, {12.0: 3.0})
        self.assertEqual(tool.inp.spline.deleted, [])
        self.assertNotIn("removed_stray_keys", out)

    def test_undeletable_stray_key_is_reported_not_hidden(self):
        class _StickySpline(_Spline):
            def DeleteKeyFrames(self, time):
                self.deleted.append(time)   # Fusion returns, key stays

        tool = _Tool(_Input(spline_cls=_StickySpline), current_time=0)
        out = _keyframe(tool, 10, 5.0)
        self.assertTrue(out.get("success"), out)
        self.assertEqual(out["stray_keys_remaining"], [0.0])
        self.assertIn("delete_keyframe", out["warning"])


    def test_text_modifier_range_bounds_are_not_stray_keys(self):
        # Measured live: a StyledTextFollower answers Input.GetKeyFrames with
        # its render-range bounds [-1e9, 1e9] and has no DeleteKeyFrames.
        class _Follower:
            keys = {-1e9: None, 1e9: None}

        tool = _Tool(_Input(spline_cls=_Follower), current_time=0)
        out = _keyframe(tool, 0, "Hi")
        self.assertTrue(out.get("success"), out)
        self.assertNotIn("warning", out)
        self.assertNotIn("removed_stray_keys", out)


if __name__ == "__main__":
    unittest.main()
