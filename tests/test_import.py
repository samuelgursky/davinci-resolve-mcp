"""Basic syntax and tool-count smoke tests."""

import ast
import json
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


def test_npm_package_metadata():
    package = json.loads((PROJECT_ROOT / "package.json").read_text())
    assert package["name"] == "davinci-resolve-mcp"
    assert package["version"] == _string_assignment(PROJECT_ROOT / "install.py", "VERSION")
    assert package["bin"]["davinci-resolve-mcp"] == "./bin/davinci-resolve-mcp.mjs"
    assert (PROJECT_ROOT / "bin" / "davinci-resolve-mcp.mjs").exists()


def test_utils_syntax():
    utils_dir = PROJECT_ROOT / "src" / "utils"
    for py_file in utils_dir.glob("*.py"):
        assert _parse(py_file) is not None, f"{py_file.name} has syntax errors"


def test_compound_tool_count():
    # 34 = 33 baseline + edit_engine (Phase E).
    assert _count_mcp_tools(PROJECT_ROOT / "src" / "server.py") == 34


def test_prompt_registrations():
    source = (PROJECT_ROOT / "src" / "server.py").read_text()
    # 2 baseline (davinci_resolve_workflow + analyze_media) + 5 F2 workflow prompts.
    assert source.count("@mcp.prompt") == 7
    # Baseline prompts (must not regress).
    assert 'name="analyze_media"' in source
    assert "def analyze_media(" in source
    assert "include_visuals: bool = True" in source
    assert "include_transcription: bool = True" in source
    assert "publish_metadata" in source
    assert "include_visuals=false" in source
    assert "Do not silently downgrade media analysis" in source
    assert "session_only=true" in source
    # F2 workflow prompts (see local/design/agentic-flow-improvements-gameplan-2.md task F2).
    assert 'name="analyze_and_propose_grade"' in source
    assert 'name="match_bin_to_hero"' in source
    assert 'name="verify_timeline_coverage"' in source
    assert 'name="open_and_analyze_selection"' in source
    assert 'name="prep_color_handoff"' in source


def test_granular_tool_count():
    total = sum(_count_mcp_tools(py_file) for py_file in GRANULAR_DIR.glob("*.py"))
    assert total == 341


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
