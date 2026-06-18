"""Regression tests for CDL normalization and installer env generation."""

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSTALL_PATH = PROJECT_ROOT / "install.py"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.cdl import normalize_cdl_payload

_spec = importlib.util.spec_from_file_location("resolve_install", INSTALL_PATH)
install = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(install)


class NormalizeCDLTests(unittest.TestCase):
    def test_normalize_cdl_accepts_arrays_and_numbers(self):
        payload = {
            "NodeIndex": 1,
            "Slope": [1.0, 1.0, 1.0],
            "Offset": (0.0, 0.0, 0.0),
            "Power": [0.9, 1.0, 1.1],
            "Saturation": 1.25,
        }

        normalized = normalize_cdl_payload(payload)

        self.assertEqual(normalized["NodeIndex"], "1")
        self.assertEqual(normalized["Slope"], "1.0 1.0 1.0")
        self.assertEqual(normalized["Offset"], "0.0 0.0 0.0")
        self.assertEqual(normalized["Power"], "0.9 1.0 1.1")
        self.assertEqual(normalized["Saturation"], "1.25")

    def test_normalize_cdl_preserves_existing_string_form(self):
        payload = {
            "NodeIndex": "1",
            "Slope": "1.0 1.0 1.0",
            "Offset": "0.0 0.0 0.0",
            "Power": "1.0 1.0 1.0",
            "Saturation": "1.0",
        }

        self.assertEqual(normalize_cdl_payload(payload), payload)

    def test_normalize_cdl_passes_through_non_dict_values(self):
        self.assertEqual(normalize_cdl_payload("1.0 1.0 1.0"), "1.0 1.0 1.0")


class InstallConfigTests(unittest.TestCase):
    def test_build_server_entry_includes_env(self):
        entry = install.build_server_entry(
            Path("/tmp/python"),
            Path("/tmp/server.py"),
            "/Resolve/Scripting",
            "/Resolve/fusionscript.so",
            system="Linux",
        )

        self.assertEqual(entry["command"], "/tmp/python")
        self.assertEqual(entry["args"], ["/tmp/server.py"])
        self.assertEqual(
            entry["env"],
            {
                "RESOLVE_SCRIPT_API": "/Resolve/Scripting",
                "RESOLVE_SCRIPT_LIB": "/Resolve/fusionscript.so",
                "PYTHONPATH": "/Resolve/Scripting/Modules",
            },
        )

    def test_windows_entry_adds_pythonhome(self):
        entry = install.build_server_entry(
            Path(r"C:\venv\Scripts\python.exe"),
            Path(r"C:\repo\src\server.py"),
            r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting",
            r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll",
            system="Windows",
            python_home=r"C:\Users\sam\AppData\Local\Programs\Python\Python312",
        )

        self.assertEqual(
            entry["env"]["PYTHONHOME"],
            r"C:\Users\sam\AppData\Local\Programs\Python\Python312",
        )

    def test_generate_manual_config_formats_include_env(self):
        standard, vscode_fmt, zed_fmt, opencode_fmt = install.generate_manual_config(
            Path("/tmp/python"),
            Path("/tmp/server.py"),
            "/Resolve/Scripting",
            "/Resolve/fusionscript.so",
        )

        standard_json = json.loads(standard)
        vscode_json = json.loads(vscode_fmt)
        zed_json = json.loads(zed_fmt)
        opencode_json = json.loads(opencode_fmt)

        self.assertIn("env", standard_json["mcpServers"]["davinci-resolve"])
        self.assertIn("env", vscode_json["servers"]["davinci-resolve"])
        self.assertIn("env", zed_json["context_servers"]["davinci-resolve"])
        # OpenCode names the env block "environment", not "env" (issue #72).
        self.assertIn("environment", opencode_json["mcp"]["davinci-resolve"])

        self.assertEqual(
            standard_json["mcpServers"]["davinci-resolve"]["env"]["PYTHONPATH"],
            "/Resolve/Scripting/Modules",
        )

    def test_build_opencode_entry_uses_opencode_schema(self):
        # OpenCode's schema (issue #72): type/enabled discriminators, the
        # interpreter and script combined into a single "command" array, and the
        # env block keyed "environment" rather than "env".
        entry = install.build_opencode_entry(
            Path("/tmp/python"),
            Path("/tmp/server.py"),
            "/Resolve/Scripting",
            "/Resolve/fusionscript.so",
            system="Linux",
        )

        self.assertEqual(entry["type"], "local")
        self.assertTrue(entry["enabled"])
        self.assertEqual(entry["command"], ["/tmp/python", "/tmp/server.py"])
        self.assertNotIn("args", entry)
        self.assertNotIn("env", entry)
        self.assertEqual(
            entry["environment"],
            {
                "RESOLVE_SCRIPT_API": "/Resolve/Scripting",
                "RESOLVE_SCRIPT_LIB": "/Resolve/fusionscript.so",
                "PYTHONPATH": "/Resolve/Scripting/Modules",
            },
        )

    def test_opencode_is_a_registered_client(self):
        opencode = next(
            (c for c in install.MCP_CLIENTS if c["id"] == "opencode"), None
        )
        self.assertIsNotNone(opencode)
        self.assertEqual(opencode["config_key"], "mcp")
        self.assertIn("opencode", str(opencode["get_path"]()))

    def test_verify_connection_uses_generated_env(self):
        fake_result = SimpleNamespace(
            stdout="IMPORTED_OK: Module loads but Resolve not running or not responding",
            stderr="",
            returncode=0,
        )

        with patch.object(
            install,
            "build_server_env",
            return_value={
                "RESOLVE_SCRIPT_API": "api",
                "RESOLVE_SCRIPT_LIB": "lib",
                "PYTHONPATH": "modules",
                "PYTHONHOME": "pyhome",
            },
        ), patch.object(install.subprocess, "run", return_value=fake_result) as run_mock:
            success, message = install.verify_resolve_connection(
                Path("/tmp/python"),
                "api",
                "lib",
            )

        self.assertTrue(success)
        self.assertIn("API module loaded", message)
        self.assertEqual(run_mock.call_args.kwargs["env"]["PYTHONHOME"], "pyhome")
        self.assertEqual(run_mock.call_args.kwargs["env"]["PYTHONPATH"], "modules")

    def test_windows_stdio_helper_disables_newline_translation(self):
        source = (PROJECT_ROOT / "src" / "utils" / "mcp_stdio.py").read_text()
        self.assertIn('newline=""', source)


