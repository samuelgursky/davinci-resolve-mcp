"""Regression tests for CDL normalization and installer env generation."""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
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


def _parse_toml(text):
    """Parse TOML with whatever reader this interpreter has.

    ``tomllib`` is stdlib only from 3.11 and the project floor is 3.10, so on an
    older interpreter these assertions fall back to a substring check rather
    than pulling in a dependency the installer itself does not need.
    """
    loader = install._toml_loader()
    if loader is None:
        raise unittest.SkipTest("no TOML reader available on this interpreter")
    return loader.loads(text)


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
        with patch.dict(os.environ, {}, clear=True):
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

    def test_build_server_entry_includes_explicit_network_env(self):
        with patch.dict(
            os.environ,
            {
                "RESOLVE_SCRIPT_HOST": "resolve.example.test",
                "RESOLVE_SCRIPT_TIMEOUT": "12.5",
            },
            clear=True,
        ):
            entry = install.build_server_entry(
                Path("/tmp/python"),
                Path("/tmp/server.py"),
                "/Resolve/Scripting",
                "/Resolve/fusionscript.so",
                system="Linux",
            )

        self.assertEqual(
            entry["env"],
            {
                "RESOLVE_SCRIPT_API": "/Resolve/Scripting",
                "RESOLVE_SCRIPT_LIB": "/Resolve/fusionscript.so",
                "RESOLVE_SCRIPT_HOST": "resolve.example.test",
                "RESOLVE_SCRIPT_TIMEOUT": "12.5",
                "PYTHONPATH": "/Resolve/Scripting/Modules",
            },
        )

    def test_verify_connection_routes_through_connect_resolve(self):
        """The installer's post-install probe must use connect_resolve so
        Network mode (RESOLVE_SCRIPT_HOST) uses the IP-targeted overload, and
        must inject the repo root so that import resolves."""
        captured = {}

        def fake_run(argv, **kwargs):
            captured["script"] = argv[-1]
            captured["timeout"] = kwargs.get("timeout")
            captured["env"] = kwargs.get("env")
            return SimpleNamespace(stdout="CONNECTED: DaVinci Resolve Studio 20.3", stderr="", returncode=0)

        repo_root = str(Path(install.__file__).resolve().parent)
        with patch.dict(
            os.environ,
            {"RESOLVE_SCRIPT_HOST": "127.0.0.1", "RESOLVE_SCRIPT_TIMEOUT": "12.5"},
            clear=True,
        ), patch.object(install.subprocess, "run", side_effect=fake_run):
            ok, detail = install.verify_resolve_connection(
                Path("/tmp/python"),
                "/Resolve/Scripting",
                "/Resolve/fusionscript.so",
            )

        self.assertTrue(ok)
        self.assertIn("connect_resolve", captured["script"])
        self.assertIn(repo_root, captured["script"])
        # RESOLVE_SCRIPT_HOST propagated into the probe env by build_server_env.
        self.assertEqual(captured["env"].get("RESOLVE_SCRIPT_HOST"), "127.0.0.1")
        # Process timeout accommodates the configured network timeout (12.5 + 2).
        self.assertGreaterEqual(captured["timeout"], 14.5)

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
        standard, vscode_fmt, zed_fmt, opencode_fmt, codex_fmt = install.generate_manual_config(
            Path("/tmp/python"),
            Path("/tmp/server.py"),
            "/Resolve/Scripting",
            "/Resolve/fusionscript.so",
        )

        # Codex is TOML, not JSON — checked separately below.
        self.assertIn("[mcp_servers.davinci-resolve]", codex_fmt)
        self.assertIn("RESOLVE_SCRIPT_API", codex_fmt)

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

        # The advanced (Node) server pins AAF_PROBE_PYTHON to the venv interpreter so the
        # offline AAF reader (pyaaf2, installed into that venv) works out of the box.
        advanced = standard_json["mcpServers"]["davinci-resolve-advanced"]
        self.assertEqual(advanced["command"], "node")
        self.assertEqual(advanced["env"]["AAF_PROBE_PYTHON"], "/tmp/python")

    def test_advanced_entry_omits_env_without_python_path(self):
        # No interpreter known → no AAF_PROBE_PYTHON pin (falls back to `python3` on PATH).
        entry = install.build_advanced_entry(Path("/tmp/server.py"))
        self.assertEqual(entry["command"], "node")
        self.assertNotIn("env", entry)

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

    def test_codex_is_a_registered_toml_client(self):
        """Issue #39: the installer claimed Codex support but never wrote
        ~/.codex/config.toml, so the entry was simply missing after install."""
        codex = next((c for c in install.MCP_CLIENTS if c["id"] == "codex"), None)
        self.assertIsNotNone(codex)
        self.assertEqual(codex["config_key"], "mcp_servers")
        self.assertEqual(codex["format"], "toml")
        self.assertTrue(str(codex["get_path"]()).endswith(".codex/config.toml"))

    def test_codex_path_honors_codex_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"CODEX_HOME": tmp}):
                self.assertEqual(install.codex_config(), Path(tmp) / "config.toml")

    def test_build_codex_block_is_valid_toml(self):
        block = install.build_codex_block(
            Path("/tmp/python"),
            Path("/tmp/server.py"),
            "/Resolve/Scripting",
            "/Resolve/fusionscript.so",
            system="Linux",
        )
        parsed = _parse_toml(block)
        entry = parsed["mcp_servers"]["davinci-resolve"]
        self.assertEqual(entry["command"], "/tmp/python")
        self.assertEqual(entry["args"], ["/tmp/server.py"])
        self.assertEqual(entry["env"]["RESOLVE_SCRIPT_API"], "/Resolve/Scripting")
        self.assertEqual(entry["env"]["PYTHONPATH"], "/Resolve/Scripting/Modules")

    def test_build_codex_block_escapes_windows_paths(self):
        # Backslashes are escape characters in a TOML basic string: unescaped,
        # a Windows path would corrupt the whole config, not just this entry.
        block = install.build_codex_block(
            Path(r"C:\Users\sam\venv\Scripts\python.exe"),
            Path(r"C:\Users\sam\mcp\src\server.py"),
            r"C:\ProgramData\Blackmagic Design\Scripting",
            r"C:\ProgramData\Blackmagic Design\fusionscript.dll",
            system="Windows",
            python_home=r"C:\Python312",
        )
        entry = _parse_toml(block)["mcp_servers"]["davinci-resolve"]
        self.assertEqual(entry["command"], r"C:\Users\sam\venv\Scripts\python.exe")
        self.assertEqual(entry["args"], [r"C:\Users\sam\mcp\src\server.py"])
        self.assertEqual(entry["env"]["PYTHONHOME"], r"C:\Python312")

    def test_claude_desktop_prefers_msix_virtualized_path(self):
        """Issue #93: MSIX builds of Claude Desktop read config from a
        package-containerized path, not %APPDATA%\\Claude\\."""
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "Local"
            roaming = Path(tmp) / "Roaming"
            virtual = (
                local / "Packages" / "Claude_pzs8sxrjxfjjc"
                / "LocalCache" / "Roaming" / "Claude"
            )
            virtual.mkdir(parents=True)
            env = {"LOCALAPPDATA": str(local), "APPDATA": str(roaming)}
            with patch.dict(os.environ, env):
                path = install.windows_claude_desktop_config()
            self.assertEqual(path, virtual / "claude_desktop_config.json")

    def test_claude_desktop_falls_back_to_appdata_without_msix(self):
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "Local"
            roaming = Path(tmp) / "Roaming"
            (local / "Packages").mkdir(parents=True)
            env = {"LOCALAPPDATA": str(local), "APPDATA": str(roaming)}
            with patch.dict(os.environ, env):
                path = install.windows_claude_desktop_config()
            self.assertEqual(
                path, roaming / "Claude" / "claude_desktop_config.json"
            )

    def test_claude_desktop_ignores_msix_package_never_launched(self):
        """A Claude_* package dir without LocalCache/Roaming/Claude (app never
        run) must not divert the config away from %APPDATA%."""
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "Local"
            roaming = Path(tmp) / "Roaming"
            (local / "Packages" / "Claude_pzs8sxrjxfjjc").mkdir(parents=True)
            env = {"LOCALAPPDATA": str(local), "APPDATA": str(roaming)}
            with patch.dict(os.environ, env):
                path = install.windows_claude_desktop_config()
            self.assertEqual(
                path, roaming / "Claude" / "claude_desktop_config.json"
            )

    def test_claude_desktop_client_uses_msix_helper_on_windows(self):
        client = next(
            c for c in install.MCP_CLIENTS if c["id"] == "claude-desktop"
        )
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "Local"
            virtual = (
                local / "Packages" / "Claude_abc123"
                / "LocalCache" / "Roaming" / "Claude"
            )
            virtual.mkdir(parents=True)
            env = {"LOCALAPPDATA": str(local), "APPDATA": str(Path(tmp) / "Roaming")}
            with patch.dict(os.environ, env), patch.object(install, "SYSTEM", "Windows"):
                path = client["get_path"]()
            self.assertEqual(path, virtual / "claude_desktop_config.json")

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


