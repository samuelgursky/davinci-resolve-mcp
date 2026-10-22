"""doctor's Python-environment checks: bitness, version-for-this-Resolve, which Python.

Every interpreter here is a fake. A scripted runner answers the probe for each
path, and library headers are a few synthetic bytes, so nothing depends on the
Pythons or the Resolve install of the machine running the suite. The real
machine is what `python scripts/doctor.py` is for.

Each check has a null control: a clean 64-bit 3.12 setup must come back with no
WARN and no FAIL. Without it a check that warns on everything would pass every
failure-mode test below.
"""

from __future__ import annotations

import json
import os
import plistlib
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import doctor_python_env as env  # noqa: E402


# ─── Fakes ────────────────────────────────────────────────────────────────────

def _payload(version=(3, 12, 4), bits=64, machine="arm64", platform="macosx-11.0-arm64",
             executable=None, prefix="/base"):
    return {
        "version": list(version), "bits": bits, "machine": machine,
        "platform": platform, "executable": executable, "prefix": prefix,
    }


def fake_runner(table: dict):
    """A runner whose answer for `[path, ...]` is `table[path]`.

    A dict answers the probe; a string is an error on stderr; a missing path is
    "no such file". Records every command it was asked to run.
    """
    calls = []

    def run(cmd):
        calls.append(cmd)
        answer = table.get(cmd[0])
        if answer is None:
            return {"returncode": None, "stdout": "", "stderr": f"[Errno 2] No such file: {cmd[0]}"}
        if isinstance(answer, str):
            return {"returncode": 1, "stdout": "", "stderr": answer}
        return {"returncode": 0, "stdout": json.dumps(answer) + "\n", "stderr": ""}

    run.calls = calls
    return run


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def elf(machine: int, bits: int = 64) -> bytes:
    head = bytearray(64)
    head[:4] = b"\x7fELF"
    head[4] = 2 if bits == 64 else 1
    head[5] = 1  # little-endian
    struct.pack_into("<H", head, 18, machine)
    return bytes(head)


def macho_thin(cpu: int) -> bytes:
    return struct.pack("<Ii", 0xFEEDFACF, cpu) + bytes(24)


def macho_fat(*cpus: int) -> bytes:
    data = struct.pack(">II", 0xCAFEBABE, len(cpus))
    for cpu in cpus:
        data += struct.pack(">iiIII", cpu, 0, 0, 0, 0)
    return data + bytes(64)


def pe(machine: int) -> bytes:
    head = bytearray(256)
    head[:2] = b"MZ"
    struct.pack_into("<I", head, 0x3C, 0x80)
    head[0x80:0x84] = b"PE\x00\x00"
    struct.pack_into("<H", head, 0x84, machine)
    return bytes(head)


X86_64, ARM64 = 0x01000007, 0x0100000C
REPO_FAKE = Path("/fake/repo")
VENV_PY = str(REPO_FAKE / "venv" / "bin" / "python")


def statuses(results):
    return {item["name"]: item["status"] for item in results}


# ─── Library headers ──────────────────────────────────────────────────────────

class LibraryArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="doctor_lib_"))

    def arch(self, data: bytes):
        return env.library_architectures(_write(self.tmp / "lib", data))

    def test_linux_elf(self):
        self.assertEqual(self.arch(elf(0x3E)), (["x86_64"], None))
        self.assertEqual(self.arch(elf(0xB7)), (["arm64"], None))

    def test_macos_thin_and_universal(self):
        self.assertEqual(self.arch(macho_thin(ARM64)), (["arm64"], None))
        self.assertEqual(self.arch(macho_fat(X86_64, ARM64)), (["x86_64", "arm64"], None))

    def test_windows_pe(self):
        self.assertEqual(self.arch(pe(0x8664)), (["x86_64"], None))
        self.assertEqual(self.arch(pe(0x014C)), (["x86"], None))

    def test_a_non_library_and_a_missing_file_give_a_reason_not_a_guess(self):
        archs, reason = self.arch(b"#!/bin/sh\necho hi\n")
        self.assertIsNone(archs)
        self.assertIn("not a recognised native library", reason)
        archs, reason = env.library_architectures(self.tmp / "absent")
        self.assertIsNone(archs)
        self.assertIn("cannot read", reason)


