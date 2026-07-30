"""Static guard: an optional-dependency flag must actually guard every use.

The bug class this exists for::

    try:
        import librosa
        HAVE_LIBROSA = True
    except ImportError:
        HAVE_LIBROSA = False
    ...
    if HAVE_LIBROSA: ...        # guarded here
    ...
    y, sr = librosa.load(path)  # and NOT here -> bare NameError on a default install

pyflakes cannot see it: the name *is* bound inside the `try`, so it is a legal
module-level binding as far as static analysis is concerned. The failure only
appears on a machine without the optional package — i.e. the default install,
i.e. not the developer's.

Legitimate shapes, all of which appear in this codebase and all of which are
accepted:

1. **Total fallback** — the `except` handler rebinds the same name to a working
   default, so the name is unconditionally available and no guard is needed.
2. **Local guard** — the use sits inside an `if <FLAG>` / `if <module> is not
   None` branch.
3. **Early-exit guard** — a function opens with ``if _mod is None: raise/return``,
   which makes the rest of that function safe.
4. **Identity test** — ``_mod is None`` is itself safe; it is the check.
5. **Declared module contract** — the module sets ``_OPTIONAL_DEPENDENCY_CONTRACT``
   to a sentence explaining that every caller passes a capability gate. This is
   machine-readable on purpose: a contract that only exists in a comment two
   hundred lines away is not a contract anyone can find.

A module doing none of these fails here.
"""

from __future__ import annotations

import ast
import pathlib
import unittest

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"

#: A module declaring this asserts shape 5 — every caller passes a capability
#: gate. Machine-readable so the contract is greppable, not buried in a comment.
CONTRACT_CONSTANT = "_OPTIONAL_DEPENDENCY_CONTRACT"


def _optional_imports(tree: ast.Module) -> dict[str, str]:
    """{bound_name: flag_name_or_empty} for imports inside a module-level try.

    Excluded as unconditionally bound (shape 1, a total fallback), whether the
    default is written before the try (``dvr_script = None`` then
    ``import ... as dvr_script``) or in the handler — both leave the name
    always defined, so neither needs a guard.
    """
    def _is_working_default(value: ast.expr) -> bool:
        """A fallback only makes a name safe if it is usable.

        ``_np = None`` is a sentinel, not a default: a bare ``_np.asarray(...)``
        still crashes, merely with AttributeError instead of NameError. Only a
        non-None fallback (an inlined word set, a shim object) removes the need
        for a guard.
        """
        return not (isinstance(value, ast.Constant) and value.value is None)

    predefined: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and _is_working_default(node.value):
            predefined.update(t.id for t in node.targets if isinstance(t, ast.Name))

    found: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Try):
            continue
        bound: list[str] = []
        for child in ast.walk(node):
            if isinstance(child, ast.Import):
                bound += [(a.asname or a.name.split(".")[0]) for a in child.names]
            elif isinstance(child, ast.ImportFrom):
                bound += [(a.asname or a.name) for a in child.names]
        if not bound:
            continue
        rebound: set[str] = set()
        for handler in node.handlers:
            for child in ast.walk(handler):
                if isinstance(child, ast.Assign) and _is_working_default(child.value):
                    rebound.update(t.id for t in child.targets if isinstance(t, ast.Name))
        flag = ""
        for child in ast.walk(node):
            if isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Name) and target.id.isupper():
                        flag = target.id
        for name in bound:
            if name in rebound or name in predefined:
                continue  # shape 1: total fallback, always bound
            found[name] = flag
    return found


def _declares_contract(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == CONTRACT_CONSTANT for t in node.targets):
                return True
    return False


def _same_try_lines(tree: ast.Module) -> set[int]:
    """Lines inside the very `try` body that performs the import.

    Reaching them at all means the import succeeded — control is in the `except`
    otherwise. This is the ``import x; use(x)`` shape.
    """
    lines: set[int] = set()
    for node in tree.body:
        if not isinstance(node, ast.Try):
            continue
        has_import = any(isinstance(c, (ast.Import, ast.ImportFrom)) for c in ast.walk(node))
        if not has_import:
            continue
        for statement in node.body:
            for child in ast.walk(statement):
                if hasattr(child, "lineno"):
                    lines.add(child.lineno)
    return lines


