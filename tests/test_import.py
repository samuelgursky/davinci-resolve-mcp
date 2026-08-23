"""Basic syntax and tool-count smoke tests."""

import ast
import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
GRANULAR_DIR = PROJECT_ROOT / "src" / "granular"


def _parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text())


def _is_mcp_tool_decorator(decorator: ast.expr) -> bool:
    if not isinstance(decorator, ast.Call):
        return False
    func = decorator.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "tool"
        and isinstance(func.value, ast.Name)
        and func.value.id == "mcp"
    )


def _count_mcp_tools(path: Path) -> int:
    tree = _parse(path)
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for decorator in node.decorator_list
        if _is_mcp_tool_decorator(decorator)
    )


def _tool_annotation_name(path: Path, function_name: str) -> str:
    tree = _parse(path)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != function_name:
            continue
        for decorator in node.decorator_list:
            if not _is_mcp_tool_decorator(decorator):
                continue
            for keyword in decorator.keywords:
                if keyword.arg == "annotations" and isinstance(keyword.value, ast.Name):
                    return keyword.value.id
        return ""
    return ""


def _string_assignment(path: Path, name: str) -> str:
    tree = _parse(path)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return node.value.value
    return ""


def test_server_syntax():
    assert _parse(PROJECT_ROOT / "src" / "server.py") is not None


def test_granular_entrypoint_syntax():
    assert _parse(PROJECT_ROOT / "src" / "resolve_mcp_server.py") is not None


def test_granular_module_syntax():
    for py_file in GRANULAR_DIR.glob("*.py"):
        assert _parse(py_file) is not None, f"{py_file.name} has syntax errors"


def test_install_syntax():
    assert _parse(PROJECT_ROOT / "install.py") is not None


class McpSdkPinTest(unittest.TestCase):
    """Both install sites must cap the MCP SDK while server.py imports 1.x.

    A TestCase rather than a bare function on purpose: the rest of this module
    is pytest-style, but `unittest discover` does not collect bare functions,
    and this guard protects a regression that broke every fresh install (#103).
    It has to be reachable from both runners.
    """

    def test_mcp_sdk_pinned_below_2_everywhere(self):
        # SDK 2.0.0 dropped `mcp.server.fastmcp`. install.py installs mcp[cli]
        # directly AND from requirements.txt; a cap on only one of them still
        # lets a fresh install resolve to 2.x. Conditional on server.py's
        # import so the guard retires itself when the server is ported to the
        # 2.x layout, rather than blocking that port.
        server_src = (PROJECT_ROOT / "src" / "server.py").read_text()
        if "from mcp.server.fastmcp import" not in server_src:
            self.skipTest("server.py no longer imports mcp.server.fastmcp")

        # String literals only — install.py discusses mcp[cli] in prose
        # comments too, and a comment must not be able to satisfy (or fail)
        # this guard.
        specs = [
            node.value
            for node in ast.walk(_parse(PROJECT_ROOT / "install.py"))
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.startswith("mcp[cli]")
        ]
        specs += [
            line.strip()
            for line in (PROJECT_ROOT / "requirements.txt").read_text().splitlines()
            if line.strip().startswith("mcp[cli]")
        ]
        self.assertGreaterEqual(
            len(specs), 2,
            f"expected mcp[cli] pinned in both install.py and requirements.txt, "
            f"found {specs}",
        )
        for spec in specs:
            self.assertIn(
                "<2", spec,
                f"'{spec}' installs mcp[cli] without a <2 cap; SDK 2.0 removed "
                "mcp.server.fastmcp and breaks server.py at import (issue #103)",
            )


def test_npm_package_metadata():
    package = json.loads((PROJECT_ROOT / "package.json").read_text())
    assert package["name"] == "davinci-resolve-mcp"
    assert package["version"] == _string_assignment(PROJECT_ROOT / "install.py", "VERSION")
    assert package["bin"]["davinci-resolve-mcp"] == "./bin/davinci-resolve-mcp.mjs"
    assert (PROJECT_ROOT / "bin" / "davinci-resolve-mcp.mjs").exists()