class InterpreterArchTests(unittest.TestCase):
    def test_windows_reads_the_build_not_the_os(self):
        # A 32-bit Python on 64-bit Windows: platform.machine() says AMD64.
        info = {"platform": "win32", "machine": "AMD64", "bits": 32}
        self.assertEqual(env.interpreter_arch(info), "x86")
        self.assertEqual(env.interpreter_arch({"platform": "win-amd64", "machine": "AMD64", "bits": 64}), "x86_64")
        self.assertEqual(env.interpreter_arch({"platform": "win-arm64", "machine": "ARM64", "bits": 64}), "arm64")

    def test_posix_uses_the_process_machine(self):
        self.assertEqual(env.interpreter_arch({"platform": "macosx-10.9-universal2", "machine": "x86_64", "bits": 64}), "x86_64")
        self.assertEqual(env.interpreter_arch({"platform": "linux-aarch64", "machine": "aarch64", "bits": 64}), "arm64")
        self.assertEqual(env.interpreter_arch({"platform": "linux-x86_64", "machine": "x86_64", "bits": 32}), "x86")


class ProbeInterpreterTests(unittest.TestCase):
    def test_reads_the_payload(self):
        runner = fake_runner({"/py": _payload(version=(3, 11, 9), machine="x86_64")})
        info = env.probe_interpreter("/py", runner)
        self.assertEqual(info["version"], (3, 11, 9))
        self.assertEqual(info["arch"], "x86_64")
        self.assertNotIn("error", info)
        # Isolated from PYTHONPATH / PYTHONHOME and the user's site-packages.
        self.assertEqual(runner.calls[0][1:3], ["-E", "-s"])

    def test_an_interpreter_that_will_not_run_is_an_error_not_a_crash(self):
        info = env.probe_interpreter("/py", fake_runner({"/py": "SyntaxError: invalid syntax"}))
        self.assertEqual(info["error"], "SyntaxError: invalid syntax")
        self.assertIn("No such file", env.probe_interpreter("/gone", fake_runner({}))["error"])


# ─── Check 1: bitness ─────────────────────────────────────────────────────────

class BitnessTests(unittest.TestCase):
    def server(self, **kw):
        payload = _payload(**kw)
        info = {"path": VENV_PY, **payload, "version": tuple(payload["version"])}
        info["arch"] = env.interpreter_arch(info)
        return info

    def test_null_control_64_bit_matching_library_passes(self):
        result = env.check_bitness(self.server(), Path("/lib"), ["x86_64", "arm64"], None, REPO_FAKE, "darwin")
        self.assertEqual(result["status"], "OK")
        self.assertNotIn("fix", result)
        self.assertIn("universal", result["detail"])

    def test_32_bit_python_fails_with_the_venv_rebuild(self):
        server = self.server(bits=32, machine="AMD64", platform="win32")
        server["path"] = str(REPO_FAKE / "venv" / "Scripts" / "python.exe")
        result = env.check_bitness(server, Path("/lib"), ["x86_64"], None, REPO_FAKE, "win32")
        self.assertEqual(result["status"], "FAIL")
        # The 32-bit diagnosis itself, not the architecture-mismatch one that
        # would also fire for an x86 interpreter against an x86_64 library.
        self.assertIn("64-bit only", result["detail"])
        self.assertIn('move "', result["fix"])
        self.assertIn("py -3.12", result["fix"])
        self.assertIn("64-bit", result["fix"])

    def test_intel_python_under_rosetta_against_arm64_only_library_fails(self):
        server = self.server(machine="x86_64")
        result = env.check_bitness(server, Path("/fusionscript.so"), ["arm64"], None, REPO_FAKE, "darwin")
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("cannot load a library of another architecture", result["detail"])
        self.assertIn("Rosetta", result["detail"])
        self.assertIn("native arm64", result["fix"])
        self.assertIn(f'mv "{REPO_FAKE / "venv"}"', result["fix"])

    def test_unreadable_library_is_info_not_a_false_fail(self):
        result = env.check_bitness(self.server(), Path("/lib"), None, "cannot read /lib", REPO_FAKE, "darwin")
        self.assertEqual(result["status"], "INFO")
        self.assertIn("unchecked", result["detail"])

    def test_a_python_that_will_not_run_fails(self):
        server = {"path": VENV_PY, "error": "exited with 1"}
        result = env.check_bitness(server, Path("/lib"), ["arm64"], None, REPO_FAKE, "darwin")
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("fix", result)


