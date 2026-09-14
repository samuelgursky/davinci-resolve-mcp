"""Every write the risk classifier rates is enforced, and the unrated backlog only shrinks.

Twice in two days a whole class of writes turned out to pass every safety gate.
v3.0.0: plugin-folder install/remove were in neither write table. v3.0.1:
thirteen deletes the classifier ALREADY rated HIGH, and the CRITICAL project
delete, sat on tools with no `@_destructive_op`; and nine risk rules named
actions no tool dispatches — among them the CRITICAL rule for deleting a
project. Safe mode is enforced only by the decorator, and only for registered
actions, so a rating nobody enforces is a promise nobody keeps.

This file makes the three failure modes structural:

  1. an action rated destructive must be enforced — its tool decorated, the
     action registered;
  2. every risk rule must name an action that some tool actually dispatches;
  3. write-style actions that are neither rated nor registered are frozen as a
     backlog that can only shrink: a new one fails the suite, and one that gets
     rated must be taken off the list.

Actions are discovered from literal `action == "x"` / `action in {...}`
comparisons in each @mcp.tool function, the same shape the action-list drift
guard trusts. "Write-style" is a name heuristic — a ratchet, not a proof.

Both servers are covered, by different means, because they are built differently.

The COMPOUND server (`src/server.py`) dispatches `(tool, action)` pairs through
`@_destructive_op`, so a rating can be checked against a real enforcement hook —
that is the first three tests.

The GRANULAR server (`src/granular/`) has one function per tool, no `action`
argument, and **no enforcement hook at all**: `@_destructive_op` wraps a
`(action, params)` signature that granular tools do not have, and none of the risk
tables or the destructive registry can key on them. For four releases that meant
its 387 tools were scanned by nothing — which is how `ti_copy_grades` reached
`TimelineItem.CopyGrades`, an API that replaces a node graph with no recovery
version, behind no guard of any kind (v4.3.0).

So the granular tests below claim less, on purpose:

  * a tool that calls a symbol the ledger marks `destroys_prior_work` MUST be
    gated — that is a real enforcement check, and the one that would have caught
    `ti_copy_grades` mechanically rather than by someone reading the file;
  * every other destructive-hinted granular tool is frozen in a backlog that can
    only shrink. That is a VISIBILITY ratchet, not an enforcement one. It does not
    make those 131 tools safe; it makes the 132nd fail the suite.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

from src.granular.common import _annotations_for_tool_name
from src.utils import destructive_hook
from src.utils.api_truth import API_TRUTH
from src.utils.execution_lifecycle import RiskClassificationHook, classify_operation_risk

SERVER = Path(__file__).resolve().parents[1] / "src" / "server.py"
GRANULAR = Path(__file__).resolve().parents[1] / "src" / "granular"
RISK_TABLES = ("_CRITICAL_ACTIONS", "_HIGH_RISK_ACTIONS", "_MEDIUM_RISK_ACTIONS",
               "_LOW_RISK_ACTIONS", "_GRAPH_LUT_ACTIONS")
WRITE_STYLE = re.compile(
    r"^(set|delete|remove|create|add|import|install|move|apply|update|write|replace|rename|clear|reset|insert|append|link|relink|save|load|restore|archive|duplicate|ripple|lift|overwrite|bulk|safe_(?!.*(probe|report)))"
)

#: Write-style actions with no risk rating and no registry entry, as of v3.0.1.
#: This list may only shrink. Rating or registering one of these makes the
#: stale-entry test fail until it is removed here; adding a new unrated
#: write-style action fails the other test until it is rated or listed.
UNRATED_WRITE_BACKLOG = frozenset({
    "color_group.set_name",
    "edit_engine.setup_sheet",
    "folder.clear_audio_classification",
    "folder.clear_transcription",
    "fusion_comp.add_fusion_mask",
    "fusion_comp.add_keyframe",
    "fusion_comp.add_tool",
    "fusion_comp.bulk_set_expressions",
    "fusion_comp.bulk_set_inputs",
    "fusion_comp.safe_add_tool",
    "fusion_comp.safe_connect_tools",
    "fusion_comp.safe_set_inputs",
    "fusion_comp.set_attrs",
    "fusion_comp.set_frame_range",
    "fusion_comp.set_input",
    "fusion_comp.set_position",
    "fusion_comp.set_text_plus",
    "gallery.create_power_grade_album",
    "gallery.create_still_album",
    "gallery.set_album_name",
    "gallery.set_current_album",
    "gallery_stills.import_stills",
    "gallery_stills.set_label",
    "graph.set_node_cache",
    "layout_presets.delete",
    "layout_presets.import_preset",
    "layout_presets.load",
    "layout_presets.save",
    "layout_presets.update",
    "media_pool.add_subfolder",
    "media_pool.import_folder",
    "media_pool.import_media",
    "media_pool.import_timeline",
    "media_pool.link_full_resolution_checked",
    "media_pool.link_proxy_checked",
    "media_pool.relink",
    "media_pool.safe_import_folder",
    "media_pool.safe_import_media",
    "media_pool.safe_import_sequence",
    "media_pool.safe_relink",
    "media_pool.safe_unlink",
    "media_pool.set_current_folder",
    "media_pool.set_selected",
    "media_pool_item.clear_audio_classification",
    "media_pool_item.clear_clip_color",
    "media_pool_item.clear_mark_in_out",
    "media_pool_item.clear_transcription",
    "media_pool_item.link_full_resolution_media",
    "media_pool_item.link_proxy",
    "media_pool_item.replace_clip",
    "media_pool_item.replace_clip_preserve_sub_clip",
    "media_pool_item.set_clip_color",
    "media_pool_item.set_clip_property",
    "media_pool_item.set_mark_in_out",
    "media_pool_item.set_metadata",
    "media_pool_item.set_name",
    "media_pool_item.set_third_party_metadata",
    "media_pool_item_markers.add",
    "media_pool_item_markers.add_flag",
    "media_pool_item_markers.clear_flags",
    "media_pool_item_markers.link_full_resolution_media",
    "media_pool_item_markers.replace_clip_preserve_sub_clip",
    "media_pool_item_markers.set_name",
    "media_pool_item_markers.update_custom_data",
    "media_storage.add_clip_mattes",
    "media_storage.add_timeline_mattes",
    "media_storage.import_to_pool",
    "project_manager.apply_spec",
    "project_manager.archive",
    "project_manager.create",
    "project_manager.import_project",
    "project_manager.load",
    "project_manager.restore",
    "project_manager.safe_project_archive",
    "project_manager.safe_project_create",
    "project_manager.safe_project_export",
    "project_manager.safe_project_import",
    "project_manager.safe_project_restore",
    "project_manager.safe_set_current_database",
    "project_manager.safe_set_project_settings",
    "project_manager.save",
    "project_manager_cloud.create",
    "project_manager_cloud.import_project",
    "project_manager_cloud.load",
    "project_manager_cloud.restore",
    "project_manager_database.set_current",
    "project_manager_folders.create",
    "project_manager_folders.delete",
    "project_settings.add_color_group",
    "project_settings.apply_fairlight_preset",
    "project_settings.insert_audio",
    "project_settings.load_burnin_preset",
    "project_settings.reset_intellisearch_analysis",
    "project_settings.set_name",
    "project_settings.set_preset",
    "project_settings.set_setting",
    "render.add_job",
    "render.load_preset",
    "render.safe_quick_export",
    "render.safe_set_render_settings",
    "render.save_preset",
    "render.set_format_and_codec",
    "render.set_mode",
    "render.set_settings",
    "render_presets.import_burnin",
    "render_presets.import_render",
    "resolve_control.clear_executions",
    "resolve_control.clear_mcp_update_preferences",
    "resolve_control.import_user_preferences_preset",
    "resolve_control.load_user_preferences_preset",
    "resolve_control.restore_state",
    "resolve_control.save_state",
    "resolve_control.save_user_preferences_preset",
    "resolve_control.set_high_priority",
    "resolve_control.set_keyframe_mode",
    "resolve_control.set_mcp_update_policy",
    "setup.clear",
    "setup.clear_defaults",
    "setup.reset",
    "setup.set",
    "setup.set_defaults",
    "timeline.apply_look_to_items",
    "timeline.bulk_set_item_properties",
    "timeline.bulk_set_title_text",
    "timeline.create_variant_from_ranges",
    "timeline.import_from_drp",
    "timeline.import_timeline_checked",
    "timeline.safe_auto_sync_audio",
    "timeline.safe_set_audio_properties",
    "timeline.set_current",
    "timeline.set_name",
    "timeline_item.add_keyframe",
    "timeline_item.load_burnin_preset",
    "timeline_item.set_keyframe_interpolation",
    "timeline_item_color.bulk_match_to_hero",
    "timeline_item_color.safe_apply_drx",
    "timeline_item_color.safe_copy_grade",
    "timeline_item_color.safe_export_lut",
    "timeline_item_color.safe_set_cdl",
    "timeline_item_fusion.set_cache",
    "timeline_markers.clear_annotations_by_scope",
    "timeline_markers.move_annotations",
    "timeline_markers.set_current_timecode",
    "timeline_versioning.archive_current",
})


def _tools():
    """{tool: (decorated, dispatched_actions)} for every @mcp.tool in server.py."""
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    out = {}
    for fn in tree.body:
        if not isinstance(fn, ast.FunctionDef):
            continue
        decorators = [ast.unparse(d) for d in fn.decorator_list]
        if not any(d.startswith("mcp.tool") for d in decorators):
            continue
        actions = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == "action":
                for comp in node.comparators:
                    if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                        actions.add(comp.value)
                    elif isinstance(comp, (ast.Set, ast.List, ast.Tuple)):
                        actions |= {e.value for e in comp.elts
                                    if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        out[fn.name] = (any("_destructive_op" in d for d in decorators), actions)
    return out


class WriteEnforcementRatchetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tools = _tools()
        cls.registry = destructive_hook.DESTRUCTIVE_ACTIONS_BY_TOOL

    def test_every_rated_write_is_enforced(self) -> None:
        """Raw registry membership, not is_destructive(): an action whose default
        call is plan-only (ripple_insert) reads non-destructive for an empty
        payload yet is correctly registered."""
        unenforced = []
        for tool, (decorated, actions) in sorted(self.tools.items()):
            for action in sorted(actions):
                risk = classify_operation_risk(tool, action, {})
                if risk.recognised and risk.destructive and not (
                    decorated and action in self.registry.get(tool, ())
                ):
                    why = "tool has no @_destructive_op" if not decorated else "action not registered"
                    unenforced.append(f"{risk.level.value} {tool}.{action} ({why})")
        self.assertEqual(unenforced, [], "rated destructive, but no gate enforces the rating")

    def test_every_risk_rule_names_a_real_action(self) -> None:
        """A rule for an action that no tool dispatches protects nothing. The
        CRITICAL rule for project deletion named `delete_project` for this
        reason while the real action, `delete`, went ungated."""
        dead = [f"{table}: {tool}.{action}"
                for table in RISK_TABLES
                for tool, action in sorted(getattr(RiskClassificationHook, table))
                if action not in self.tools.get(tool, (False, set()))[1]]
        self.assertEqual(dead, [], "risk rules that match nothing")

    def _unrated(self) -> set:
        return {f"{tool}.{action}"
                for tool, (_, actions) in self.tools.items() for action in actions
                if WRITE_STYLE.match(action)
                and not classify_operation_risk(tool, action, {}).recognised
                and action not in self.registry.get(tool, ())}

    def test_no_new_unrated_write_action(self) -> None:
        new = sorted(self._unrated() - UNRATED_WRITE_BACKLOG)
        self.assertEqual(new, [], "rate or register these write-style actions")

    def test_the_backlog_has_no_stale_entries(self) -> None:
        """The ratchet: once an entry is rated or registered it comes off the
        list, so the list can only get shorter."""
        stale = sorted(UNRATED_WRITE_BACKLOG - self._unrated())
        self.assertEqual(stale, [], "these are rated or registered now — remove them from the backlog")



# ── Granular server ──────────────────────────────────────────────────────────

#: Method names the ledger says destroy work that cannot be recovered. Derived from
#: API_TRUTH rather than written out, so flagging a new entry extends this guard
#: without anyone remembering to come back here.
TRAP_METHODS = frozenset(
    entry["symbol"].rsplit(".", 1)[-1]
    for entry in API_TRUTH
    if entry.get("destroys_prior_work")
)

#: Granular tools hinted destructive with no gate in front of them, as of v4.4.1.
#: This list may only shrink. Gating one makes the stale-entry test fail until it is
#: removed here; adding a new ungated destructive tool fails the other test.
#:
#: These are NOT safe. Each one mutates, and nothing on the granular server enforces
#: anything about it — no archive, no safe-mode refusal, no audit row. The list is
#: here so the number is known and cannot quietly grow.
UNGATED_GRANULAR_DESTRUCTIVE = frozenset({
    "add_timeline_item_transition",
    "auto_align_timeline_clips",
    "clear_clip_audio_classification",
    "clear_clip_color",
    "clear_clip_flags",
    "clear_clip_mark_in_out",
    "clear_clip_transcription",
    "clear_folder_transcription",
    "clear_transcription",
    "close_project",
    "create_multicam_clip",
    "delete_burn_in_preset",
    "delete_clip_marker_at_frame",
    "delete_clip_marker_by_custom_data",
    "delete_clip_markers_by_color",
    "delete_clip_mattes",
    "delete_color_group",
    "delete_keyframe",
    "delete_layout_preset_tool",
    "delete_media_pool_clips",
    "delete_media_pool_folders",
    "delete_project",
    "delete_project_folder",
    "delete_render_job",
    "delete_render_preset",
    "delete_stills_from_album",
    "delete_timelines_by_id",
    "delete_user_preferences_preset",
    "flatten_timeline_item_multicam",
    "folder_clear_audio_classification",
    "folder_clear_transcription",
    "folder_remove_motion_blur",
    "graph_reset_all_grades",
    "graph_set_lut",
    "graph_set_node_cache_mode",
    "graph_set_node_enabled",
    "load_burn_in_preset",
    "load_cloud_project",
    "load_cloud_project_tool",
    "load_layout_preset_tool",
    "load_render_preset",
    "load_user_preferences_preset",
    "normalize_timeline_audio_level",
    "quit_app",
    "quit_resolve",
    "remove_clip_motion_blur",
    "replace_clip",
    "replace_media_pool_clip",
    "replace_media_pool_clip_preserve_sub_clip",
    "restart_app",
    "set_cache_mode",
    "set_cache_path",
    "set_clip_color",
    "set_clip_mark_in_out",
    "set_clip_metadata",
    "set_clip_property",
    "set_clip_third_party_metadata",
    "set_color_science_mode_tool",
    "set_color_space_tool",
    "set_current_database",
    "set_current_media_pool_folder",
    "set_current_render_format_and_codec",
    "set_current_render_mode",
    "set_current_still_album",
    "set_current_timeline",
    "set_gallery_album_name",
    "set_keyframe_interpolation",
    "set_keyframe_mode",
    "set_media_pool_clip_name",
    "set_optimized_media_mode",
    "set_project_name",
    "set_project_preset",
    "set_project_property_tool",
    "set_project_setting",
    "set_proxy_mode",
    "set_proxy_quality",
    "set_render_settings",
    "set_selected_clip",
    "set_still_label",
    "set_superscale_settings_tool",
    "set_timeline_format_tool",
    "set_timeline_item_audio",
    "set_timeline_item_composite",
    "set_timeline_item_crop",
    "set_timeline_item_output_blanking",
    "set_timeline_item_retime",
    "set_timeline_item_stabilization",
    "set_timeline_item_transform",
    "set_timeline_item_use_timeline_for_output_blanking",
    "set_timeline_output_blanking",
    "set_timeline_setting",
    "stop_rendering",
    "ti_clear_clip_color",
    "ti_clear_flags",
    "ti_delete_fusion_comp",
    "ti_delete_marker_at_frame",
    "ti_delete_marker_by_custom_data",
    "ti_delete_markers_by_color",
    "ti_delete_take",
    "ti_delete_version",
    "ti_load_burn_in_preset",
    "ti_load_fusion_comp",
    "ti_load_version",
    "ti_remove_from_color_group",
    "ti_reset_all_node_colors",
    "ti_set_cdl",
    "ti_set_clip_color",
    "ti_set_clip_enabled",
    "ti_set_color_output_cache",
    "ti_set_fusion_output_cache",
    "ti_set_name",
    "ti_set_property",
    "ti_set_voice_isolation_state",
    "timeline_clear_mark_in_out",
    "timeline_delete_clips",
    "timeline_delete_marker_at_frame",
    "timeline_delete_marker_by_custom_data",
    "timeline_delete_markers_by_color",
    "timeline_delete_track",
    "timeline_detect_scene_cuts",
    "timeline_set_clips_linked",
    "timeline_set_current_timecode",
    "timeline_set_mark_in_out",
    "timeline_set_name",
    "timeline_set_start_timecode",
    "timeline_set_track_enable",
    "timeline_set_track_lock",
    "timeline_set_track_name",
    "timeline_set_voice_isolation_state",
    "unlink_clip_proxy_media",
    "unlink_proxy_media",
})


def _granular_tools():
    """{tool: (annotation_or_None, called_methods, gated)} for every granular tool."""
    out = {}
    for path in sorted(GRANULAR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in tree.body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = [d for d in fn.decorator_list
                          if isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "tool"]
            if not decorators:
                continue
            explicit = None
            for d in decorators:
                for kw in d.keywords:
                    if kw.arg == "annotations":
                        explicit = ast.unparse(kw.value)
            called = {n.func.attr for n in ast.walk(fn)
                      if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                      and n.func.attr and n.func.attr[0].isupper()}
            # Gated means the two halves are really there, checked as calls and
            # parameters rather than as substrings: an earlier version of this guard
            # looked for the text "CONFIRM_TOKENS", and deleting the redemption while
            # leaving the issuance behind still read as gated. Issuing a token nobody
            # checks is exactly the failure worth catching.
            confirm_calls = {n.func.attr for n in ast.walk(fn)
                             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                             and isinstance(n.func.value, ast.Name)
                             and n.func.value.id == "CONFIRM_TOKENS"}
            params = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
            gated = ({"issue", "consume"} <= confirm_calls
                     and "acknowledge_trap" in params
                     and "confirm_token" in params)
            out[fn.name] = (explicit, called, gated)
    return out


def _is_destructive(tool: str, explicit) -> bool:
    if explicit is not None:
        return explicit == "DESTRUCTIVE_TOOL"
    return _annotations_for_tool_name(tool).destructiveHint


class GranularWriteEnforcementTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tools = _granular_tools()

    def test_every_trap_symbol_call_is_gated(self) -> None:
        """The one enforcement claim on this surface, and the one that matters.

        `TimelineItem.CopyGrades` replaces a grade with no version to restore, and
        the granular twin called it with no acknowledgement and no confirmation.
        A tool reaching a `destroys_prior_work` symbol must ask twice: the trap
        acknowledgement, then a confirm token bound to the resolved targets.
        """
        self.assertTrue(TRAP_METHODS, "no destroys_prior_work entries — guard is vacuous")
        ungated = [f"{tool} calls {sorted(called & TRAP_METHODS)}"
                   for tool, (_explicit, called, gated) in sorted(self.tools.items())
                   if (called & TRAP_METHODS) and not gated]
        self.assertEqual(ungated, [], "granular tools reaching an unrecoverable API "
                                      "with no acknowledge_trap + confirm_token gate")

    def test_trap_symbol_tools_are_hinted_destructive(self) -> None:
        """A gate the caller only meets after calling is half a gate.

        A client that refuses destructive tools should never reach the confirmation
        at all, so the hint has to agree with the gate.
        """
        mismatched = [tool for tool, (explicit, called, _gated) in sorted(self.tools.items())
                      if (called & TRAP_METHODS) and not _is_destructive(tool, explicit)]
        self.assertEqual(mismatched, [], "reaches an unrecoverable API but is not "
                                         "hinted destructive")

    def _ungated_destructive(self) -> set:
        return {tool for tool, (explicit, _called, gated) in self.tools.items()
                if _is_destructive(tool, explicit) and not gated}

    def test_no_new_ungated_destructive_granular_tool(self) -> None:
        new = sorted(self._ungated_destructive() - UNGATED_GRANULAR_DESTRUCTIVE)
        self.assertEqual(new, [], "new destructive granular tool with no gate — add a "
                                  "gate, or add it to the backlog with a reason")

    def test_the_granular_backlog_has_no_stale_entries(self) -> None:
        """The ratchet: gating a tool takes it off the list, so the list only shrinks."""
        stale = sorted(UNGATED_GRANULAR_DESTRUCTIVE - self._ungated_destructive())
        self.assertEqual(stale, [], "these are gated now — remove them from the backlog")



if __name__ == "__main__":
    unittest.main()
