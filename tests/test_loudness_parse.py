"""The shared EBU R128 parser: what counts as the measurement, and what does not.

The failure this guards against is silent. `ebur128` prints a progress line per frame
carrying its own `I:`, `LRA:` and peak fields; read one of those instead of the summary
and the numbers still parse, the call still succeeds, and a single frame is delivered as
a programme measurement. Nothing raises. So the tests here are mostly about what the
parser refuses to look at.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.utils import loudness_parse  # noqa: E402

HAVE_FFMPEG = shutil.which("ffmpeg") is not None

PROGRESS = (
    "[Parsed_ebur128_0 @ 0x1] t: 11.9  TARGET:-23 LUFS  M: -27.8 S: -27.8  "
    "I: -27.8 LUFS  LRA: 0.0 LU  TPK: -27.1 -27.1 dBFS"
)
SUMMARY = """[Parsed_ebur128_0 @ 0x1] Summary:

  Integrated loudness:
    I:         -19.4 LUFS
    Threshold: -29.4 LUFS

  Loudness range:
    LRA:         3.7 LU
    LRA low:   -22.1 LUFS
    LRA high:  -18.4 LUFS

  True peak:
    Peak:      -2.5 dBFS
"""
TRAILER = "[out#0/null @ 0x2] video:0KiB audio:2250KiB muxing overhead: unknown"


class TestSummaryBlock(unittest.TestCase):
    def test_block_starts_at_the_summary(self):
        block = loudness_parse.summary_block(PROGRESS + "\n" + SUMMARY)
        self.assertTrue(block.startswith("[Parsed_ebur128_0 @ 0x1] Summary:"))

    def test_block_ends_at_the_next_ffmpeg_log_line(self):
        """The body is indented plain text; every log line carries a bracketed prefix."""
        block = loudness_parse.summary_block(SUMMARY + TRAILER + "\n")
        self.assertIn("Peak:      -2.5 dBFS", block)
        self.assertNotIn("muxing overhead", block)

    def test_no_summary_is_an_empty_block(self):
        self.assertEqual(loudness_parse.summary_block(PROGRESS), "")

    def test_the_last_summary_wins(self):
        """Two ebur128 instances print two summaries; the later one is the live result."""
        first = SUMMARY.replace("-19.4", "-30.0")
        block = loudness_parse.summary_block(first + "\n" + SUMMARY)
        self.assertIn("-19.4", block)
        self.assertNotIn("-30.0", block)


class TestParseLoudness(unittest.TestCase):
    def test_reads_the_summary(self):
        parsed = loudness_parse.parse_loudness(PROGRESS + "\n" + SUMMARY)
        self.assertEqual(parsed["integrated_lufs"], -19.4)
        self.assertEqual(parsed["loudness_range_lu"], 3.7)
        self.assertEqual(parsed["true_peak_dbtp"], -2.5)

    def test_a_progress_line_after_the_summary_does_not_win(self):
        parsed = loudness_parse.parse_loudness(SUMMARY + PROGRESS + "\n")
        self.assertEqual(parsed["integrated_lufs"], -19.4)
        self.assertEqual(parsed["loudness_range_lu"], 3.7)

    def test_any_log_line_after_the_summary_is_excluded(self):
        """Not only progress lines: nothing outside the block is a measurement."""
        stray = SUMMARY + "[some_other_filter @ 0x3] I: -50.0 LUFS  LRA: 22.0 LU\n"
        self.assertEqual(loudness_parse.parse_loudness(stray)["integrated_lufs"], -19.4)

    def test_a_progress_line_is_never_read_however_it_is_formatted(self):
        """The two steps guard independent assumptions, so both have to stay.

        Bounding the block assumes ffmpeg log lines carry a `[component @ addr]` prefix.
        Dropping `TARGET:` assumes progress lines carry that field. If either assumption
        stops holding, the other still keeps a per-frame reading out of the result. The
        line below is deliberately unprefixed — not a format ffmpeg emits today, which is
        the point: it isolates the second guard by breaking the first one's premise.
        """
        unprefixed = SUMMARY + (
            "t: 12.0  TARGET:-23 LUFS  M: -40.0 S: -40.0  I: -40.0 LUFS  LRA: 9.9 LU\n"
        )
        parsed = loudness_parse.parse_loudness(unprefixed)
        self.assertEqual(parsed["integrated_lufs"], -19.4)
        self.assertEqual(parsed["loudness_range_lu"], 3.7)

    def test_no_summary_yields_none_not_a_frame_reading(self):
        """"No measurement" and "one frame's measurement" are different answers."""
        parsed = loudness_parse.parse_loudness(PROGRESS)
        self.assertIsNone(parsed["integrated_lufs"])
        self.assertIsNone(parsed["loudness_range_lu"])
        self.assertIsNone(parsed["true_peak_dbtp"])

    def test_unrelated_output_yields_none(self):
        parsed = loudness_parse.parse_loudness("ffmpeg: no audio streams found\n")
        self.assertIsNone(parsed["integrated_lufs"])

    def test_empty_input(self):
        self.assertIsNone(loudness_parse.parse_loudness("")["integrated_lufs"])

    def test_custom_float_conversion_is_used(self):
        calls = []

        def convert(value):
            calls.append(value)
            return 42.0

        parsed = loudness_parse.parse_loudness(SUMMARY, to_float=convert)
        self.assertEqual(parsed["integrated_lufs"], 42.0)
        self.assertIn("-19.4", calls)

    def test_lra_low_and_high_do_not_displace_the_range(self):
        """`LRA low:`/`LRA high:` are LUFS lines inside the block, not the range."""
        self.assertEqual(loudness_parse.parse_loudness(SUMMARY)["loudness_range_lu"], 3.7)


class TestCallersAgree(unittest.TestCase):
    """Both callers must return the same numbers — they now share the implementation."""

    def test_media_analysis_and_mix_plan_agree(self):
        from src.utils import media_analysis, mix_plan

        for name, sample in (
            ("summary", PROGRESS + "\n" + SUMMARY),
            ("trailing_progress", SUMMARY + PROGRESS + "\n"),
            ("trailing_log", SUMMARY + TRAILER + "\n"),
            ("no_summary", PROGRESS),
        ):
            with self.subTest(sample=name):
                self.assertEqual(
                    dict(media_analysis._parse_loudness(sample)),
                    dict(mix_plan.parse_loudness(sample)),
                )


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg required")
class TestAgainstRealFfmpeg(unittest.TestCase):
    """The block-bounding rule has to match what ffmpeg actually prints, not a fixture."""

    def test_bounds_a_real_ebur128_run(self):
        import os
        import tempfile

        directory = tempfile.mkdtemp(prefix="loudness_parse_")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        tone = os.path.join(directory, "tone.wav")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
             "sine=frequency=440:duration=3:sample_rate=48000", "-ac", "2", tone],
            check=True, capture_output=True)
        stderr = subprocess.run(
            ["ffmpeg", "-v", "info", "-nostats", "-i", tone,
             "-filter_complex", "ebur128=peak=true", "-f", "null", "-"],
            capture_output=True).stderr.decode("utf-8", "replace")

        block = loudness_parse.summary_block(stderr)
        self.assertTrue(block, "no summary block found in real ffmpeg output")
        # The block ends before ffmpeg's own trailer, and contains no progress line.
        self.assertNotIn("muxing overhead", block)
        self.assertNotIn("TARGET:", block)
        parsed = loudness_parse.parse_loudness(stderr)
        self.assertIsNotNone(parsed["integrated_lufs"])
        self.assertIsNotNone(parsed["true_peak_dbtp"])


if __name__ == "__main__":
    unittest.main()
