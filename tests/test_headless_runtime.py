"""Headless detection, headless launching, and the GUI/headless differential.

The measurements behind these tests are in `docs/reference/headless-cli.md`:
238 paired observations on Studio 19.1.3.7 with zero headless-only failures, and
no way to tell the two modes apart from the scripting API. That last part is why
detection has to read the process argv, and why these tests care so much about
what happens when the argv cannot be read.
"""

from __future__ import annotations

import unittest
from unittest import mock

from src.utils import headless_differential as hd
from src.utils import resolve_runtime as rr


def _ps(stdout: str):
    return mock.Mock(returncode=0, stdout=stdout)


def _ps_table(comm: str, args: str):
    """A fake `ps` that answers the executable column and the argv column
    separately, keyed by pid — the shape the real scan reads."""
    def run(argv, **_kwargs):
        columns = argv[-1] if argv and argv[0] == "ps" else ""
        return mock.Mock(returncode=0, stdout=args if "args" in columns else comm)
    return run


class ProcessTableTests(unittest.TestCase):
    """The scan counts an instance on its executable path OR its argv.

    On 2026-09-08 `resolve_control runtime_mode` answered `running: false,
    instances: 0` while Studio 19.1.3.7 was up at the stock path and answering
    scripting calls in the same minute. That exact condition did not reproduce
    afterwards (the same instance, restarted, matched), so the fix removes the
    scan's single point of failure instead of guessing at the trigger: an
    argv-only scan is blind whenever the kernel withholds the argument vector
    (`ps` prints `(Resolve)`) and whenever a launch argument follows the path.
    The executable column is readable whenever the process is.
    """
    EXE = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/MacOS/Resolve"
    XPC = ("/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/XPCServices/"
           "IOXPC.xpc/Contents/MacOS/IOXPC")

    def test_the_stock_macos_table_is_one_gui_instance(self) -> None:
        """The real table from the day of the report: pid 39560 at the stock path,
        its IOXPC helper beside it, argv identical to the executable."""
        comm = f"    1 /sbin/launchd\n39560 {self.EXE}\n39561 {self.XPC}\n"
        args = f"    1 /sbin/launchd\n39560 {self.EXE}\n39561 {self.XPC}\n"
        with mock.patch.object(rr.subprocess, "run", side_effect=_ps_table(comm, args)):
            mode = rr.runtime_mode()
        self.assertTrue(mode["running"])
        self.assertEqual(mode["instances"], 1, "the XPC helper is not an instance")
        self.assertIs(mode["headless"], False)
        self.assertEqual(mode["command_lines"], [self.EXE])

    def test_an_unreadable_argv_still_counts_by_executable_path(self) -> None:
        """`ps` prints `(Resolve)` when it cannot read the argument vector. The
        instance is real; only its mode is unknown — None, not False."""
        comm = f"39560 {self.EXE}\n39561 {self.XPC}\n"
        args = "39560 (Resolve)\n39561 (IOXPC)\n"
        with mock.patch.object(rr.subprocess, "run", side_effect=_ps_table(comm, args)):
            mode = rr.runtime_mode()
        self.assertTrue(mode["running"])
        self.assertEqual(mode["instances"], 1)
        self.assertIsNone(mode["headless"], "mode cannot be read from an unreadable argv")
        self.assertEqual(mode["command_lines"], [self.EXE])

    def test_a_launch_argument_after_the_path_does_not_hide_the_instance(self) -> None:
        """A project file handed to the binary on the command line is not a
        flag, so the flag-stripping suffix test used to leave it attached."""
        args = f"39560 {self.EXE} /Users/sam/Projects/Show.drp\n"
        comm = f"39560 {self.EXE}\n"
        with mock.patch.object(rr.subprocess, "run", side_effect=_ps_table(comm, args)):
            mode = rr.runtime_mode()
        self.assertTrue(mode["running"])
        self.assertEqual(mode["instances"], 1)
        # And the same line with only argv readable — the executable extraction
        # itself must handle it, not just the comm fallback.
        self.assertTrue(rr._is_resolve_command(f"{self.EXE} /Users/sam/Projects/Show.drp"))
        self.assertTrue(rr._is_resolve_command(f"{self.EXE} /Users/sam/Projects/Show.drp -nogui"))
        self.assertEqual(rr._executable_from_line(f"{self.EXE} /Users/sam/Projects/Show.drp"),
                         self.EXE)

    def test_a_flag_after_a_launch_argument_still_reads_as_headless(self) -> None:
        args = f"39560 {self.EXE} /Users/sam/Projects/Show.drp -nogui\n"
        comm = f"39560 {self.EXE}\n"
        with mock.patch.object(rr.subprocess, "run", side_effect=_ps_table(comm, args)):
            self.assertTrue(rr.runtime_mode()["headless"])

    def test_an_unquoted_shell_line_naming_the_binary_is_still_not_an_instance(self) -> None:
        """`/bin/sh -c /opt/resolve/bin/resolve -nogui` contains the pattern at a
        token boundary; the flag token before it is what marks it as a shell."""
        args = "4242 /bin/sh -c /opt/resolve/bin/resolve -nogui\n"
        comm = "4242 /bin/sh\n"
        with mock.patch.object(rr.subprocess, "run", side_effect=_ps_table(comm, args)):
            mode = rr.runtime_mode()
        self.assertFalse(mode["running"])
        self.assertEqual(mode["instances"], 0)

    def test_ps_is_asked_for_wide_output(self) -> None:
        """Without -ww BSD ps may cut a long command line to the terminal width,
        and a cut line no longer ends in the executable."""
        seen = []

        def run(argv, **_kwargs):
            seen.append(argv)
            return mock.Mock(returncode=0, stdout="")
        with mock.patch.object(rr.platform, "system", return_value="Darwin"), \
                mock.patch.object(rr.subprocess, "run", side_effect=run):
            rr.runtime_mode()
        self.assertTrue(seen, "ps was not run")
        for argv in seen:
            self.assertEqual(argv[0], "ps")
            self.assertIn("-Awwo", argv, argv)

    def test_one_column_failing_does_not_make_the_answer_unknown(self) -> None:
        """If the argv column cannot be read at all but the executable column
        can, the instance is still counted; only both failing is undeterminable."""
        def run(argv, **_kwargs):
            if "args" in argv[-1]:
                raise OSError("no argv for you")
            return mock.Mock(returncode=0, stdout=f"39560 {self.EXE}\n")
        with mock.patch.object(rr.subprocess, "run", side_effect=run):
            mode = rr.runtime_mode()
        self.assertTrue(mode["determinable"])
        self.assertTrue(mode["running"])
        self.assertIsNone(mode["headless"])


