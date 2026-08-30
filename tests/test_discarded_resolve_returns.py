"""No Resolve mutator may drop its return without a written reason.

Every write in the Resolve scripting API reports itself with a bare boolean and
nothing else, so a discarded return turns a failed write into a
successful-looking no-op. That is the only failure shape worse than a crash:
the tool reports what it meant to do, and the project does not have it.

An AST pass over src/ found 113 bare-expression statements calling a
capitalised Resolve mutator. 47 of them were fixed (see the CHANGELOG); the
rest are listed below with the reason each one is genuinely fire-and-forget.
The point of the allowlist is that "fire-and-forget" has to be ARGUED, once,
in writing, and a NEW discarded return has to be argued too instead of joining
the pile unnoticed.

Three reasons recur, and only these three are accepted:

  NIL   The API returns nil/None, so the return carries no information at all.
        Fusion's Lua bridge is the whole of this category: SetInput, SetAttrs,
        SetPos, SetData, SetExpression, Delete, StartUndo, Render, LoadSettings
        and AddModifier all return nil whether or not they took. Where these
        matter, the fix is a readback, not a return check, and the ones that
        matter have one.
  TEARDOWN  Cleanup or restore that runs after the measured work. Turning a
        failed teardown into a failed operation would report successful work as
        a failure, and the failure is visible (a leftover job, a still in the
        Gallery, a bin left open) rather than silent.
  PROBE_CAPTURED  A probe harness where the return IS the measurement and is
        captured into a separate variable on the next line, or where the whole
        step is torn down and re-measured anyway.
"""
from __future__ import annotations

import ast
import pathlib
import unittest

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"

MUTATOR_PREFIXES = (
    "Set", "Add", "Delete", "Import", "Save", "Append", "Create", "Load", "Link",
    "Relink", "Unlink", "Export", "Apply", "Move", "Insert", "Refresh", "Render",
    "Start", "Stop", "Remove",
)

NIL = "Fusion Lua bridge: returns nil whether or not it took, so the return is not evidence"
TEARDOWN = "teardown after the measured work; a failure here is visible, not silent, and is logged"
PROBE = "probe harness: the return is the measurement and is captured separately, or the step is re-measured"

# (module path relative to src/, enclosing function, method) -> reason.
ALLOWED: dict[tuple[str, str, str], str] = {
    # --- Fusion, via the Lua bridge (returns nil) ---------------------------
    ("server.py", "fusion_comp", "SetInput"): NIL,
    ("server.py", "fusion_comp", "SetAttrs"): NIL,
    ("server.py", "fusion_comp", "SetPos"): NIL,
    ("server.py", "fusion_comp", "Delete"): NIL,
    ("server.py", "fusion_comp", "Render"): NIL,
    ("server.py", "fusion_comp", "StartUndo"): NIL,
    ("server.py", "fusion_comp", "LoadSettings"): NIL,
    ("server.py", "fusion_comp", "AddModifier"): (
        NIL + "; verified instead by reading GetConnectedOutput back, because "
        "without the spline the assignment sets a STATIC value and no keyframe"
    ),
    ("server.py", "_fusion_add_mask", "SetInput"): NIL,
    ("server.py", "_fusion_add_mask", "SetAttrs"): NIL,
    ("server.py", "_safe_add_fusion_tool", "SetAttrs"): NIL,
    ("server.py", "_safe_set_fusion_inputs", "SetInput"): NIL + "; the action takes readback=True",
    ("server.py", "_fusion_set_point_input", "SetInput"): NIL,
    ("server.py", "_fusion_set_text_plus", "SetInput"): NIL + "; verified by get_text_plus readback",
    ("server.py", "_fusion_comp_bulk_set_inputs", "SetInput"): NIL,
    ("server.py", "_fusion_comp_bulk_set_inputs", "StartUndo"): NIL,
    ("server.py", "_fusion_comp_bulk_set_expressions", "SetExpression"): NIL,
    ("server.py", "_fusion_comp_bulk_set_expressions", "StartUndo"): NIL,
    ("server.py", "_fusion_group_settings_load", "StartUndo"): NIL + "; tracked by undo_started",
    ("server.py", "_fusion_group_settings_load", "LoadSettings"): NIL,
    ("server.py", "_fusion_group_settings_load", "SaveSettings"): (
        NIL + "; the backup is verified by os.path.isfile, which is what makes the "
        "load reversible"
    ),
    ("server.py", "_fusion_group_settings_export", "SaveSettings"): (
        NIL + "; verified by os.path.isfile on the path it was asked to write"
    ),
    ("server.py", "_fusion_delete_keyframe", "DeleteKeyFrames"): (
        "measured on a live build to return None whether or not it removed anything; "
        "verified by re-reading the keyframe list (v2.98.3)"
    ),
    ("server.py", "_run_inline_lua", "SetData"): (
        NIL + "; the completion sentinel is verified by reading __mcp_done__ back, "
        "because a stale value hands the previous run's output back as this run's"
    ),

    # --- teardown ----------------------------------------------------------
    ("server.py", "_playhead_frame_render", "DeleteRenderJob"): TEARDOWN,
    ("server.py", "_playhead_frame_render", "SetRenderSettings"): (
        TEARDOWN + "; explicitly not a restore either -- without GetRenderSettings "
        "there is nothing to restore FROM"
    ),
    ("server.py", "_playhead_frame_full", "DeleteStills"): TEARDOWN,
    ("server.py", "render", "StopRendering"): (
        "the API returns None; the caller polls IsRenderingInProgress"
    ),
    ("project.py", "stop_rendering", "StopRendering"): (
        "the API returns None; the granular twin of the compound render path"
    ),
    ("graph.py", "graph_set_lut", "RefreshLUTList"): (
        TEARDOWN + "; the granular twin of the compound path, which logs it"
    ),

    # --- probe harnesses ---------------------------------------------------
    ("probe_catalogue.py", "_probe_pool_add_subfolder", "SetCurrentFolder"): PROBE,
    ("probe_catalogue.py", "_probe_pool_add_subfolder", "DeleteFolders"): PROBE,
    ("probe_catalogue.py", "_probe_pool_append_to_timeline", "AppendToTimeline"): PROBE,
    ("probe_catalogue.py", "_probe_pool_clip_marker_roundtrip", "DeleteMarkerAtFrame"): PROBE,
    ("probe_catalogue.py", "_probe_timeline_marker_roundtrip", "DeleteMarkerAtFrame"): PROBE,
    ("probe_catalogue.py", "_probe_item_marker_roundtrip", "DeleteMarkerAtFrame"): PROBE,
    ("probe_catalogue.py", "_probe_timeline_track_enable_roundtrip", "SetTrackEnable"): PROBE,
    ("probe_catalogue.py", "_probe_color_group_roundtrip", "RemoveFromColorGroup"): PROBE,
    ("probe_catalogue.py", "_probe_color_group_roundtrip", "DeleteColorGroup"): PROBE,
    ("probe_catalogue.py", "_probe_gallery_export_stills", "DeleteStills"): PROBE,
    ("probe_catalogue.py", "_probe_render_job_roundtrip", "SetRenderSettings"): PROBE,
    ("probe_catalogue.py", "_probe_render_to_disk", "SetRenderSettings"): PROBE,
    ("probe_catalogue.py", "_probe_render_to_disk", "SetCurrentRenderFormatAndCodec"): PROBE,
    ("probe_catalogue.py", "_probe_render_to_disk", "StartRendering"): PROBE,
    ("probe_catalogue.py", "_probe_render_to_disk", "DeleteRenderJob"): PROBE,
    ("probe_catalogue.py", "_probe_projectlevel_multi_job", "SetRenderSettings"): PROBE,
    ("probe_catalogue.py", "_probe_projectlevel_multi_job", "DeleteRenderJob"): PROBE,
    ("probe_catalogue.py", "_probe_lifecycle_load_and_close", "LoadProject"): PROBE,
    ("probe_catalogue.py", "_probe_lifecycle_delete_after_close_releases_lock", "LoadProject"): PROBE,
    ("probe_catalogue.py", "_probe_editorial_linked", "SetClipsLinked"): PROBE,
    ("color_grade_live_probe.py", "run_probe", "AppendToTimeline"): PROBE,
    ("color_grade_live_probe.py", "run_probe", "SetCurrentTimecode"): PROBE,
    ("timeline_conform_live_probe.py", "run_probe", "AppendToTimeline"): PROBE,
    ("fusion_composition_live_probe.py", "run_probe", "SetCurrentTimecode"): PROBE,
    ("review_annotation_live_probe.py", "run_probe", "SetCurrentTimecode"): PROBE,
}


