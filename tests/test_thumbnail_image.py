import base64
import unittest

from src.server import _thumbnail_data_to_png_bytes


class ThumbnailImageTests(unittest.TestCase):
    def test_rgb_thumbnail_converts_to_png(self):
        raw_rgb = bytes([
            255, 0, 0,
            0, 255, 0,
        ])
        png = _thumbnail_data_to_png_bytes({
            "width": 2,
            "height": 1,
            "noOfComponents": 3,
            "depth": 8,
            "data": base64.b64encode(raw_rgb).decode("ascii"),
        })

        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertIn(b"IHDR", png)
        self.assertIn(b"IDAT", png)
        self.assertIn(b"IEND", png)

    def test_rejects_short_thumbnail_data(self):
        with self.assertRaisesRegex(ValueError, "too short"):
            _thumbnail_data_to_png_bytes({
                "width": 2,
                "height": 1,
                "noOfComponents": 3,
                "depth": 8,
                "data": base64.b64encode(b"\x00\x00\x00").decode("ascii"),
            })

    def test_rgba_thumbnail_uses_rgba_color_type(self):
        raw_rgba = bytes([
            255, 0, 0, 255,
            0, 255, 0, 128,
        ])
        png = _thumbnail_data_to_png_bytes({
            "width": 2,
            "height": 1,
            "noOfComponents": 4,
            "depth": 8,
            "data": raw_rgba,
        })

        # Color type is the tenth byte of IHDR data: 2 = RGB, 6 = RGBA.
        ihdr_offset = png.index(b"IHDR") + 4
        self.assertEqual(png[ihdr_offset + 9], 6)


if __name__ == "__main__":
    unittest.main()
