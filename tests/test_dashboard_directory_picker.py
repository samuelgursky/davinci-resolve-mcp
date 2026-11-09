"""The dashboard's native folder picker must never splice the caller's
start directory into AppleScript source.

``_native_directory_picker`` is reached from the HTTP handler with the
request's ``initial`` value, which is only checked with ``os.path.isdir``.
A real directory whose name contains ``"`` would close an interpolated
string literal and inject AppleScript, so the path has to travel as a
run-handler argument instead.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import src.analysis_dashboard as dash

HOSTILE_NAME = 'pick "me\\" & (do shell script "touch pwned") & "'


class NativeDirectoryPickerArgvTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="picker-")
        self.hostile = os.path.join(self.tmp, HOSTILE_NAME)
        os.mkdir(self.hostile)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_picker(self, initial):
        done = subprocess.CompletedProcess(args=[], returncode=0, stdout="/chosen/\n", stderr="")
        with mock.patch.object(dash.sys, "platform", "darwin"), \
                mock.patch("subprocess.run", return_value=done) as run:
            result = dash._native_directory_picker(initial=initial)
        self.assertEqual(run.call_count, 1)
        return result, list(run.call_args.args[0])

    @staticmethod
    def _script_args(argv):
        return [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == "-e"]

    def test_hostile_directory_name_never_reaches_script_source(self):
        self.assertTrue(os.path.isdir(self.hostile))
        result, argv = self._run_picker(self.hostile)
        self.assertEqual(result, {"success": True, "path": "/chosen"})
        self.assertEqual(argv[0], "osascript")
        scripts = self._script_args(argv)
        self.assertTrue(scripts, argv)
        for script in scripts:
            self.assertNotIn(HOSTILE_NAME, script)
            self.assertNotIn("do shell script", script)
            self.assertNotIn(self.tmp, script)
        # The path is handed over verbatim as the run handler's argument.
        self.assertEqual(argv[-2:], ["--", os.path.abspath(self.hostile)])
        self.assertIn("item 1 of argv", "\n".join(scripts))

    def test_relative_start_dir_is_made_absolute(self):
        cwd = os.getcwd()
        os.chdir(self.tmp)
        try:
            os.mkdir("-dashdir")
            _, argv = self._run_picker("-dashdir")
        finally:
            os.chdir(cwd)
        self.assertTrue(os.path.isabs(argv[-1]))
        self.assertFalse(argv[-1].startswith("-"))

    def test_missing_start_dir_falls_back_to_home(self):
        _, argv = self._run_picker(os.path.join(self.tmp, "does-not-exist"))
        self.assertEqual(argv[-1], os.path.abspath(os.path.expanduser("~")))


if __name__ == "__main__":
    unittest.main()