class RuntimeModeTests(unittest.TestCase):
    GUI = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/MacOS/Resolve"
    HEADLESS = GUI + " -nogui"

    def test_nogui_in_the_argv_is_the_signal(self) -> None:
        with mock.patch.object(rr.subprocess, "run", return_value=_ps(f"{self.HEADLESS}\nfinder\n")):
            mode = rr.runtime_mode()
        self.assertTrue(mode["running"])
        self.assertTrue(mode["headless"])
        self.assertEqual(mode["instances"], 1)

    def test_a_gui_instance_is_not_headless(self) -> None:
        with mock.patch.object(rr.subprocess, "run", return_value=_ps(f"{self.GUI}\nDock\n")):
            self.assertFalse(rr.is_headless())

    def test_nothing_running_leaves_headless_unknown_rather_than_false(self) -> None:
        """`False` would mean "it has a UI", which is a claim about an application
        that does not exist. The distinction drives real behaviour: `False` tells an
        agent to take the careful path around modals, and there is nothing to be
        careful around."""
        with mock.patch.object(rr.subprocess, "run", return_value=_ps("finder\nDock\n")):
            mode = rr.runtime_mode()
        self.assertFalse(mode["running"])
        self.assertIsNone(mode["headless"])
        self.assertEqual(mode["instances"], 0)

    def test_an_unreadable_process_list_is_undeterminable_not_absent(self) -> None:
        """The bug this shape prevents: "cannot tell" decaying into "nothing is
        running", which is the answer that leads to launching a second instance on
        top of a live one."""
        with mock.patch.object(rr.subprocess, "run", side_effect=OSError("no ps")):
            mode = rr.runtime_mode()
        self.assertFalse(mode["determinable"])
        self.assertIsNone(mode["running"])
        self.assertIsNone(mode["headless"])

    def test_both_macos_editions_are_detected(self) -> None:
        appstore = "/Applications/DaVinci Resolve.app/Contents/MacOS/Resolve -nogui"
        with mock.patch.object(rr.subprocess, "run", return_value=_ps(appstore)):
            self.assertTrue(rr.is_headless())

    def test_a_mere_mention_of_the_path_is_not_an_instance(self) -> None:
        """A shell running a script that *names* Resolve is not Resolve.

        The original substring test counted exactly that as a second instance,
        which made `instances` wrong and made a launch refuse with "a Resolve is
        running in the other mode" — observed against a real `zsh -c` command
        line that happened to contain both the executable path and `-nogui`.
        """
        shell = ("/bin/zsh -c eval 'nohup \"" + self.GUI + "\" -nogui > /tmp/x.log'")
        with mock.patch.object(rr.subprocess, "run", return_value=_ps(f"{shell}\nfinder\n")):
            mode = rr.runtime_mode()
        self.assertFalse(mode["running"], "a shell mentioning the path is not an instance")
        self.assertEqual(mode["instances"], 0)

    def test_flags_do_not_prevent_recognition(self) -> None:
        for command in (self.GUI, self.HEADLESS, self.GUI + " -nogui -fastmode"):
            with self.subTest(command=command):
                with mock.patch.object(rr.subprocess, "run", return_value=_ps(command)):
                    self.assertTrue(rr.runtime_mode()["running"], command)

    def test_windows_quotes_the_executable_and_it_is_still_an_instance(self) -> None:
        """WMIC wraps the command line in double quotes when the executable path
        contains spaces, which the default Windows install path always does.

        The line then *ends* with `"`, so `endswith("Resolve.exe")` was False on
        every stock Windows machine: `runtime_mode` reported `running: false,
        instances: 0` while the same server was driving that very instance over
        the scripting API, and the second-instance guard in `get_resolve()` —
        which asks exactly this question before auto-launching — was reading a
        permanent "nothing is running". Reported in #150.
        """
        exe = r'"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe"'
        # Trailing whitespace included: it is what WMIC actually prints.
        for command in (exe, exe + "  ", exe + " -nogui", r"C:\BMD\Resolve.exe"):
            with self.subTest(command=command):
                with mock.patch.object(rr.subprocess, "run", return_value=_ps(command)):
                    mode = rr.runtime_mode()
                self.assertTrue(mode["running"], command)
                self.assertEqual(mode["instances"], 1)
        with mock.patch.object(rr.subprocess, "run", return_value=_ps(exe + " -nogui")):
            self.assertTrue(rr.is_headless())
        with mock.patch.object(rr.subprocess, "run", return_value=_ps(exe)):
            self.assertFalse(rr.is_headless(), "a quoted GUI instance must not read as headless")

    def test_a_quoted_launcher_that_names_resolve_is_not_an_instance(self) -> None:
        """The quoted-executable path must not become a substring test by another
        route: what sits inside the first quoted span is the executable, and
        everything after the closing quote is arguments."""
        for command in (
            r'"C:\Windows\System32\cmd.exe" /c start "" "C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe" -nogui',
            r'"C:\Windows\explorer.exe"',
        ):
            with self.subTest(command=command):
                with mock.patch.object(rr.subprocess, "run", return_value=_ps(command)):
                    mode = rr.runtime_mode()
                self.assertFalse(mode["running"], command)
                self.assertEqual(mode["instances"], 0)

    def test_a_second_instance_is_counted(self) -> None:
        """Two Resolves is a conflict to report, not a mode to average."""
        with mock.patch.object(rr.subprocess, "run", return_value=_ps(f"{self.GUI}\n{self.HEADLESS}\n")):
            mode = rr.runtime_mode()
        self.assertEqual(mode["instances"], 2)
        self.assertTrue(mode["headless"])

    def test_guidance_travels_with_the_mode(self) -> None:
        with mock.patch.object(rr.subprocess, "run", return_value=_ps(self.HEADLESS)):
            described = rr.describe()
        # This assertion used to require the guidance to say headless raises "no
        # dialog". Measured later: headless is NOT modal-immune — it cannot
        # display a dialog but still tries to raise one, and SaveProject on the
        # never-saved default project then blocks forever where the GUI returns
        # False. The guidance now has to warn, not reassure.
        self.assertIn("NOT modal-immune", described["guidance"])
        self.assertIn("save_project_if_safe", described["guidance"])
        with mock.patch.object(rr.subprocess, "run", return_value=_ps(self.GUI)):
            described = rr.describe()
        self.assertIn("SaveProject", described["guidance"])


