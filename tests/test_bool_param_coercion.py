"""Boolean tool params must honour "false", "no", "0" and "off".

server.py read ~160 boolean params with bare truthiness: ``p.get("k", True)``,
``bool(p.get("k", False))`` and ``if p.get("k"):``. A string "false" is truthy,
so the caller got the opposite of what they asked for. The ones that mattered:
``override_governance="false"`` skipped AI-governance enforcement,
``stop_render="false"`` stopped a running render to close the project,
``execute="false"`` ran propose_grade's execute path, ``clear_flags="false"``
cleared flags, and ``install``/``cleanup="false"`` installed and removed
extensions. Every read now goes through a coercer, and the two ratchets below
keep a bare read from coming back.

``allow_non_mcp_name`` and ``overwrite`` were already safe end to end — the
guard helpers and the install actions coerce at the point of use — so their
tests pin the handler-level contract (a real bool reaches the next layer).
"""
import ast
import pathlib
import unittest
from unittest import mock

from src import server as s

SERVER = pathlib.Path(s.__file__)
COERCERS = {"_coerce_bool", "_media_analysis_bool", "_setup_bool", "_explicit_bool_param"}
FALSE_SPELLINGS = ("false", "False", "no", "0", "off")


class GovernanceOverrideTest(unittest.TestCase):
    def _gate(self, params):
        check = {"applies": True, "exceeded": True, "tier": "standard", "warnings": ["over."]}
        with mock.patch.object(s, "_ai_governance_mode", return_value="enforce"), \
                mock.patch.object(s, "_ai_governance_check", return_value=check):
            return s._ai_governance_gate("render", params)

    def test_override_false_spellings_still_block(self):
        for key in ("override_governance", "overrideGovernance"):
            for spelling in FALSE_SPELLINGS:
                with self.subTest(key=key, spelling=spelling):
                    blocked = self._gate({key: spelling})
                    self.assertIsNotNone(blocked)
                    self.assertEqual(blocked["error"]["code"], "GOVERNANCE_BLOCKED")

    def test_override_true_still_overrides(self):
        self.assertIsNone(self._gate({"override_governance": "true"}))


class RenderingProject:
    def __init__(self):
        self.closed = False

    def IsRenderingInProgress(self):
        return True


class ProjectManagerStub:
    def __init__(self, proj):
        self.proj = proj
        self.close_calls = 0

    def GetCurrentProject(self):
        return self.proj

    def CloseProject(self, proj):
        self.close_calls += 1
        return True


class CloseDuringRenderTest(unittest.TestCase):
    def test_stop_render_false_spellings_refuse_to_close(self):
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                pm = ProjectManagerStub(RenderingProject())
                resolve = mock.Mock()
                resolve.GetProjectManager.return_value = pm
                stopper = mock.Mock(return_value={"safe": True})
                with mock.patch.object(s, "get_resolve", return_value=resolve), \
                        mock.patch("src.utils.project_cleanup.stop_render_before_close", stopper):
                    out = s.project_manager("close", {"stop_render": spelling})
                self.assertFalse(out.get("success", False), out)
                stopper.assert_not_called()
                self.assertEqual(pm.close_calls, 0)


def _proposal(**extra):
    return {
        "target_id": "item-1",
        "evidence_base": "Evidence base: frame 10 reads warm.",
        "frame_paths": ["/tmp/frame.png"],
        "operation_class": "direct",
        "cdl_delta_or_artifact": {"cdl": {"slope": [1, 1, 1]}},
        **extra,
    }


class ProposeGradeExecuteTest(unittest.TestCase):
    def test_execute_false_spellings_do_not_execute(self):
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                out = s._propose_grade(None, _proposal(execute=spelling))
                self.assertTrue(out.get("accepted"), out)
                self.assertIs(out.get("executed"), False)
                self.assertNotIn("error", out)


class ClearableItem:
    def __init__(self):
        self.cleared_flags = []
        self.clip_color_cleared = False

    def DeleteMarkersByColor(self, color):
        return True

    def ClearFlags(self, color):
        self.cleared_flags.append(color)
        return True

    def ClearClipColor(self):
        self.clip_color_cleared = True
        return True


class ClearAnnotationsTest(unittest.TestCase):
    def _clear(self, params):
        item = ClearableItem()
        with mock.patch.object(s, "_annotation_target", return_value=(item, None)):
            s._clear_annotations_by_scope(object(), {"scope": "timeline_item", **params})
        return item

    def test_clear_flags_false_spellings_keep_flags(self):
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                self.assertEqual(self._clear({"clear_flags": spelling}).cleared_flags, [])

    def test_clear_clip_color_false_spellings_keep_color(self):
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                self.assertFalse(self._clear({"clear_clip_color": spelling}).clip_color_cleared)

    def test_clear_flags_true_clears(self):
        self.assertEqual(self._clear({"clear_flags": True}).cleared_flags, ["All"])


