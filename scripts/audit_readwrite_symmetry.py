#!/usr/bin/env python3
"""Audit read/write symmetry across the compound server's action surface.

For every mutating action (set_/add_/clear_/enable_/...) it checks whether a
matching read action (get_/list_/...) exists on the same tool, and reports the
asymmetries. The goal is to find write-without-read gaps before users have to —
the repeatable feature-discovery method behind R5.

Reads the `_unknown(action, [...])` lists in src/server.py, which enumerate every
action a tool accepts. Prints a markdown report.
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "src", "server.py")

READ_PREFIXES = ("get_", "list_", "probe_", "is_", "has_", "find_")
# `set_` is the high-signal class: a set with no get is a genuine readback gap.
# create_/add_/insert_/import_ are inherently writes that usually have no paired
# read of the same noun, so they're reported separately as low-signal.
HIGH_SIGNAL = ("set_",)
LOW_SIGNAL = ("add_", "create_", "insert_", "apply_", "import_")

STEM_READ_ALIASES = {
    # Resolve's public names often use enable/lock verbs on writes but enabled/
    # locked nouns on reads; keep the audit focused on real missing readbacks.
    "cache": ("cache_enabled",),
    "caps_preset": ("caps",),
    "track_enable": ("track_enabled",),
    "track_lock": ("track_locked",),
}

DIRECT_READ_ALIASES = {
    # mcp_update_status returns the persisted prompt policy and effective
    # decision, so set_mcp_update_policy has a direct readback without a get_
    # name.
    "mcp_update_policy": ("mcp_update_status",),
}


def _module_constants(tree: ast.Module):
    """Collect module-level named assignments without evaluating the module."""
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = (node.target,)
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                constants[target.id] = node.value
    return constants


def _resolve_actions(expr, constants, seen=None):
    """Resolve supported action-list expressions or return None."""
    seen = set() if seen is None else seen
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return [expr.value]
    if isinstance(expr, ast.Name):
        if expr.id in seen or expr.id not in constants:
            return None
        return _resolve_actions(expr=constants[expr.id], constants=constants,
                                 seen=seen | {expr.id})
    if isinstance(expr, (ast.List, ast.Tuple)):
        actions = []
        for element in expr.elts:
            if isinstance(element, ast.Starred):
                element = element.value
            resolved = _resolve_actions(element, constants, seen)
            if resolved is None:
                return None
            actions.extend(resolved)
        return actions
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
        left = _resolve_actions(expr.left, constants, seen)
        right = _resolve_actions(expr.right, constants, seen)
        if left is None or right is None:
            return None
        return left + right
    return None


def _action_lists(src: str):
    """Yield action lists passed to ``_unknown(action, ...)`` calls."""
    tree = ast.parse(src)
    constants = _module_constants(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name)
                and node.func.id == "_unknown"
                and len(node.args) >= 2
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == "action"):
            continue
        actions = _resolve_actions(node.args[1], constants)
        if actions is not None:
            yield actions


def _has_read(stem: str, aset: set) -> bool:
    # Match get_<stem>, list_<stem>, and plural get_<stem>s (e.g. add_keyframe -> get_keyframes).
    stems = {stem, *STEM_READ_ALIASES.get(stem, ())}
    candidates = set(DIRECT_READ_ALIASES.get(stem, ()))
    for candidate_stem in stems:
        candidates |= {rp + candidate_stem for rp in READ_PREFIXES}
        candidates |= {rp + candidate_stem + "s" for rp in READ_PREFIXES}
        candidates |= {rp + candidate_stem.rstrip("s") for rp in READ_PREFIXES}
    return bool(candidates & aset)


def audit(src: str):
    high, low, covered, total = set(), set(), 0, 0
    for actions in _action_lists(src):
        aset = set(actions)
        for a in actions:
            for wp in HIGH_SIGNAL + LOW_SIGNAL:
                if a.startswith(wp):
                    total += 1
                    stem = a[len(wp):]
                    if _has_read(stem, aset):
                        covered += 1
                    elif wp in HIGH_SIGNAL:
                        high.add(a)
                    else:
                        low.add(a)
                    break
    return total, covered, sorted(high), sorted(low)


def render_report(src: str) -> str:
    total, covered, high, low = audit(src)
    lines = [
        "<!-- Generated by scripts/audit_readwrite_symmetry.py — do not edit by hand. -->",
        "",
        "# Read/Write Symmetry Audit",
        "",
        f"- write-style action occurrences scanned: **{total}**",
        f"- write-style action occurrences with a matching read: **{covered}**",
        f"- distinct high-signal `set_` actions without a direct/known readback: **{len(high)}**",
        "",
    ]
    if high:
        lines += [
            "## High-signal gaps — `set_` with no direct/known readback",
            "",
        ]
        for a in high:
            lines.append(f"- `{a}`")
    lines += [
        "",
        f"## Low-signal (create/add/insert/apply/import — usually expected): "
        f"{len(low)} distinct names",
        "",
        ", ".join(f"`{a}`" for a in low),
    ]
    return "\n".join(lines).rstrip() + "\n"


def main():
    with open(SERVER, encoding="utf-8") as fh:
        src = fh.read()
    print(render_report(src), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
