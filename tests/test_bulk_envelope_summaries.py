"""Bulk per-op tools must reflect their rows at the top level — a bare
{results, op_count} envelope (or an unconditional success:True) made
all-failed and all-succeeded calls indistinguishable to an envelope-reading
caller. Same class as import_from_drp reporting success over failed rows."""
import unittest
from unittest import mock

from src import server
from src.server import _summarize_bulk_results


class SummarizeBulkResultsTest(unittest.TestCase):
    def test_all_succeeded(self):
        out = _summarize_bulk_results([{"success": True}, {"success": True}], 2)
        self.assertTrue(out["success"])
        self.assertEqual((out["succeeded"], out["failed"]), (2, 0))
        self.assertNotIn("warning", out)

    def test_all_failed_is_an_error(self):
        out = _summarize_bulk_results([{"error": "x"}, {"error": "y"}], 2)
        self.assertFalse(out["success"])
        self.assertIn("All 2 op(s) failed", out["error"])

    def test_partial_is_flagged(self):
        out = _summarize_bulk_results([{"success": True}, {"error": "y"}], 2)
        self.assertTrue(out["partial"])
        self.assertIn("1 of 2", out["warning"])


class BulkSetTitleTextEnvelopeTest(unittest.TestCase):
    def test_all_failed_ops_fail_the_envelope(self):
        tl = mock.Mock()
        with mock.patch.object(server, "_timeline_set_title_text",
                               return_value={"success": False, "error": "no keys"}):
            out = server._timeline_bulk_set_title_text(tl, {"ops": [{"text": "A"}, {"text": "B"}]})
        self.assertFalse(out["success"])
        self.assertEqual(out["failed"], 2)


class AddMaskEnvelopeTest(unittest.TestCase):
    def _comp(self, set_input_raises):
        tool = mock.Mock()
        if set_input_raises:
            tool.SetInput.side_effect = RuntimeError("unsupported input")
        tool.GetAttrs.return_value = {"TOOLS_RegID": "RectangleMask"}
        comp = mock.Mock()
        comp.AddTool.return_value = tool
        comp.FindTool.return_value = None
        return comp

    def test_all_inputs_failing_fails_the_envelope(self):
        comp = self._comp(set_input_raises=True)
        out = server._fusion_add_mask(comp, {"mask_type": "Rectangle", "inputs": {"Width": 0.3, "Height": 0.4}})
        self.assertFalse(out["success"], out)
        self.assertIn("default-shaped", out["error"])

    def test_clean_apply_succeeds(self):
        comp = self._comp(set_input_raises=False)
        out = server._fusion_add_mask(comp, {"mask_type": "Rectangle", "inputs": {"Width": 0.3, "Height": 0.4}})
        self.assertTrue(out["success"], out)
        self.assertNotIn("error", out)


if __name__ == "__main__":
    unittest.main()