def _early_exit_guarded_lines(tree: ast.Module, names: set[str]) -> set[int]:
    """Lines after an `if <name> is None: raise/return` inside the same function.

    Walks nested blocks, not just the function's top level — the guard is often
    inside a `with` (a lock) rather than the first statement.
    """
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for statement in ast.walk(node):
            if not isinstance(statement, ast.If):
                continue
            mentioned = {n.id for n in ast.walk(statement.test) if isinstance(n, ast.Name)}
            if not (mentioned & names):
                continue
            if not any(isinstance(b, (ast.Raise, ast.Return)) for b in statement.body):
                continue
            end = getattr(node, "end_lineno", None) or statement.lineno
            lines.update(range(statement.lineno, end + 1))
    return lines


def _identity_test_lines(tree: ast.Module, names: set[str]) -> set[int]:
    """`x is None` / `x is not None` is the check itself, never an unsafe use."""
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and any(
            isinstance(op, (ast.Is, ast.IsNot)) for op in node.ops
        ):
            mentioned = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            if mentioned & names:
                for child in ast.walk(node):
                    if hasattr(child, "lineno"):
                        lines.add(child.lineno)
    return lines


def _guard_lines(tree: ast.Module, names: set[str]) -> set[int]:
    """Line numbers of `if` tests that mention any guarded name or its flag."""
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.IfExp)):
            mentioned = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
            if mentioned & names:
                for child in ast.walk(node):
                    if hasattr(child, "lineno"):
                        lines.add(child.lineno)
        elif isinstance(node, ast.BoolOp):
            mentioned = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            if mentioned & names:
                lines.add(node.lineno)
    return lines


class OptionalDependencyGuardTest(unittest.TestCase):
    def test_every_optional_import_guards_all_of_its_uses(self) -> None:
        problems: list[str] = []
        checked = 0
        for path in sorted(SRC.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(source)
            except SyntaxError:  # pragma: no cover - would fail elsewhere first
                continue
            optional = _optional_imports(tree)
            if not optional:
                continue
            checked += 1
            if _declares_contract(tree):
                continue  # shape 5: declared module-wide caller contract
            names = set(optional) | {f for f in optional.values() if f}
            safe = (
                _guard_lines(tree, names)
                | _early_exit_guarded_lines(tree, names)
                | _identity_test_lines(tree, names)
                | _same_try_lines(tree)
            )
            for node in ast.walk(tree):
                if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
                    continue
                if node.id not in optional or node.lineno in safe:
                    continue
                problems.append(
                    f"{path.relative_to(SRC.parent)}:{node.lineno}: {node.id!r} used with no "
                    f"guard and no documented caller contract"
                )
        self.assertGreater(checked, 0, "guard found no optional imports — parser broken?")
        self.assertEqual(problems, [], "\n".join(problems))

    def test_the_guard_catches_the_bug_it_exists_for(self) -> None:
        """A negative control: the real-world shape must be detected."""
        bad = ast.parse(
            "try:\n"
            "    import librosa\n"
            "    HAVE_LIBROSA = True\n"
            "except ImportError:\n"
            "    HAVE_LIBROSA = False\n"
            "\n"
            "def analyze(path):\n"
            "    return librosa.load(path)\n"
        )
        optional = _optional_imports(bad)
        self.assertIn("librosa", optional)
        names = set(optional) | {optional["librosa"]}
        safe = _guard_lines(bad, names)
        unguarded = [
            n.lineno for n in ast.walk(bad)
            if isinstance(n, ast.Name) and n.id == "librosa"
            and isinstance(n.ctx, ast.Load) and n.lineno not in safe
        ]
        self.assertTrue(unguarded, "the guard would not have caught the bug it exists for")

    def test_the_guard_accepts_a_properly_guarded_module(self) -> None:
        """A positive control: a correct guard must not be flagged."""
        good = ast.parse(
            "try:\n"
            "    import librosa\n"
            "    HAVE_LIBROSA = True\n"
            "except ImportError:\n"
            "    HAVE_LIBROSA = False\n"
            "\n"
            "def analyze(path):\n"
            "    if HAVE_LIBROSA:\n"
            "        return librosa.load(path)\n"
            "    return None\n"
        )
        optional = _optional_imports(good)
        names = set(optional) | {optional["librosa"]}
        safe = _guard_lines(good, names)
        unguarded = [
            n.lineno for n in ast.walk(good)
            if isinstance(n, ast.Name) and n.id == "librosa"
            and isinstance(n.ctx, ast.Load) and n.lineno not in safe
        ]
        self.assertEqual(unguarded, [])


if __name__ == "__main__":
    unittest.main()
