"""A Python child process of the offline suite cannot reach DaVinci Resolve.

`offline_guard` swaps the server's entry points inside the test process, and
none of those swaps exists in a child. The control-panel tests start the real
`src/analysis_dashboard.py` through `server._open_control_panel`. Measured on
v4.8.4 with a tripwire standing in for the library, a full `unittest discover`
run made 6 `scriptapp("Resolve")` calls from 3 panel children, through
`_connect_resolve_read_only`. So the guard now exports `tests/offline_child_site`
on PYTHONPATH, and every Python child runs its `sitecustomize.py`.

The fakes here are shaped like Blackmagic's pair: `DaVinciResolveScript.py` is a
loader that hands over `fusionscript`, and `scriptapp` lives in `fusionscript`.
Both record to a file whenever they are imported or called, so a guard that
lets them load fails loudly instead of passing quietly. Nothing in this file can
reach the real library. The children that run without the guard have only the
fakes on PYTHONPATH, and the one launch this file attempts names a program in a
temp directory that does not exist.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from tests import offline_guard

SITE_FILE = Path(offline_guard.CHILD_SITE_DIR) / "sitecustomize.py"
RECORD_ENV = "OFFLINE_GUARD_TEST_RECORD"

FAKE_LOADER = """\
import os
import sys

with open(os.environ["OFFLINE_GUARD_TEST_RECORD"], "a") as fh:
    fh.write("imported DaVinciResolveScript\\n")

import fusionscript as script_module

sys.modules[__name__] = script_module
"""

FAKE_LIBRARY = """\
import os


def _record(line):
    with open(os.environ["OFFLINE_GUARD_TEST_RECORD"], "a") as fh:
        fh.write(line + "\\n")


_record("imported fusionscript")


def scriptapp(*args):
    _record("scriptapp %r" % (args,))
    return None
"""

#: Reports what `import` hands back for each name, and what calling `scriptapp` does.
PROBE = """\
import json
import sys

report = {}
for name in ("DaVinciResolveScript", "fusionscript"):
    module = __import__(name)
    sys.modules.pop(name, None)  # the next import must be answered again
    again = __import__(name)
    try:
        module.scriptapp("Resolve")
        error = None
    except AttributeError as exc:
        error = str(exc)
    report[name] = {
        "stub": bool(getattr(module, "__resolve_offline_guard_stub__", False)),
        "stub_after_pop": bool(getattr(again, "__resolve_offline_guard_stub__", False)),
        "error": error,
    }
