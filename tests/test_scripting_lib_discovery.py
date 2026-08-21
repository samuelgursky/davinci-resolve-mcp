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
        with open(path, "w"):
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
        with open(path, "w"):
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
            with open(exe, "w"):
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


class GetResolvePathsDiscoveryTests(unittest.TestCase):
    def test_discovery_fills_in_a_missing_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lib = os.path.join(tmp, "fusionscript.so")
            with open(lib, "w"):
                pass
            with mock.patch.object(platform_utils, "get_platform", return_value="darwin"), \
                    mock.patch.object(platform_utils, "discover_scripting_lib", return_value=lib), \
                    mock.patch.dict(os.environ, _env_without_overrides(), clear=True):
                paths = platform_utils.get_resolve_paths()
            self.assertEqual(paths["lib_path"], lib)

    def test_an_existing_env_override_still_wins_over_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            override = os.path.join(tmp, "override.so")
            discovered = os.path.join(tmp, "discovered.so")
            for path in (override, discovered):
                with open(path, "w"):
                    pass
            env = _env_without_overrides()
            env["RESOLVE_SCRIPT_LIB"] = override
            with mock.patch.object(platform_utils, "get_platform", return_value="darwin"), \
                    mock.patch.object(platform_utils, "discover_scripting_lib", return_value=discovered), \
                    mock.patch.dict(os.environ, env, clear=True):
                paths = platform_utils.get_resolve_paths()
            self.assertEqual(paths["lib_path"], override)

    def test_the_platform_default_survives_when_discovery_finds_nothing(self) -> None:
        """A failed lookup must not replace the expected path with a second guess:
        the default is what the error message needs to name."""
        with mock.patch.object(platform_utils, "get_platform", return_value="darwin"), \
                mock.patch.object(platform_utils, "discover_scripting_lib", return_value=None), \
                mock.patch.dict(os.environ, _env_without_overrides(), clear=True):
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
            with open(lib, "w"):
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
            with open(override, "w"):
                pass
            env = _env_without_overrides()
            env["RESOLVE_SCRIPT_LIB"] = override
            with mock.patch.object(install, "RESOLVE_PATHS", _resolve_paths_with_api(tmp)), \
                    mock.patch.object(platform_utils, "discover_scripting_lib",
                                      return_value="/should/not/be/used.dll"), \
                    mock.patch.dict(os.environ, env, clear=True):
                _, lib_path = install.find_resolve_paths()
        self.assertEqual(lib_path, override)


if __name__ == "__main__":
    unittest.main()