class LaunchCommandTests(unittest.TestCase):
    def test_headless_runs_the_binary_because_open_discards_the_flag(self) -> None:
        """`open -a` hands the argument list to LaunchServices, which starts the
        application normally and drops `-nogui` — a window appears and nothing
        reports an error. Verified on macOS; it is the whole reason this helper
        exists instead of appending a flag to the previous launch call."""
        with mock.patch.object(rr.platform, "system", return_value="Darwin"), \
                mock.patch.object(rr.os.path, "exists", return_value=True):
            command = rr.launch_command(headless=True)
        self.assertNotIn("open", command)
        self.assertTrue(command[0].endswith("Contents/MacOS/Resolve"))
        self.assertEqual(command[1], "-nogui")

    def test_the_gui_launch_still_goes_through_open(self) -> None:
        with mock.patch.object(rr.platform, "system", return_value="Darwin"), \
                mock.patch.object(rr.os.path, "exists", return_value=True):
            self.assertEqual(rr.launch_command(headless=False)[0], "open")

    def test_a_missing_install_yields_no_command(self) -> None:
        with mock.patch.object(rr.platform, "system", return_value="Darwin"), \
                mock.patch.object(rr.os.path, "exists", return_value=False):
            self.assertIsNone(rr.launch_command(headless=True))

    def test_linux_and_windows_take_the_flag_directly(self) -> None:
        for system, expected in (("Linux", "/opt/resolve/bin/resolve"), ("Windows", "Resolve.exe")):
            with self.subTest(system=system):
                with mock.patch.object(rr.platform, "system", return_value=system), \
                        mock.patch.object(rr.os.path, "exists", return_value=True):
                    command = rr.launch_command(headless=True)
                self.assertIn(expected, command[0])
                self.assertEqual(command[1], "-nogui")

    def test_headless_preference_is_opt_in(self) -> None:
        self.assertFalse(rr.prefers_headless({}))
        for value in ("1", "true", "YES", "on"):
            self.assertTrue(rr.prefers_headless({rr.ENV_PREFER_HEADLESS: value}), value)
        self.assertFalse(rr.prefers_headless({rr.ENV_PREFER_HEADLESS: "0"}))


