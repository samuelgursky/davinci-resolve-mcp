"""Tests for the Cut-IR Pass-1 mechanical detector and propose_cuts action."""
import unittest
from unittest import mock

import src.server as s
from src.utils import cut_ir


class FillerTest(unittest.TestCase):
    def test_filler_words(self):
        self.assertTrue(cut_ir._is_filler_only("um"))
        self.assertTrue(cut_ir._is_filler_only("Uh."))
        self.assertTrue(cut_ir._is_filler_only("um uh"))

    def test_filler_phrase(self):
        self.assertTrue(cut_ir._is_filler_only("you know"))

    def test_not_filler(self):
        self.assertFalse(cut_ir._is_filler_only("hello world"))
        self.assertFalse(cut_ir._is_filler_only(""))


class Pass1Test(unittest.TestCase):
    def test_detects_filler(self):
        cues = [{"text": "um", "start": 0, "end": 10},
                {"text": "the real point", "start": 12, "end": 60}]
        cuts = cut_ir.detect_cuts_pass1(cues)
        kinds = [c["kind"] for c in cuts]
        self.assertIn("filler", kinds)
        f = next(c for c in cuts if c["kind"] == "filler")
        self.assertEqual(f["span"], {"start": 0, "end": 10})
        self.assertEqual(f["action"], "lift")

    def test_detects_repeat(self):
        cues = [{"text": "let me start", "start": 0, "end": 20},
                {"text": "let me start", "start": 22, "end": 42}]
        kinds = [c["kind"] for c in cut_ir.detect_cuts_pass1(cues)]
        self.assertIn("stammer", kinds)

    def test_detects_long_pause(self):
        cues = [{"text": "first", "start": 0, "end": 20},
                {"text": "second", "start": 200, "end": 220}]
        cuts = cut_ir.detect_cuts_pass1(cues, long_pause_frames=48)
        pause = next(c for c in cuts if c["kind"] == "long_pause")
        self.assertEqual(pause["span"], {"start": 20, "end": 200})

    def test_no_false_positives(self):
        cues = [{"text": "a clean sentence", "start": 0, "end": 24},
                {"text": "another clean one", "start": 26, "end": 50}]
        self.assertEqual(cut_ir.detect_cuts_pass1(cues), [])

    def test_build_cut_list_shape(self):
        out = cut_ir.build_cut_list([{"text": "um", "start": 0, "end": 5}])
        self.assertEqual(out["cut_count"], 1)
        self.assertEqual(out["basis_cue_count"], 1)
        self.assertEqual(out["pass"], "mechanical")
        self.assertIn("Dry-run", out["note"])


class ProposeCutsActionTest(unittest.TestCase):
    def _call(self, params):
        proj = mock.Mock()
        proj.GetCurrentTimeline.return_value = mock.Mock()
        with mock.patch.object(s, "_check", return_value=(None, proj, None)):
            return s.timeline("propose_cuts", params)

    def test_provided_cues(self):
        out = self._call({"cues": [
            {"text": "um", "start": 0, "end": 10},
            {"text": "the point", "start": 12, "end": 60},
        ]})
        self.assertGreaterEqual(out["cut_count"], 1)
        self.assertEqual(out["basis_cue_count"], 2)

    def test_dry_run_note(self):
        out = self._call({"cues": []})
        self.assertEqual(out["cut_count"], 0)
        self.assertIn("no edits", out["note"].lower())


if __name__ == "__main__":
    unittest.main()
