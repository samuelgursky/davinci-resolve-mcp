"""Issue #158: a Windows setup that failed with nothing to read.

Three defects compounded into one unexplained exit on a machine with both
Python 3.12 and 3.13 installed:

  1. The npm launcher probed for the Windows `py` launcher with `py --version`,
     which is not a flag every build accepts (it exits 101 on the ones that do
     not). A false negative there discarded every `py -3.12/-3.11/-3.10`
     candidate and fell through to bare `python` — the 3.13 that the candidate
     ordering exists specifically to avoid.
  2. Loading Resolve's scripting library under a Python whose C ABI it was not
     built against terminates the process with an access violation. There is no
     traceback to print: the OS kills the interpreter. Reported as a bare exit
     code, it reads as a silent crash.
  3. doctor.py's own Windows blind spots (covered in test_doctor_paths.py).

These tests pin 1 and 2. What is NOT covered, and is not coverable from macOS:
whether `py --version` fails on any particular Windows build. That claim comes
from the reporter. The fix does not depend on it being true — it removes the
probe rather than correcting it, so the code no longer has an opinion either
way.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
LAUNCHER = REPO / "bin" / "davinci-resolve-mcp.mjs"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

_spec = importlib.util.spec_from_file_location("resolve_install_crash", REPO / "install.py")
install = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(install)


class LauncherPyDetectionTests(unittest.TestCase):
    """The `py` candidates must not sit behind a probe that can lie."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = LAUNCHER.read_text(encoding="utf-8")

    def test_the_version_flag_probe_is_gone(self) -> None:
        self.assertNotIn("commandExists", self.source)

    def test_py_candidates_are_not_conditioned_on_a_probe(self) -> None:
        """The win32 branch may test the platform and nothing else. Any call in
        that condition is a probe that can discard the candidates below it."""
        match = re.search(
            r"if \(process\.platform === \"win32\"(?P<extra>[^)]*)\) \{\s*candidates\.push\(\s*\{ command: \"py\"",
            self.source,
        )
        self.assertIsNotNone(match, "the win32 `py` candidate block moved or changed shape")
        self.assertEqual(match.group("extra").strip(), "")

    def test_the_version_pinned_candidates_still_precede_bare_python(self) -> None:
        """Ordering is the actual protection against landing on 3.13; the probe
        bug mattered because it skipped past this."""
        pinned = self.source.index('{ command: "py", args: ["-3.12"] }')
        bare = self.source.index('{ command: "python", args: [] }')
        self.assertLess(pinned, bare)

    def test_the_launcher_explains_an_access_violation_exit(self) -> None:
        self.assertIn("3221225477", self.source)
        self.assertIn("-1073741819", self.source)
        self.assertIn("accessViolationNote", self.source)


class AccessViolationMessageTests(unittest.TestCase):
    """A crash the OS caused still has to arrive as an explanation."""

    def test_both_spellings_of_the_exit_code_are_recognized(self) -> None:
        # The unsigned value and the signed reading of the same 32 bits; which
        # one a caller sees depends on the reporting layer, not on the crash.
        self.assertIn(3221225477, install.WINDOWS_ACCESS_VIOLATION_CODES)
        self.assertIn(-1073741819, install.WINDOWS_ACCESS_VIOLATION_CODES)

    def test_the_message_names_the_code_and_the_remedy(self) -> None:
        message = install.access_violation_message(3221225477, (3, 13, 3))
        self.assertIn("0xC0000005", message)
        self.assertIn("3.10-3.12", message)

    def test_a_version_given_as_a_string_is_read_the_same_way(self) -> None:
        """`is_abi_risk_python_version` unpacks a tuple; handed "3.13.3" it
        quietly answers False. The at-risk interpreter would then be told its
        version was fine."""
        self.assertIn("3.10-3.12", install.access_violation_message(3221225477, "3.13.3"))
        self.assertNotIn("3.10-3.12", install.access_violation_message(3221225477, "3.12.4"))

    def test_an_unreadable_version_falls_back_to_the_abi_theory(self) -> None:
        self.assertIn("3.10-3.12", install.access_violation_message(3221225477, "not-a-version"))

    def test_an_unknown_interpreter_version_still_gets_the_abi_theory(self) -> None:
        """The version probe can itself fail. Withholding the likeliest cause
        because of that would leave the user with the bare code again."""
        message = install.access_violation_message(3221225477, None)
        self.assertIn("3.10-3.12", message)

    def test_a_supported_interpreter_is_not_blamed_on_its_version(self) -> None:
        """On 3.12 the ABI theory does not fit, so the message must point at the
        library path instead of sending the user to reinstall Python."""
        message = install.access_violation_message(3221225477, (3, 12, 4))
        self.assertNotIn("3.10-3.12", message)
        self.assertIn("RESOLVE_SCRIPT_LIB", message)


class VerifyConnectionCrashTests(unittest.TestCase):
    """The installer's probe reported `Process exited with code 3221225477`."""

    def _verify(self, returncode: int, version: tuple = (3, 13, 3)):
        completed = SimpleNamespace(stdout="", stderr="", returncode=returncode)
        with mock.patch.object(install.subprocess, "run", return_value=completed), \
                mock.patch.object(install, "_version_for_python", return_value=version):
            return install.verify_resolve_connection(
                "/nope/python", "/nope/Developer/Scripting", "/nope/fusionscript.dll"
            )

    def test_a_crash_exit_is_translated(self) -> None:
        ok, message = self._verify(3221225477)
        self.assertFalse(ok)
        self.assertIn("0xC0000005", message)
        self.assertNotIn("Process exited with code", message)

    def test_the_signed_spelling_is_translated_too(self) -> None:
        ok, message = self._verify(-1073741819)
        self.assertFalse(ok)
        self.assertIn("0xC0000005", message)

    def test_an_ordinary_failure_is_left_alone(self) -> None:
        """Only the crash codes get the crash story."""
        ok, message = self._verify(1)
        self.assertFalse(ok)
        self.assertIn("Process exited with code 1", message)

    def test_a_failing_version_probe_does_not_mask_the_crash(self) -> None:
        completed = SimpleNamespace(stdout="", stderr="", returncode=3221225477)
        with mock.patch.object(install.subprocess, "run", return_value=completed), \
                mock.patch.object(
                    install, "_version_for_python", side_effect=RuntimeError("no python")
                ):
            ok, message = install.verify_resolve_connection(
                "/nope/python", "/nope/Developer/Scripting", "/nope/fusionscript.dll"
            )
        self.assertFalse(ok)
        self.assertIn("0xC0000005", message)


if __name__ == "__main__":
    unittest.main()
