import unittest

from src.utils.project_cleanup import delete_project_safely


class _FakeProject:
    def __init__(self, name):
        self._name = name

    def GetName(self):
        return self._name


class _FakePM:
    """Minimal ProjectManager stand-in with scriptable DeleteProject results."""

    def __init__(self, current=None, delete_results=(True,), load_ok=True):
        self.current = current
        self.delete_results = list(delete_results)
        self.load_ok = load_ok
        self.loaded = []
        self.closed = []
        self.delete_calls = 0

    def GetCurrentProject(self):
        return _FakeProject(self.current) if self.current else None

    def LoadProject(self, name):
        self.loaded.append(name)
        if self.load_ok:
            self.current = name
        return self.load_ok

    def CloseProject(self, project):
        self.closed.append(project.GetName())
        self.current = None
        return True

    def DeleteProject(self, name):
        self.delete_calls += 1
        if self.delete_results:
            return self.delete_results.pop(0)
        return False


class DeleteProjectSafelyTests(unittest.TestCase):
    def test_simple_success(self):
        pm = _FakePM(current="other", delete_results=[True])
        out = delete_project_safely(pm, "zz_pilot")
        self.assertTrue(out["success"])
        self.assertEqual(out["attempts"], 1)
        self.assertIsNone(out["leftover"])
        self.assertEqual(pm.loaded, [])

    def test_retry_after_false_then_success(self):
        pm = _FakePM(current="other", delete_results=[False, True])
        out = delete_project_safely(pm, "zz_pilot", delay_seconds=0)
        self.assertTrue(out["success"])
        self.assertEqual(out["attempts"], 2)

    def test_switches_away_when_target_is_current(self):
        pm = _FakePM(current="zz_pilot", delete_results=[True])
        out = delete_project_safely(pm, "zz_pilot", switch_to="real_project",
                                    delay_seconds=0)
        self.assertTrue(out["success"])
        self.assertEqual(pm.loaded, ["real_project"])
        self.assertEqual(pm.closed, [])

    def test_closes_current_without_fallback(self):
        pm = _FakePM(current="zz_pilot", delete_results=[True])
        out = delete_project_safely(pm, "zz_pilot", delay_seconds=0)
        self.assertTrue(out["success"])
        self.assertEqual(pm.closed, ["zz_pilot"])

    def test_close_fallback_when_load_fails(self):
        pm = _FakePM(current="zz_pilot", delete_results=[True], load_ok=False)
        out = delete_project_safely(pm, "zz_pilot", switch_to="real_project",
                                    delay_seconds=0)
        self.assertTrue(out["success"])
        self.assertEqual(pm.loaded, ["real_project"])
        self.assertEqual(pm.closed, ["zz_pilot"])

    def test_reports_leftover_by_name_on_persistent_failure(self):
        pm = _FakePM(current="other", delete_results=[False, False])
        out = delete_project_safely(pm, "zz_pilot", delay_seconds=0)
        self.assertFalse(out["success"])
        self.assertEqual(out["attempts"], 2)
        self.assertEqual(out["leftover"], "zz_pilot")
        self.assertTrue(out["detail"])

    def test_exception_in_delete_is_reported_not_raised(self):
        class _BoomPM(_FakePM):
            def DeleteProject(self, name):
                raise RuntimeError("api wedged")

        pm = _BoomPM(current="other")
        out = delete_project_safely(pm, "zz_pilot", delay_seconds=0)
        self.assertFalse(out["success"])
        self.assertEqual(out["leftover"], "zz_pilot")
        self.assertIn("api wedged", out["detail"])

    def test_never_loads_target_as_fallback(self):
        pm = _FakePM(current="zz_pilot", delete_results=[True])
        delete_project_safely(pm, "zz_pilot", switch_to="zz_pilot",
                              delay_seconds=0)
        self.assertEqual(pm.loaded, [])
        self.assertEqual(pm.closed, ["zz_pilot"])


if __name__ == "__main__":
    unittest.main()
