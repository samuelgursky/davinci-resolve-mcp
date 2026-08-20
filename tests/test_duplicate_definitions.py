"""Static guard: no module-level name is defined twice under src/.

A second `def foo` silently replaces the first. In a 20k-line module like
`src/server.py` the two definitions can be thousands of lines apart, have
different signatures, and serve unrelated callers — so every existing caller of
the first one starts calling the second and fails at runtime, or worse, succeeds
with the wrong semantics.

pyflakes does not catch this. It reports "redefinition of *unused* name", so a
first definition that IS used before being shadowed passes clean — which is
exactly the dangerous case.

This is the same family as the silent-fallback class the `test_static_undefined_names`
guard covers: code that looks fine, imports fine, and is wrong at runtime.

Only true module-level definitions are checked. Definitions nested inside `if`,
`try`, or a class body are legitimate (platform/version branches) and are ignored.
"""

import ast
import pathlib
import unittest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"


def _module_level_definitions(tree: ast.Module):
    """Yield (name, lineno) for every top-level def/class in a parsed module."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield node.name, node.lineno


class DuplicateDefinitionTest(unittest.TestCase):
    def test_no_module_level_name_is_defined_twice(self):
        offenders = []
        for path in sorted(SRC.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError as exc:  # pragma: no cover - a parse break is its own failure
                self.fail(f"{path} does not parse: {exc}")
            seen = {}
            for name, lineno in _module_level_definitions(tree):
                if name in seen:
                    offenders.append(
                        f"{path.relative_to(SRC.parent)}:{lineno} redefines '{name}' "
                        f"(first defined at line {seen[name]})"
                    )
                else:
                    seen[name] = lineno
        self.assertEqual(
            offenders,
            [],
            "module-level names defined more than once — the later definition wins "
            "and silently replaces the earlier one:\n" + "\n".join(offenders),
        )

    def test_guard_detects_a_planted_duplicate(self):
        """The guard must actually fire; a scan that never fails is not a guard."""
        tree = ast.parse("def a():\n    pass\n\n\ndef a():\n    pass\n")
        names = [name for name, _ in _module_level_definitions(tree)]
        self.assertEqual(names, ["a", "a"])

    def test_nested_definitions_are_not_flagged(self):
        """Platform/version branches legitimately define the same name twice."""
        tree = ast.parse(
            "import sys\n"
            "if sys.platform == 'win32':\n"
            "    def p():\n        pass\n"
            "else:\n"
            "    def p():\n        pass\n"
        )
        self.assertEqual(list(_module_level_definitions(tree)), [])


if __name__ == "__main__":
    unittest.main()