# ─── Check 2: version for this Resolve ────────────────────────────────────────

class VersionTests(unittest.TestCase):
    def check(self, version, resolve=None, probe=None, lib_exists=True):
        server = {"path": VENV_PY, "version": version, "bits": 64}
        return env.check_version(server, resolve, probe or {}, lib_exists, REPO_FAKE, "darwin")

    def test_null_control_3_12_passes_on_any_resolve(self):
        for resolve in (None, (19, 1, 3), (21, 0)):
            with self.subTest(resolve=resolve):
                result = self.check((3, 12, 4), resolve)
                self.assertEqual(result["status"], "OK")
                self.assertNotIn("fix", result)

    def test_below_the_sdk_floor_fails(self):
        result = self.check((3, 9, 6), (20, 3, 2))
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("3.10", result["detail"])
        self.assertIn("python3.12", result["fix"])

    def test_3_13_on_an_older_resolve_warns_with_a_conditional_fix(self):
        result = self.check((3, 13, 1), (19, 1, 3))
        self.assertEqual(result["status"], "WARN")
        self.assertIn("Resolve 19.1.3", result["detail"])
        self.assertTrue(result["fix"].startswith("If Resolve is running"))

    def test_3_13_with_an_unknown_resolve_still_warns(self):
        self.assertEqual(self.check((3, 14, 0), None)["status"], "WARN")

    def test_3_13_on_a_verified_resolve_passes(self):
        self.assertEqual(self.check((3, 14, 0), (20, 3, 2))["status"], "OK")
        self.assertEqual(self.check((3, 14, 0), (21, 0))["status"], "OK")
        # 20.3.0 predates the verified build.
        self.assertEqual(self.check((3, 14, 0), (20, 3, 0))["status"], "WARN")

    def test_3_13_that_resolve_answered_on_passes(self):
        probe = {"import_ok": True, "resolve_connected": True, "version": "19.1.3.7"}
        self.assertEqual(self.check((3, 13, 1), (19, 1, 3), probe)["status"], "OK")

    def test_a_bridge_answer_says_nothing_about_this_interpreter(self):
        probe = {"import_skipped": True, "resolve_connected": True, "transport": "bridge"}
        self.assertEqual(self.check((3, 13, 1), (19, 1, 3), probe)["status"], "WARN")

    def test_3_13_that_cannot_import_an_existing_library_fails(self):
        probe = {"import_ok": False, "error": "ImportError: dlopen(...): symbol not found"}
        result = self.check((3, 13, 1), (19, 1, 3), probe)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("fix", result)

    def test_a_missing_module_is_not_blamed_on_the_python_version(self):
        probe = {"import_ok": False, "error": "ModuleNotFoundError: No module named 'DaVinciResolveScript'"}
        self.assertEqual(self.check((3, 13, 1), (19, 1, 3), probe)["status"], "WARN")


# ─── Check 3: which Python ────────────────────────────────────────────────────

def probed(path, name="python3", **kw):
    payload = _payload(**kw)
    info = {"path": path, "name": name, **payload, "version": tuple(payload["version"])}
    info["arch"] = env.interpreter_arch(info)
    return info


