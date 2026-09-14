"""Granular tools must not advertise a safety hint their body contradicts.

Granular tools infer their MCP annotation from the leading verb in the tool name.
That worked for `delete_marker` and silently failed for `ti_delete_marker`: the
`ti_` namespace sits in front of the verb, so the name matched no verb list and fell
through to the plain-write default. 86 tools were hinted wrongly — 43 destructive
ones (deletes, clears, sets, loads, resets) advertised as ordinary writes, and 43
pure readers advertised as writes.

The destructive half is the one that mattered: a client that gates on
`destructiveHint` — asking the user to approve, or refusing in a read-only mode —
was told `ti_copy_grades` was safe, and `CopyGrades` replaces a node graph with no
version to restore.

These are guards on the classifier, not on any one tool, because the failure was
never about a single name: it was a whole namespace that the heuristic could not
see past.
"""

from __future__ import annotations

import ast
import pathlib
import re
import unittest

from src.granular.common import (
    _annotations_for_tool_name,
    _strip_namespace,
    matches_a_verb,
)

GRANULAR = pathlib.Path(__file__).resolve().parent.parent / "src" / "granular"

#: Resolve methods whose name shape makes them safe to call from a read-only tool.
#: Export writes a file, but to a path the caller named, and never mutates the
#: project — the granular export tools are hinted as writes by their own verb.
_READ_SHAPED = re.compile(r"^(Get|Is|Has|List|Find|Export)")


def _tool_defs():
    """Every @mcp.tool function, with whether it passed an explicit annotation."""
    for path in sorted(GRANULAR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = [d for d in node.decorator_list
                          if isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "tool"]
            if not decorators:
                continue
            explicit = any(k.arg == "annotations" for d in decorators for k in d.keywords)
            yield path.name, node, explicit


def _uppercase_calls(node):
    """Resolve API methods the function calls, by attribute name."""
    return {sub.func.attr for sub in ast.walk(node)
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
            and sub.func.attr and sub.func.attr[0].isupper()}


class ReadOnlyHintIsHonest(unittest.TestCase):
    def test_no_read_only_tool_calls_a_mutating_resolve_method(self):
        """`readOnlyHint=True` is a promise a client may act on.

        Timeline.DetectSceneCuts is why this guard exists: `detect_` sat in the
        read-prefix list, and the only tool using it was `timeline_detect_scene_cuts`,
        whose namespace hid it. Teaching the classifier to strip namespaces would
        have promoted a tool that restructures the timeline to read-only.
        """
        offenders = []
        for filename, node, explicit in _tool_defs():
            if explicit:
                continue
            if not _annotations_for_tool_name(node.name).readOnlyHint:
                continue
            mutating = {m for m in _uppercase_calls(node) if not _READ_SHAPED.match(m)}
            # Resolve.Fusion() is an accessor that returns the Fusion object.
            mutating -= {"Fusion"}
            if mutating:
                offenders.append(f"{filename}:{node.name} calls {sorted(mutating)}")
        self.assertEqual(offenders, [], "read-only hint contradicted by the body:\n"
                                        + "\n".join(offenders))


class NamespacePrefixesAreStripped(unittest.TestCase):
    def test_no_namespaced_tool_falls_through_to_the_default(self):
        """A namespace must expose a verb the prefix lists actually know.

        This is the guard on the original bug rather than on its symptoms. Every
        `ti_*`, `timeline_*`, `graph_*` and `folder_*` tool used to land here: the
        namespace sat in front of the verb, nothing matched, and all 132 of them took
        the plain-write default — which happened to be right for the writes and wrong
        for every reader and every delete.

        `matches_a_verb` is False only when a name matched no list at all, so a
        deliberate WRITE (`add_`, `create_`, `export_`) passes and a fallthrough does
        not. Adding a namespace whose tools are not `<namespace>_<verb>_...` fails
        here instead of silently re-creating the bug.
        """
        fell_through = sorted(
            f"{filename}:{node.name}"
            for filename, node, explicit in _tool_defs()
            if not explicit
            and _strip_namespace(node.name.lower()) != node.name.lower()
            and not matches_a_verb(node.name)
        )
        # Verbs with no rule, so these keep the conservative write default. Each is a
        # genuine write, which is what the default says — they are listed rather than
        # given rules because a one-off verb is not worth a prefix everyone must read.
        allowed = {
            "folder.py:folder_analyze_for_intellisearch",
            "folder.py:folder_analyze_for_slate",
            "folder.py:folder_perform_audio_classification",
            "timeline.py:timeline_analyze_dolby_vision",
            "timeline.py:timeline_convert_to_stereo",
            "timeline.py:timeline_grab_all_stills",
            "timeline.py:timeline_grab_still",
            "timeline.py:timeline_update_marker_custom_data",
            "timeline_item.py:ti_finalize_take",
            "timeline_item.py:ti_regenerate_magic_mask",
            "timeline_item.py:ti_select_take",
            "timeline_item.py:ti_smart_reframe",
            "timeline_item.py:ti_stabilize",
            "timeline_item.py:ti_update_marker_custom_data",
            "timeline_item.py:ti_update_sidecar",
        }
        self.assertEqual(
            sorted(set(fell_through) - allowed), [],
            "namespaced tools the verb lists cannot read (add a verb rule, an "
            "explicit annotation, or extend the allow-list with a reason)",
        )
        self.assertEqual(
            sorted(allowed - set(fell_through)), [],
            "allow-list entries that now match a verb — drop them from the list",
        )


class TheKnownDangerousToolsAreHinted(unittest.TestCase):
    """Spot-checks with a real consequence behind them."""

    def test_deletes_and_clears_under_a_namespace_are_destructive(self):
        for name in ("ti_delete_marker_at_frame", "ti_delete_version", "ti_clear_flags",
                     "timeline_delete_track", "timeline_delete_clips",
                     "folder_clear_transcription", "graph_reset_all_grades"):
            with self.subTest(tool=name):
                self.assertTrue(_annotations_for_tool_name(name).destructiveHint)

    def test_namespaced_getters_are_read_only(self):
        for name in ("ti_get_info", "ti_get_markers", "timeline_get_track_name",
                     "graph_get_lut", "timeline_get_mark_in_out"):
            with self.subTest(tool=name):
                self.assertTrue(_annotations_for_tool_name(name).readOnlyHint)

    def test_detect_scene_cuts_is_not_a_read(self):
        # `detect_` used to be a read prefix. The namespace was the only reason this
        # tool was not already hinted read-only.
        self.assertFalse(_annotations_for_tool_name("detect_scene_cuts").readOnlyHint)
        self.assertFalse(_annotations_for_tool_name("timeline_detect_scene_cuts").readOnlyHint)


if __name__ == "__main__":
    unittest.main()
