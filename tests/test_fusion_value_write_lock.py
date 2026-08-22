"""Fusion value writes must not be wrapped in comp.Lock()/Unlock().

A value write (SetInput / SetExpression) wrapped in a comp lock lands in the
graph and reads back correctly — GetInput returns it, and so does the server's
own `get_input` — while the RENDER ignores it completely.

Measured live on DaVinci Resolve Studio 19.1.3.7 (2026-08-21), on a
MediaIn -> Blur(XBlurSize 20) -> MediaOut comp attached to a media-backed clip:

    value written through fusion_comp set_input (locked)   PSNR inf     IGNORED
    same value written with the lock removed               PSNR 24.38dB RENDERED
    same value written raw, tool.XBlurSize = 20.0          PSNR 24.38dB RENDERED
    same value written raw, tool.SetInput(...)             PSNR 24.38dB RENDERED

The variable was isolated against the comp handle (AddFusionComp,
GetFusionCompByIndex and GetFusionCompByName all render), the node name, and
the write form. Only the lock around the write decides it.

Scope, settled in v2.98.8 by mutation-checking every site with a render: four of
the six locked paths are genuinely broken — `set_input`, `safe_set_inputs`,
`set_text_plus`, `add_fusion_mask`. The two that escape, `bulk_set_inputs` and
`bulk_set_expressions`, do so because they wrap their write in
`StartUndo`/`EndUndo`.

An earlier reading (v2.98.6) had this the other way round, because the two
test cases for `set_text_plus` and `add_fusion_mask` primed their comps with
setup writes and could not fail. Any unlocked value write anywhere in a comp
clears the condition, so this guard refuses a lock around ANY value write rather
than encoding which call shapes happen to get away with it.

This is a STATIC guard because the real proof needs a render: see
`tests/live_fusion_value_write_validation.py`, which measures it end to end.
A static guard is still worth having — the failure is invisible to every
readback the API offers, so a reintroduced lock would otherwise go unnoticed
until someone diffed a delivered frame.

Structural edits (AddTool, ConnectInput, LoadSettings, SetAttrs) are a
different case: they invalidate the render through another path, were verified
to render while locked, and deliberately keep their locks.
"""

from __future__ import annotations

import ast
import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(REPO_ROOT, "src", "server.py")

# Calls that write a VALUE into a Fusion tool. A lock around any of these is
# the bug. Structural calls are intentionally absent.
VALUE_WRITE_METHODS = frozenset({"SetInput", "SetExpression"})


def _method_name(node: ast.AST):
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _is_comp_lock(node: ast.AST) -> bool:
    """`<something>.Lock()` — the receiver is a comp in every current use."""
    return _method_name(node) == "Lock"


def _value_writes_under(node: ast.AST):
    """Value-write method names anywhere beneath `node`."""
    found = []
    for child in ast.walk(node):
        name = _method_name(child)
        if name in VALUE_WRITE_METHODS:
            found.append((name, getattr(child, "lineno", "?")))
    return found


class FusionValueWriteLockTests(unittest.TestCase):
    def test_no_value_write_happens_inside_a_comp_lock(self) -> None:
        tree = ast.parse(open(SERVER, encoding="utf-8").read(), filename=SERVER)

        offenders = []
        for node in ast.walk(tree):
            # The shape is: comp.Lock(); try: <writes>; finally: comp.Unlock()
            if not isinstance(node, ast.Try):
                continue
            prev_is_lock = False
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.Expr) and _is_comp_lock(stmt.value):
                    prev_is_lock = True
                    break
            # A Try whose finally calls Unlock is the locked region.
            finally_unlocks = any(
                _method_name(getattr(s, "value", None)) == "Unlock"
                for s in node.finalbody
                if isinstance(s, ast.Expr)
            )
            if not finally_unlocks:
                continue
            for name, lineno in _value_writes_under(ast.Module(body=node.body, type_ignores=[])):
                offenders.append(f"{name} at src/server.py:{lineno}")
            del prev_is_lock

        self.assertEqual(
            offenders,
            [],
            "Fusion value write(s) wrapped in comp.Lock()/Unlock(). Measured on "
            "Studio 19.1.3.7, a bare numeric SetInput under a lock reads back "
            "correctly and is IGNORED at render (PSNR inf vs baseline). Four other "
            "locked call paths did not reproduce it, but which mechanism rescues "
            "them is unknown — so no value write gets a lock. Move the write "
            "outside; structural edits (AddTool/ConnectInput) may stay locked."
            "\nOffenders: " + ", ".join(offenders),
        )

    def test_the_guard_can_actually_see_a_violation(self) -> None:
        """A guard that cannot fail is not a guard."""
        bad = ast.parse(
            "comp.Lock()\n"
            "try:\n"
            "    tool.SetInput('XBlurSize', 20)\n"
            "finally:\n"
            "    comp.Unlock()\n"
        )
        seen = []
        for node in ast.walk(bad):
            if not isinstance(node, ast.Try):
                continue
            if not any(
                _method_name(getattr(s, "value", None)) == "Unlock"
                for s in node.finalbody
                if isinstance(s, ast.Expr)
            ):
                continue
            seen += _value_writes_under(ast.Module(body=node.body, type_ignores=[]))
        self.assertTrue(seen, "guard failed to flag a known-bad locked value write")


if __name__ == "__main__":
    unittest.main()
