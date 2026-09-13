"""Static guard: live harnesses stub the MCP SDK through one installer, and that
installer keeps up with what `src/server.py` imports.

Every live harness imports `src.server`, which pulls in the MCP SDK at module
scope. Harnesses used to each carry a private copy of a stub installer. Two
things went wrong with that, and both were silent:

1. The copies called `sys.modules.setdefault("mcp", stub)` before anything had
   imported `mcp`, so on a machine where the genuine SDK was installed and
   working, the stand-in won anyway.
2. `src/server.py` grew `Context`, `Image` and `mcp.types`; the copies kept
   offering only `FastMCP`. A harness then died at whichever import its own copy
   had never been taught about — reported from the field as
   `ImportError: cannot import name 'Context' from 'mcp.server.fastmcp'`.

Neither is visible in the unit suite, because these harnesses only run by hand
against a live Resolve. So the guard is static: nobody hand-rolls the stubs, and
the one stub set is compared against the server's real imports.
"""

import ast
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
SERVER = REPO / "src" / "server.py"

# Where a harness may legitimately mention the stub module names.
INSTALLER = REPO / "src" / "utils" / "mcp_import_stubs.py"


def _harness_files():
    """Every hand-run live harness that imports `src.server`."""
    found = list((REPO / "tests").glob("live_*.py")) + list((REPO / "src" / "utils").glob("*live_probe*.py"))
    return sorted(p for p in found if p != INSTALLER)


def _mcp_imports_of_server():
    """(module, name) for every name `src/server.py` imports out of the SDK."""
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    wanted = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "mcp" or module.startswith("mcp."):
                for alias in node.names:
                    wanted.append((module, alias.name))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "mcp" or alias.name.startswith("mcp."):
                    wanted.append((alias.name, None))
    return wanted


class TestMcpImportStubs(unittest.TestCase):
    def test_no_harness_hand_rolls_mcp_stubs(self):
        """A private copy is how the stub set drifted behind the server before."""
        offenders = []
        for path in _harness_files():
            text = path.read_text(encoding="utf-8")
            if 'setdefault("mcp"' in text or "setdefault('mcp'" in text:
                offenders.append(str(path.relative_to(REPO)))
        self.assertEqual(
            offenders,
            [],
            "These harnesses install their own MCP stubs instead of calling "
            "src.utils.mcp_import_stubs.install_mcp_stubs(): " + ", ".join(offenders),
        )

    def test_stub_set_covers_every_name_the_server_imports(self):
        """Adding an SDK import to server.py must not break harnesses silently."""
        from src.utils.mcp_import_stubs import MCP_STUB_NAMES

        missing = []
        for module, name in _mcp_imports_of_server():
            if module not in MCP_STUB_NAMES:
                missing.append(f"{module} (whole module)")
                continue
            if name is not None and name not in MCP_STUB_NAMES[module]:
                missing.append(f"{module}.{name}")
        self.assertEqual(
            missing,
            [],
            "src/server.py imports names the MCP stubs do not provide, so every "
            "live harness fails at import when the real SDK is absent: " + ", ".join(missing),
        )

    def test_installer_leaves_a_working_sdk_alone(self):
        """The real package must win; setdefault used to shadow it."""
        import sys

        from src.utils.mcp_import_stubs import install_mcp_stubs

        try:
            import mcp  # noqa: F401
            from mcp.server.fastmcp import Context, FastMCP, Image  # noqa: F401
        except Exception:
            self.skipTest("real MCP SDK is not installed in this environment")

        before = sys.modules["mcp"]
        self.assertFalse(install_mcp_stubs(), "installer stubbed over a working SDK")
        self.assertIs(sys.modules["mcp"], before)


if __name__ == "__main__":
    unittest.main()
