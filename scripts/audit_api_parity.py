#!/usr/bin/env python3
"""API-docs-vs-source parity guard for davinci-resolve-mcp.

Catches three regressions that have shipped in past releases:

1. **Broken imports** — `from api.X import Y` patterns that crash on first call
   (the bug class fixed in v2.3.2 by removing 25 broken granular tools).
2. **Undocumented Resolve methods** — wrappers around methods that don't appear
   in `docs/resolve_scripting_api.txt` (the bug class fixed in v2.3.2/v2.3.3
   by removing wrappers for ExportProjectToCloud, AddUserToCloudProject, etc.).
3. **Documented methods missing from both layers** — Resolve API methods that
   are documented but exposed neither in compound (`src/server.py`) nor
   granular (`src/granular/*.py`).

Exit codes: 0 if no issues, 1 if any check fails.

Run: `python3 scripts/audit_api_parity.py`
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_PATH = REPO_ROOT / "docs" / "resolve_scripting_api.txt"
SERVER_PATH = REPO_ROOT / "src" / "server.py"
GRANULAR_DIR = REPO_ROOT / "src" / "granular"

# Class-prefixed methods like Resolve.OpenPage are split into class+method when
# we extract; the class name comes from the section heading above the method.
CLASS_HEADING_RE = re.compile(r"^([A-Z][A-Za-z]+)\s*$")
METHOD_RE = re.compile(r"^\s+([A-Z][A-Za-z0-9_]+)\s*\(")

# Methods to ignore in the "missing from both layers" check. These are either:
# - intrinsic Python object methods we don't want to wrap
# - methods that exist on multiple classes where one exposure is enough
# - methods that are documented but optional on older Resolve builds
IGNORE_METHODS: Set[str] = set()


def parse_documented_methods(docs_path: Path) -> Dict[str, Set[str]]:
    """Return {class_name: {method_name, ...}}. Skips:
    - standalone sections like 'Cache Mode information' that aren't class headings
    - everything after the 'Deprecated Resolve API Functions' marker
    - everything after the 'Unsupported Resolve API Functions' marker
    """
    classes: Dict[str, Set[str]] = {}
    current_class: str | None = None
    text = docs_path.read_text()
    # Truncate at the first deprecation marker
    for marker in ("\nDeprecated Resolve API Functions",
                   "\nUnsupported Resolve API Functions"):
        idx = text.find(marker)
        if idx != -1:
            text = text[:idx]
    for line in text.splitlines():
        if not line.strip():
            continue
        if not line.startswith(" "):
            m = CLASS_HEADING_RE.match(line)
            if m:
                # Heuristic: class headings are short single words, not section
                # titles like "Looking up Render Settings"
                candidate = m.group(1)
                if len(candidate.split()) == 1:
                    current_class = candidate
                    classes.setdefault(current_class, set())
                else:
                    current_class = None
            continue
        if current_class is None:
            continue
        mm = METHOD_RE.match(line)
        if mm:
            classes[current_class].add(mm.group(1))
    return classes


def collect_source_text() -> str:
    """Concatenate every Python file under src/ for substring searches."""
    parts: List[str] = []
    for py_path in (REPO_ROOT / "src").rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        try:
            parts.append(py_path.read_text())
        except (OSError, UnicodeDecodeError):
            continue
    return "\n".join(parts)


def find_broken_api_imports() -> List[Tuple[Path, int, str]]:
    """Find any `from api.X import Y` lines (the v2.3.2 bug class)."""
    hits: List[Tuple[Path, int, str]] = []
    pattern = re.compile(r"^\s*from\s+api\.\w+\s+import\s+")
    for py_path in (REPO_ROOT / "src").rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        try:
            for i, line in enumerate(py_path.read_text().splitlines(), 1):
                if pattern.search(line):
                    hits.append((py_path.relative_to(REPO_ROOT), i, line.strip()))
        except (OSError, UnicodeDecodeError):
            continue
    return hits


def find_methods_missing_from_source(
    docs: Dict[str, Set[str]],
    source_text: str,
) -> Dict[str, Set[str]]:
    """For each class.method documented in the API, return those whose
    method name does not appear in any src/*.py file at all.

    This is a coarse check (substring match) — it will not catch overload gaps
    or incomplete dict-key forwarding. Those are checked separately at
    development time, not in CI.
    """
    missing: Dict[str, Set[str]] = {}
    for cls, methods in docs.items():
        for method in methods:
            if method in IGNORE_METHODS:
                continue
            # A simple but effective signal: look for ".MethodName(" anywhere
            # in src/. Compound dispatchers and granular wrappers both call
            # `obj.MethodName(...)` — so this catches both layers in one pass.
            if f".{method}(" not in source_text:
                missing.setdefault(cls, set()).add(method)
    return missing


def find_undocumented_method_wrappers(
    docs: Dict[str, Set[str]],
    source_text: str,
) -> List[Tuple[str, str, int]]:
    """Find calls to .MethodName( in source where MethodName is NOT documented
    in any class of the API docs. Likely candidates for removal.

    Skips: dunder methods, common Python builtins, snake_case methods (which
    aren't Resolve API), and methods whose names overlap with stdlib/MCP.
    """
    documented: Set[str] = set()
    for methods in docs.values():
        documented.update(methods)

    skip_prefixes = ("Get", "Set", "Is", "Has", "Add", "Delete", "Create", "Update",
                     "Load", "Save", "Open", "Close", "Start", "Stop", "Import",
                     "Export", "Append", "Remove", "Move", "Copy", "Insert",
                     "Replace", "Find", "Reset", "Refresh", "Reveal", "Restore",
                     "Convert", "Detect", "Apply", "Render", "Transcribe", "Clear",
                     "Link", "Unlink", "Relink", "Sync", "Make", "Build", "Run",
                     "Generate", "Cancel", "Pause", "Resume", "Process", "Execute",
                     "Validate", "Initialize", "Quit", "Show", "Hide", "Mark",
                     "Auto", "Switch", "Assign", "Monitor", "Disable", "Enable",
                     "Modify", "Duplicate", "Merge", "Split", "Trim", "Slip",
                     "Slide", "Scale", "Rotate", "Flip", "Crop")

    # Find every .MethodName( call site
    call_pattern = re.compile(r"\.([A-Z][A-Za-z0-9_]+)\(")
    suspicious: List[Tuple[str, str, int]] = []
    seen: Set[str] = set()

    for py_path in (REPO_ROOT / "src").rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        try:
            for i, line in enumerate(py_path.read_text().splitlines(), 1):
                for m in call_pattern.finditer(line):
                    name = m.group(1)
                    if name in documented or name in seen:
                        continue
                    if not any(name.startswith(p) for p in skip_prefixes):
                        continue
                    seen.add(name)
                    suspicious.append((str(py_path.relative_to(REPO_ROOT)), name, i))
        except (OSError, UnicodeDecodeError):
            continue
    return suspicious


def main() -> int:
    if not DOCS_PATH.exists():
        print(f"FAIL: API docs not found at {DOCS_PATH}", file=sys.stderr)
        return 1

    docs = parse_documented_methods(DOCS_PATH)
    source_text = collect_source_text()

    failures = 0

    print("=" * 70)
    print("Check 1: broken `from api.X import` imports (v2.3.2 bug class)")
    print("=" * 70)
    broken = find_broken_api_imports()
    if broken:
        for path, line_no, snippet in broken:
            print(f"  FAIL {path}:{line_no}  {snippet}")
        failures += len(broken)
    else:
        print("  OK — no broken api.* imports")

    print()
    print("=" * 70)
    print("Check 2: documented methods missing from source")
    print("=" * 70)
    missing = find_methods_missing_from_source(docs, source_text)
    if missing:
        for cls in sorted(missing):
            for m in sorted(missing[cls]):
                print(f"  MISSING {cls}.{m}")
                failures += 1
    else:
        print("  OK — every documented method appears somewhere in src/")

    print()
    print("=" * 70)
    print("Check 3: wrappers calling undocumented Resolve methods (advisory)")
    print("=" * 70)
    suspicious = find_undocumented_method_wrappers(docs, source_text)
    if suspicious:
        # Advisory only — these may legitimately be helper methods on non-Resolve
        # objects (e.g., MCP framework, FastMCP). Print but do not count as failure.
        for path, name, line in sorted(set(suspicious))[:30]:
            print(f"  REVIEW {path}:{line}  .{name}(")
        if len(suspicious) > 30:
            print(f"  ... and {len(suspicious) - 30} more (advisory only)")
    else:
        print("  OK — no suspicious method calls")

    print()
    print("=" * 70)
    if failures:
        print(f"FAIL — {failures} parity issue(s) found")
        return 1
    print("PASS — all checks clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