def _discarded_mutator_calls():
    """(module, function, method, line) for every bare-expression Resolve write."""
    found = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        owner = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(node):
                    owner.setdefault(child, node.name)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Expr):
                continue
            call = node.value
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
                continue
            method = call.func.attr
            # Capitalised first letter is the discriminator: Resolve's API is
            # always PascalCase and Python's stdlib never is, so `.append(` on a
            # local list cannot be mistaken for `.AppendToTimeline(`.
            if not (method[:1].isupper() and method.startswith(MUTATOR_PREFIXES)):
                continue
            found.append((path.name, owner.get(node, "<module>"), method, node.lineno,
                          str(path.relative_to(SRC.parent))))
    return found


class DiscardedResolveReturnsTest(unittest.TestCase):
    def test_the_scan_finds_something(self):
        """A scanner that matches nothing passes everything."""
        self.assertGreater(len(_discarded_mutator_calls()), 20)

    def test_every_discarded_return_has_a_written_reason(self):
        offenders = []
        for module, func, method, line, rel in _discarded_mutator_calls():
            if (module, func, method) in ALLOWED:
                continue
            offenders.append(f"{rel}:{line}  {func}() drops {method}()'s return")
        self.assertEqual(
            offenders, [],
            "A Resolve mutator's return was discarded with no reason on record. "
            "Either check it -- a False here is a silent no-op reported as success "
            "-- or add it to ALLOWED in this file with the reason it is genuinely "
            "fire-and-forget:\n  " + "\n  ".join(offenders),
        )

    def test_the_allowlist_has_not_gone_stale(self):
        """An entry for code that no longer exists hides the next real one."""
        live = {(module, func, method)
                for module, func, method, _line, _rel in _discarded_mutator_calls()}
        stale = sorted(key for key in ALLOWED if key not in live)
        self.assertEqual(
            stale, [],
            "these ALLOWED entries no longer match any callsite; delete them:\n  "
            + "\n  ".join(str(key) for key in stale),
        )

    def test_every_reason_says_something(self):
        for key, reason in ALLOWED.items():
            with self.subTest(key=key):
                self.assertGreater(len(reason), 25, f"{key}: the reason is not a reason")


if __name__ == "__main__":
    unittest.main()
