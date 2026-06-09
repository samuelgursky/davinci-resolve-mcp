"""Tests for the headless batch-runner CLI (src/batch_cli.py).

These cover argparse plumbing and exit-code mapping. Engine-level behavior
(slice execution, index building, cancel/resume) is already covered by
tests/test_media_analysis.py — we trust it here.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from src import batch_cli
from src.utils import media_analysis_jobs


class BatchCliParserTests(unittest.TestCase):
    def test_help_lists_all_subcommands(self):
        parser = batch_cli._build_parser()
        # SystemExit on --help is expected; capture and inspect text.
        with self.assertRaises(SystemExit):
            with redirect_stdout(io.StringIO()) as buf:
                parser.parse_args(["--help"])
        text = buf.getvalue()
        for sub in ("plan", "run", "status", "list", "resume", "cancel"):
            self.assertIn(sub, text)

    def test_run_requires_paths(self):
        parser = batch_cli._build_parser()
        with self.assertRaises(SystemExit):
            with redirect_stdout(io.StringIO()), patch("sys.stderr", io.StringIO()):
                parser.parse_args(["run"])

    def test_run_rejects_invalid_depth(self):
        parser = batch_cli._build_parser()
        with self.assertRaises(SystemExit):
            with redirect_stdout(io.StringIO()), patch("sys.stderr", io.StringIO()):
                parser.parse_args(["run", "/tmp/x", "--depth", "bogus"])

    def test_json_flag_works_in_either_position(self):
        parser = batch_cli._build_parser()
        before = parser.parse_args(["--json", "run", "/tmp/x"])
        after = parser.parse_args(["run", "/tmp/x", "--json"])
        self.assertTrue(before.json)
        self.assertTrue(after.json)

    def test_run_defaults(self):
        parser = batch_cli._build_parser()
        args = parser.parse_args(["run", "/tmp/x"])
        self.assertEqual(args.cmd, "run")
        self.assertTrue(args.recursive)
        self.assertEqual(args.max_clips, 1)
        self.assertIsNone(args.max_seconds)
        self.assertFalse(args.no_follow)
        self.assertIsNone(args.depth)
        # --json uses SUPPRESS so absence means default-false (applied in main()).
        self.assertFalse(hasattr(args, "json"))


class BatchCliExitCodeTests(unittest.TestCase):
    def test_plan_with_no_media_returns_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty_dir = os.path.join(tmp, "empty")
            os.makedirs(empty_dir)
            with redirect_stdout(io.StringIO()):
                rc = batch_cli.main(["plan", empty_dir])
        self.assertEqual(rc, batch_cli.EXIT_FATAL)

    def test_run_with_no_media_returns_fatal_and_emits_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty_dir = os.path.join(tmp, "empty")
            os.makedirs(empty_dir)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = batch_cli.main(["--json", "run", empty_dir])
        self.assertEqual(rc, batch_cli.EXIT_FATAL)
        line = buf.getvalue().strip().splitlines()[0]
        payload = json.loads(line)
        self.assertFalse(payload.get("success"))

    def test_status_for_missing_job_returns_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stdout(io.StringIO()):
                rc = batch_cli.main(
                    ["status", "job-does-not-exist", "--project-root", tmp]
                )
        self.assertEqual(rc, batch_cli.EXIT_FATAL)

    def test_list_empty_returns_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stdout(io.StringIO()):
                rc = batch_cli.main(["list", "--project-root", tmp])
        self.assertEqual(rc, batch_cli.EXIT_OK)

    def test_exit_for_status_mapping(self):
        self.assertEqual(batch_cli._exit_for_status("completed"), batch_cli.EXIT_OK)
        self.assertEqual(
            batch_cli._exit_for_status("completed_with_errors"),
            batch_cli.EXIT_PARTIAL,
        )
        self.assertEqual(batch_cli._exit_for_status("canceled"), batch_cli.EXIT_CANCELED)
        self.assertEqual(batch_cli._exit_for_status("queued"), batch_cli.EXIT_FATAL)
        self.assertEqual(batch_cli._exit_for_status(None), batch_cli.EXIT_FATAL)


class BatchCliJsonOutputShapeTests(unittest.TestCase):
    def test_list_json_emits_single_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = batch_cli.main(["--json", "list", "--project-root", tmp])
        self.assertEqual(rc, batch_cli.EXIT_OK)
        lines = [line for line in buf.getvalue().splitlines() if line.strip()]
        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertTrue(payload.get("success"))
        self.assertEqual(payload.get("jobs"), [])


class BatchCliRunIntegrationTests(unittest.TestCase):
    """End-to-end smoke test through the real engine with synthetic media."""

    @staticmethod
    def _write_synthetic_media(source: str) -> None:
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=160x90:rate=24:duration=2",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=1000:duration=2",
                "-c:v",
                "mpeg4",
                "-c:a",
                "aac",
                "-shortest",
                source,
            ],
            check=True,
        )

    def test_run_drives_synthetic_job_to_completion(self):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("ffmpeg/ffprobe not installed")
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = os.path.join(tmp, "source")
            analysis_dir = os.path.join(tmp, "analysis")
            os.makedirs(source_dir)
            source = os.path.join(source_dir, "cli_smoke.mp4")
            self._write_synthetic_media(source)
            caps = media_analysis_jobs.detect_capabilities()
            caps["transcription"] = {"available": True, "backends": ["local_mock"]}

            buf = io.StringIO()
            with patch("src.utils.media_analysis_jobs.detect_capabilities", return_value=caps), redirect_stdout(buf):
                rc = batch_cli.main(
                    [
                        "--json",
                        "run",
                        source,
                        "--analysis-root",
                        analysis_dir,
                        "--project-name",
                        "CLI smoke",
                        "--depth",
                        "quick",
                        "--max-clips",
                        "5",
                    ]
                )
            self.assertEqual(rc, batch_cli.EXIT_OK)
            lines = [line for line in buf.getvalue().splitlines() if line.strip()]
            events = [json.loads(line) for line in lines]
            self.assertEqual(events[0].get("event"), "job_created")
            self.assertEqual(events[-1].get("event"), "job_done")
            self.assertEqual(events[-1].get("status"), "completed")


class BatchCliSpecCommandTests(unittest.TestCase):
    """plan-spec / apply argparse plumbing + exit-code mapping. The spec action
    itself (project_spec) is covered by tests/test_project_spec.py; here we mock
    _run_spec_action so no Resolve connection is needed."""

    def test_help_lists_spec_subcommands(self):
        parser = batch_cli._build_parser()
        with self.assertRaises(SystemExit):
            with redirect_stdout(io.StringIO()) as buf:
                parser.parse_args(["--help"])
        text = buf.getvalue()
        self.assertIn("plan-spec", text)
        self.assertIn("apply", text)

    def test_apply_requires_spec(self):
        parser = batch_cli._build_parser()
        with self.assertRaises(SystemExit):
            with redirect_stdout(io.StringIO()), patch("sys.stderr", io.StringIO()):
                parser.parse_args(["apply"])

    def test_plan_spec_emits_plan_and_exits_ok(self):
        plan = {"project": "Show", "change_count": 1,
                "actions": [{"op": "create", "target": "project:Show", "detail": ""}],
                "diff": {}}
        with patch.object(batch_cli, "_run_spec_action", return_value=plan):
            with redirect_stdout(io.StringIO()):
                rc = batch_cli.main(["plan-spec", "/tmp/spec.json"])
        self.assertEqual(rc, batch_cli.EXIT_OK)

    def test_apply_success_exit_ok(self):
        result = {"success": True, "applied_count": 3, "applied": [], "failures": []}
        with patch.object(batch_cli, "_run_spec_action", return_value=result):
            with redirect_stdout(io.StringIO()):
                rc = batch_cli.main(["apply", "/tmp/spec.json"])
        self.assertEqual(rc, batch_cli.EXIT_OK)

    def test_apply_partial_exit_2(self):
        result = {"success": False, "applied_count": 1, "applied": [],
                  "failures": [{"target": "timeline:A"}]}
        with patch.object(batch_cli, "_run_spec_action", return_value=result):
            with redirect_stdout(io.StringIO()):
                rc = batch_cli.main(["apply", "/tmp/spec.json"])
        self.assertEqual(rc, batch_cli.EXIT_PARTIAL)

    def test_not_connected_exit_fatal(self):
        with patch.object(batch_cli, "_run_spec_action", return_value=None):
            with redirect_stdout(io.StringIO()):
                rc = batch_cli.main(["apply", "/tmp/spec.json"])
        self.assertEqual(rc, batch_cli.EXIT_FATAL)

    def test_spec_error_envelope_exit_fatal(self):
        result = {"error": {"message": "bad spec", "category": "invalid_input"}}
        with patch.object(batch_cli, "_run_spec_action", return_value=result):
            with redirect_stdout(io.StringIO()):
                rc = batch_cli.main(["plan-spec", "/tmp/spec.json"])
        self.assertEqual(rc, batch_cli.EXIT_FATAL)


if __name__ == "__main__":
    unittest.main()