class ClassificationTests(unittest.TestCase):
    def _verdict(self, gui, headless, name="thing"):
        return hd.classify(name, gui, headless, present_in=(True, True))["verdict"]

    def test_worked_with_a_ui_and_failed_without_one(self) -> None:
        self.assertEqual(self._verdict(True, False), "headless_degraded")

    def test_the_reverse_is_its_own_verdict(self) -> None:
        """Not folded into a generic "differs": headless succeeding where the GUI
        blocks on a modal is the finding that argues for running headless at all."""
        self.assertEqual(self._verdict(False, True), "gui_degraded")

    def test_failing_in_both_modes_is_not_a_headless_finding(self) -> None:
        self.assertEqual(self._verdict(False, False), "both_failed")
        self.assertEqual(self._verdict(None, None), "both_failed")

    def test_zero_and_empty_string_are_readings_not_failures(self) -> None:
        """A timeline with no markers and an unset property are legitimate answers.
        Counting them as failures manufactures degradations that do not exist."""
        self.assertEqual(self._verdict(0, 0), "parity")
        self.assertEqual(self._verdict("", ""), "parity")

    def test_a_raised_or_absent_surface_probe_counts_as_failure(self) -> None:
        returned = {"outcome": "returned", "value": 1}
        for failed in ({"outcome": "raised", "error": "AttributeError"},
                       {"outcome": "absent"},
                       {"outcome": "unreachable"}):
            with self.subTest(failed=failed):
                self.assertEqual(self._verdict(returned, failed), "headless_degraded")

    def test_byte_counts_compare_as_written_versus_empty(self) -> None:
        """Interchange exports embed the timestamped scratch project name, so their
        exact size differs between two runs by construction. Whether a file was
        produced is the capability question."""
        self.assertEqual(self._verdict(22405, 22282, name="export_drt_bytes"), "parity")
        self.assertEqual(self._verdict(22405, 0, name="export_drt_bytes"), "headless_degraded")
        self.assertEqual(self._verdict(0, 22282, name="export_drt_bytes"), "gui_degraded")

    def test_session_variant_readings_compare_by_type(self) -> None:
        self.assertEqual(self._verdict("uuid-a", "uuid-b", name="GetUniqueId"), "parity")
        self.assertEqual(self._verdict("uuid-a", 7, name="GetUniqueId"), "divergent")

    def test_differing_values_that_are_not_exempt_are_reported(self) -> None:
        self.assertEqual(self._verdict("mp4", "mov"), "divergent")

    def test_an_observation_seen_in_one_run_only_is_untested_not_parity(self) -> None:
        """A coverage gap that renders as a blank cell reads as agreement."""
        self.assertEqual(
            hd.classify("thing", True, None, present_in=(True, False))["verdict"], "untested"
        )


