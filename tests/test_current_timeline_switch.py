"""A discarded SetCurrentTimeline is work done on the wrong timeline.

`AppendToTimeline`, `GetCurrentTimeline` and every other "current timeline"
call writes to whatever the PROJECT believes is current, not to the handle in
scope. Seven callsites in src/server.py switched the current timeline and threw
the return away, six of them inside `try/except: pass`, which catches an
exception and never a `False`. The failure shape was the worst available: the
assembly happened, on the timeline the editor was looking at, and the tool
returned the NEW timeline's name and id as a success.

`edit_engine.execute_swap` was the sharpest case. The lift is handle-based and
hits the right timeline; the append that puts the replacement back is
current-timeline-based. A failed switch punched a hole in the target and
dropped the alternate somewhere else, and the handler still returned
`success: bool(appended)` = True.
"""

import unittest

from src.server import _set_current_timeline_checked


class _Timeline:
    def __init__(self, timeline_id):
        self.timeline_id = timeline_id

    def GetUniqueId(self):
        return self.timeline_id


class _Project:
    """SetCurrentTimeline as Resolve implements it: a bare bool, and on a
    failure the current timeline does not move."""

    def __init__(self, current=None, *, returns=True, moves=True, raises=False,
                 has_getter=True):
        self.current = current
        self.returns = returns
        self.moves = moves
        self.raises = raises
        self.has_getter = has_getter
        self.calls = []

    def SetCurrentTimeline(self, timeline):
        self.calls.append(timeline)
        if self.raises:
            raise RuntimeError("bridge is wedged")
        if self.moves:
            self.current = timeline
        return self.returns

    def GetCurrentTimeline(self):
        if not self.has_getter:
            raise AttributeError("GetCurrentTimeline")
        return self.current


class SetCurrentTimelineCheckedTest(unittest.TestCase):
    def test_a_real_switch_returns_no_error(self):
        wanted = _Timeline("tl-new")
        project = _Project(current=_Timeline("tl-old"))

        self.assertIsNone(
            _set_current_timeline_checked(project, wanted, what="the test")
        )
        self.assertIs(project.current, wanted)

    def test_a_false_return_is_a_structured_error(self):
        wanted = _Timeline("tl-new")
        project = _Project(current=_Timeline("tl-old"), returns=False, moves=False)

        out = _set_current_timeline_checked(project, wanted, what="assembling the selects")

        self.assertEqual(out["error"]["code"], "TIMELINE_SWITCH_FAILED")
        self.assertEqual(out["error"]["category"], "resolve_api_failed")
        self.assertFalse(out["error"]["retryable"])
        self.assertIn("assembling the selects", out["error"]["message"])
        self.assertEqual(out["error"]["state"]["wanted_timeline_id"], "tl-new")
        self.assertEqual(out["error"]["state"]["current_timeline_id"], "tl-old")

    def test_a_true_that_did_not_take_is_caught_by_the_readback(self):
        """Observed on a Resolve attached to no database: True, no switch."""
        wanted = _Timeline("tl-new")
        project = _Project(current=_Timeline("tl-old"), returns=True, moves=False)

        out = _set_current_timeline_checked(project, wanted, what="the test")

        self.assertEqual(out["error"]["code"], "TIMELINE_SWITCH_FAILED")

    def test_an_exception_is_reported_not_swallowed(self):
        project = _Project(raises=True)

        out = _set_current_timeline_checked(project, _Timeline("tl-new"), what="the test")

        self.assertEqual(out["error"]["code"], "TIMELINE_SWITCH_FAILED")
        self.assertIn("bridge is wedged", out["error"]["message"])

    def test_a_missing_getter_falls_back_to_the_bool(self):
        """A weaker check, not a reason to refuse the work."""
        project = _Project(has_getter=False)

        self.assertIsNone(
            _set_current_timeline_checked(project, _Timeline("tl-new"), what="the test")
        )

    def test_a_missing_getter_plus_a_false_still_fails(self):
        project = _Project(has_getter=False, returns=False, moves=False)

        out = _set_current_timeline_checked(project, _Timeline("tl-new"), what="the test")

        self.assertEqual(out["error"]["code"], "TIMELINE_SWITCH_FAILED")


class CallsitesRefuseInsteadOfWritingElsewhereTest(unittest.TestCase):
    """The class-level guard: no bare, unchecked SetCurrentTimeline in src/."""

    def test_no_callsite_discards_the_return(self):
        import ast
        import pathlib

        root = pathlib.Path(__file__).resolve().parent.parent / "src"
        offenders = []
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Expr):
                    continue
                call = node.value
                if not isinstance(call, ast.Call):
                    continue
                func = call.func
                if isinstance(func, ast.Attribute) and func.attr == "SetCurrentTimeline":
                    offenders.append(f"{path.relative_to(root.parent)}:{node.lineno}")
        self.assertEqual(
            offenders, [],
            "SetCurrentTimeline's return is discarded here. A False leaves the "
            "project on the old timeline while the caller reports success:\n  "
            + "\n  ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
