"""A caller path in a positional argv slot must not be read as an option (#350).

ffprobe given ``-report`` as its operand writes a log into its working
directory before it notices there is no input. Every site below puts a path
that can come from a tool call into a bare positional slot, so each one refuses
a leading ``-`` before it spawns. The Node server's twin is ``assertNotOption``
in ``resolve-advanced/server/spawn-guard.mjs``; the error code is shared.

Each test makes the spawn fail loudly if it is reached, so a site that stops
checking fails here rather than spawning the program.
"""
import os
import pathlib
import sys
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.utils import proc  # noqa: E402

OPTION = "-report"


def _no_spawn(*_args, **_kwargs):
    raise AssertionError("spawned a program with an option-like positional path")


class OptionLikePathErrorTests(unittest.TestCase):
    def test_a_leading_dash_is_refused_with_the_label(self):
        message = proc.option_like_path_error(OPTION, "proxy_path")
        self.assertIn("proxy_path '-report'", message)
        self.assertIn("absolute path", message)

    def test_paths_a_program_reads_as_a_file_pass(self):
        for value in ("clip.mov", "./-report", os.path.abspath("-report"), "a-b.mov", "", None):
            self.assertIsNone(proc.option_like_path_error(value), value)

    def test_the_code_matches_the_advanced_server(self):
        guard = (REPO_ROOT / "resolve-advanced" / "server" / "spawn-guard.mjs").read_text(encoding="utf-8")
        self.assertIn(f"'{proc.OPTION_LIKE_PATH_REFUSED}'", guard)


class ServerProbeSiteTests(unittest.TestCase):
    def setUp(self):
        from src import server

        self.server = server
        patches = [
            mock.patch.object(server.shutil, "which", return_value="/usr/bin/ffprobe"),
            mock.patch.object(server.subprocess, "run", side_effect=_no_spawn),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_probe_media_file_refuses(self):
        result = self.server._probe_media_file(OPTION)
        self.assertFalse(result["success"])
        self.assertEqual(result["code"], proc.OPTION_LIKE_PATH_REFUSED)

    def test_ffprobe_media_summary_refuses(self):
        result = self.server._ffprobe_media_summary(OPTION)
        self.assertEqual(result["code"], proc.OPTION_LIKE_PATH_REFUSED)

    def test_extract_frames_refuses_an_option_like_output_dir(self):
        clip = mock.Mock()
        clip.GetClipProperty.return_value = __file__
        with mock.patch.object(self.server, "safe_run", side_effect=_no_spawn), \
                mock.patch.object(self.server.os, "makedirs", side_effect=_no_spawn):
            result = self.server._extract_clip_frames(clip, {"timestamps": [1.0], "output_dir": "-x"})
        self.assertEqual(result["error"]["code"], proc.OPTION_LIKE_PATH_REFUSED)
        self.assertEqual(result["error"]["category"], "invalid_input")
        self.assertFalse(result["error"]["retryable"])


class MediaAnalysisSiteTests(unittest.TestCase):
    def setUp(self):
        from src.utils import media_analysis

        self.media_analysis = media_analysis
        patch = mock.patch.object(media_analysis, "_run_command", side_effect=_no_spawn)
        patch.start()
        self.addCleanup(patch.stop)

    def test_ffprobe_refuses(self):
        result = self.media_analysis._ffprobe(OPTION)
        self.assertFalse(result["success"])
        self.assertEqual(result["code"], proc.OPTION_LIKE_PATH_REFUSED)

    def test_whisper_cli_refuses(self):
        with mock.patch.object(self.media_analysis.shutil, "which", return_value="/usr/bin/whisper"), \
                mock.patch.object(self.media_analysis.os, "makedirs", side_effect=_no_spawn):
            result = self.media_analysis._transcribe_with_whisper_cli(
                OPTION, {"analysis_json": "/tmp/x/analysis.json"}, {})
        self.assertFalse(result["success"])
        self.assertEqual(result["code"], proc.OPTION_LIKE_PATH_REFUSED)


class MixPlanSiteTests(unittest.TestCase):
    def setUp(self):
        from src.utils import mix_plan

        self.mix_plan = mix_plan
        patches = [
            mock.patch.object(mix_plan.shutil, "which", return_value="/usr/bin/ffprobe"),
            mock.patch.object(mix_plan, "_run", side_effect=_no_spawn),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_probe_duration_refuses(self):
        with self.assertRaisesRegex(self.mix_plan.MixPlanError, "starts with '-'"):
            self.mix_plan.probe_duration(OPTION)

    def test_write_wav_refuses_an_option_like_output_path(self):
        with mock.patch.object(self.mix_plan.os, "makedirs", side_effect=_no_spawn), \
                self.assertRaisesRegex(self.mix_plan.MixPlanError, "output_path '-report'"):
            self.mix_plan._write_wav(OPTION, [0.0])


class ImageQcSiteTests(unittest.TestCase):
    def test_color_transfer_probe_does_not_spawn(self):
        from src.utils import image_qc

        with mock.patch.object(image_qc.shutil, "which", return_value="/usr/bin/ffprobe"), \
                mock.patch.object(image_qc.subprocess, "run", side_effect=_no_spawn):
            self.assertIsNone(image_qc._probe_color_transfer(OPTION))


class SoundDensityDurationTests(unittest.TestCase):
    """`duration_seconds` used to land `-t` between `-i` and the path."""

    def test_the_duration_limit_goes_before_the_input(self):
        from src.utils import sound_density

        seen = []

        def capture(cmd, **_kwargs):
            seen.append(list(cmd))
            return mock.Mock(returncode=1, stdout=b"", stderr=b"stop")

        with mock.patch("shutil.which", return_value="/usr/bin/ffmpeg"), \
                mock.patch("subprocess.run", side_effect=capture):
            sound_density.measure_track_levels({"A1": OPTION}, duration_seconds=12)
        cmd = seen[0]
        self.assertEqual(cmd[cmd.index("-i") + 1], OPTION)
        self.assertLess(cmd.index("-t"), cmd.index("-i"))
        self.assertEqual(cmd[cmd.index("-t") + 1], "12")


if __name__ == "__main__":
    unittest.main()