class ConfigMergeTests(unittest.TestCase):
    """Regression coverage for issue #71: never wipe an existing config."""

    def _zed_client(self, config_path):
        return {
            "id": "zed",
            "name": "Zed",
            "get_path": lambda: config_path,
            "config_key": "context_servers",
        }

    def _write_config(self, config_path):
        return install.write_client_config(
            self._zed_client(config_path),
            Path("/tmp/python"),
            Path("/tmp/server.py"),
            "/Resolve/Scripting",
            "/Resolve/fusionscript.so",
        )

    def test_jsonc_settings_are_merged_not_overwritten(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "settings.json"
            config_path.write_text(
                "{\n"
                '  // Zed ships commented defaults\n'
                '  "theme": "One Dark",\n'
                '  "terminal": { "env": { "PATH": "/custom/bin:$PATH" } },\n'
                "}\n"
            )

            success, _ = self._write_config(config_path)
            self.assertTrue(success)

            result = json.loads(config_path.read_text())
            # Existing keys survive the merge.
            self.assertEqual(result["theme"], "One Dark")
            self.assertEqual(result["terminal"]["env"]["PATH"], "/custom/bin:$PATH")
            # And the MCP entry was added.
            self.assertIn("davinci-resolve", result["context_servers"])

    def test_plain_json_settings_are_merged(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "settings.json"
            config_path.write_text(json.dumps({"theme": "Ayu", "lsp": {"x": 1}}))

            success, _ = self._write_config(config_path)
            self.assertTrue(success)

            result = json.loads(config_path.read_text())
            self.assertEqual(result["theme"], "Ayu")
            self.assertEqual(result["lsp"], {"x": 1})
            self.assertIn("davinci-resolve", result["context_servers"])

    def test_unparseable_file_is_not_overwritten(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "settings.json"
            garbage = '{ "theme": "One Dark" this is not valid json at all '
            config_path.write_text(garbage)

            success, message = self._write_config(config_path)

            self.assertFalse(success)
            self.assertIn("could not be parsed", message)
            # The original file must be left untouched.
            self.assertEqual(config_path.read_text(), garbage)

    def test_missing_file_is_created(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "nested" / "settings.json"

            success, _ = self._write_config(config_path)
            self.assertTrue(success)

            result = json.loads(config_path.read_text())
            self.assertIn("davinci-resolve", result["context_servers"])

    def test_opencode_config_merges_with_opencode_schema(self):
        import tempfile

        opencode_client = {
            "id": "opencode",
            "name": "OpenCode",
            "get_path": None,  # set per-test below
            "config_key": "mcp",
        }

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "opencode.json"
            config_path.write_text(
                json.dumps(
                    {
                        "$schema": "https://opencode.ai/config.json",
                        "theme": "tokyonight",
                        "mcp": {"other-server": {"type": "local", "enabled": True}},
                    }
                )
            )
            opencode_client["get_path"] = lambda: config_path

            success, _ = install.write_client_config(
                opencode_client,
                Path("/tmp/python"),
                Path("/tmp/server.py"),
                "/Resolve/Scripting",
                "/Resolve/fusionscript.so",
            )
            self.assertTrue(success)

            result = json.loads(config_path.read_text())
            # Existing keys and sibling servers survive the merge.
            self.assertEqual(result["theme"], "tokyonight")
            self.assertIn("other-server", result["mcp"])
            # The DaVinci entry uses OpenCode's schema, not the standard one.
            entry = result["mcp"]["davinci-resolve"]
            self.assertEqual(entry["type"], "local")
            self.assertEqual(entry["command"], ["/tmp/python", "/tmp/server.py"])
            self.assertIn("environment", entry)
            self.assertNotIn("env", entry)

    def test_strip_jsonc_preserves_comment_markers_inside_strings(self):
        text = '{ "url": "https://example.com", /* drop me */ "a": 1, }'
        parsed = json.loads(install._strip_jsonc(text))
        self.assertEqual(parsed["url"], "https://example.com")
        self.assertEqual(parsed["a"], 1)

    def test_strip_jsonc_does_not_strip_commas_inside_string_values(self):
        # The trailing-comma step must be string-aware: a comma followed by
        # whitespace and a brace INSIDE a string value must survive, while real
        # trailing commas are still removed. (Regression: the prior regex pass
        # corrupted such string values during a JSONC merge.)
        text = (
            '{\n'
            '  // a comment forces the JSONC path\n'
            '  "greeting": "hello, } world",\n'
            '  "list": "items: a, b, ]",\n'
            '  "arr": [1, 2, ],\n'
            '  "obj": {"k": "v",},\n'
            '}'
        )
        parsed = json.loads(install._strip_jsonc(text))
        self.assertEqual(parsed["greeting"], "hello, } world")
        self.assertEqual(parsed["list"], "items: a, b, ]")
        self.assertEqual(parsed["arr"], [1, 2])
        self.assertEqual(parsed["obj"], {"k": "v"})


class PythonVersionGateTests(unittest.TestCase):
    def test_floor_and_above_accepted(self):
        # The only hard requirement is the 3.10 floor (MCP SDK). Everything
        # above it is accepted, including 3.13/3.14.
        for minor in (10, 11, 12, 13, 14):
            self.assertTrue(install.is_supported_python_version((3, minor, 0)))

    def test_below_minimum_rejected(self):
        self.assertFalse(install.is_supported_python_version((3, 9, 0)))
        self.assertFalse(install.is_supported_python_version((2, 7, 0)))

    def test_abi_risk_flagged_for_313_plus(self):
        self.assertFalse(install.is_abi_risk_python_version((3, 12, 0)))
        self.assertTrue(install.is_abi_risk_python_version((3, 13, 0)))
        self.assertTrue(install.is_abi_risk_python_version((3, 14, 3)))

    def test_314_is_supported_but_flagged(self):
        # 3.14 must NOT be refused (it works on recent Resolve), only flagged.
        self.assertTrue(install.is_supported_python_version((3, 14, 3)))
        self.assertTrue(install.is_abi_risk_python_version((3, 14, 3)))

    def test_require_supported_python_accepts_314_with_note(self):
        with patch.object(install, "_version_for_python", return_value=(3, 14, 3)):
            version = install.require_supported_python("/usr/bin/python3.14")
        self.assertEqual(version, (3, 14, 3))

    def test_require_supported_python_exits_below_floor(self):
        with patch.object(install, "_version_for_python", return_value=(3, 9, 0)):
            with self.assertRaises(SystemExit):
                install.require_supported_python("/usr/bin/python3.9")


if __name__ == "__main__":
    unittest.main()
