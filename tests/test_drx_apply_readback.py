"""DRX applies read back every graph the grade could land in (issues #318, #319).

#318: a timeline apply of a .drx whose <pTrackVer> has HasCorrection false
returns True, adds nothing and empties the timeline graph. It is now refused.

#319: on a clip in a color group the grade replaced node 1 of the group's
pre-clip graph while the clip graph stayed empty, and the result said success.
The apply now reports changed_graphs and fails when only an untargeted graph
changed.
"""
import os
import tempfile
import unittest
from unittest import mock

from src import server as s

_TRACK = """ <pTrackVer>
  <ListMgt::LmVersion DbId="t">
   <HasCorrection>{has}</HasCorrection>
   <VerType>1</VerType>
   <Body>00</Body>
  </ListMgt::LmVersion>
 </pTrackVer>"""


def _drx(track="false"):
    body = ('<?xml version="1.0"?>\n<gradeData>\n <pClipFullVer>\n'
            '  <ListMgt::LmVersion DbId="c"><HasCorrection>true</HasCorrection>'
            '<VerType>0</VerType><Body>00</Body></ListMgt::LmVersion>\n </pClipFullVer>\n')
    if track is not None:
        body += _TRACK.format(has=track) + "\n"
    body += "</gradeData>\n"
    fd, path = tempfile.mkstemp(suffix=".drx")
    with os.fdopen(fd, "w") as fh:
        fh.write(body)
    return path


class _Graph:
    def __init__(self, nodes):
        self.nodes = list(nodes)      # [(label, lut)]
        self.on_apply = None
        self.applied = []

    def GetNumNodes(self):
        return len(self.nodes)

    def GetNodeLabel(self, i):
        return self.nodes[i - 1][0]

    def GetLUT(self, i):
        return self.nodes[i - 1][1]

    def ApplyGradeFromDRX(self, path, mode):
        self.applied.append((path, mode))
        if self.on_apply:
            self.on_apply()
        return True


class _Group:
    def __init__(self, name, pre, post):
        self.name, self.pre, self.post = name, pre, post

    def GetName(self):
        return self.name

    def GetPreClipNodeGraph(self):
        return self.pre

    def GetPostClipNodeGraph(self):
        return self.post


class _Item:
    def __init__(self, graph, group=None):
        self.graph, self.group = graph, group

    def GetNodeGraph(self, layer=None):
        return self.graph

    def GetColorGroup(self):
        return self.group


class _Timeline:
    def __init__(self, graph):
        self.graph = graph

    def GetNodeGraph(self):
        return self.graph


class _Project:
    def __init__(self, groups):
        self.groups = groups

    def GetColorGroupsList(self):
        return self.groups


class _Fixture:
    """A clip in a color group on a timeline, each graph separately readable."""

    def __init__(self):
        self.clip = _Graph([("", "")])
        self.pre = _Graph([("Show LUT", "show.cube")])
        self.post = _Graph([])
        self.tl_graph = _Graph([("Hand node", "")])
        self.group = _Group("Scene 1", self.pre, self.post)
        self.item = _Item(self.clip, self.group)
        self.tl = _Timeline(self.tl_graph)
        self.proj = _Project([self.group])

    def graph(self, params):
        with mock.patch.object(s, "_get_tl", return_value=(self.proj, self.tl, None)), \
             mock.patch.object(s, "_get_item", return_value=(self.proj, self.item, None)), \
             mock.patch.object(s, "_check", return_value=(None, self.proj, None)), \
             mock.patch.object(s, "_confirm_token_required", return_value=False):
            return s.graph("apply_grade_from_drx", params)


class TrackGradeState(unittest.TestCase):
    def test_reads_each_state(self):
        for track, want in (("true", "present"), ("false", "empty"), (None, "missing")):
            path = _drx(track)
            self.addCleanup(os.remove, path)
            self.assertEqual(s._drx_track_grade_state(path), want, track)

    def test_unreadable_path(self):
        self.assertEqual(s._drx_track_grade_state("/nonexistent/x.drx"), "unreadable")


