"""Finding fusionscript when Resolve is not where the defaults say it is.

Blackmagic's `DaVinciResolveScript.py` hardcodes one install root per platform,
and this project's defaults mirrored it. A Resolve installed anywhere else — a
second drive, an external volume, a custom directory — was therefore invisible,
and the failure was silent in a specific and expensive way:

  1. `find_resolve_paths()` returned `lib_path=None`.
  2. `build_server_env()` turned that into `"RESOLVE_SCRIPT_LIB": ""`, which
     reads as configured in the config file but is falsy to the loader, so it
     reverted to the same hardcoded path that was already known to be wrong.
  3. The connection check failed with `DLL load failed`, mid-output.
  4. The installer's last line said `Setup complete!`.

The running Resolve process settles the question without guessing: its image
path is the install location. These tests pin that discovery, and pin the two
reporting behaviours that let the failure masquerade as a success.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils import platform as platform_utils  # noqa: E402
from src.utils import resolve_runtime as rr  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "resolve_install", PROJECT_ROOT / "install.py"
)
install = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(install)

ENV_KEYS = ("RESOLVE_SCRIPT_API", "RESOLVE_SCRIPT_LIB")


def _ps(stdout: str):
    return mock.Mock(returncode=0, stdout=stdout)


def _env_without_overrides():
    return {k: v for k, v in os.environ.items() if k not in ENV_KEYS}


def _resolve_paths_with_api(api_dir: str) -> dict:
    """A RESOLVE_PATHS stand-in with a real API dir and no findable library.

    Both the host's key and "Linux" are present because `find_resolve_paths`
    reads `RESOLVE_PATHS.get(SYSTEM, RESOLVE_PATHS["Linux"])`, and Python
    evaluates that default eagerly — a replacement holding only the host key
    raises KeyError on any host that is not Linux.
    """
    entry = {"api": [api_dir], "lib": ["/nope/fusionscript.dll"], "app": []}
    return {install.SYSTEM: entry, "Linux": entry}


def _windows_install(root: str) -> str:
    """A Resolve.exe with fusionscript.dll beside it. Returns the exe path."""
    os.makedirs(root, exist_ok=True)
    exe = os.path.join(root, "Resolve.exe")
    for path in (exe, os.path.join(root, "fusionscript.dll")):
        with open(path, "w", encoding="utf-8"):
            pass
    return exe


def _macos_install(root: str) -> str:
    """A Resolve.app laid out the way the installer build is. Returns the exe.

    Joined with "/" on every host, not os.sep: RESOLVE_PROCESS_PATTERNS matches
    a slash-separated suffix, because that is what `ps` prints. Building this
    fixture with the host separator made the test pass on POSIX and fail on
    Windows for a reason that has nothing to do with the code under test.
    Windows accepts forward slashes in filesystem calls, so the files below are
    still real on both.
    """
    bundle = f"{root}/DaVinci Resolve.app"
    macos = f"{bundle}/Contents/MacOS"
    fusion = f"{bundle}/Contents/Libraries/Fusion"
    os.makedirs(macos, exist_ok=True)
    os.makedirs(fusion, exist_ok=True)
    exe = f"{macos}/Resolve"
    for path in (exe, f"{fusion}/fusionscript.so"):
        with open(path, "w", encoding="utf-8"):
            pass
    return exe


class RunningResolveLibTests(unittest.TestCase):
    def test_windows_install_on_another_drive_is_found(self) -> None:
        """The reported case: Resolve on F:, the default probing C:."""
        with tempfile.TemporaryDirectory() as tmp:
            exe = _windows_install(os.path.join(tmp, "Blackmagic Design", "DaVinci Resolve"))
            # WMIC quotes a path containing spaces, and this one does.
            with mock.patch.object(rr.platform, "system", return_value="Windows"), \
                    mock.patch.object(rr.subprocess, "run", return_value=_ps(f'"{exe}"  \n')):
                found = rr.running_resolve_lib()
            self.assertEqual(found, os.path.join(os.path.dirname(exe), "fusionscript.dll"))

    def test_macos_reads_through_the_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            exe = _macos_install(tmp)
            with mock.patch.object(rr.platform, "system", return_value="Darwin"), \
                    mock.patch.object(rr.subprocess, "run", return_value=_ps(f"{exe}\nDock\n")):
                found = rr.running_resolve_lib()
            self.assertIsNotNone(found)
            normalized = found.replace(os.sep, "/")
            self.assertTrue(normalized.endswith("Libraries/Fusion/fusionscript.so"))
            self.assertTrue(os.path.isfile(found))

    def test_flags_after_the_executable_do_not_break_the_derivation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            exe = _macos_install(tmp)
            with mock.patch.object(rr.platform, "system", return_value="Darwin"), \
                    mock.patch.object(rr.subprocess, "run", return_value=_ps(f"{exe} -nogui\n")):
                self.assertIsNotNone(rr.running_resolve_lib())

    def test_nothing_running_is_none_not_a_guess(self) -> None:
        with mock.patch.object(rr.subprocess, "run", return_value=_ps("Dock\nfinder\n")):
            self.assertIsNone(rr.running_resolve_lib())

    def test_an_unreadable_process_list_is_none(self) -> None:
        with mock.patch.object(rr.subprocess, "run", side_effect=OSError("no wmic")):
            self.assertIsNone(rr.running_resolve_lib())

    def test_a_running_resolve_without_the_library_beside_it_is_none(self) -> None:
        """Derivation must confirm the file, not assume the layout."""
        with tempfile.TemporaryDirectory() as tmp:
            exe = os.path.join(tmp, "Resolve.exe")
            with open(exe, "w", encoding="utf-8"):
                pass
            with mock.patch.object(rr.platform, "system", return_value="Windows"), \
                    mock.patch.object(rr.subprocess, "run", return_value=_ps(f'"{exe}"\n')):
                self.assertIsNone(rr.running_resolve_lib())


class CandidateListTests(unittest.TestCase):
    """The cold-install lists, for when Resolve is not running.

    These are pure path construction — no filesystem, so they run identically on
    every host and cover the platforms this developer cannot test on.
    """

    def test_windows_looks_beyond_the_c_drive(self) -> None:
        with mock.patch.dict(os.environ, {"PROGRAMFILES": r"C:\Program Files"}, clear=True), \
                mock.patch.object(platform_utils.os.path, "isdir", lambda p: p in ("C:\\", "F:\\")):
            candidates = platform_utils._windows_lib_candidates()
        self.assertTrue(any(c.startswith("F:") for c in candidates))
        self.assertTrue(any("Program Files" in c for c in candidates))
        self.assertTrue(all(c.endswith("fusionscript.dll") for c in candidates))

    def test_macos_covers_both_bundle_locations(self) -> None:
        """The App Store build sits at /Applications/DaVinci Resolve.app, which
        the platform default does not name."""
        candidates = platform_utils._macos_lib_candidates()
        self.assertIn(
            "/Applications/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so",
            [c.replace(os.sep, "/") for c in candidates],
        )
        self.assertEqual(len(candidates), 2)

    def test_linux_covers_the_shipped_opt_layouts(self) -> None:
        candidates = platform_utils._linux_lib_candidates()
        self.assertTrue(all(c.startswith("/opt/resolve/") for c in candidates))
        self.assertTrue(all(c.endswith("fusionscript.so") for c in candidates))

    def test_an_unknown_platform_yields_no_candidates_rather_than_an_error(self) -> None:
        # Patched on resolve_runtime, not on this module: discover_scripting_lib
        # imports the helper inside the function body, so that is where the
        # lookup lands. Patching the wrong module leaves the real process probe
        # running and makes the result depend on whether Resolve happens to be
        # open on the machine running the tests.
        with mock.patch.object(rr, "running_resolve_lib", return_value=None):
            self.assertIsNone(platform_utils.discover_scripting_lib("plan9"))


def _default_lib_absent():
    """Make the platform default missing, whatever this machine has installed.

    `get_resolve_paths()` only reaches discovery when the default is not on
    disk, so a test that does not force that condition checks nothing on a
    machine where Resolve *is* at the default location — and on macOS it does
    not merely pass vacuously, it fails, because the real default comes back
    instead of the stub. Neither of the machines this change was written on
    shows it: a Linux box has no `/Applications`, and the Windows box that
    prompted the fix has Resolve on `F:`, so on both the default is already
    absent for real and the branch runs by accident.
    """
    real_isfile = os.path.isfile
    return mock.patch.object(
        platform_utils.os.path,
        "isfile",
        lambda path: False if "DaVinci Resolve" in str(path) else real_isfile(path),
    )


class GetResolvePathsDiscoveryTests(unittest.TestCase):
    def test_discovery_fills_in_a_missing_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lib = os.path.join(tmp, "fusionscript.so")
            with open(lib, "w", encoding="utf-8"):
                pass
            with mock.patch.object(platform_utils, "get_platform", return_value="darwin"), \
                    mock.patch.object(platform_utils, "discover_scripting_lib", return_value=lib), \
                    mock.patch.dict(os.environ, _env_without_overrides(), clear=True), \
                    _default_lib_absent():
                paths = platform_utils.get_resolve_paths()
            self.assertEqual(paths["lib_path"], lib)

    def test_an_existing_env_override_still_wins_over_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            override = os.path.join(tmp, "override.so")
            discovered = os.path.join(tmp, "discovered.so")
            for path in (override, discovered):
                with open(path, "w", encoding="utf-8"):
                    pass
            env = _env_without_overrides()
            env["RESOLVE_SCRIPT_LIB"] = override
            with mock.patch.object(platform_utils, "get_platform", return_value="darwin"), \
                    mock.patch.object(platform_utils, "discover_scripting_lib", return_value=discovered), \
                    mock.patch.dict(os.environ, env, clear=True), \
                    _default_lib_absent():
                paths = platform_utils.get_resolve_paths()
            self.assertEqual(paths["lib_path"], override)

    def test_the_platform_default_survives_when_discovery_finds_nothing(self) -> None:
        """A failed lookup must not replace the expected path with a second guess:
        the default is what the error message needs to name."""
        with mock.patch.object(platform_utils, "get_platform", return_value="darwin"), \
                mock.patch.object(platform_utils, "discover_scripting_lib", return_value=None), \
                mock.patch.dict(os.environ, _env_without_overrides(), clear=True), \
                _default_lib_absent():
            paths = platform_utils.get_resolve_paths()
        self.assertEqual(
            paths["lib_path"],
            "/Applications/DaVinci Resolve/DaVinci Resolve.app"
            "/Contents/Libraries/Fusion/fusionscript.so",
        )


class InstallerEnvTests(unittest.TestCase):
    def test_an_unfound_library_is_omitted_not_written_empty(self) -> None:
        """`"RESOLVE_SCRIPT_LIB": ""` is the worst of both worlds: it looks set
        in the config and is unset to the loader, which then falls back to the
        hardcoded default that was already missing."""
        env = install.build_server_env(
            "/usr/bin/python3", "/api", None, system="Darwin"
        )
        self.assertNotIn("RESOLVE_SCRIPT_LIB", env)
        self.assertEqual(env["RESOLVE_SCRIPT_API"], "/api")

    def test_a_found_library_is_written(self) -> None:
        env = install.build_server_env(
            "/usr/bin/python3", "/api", "/Resolve/fusionscript.so", system="Darwin"
        )
        self.assertEqual(env["RESOLVE_SCRIPT_LIB"], "/Resolve/fusionscript.so")

    def test_find_resolve_paths_falls_back_to_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lib = os.path.join(tmp, "fusionscript.dll")
            with open(lib, "w", encoding="utf-8"):
                pass
            with mock.patch.object(install, "RESOLVE_PATHS", _resolve_paths_with_api(tmp)), \
                    mock.patch.object(platform_utils, "discover_scripting_lib", return_value=lib), \
                    mock.patch.dict(os.environ, _env_without_overrides(), clear=True):
                api_path, lib_path = install.find_resolve_paths()
        self.assertEqual(api_path, tmp)
        self.assertEqual(lib_path, lib)

    def test_an_env_override_is_preferred_over_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            override = os.path.join(tmp, "override.dll")
            with open(override, "w", encoding="utf-8"):
                pass
            env = _env_without_overrides()
            env["RESOLVE_SCRIPT_LIB"] = override
            with mock.patch.object(install, "RESOLVE_PATHS", _resolve_paths_with_api(tmp)), \
                    mock.patch.object(platform_utils, "discover_scripting_lib",
                                      return_value="/should/not/be/used.dll"), \
                    mock.patch.dict(os.environ, env, clear=True):
                _, lib_path = install.find_resolve_paths()
        self.assertEqual(lib_path, override)

#: Stand-in for whatever `find_resolve_paths()` would discover. Any truthy
#: api_path reaches the verification branch, which is all the reporting tests
#: need; nothing is opened, because the probe is pinned alongside it.
_PINNED_PATHS = ("/pinned/Developer/Scripting", "/pinned/fusionscript.so")


def _resolve_is_installed() -> bool:
    """True when this machine has BOTH halves install.py needs to verify.

    The failure-path tests below mock RESOLVE_PATHS to a dead install and run
    everywhere; the success-path one deliberately does not, so it can only run
    where a real one exists.

    Both halves, not just the library: `main()` sets `verification_failed` when
    `api_path` is falsy ("Skipped — Resolve API path not detected") without ever
    running the probe. A gate that checked only `lib` therefore admitted a
    machine where the app is installed but `Developer/Scripting` is not —
    Studio's installer can leave that component out, and on Linux it lives
    somewhere the defaults may not name — and on such a machine the success-path
    test failed deterministically, for a reason that has nothing to do with the
    regression it pins.
    """
    username = os.environ.get("USER", os.environ.get("USERNAME", ""))
    for paths in install.RESOLVE_PATHS.values():
        has_api = any(
            Path(candidate.replace("{user}", username)).is_dir()
            for candidate in paths.get("api", [])
        )
        has_lib = any(
            Path(candidate.replace("{user}", username)).is_file()
            for candidate in paths.get("lib", [])
        )
        if has_api and has_lib:
            return True
    return False


#: The switch the live harnesses already use, e.g. `tests/live_drp_roundtrip_verification.py`.
LIVE_OPT_IN_ENV = "RESOLVE_VERIFY"


def _live_resolve_requested() -> bool:
    """Has whoever runs the suite asked for the test that talks to a live Resolve?

    Read when the test runs, not in a decorator at import, so the regression test
    below can run the live test with the switch off and on.
    """
    return os.environ.get(LIVE_OPT_IN_ENV) in ("1", "true", "yes")


class SetupExitStatusTests(unittest.TestCase):
    """The summary line and the exit status have to agree with each other.

    `Setup complete!` over a dead install was the headline bug. Two ways out of
    the same block survived the first fix: the no-clients branch still printed
    `Environment ready!`, and `main()` returned None either way, so
    `npx davinci-resolve-mcp setup` in a script or CI saw a zero over an install
    that could not load the API. Both are pinned here because both are invisible
    in a normal interactive run on a working machine.
    """

    @staticmethod
    def _run_main(*, clients, healthy, verification=None, probe_result=None,
                  found_paths=None):
        """Run `install.main()` with stdout captured.

        `verification` pins the probe's answer to `(success, message)` instead
        of letting it talk to whatever Resolve is on the machine, which is what
        makes the summary/exit-status assertions deterministic.

        `found_paths` pins `find_resolve_paths()` to `(api_path, lib_path)`.
        Pinning the verification alone is not enough to make a test
        machine-independent: `main()` only calls the probe `if api_path`, and
        otherwise sets `verification_failed` directly. A test that pinned the
        probe but let discovery run would therefore still fail on a machine
        with no Resolve — the probe it pinned never gets called.

        `probe_result`, if given a list, receives the real probe's
        `(success, message)` so a caller can tell "the installer misreported a
        good verification" from "this machine's Resolve did not answer".
        """
        import contextlib
        import io

        dead = {
            key: {"api": ["/nonexistent/api"], "lib": ["/nonexistent/fusionscript.so"]}
            for key in install.RESOLVE_PATHS
        }
        buf = io.StringIO()
        argv = ["install.py", "--clients", clients, "--dry-run", "--no-venv"]

        real_verify = install.verify_resolve_connection

        def _spy(*args, **kwargs):
            outcome = real_verify(*args, **kwargs)
            if probe_result is not None:
                probe_result.append(outcome)
            return outcome

        paths_patch = (
            mock.patch.object(install, "find_resolve_paths", return_value=found_paths)
            if found_paths is not None else contextlib.nullcontext()
        )

        if verification is not None:
            verify_patch = mock.patch.object(
                install, "verify_resolve_connection", return_value=verification)
        elif probe_result is not None:
            verify_patch = mock.patch.object(
                install, "verify_resolve_connection", side_effect=_spy)
        else:
            verify_patch = contextlib.nullcontext()

        with mock.patch.object(
                install, "RESOLVE_PATHS",
                install.RESOLVE_PATHS if healthy else dead), \
                mock.patch.dict(os.environ, _env_without_overrides(), clear=True), \
                mock.patch.object(sys, "argv", argv), \
                paths_patch, \
                verify_patch, \
                contextlib.redirect_stdout(buf):
            try:
                code = install.main()
            except SystemExit as exc:  # pragma: no cover - defensive
                code = exc.code
        return code, buf.getvalue()

    def test_a_failed_verification_exits_non_zero(self) -> None:
        code, out = self._run_main(clients="manual", healthy=False)
        self.assertEqual(code, 1)
        self.assertIn("Setup incomplete", out)
        self.assertNotIn("Setup complete!", out)

    def test_the_no_clients_branch_is_not_reported_ready_when_verification_failed(self) -> None:
        code, out = self._run_main(clients="", healthy=False)
        self.assertEqual(code, 1)
        self.assertIn("Environment incomplete", out)
        self.assertNotIn("Environment ready!", out)

    def test_a_working_install_still_reports_ready_and_exits_zero(self) -> None:
        """The regression that matters in the other direction: an installer that
        called every machine broken would be worse than the bug it replaced.

        Pinned against a *stated* successful verification rather than against
        whatever Resolve happens to be on the machine. What this guards is the
        reporting logic — a success must print `Environment ready!` and return
        0 — and that is a property of `main()`, not of the host. Deriving it
        from a live probe made the test unrunnable on CI and, worse,
        occasionally wrong here: see
        `test_the_live_probe_agrees_with_the_summary` below for why the live
        form cannot carry this assertion.
        """
        code, out = self._run_main(
            clients="", healthy=False, found_paths=_PINNED_PATHS,
            verification=(True, "API module loaded (Resolve not running)"))
        self.assertEqual(code, 0, msg=f"installer output was:\n{out}")
        self.assertIn("Environment ready!", out, msg=f"installer output was:\n{out}")

    def test_a_stated_failure_is_never_reported_ready(self) -> None:
        """The same invariant from the other side, and the one that was the
        original bug. Independent of RESOLVE_PATHS: it is the verification
        result, not the machine, that decides the summary."""
        code, out = self._run_main(
            clients="", healthy=False, found_paths=_PINNED_PATHS,
            verification=(False, "Connection timed out"))
        self.assertEqual(code, 1, msg=f"installer output was:\n{out}")
        self.assertIn("Environment incomplete", out)
        self.assertNotIn("Environment ready!", out)

    def test_the_live_probe_agrees_with_the_summary(self) -> None:
        """Integration check: run the real probe and confirm the summary matches it.

        This is deliberately *not* an assertion that the probe succeeds. The
        probe spawns a subprocess that asks a live GUI application to answer
        over IPC within 10 seconds, and returns `False, "Connection timed out"`
        if it does not. Resolve can be mid-launch, showing a modal, loading a
        project, or simply slow while the rest of this suite saturates the
        machine — none of which is a defect in the installer, and all of which
        made this test fail roughly once in a run of the full suite while
        passing on its own.

        So a probe that did not answer is a skip naming the reason, not a
        failure. What is still asserted, and is the whole point: whatever the
        probe said, the summary line and the exit status must agree with it.
        The reporting invariant itself is pinned deterministically above.

        Opt-in with `RESOLVE_VERIFY=1`, like the live harnesses. It used to run
        whenever Resolve was installed. The probe's child sets PYTHONPATH to
        Blackmagic's Modules directory, so neither the offline guard's child site
        nor a PYTHONPATH tripwire loads in it. With Resolve open, every run of the
        offline suite connected to it: `scriptapp`, then `GetProductName` and
        `GetVersionString`.
        """
        if not _live_resolve_requested():
            self.skipTest(f"talks to a live Resolve; set {LIVE_OPT_IN_ENV}=1 to run it")
        if not _resolve_is_installed():
            self.skipTest(
                "needs a real Resolve install — this exercises the real probe, and "
                "without Resolve on the machine there is no probe result to check")
        probe: list = []
        code, out = self._run_main(clients="", healthy=True, probe_result=probe)
        self.assertEqual(len(probe), 1, msg=f"probe ran {len(probe)} times:\n{out}")
        success, message = probe[0]
        if not success:
            self.skipTest(
                f"live Resolve probe did not answer, so there is no healthy "
                f"branch to check on this machine right now: {message}")
        self.assertEqual(code, 0, msg=f"probe succeeded but exit was {code}:\n{out}")
        self.assertIn("Environment ready!", out, msg=f"installer output was:\n{out}")


class ReportingTestsStayMachineIndependentTests(unittest.TestCase):
    """The summary/exit-status assertions must not depend on a live Resolve.

    They used to. `test_a_working_install_still_reports_ready_and_exits_zero`
    asserted the healthy branch by running the *real* probe against whatever
    Resolve was on the machine — a subprocess asking a GUI application to answer
    over IPC inside 10 seconds. That made the test unrunnable on CI, and made it
    fail here roughly once per full-suite run while passing in isolation,
    because Resolve can be mid-launch, modal, loading a project, or merely slow
    while the rest of the suite saturates the box. None of that is a defect in
    the installer, which is what the test exists to catch.

    These guards fail if that dependency comes back.
    """

    def test_the_ready_assertion_holds_on_a_machine_with_no_resolve(self) -> None:
        """Dead RESOLVE_PATHS, pinned discovery, stated success -> still ready.

        This is the property that makes the assertion meaningful: the summary
        follows the verification *result*, not the host. If someone re-derives
        it from the machine, this fails on every box without Resolve — which is
        every CI runner.
        """
        code, out = SetupExitStatusTests._run_main(
            clients="", healthy=False, found_paths=_PINNED_PATHS,
            verification=(True, "API module loaded (Resolve not running)"))
        self.assertEqual(code, 0, msg=out)
        self.assertIn("Environment ready!", out)

    #: The one test allowed to touch a live Resolve. Everything else in
    #: SetupExitStatusTests must be decided by a pinned verification.
    LIVE_TEST = "test_the_live_probe_agrees_with_the_summary"

    def test_only_the_designated_live_test_touches_a_real_resolve(self) -> None:
        """Run every other SetupExitStatusTests case with the probe booby-trapped.

        This is the rule the flake violated, stated as an assertion. Any test in
        that class other than `LIVE_TEST` that reaches the real
        `verify_resolve_connection` — by dropping its pin, by letting discovery
        find the host's Resolve, or by being added without one — spawns a
        subprocess against a live GUI app and inherits its timing. Here that
        call raises instead, so such a test fails loudly at authoring time
        rather than once a fortnight in someone's suite run.
        """
        def _explode(*args, **kwargs):
            raise AssertionError(
                "reached the real verify_resolve_connection, which probes a "
                "live Resolve over IPC with a 10s timeout. Pin it with "
                "_run_main(verification=...) and found_paths=_PINNED_PATHS, or "
                "name this test in LIVE_TEST if it genuinely needs the probe.")

        names = [n for n in dir(SetupExitStatusTests)
                 if n.startswith("test_") and n != self.LIVE_TEST]
        self.assertGreater(len(names), 2, "expected several reporting tests to check")

        real = install.verify_resolve_connection
        install.verify_resolve_connection = _explode
        try:
            result = unittest.TextTestRunner(
                stream=open(os.devnull, "w", encoding="utf-8"), verbosity=0,
            ).run(unittest.TestSuite(
                [SetupExitStatusTests(name) for name in names]))
        finally:
            install.verify_resolve_connection = real

        problems = [f"{t.id().rsplit('.', 1)[-1]}: {err.strip().splitlines()[-1]}"
                    for t, err in (result.failures + result.errors)]
        self.assertEqual(
            problems, [],
            "these reporting tests depend on a live Resolve:\n  " + "\n  ".join(problems))

    def test_the_reporting_tests_never_spawn_the_real_probe(self) -> None:
        """A pinned verification must actually replace the probe, not shadow it.

        `verify_resolve_connection` spawns a subprocess. If a future edit pins
        the result but lets the real function run first (or pins the wrong
        symbol), the test would still pass while reacquiring the flakiness it
        was written to remove. Exploding on any real call is the only way to
        state "this must never touch a live Resolve" as an assertion.
        """
        def _explode(*args, **kwargs):  # pragma: no cover - must not be reached
            raise AssertionError(
                "the real verify_resolve_connection was called by a test that "
                "pinned it — the pin is not taking effect")

        real = install.verify_resolve_connection
        install.verify_resolve_connection = _explode
        try:
            for verification, expected in ((True, 0), (False, 1)):
                code, out = SetupExitStatusTests._run_main(
                    clients="", healthy=False, found_paths=_PINNED_PATHS,
                    verification=(verification, "pinned"))
                self.assertEqual(code, expected, msg=out)
        finally:
            install.verify_resolve_connection = real

    def test_the_live_test_runs_only_when_asked(self) -> None:
        """`LIVE_TEST` stays off in the offline suite unless `RESOLVE_VERIFY=1` is set.

        Its probe starts a child with PYTHONPATH set to Blackmagic's Modules
        directory, so neither the offline guard nor a PYTHONPATH tripwire loads in
        it. It used to run whenever Resolve was installed, and with Resolve open
        every run of the suite connected to it. Here the host is made to look
        installed, discovery is pinned and the probe is booby-trapped. With the
        switch on, the trap goes off, which shows it is armed. With the switch off,
        only the opt-in can have kept the test away from it.
        """
        calls: list = []

        def _explode(*args, **kwargs):
            calls.append(args)
            raise AssertionError("reached the real verify_resolve_connection")

        def run_live_test(opted_in: bool):
            del calls[:]
            env = {"DAVINCI_RESOLVE_MCP_UPDATE_CHECK": "0"}  # no request to GitHub
            with mock.patch.dict(os.environ, env), \
                    mock.patch.object(install, "verify_resolve_connection", _explode), \
                    mock.patch.object(install, "find_resolve_paths", return_value=_PINNED_PATHS), \
                    mock.patch.object(sys.modules[__name__], "_resolve_is_installed", return_value=True), \
                    open(os.devnull, "w", encoding="utf-8") as sink:
                if opted_in:
                    os.environ[LIVE_OPT_IN_ENV] = "1"
                else:
                    os.environ.pop(LIVE_OPT_IN_ENV, None)
                return unittest.TextTestRunner(stream=sink, verbosity=0).run(
                    SetupExitStatusTests(self.LIVE_TEST))

        result = run_live_test(opted_in=True)
        self.assertEqual(len(calls), 1, "the booby-trapped probe was not reached with the switch on")
        self.assertFalse(result.wasSuccessful())

        result = run_live_test(opted_in=False)
        self.assertEqual(calls, [], "the live test reached the probe without RESOLVE_VERIFY=1")
        self.assertTrue(result.wasSuccessful(), result.failures + result.errors)
        self.assertEqual(len(result.skipped), 1)
        self.assertIn(LIVE_OPT_IN_ENV, result.skipped[0][1])

    def test_the_skip_gate_covers_everything_the_probe_branch_needs(self) -> None:
        """`_resolve_is_installed()` gates the one test that uses the real probe.

        `main()` marks verification failed when `api_path` is falsy, *before*
        the probe runs. A gate that checked only the library therefore admitted
        machines where the app is present but `Developer/Scripting` is not, and
        there the live test failed deterministically for a reason unrelated to
        the regression it pins. Assert the gate reads both halves.
        """
        entry = {"api": ["/nonexistent/api"], "lib": [__file__], "app": []}
        with mock.patch.object(install, "RESOLVE_PATHS",
                               {install.SYSTEM: entry, "Linux": entry}):
            self.assertFalse(
                _resolve_is_installed(),
                "a library with no API directory must not satisfy the gate — "
                "main() fails verification before the probe ever runs")

        entry_ok = {"api": [str(PROJECT_ROOT)], "lib": [__file__], "app": []}
        with mock.patch.object(install, "RESOLVE_PATHS",
                               {install.SYSTEM: entry_ok, "Linux": entry_ok}):
            self.assertTrue(_resolve_is_installed())


class DiscoveryDoesNotSwallowRealErrorsTests(unittest.TestCase):
    """A defect inside the process probe must not read as 'Resolve is not up'.

    The first cut caught bare `Exception` around the `running_resolve_lib`
    import and call, which is how a silent-fallback bug gets a second life: any
    error raised inside discovery would have been laundered into "nothing
    found", and the caller would have gone on to report the platform default.
    """

    def test_an_error_inside_the_process_probe_propagates(self) -> None:
        with mock.patch.object(rr, "running_resolve_lib",
                               side_effect=RuntimeError("probe is broken")):
            with self.assertRaises(RuntimeError):
                platform_utils.discover_scripting_lib("darwin")


if __name__ == "__main__":
    unittest.main()