class MatrixTests(unittest.TestCase):
    def _reports(self):
        gui = {
            "metadata": {"version": "19.1.3.7"},
            "surface": {"timeline.GetName": {"outcome": "returned", "value": "A"},
                        "_pass_meta": {"page_before": "edit"}},
            "scenarios": {"gallery": {"export_stills": True}},
        }
        headless = {
            "metadata": {"version": "19.1.3.7"},
            "surface": {"timeline.GetName": {"outcome": "returned", "value": "A"},
                        "_pass_meta": {"page_before": "media"}},
            "scenarios": {"gallery": {"export_stills": False}},
        }
        return gui, headless

    def test_pass_metadata_is_not_mistaken_for_an_observation(self) -> None:
        matrix = hd.build_matrix(*self._reports())
        self.assertNotIn("surface::_pass_meta", [f["key"] for f in matrix["findings"]])

    def test_counts_and_grouping_line_up(self) -> None:
        matrix = hd.build_matrix(*self._reports())
        self.assertEqual(matrix["counts"]["headless_degraded"], 1)
        groups = hd.by_group(matrix)
        self.assertEqual(groups["gallery"]["headless_degraded"], 1)
        self.assertEqual(groups["surface"]["parity"], 1)

    def test_the_rendered_report_names_the_degradation(self) -> None:
        markdown = hd.render_matrix_markdown(hd.build_matrix(*self._reports()))
        self.assertIn("gallery::export_stills", markdown)
        self.assertIn("## Coverage", markdown)

    def test_a_clean_run_says_so_instead_of_printing_an_empty_table(self) -> None:
        gui, _ = self._reports()
        matrix = hd.build_matrix(gui, gui)
        self.assertIn("every observation reached parity", hd.render_matrix_markdown(matrix))


