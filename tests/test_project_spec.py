"""Unit tests for the declarative project spec: load, plan, apply (Phase B)."""
import json
import os
import tempfile
import unittest

from src.utils import project_spec as ps


class FakeExecutor:
    """In-memory executor recording calls; mimics the live one's contract."""

    def __init__(self, live):
        self._live = live
        self.calls = []
        self.fail_on = set()  # targets to fail

    def live_state(self):
        return self._live

    def _ok(self, tag, target):
        self.calls.append((tag, target))
        return target not in self.fail_on

    def ensure_project(self, name):
        return self._ok("ensure_project", f"project:{name}")

    def set_project_setting(self, key, value):
        return self._ok("set_project_setting", f"setting:{key}")

    def ensure_timeline(self, name, fps):
        return self._ok("ensure_timeline", f"timeline:{name}")

    def set_timeline_setting(self, tl, key, value):
        return self._ok("set_timeline_setting", f"timeline:{tl}/setting:{key}")

    def add_marker(self, tl, marker):
        return self._ok("add_marker", f"timeline:{tl}/marker:{marker.get('frame')}")

    def ensure_bin(self, path):
        return self._ok("ensure_bin", f"bin:{path}")


SPEC_DICT = {
    "project": "MyShow",
    "color_preset": "rec709_gamma24",
    "settings": {"timelineFrameRate": "24"},
    "bins": ["Master/Admin", "Master/Media/Scene_01"],
    "timelines": [
        {"name": "Edit_v2", "fps": 24,
         "markers": [{"frame": 0, "color": "Blue", "name": "HEAD"}]},
    ],
    "hooks": {"before": [{"command": "echo hi", "name": "setup"}], "after": ["echo bye"]},
}


class SpecLoadTest(unittest.TestCase):
    def test_from_dict_ok(self):
        spec = ps.spec_from_dict(SPEC_DICT)
        self.assertEqual(spec.project, "MyShow")
        self.assertEqual(spec.color_preset, "rec709_gamma24")
        self.assertEqual(spec.bins, ["Master/Admin", "Master/Media/Scene_01"])
        self.assertEqual(len(spec.timelines), 1)
        self.assertEqual(spec.timelines[0].fps, 24)
        self.assertEqual(len(spec.hooks), 2)

    def test_missing_project_raises(self):
        with self.assertRaises(ps.SpecError):
            ps.spec_from_dict({"timelines": []})

    def test_unknown_preset_raises(self):
        with self.assertRaises(ps.SpecError) as cm:
            ps.spec_from_dict({"project": "X", "color_preset": "nope"})
        self.assertIn("known_presets", cm.exception.state)

    def test_timeline_requires_name(self):
        with self.assertRaises(ps.SpecError):
            ps.spec_from_dict({"project": "X", "timelines": [{"fps": 24}]})

    def test_load_json_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "spec.json")
            with open(path, "w") as fh:
                json.dump(SPEC_DICT, fh)
            spec = ps.load_spec(path)
            self.assertEqual(spec.project, "MyShow")

    def test_load_missing_file_raises(self):
        with self.assertRaises(ps.SpecError):
            ps.load_spec("/no/such/spec.json")


class EffectiveSettingsTest(unittest.TestCase):
    def test_explicit_overrides_preset(self):
        spec = ps.spec_from_dict({
            "project": "X", "color_preset": "rec709_gamma24",
            "settings": {"colorSpaceOutput": "Custom"},
        })
        eff = ps.effective_settings(spec)
        self.assertEqual(eff["colorSpaceOutput"], "Custom")  # explicit wins
        self.assertIn("colorScienceMode", eff)               # preset still present

    def test_settings_order_puts_color_science_first(self):
        keys = ps._ordered_setting_keys(["timelineFrameRate", "colorSpaceOutput", "colorScienceMode"])
        self.assertLess(keys.index("colorScienceMode"), keys.index("colorSpaceOutput"))


class NumericSettingNormalizationTest(unittest.TestCase):
    """Regression for the live finding: Resolve reports fps as '24.0' but specs
    say '24' — comparison must be numeric so reconcile converges."""

    def test_norm_value(self):
        self.assertEqual(ps._norm_setting_value("24.0"), "24")
        self.assertEqual(ps._norm_setting_value("24"), "24")
        self.assertEqual(ps._norm_setting_value(24.0), "24")
        self.assertEqual(ps._norm_setting_value("Rec.709"), "Rec.709")

    def test_settings_equal_numeric(self):
        self.assertTrue(ps._settings_equal("24.0", "24"))
        self.assertTrue(ps._settings_equal("23.976", "23.976"))
        self.assertFalse(ps._settings_equal("24", "25"))

    def test_project_setting_2400_matches_24_is_noop(self):
        spec = ps.spec_from_dict({"project": "S", "settings": {"timelineFrameRate": "24"}})
        plan = ps.plan_spec(spec, {"project": "S", "projects": ["S"],
                                   "settings": {"timelineFrameRate": "24.0"}, "timelines": []})
        self.assertEqual(plan["change_count"], 0)

    def test_fps_not_emitted_as_timeline_setting(self):
        # fps is creation-time only — no per-timeline timelineFrameRate set action.
        spec = ps.spec_from_dict({"project": "S",
                                  "timelines": [{"name": "A", "fps": 24}]})
        plan = ps.plan_spec(spec, {"project": "S", "projects": ["S"], "settings": {},
                                   "timelines": [{"name": "A", "settings": {"timelineFrameRate": "24.0"}}]})
        setting_actions = [a for a in plan["actions"] if "/setting:timelineFrameRate" in a["target"]
                           and a["target"].startswith("timeline:")]
        self.assertEqual(setting_actions, [])


