"""Basic syntax and tool-count smoke tests."""

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
GRANULAR_DIR = PROJECT_ROOT / "src" / "granular"


def _parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text())


def test_server_syntax():
    assert _parse(PROJECT_ROOT / "src" / "server.py") is not None


def test_granular_entrypoint_syntax():
    assert _parse(PROJECT_ROOT / "src" / "resolve_mcp_server.py") is not None


def test_granular_module_syntax():
    for py_file in GRANULAR_DIR.glob("*.py"):
        assert _parse(py_file) is not None, f"{py_file.name} has syntax errors"


def test_install_syntax():
    assert _parse(PROJECT_ROOT / "install.py") is not None


def test_utils_syntax():
    utils_dir = PROJECT_ROOT / "src" / "utils"
    for py_file in utils_dir.glob("*.py"):
        assert _parse(py_file) is not None, f"{py_file.name} has syntax errors"


def test_compound_tool_count():
    source = (PROJECT_ROOT / "src" / "server.py").read_text()
    assert source.count("@mcp.tool()") == 27


def test_granular_tool_count():
    total = sum(py_file.read_text().count("@mcp.tool()") for py_file in GRANULAR_DIR.glob("*.py"))
    assert total == 354


def run_all():
    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            func()


if __name__ == "__main__":
    run_all()
    print("test_import.py: ok")
