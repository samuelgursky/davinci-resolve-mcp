import unittest

from src.utils.timeline_kernel_probe import (
    ProbeRecorder,
    parse_api_class_methods,
    parse_timeline_item_property_keys,
    render_markdown_report,
    values_match,
)


class TimelineKernelProbeHelpersTest(unittest.TestCase):
    def test_parse_timeline_item_property_keys_preserves_doc_order(self):
        api_text = '''
Looking up Timeline item properties
The supported keys with their accepted values are:
  "Pan" : floating point values
  "Tilt" : floating point values
  "Pan" : duplicate entry
  "Opacity" : floating point values
Values beyond the range will be clipped
'''

        self.assertEqual(parse_timeline_item_property_keys(api_text), ["Pan", "Tilt", "Opacity"])

    def test_parse_api_class_methods_stops_at_next_class(self):
        api_text = """
Timeline
  GetTrackCount(trackType)                        --> int
  DeleteClips([timelineItems], Bool)              --> Bool
TimelineItem
  GetName()                                       --> string
"""

        self.assertEqual(parse_api_class_methods(api_text, "Timeline"), ["GetTrackCount", "DeleteClips"])

    def test_probe_recorder_counts_and_validates_status(self):
        recorder = ProbeRecorder()

        recorder.record("runtime", "Timeline.GetTrackCount", "supported")
        recorder.record("runtime", "Timeline.SplitClip", "unsupported")

        self.assertEqual(recorder.counts()["supported"], 1)
        self.assertEqual(recorder.counts()["unsupported"], 1)
        with self.assertRaises(ValueError):
            recorder.record("runtime", "bad", "maybe")

    def test_values_match_handles_booleans_and_numeric_tolerance(self):
        self.assertTrue(values_match(1.0004, 1.0))
        self.assertTrue(values_match(1, True))
        self.assertFalse(values_match(0, True))
        self.assertTrue(values_match("Normal", "Normal"))

    def test_render_markdown_report_groups_records(self):
        recorder = ProbeRecorder()
        recorder.record("properties.video", "Pan", "supported", details={"read": 0, "write": True})
        report = recorder.to_report(
            {"timestamp_utc": "2026-05-09T12:00:00+00:00", "product": "Resolve", "version_string": "20.3"},
            {"json": "/tmp/report.json"},
        )

        markdown = render_markdown_report(report)

        self.assertIn("# Timeline Edit Kernel Capability Probe", markdown)
        self.assertIn("### properties.video", markdown)
        self.assertIn("`Pan`", markdown)


if __name__ == "__main__":
    unittest.main()
