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
        standard, vscode_fmt, zed_fmt = install.generate_manual_config(
            Path("/tmp/python"),
            Path("/tmp/server.py"),
            "/Resolve/Scripting",
            "/Resolve/fusionscript.so",
        )

        standard_json = json.loads(standard)
        vscode_json = json.loads(vscode_fmt)
        zed_json = json.loads(zed_fmt)

        self.assertIn("env", standard_json["mcpServers"]["davinci-resolve"])
        self.assertIn("env", vscode_json["servers"]["davinci-resolve"])
        self.assertIn("env", zed_json["context_servers"]["davinci-resolve"])

        self.assertEqual(
            standard_json["mcpServers"]["davinci-resolve"]["env"]["PYTHONPATH"],
            "/Resolve/Scripting/Modules",
        )

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


if __name__ == "__main__":
    unittest.main()
