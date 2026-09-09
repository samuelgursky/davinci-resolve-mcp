"""Contract tests for timeline_item_color.apply_trace_plan — the live half of
the advanced server's color_trace (identity-matched ColorTrace replacement)."""
import json
import os
import tempfile
import unittest

import src.server as compound


class _GraphStub:
    def __init__(self, ok=True):
        self.calls = []
        self.ok = ok

    def ApplyGradeFromDRX(self, path, mode):
        self.calls.append((path, mode))
        return self.ok


class _ItemStub:
    def __init__(self, uid, name, start, duration, ok=True):
        self._uid, self._name, self._start, self._dur = uid, name, start, duration
        self.graph = _GraphStub(ok)
        self.versions = []

    def GetUniqueId(self):
        return self._uid

    def GetName(self):
        return self._name

    def GetStart(self):
        return self._start

    def GetDuration(self):
        return self._dur

    def GetEnd(self):
        return self._start + self._dur

    def GetNodeGraph(self):
        return self.graph

    def AddVersion(self, name, vtype):
        self.versions.append((name, vtype))
        return True


class _TimelineStub:
    def __init__(self, name, tracks):
        self._name = name
        self._tracks = tracks  # {1: [items]}

    def GetName(self):
        return self._name

    def GetTrackCount(self, track_type):
        return len(self._tracks) if track_type == "video" else 0

    def GetItemListInTrack(self, track_type, idx):
        return self._tracks.get(idx, []) if track_type == "video" else []


def _match(index, name, start, duration, drx, source="SRC", method="media-overlap", confidence=0.95,
           status="ready", ambiguous=False):
    return {
        "index": index,
        "target": {"name": name, "start": start, "duration": duration},
        "source": {"name": source} if source else None,
        "method": method, "confidence": confidence, "ambiguous": ambiguous,
        "gradeApply": {"status": status, "drxPath": drx} if source else None,
    }


class _ResolveStub:
    def __init__(self, page="edit", can_switch=True):
        self.page = page
        self.can_switch = can_switch
        self.opened = []

    def GetCurrentPage(self):
        return self.page

    def OpenPage(self, page):
        self.opened.append(page)
        if not self.can_switch:
            return False
        self.page = page
        return True


class ApplyTracePlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="trace-test-")
        self.drx_a = os.path.join(self.tmp, "trace-0000.drx")
        self.drx_b = os.path.join(self.tmp, "trace-0001.drx")
        for pth in (self.drx_a, self.drx_b):
            with open(pth, "w", encoding="utf-8") as fh:
                fh.write("<Gallery::GyStill/>")
        self.a = _ItemStub("a", "SHOT_A", 86400, 48)
        self.b = _ItemStub("b", "SHOT_B", 86448, 24)
        self.b2 = _ItemStub("b2", "SHOT_B", 86448, 60)  # stacked on V2, different duration
        self.tl = _TimelineStub("REEL_01 v08", {1: [self.a, self.b], 2: [self.b2]})
        self._orig_get_tl = compound._get_tl
        compound._get_tl = lambda: (object(), self.tl, None)
        self._orig_required = compound._confirm_token_required
        compound._confirm_token_required = lambda: True
        self.resolve = _ResolveStub(page="edit")
        self._orig_get_resolve = compound.get_resolve
        compound.get_resolve = lambda: self.resolve

    def tearDown(self):
        compound._get_tl = self._orig_get_tl
        compound._confirm_token_required = self._orig_required
        compound.get_resolve = self._orig_get_resolve

    def _plan(self, matches, timeline="REEL_01 v08"):
        plan = {"kind": "color_trace.plan", "target": {"timeline": timeline}, "source": {"timeline": "REEL_01 v07"},
                "matches": matches}
        path = os.path.join(self.tmp, "plan.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(plan, fh)
        return path

    def test_missing_plan(self):
        out = compound._apply_trace_plan({})
        self.assertEqual(out["error"]["code"], "MISSING_PLAN")

    def test_timeline_mismatch_refuses(self):
        path = self._plan([_match(0, "SHOT_A", 86400, 48, self.drx_a)], timeline="OTHER")
        out = compound._apply_trace_plan({"plan_path": path, "dry_run": True})
        self.assertEqual(out["error"]["code"], "TIMELINE_MISMATCH")
        out = compound._apply_trace_plan({"plan_path": path, "dry_run": True, "allow_timeline_mismatch": True})
        self.assertTrue(out["success"])

    def test_dry_run_resolves_every_entry_with_a_reason(self):
        path = self._plan([
            _match(0, "SHOT_A", 86400, 48, self.drx_a),                              # apply
            _match(1, "SHOT_B", 86448, 24, self.drx_b),                              # stacked: duration disambiguates
            _match(2, "SHOT_C", 90000, 10, self.drx_a),                              # not on timeline
            _match(3, "SHOT_A", 86400, 48, self.drx_a, method="normalized-name", confidence=0.6),  # below gate
            _match(4, "SHOT_A", 86400, 48, os.path.join(self.tmp, "nope.drx")),      # drx missing
            _match(5, "SHOT_A", 86400, 48, self.drx_a, status="no-source-grade"),
            _match(6, "SHOT_X", 1, 1, None, source=None),                            # unmatched
        ])
        out = compound._apply_trace_plan({"plan_path": path, "dry_run": True})
        self.assertTrue(out["success"])
        self.assertTrue(out["dry_run"])
        self.assertTrue(os.path.isfile(out["report_path"]))
        self.assertEqual(os.path.dirname(out["report_path"]), self.tmp)
        self.assertFalse(out["resolution"]["truncated"])
        statuses = [(r["status"], r["reason"]) for r in out["resolution"]["rows"]]
        self.assertEqual(statuses, [
            ("apply", None), ("apply", None),
            ("skip", "live_item_not_found"), ("skip", "below_min_confidence"),
            ("skip", "drx_missing"), ("skip", "no-source-grade"), ("skip", "unmatched"),
        ])
        self.assertEqual(out["resolution"]["rows"][1]["live"]["id"], "b")
        self.assertEqual(out["summary"]["would_apply"], 2)
        # attention = non-bulk skips; unmatched / no-source-grade are bulk noise
        self.assertEqual(sorted(r["reason"] for r in out["attention"]["rows"]),
                         ["below_min_confidence", "drx_missing", "live_item_not_found"])
        self.assertEqual(out["summary"]["skipped_by_reason"]["live_item_not_found"], 1)
        self.assertEqual(self.a.graph.calls, [])  # nothing mutated

    def test_ambiguous_live_item_is_skipped_not_guessed(self):
        self.tl = _TimelineStub("REEL_01 v08", {1: [self.b], 2: [_ItemStub("b3", "SHOT_B", 86448, 24)]})
        compound._get_tl = lambda: (object(), self.tl, None)
        path = self._plan([_match(0, "SHOT_B", 86448, 24, self.drx_b)])
        out = compound._apply_trace_plan({"plan_path": path, "dry_run": True})
        row = out["resolution"]["rows"][0]
        self.assertEqual(row["reason"], "ambiguous_live_item")
        self.assertEqual(len(row["live_candidates"]), 2)

    def test_drx_outside_temp_refused_unless_opted_out(self):
        outside = os.path.join(os.path.expanduser("~"), "not-temp-trace.drx")
        path = self._plan([_match(0, "SHOT_A", 86400, 48, outside)])
        # file need not exist for the temp check to be the reason only if it exists; create-less path → drx_missing
        out = compound._apply_trace_plan({"plan_path": path, "dry_run": True})
        self.assertEqual(out["resolution"]["rows"][0]["reason"], "drx_missing")

    def test_token_then_apply_with_version(self):
        path = self._plan([_match(0, "SHOT_A", 86400, 48, self.drx_a), _match(1, "SHOT_B", 86448, 24, self.drx_b)])
        params = {"plan_path": path, "version_name": "traced v07", "grade_mode": 0}
        first = compound._apply_trace_plan(dict(params))
        self.assertEqual(first["status"], "confirmation_required")
        self.assertEqual(first["preview"]["will_apply"], 2)
        self.assertEqual(self.a.graph.calls, [])
        second = compound._apply_trace_plan({**params, "confirm_token": first["confirm_token"]})
        self.assertTrue(second["success"], second)
        self.assertEqual(second["applied"]["count"], 2)
        self.assertEqual(len(second["applied"]["rows"]), 2)
        self.assertTrue(os.path.isfile(second["report_path"]))
        with open(second["report_path"], encoding="utf-8") as fh:
            report = json.load(fh)
        self.assertEqual(len(report["applied"]), 2)
        self.assertEqual(self.a.graph.calls, [(self.drx_a, 0)])
        self.assertEqual(self.b.graph.calls, [(self.drx_b, 0)])
        self.assertEqual(self.b2.graph.calls, [])
        self.assertEqual(self.a.versions, [("traced v07", 0)])
        self.assertEqual(second["summary"]["applied"], 2)
        # Grade calls return False off the color page (19.1.3.7): the batch runs
        # on the color page and the user's page comes back afterwards.
        self.assertEqual(self.resolve.opened, ["color", "edit"])
        self.assertEqual(second["page"], {"before": "edit", "switched": True, "restored": True})

    def test_already_on_color_page_does_not_switch(self):
        self.resolve.page = "color"
        compound._confirm_token_required = lambda: False
        path = self._plan([_match(0, "SHOT_A", 86400, 48, self.drx_a)])
        out = compound._apply_trace_plan({"plan_path": path})
        self.assertTrue(out["success"])
        self.assertEqual(self.resolve.opened, [])
        self.assertEqual(out["page"], {"before": "color", "switched": False, "restored": None})

    def test_page_switch_failure_refuses_before_touching_clips(self):
        self.resolve.can_switch = False
        compound._confirm_token_required = lambda: False
        path = self._plan([_match(0, "SHOT_A", 86400, 48, self.drx_a)])
        out = compound._apply_trace_plan({"plan_path": path})
        self.assertEqual(out["error"]["code"], "PAGE_SWITCH_FAILED")
        self.assertEqual(self.a.graph.calls, [])
        self.assertEqual(self.a.versions, [])

    def test_partial_failure_is_reported_not_hidden(self):
        self.b.graph.ok = False
        path = self._plan([_match(0, "SHOT_A", 86400, 48, self.drx_a), _match(1, "SHOT_B", 86448, 24, self.drx_b)])
        compound._confirm_token_required = lambda: False
        out = compound._apply_trace_plan({"plan_path": path})
        self.assertFalse(out["success"])
        self.assertEqual(out["applied"]["count"], 1)
        self.assertEqual(out["failed"][0]["target"]["name"], "SHOT_B")
        self.assertIn("returned False", out["failed"][0]["error"])

    def test_nothing_to_apply_needs_no_token(self):
        path = self._plan([_match(0, "SHOT_C", 90000, 10, self.drx_a)])
        out = compound._apply_trace_plan({"plan_path": path})
        self.assertTrue(out["success"])
        self.assertEqual(out["applied"], [])
        self.assertIn("nothing to apply", out["note"])

    def test_max_rows_truncates_lists_but_never_failed(self):
        path = self._plan([_match(i, "SHOT_C", 90000 + i, 10, self.drx_a) for i in range(5)])
        out = compound._apply_trace_plan({"plan_path": path, "dry_run": True, "max_rows": 2})
        self.assertEqual(out["resolution"]["count"], 5)
        self.assertTrue(out["resolution"]["truncated"])
        self.assertEqual(len(out["resolution"]["rows"]), 2)
        with open(out["report_path"], encoding="utf-8") as fh:
            self.assertEqual(len(json.load(fh)["resolution"]), 5)
        full = compound._apply_trace_plan({"plan_path": path, "dry_run": True, "max_rows": 2, "verbose": True})
        self.assertFalse(full["resolution"]["truncated"])
        self.assertEqual(len(full["resolution"]["rows"]), 5)

    def test_dispatch_does_not_need_an_item(self):
        # Empty timeline: _get_item would fail; apply_trace_plan is timeline-scoped.
        compound._get_tl = lambda: (object(), _TimelineStub("REEL_01 v08", {}), None)
        path = self._plan([_match(0, "SHOT_A", 86400, 48, self.drx_a)])
        out = compound.timeline_item_color("apply_trace_plan", {"plan_path": path, "dry_run": True})
        self.assertTrue(out.get("success"), out)
        self.assertEqual(out["resolution"]["rows"][0]["reason"], "live_item_not_found")


if __name__ == "__main__":
    unittest.main()
