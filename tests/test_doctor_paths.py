"""doctor.py's Resolve/client paths must be per-platform, and must not drift
from install.py's.

Issue #106: doctor.py hardcoded the macOS locations. Run standalone on Windows
(i.e. without the env vars the npm/install.py flow injects) it reported four
FAILs naming a `.app` bundle and `fusionscript.so` on a machine that had
neither — while install.py detected that very same install correctly. Two
tables describing one thing, one of them platform-blind.

So these tests pin two properties:

  1. Each platform gets its own candidates, and macOS's stay byte-identical
     (the fix must not perturb the platform we can actually test on).
  2. Every path doctor names also appears in install.py's RESOLVE_PATHS — the
     drift guard. Subset, not equality: install.py carries extra candidates
     (e.g. Linux's `{user}` template) that doctor has no use for.

What is NOT covered, and is not coverable from macOS: whether those Windows
paths are where Resolve actually installs. They are inherited from install.py,
which has been in the field since v2.0 and is reported working on Windows.
"""

from __future__ import annotations

import ast
import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
if str(REPO) not in sys.path:
    # The discovery tests below reach into src.utils; doctor itself does the
    # same when run standalone.
    sys.path.insert(0, str(REPO))

import doctor  # noqa: E402


def _install_py_resolve_paths() -> dict:
    """RESOLVE_PATHS from install.py, read statically.

    Parsed rather than imported: install.py runs setup work at import time, and
    a diagnostics test must not be the thing that mutates a user's config.
    """
    tree = ast.parse((REPO / "install.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "RESOLVE_PATHS" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("install.py no longer defines RESOLVE_PATHS")


#: doctor keys off sys.platform; install.py keys off platform.system().
_PLATFORM_KEYS = {"darwin": "Darwin", "win32": "Windows", "linux": "Linux"}


class PlatformDefaultsTests(unittest.TestCase):
    def test_every_platform_has_app_api_and_lib_candidates(self) -> None:
        for platform in _PLATFORM_KEYS:
            with self.subTest(platform=platform):
                entry = doctor._RESOLVE_PATH_CANDIDATES[doctor._platform_key(platform)]
                for kind in ("app", "api", "lib"):
                    self.assertTrue(entry[kind], f"{platform}/{kind} has no candidates")

    def test_macos_defaults_are_unchanged(self) -> None:
        """Byte-identical to what doctor shipped before the fix. macOS is the
        platform this repo is developed and live-tested on; a Windows fix that
        perturbs it would trade a bug we cannot reproduce for one we can."""
        entry = doctor._RESOLVE_PATH_CANDIDATES["darwin"]
        self.assertEqual(
            entry["app"][0], "/Applications/DaVinci Resolve/DaVinci Resolve.app"
        )
        self.assertEqual(
            entry["api"][0],
            "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting",
        )
        self.assertEqual(
            entry["lib"][0],
            "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so",
        )

    def test_no_macos_paths_leak_into_the_other_platforms(self) -> None:
        """The actual #106 symptom: `\\Applications\\DaVinci Resolve.app` and
        `fusionscript.so` reported as FAIL on Windows 11."""
        for platform in ("win32", "linux"):
            with self.subTest(platform=platform):
                entry = doctor._RESOLVE_PATH_CANDIDATES[platform if platform == "win32" else "linux"]
                flat = [p for kind in ("app", "api", "lib") for p in entry[kind]]
                self.assertFalse(
                    [p for p in flat if "/Applications/" in p or ".app/" in p],
                    f"macOS bundle path on {platform}: {flat}",
                )

    def test_windows_uses_the_dll_and_linux_the_so(self) -> None:
        self.assertTrue(
            all(p.endswith(".dll") for p in doctor._RESOLVE_PATH_CANDIDATES["win32"]["lib"])
        )
        self.assertTrue(
            all(p.endswith(".so") for p in doctor._RESOLVE_PATH_CANDIDATES["linux"]["lib"])
        )

    def test_an_unknown_platform_falls_back_to_linux(self) -> None:
        # freebsd, sunos, anything else: POSIX layout is the closest guess, and
        # a wrong-but-POSIX path beats a KeyError inside a diagnostic tool.
        self.assertEqual(doctor._platform_key("freebsd14"), "linux")

    def test_the_default_is_the_first_existing_candidate(self) -> None:
        """Windows lists two scripting-API locations; doctor must name whichever
        is actually present rather than always the first."""
        from unittest import mock

        candidates = ("/nope/missing-api", "/nope/present-api")
        with mock.patch.dict(
            doctor._RESOLVE_PATH_CANDIDATES["win32"], {"api": candidates}
        ), mock.patch.object(
            doctor.Path, "exists", lambda self: str(self) == "/nope/present-api"
        ):
            self.assertEqual(doctor._resolve_default("api", "win32"), "/nope/present-api")

    def test_the_default_falls_back_to_the_canonical_path_when_none_exist(self) -> None:
        """With Resolve absent, the FAIL line should name the canonical location
        — that is the line the user is about to go looking for."""
        from unittest import mock

        with mock.patch.object(doctor.Path, "exists", lambda self: False):
            self.assertEqual(
                doctor._resolve_default("app", "win32"),
                doctor._RESOLVE_PATH_CANDIDATES["win32"]["app"][0],
            )


class NonDefaultInstallDiscoveryTests(unittest.TestCase):
    """Issue #158: Resolve installed off the conventional root.

    The reporter had Resolve on `D:\\Programs\\DaVinci Resolve`. Every candidate
    in the table missed, so doctor printed FAIL for a machine whose install
    install.py had already located. Discovery is consulted only after the table
    misses, so the existing "first existing candidate wins" behaviour above is
    untouched.
    """

    def test_lib_falls_back_to_runtime_discovery(self) -> None:
        from unittest import mock

        import src.utils.platform as platform_utils

        discovered = r"D:\Programs\DaVinci Resolve\fusionscript.dll"
        with mock.patch.object(
            doctor.Path, "exists", lambda self: str(self) == discovered
        ), mock.patch.object(
            platform_utils, "discover_scripting_lib", lambda *a, **k: discovered
        ):
            self.assertEqual(doctor._resolve_default("lib", "win32"), discovered)

    def test_app_falls_back_to_the_running_process(self) -> None:
        from unittest import mock

        import src.utils.resolve_runtime as runtime

        executable = r"D:\Programs\DaVinci Resolve\Resolve.exe"
        with mock.patch.object(
            doctor.Path, "exists", lambda self: str(self) == executable
        ), mock.patch.object(
            runtime, "resolve_processes", lambda: [f'"{executable}" -nogui']
        ):
            self.assertEqual(doctor._resolve_default("app", "win32"), executable)

    def test_discovery_that_finds_nothing_still_names_the_canonical_path(self) -> None:
        """A miss must not turn into a second guess — the FAIL line should keep
        naming the location the user can go and check."""
        from unittest import mock

        import src.utils.platform as platform_utils

        with mock.patch.object(doctor.Path, "exists", lambda self: False), \
                mock.patch.object(platform_utils, "discover_scripting_lib", lambda *a, **k: None):
            self.assertEqual(
                doctor._resolve_default("lib", "win32"),
                doctor._RESOLVE_PATH_CANDIDATES["win32"]["lib"][0],
            )

    def test_a_broken_discovery_helper_does_not_crash_the_diagnostic(self) -> None:
        """doctor is what a user runs when things are already wrong. It must not
        be the thing that raises."""
        from unittest import mock

        import src.utils.platform as platform_utils

        def boom(*a, **k):
            raise RuntimeError("no process table")

        with mock.patch.object(doctor.Path, "exists", lambda self: False), \
                mock.patch.object(platform_utils, "discover_scripting_lib", boom):
            self.assertEqual(
                doctor._resolve_default("lib", "win32"),
                doctor._RESOLVE_PATH_CANDIDATES["win32"]["lib"][0],
            )


class EscapedPathMatchingTests(unittest.TestCase):
    """Issue #158: doctor reported `missing` on configs it had just written.

    A Windows path written into JSON comes back with its separators doubled, so
    the literal substring test could never match. This is a false negative in a
    tool whose whole job is telling the user whether setup worked.
    """

    def _write(self, text: str) -> Path:
        import tempfile

        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        handle.write(text)
        handle.close()
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        return Path(handle.name)

    def test_json_escaped_windows_path_matches_its_unescaped_needle(self) -> None:
        needle = r"C:\Users\sam\davinci-resolve-mcp\src\server.py"
        path = self._write(json.dumps({"args": [needle]}))
        # Round-tripping through json is the point: this is the escaping doctor
        # reads back off disk, not a hand-written approximation of it.
        self.assertIn("\\\\", path.read_text(encoding="utf-8"))
        ok, detail = doctor.file_contains(path, [needle])
        self.assertTrue(ok, detail)

    def test_single_escaped_path_also_matches(self) -> None:
        """TOML (Codex CLI) and hand-edited configs carry single backslashes."""
        needle = r"C:\Users\sam\davinci-resolve-mcp\src\server.py"
        path = self._write(f'command = "{needle}"')
        ok, detail = doctor.file_contains(path, [needle])
        self.assertTrue(ok, detail)

    def test_a_genuinely_absent_entry_is_still_reported_missing(self) -> None:
        """Normalizing separators must not soften the check into always-true."""
        path = self._write(json.dumps({"args": [r"C:\Users\someone-else\server.py"]}))
        ok, detail = doctor.file_contains(
            path, [r"C:\Users\sam\davinci-resolve-mcp\src\server.py"]
        )
        self.assertFalse(ok)
        self.assertIn("missing", detail)

    def test_posix_paths_are_unaffected(self) -> None:
        needle = "/Users/sam/davinci-resolve-mcp/src/server.py"
        path = self._write(json.dumps({"args": [needle]}))
        ok, detail = doctor.file_contains(path, [needle])
        self.assertTrue(ok, detail)


class InstallerDriftTests(unittest.TestCase):
    """doctor.py and install.py must not disagree about where Resolve lives."""

    def test_doctor_paths_are_a_subset_of_install_py(self) -> None:
        installer = _install_py_resolve_paths()
        for doctor_key, install_key in _PLATFORM_KEYS.items():
            entry = doctor._RESOLVE_PATH_CANDIDATES[doctor._platform_key(doctor_key)]
            for kind in ("app", "api", "lib"):
                known = set(installer[install_key][kind])
                for path in entry[kind]:
                    with self.subTest(platform=doctor_key, kind=kind, path=path):
                        self.assertIn(
                            path, known,
                            f"doctor.py names a {doctor_key} {kind} path install.py "
                            f"does not know about. One of the two is wrong — they "
                            f"describe the same install.",
                        )

    def test_install_py_still_defines_the_table_this_guard_reads(self) -> None:
        # If install.py's structure changes, the guard above silently passes on
        # an empty comparison. Fail loudly instead.
        installer = _install_py_resolve_paths()
        self.assertEqual(set(installer) & set(_PLATFORM_KEYS.values()), set(_PLATFORM_KEYS.values()))


class ClaudeDesktopConfigTests(unittest.TestCase):
    def test_windows_prefers_the_msix_virtualized_path(self) -> None:
        """Issue #93: Claude Desktop for Windows is an MSIX package whose
        %APPDATA% writes are virtualized, so `%APPDATA%\\Claude` is a decoy the
        app never reads. doctor must check the same path install.py writes."""
        import os
        import tempfile
        from unittest import mock

        local = Path(tempfile.mkdtemp(prefix="localappdata_"))
        virtual = local / "Packages" / "Claude_abc123def" / "LocalCache" / "Roaming" / "Claude"
        virtual.mkdir(parents=True)

        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch.dict(os.environ, {"LOCALAPPDATA": str(local)}):
            resolved = doctor._default_claude_config()
        self.assertEqual(resolved, virtual / "claude_desktop_config.json")

    def test_windows_falls_back_to_appdata_without_an_msix_package(self) -> None:
        import os
        import tempfile
        from unittest import mock

        local = Path(tempfile.mkdtemp(prefix="localappdata_"))
        appdata = Path(tempfile.mkdtemp(prefix="appdata_"))
        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch.dict(
                    os.environ,
                    {"LOCALAPPDATA": str(local), "APPDATA": str(appdata)},
                ):
            resolved = doctor._default_claude_config()
        self.assertEqual(resolved, appdata / "Claude" / "claude_desktop_config.json")

    def test_macos_config_path_is_unchanged(self) -> None:
        from unittest import mock

        with mock.patch.object(sys, "platform", "darwin"):
            resolved = doctor._default_claude_config()
        self.assertEqual(
            resolved,
            Path("~/Library/Application Support/Claude/claude_desktop_config.json").expanduser(),
        )


class ResolveProbeLifecycleTests(unittest.TestCase):
    def _layout(self, root: Path, helper: str, dvr: str) -> tuple[Path, Path]:
        repo = root / "repo"
        utils = repo / "src" / "utils"
        modules = root / "modules"
        utils.mkdir(parents=True)
        modules.mkdir()
        (repo / "src" / "__init__.py").write_text("", encoding="utf-8")
        (utils / "__init__.py").write_text("", encoding="utf-8")
        (utils / "resolve_connection.py").write_text(helper, encoding="utf-8")
        (modules / "DaVinciResolveScript.py").write_text(dvr, encoding="utf-8")
        return repo, modules

    def test_bridge_first_skips_native_fusion_import(self) -> None:
        import tempfile
        from unittest import mock

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo, modules = self._layout(
                root,
                "class Proxy:\n"
                " def GetProductName(self): return 'Bridge Resolve'\n"
                " def GetVersionString(self): return '1.0'\n"
                "def connect_resolve(dvr):\n"
                " assert dvr is None\n"
                " return Proxy()\n",
                "raise RuntimeError('native Fusion import must not happen')\n",
            )
            with mock.patch.object(doctor, "REPO", repo), mock.patch.object(
                doctor, "RESOLVE_MODULES", modules
            ), mock.patch.object(doctor, "PYTHON", Path(sys.executable)):
                probe = doctor.resolve_probe()

        self.assertTrue(probe["resolve_connected"])
        self.assertTrue(probe["import_skipped"])
        self.assertEqual(probe["transport"], "bridge")
        self.assertEqual(probe["returncode"], 0)

    def test_native_fallback_hard_exits_without_running_atexit(self) -> None:
        import tempfile
        from unittest import mock

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            finalized = root / "finalized.txt"
            repo, modules = self._layout(
                root,
                "def connect_resolve(dvr):\n"
                " return None if dvr is None else dvr.scriptapp('Resolve')\n",
                "import atexit\nfrom pathlib import Path\n"
                f"atexit.register(lambda: Path({str(finalized)!r}).write_text('ran'))\n"
                "class Proxy:\n"
                " def GetProductName(self): return 'Direct Resolve'\n"
                " def GetVersionString(self): return '1.0'\n"
                "def scriptapp(name): return Proxy()\n",
            )
            with mock.patch.object(doctor, "REPO", repo), mock.patch.object(
                doctor, "RESOLVE_MODULES", modules
            ), mock.patch.object(doctor, "PYTHON", Path(sys.executable)):
                probe = doctor.resolve_probe()

            self.assertTrue(probe["import_ok"])
            self.assertTrue(probe["resolve_connected"])
            self.assertEqual(probe["returncode"], 0)
            self.assertFalse(finalized.exists(), "native probe ran Python finalizers")


if __name__ == "__main__":
    unittest.main()
