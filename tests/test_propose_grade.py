"""Contract tests for C2 — propose_grade structured output action.

See local/design/agentic-flow-improvements-gameplan.md §3 task C2.
"""
import unittest

import src.server as compound


GOOD_EVIDENCE = "evidence base: hero shot 2A graded (Version 1, 3 nodes)"


class ProposeGradeValidationTest(unittest.TestCase):
    def test_missing_target_id(self):
        err = compound._propose_grade_validate({
            "evidence_base": GOOD_EVIDENCE,
            "frame_paths": ["/a.jpg"],
            "operation_class": "review_only",
        })
        self.assertEqual(err["error"]["code"], "MISSING_TARGET_ID")

    def test_missing_evidence_base(self):
        err = compound._propose_grade_validate({
            "target_id": "x", "frame_paths": ["/a.jpg"], "operation_class": "review_only",
        })
        self.assertEqual(err["error"]["code"], "MISSING_EVIDENCE_BASE")

    def test_evidence_base_must_start_with_canonical_prefix(self):
        err = compound._propose_grade_validate({
            "target_id": "x", "evidence_base": "some other prefix",
            "frame_paths": ["/a.jpg"], "operation_class": "review_only",
        })
        self.assertEqual(err["error"]["code"], "EVIDENCE_BASE_MALFORMED")

    def test_missing_frame_paths(self):
        err = compound._propose_grade_validate({
            "target_id": "x", "evidence_base": GOOD_EVIDENCE,
            "operation_class": "direct",
        })
        self.assertEqual(err["error"]["code"], "MISSING_FRAME_PATHS")

    def test_invalid_operation_class(self):
        err = compound._propose_grade_validate({
            "target_id": "x", "evidence_base": GOOD_EVIDENCE,
            "frame_paths": ["/a.jpg"], "operation_class": "garbage",
        })
        self.assertEqual(err["error"]["code"], "INVALID_OPERATION_CLASS")

    def test_direct_requires_cdl(self):
        err = compound._propose_grade_validate({
            "target_id": "x", "evidence_base": GOOD_EVIDENCE,
            "frame_paths": ["/a.jpg"], "operation_class": "direct",
            "cdl_delta_or_artifact": {},
        })
        self.assertEqual(err["error"]["code"], "DIRECT_REQUIRES_CDL")

    def test_opaque_requires_artifact(self):
        err = compound._propose_grade_validate({
            "target_id": "x", "evidence_base": GOOD_EVIDENCE,
            "frame_paths": ["/a.jpg"], "operation_class": "opaque",
            "cdl_delta_or_artifact": {},
        })
        self.assertEqual(err["error"]["code"], "OPAQUE_REQUIRES_ARTIFACT")

    def test_asset_requires_lut_path(self):
        err = compound._propose_grade_validate({
            "target_id": "x", "evidence_base": GOOD_EVIDENCE,
            "frame_paths": ["/a.jpg"], "operation_class": "asset",
            "cdl_delta_or_artifact": {},
        })
        self.assertEqual(err["error"]["code"], "ASSET_REQUIRES_LUT_PATH")

    def test_review_only_requires_two_frames(self):
        err = compound._propose_grade_validate({
            "target_id": "x", "evidence_base": GOOD_EVIDENCE,
            "frame_paths": ["/only_one.jpg"], "operation_class": "review_only",
        })
        self.assertEqual(err["error"]["code"], "REVIEW_NEEDS_FRAMES")

    def test_unsupported_requires_explanation(self):
        err = compound._propose_grade_validate({
            "target_id": "x", "evidence_base": GOOD_EVIDENCE,
            "frame_paths": ["/a.jpg"], "operation_class": "unsupported",
        })
        self.assertEqual(err["error"]["code"], "UNSUPPORTED_NEEDS_EXPLANATION")

    def test_valid_review_only(self):
        err = compound._propose_grade_validate({
            "target_id": "x", "evidence_base": GOOD_EVIDENCE,
            "frame_paths": ["/a.jpg", "/b.jpg"], "operation_class": "review_only",
        })
        self.assertIsNone(err)


class ProposeGradeExecuteTest(unittest.TestCase):
    def test_default_does_not_execute(self):
        out = compound._propose_grade(None, {
            "target_id": "x", "evidence_base": GOOD_EVIDENCE,
            "frame_paths": ["/a.jpg", "/b.jpg"], "operation_class": "review_only",
        })
        self.assertTrue(out["accepted"])
        self.assertFalse(out["executed"])
        self.assertTrue(out["plan_id"].startswith("plan_"))

    def test_execute_review_only_is_noop(self):
        out = compound._propose_grade(None, {
            "target_id": "x", "evidence_base": GOOD_EVIDENCE,
            "frame_paths": ["/a.jpg", "/b.jpg"],
            "operation_class": "review_only", "execute": True,
        })
        self.assertFalse(out["executed"])
        self.assertIn("notes", out["validation"])


if __name__ == "__main__":
    unittest.main()