def test_package_lock_in_sync():
    """package-lock.json must track package.json — version AND dependencies.

    `npm ci` refuses to install at all when the two disagree ("Missing: X from
    lock file"), so a stale lock breaks every reproducible install — CI, a
    fresh contributor clone, a container build — while `npm install` and
    `npm publish` stay green and hide it. That is exactly how this drifted
    seven releases: the version fell behind at 2.90.0, and two
    optionalDependencies (js-yaml, pg) were added without ever being locked.

    Regenerate with `npm install --package-lock-only`, and commit the result.
    """
    package = json.loads((PROJECT_ROOT / "package.json").read_text())
    lock = json.loads((PROJECT_ROOT / "package-lock.json").read_text())
    root = lock["packages"][""]

    assert lock["version"] == package["version"], (
        f"package-lock.json version {lock['version']!r} != package.json "
        f"{package['version']!r} — run: npm install --package-lock-only"
    )
    assert root["version"] == package["version"], (
        f"package-lock.json packages[''] version {root['version']!r} != "
        f"package.json {package['version']!r} — run: npm install --package-lock-only"
    )

    # The block that actually decides whether `npm ci` runs.
    for block in ("dependencies", "devDependencies", "optionalDependencies"):
        assert package.get(block, {}) == root.get(block, {}), (
            f"package.json {block} != package-lock.json packages[''] {block} — "
            f"npm ci will fail with EUSAGE. Run: npm install --package-lock-only"
        )


def test_utils_syntax():
    utils_dir = PROJECT_ROOT / "src" / "utils"
    for py_file in utils_dir.glob("*.py"):
        assert _parse(py_file) is not None, f"{py_file.name} has syntax errors"


def test_compound_tool_count():
    # 35 = 33 baseline + edit_engine (Phase E) + timeline_frame (#146).
    assert _count_mcp_tools(PROJECT_ROOT / "src" / "server.py") == 36


def test_prompt_registrations():
    source = (PROJECT_ROOT / "src" / "server.py").read_text()
    # 2 baseline (davinci_resolve_workflow + analyze_media) + 5 F2 workflow prompts
    # + 7 per-domain workflow routers.
    assert source.count("@mcp.prompt") == 14
    # Per-domain routers (cross-platform depth via MCP prompts).
    for _name in (
        "color_grade_workflow",
        "timeline_edit_workflow",
        "conform_workflow",
        "delivery_workflow",
        "fusion_workflow",
        "audio_workflow",
        "media_pool_workflow",
    ):
        assert f'name="{_name}"' in source
    # Baseline prompts (must not regress).
    assert 'name="analyze_media"' in source
    assert "def analyze_media(" in source
    assert "include_visuals: bool = True" in source
    assert "include_transcription: bool = True" in source
    assert "publish_metadata" in source
    assert "include_visuals=false" in source
    assert "Do not silently downgrade media analysis" in source
    assert "session_only=true" in source
    # F2 workflow prompts (agentic-flow improvement F2).
    assert 'name="analyze_and_propose_grade"' in source
    assert 'name="match_bin_to_hero"' in source
    assert 'name="verify_timeline_coverage"' in source
    assert 'name="open_and_analyze_selection"' in source
    assert 'name="prep_color_handoff"' in source


def test_granular_tool_count():
    total = sum(_count_mcp_tools(py_file) for py_file in GRANULAR_DIR.glob("*.py"))
    assert total == 353


def test_reported_granular_tools_have_explicit_annotations():
    expected = {
        "gallery.py": {"get_gallery_album_name": "READ_ONLY_TOOL"},
        "media_pool.py": {"import_media": "EXTERNAL_WRITE_TOOL"},
        "media_pool_item.py": {"link_proxy_media": "EXTERNAL_DESTRUCTIVE_TOOL"},
        "project.py": {"set_project_setting": "DESTRUCTIVE_TOOL"},
        "resolve_control.py": {"switch_page": "IDEMPOTENT_WRITE_TOOL"},
        "timeline_item.py": {"set_timeline_item_transform": "DESTRUCTIVE_TOOL"},
    }
    for file_name, functions in expected.items():
        path = GRANULAR_DIR / file_name
        for function_name, annotation_name in functions.items():
            assert _tool_annotation_name(path, function_name) == annotation_name


def run_all():
    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            func()


if __name__ == "__main__":
    run_all()
    print("test_import.py: ok")
