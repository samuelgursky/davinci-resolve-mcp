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


if __name__ == "__main__":
    unittest.main()
