"""Query the shipped Resolve 21.1 typed stub from inside the server.

PR #205 landed Blackmagic's `DaVinciResolveScript.pyi` in `docs/reference/`, and
`scripts/audit_typed_api.py` can turn it into a full inventory — but only from a
shell. An agent talking to this server had no way to ask what the native API
contains. `resolve_control api_truth` answers "what is broken"; nothing answered
"what exists".

The official Blackmagic MCP exposes `search_scripting_api` for this. This is the
equivalent, with one addition that matters more here: each result says whether
**this server** references the method, and where. That turns a lookup into a
parity check — "does the native API have it, and do we wrap it?" — which is the
question that drove the whole 21.1 audit.

Parsing is `ast`-based and reuses the same shapes as the audit script. Source
references are executable syntax only: a method named in a docstring or comment
is not counted as coverage.
"""

import ast
import os
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional

STUB_RELATIVE = os.path.join("docs", "reference", "DaVinciResolveScript.pyi")
MAX_RESULTS = 200


class TypedApiError(ValueError):
    """The stub is missing, unparseable, or the query was unusable."""


def stub_path(project_dir: str) -> str:
    return os.path.join(project_dir, STUB_RELATIVE)


@lru_cache(maxsize=4)
def _inventory(path: str, mtime: float) -> Dict[str, Any]:
    """Parse the stub into methods and TypedDicts. Cached on path plus mtime."""
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    methods: Dict[str, Any] = {}
    option_types: Dict[str, Any] = {}
    for cls in ast.parse(text).body:
        if not isinstance(cls, ast.ClassDef):
            continue
        for node in cls.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
                signature = f"{node.name}({ast.unparse(node.args)})"
                if node.returns is not None:
                    signature += f" -> {ast.unparse(node.returns)}"
                row = methods.setdefault(f"{cls.name}.{node.name}", {
                    "object": cls.name,
                    "method": node.name,
                    "signatures": [],
                    "stub_line": node.lineno,
                    "description": ast.get_docstring(node),
                })
                row["signatures"].append(signature)
        if any(ast.unparse(base).endswith("TypedDict") for base in cls.bases):
            fields: Dict[str, Any] = {}
            for index, node in enumerate(cls.body):
                if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    doc = None
                    if index + 1 < len(cls.body):
                        following = cls.body[index + 1]
                        if (isinstance(following, ast.Expr)
                                and isinstance(following.value, ast.Constant)
                                and isinstance(following.value.value, str)):
                            doc = following.value.value
                    fields[node.target.id] = {"type": ast.unparse(node.annotation),
                                              "stub_line": node.lineno,
                                              "description": doc}
            option_types[cls.name] = fields
    if not methods:
        raise TypedApiError("The typed stub contains no public class methods; refusing an empty inventory")
    return {"methods": methods, "option_types": option_types}


def load(project_dir: str) -> Dict[str, Any]:
    path = stub_path(project_dir)
    if not os.path.isfile(path):
        raise TypedApiError(
            f"Typed API stub not found at {STUB_RELATIVE}. It ships with this "
            "repository; a source checkout is required for API search."
        )
    return _inventory(path, os.path.getmtime(path))


@lru_cache(maxsize=4)
def _wrapped_names(project_dir: str, fingerprint: str) -> Dict[str, List[str]]:
    """Map native method name -> source files that actually call or read it.

    Executable syntax only. A name that appears solely in a docstring or comment
    is not coverage, and counting it as such is exactly the mistake this whole
    audit existed to avoid.
    """
    found: Dict[str, set] = {}
    src_root = os.path.join(project_dir, "src")
    for current, _dirs, files in os.walk(src_root):
        for filename in files:
            if not filename.endswith(".py"):
                continue
            absolute = os.path.join(current, filename)
            try:
                with open(absolute, "r", encoding="utf-8", errors="replace") as handle:
                    tree = ast.parse(handle.read())
            except (OSError, SyntaxError):
                continue
            relative = os.path.relpath(absolute, project_dir).replace(os.sep, "/")
            for node in ast.walk(tree):
                name = None
                if isinstance(node, ast.Attribute):
                    name = node.attr
                elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                      and node.func.id == "getattr" and len(node.args) > 1
                      and isinstance(node.args[1], ast.Constant)
                      and isinstance(node.args[1].value, str)):
                    name = node.args[1].value
                if name:
                    found.setdefault(name, set()).add(relative)
    return {name: sorted(paths) for name, paths in found.items()}