class InterpreterTests(unittest.TestCase):
    def setUp(self):
        self.server = probed(VENV_PY, prefix=str(REPO_FAKE / "venv"))

    def run_check(self, on_path, clients, menu=None, platform="darwin"):
        return env.check_interpreters(self.server, on_path, clients, menu, platform)

    def test_null_control_one_python_absolute_client_passes(self):
        clients = [{"client": "Claude Desktop", "entry": "davinci-resolve", "command": VENV_PY, "info": self.server}]
        results = self.run_check([self.server], clients, {"path": "/usr/local/bin/python3", "source": "/usr/local/bin/python3"})
        found = statuses(results)
        self.assertEqual(found["Claude Desktop interpreter"], "OK")
        self.assertEqual(found["Pythons on PATH"], "OK")
        self.assertNotIn("WARN", found.values())
        self.assertNotIn("FAIL", found.values())
        where = next(r for r in results if r["name"] == "Where fusionscript loads")
        self.assertIn(VENV_PY, where["detail"])
        self.assertIn("/usr/local/bin/python3", where["detail"])

    def test_a_bare_client_command_warns_with_the_absolute_path(self):
        clients = [{"client": "Claude Desktop", "entry": "davinci-resolve", "command": "python3"}]
        other = probed("/opt/homebrew/bin/python3", version=(3, 13, 0), prefix="/opt/homebrew")
        results = self.run_check([other, self.server], clients)
        client = next(r for r in results if r["name"] == "Claude Desktop interpreter")
        self.assertEqual(client["status"], "WARN")
        self.assertIn("looked up on the PATH", client["detail"])
        self.assertIn(f"to the absolute path {VENV_PY}", client["fix"])
        self.assertEqual(statuses(results)["Pythons on PATH"], "WARN")

    def test_a_client_running_a_different_absolute_python_warns(self):
        other = probed("/usr/bin/python3", version=(3, 9, 6), prefix="/usr")
        clients = [{"client": "Codex", "entry": "resolve", "command": "/usr/bin/python3", "info": other}]
        client = next(r for r in self.run_check([self.server], clients) if r["name"] == "Codex interpreter")
        self.assertEqual(client["status"], "WARN")
        self.assertIn("3.9.6", client["detail"])
        self.assertIn("DAVINCI_MCP_PYTHON=/usr/bin/python3", client["fix"])

    def test_several_pythons_with_absolute_clients_is_info_naming_the_server(self):
        other = probed("/opt/homebrew/bin/python3", version=(3, 13, 0), prefix="/opt/homebrew")
        clients = [{"client": "Claude Desktop", "entry": "d", "command": VENV_PY, "info": self.server}]
        result = next(r for r in self.run_check([other, self.server], clients) if r["name"] == "Pythons on PATH")
        self.assertEqual(result["status"], "INFO")
        self.assertIn("/opt/homebrew/bin/python3", result["detail"])
        self.assertIn(f'"{VENV_PY}" -c "import DaVinciResolveScript"', result["detail"])
        self.assertIn("[runs the server]", result["detail"])

    def test_a_32_bit_python_first_on_path_warns(self):
        stray = probed(r"C:\Python312-32\python.exe", name="python.exe", bits=32, machine="AMD64", platform="win32", prefix=r"C:\Python312-32")
        result = next(r for r in self.run_check([stray, self.server], [], platform="win32") if r["name"] == "Pythons on PATH")
        self.assertEqual(result["status"], "WARN")
        self.assertIn("32-bit", result["detail"])

    def test_the_windows_store_alias_is_named(self):
        stub = {"path": r"C:\Users\u\AppData\Local\Microsoft\WindowsApps\python.exe", "name": "python.exe", "error": "exited with 9009"}
        found = statuses(self.run_check([stub, self.server], [], platform="win32"))
        self.assertEqual(found["Microsoft Store python alias"], "WARN")

    def test_a_venv_and_its_base_interpreter_are_different_pythons(self):
        # Same binary on disk, different sys.prefix: different installed packages.
        with mock.patch.object(env, "_real", lambda path: "/base/bin/python3.12"):
            base = probed("/base/bin/python3", prefix="/base")
            self.assertFalse(env.same_interpreter(base, self.server))
            twin = probed(str(REPO_FAKE / "venv" / "bin" / "python3"), prefix=str(REPO_FAKE / "venv"))
            self.assertTrue(env.same_interpreter(twin, self.server))
            self.assertEqual(len(env.dedupe_interpreters([base, twin, self.server])), 2)


