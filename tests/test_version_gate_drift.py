"""Static guard: the version floors in the code and in the ledger agree.

Two places in this repo know that a scripting method needs a given Resolve
build, and for a long time they did not talk to each other:

1. The call sites. `_requires_method(obj, "GetLayoutPresetList", "21.0.4")`
   refuses the call when the method is absent and names the floor.
2. `resolve_versions.VERSION_GATES`, which is what
   `resolve_control(action="check_version_support")` answers from.

The servers gated thirty-one symbols while the ledger knew seven, so the one
call an agent is *told* to make answered `unknown` for surfaces this repo was
already routing on — build-aware behaviour that could not be asked about. That
is issue #132's remaining half showing up inside our own tooling, and a table
copied by hand is exactly the thing that drifts back apart, so it gets a guard.

The second half of this file is the other way the same lie gets told:
`if not hasattr(obj, "Method")` reads like a capability check and is a constant
`True` on Resolve API objects — measured on Studio 19.1.3.7 across 42 checks,
recorded in `api_truth` under "hasattr() / getattr() on Resolve API objects".
Eleven of those guards shipped in `src/granular/`, where they could never fire.
"""

import ast
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

import sys

sys.path.insert(0, str(ROOT))

from src.utils.resolve_versions import (  # noqa: E402
    CODE_FLOORS,
    UNDATED_FLOORS,
    VERSION_GATES,
    parse_version,
)

#: Modules that gate calls on a Resolve build.
GATING_MODULES = [SRC / "server.py"] + sorted((SRC / "granular").glob("*.py"))


def _requires_method_calls(tree):
    """Yield (method, floor, lineno) for each literal `_requires_method` call."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "_requires_method"):
            continue
        if len(node.args) != 3:
            continue
        method, floor = node.args[1], node.args[2]
        if isinstance(method, ast.Constant) and isinstance(floor, ast.Constant):
            yield str(method.value), str(floor.value), node.lineno


def _bare_method(symbol: str) -> str:
    """`Resolve.GetLayoutPresetList` -> `GetLayoutPresetList`."""
    return symbol.rsplit(".", 1)[-1].split(" ", 1)[0]


class VersionGateDriftTest(unittest.TestCase):
    def test_every_gated_call_site_is_recorded_in_the_ledger(self):
        """A floor the code enforces must be a floor an agent can ask about."""
        gates = {_bare_method(g["symbol"]): g["introduced_in"] for g in VERSION_GATES}
        undated = {_bare_method(s) for s in UNDATED_FLOORS}
        missing, disagreeing = [], []
        for path in GATING_MODULES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for method, floor, lineno in _requires_method_calls(tree):
                where = f"{path.relative_to(ROOT)}:{lineno} {method}"
                if parse_version(floor) is None:
                    # No usable floor at the call site. Recording it as undated
                    # is honest; silently skipping it is how one goes missing.
                    if method not in undated:
                        missing.append(f"{where} names an unparseable floor "
                                       f"{floor!r} and is not in UNDATED_FLOORS")
                    continue
                if method not in gates:
                    missing.append(f"{where} gates on {floor} with no entry in "
                                   "CODE_FLOORS or VERSION_GATES")
                elif parse_version(gates[method]) != parse_version(floor):
                    disagreeing.append(f"{where} says {floor}, the ledger says "
                                       f"{gates[method]}")
        self.assertEqual(
            [], missing + disagreeing,
            "src/utils/resolve_versions.py has drifted from the call sites. "
            "check_version_support answers from the ledger, so anything absent "
            "here is a build gate an agent cannot ask about:\n  "
            + "\n  ".join(missing + disagreeing),
        )

    def test_a_bare_method_name_never_carries_two_different_floors(self):
        """`gate_for` accepts a bare name, so the classes must agree on it.

        `SetName` is gated on four classes. A lookup for the bare name can only
        stay honest while every class that gates it names the same floor; if
        Blackmagic ever introduces one later than another, the bare-name answer
        becomes a coin flip and this fails rather than lying quietly.
        """
        floors = {}
        for gate in VERSION_GATES:
            floors.setdefault(_bare_method(gate["symbol"]), set()).add(
                gate["introduced_in"]
            )
        conflicts = {name: sorted(vs) for name, vs in floors.items() if len(vs) > 1}
        self.assertEqual(
            {}, conflicts,
            "These method names are gated at different builds on different "
            "classes, so a bare-name lookup cannot answer honestly. Qualify the "
            "lookups, or teach gate_for to refuse: " + repr(conflicts),
        )

    def test_recorded_floors_all_parse(self):
        for symbol, floor in CODE_FLOORS.items():
            self.assertIsNotNone(parse_version(floor), f"{symbol}: {floor!r}")


#: A Resolve API name: `GetUniqueId`, `RemoveMotionBlur`, `EXPORT_AAF`. Ordinary
#: Python attributes (`json`, `__len__`, `read`) do not match, and `hasattr` is
#: correct for those — this guard is about Resolve objects only.
RESOLVE_NAME = re.compile(r"^[A-Z][A-Za-z0-9_]{2,}$")


def _hasattr_calls_needing_review(tree):
    """`hasattr` calls on Resolve-shaped names, minus the already-safe form.

    `hasattr(o, "X") and callable(getattr(o, "X"))` is fine — the callable half
    carries the whole test and the hasattr half is merely redundant. Only a
    `hasattr` standing on its own is load-bearing, and therefore wrong.
    """
    exempt = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.BoolOp):
            continue
        if not any(isinstance(v, ast.Call) and isinstance(v.func, ast.Name)
                   and v.func.id == "callable" for v in node.values):
            continue
        for value in node.values:
            if (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                    and value.func.id == "hasattr"):
                exempt.add((value.lineno, value.col_offset))

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "hasattr" and len(node.args) == 2):
            continue
        if (node.lineno, node.col_offset) in exempt:
            continue
        name = node.args[1]
        if isinstance(name, ast.Constant) and isinstance(name.value, str):
            if RESOLVE_NAME.match(name.value):
                yield node.lineno, repr(name.value)
        elif isinstance(name, ast.Name):
            # A name computed at runtime. On these code paths it is always a
            # Resolve method or constant, and the safe form costs nothing.
            yield node.lineno, f"<{name.id}>"


class HasattrCapabilityGuardTest(unittest.TestCase):
    """`hasattr(resolve_obj, "Method")` is a constant True, so it cannot guard.

    Measured on Studio 19.1.3.7, direct connection, 42 checks: bare `hasattr`
    returns True for EVERY name on every Resolve object — real, borrowed from
    another object type, or invented — while `getattr` returns None for the ones
    that do not exist. Two shapes shipped from that:

      - `if not hasattr(clip, "RemoveMotionBlur")` — a dead branch, so the
        "requires Resolve 21+" refusal never fired and the user got an
        AttributeError from the line below it instead.
      - `getattr(r, n) if hasattr(r, n) else n` — the else never fired either,
        so a build without the constant got `None` where the author had written
        a string fallback, and the None travelled on into `Export()`.

    Use `src/utils/resolve_probe.has_method` / `api_constant`.
    """

    def test_no_bare_hasattr_probes_on_resolve_objects(self):
        offenders = []
        for path in sorted(SRC.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for lineno, name in _hasattr_calls_needing_review(tree):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno} {name}")
        self.assertEqual(
            [], offenders,
            "hasattr is a constant True on Resolve API objects, so these probes "
            "cannot distinguish anything. Use has_method() for methods and "
            "api_constant() for EXPORT_*-style constants:\n  "
            + "\n  ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