class WindowsProcessReadersTest(unittest.TestCase):
    r"""The Windows reader chain, and why there is a chain at all.

    WMIC was removed in Windows 11 build 26200 — not on PATH, and absent from
    C:\Windows\System32\wbem. Spawning it raises FileNotFoundError, the read
    returned None, and None is "cannot determine", so every tool refused with
    RESOLVE_NOT_RUNNING while Resolve ran in front of the user. Reported in
    #210 with the PowerShell replacement, verified there on build 26200; the
    maintainer has no Windows machine, so these tests are the local half and
    the hardware half is the reporter's.
    """

    EXE = r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe"

    def _readers(self, *, wmic=None, powershell=None, pwsh=None):
        """A fake spawn where each reader either answers or is not installed.

        None means "this binary does not exist here" — FileNotFoundError, the
        way a missing executable actually fails, not a non-zero exit.
        """
        answers = {"wmic": wmic, "powershell": powershell, "pwsh": pwsh}

        def run(command, *args, **kwargs):
            answer = answers.get(command[0])
            if answer is None:
                raise FileNotFoundError(2, "not found: " + command[0])
            return mock.Mock(returncode=answer[0], stdout=answer[1])

        return run

    def _cim(self, command_line, executable=None, pid=12692, name="Resolve.exe"):
        return "%d\t%s\t%s\t%s" % (
            pid, name, self.EXE if executable is None else executable, command_line)

    def _mode(self, run):
        with mock.patch.object(rr.platform, "system", return_value="Windows"):
            with mock.patch.object(rr.subprocess, "run", side_effect=run):
                return rr.runtime_mode()

    def test_a_machine_without_wmic_still_sees_the_running_resolve(self) -> None:
        """The reported bug: the only reader is gone, so the answer was None."""
        mode = self._mode(self._readers(powershell=(0, self._cim('"%s"' % self.EXE))))
        self.assertTrue(mode["determinable"])
        self.assertTrue(mode["running"])
        self.assertEqual(mode["instances"], 1)
        self.assertFalse(mode["headless"])

    def test_the_flag_survives_the_new_reader(self) -> None:
        """Headless detection is the whole reason a command line is read at
        all; a fallback that lost `-nogui` would be a silent downgrade."""
        mode = self._mode(self._readers(powershell=(0, self._cim('"%s" -nogui' % self.EXE))))
        self.assertTrue(mode["running"])
        self.assertTrue(mode["headless"])

    def test_an_unreadable_command_line_is_still_a_running_instance(self) -> None:
        """The case that decided the query's shape.

        A Resolve running elevated or under another account can answer
        ExecutablePath while CommandLine comes back empty. Reading only the
        command line makes that instance no row at all — an empty list, which
        does not mean "cannot tell", it means "nothing is running", and that
        is the answer that launches a second Resolve onto a live one. The
        executable column keeps it counted; the mode is honestly unknown.
        """
        mode = self._mode(self._readers(powershell=(0, self._cim(""))))
        self.assertTrue(mode["running"])
        self.assertEqual(mode["instances"], 1)
        self.assertIsNone(mode["headless"], "no argv means the mode is unknown, not GUI")

    def test_only_the_process_name_survives_and_it_is_still_an_instance(self) -> None:
        """The shape the reporter actually measured on build 26200.

        Querying as an unelevated user, a process the caller cannot fully read
        comes back with ProcessId and Name populated and CommandLine NULL —
        the *column* is access-restricted, not the row. ExecutablePath was not
        shown to survive that restriction, and for a protected process it
        commonly does not, so the executable column falls back to the bare
        process name. That is still enough to prove an instance is up, which
        is the only claim that has to hold: the guard this feeds asks "may I
        launch?", and the answer must be no.
        """
        mode = self._mode(self._readers(powershell=(0, self._cim("", executable=""))))
        self.assertTrue(mode["running"], "a row with only a name still proves Resolve is up")
        self.assertEqual(mode["instances"], 1)
        self.assertIsNone(mode["headless"], "-nogui lives only in the command line")

    def test_wmic_is_still_preferred_where_it_exists(self) -> None:
        """Machines that still have WMIC must be untouched by the fallback."""
        run = self._readers(wmic=(0, '"%s"' % self.EXE),
                            powershell=(0, self._cim('"%s" -nogui' % self.EXE)))
        mode = self._mode(run)
        self.assertTrue(mode["running"])
        self.assertFalse(mode["headless"], "the WMIC answer must win, not PowerShell's")

    def test_a_reader_that_runs_and_finds_nothing_ends_the_chain(self) -> None:
        """An empty answer is an answer. Falling through to the next reader
        would make "no Resolve running" cost every timeout in the chain."""
        calls = []

        def run(command, *args, **kwargs):
            calls.append(command[0])
            if command[0] == "wmic":
                raise FileNotFoundError(2, "not found: wmic")
            return mock.Mock(returncode=0, stdout="")

        mode = self._mode(run)
        self.assertTrue(mode["determinable"])
        self.assertFalse(mode["running"])
        self.assertEqual(mode["instances"], 0)
        self.assertEqual(calls, ["wmic", "powershell"], "pwsh must not be reached")

    def test_a_broken_reader_falls_through_to_the_next(self) -> None:
        """Non-zero exit with nothing on stdout is a reader that did not work,
        not a machine with no Resolve on it."""
        run = self._readers(powershell=(1, ""), pwsh=(0, self._cim('"%s"' % self.EXE)))
        mode = self._mode(run)
        self.assertTrue(mode["running"])
        self.assertEqual(mode["instances"], 1)

    def test_no_reader_at_all_is_undeterminable_not_empty(self) -> None:
        """The distinction the whole module is built on must survive the chain."""
        mode = self._mode(self._readers())
        self.assertFalse(mode["determinable"])
        self.assertIsNone(mode["running"])
        self.assertIsNone(mode["instances"])

    def test_a_command_line_containing_tabs_keeps_its_arguments(self) -> None:
        """The command line is the last column and may contain the separator,
        so the split is bounded rather than greedy."""
        rows = rr._windows_cim_rows('7	Resolve.exe	%s	"%s"	-nogui' % (self.EXE, self.EXE))
        self.assertEqual(rows[0]["pid"], 7)
        self.assertTrue(rows[0]["args"].endswith('	-nogui'))

    def test_a_non_numeric_pid_does_not_lose_the_row(self) -> None:
        """A header or a stray line must not raise; the row still carries its
        columns, keyed by a synthetic pid the way the WMIC branch always has."""
        rows = rr._windows_cim_rows("ProcessId	Name	ExecutablePath	CommandLine")
        self.assertEqual(len(rows), 1)
        self.assertLess(rows[0]["pid"], 0)


if __name__ == "__main__":
    unittest.main()