class DiscoveryTests(unittest.TestCase):
    def test_pythons_on_path_in_order(self):
        tmp = Path(tempfile.mkdtemp(prefix="doctor_path_"))
        first, second, empty = tmp / "a", tmp / "b", tmp / "c"
        for directory in (first, second, empty):
            directory.mkdir()
        _write(first / "python3", b"")
        _write(second / "python3", b"")
        _write(second / "python", b"")
        path_value = os.pathsep.join([str(first), str(empty), "", str(second), str(first)])
        found = env.pythons_on_path(path_value, "darwin")
        self.assertEqual(
            [item["path"] for item in found],
            [str(first / "python3"), str(second / "python3"), str(second / "python")],
        )

    def test_windows_looks_for_exe(self):
        seen = []
        env.pythons_on_path("/py", "win32", is_file=lambda p: seen.append(p.name) or False)
        self.assertEqual(seen, ["python.exe", "python3.exe"])

    def test_client_commands_only_for_this_server(self):
        tmp = Path(tempfile.mkdtemp(prefix="doctor_cfg_"))
        claude = _write(tmp / "claude.json", json.dumps({"mcpServers": {
            "davinci-resolve": {"command": VENV_PY, "args": ["/fake/repo/src/server.py"]},
            "other": {"command": "node", "args": ["other.js"]},
        }}).encode())
        codex = _write(tmp / "config.toml", (
            '[mcp_servers.resolve]\ncommand = "python3"\nargs = ["/fake/repo/src/server.py"]\n'
        ).encode())
        commands = env.client_python_commands(claude, codex)
        self.assertIn({"client": "Claude Desktop", "entry": "davinci-resolve", "command": VENV_PY}, commands)
        self.assertNotIn("node", [c["command"] for c in commands])
        try:
            import tomllib  # noqa: F401
        except ImportError:
            return
        self.assertIn({"client": "Codex", "entry": "resolve", "command": "python3"}, commands)

    def test_missing_or_broken_configs_are_skipped(self):
        tmp = Path(tempfile.mkdtemp(prefix="doctor_cfg_"))
        broken = _write(tmp / "claude.json", b"{not json")
        self.assertEqual(env.client_python_commands(broken, tmp / "absent.toml"), [])

    def test_resolve_version_from_the_app_bundle(self):
        app = Path(tempfile.mkdtemp(prefix="doctor_app_")) / "DaVinci Resolve.app"
        (app / "Contents").mkdir(parents=True)
        with open(app / "Contents" / "Info.plist", "wb") as handle:
            plistlib.dump({"CFBundleShortVersionString": "19.1.3"}, handle)
        self.assertEqual(env.resolve_app_version(app), (19, 1, 3))
        self.assertIsNone(env.resolve_app_version(app.parent / "missing.app"))
        self.assertEqual(env.parse_version("21.0.4.5"), (21, 0, 4, 5))
        self.assertEqual(env.parse_version("20.3b2"), (20, 3))
        self.assertIsNone(env.parse_version(""))

    def test_fix_outside_a_venv_points_at_no_venv(self):
        fix = env.rebuild_fix("/usr/bin/python3", REPO_FAKE, "linux")
        self.assertIn("--no-venv --python", fix)
        self.assertNotIn("mv ", fix)


# ─── End to end through collect() ─────────────────────────────────────────────

