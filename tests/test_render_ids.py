"""Pure resolver tests for src/utils/render_ids.py.

These live apart from the render-probe tests because the resolvers are shared by
the compound and granular servers — the format fix originally landed in only one
of them, which is the drift this module exists to prevent.
"""

import unittest

from src.utils.render_ids import (
    render_codec_id_from_codecs,
    render_format_id_from_formats,
)

FORMATS = {"mp4": "mp4", "QuickTime": "mov", "MXF OP-Atom": "mxf_op_atom"}
MOV_CODECS = {
    "Apple ProRes 422 HQ": "ProRes422HQ",
    "Apple ProRes 4444": "ProRes4444",
    "DNxHR HQ": "DNxHR_HQ",
}
MP4_CODECS = {"H.264": "H.264", "H.265": "H.265"}


class RenderFormatIdTest(unittest.TestCase):
    def test_display_name_resolves_to_id(self):
        self.assertEqual(render_format_id_from_formats(FORMATS, "QuickTime"), "mov")
        self.assertEqual(render_format_id_from_formats(FORMATS, "MXF OP-Atom"), "mxf_op_atom")

    def test_id_passes_through(self):
        self.assertEqual(render_format_id_from_formats(FORMATS, "mov"), "mov")

    def test_match_is_case_insensitive_on_either_side(self):
        self.assertEqual(render_format_id_from_formats(FORMATS, "quicktime"), "mov")
        self.assertEqual(render_format_id_from_formats(FORMATS, "MOV"), "mov")

    def test_unknown_and_malformed_pass_through(self):
        self.assertEqual(render_format_id_from_formats(FORMATS, "Betamax"), "Betamax")
        self.assertEqual(render_format_id_from_formats(None, "mov"), "mov")
        self.assertEqual(render_format_id_from_formats(FORMATS, ""), "")
        self.assertIsNone(render_format_id_from_formats(FORMATS, None))


class RenderCodecIdTest(unittest.TestCase):
    def test_display_name_resolves_to_id(self):
        self.assertEqual(render_codec_id_from_codecs(MOV_CODECS, "Apple ProRes 422 HQ"), "ProRes422HQ")
        self.assertEqual(render_codec_id_from_codecs(MOV_CODECS, "DNxHR HQ"), "DNxHR_HQ")

    def test_id_passes_through(self):
        self.assertEqual(render_codec_id_from_codecs(MOV_CODECS, "ProRes4444"), "ProRes4444")

    def test_label_equals_id_case_is_stable(self):
        """mp4 codecs have label == id — the coincidence that hid this bug."""
        self.assertEqual(render_codec_id_from_codecs(MP4_CODECS, "H.264"), "H.264")

    def test_match_is_case_insensitive_on_either_side(self):
        self.assertEqual(render_codec_id_from_codecs(MOV_CODECS, "apple prores 4444"), "ProRes4444")
        self.assertEqual(render_codec_id_from_codecs(MOV_CODECS, "prores422hq"), "ProRes422HQ")

    def test_unknown_and_malformed_pass_through(self):
        self.assertEqual(render_codec_id_from_codecs(MOV_CODECS, "Cinepak"), "Cinepak")
        self.assertEqual(render_codec_id_from_codecs({}, "ProRes422HQ"), "ProRes422HQ")
        self.assertEqual(render_codec_id_from_codecs(None, "ProRes422HQ"), "ProRes422HQ")
        self.assertIsNone(render_codec_id_from_codecs(MOV_CODECS, None))


if __name__ == "__main__":
    unittest.main()