class FuseProbeLifecycleTest(unittest.TestCase):
    def _probe(self, params):
        fuse_calls, script_calls = [], []

        def fake_fuse(action, args=None):
            fuse_calls.append(action)
            return {"success": True, "source": "-- " + s._FUSE_MARKER} if action == "template" else {"success": True}

        def fake_script(action, args=None):
            script_calls.append((action, dict(args or {})))
            return {"success": True}

        with mock.patch.object(s, "fuse_plugin", side_effect=fake_fuse), \
                mock.patch.object(s, "script_plugin", side_effect=fake_script):
            s._probe_fuse_lifecycle(params)
        return [a for a, _ in script_calls], script_calls

    def test_install_false_spellings_do_not_install(self):
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                actions, _ = self._probe({"install": spelling})
                self.assertNotIn("safe_install_extension", actions)

    def test_cleanup_false_spellings_keep_the_install(self):
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                actions, _ = self._probe({"install": True, "cleanup": spelling})
                self.assertIn("safe_install_extension", actions)
                self.assertNotIn("safe_remove_extension", actions)

    def test_default_installs_nothing_and_install_true_cleans_up(self):
        self.assertEqual(self._probe({})[0], [])
        self.assertEqual(self._probe({"install": True})[0],
                         ["safe_install_extension", "safe_remove_extension"])


class SafetyFlagContractTest(unittest.TestCase):
    """Already safe end to end; pin that a real bool leaves the handler."""

    def test_allow_non_mcp_name_false_spellings_refuse_project_create(self):
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                out = s._safe_project_create(mock.Mock(), mock.Mock(),
                                             {"name": "client_project", "allow_non_mcp_name": spelling})
                self.assertFalse(out.get("success", False), out)
                self.assertIn("_mcp_", str(out.get("error")))

    def test_overwrite_false_spellings_reach_install_as_false(self):
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                seen = {}

                def fake_fuse(action, args=None):
                    seen.update(args or {})
                    return {"success": True}

                with mock.patch.object(s, "fuse_plugin", side_effect=fake_fuse):
                    s._safe_install_extension({
                        "extension_type": "fuse", "name": "_mcp_probe",
                        "source": "-- " + s._FUSE_MARKER, "overwrite": spelling,
                    })
                self.assertIs(seen.get("overwrite"), False)


class TemplateOptionTest(unittest.TestCase):
    """Fuse/DCTL template options read the same flags from caller input."""

    def test_false_spellings_generate_the_false_variant(self):
        from src.utils import dctl_templates, fuse_templates
        cases = ((fuse_templates.per_pixel, "amount"), (fuse_templates.channel_op, "rgba_only"),
                 (dctl_templates.aces_idt, "parametric"), (dctl_templates.aces_odt, "parametric"))
        for generator, key in cases:
            off_variant = generator("_mcp_probe", {key: False})
            self.assertNotEqual(generator("_mcp_probe", {key: True}), off_variant)
            for spelling in FALSE_SPELLINGS:
                with self.subTest(template=generator.__name__, spelling=spelling):
                    self.assertEqual(generator("_mcp_probe", {key: spelling}), off_variant)


def _tree_and_parents():
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return tree, parents


def _is_str_get(node):
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get" and node.args
            and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str))


def _in_coercer(node, parents):
    parent = parents.get(node)
    return (isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name)
            and parent.func.id in COERCERS)


class NoBareBooleanReadsTest(unittest.TestCase):
    """Ratchet: ``x.get("k", True|False)`` in server.py sits inside a coercer.

    A boolean default marks the key as boolean, so a bare read of it is the bug.
    NON_BOOLEAN_KEYS is for a key verified to carry non-bool values; it is empty
    because every key found in the sweep was a real flag.
    """

    NON_BOOLEAN_KEYS: frozenset = frozenset()

    def test_every_boolean_default_read_is_coerced(self):
        tree, parents = _tree_and_parents()
        bare = []
        for node in ast.walk(tree):
            if not (_is_str_get(node) and len(node.args) == 2
                    and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, bool)):
                continue
            if node.args[0].value in self.NON_BOOLEAN_KEYS:
                continue
            # the innermost of a fallback chain: p.get("a", p.get("b", False))
            outer = node
            while _is_str_get(parents.get(outer)) and parents[outer].args[-1] is outer:
                outer = parents[outer]
            if not _in_coercer(outer, parents):
                bare.append(f"line {node.lineno}: {ast.unparse(outer)}")
        self.assertEqual(bare, [], "boolean params read without a coercer:\n" + "\n".join(bare))


class NoBareTruthinessOfBooleanKeysTest(unittest.TestCase):
    """Ratchet: a key coerced somewhere is never tested with bare truthiness.

    Catches ``if p.get("install"):`` for a key that is a flag elsewhere in the
    file. SKIP lists receivers that hold server-built values, not caller input.
    """

    CALLER_RECEIVERS = {"p", "params", "target"}

    def test_boolean_keys_are_not_read_bare_in_a_truth_context(self):
        tree, parents = _tree_and_parents()
        boolean_keys = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in COERCERS:
                arg = node.args[0] if node.args else None
                while _is_str_get(arg):
                    boolean_keys.add(arg.args[0].value)
                    arg = arg.args[1] if len(arg.args) > 1 else None

        def truth_context(node):
            parent = parents.get(node)
            if isinstance(parent, (ast.If, ast.While, ast.IfExp, ast.Assert)) and parent.test is node:
                return True
            if isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.Not):
                return True
            if isinstance(parent, ast.BoolOp):
                return True
            return (isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name)
                    and parent.func.id == "bool")

        bare = []
        for node in ast.walk(tree):
            if (_is_str_get(node) and len(node.args) == 1
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in self.CALLER_RECEIVERS
                    and node.args[0].value in boolean_keys
                    and truth_context(node) and not _in_coercer(node, parents)):
                bare.append(f"line {node.lineno}: {ast.unparse(node)}")
        self.assertEqual(bare, [], "boolean params tested with bare truthiness:\n" + "\n".join(bare))


if __name__ == "__main__":
    unittest.main()