print(json.dumps(report))
"""


def _load_site_module():
    """The guard's `sitecustomize.py` under another name, so nothing gets installed."""
    spec = importlib.util.spec_from_file_location("offline_child_site_under_test", SITE_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeResolveTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="offline-child-guard-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.fakes = self.tmp / "fakes"
        self.fakes.mkdir()
        (self.fakes / "DaVinciResolveScript.py").write_text(FAKE_LOADER, encoding="utf-8")
        (self.fakes / "fusionscript.py").write_text(FAKE_LIBRARY, encoding="utf-8")
        self.record = self.tmp / "record.txt"

    def recorded(self) -> list:
        if not self.record.exists():
            return []
        return self.record.read_text(encoding="utf-8").splitlines()

    def child_env(self, *pythonpath) -> dict:
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(str(entry) for entry in pythonpath)
        env[RECORD_ENV] = str(self.record)
        env.pop("DAVINCI_RESOLVE_BRIDGE", None)
        return env

    def run_child(self, code: str, *pythonpath) -> subprocess.CompletedProcess:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            env=self.child_env(*pythonpath),
            cwd=str(self.tmp),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc


class ExportedEnvironmentTests(unittest.TestCase):
    """What every child of this run inherits."""

    def test_the_guard_directory_is_first_on_pythonpath(self) -> None:
        entries = os.environ.get("PYTHONPATH", "").split(os.pathsep)
        self.assertEqual(entries[0], offline_guard.CHILD_SITE_DIR)
        self.assertTrue(SITE_FILE.is_file())

    def test_the_bridge_config_children_inherit_does_not_exist(self) -> None:
        if offline_guard.SKIPPED_REASON:
            self.skipTest(offline_guard.SKIPPED_REASON)
        path = os.environ.get("DAVINCI_RESOLVE_BRIDGE_CONFIG")
        self.assertTrue(path)
        self.assertFalse(os.path.exists(path), path)

    def test_install_is_idempotent_and_uninstall_restores_pythonpath(self) -> None:
        with mock.patch.dict(os.environ, {"PYTHONPATH": os.pathsep.join(["a", "b"])}), \
                mock.patch.dict(offline_guard._originals, clear=True):
            offline_guard._guard_child_processes()
            offline_guard._guard_child_processes()
            self.assertEqual(
                os.environ["PYTHONPATH"].split(os.pathsep), [offline_guard.CHILD_SITE_DIR, "a", "b"]
            )
            offline_guard._unguard_child_processes()
            self.assertEqual(os.environ["PYTHONPATH"], os.pathsep.join(["a", "b"]))

        with mock.patch.dict(os.environ), mock.patch.dict(offline_guard._originals, clear=True):
            os.environ.pop("PYTHONPATH", None)
            offline_guard._guard_child_processes()
            self.assertEqual(os.environ["PYTHONPATH"], offline_guard.CHILD_SITE_DIR)
            offline_guard._unguard_child_processes()
            self.assertNotIn("PYTHONPATH", os.environ)

    def test_the_child_copy_of_the_stand_in_matches_the_in_process_one(self) -> None:
        """`sitecustomize.py` cannot import `offline_guard`, so it repeats these."""
        site = _load_site_module()
        self.assertEqual(site.SCRIPTING_MODULES, offline_guard.SCRIPTING_MODULES)
        self.assertEqual(site.STUB_MARKER, offline_guard.STUB_MARKER)
        # The finder attribute `scripting_stub_installed()` looks for.
        self.assertTrue(getattr(offline_guard._ScriptingModuleStub, site.GUARD_MARKER))


class ScriptingModulesInAChildTests(_FakeResolveTestCase):
    def test_without_the_guard_a_child_reaches_the_fake_scriptapp(self) -> None:
        """The control. Without it, an empty record below could mean broken fakes."""
        self.run_child("import DaVinciResolveScript as d; d.scriptapp('Resolve')", self.fakes)
        self.assertEqual(
            self.recorded(),
            ["imported DaVinciResolveScript", "imported fusionscript", "scriptapp ('Resolve',)"],
        )

    def test_with_the_guard_both_modules_are_the_stand_in(self) -> None:
        proc = self.run_child(PROBE, offline_guard.CHILD_SITE_DIR, self.fakes)
        report = json.loads(proc.stdout)
        for name in ("DaVinciResolveScript", "fusionscript"):
            with self.subTest(name=name):
                self.assertTrue(report[name]["stub"], report)
                self.assertTrue(report[name]["stub_after_pop"], report)
                self.assertIn("offline test guard", report[name]["error"])
                self.assertIn("'scriptapp'", report[name]["error"])
        self.assertEqual(self.recorded(), [], "a fake on PYTHONPATH was loaded past the guard")


#: Shaped like a developer's tripwire, and like the one this file was verified
#: behind: records that it ran, runs "the next sitecustomize that is not me" (so it
#: does not hide the interpreter's own either), then puts its own finder first.
CHAINING_SITECUSTOMIZE = """\
import importlib.machinery
import importlib.util
import os
import sys

with open(os.environ["OFFLINE_GUARD_TEST_RECORD"], "a") as fh:
    fh.write("%(name)s ran\\n")

here = os.path.dirname(os.path.abspath(__file__))
rest = [p for p in sys.path if os.path.abspath(p or os.curdir) != here]
spec = importlib.machinery.PathFinder.find_spec("sitecustomize", rest)
if %(chains)r and spec is not None:
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


class Finder:
    def find_spec(self, name, path=None, target=None):
        return None


sys.meta_path.insert(0, Finder())
"""

#: What a child reports about who answers `import DaVinciResolveScript`.
WHO_ANSWERS = (
    "import json, sys, DaVinciResolveScript as d\n"
    "print(json.dumps([bool(getattr(d, '__resolve_offline_guard_stub__', False)),"
    " bool(getattr(sys.meta_path[0], 'resolve_offline_guard', False))]))"
)


class ShadowedSitecustomizeTests(_FakeResolveTestCase):
    """Python loads only the first `sitecustomize`; the guard must not cost the one it hides."""

    def sitecustomize(self, name: str, chains: bool) -> Path:
        directory = self.tmp / name
        directory.mkdir()
        (directory / "sitecustomize.py").write_text(
            CHAINING_SITECUSTOMIZE % {"name": name, "chains": chains}, encoding="utf-8"
        )
        return directory

    def run_guarded(self, *pythonpath) -> subprocess.CompletedProcess:
        proc = self.run_child(WHO_ANSWERS, offline_guard.CHILD_SITE_DIR, *pythonpath)
        self.assertEqual(json.loads(proc.stdout), [True, True], "the guard is not in front")
        self.assertNotIn("Error in sitecustomize", proc.stderr)
        return proc

    def test_the_shadowed_sitecustomize_runs_and_the_guard_stays_in_front(self) -> None:
        self.run_guarded(self.sitecustomize("other", chains=False))
        self.assertEqual(self.recorded(), ["other ran"])

    def test_one_that_chains_back_to_the_guard_reaches_the_file_after_it(self) -> None:
        """The loop that was measured: two files each running "the next one that is
        not me" ran into each other until RecursionError, and the tripwire, not the
        guard, ended up answering the import."""
        self.run_guarded(self.sitecustomize("tripwire", chains=True), self.sitecustomize("interpreter", chains=False))
        self.assertEqual(self.recorded(), ["tripwire ran", "interpreter ran"])

    def test_a_second_copy_of_the_guard_does_not_chain_into_this_one(self) -> None:
        copy = self.tmp / "other-checkout" / "offline_child_site"
        copy.mkdir(parents=True)
        shutil.copy(SITE_FILE, copy / "sitecustomize.py")
        self.run_guarded(copy, self.sitecustomize("other", chains=True))
        self.assertEqual(self.recorded(), ["other ran"])


class LaunchGuardTests(_FakeResolveTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.site = _load_site_module()

    def test_the_launch_commands_the_server_builds_are_refused(self) -> None:
        from src.utils import resolve_runtime

        for system in ("Darwin", "Windows", "Linux"):
            for headless in (False, True):
                with self.subTest(system=system, headless=headless), \
                        mock.patch.object(resolve_runtime.platform, "system", return_value=system), \
                        mock.patch.object(resolve_runtime.os.path, "exists", return_value=True):
                    command = resolve_runtime.launch_command(headless)
                self.assertTrue(command, (system, headless))
                self.assertTrue(self.site.launches_resolve(command), command)

    def test_other_ways_to_start_the_application_are_refused(self) -> None:
        for args, executable in (
            (["open", "-a", "DaVinci Resolve"], None),
            (["/usr/bin/open", "-b", "com.blackmagic-design.DaVinciResolve"], None),
            (["osascript", "-e", 'tell application "DaVinci Resolve" to activate'], None),
            ("open '/Applications/DaVinci Resolve.app'", None),
            (["/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fuscript"], None),
            ([r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fuscript.exe"], None),
            (["/opt/resolve/libs/Fusion/fuscript"], None),
            (["renamed"], "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/MacOS/Resolve"),
        ):
            with self.subTest(args=args):
                self.assertTrue(self.site.launches_resolve(args, executable))

    def test_ordinary_children_still_run(self) -> None:
        for args in (
            [sys.executable, "-c", "print('/Applications/DaVinci Resolve/DaVinci Resolve.app')"],
            ["/Users/me/DaVinci Resolve Scripts/davinci-resolve-mcp/venv/bin/python", "-m", "src.analysis_dashboard"],
            [r"C:\Users\me\DaVinci Resolve\venv\Scripts\python.exe"],
            ["open", "http://127.0.0.1:8765/#token=abc"],
            ["lsof", "-nP", "-iTCP:8765", "-sTCP:LISTEN", "-t"],
        ):
            with self.subTest(args=args):
                self.assertFalse(self.site.launches_resolve(args))

    def test_a_guarded_child_refuses_before_anything_starts(self) -> None:
        # A bundle-shaped path in the temp directory with no program in it. If the
        # guard failed, Popen would raise FileNotFoundError, not start anything.
        # Passed in the environment rather than argv, so a developer's tripwire that
        # refuses any command line naming the bundle does not refuse this child.
        program = self.tmp / "DaVinci Resolve.app" / "Contents" / "MacOS" / "Resolve"
        with mock.patch.dict(os.environ, {"OFFLINE_GUARD_TEST_PROGRAM": str(program)}):
            proc = self.run_child(
                "import os, subprocess\n"
                "try:\n"
                "    subprocess.Popen([os.environ['OFFLINE_GUARD_TEST_PROGRAM'], '-nogui'])\n"
                "except PermissionError as exc:\n"
                "    print(exc)\n",
                offline_guard.CHILD_SITE_DIR,
            )
        self.assertIn("offline test guard refuses to launch DaVinci Resolve", proc.stdout)


class ControlPanelChildTests(_FakeResolveTestCase):
    """The case that was measured: the real panel, started the way the tests start it."""

    def setUp(self) -> None:
        super().setUp()
        if offline_guard.SKIPPED_REASON:
            self.skipTest(offline_guard.SKIPPED_REASON)
        from src import server

        self.server = server
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        env = mock.patch.dict(os.environ, {
            # The launcher writes its log under ~/Documents; keep it in the sandbox.
            "HOME": str(self.tmp),
            "USERPROFILE": str(self.tmp),
            # Behind the guard, so a guard that is not inherited lets the panel load them.
            "PYTHONPATH": os.pathsep.join([os.environ.get("PYTHONPATH", ""), str(self.fakes)]),
            RECORD_ENV: str(self.record),
        })
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("DAVINCI_RESOLVE_BRIDGE", None)  # restored by env.stop
        for target, value in (
            ("_control_panel_pidfile", str(self.tmp / "control_panel.json")),
            ("_port_owner_pid", None),
        ):
            patcher = mock.patch.object(server, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _stop(self, pid: int) -> None:
        """Terminate the panel and wait until it is gone, so its record is final.

        This process started the panel, so it has to reap it: `os.kill(pid, 0)`
        keeps succeeding on a zombie, and nothing else holds the `Popen` object.
        """
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return
        if not hasattr(os, "WNOHANG"):
            return
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                if os.waitpid(pid, os.WNOHANG)[0]:
                    return
            except ChildProcessError:
                return  # already reaped
            time.sleep(0.05)

    def test_the_panel_meets_the_stand_in_and_never_loads_blackmagics_module(self) -> None:
        result = self.server._open_control_panel({
            "host": "127.0.0.1",
            "port": self.port,
            "analysis_root": str(self.tmp / "analysis"),
        })
        self.assertTrue(result.get("success"), result)
        self.addCleanup(self._stop, result["pid"])

        token = result["url"].split("#token=", 1)[1]
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/boot",
            headers={"Authorization": f"Bearer {token}"},
        )
        # The first /api/boot is slow (cold inventory warm-up), so be patient.
        with urllib.request.urlopen(request, timeout=60) as response:
            boot = json.loads(response.read().decode("utf-8"))
        self._stop(result["pid"])

        # The panel's own report proves its connect path ran and met the stand-in.
        # A guard that was never inherited would load the fakes instead, and the
        # panel would report "not connected" with a scriptapp call in the record.
        resolve = boot["resolve"]
        self.assertFalse(resolve["available"], resolve)
        self.assertIn("offline test guard", resolve["error"])
        self.assertIn("'scriptapp'", resolve["error"])
        self.assertEqual(self.recorded(), [], "the panel loaded Blackmagic's module past the guard")


if __name__ == "__main__":
    unittest.main()