class ConsoleEncodingTests(unittest.TestCase):
    """Regression coverage for issue #150: a successful install ending in a
    traceback.

    The installer prints box-drawing and check-mark glyphs. A Windows console
    carries them, but a redirected stdout falls back to the locale code page —
    cp1252 by default — and the summary divider raises UnicodeEncodeError after
    every client has already been configured. Reported against
    `npx davinci-resolve-mcp setup --clients manual 2>&1 | tail`.
    """

    class _Stream:
        def __init__(self, encoding):
            self.encoding = encoding
            self.calls = []

        def reconfigure(self, **kwargs):
            self.calls.append(kwargs)
            if "encoding" in kwargs:
                self.encoding = kwargs["encoding"]

    def test_a_code_page_that_cannot_carry_the_glyphs_is_reconfigured(self):
        out, err = self._Stream("cp1252"), self._Stream("cp1252")
        with patch.object(install.sys, "stdout", out), patch.object(install.sys, "stderr", err):
            install._ensure_glyph_capable_stdio()
        for stream in (out, err):
            self.assertEqual(stream.calls, [{"encoding": "utf-8", "errors": "replace"}])

    def test_a_capable_stream_keeps_its_own_encoding(self):
        """Only the streams that would crash are touched — a console that is
        already right must not be re-encoded underneath the user."""
        out = self._Stream("utf-8")
        with patch.object(install.sys, "stdout", out), patch.object(install.sys, "stderr", out):
            install._ensure_glyph_capable_stdio()
        self.assertEqual(out.calls, [])

    def test_the_glyph_probe_covers_what_the_installer_actually_prints(self):
        """The probe is the whole gate: a glyph the installer prints but the
        probe omits would encode-check clean and still crash at the summary."""
        source = INSTALL_PATH.read_text(encoding="utf-8")
        for glyph in ("\u2500", "\u2192", "\u2713", "\u2298"):
            with self.subTest(glyph=glyph):
                self.assertIn(glyph, source, "glyph is no longer printed; prune the probe")
                self.assertIn(glyph, install._GLYPH_PROBE)

    def test_a_redirected_cp1252_run_prints_the_divider_instead_of_crashing(self):
        """End to end, in a child interpreter with a piped stdout: this is the
        exact shape of the reported failure, and it fails without the guard."""
        script = (
            "import sys; sys.path.insert(0, %r); import install\n"
            "print('  ' + '\u2500' * 50)\n"
        ) % str(PROJECT_ROOT)
        env = dict(os.environ, PYTHONIOENCODING="cp1252")
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(PROJECT_ROOT), env=env, capture_output=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        self.assertIn("\u2500" * 50, proc.stdout.decode("utf-8", "replace"))


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

    def _codex_client(self, config_path):
        return {
            "id": "codex",
            "name": "Codex CLI",
            "get_path": lambda: config_path,
            "config_key": "mcp_servers",
            "format": "toml",
        }

    def _write_codex(self, config_path, **kwargs):
        return install.write_client_config(
            self._codex_client(config_path),
            Path("/tmp/python"),
            Path("/tmp/server.py"),
            "/Resolve/Scripting",
            "/Resolve/fusionscript.so",
            **kwargs,
        )

    def test_codex_config_is_created_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / ".codex" / "config.toml"

            success, message = self._write_codex(config_path)
            self.assertTrue(success, message)

            entry = _parse_toml(config_path.read_text())["mcp_servers"]["davinci-resolve"]
            self.assertEqual(entry["command"], "/tmp/python")
            self.assertEqual(entry["args"], ["/tmp/server.py"])

    def test_codex_merge_keeps_other_settings_and_servers(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text(
                "# my codex setup\n"
                'model = "gpt-5-codex"\n'
                'approval_policy = "on-request"\n'
                "\n"
                "[mcp_servers.other]\n"
                'command = "npx"\n'
                'args = ["-y", "other-mcp"]\n'
            )

            success, message = self._write_codex(config_path)
            self.assertTrue(success, message)

            text = config_path.read_text()
            parsed = _parse_toml(text)
            self.assertEqual(parsed["model"], "gpt-5-codex")
            self.assertEqual(parsed["approval_policy"], "on-request")
            self.assertEqual(parsed["mcp_servers"]["other"]["command"], "npx")
            self.assertIn("davinci-resolve", parsed["mcp_servers"])
            # Comments and hand formatting survive the splice.
            self.assertIn("# my codex setup", text)
            # And the original file is backed up before the rewrite.
            self.assertTrue(config_path.with_suffix(".toml.backup").exists())

    def test_codex_merge_replaces_stale_entry_in_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text(
                'model = "gpt-5-codex"\n'
                "\n"
                "[mcp_servers.davinci-resolve]\n"
                'command = "/old/python"\n'
                'args = ["/old/server.py"]\n'
                "\n"
                "[mcp_servers.other]\n"
                'command = "npx"\n'
            )

            success, message = self._write_codex(config_path)
            self.assertTrue(success, message)

            text = config_path.read_text()
            parsed = _parse_toml(text)
            self.assertEqual(
                parsed["mcp_servers"]["davinci-resolve"]["command"], "/tmp/python"
            )
            self.assertNotIn("/old/python", text)
            # The table after ours is untouched, not swallowed by the replacement.
            self.assertEqual(parsed["mcp_servers"]["other"]["command"], "npx")
            # Rewriting twice is idempotent — no duplicate table.
            self._write_codex(config_path)
            self.assertEqual(config_path.read_text().count("[mcp_servers.davinci-resolve]"), 1)

    def test_codex_invalid_toml_is_not_overwritten(self):
        if install._toml_loader() is None:
            self.skipTest("no TOML reader available on this interpreter")
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            garbage = 'model = "gpt-5-codex\n[oops\n'
            config_path.write_text(garbage)

            success, message = self._write_codex(config_path)

            self.assertFalse(success)
            self.assertIn("not valid TOML", message)
            self.assertEqual(config_path.read_text(), garbage)

    def test_codex_inline_definition_is_refused_not_duplicated(self):
        # An inline `davinci-resolve = { ... }` cannot be spliced line-by-line;
        # appending a table anyway would define the key twice and make Codex
        # reject the entire config.
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            original = (
                "[mcp_servers]\n"
                'davinci-resolve = { command = "/old/python", args = ["/old/server.py"] }\n'
            )
            config_path.write_text(original)

            success, message = self._write_codex(config_path)

            self.assertFalse(success)
            self.assertIn("manually", message)
            self.assertEqual(config_path.read_text(), original)

    def test_codex_merge_preserves_per_tool_subtables(self):
        # A hand-written Codex config puts per-tool approval modes in
        # [mcp_servers.davinci-resolve.tools.<tool>]. Dropping those on an
        # update would silently widen what the agent may do without asking.
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text(
                "[mcp_servers.davinci-resolve]\n"
                'command = "/old/python"\n'
                'args = ["/old/server.py"]\n'
                "\n"
                "[mcp_servers.davinci-resolve.env]\n"
                'RESOLVE_SCRIPT_API = "/old/api"\n'
                "\n"
                "[mcp_servers.davinci-resolve.tools.timeline]\n"
                'approval_mode = "approve"\n'
                "\n"
                "[mcp_servers.other]\n"
                'command = "npx"\n'
            )

            success, message = self._write_codex(config_path)
            self.assertTrue(success, message)

            text = config_path.read_text()
            entry = _parse_toml(text)["mcp_servers"]["davinci-resolve"]
            self.assertEqual(entry["command"], "/tmp/python")
            self.assertEqual(entry["tools"]["timeline"]["approval_mode"], "approve")
            # env keeps its sub-table shape: TOML rejects a file that defines the
            # same key both as a sub-table and inline, so the rewrite must not
            # switch forms.
            self.assertEqual(entry["env"]["RESOLVE_SCRIPT_API"], "/Resolve/Scripting")
            self.assertIn("[mcp_servers.davinci-resolve.env]", text)
            self.assertNotIn("env = {", text)
            self.assertEqual(_parse_toml(text)["mcp_servers"]["other"]["command"], "npx")

    def test_codex_merge_keeps_per_server_knobs_and_comments(self):
        # Only command/args/env are ours. Codex's own per-server settings — and
        # this server is slow enough to start that startup_timeout_sec is a
        # realistic thing to have tuned — must survive an update.
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text(
                "[mcp_servers.davinci-resolve]\n"
                "# resolve can take a while to launch\n"
                "startup_timeout_sec = 120\n"
                'command = "/old/python"\n'
                "args = [\n"
                '  "/old/server.py",\n'
                "]\n"
                "tool_timeout_sec = 90\n"
            )

            success, message = self._write_codex(config_path)
            self.assertTrue(success, message)

            text = config_path.read_text()
            entry = _parse_toml(text)["mcp_servers"]["davinci-resolve"]
            self.assertEqual(entry["command"], "/tmp/python")
            self.assertEqual(entry["args"], ["/tmp/server.py"])
            self.assertEqual(entry["startup_timeout_sec"], 120)
            self.assertEqual(entry["tool_timeout_sec"], 90)
            self.assertIn("# resolve can take a while to launch", text)
            # The multi-line args value is replaced, not left behind in pieces.
            self.assertNotIn("/old/server.py", text)

    def test_codex_merge_with_subtables_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text(
                "[mcp_servers.davinci-resolve]\n"
                'command = "/old/python"\n'
                "\n"
                "[mcp_servers.davinci-resolve.env]\n"
                'RESOLVE_SCRIPT_API = "/old/api"\n'
                "\n"
                "[mcp_servers.davinci-resolve.tools.timeline]\n"
                'approval_mode = "approve"\n'
            )

            self._write_codex(config_path)
            once = config_path.read_text()
            self._write_codex(config_path)
            self.assertEqual(config_path.read_text(), once)

    def test_codex_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"

            success, message = self._write_codex(config_path, dry_run=True)

            self.assertTrue(success)
            self.assertIn("[mcp_servers.davinci-resolve]", message)
            self.assertFalse(config_path.exists())

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


class AntigravityConfigPathTests(unittest.TestCase):
    """Issue #159 — two contributors report two paths; resolve by what exists."""

    def _resolve(self, existing):
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp)
            for rel in existing:
                target = fake_home / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("{}\n")
            with patch.object(install, "home", return_value=fake_home):
                resolved = install.antigravity_config()
            return resolved.relative_to(fake_home).as_posix()

    def test_falls_back_to_gemini_config_when_neither_exists(self):
        self.assertEqual(self._resolve([]), ".gemini/config/mcp_config.json")

    def test_uses_the_antigravity_path_when_only_it_exists(self):
        self.assertEqual(
            self._resolve([".gemini/antigravity/mcp_config.json"]),
            ".gemini/antigravity/mcp_config.json",
        )

    def test_uses_the_config_path_when_only_it_exists(self):
        self.assertEqual(
            self._resolve([".gemini/config/mcp_config.json"]),
            ".gemini/config/mcp_config.json",
        )

    def test_config_path_wins_when_both_exist(self):
        """The installer never wrote ~/.gemini/config/, so its presence is evidence."""
        self.assertEqual(
            self._resolve([
                ".gemini/config/mcp_config.json",
                ".gemini/antigravity/mcp_config.json",
            ]),
            ".gemini/config/mcp_config.json",
        )

    def test_a_bare_antigravity_directory_is_not_taken_as_a_config(self):
        """~/.gemini/antigravity/ holds runtime state on every install (#159)."""
        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp)
            (fake_home / ".gemini" / "antigravity" / "logs").mkdir(parents=True)
            with patch.object(install, "home", return_value=fake_home):
                resolved = install.antigravity_config()
        self.assertEqual(
            resolved.relative_to(fake_home).as_posix(),
            ".gemini/config/mcp_config.json",
        )

    def test_client_entry_uses_the_resolver(self):
        entry = next(c for c in install.MCP_CLIENTS if c["id"] == "antigravity")
        self.assertIs(entry["get_path"], install.antigravity_config)


if __name__ == "__main__":
    unittest.main()