def _source_fingerprint(project_dir: str) -> str:
    """Cheap change detector for the source tree: newest mtime plus file count."""
    newest = 0.0
    count = 0
    for current, _dirs, files in os.walk(os.path.join(project_dir, "src")):
        for filename in files:
            if filename.endswith(".py"):
                count += 1
                try:
                    newest = max(newest, os.path.getmtime(os.path.join(current, filename)))
                except OSError:
                    pass
    return f"{count}:{newest}"


def search(project_dir: str, pattern: str, *, kind: str = "all",
           limit: int = 50) -> Dict[str, Any]:
    """Case-insensitive regex over method names, signatures, types and docs."""
    if not isinstance(pattern, str) or not pattern.strip():
        raise TypedApiError("pattern is required")
    if kind not in ("all", "methods", "options"):
        raise TypedApiError(f"kind must be all, methods or options, not {kind!r}")
    try:
        expression = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise TypedApiError(f"pattern is not a valid regular expression: {exc}")
    try:
        limit = max(1, min(int(limit), MAX_RESULTS))
    except (TypeError, ValueError):
        raise TypedApiError("limit must be an integer")

    inventory = load(project_dir)
    wrapped = _wrapped_names(project_dir, _source_fingerprint(project_dir))

    methods: List[Dict[str, Any]] = []
    if kind in ("all", "methods"):
        for key, row in sorted(inventory["methods"].items()):
            haystack = " ".join([key] + row["signatures"] + [row["description"] or ""])
            if not expression.search(haystack):
                continue
            references = wrapped.get(row["method"], [])
            methods.append({
                "symbol": key,
                "object": row["object"],
                "signatures": row["signatures"],
                "stub_line": row["stub_line"],
                "description": row["description"],
                "referenced_in_this_server": bool(references),
                "source_files": references[:5],
            })

    options: List[Dict[str, Any]] = []
    if kind in ("all", "options"):
        for type_name, fields in sorted(inventory["option_types"].items()):
            matched = {
                field: detail for field, detail in fields.items()
                if expression.search(" ".join([type_name, field, detail["type"],
                                               detail["description"] or ""]))
            }
            if expression.search(type_name):
                matched = dict(fields)
            if matched:
                options.append({
                    "type": type_name,
                    "field_count": len(fields),
                    "matched_fields": matched,
                })

    total = len(methods) + len(options)
    return {
        "pattern": pattern,
        "kind": kind,
        "total_matches": total,
        "truncated": total > limit,
        "methods": methods[:limit],
        "option_types": options[:limit],
        "stub": STUB_RELATIVE,
        "note": ("referenced_in_this_server is executable syntax only — a name that "
                 "appears solely in a docstring or comment is not counted."),
    }


def describe(project_dir: str, symbol: str) -> Dict[str, Any]:
    """Full detail for one `Class.Method` or one TypedDict name."""
    if not isinstance(symbol, str) or not symbol.strip():
        raise TypedApiError("symbol is required")
    inventory = load(project_dir)
    key = symbol.strip()

    if key in inventory["option_types"]:
        fields = inventory["option_types"][key]
        return {"symbol": key, "kind": "option_type", "field_count": len(fields),
                "fields": fields, "stub": STUB_RELATIVE}

    row = inventory["methods"].get(key)
    if row is None:
        candidates = sorted(k for k in inventory["methods"] if k.split(".", 1)[1] == key)
        if len(candidates) == 1:
            key, row = candidates[0], inventory["methods"][candidates[0]]
        elif candidates:
            raise TypedApiError(
                f"{symbol!r} exists on more than one object: {', '.join(candidates)}. "
                "Qualify it, e.g. 'Project.GetName'."
            )
        else:
            raise TypedApiError(
                f"{symbol!r} is not in the Resolve 21.1 typed stub. Use search to "
                "find the right name."
            )

    wrapped = _wrapped_names(project_dir, _source_fingerprint(project_dir))
    references = wrapped.get(row["method"], [])
    return {
        "symbol": key,
        "kind": "method",
        "object": row["object"],
        "signatures": row["signatures"],
        "stub_line": row["stub_line"],
        "description": row["description"],
        "referenced_in_this_server": bool(references),
        "source_files": references,
        "stub": STUB_RELATIVE,
    }


def summary(project_dir: str) -> Dict[str, Any]:
    inventory = load(project_dir)
    field_total = sum(len(fields) for fields in inventory["option_types"].values())
    return {
        "stub": STUB_RELATIVE,
        "methods": len(inventory["methods"]),
        "option_types": len(inventory["option_types"]),
        "option_fields": field_total,
        "objects": sorted({row["object"] for row in inventory["methods"].values()}),
    }
