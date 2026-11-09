"""The dashboard's "open Claude Code in a terminal" launcher must not splice
its command (repo path + claude binary) into AppleScript source, for either
iTerm or Terminal.
"""
import subprocess
import unittest
from unittest import mock

import src.analysis_dashboard as dash

HOSTILE_ROOT = '/tmp/repo "\\" & (do shell script "touch pwned") & "'


class TerminalLaunchArgvTest(unittest.TestCase):
    def _launch(self, iterm_running):
        check = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="true\n" if iterm_running else "false\n", stderr="")
        done = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with mock.patch.object(dash.sys, "platform", "darwin"), \
                mock.patch.object(dash, "_repo_root", return_value=HOSTILE_ROOT), \
                mock.patch("shutil.which", return_value=None), \
                mock.patch("subprocess.run", side_effect=[check, done]) as run:
            result = dash._launch_claude_code_terminal()
        self.assertEqual(run.call_count, 2)
        return result, list(run.call_args_list[1].args[0])

    def _assert_not_in_source(self, argv, app):
        self.assertEqual(argv[0], "osascript")
        scripts = [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "-e"]
        joined = "\n".join(scripts)
        self.assertIn(f'tell application "{app}"', joined)
        self.assertIn("item 1 of argv", joined)
        for script in scripts:
            self.assertNotIn("do shell script", script)
            self.assertNotIn("/tmp/repo", script)
        self.assertEqual(argv[-2], "--")
        self.assertIn("/tmp/repo", argv[-1])
        self.assertTrue(argv[-1].endswith(" && claude"))

    def test_iterm_command_is_passed_as_argv(self):
        result, argv = self._launch(iterm_running=True)
        self.assertEqual(result["terminal"], "iterm")
        self._assert_not_in_source(argv, "iTerm")

    def test_terminal_command_is_passed_as_argv(self):
        result, argv = self._launch(iterm_running=False)
        self.assertEqual(result["terminal"], "terminal")
        self._assert_not_in_source(argv, "Terminal")


if __name__ == "__main__":
    unittest.main()