class CollectTests(unittest.TestCase):
    """The whole pipeline on fakes: runner, PATH, configs and library header."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="doctor_collect_"))
        self.repo = self.tmp / "repo"
        self.venv_py = self.repo / "venv" / "bin" / "python"
        _write(self.venv_py, b"")
        self.lib = _write(self.tmp / "fusionscript.so", macho_fat(X86_64, ARM64))
        self.claude = _write(self.tmp / "claude.json", json.dumps({"mcpServers": {
            "davinci-resolve": {"command": str(self.venv_py), "args": [str(self.repo / "src" / "server.py")]},
        }}).encode())

    def collect(self, table, path_value="", probe=None, lib=None, claude=None):
        return env.collect(
            server_python=self.venv_py, lib_path=lib or self.lib, app_path=self.tmp / "none.app",
            repo=self.repo, probe=probe or {}, claude_config=claude or self.claude,
            codex_config=self.tmp / "absent.toml", platform="darwin",
            runner=fake_runner(table), path_value=path_value,
            menu_python={"path": "/usr/local/bin/python3", "source": "/usr/local/bin/python3"},
        )

    def test_null_control_a_clean_setup_has_no_warn_or_fail(self):
        results = self.collect({str(self.venv_py): _payload(prefix=str(self.repo / "venv"))},
                               path_value=str(self.venv_py.parent))
        found = statuses(results)
        self.assertEqual(found["Python bitness"], "OK")
        self.assertEqual(found["Python version for Resolve"], "OK")
        self.assertEqual(found["Claude Desktop interpreter"], "OK")
        self.assertEqual(found["Pythons on PATH"], "OK")
        bad = [r for r in results if r["status"] in ("WARN", "FAIL")]
        self.assertEqual(bad, [])

    def test_failure_modes_each_surface_with_a_fix(self):
        cases = {
            "32-bit": ({str(self.venv_py): _payload(bits=32, machine="x86_64")}, "Python bitness", "FAIL", "64-bit only"),
            "rosetta": ({str(self.venv_py): _payload(machine="x86_64")}, "Python bitness", "FAIL", "Rosetta"),
            "too old": ({str(self.venv_py): _payload(version=(3, 9, 6))}, "Python version for Resolve", "FAIL", "SDK's floor"),
            "too new": ({str(self.venv_py): _payload(version=(3, 14, 0))}, "Python version for Resolve", "WARN", "verified on Resolve 20.3.2"),
        }
        lib = _write(self.tmp / "arm64-only.so", macho_thin(ARM64))
        for label, (table, name, status, phrase) in cases.items():
            with self.subTest(label):
                result = next(r for r in self.collect(table, lib=lib) if r["name"] == name)
                self.assertEqual(result["status"], status)
                self.assertIn(phrase, result["detail"])
                self.assertTrue(result.get("fix"))

    def test_several_pythons_and_a_bare_client_command(self):
        homebrew = self.tmp / "homebrew" / "bin"
        _write(homebrew / "python3", b"")
        claude = _write(self.tmp / "bare.json", json.dumps({"mcpServers": {
            "davinci-resolve": {"command": "python3", "args": [str(self.repo / "src" / "server.py")]},
        }}).encode())
        table = {
            str(self.venv_py): _payload(prefix=str(self.repo / "venv")),
            str(homebrew / "python3"): _payload(version=(3, 13, 2), prefix="/opt/homebrew"),
        }
        found = statuses(self.collect(table, path_value=os.pathsep.join([str(homebrew), str(self.venv_py.parent)]), claude=claude))
        self.assertEqual(found["Claude Desktop interpreter"], "WARN")
        self.assertEqual(found["Pythons on PATH"], "WARN")

    def test_a_server_python_that_will_not_run_stops_after_two_checks(self):
        results = self.collect({str(self.venv_py): "Library not loaded"})
        self.assertEqual([r["name"] for r in results], ["Python bitness", "Python version for Resolve"])
        self.assertEqual(results[0]["status"], "FAIL")


class DoctorWiringTests(unittest.TestCase):
    """doctor.py runs these checks, prints their fix, and never crashes on them."""

    @classmethod
    def setUpClass(cls):
        import doctor
        cls.doctor = doctor

    def test_a_crashing_check_becomes_a_warn(self):
        def boom(**_kw):
            raise RuntimeError("boom")
        with mock.patch.object(env, "collect", boom):
            results = self.doctor.python_env_checks({})
        self.assertEqual(results[0]["status"], "WARN")
        self.assertIn("boom", results[0]["detail"])

    def test_text_output_prints_the_fix_line(self):
        fake = [{"status": "FAIL", "name": "Python bitness", "detail": "32-bit", "fix": "use 64-bit"}]
        with mock.patch.object(self.doctor, "collect", lambda *a, **k: fake), \
                mock.patch.object(sys, "argv", ["doctor.py"]), \
                mock.patch("builtins.print") as printed:
            code = self.doctor.main()
        lines = [call.args[0] for call in printed.call_args_list]
        self.assertEqual(code, 1)
        self.assertIn("[FAIL] Python bitness: 32-bit", lines)
        self.assertIn("       Fix: use 64-bit", lines)


if __name__ == "__main__":
    unittest.main()
