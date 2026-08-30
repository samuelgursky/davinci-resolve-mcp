"""Closing or deleting a project mid-render wedges Resolve (api_truth,
measured live on Studio 19.1.3.7): the orphaned render's flag sticks True,
new jobs sit at 0%, and Quit is refused. These guards make that unreachable
through this server's own tools."""
import unittest
from unittest import mock

from src import server
from src.utils.project_cleanup import delete_project_safely, stop_render_before_close


def _project(rendering_sequence):
    """A project whose IsRenderingInProgress returns the given sequence, then
    its last value forever."""
    proj = mock.Mock()
    seq = list(rendering_sequence)

    def _is_rendering():
        return seq.pop(0) if len(seq) > 1 else seq[0]

    proj.IsRenderingInProgress.side_effect = _is_rendering
    proj.GetName.return_value = "SCRATCH"
    return proj


class StopRenderBeforeCloseTest(unittest.TestCase):
    def test_idle_project_is_immediately_safe(self):
        state = stop_render_before_close(_project([False]))
        self.assertTrue(state["safe"])
        self.assertFalse(state["was_rendering"])

    def test_render_that_stops_is_safe_and_stopped(self):
        proj = _project([True, False])
        state = stop_render_before_close(proj, wait_seconds=2)
        self.assertTrue(state["safe"])
        self.assertTrue(state["was_rendering"])
        proj.StopRendering.assert_called_once()

    def test_stuck_flag_is_refused_with_the_wedge_named(self):
        state = stop_render_before_close(_project([True]), wait_seconds=1)
        self.assertFalse(state["safe"])
        self.assertIn("wedge", state["detail"])
        self.assertIn("restarting Resolve", state["detail"])


class DeleteProjectSafelyRenderGuardTest(unittest.TestCase):
    def test_deleting_the_current_project_stops_its_render_first(self):
        proj = _project([True, False])
        pm = mock.Mock()
        pm.GetCurrentProject.return_value = proj
        pm.DeleteProject.return_value = True
        result = delete_project_safely(pm, "SCRATCH")
        self.assertTrue(result["success"])
        proj.StopRendering.assert_called_once()
        pm.CloseProject.assert_called_once()

    def test_stuck_flag_refuses_the_delete_before_any_close(self):
        proj = _project([True])
        pm = mock.Mock()
        pm.GetCurrentProject.return_value = proj
        result = delete_project_safely(pm, "SCRATCH")
        self.assertFalse(result["success"])
        self.assertIn("wedge", result["detail"])
        pm.CloseProject.assert_not_called()
        pm.DeleteProject.assert_not_called()


class CloseActionRenderGuardTest(unittest.TestCase):
    def _close(self, proj, params=None):
        pm = mock.Mock()
        pm.GetCurrentProject.return_value = proj
        pm.CloseProject.return_value = True
        with mock.patch.object(server, "_pm_check", create=True), \
             mock.patch.object(server, "get_resolve") as gr:
            r = mock.Mock()
            r.GetProjectManager.return_value = pm
            gr.return_value = r
            return server.project_manager("close", params or {}), pm

    def test_close_mid_render_is_refused_with_remediation(self):
        result, pm = self._close(_project([True]))
        self.assertIn("error", result)
        self.assertIn("stop_render", str(result))
        pm.CloseProject.assert_not_called()

    def test_stop_render_true_stops_and_closes(self):
        result, pm = self._close(_project([True, False]), {"stop_render": True})
        self.assertTrue(result.get("success"), result)
        pm.CloseProject.assert_called_once()

    def test_idle_close_is_unchanged(self):
        result, pm = self._close(_project([False]))
        self.assertTrue(result.get("success"), result)
        pm.CloseProject.assert_called_once()


if __name__ == "__main__":
    unittest.main()
