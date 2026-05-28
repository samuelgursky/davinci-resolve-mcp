"""F1 contract test — aggregated provenance citation map on summarize.

See local/design/agentic-flow-improvements-gameplan-2.md §3 task F1.

Exercises `summarize_reports` against a tmpdir that mimics the analysis-root
layout (clips/<dir>/analysis.json files). Asserts the response carries a
`provenance` block with source_reports keyed by signature and a generated_at
timestamp.
"""
import json
import os
import tempfile
import unittest

from src.utils.media_analysis import summarize_reports


def _write_report(clip_dir: str, *, signature: str = None, clip_id: str = "c-1",
                  clip_name: str = "clip.mp4") -> str:
    os.makedirs(clip_dir, exist_ok=True)
    path = os.path.join(clip_dir, "analysis.json")
    body = {
        "clip_id": clip_id,
        "clip_name": clip_name,
        "analysis_signature": signature,
        "analyzed_at": "2026-05-27T22:00:00Z",
        "record": {"clip_id": clip_id, "clip_name": clip_name},
        "technical": {"width": 1920, "height": 1080},
        "motion": {"overall_motion_level": "medium"},
        "visual": {"editing_notes": {"search_tags": ["interview", "close-up"]}},
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(body, fh)
    return path


class ProvenanceCitationMapTest(unittest.TestCase):
    def test_summarize_emits_provenance_block(self):
        with tempfile.TemporaryDirectory() as project_root:
            clips_root = os.path.join(project_root, "clips")
            _write_report(os.path.join(clips_root, "clip-a"),
                          signature="sig-aaa", clip_id="c-a", clip_name="A.mp4")
            _write_report(os.path.join(clips_root, "clip-b"),
                          signature="sig-bbb", clip_id="c-b", clip_name="B.mp4")
            out = summarize_reports(project_root)
        self.assertIn("provenance", out)
        prov = out["provenance"]
        self.assertIn("generated_at", prov)
        self.assertEqual(prov["scope"]["type"], "project")
        self.assertEqual(len(prov["source_reports"]), 2)

    def test_source_reports_carry_signature_and_path(self):
        with tempfile.TemporaryDirectory() as project_root:
            clips_root = os.path.join(project_root, "clips")
            _write_report(os.path.join(clips_root, "clip-a"),
                          signature="sig-aaa", clip_id="c-a", clip_name="A.mp4")
            out = summarize_reports(project_root)
        entry = out["provenance"]["source_reports"][0]
        self.assertEqual(entry["clip_id"], "c-a")
        self.assertEqual(entry["clip_name"], "A.mp4")
        self.assertEqual(entry["analysis_signature"], "sig-aaa")
        self.assertTrue(entry["analysis_report_path"].endswith("analysis.json"))
        self.assertEqual(entry["analyzed_at"], "2026-05-27T22:00:00Z")

    def test_unsigned_report_shows_up_in_missing_reports(self):
        with tempfile.TemporaryDirectory() as project_root:
            clips_root = os.path.join(project_root, "clips")
            _write_report(os.path.join(clips_root, "clip-a"),
                          signature=None, clip_id="c-a")  # unsigned
            _write_report(os.path.join(clips_root, "clip-b"),
                          signature="sig-bbb", clip_id="c-b")
            out = summarize_reports(project_root)
        # Both reports still surface in source_reports (the citation map is
        # exhaustive), but the unsigned one is flagged in missing_reports.
        self.assertEqual(len(out["provenance"]["source_reports"]), 2)
        missing = out["provenance"]["missing_reports"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["reason"], "unsigned_report")

    def test_empty_project_returns_empty_provenance(self):
        with tempfile.TemporaryDirectory() as project_root:
            out = summarize_reports(project_root)
        self.assertEqual(out["provenance"]["source_reports"], [])
        self.assertEqual(out["provenance"]["missing_reports"], [])


if __name__ == "__main__":
    unittest.main()