class TimelineApplyRefusal(unittest.TestCase):
    def test_empty_track_grade_is_refused_before_resolve_is_called(self):
        f = _Fixture()
        path = _drx("false")
        self.addCleanup(os.remove, path)
        out = f.graph({"path": path, "source": "timeline"})
        self.assertEqual(out["error"]["code"], "DRX_NO_TIMELINE_GRADE")
        self.assertEqual(f.tl_graph.applied, [])

    def test_missing_track_grade_is_refused(self):
        f = _Fixture()
        path = _drx(None)
        self.addCleanup(os.remove, path)
        out = f.graph({"path": path, "source": "timeline"})
        self.assertEqual(out["error"]["state"]["track_grade"], "missing")

    def test_clip_apply_of_the_same_file_is_not_refused(self):
        f = _Fixture()
        path = _drx("false")
        self.addCleanup(os.remove, path)
        f.clip.on_apply = lambda: f.clip.nodes.append(("Look", ""))
        out = f.graph({"path": path, "source": "item"})
        self.assertTrue(out["success"], out)
        self.assertEqual(f.clip.applied, [(path, 0)])

    def test_timeline_grade_present_applies(self):
        f = _Fixture()
        path = _drx("true")
        self.addCleanup(os.remove, path)
        f.tl_graph.on_apply = lambda: f.tl_graph.nodes.append(("Look", ""))
        out = f.graph({"path": path, "source": "timeline"})
        self.assertTrue(out["success"], out)
        self.assertEqual(out["changed_graphs"], ["timeline"])
        self.assertTrue(out["verification"]["verified"])


class ReadbackAcrossGraphs(unittest.TestCase):
    def setUp(self):
        self.path = _drx("false")
        self.addCleanup(os.remove, self.path)

    def test_grade_landing_in_group_pre_clip_fails(self):
        f = _Fixture()

        def lands_in_pre():
            f.pre.nodes[0] = ("", "")       # node 1 replaced, the group LUT gone
        f.clip.on_apply = lands_in_pre
        out = f.graph({"path": self.path, "source": "item"})
        self.assertFalse(out["success"])
        self.assertEqual(out["error"]["code"], "DRX_APPLIED_TO_OTHER_GRAPH")
        self.assertEqual(out["changed_graphs"], ["color_group_pre"])
        self.assertTrue(out["verification"]["contradiction"])
        self.assertEqual(set(out["graphs"]), {"item", "color_group_pre", "color_group_post", "timeline"})

    def test_target_change_is_verified(self):
        f = _Fixture()
        f.clip.on_apply = lambda: f.clip.nodes.extend([("Balance", ""), ("Look", "")])
        out = f.graph({"path": self.path, "source": "item"})
        self.assertTrue(out["success"])
        self.assertEqual(out["changed_graphs"], ["item"])
        self.assertEqual(out["graphs"]["item"]["num_nodes_after"], 3)
        self.assertNotIn("warning", out)

    def test_no_change_warns_but_does_not_fail(self):
        f = _Fixture()
        out = f.graph({"path": self.path, "source": "item"})
        self.assertTrue(out["success"])
        self.assertEqual(out["changed_graphs"], [])
        self.assertFalse(out["verification"]["verified"])
        self.assertIn("rendered frame", out["warning"])

    def test_group_source_reads_both_group_graphs_and_timeline(self):
        f = _Fixture()
        f.pre.on_apply = lambda: f.pre.nodes.append(("Group look", ""))
        out = f.graph({"path": self.path, "source": "color_group_pre", "group_name": "Scene 1"})
        self.assertTrue(out["success"], out)
        self.assertEqual(out["changed_graphs"], ["color_group_pre"])
        self.assertEqual(set(out["graphs"]), {"color_group_pre", "color_group_post", "timeline"})

    def test_safe_apply_drx_uses_the_same_readback(self):
        f = _Fixture()
        f.clip.on_apply = lambda: f.pre.nodes.clear()
        with mock.patch.object(s, "_get_tl", return_value=(f.proj, f.tl, None)), \
             mock.patch.object(s, "_confirm_token_required", return_value=False):
            out = s._safe_apply_drx(f.proj, f.item, {"path": self.path, "source": "item",
                                                     "require_temp_path": False})
        self.assertEqual(out["error"]["code"], "DRX_APPLIED_TO_OTHER_GRAPH")

    def test_safe_apply_drx_refuses_empty_timeline_grade(self):
        f = _Fixture()
        with mock.patch.object(s, "_get_tl", return_value=(f.proj, f.tl, None)), \
             mock.patch.object(s, "_confirm_token_required", return_value=False):
            out = s._safe_apply_drx(f.proj, f.item, {"path": self.path, "source": "timeline",
                                                     "require_temp_path": False})
        self.assertEqual(out["error"]["code"], "DRX_NO_TIMELINE_GRADE")
        self.assertEqual(f.tl_graph.applied, [])


if __name__ == "__main__":
    unittest.main()