class PlanTest(unittest.TestCase):
    def test_fresh_project_plans_create(self):
        spec = ps.spec_from_dict(SPEC_DICT)
        plan = ps.plan_spec(spec, {"projects": [], "settings": {}, "timelines": []})
        ops = {a["op"] for a in plan["actions"]}
        self.assertIn("create", ops)
        self.assertIn("ensure", ops)  # timeline
        self.assertGreater(plan["change_count"], 0)

    def test_matching_state_is_all_noop(self):
        spec = ps.spec_from_dict({"project": "S", "settings": {"timelineFrameRate": "24"}})
        plan = ps.plan_spec(spec, {"project": "S", "projects": ["S"],
                                   "settings": {"timelineFrameRate": "24"}, "timelines": []})
        self.assertEqual(plan["change_count"], 0)
        self.assertTrue(all(a["op"] == "noop" for a in plan["actions"]))

    def test_marker_idempotent_in_plan(self):
        spec = ps.spec_from_dict({
            "project": "S",
            "timelines": [{"name": "A", "markers": [{"frame": 0}]}],
        })
        live = {"project": "S", "projects": ["S"], "settings": {},
                "timelines": [{"name": "A", "settings": {}, "markers": [{"frame": 0}]}]}
        plan = ps.plan_spec(spec, live)
        marker_actions = [a for a in plan["actions"] if "marker" in a["target"]]
        self.assertTrue(all(a["op"] == "noop" for a in marker_actions))

    def test_missing_bins_are_ensured(self):
        spec = ps.spec_from_dict({"project": "S", "bins": ["Master/Media/Scene_01"]})
        plan = ps.plan_spec(spec, {"project": "S", "projects": ["S"], "settings": {}, "bins": ["Master"]})

        bin_actions = [a for a in plan["actions"] if a["target"].startswith("bin:")]

        self.assertEqual(bin_actions[0]["op"], "ensure")
        self.assertEqual(bin_actions[0]["target"], "bin:Master/Media/Scene_01")

    def test_unprefixed_bins_normalize_to_master(self):
        # Live bin paths are always Master-prefixed; an unprefixed spec bin
        # must still match them or the plan never converges to noop.
        spec = ps.spec_from_dict({"project": "S", "bins": ["Media/Scene_01", "/Master/Admin/"]})
        self.assertEqual(spec.bins, ["Master/Media/Scene_01", "Master/Admin"])

        plan = ps.plan_spec(spec, {"project": "S", "projects": ["S"], "settings": {},
                                   "bins": ["Master", "Master/Media/Scene_01", "Master/Admin"]})
        bin_actions = [a for a in plan["actions"] if a["target"].startswith("bin:")]
        self.assertTrue(all(a["op"] == "noop" for a in bin_actions), bin_actions)


class ApplyTest(unittest.TestCase):
    def test_dry_run_does_not_execute(self):
        spec = ps.spec_from_dict(SPEC_DICT)
        ex = FakeExecutor({"projects": [], "settings": {}, "timelines": []})
        out = ps.apply_spec(spec, ex, dry_run=True)
        self.assertTrue(out["dry_run"])
        self.assertEqual(ex.calls, [])

    def test_apply_executes_and_reports(self):
        spec = ps.spec_from_dict(SPEC_DICT)
        ex = FakeExecutor({"projects": [], "settings": {}, "timelines": []})
        out = ps.apply_spec(spec, ex)
        self.assertTrue(out["success"])
        tags = {t for t, _ in ex.calls}
        self.assertIn("ensure_project", tags)
        self.assertIn("ensure_bin", tags)
        self.assertIn("ensure_timeline", tags)
        self.assertIn("add_marker", tags)

    def test_apply_skips_matching_settings(self):
        spec = ps.spec_from_dict({"project": "S", "settings": {"timelineFrameRate": "24"}})
        ex = FakeExecutor({"project": "S", "projects": ["S"],
                           "settings": {"timelineFrameRate": "24"}, "timelines": []})
        ps.apply_spec(spec, ex)
        self.assertNotIn("set_project_setting", {t for t, _ in ex.calls})

    def test_first_failure_raises_without_continue(self):
        spec = ps.spec_from_dict({"project": "S"})
        ex = FakeExecutor({"projects": [], "settings": {}, "timelines": []})
        ex.fail_on.add("project:S")
        with self.assertRaises(ps.SpecError) as cm:
            ps.apply_spec(spec, ex)
        self.assertIn("failures", cm.exception.state)

    def test_continue_on_error_accumulates(self):
        spec = ps.spec_from_dict(SPEC_DICT)
        ex = FakeExecutor({"projects": [], "settings": {}, "timelines": []})
        ex.fail_on.add("timeline:Edit_v2/marker:0")
        out = ps.apply_spec(spec, ex, continue_on_error=True)
        self.assertFalse(out["success"])
        self.assertEqual(len(out["failures"]), 1)

    def test_hooks_opt_in(self):
        spec = ps.spec_from_dict(SPEC_DICT)
        ex = FakeExecutor({"projects": [], "settings": {}, "timelines": []})
        ran = []
        ps.apply_spec(spec, ex, run_hooks=True, run_hook=lambda h: ran.append(h.command) or True)
        self.assertEqual(ran, ["echo hi", "echo bye"])

    def test_hooks_skipped_by_default(self):
        spec = ps.spec_from_dict(SPEC_DICT)
        ex = FakeExecutor({"projects": [], "settings": {}, "timelines": []})
        ran = []
        ps.apply_spec(spec, ex, run_hook=lambda h: ran.append(h.command) or True)
        self.assertEqual(ran, [])  # run_hooks defaulted False


if __name__ == "__main__":
    unittest.main()
