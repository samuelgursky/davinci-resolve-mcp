import unittest

from src.utils.project_cleanup import delete_project_safely, save_project_if_safe


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
        self.saved = []
        self.delete_calls = 0

    def GetCurrentProject(self):
        return _FakeProject(self.current) if self.current else None

    def LoadProject(self, name):
        self.loaded.append(name)
        if self.load_ok:
            self.current = name
        return self.load_ok

    def SaveProject(self):
        # Records the call so a test can assert it was never reached.
        # Headless, reaching it on the never-saved default project
        # blocks forever, so 'was it called' is the whole assertion.
        self.saved.append(self.current)
        return True

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

    def test_save_is_skipped_on_the_project_that_hangs_headless(self):
        """`SaveProject()` on the never-saved default blocks forever headless.

        Measured on a cold `-nogui` boot with the database verified attached
        immediately beforehand: no return after 45 seconds, the client parked in
        `Fusion::RemoteApp::WaitPkt`. Resolve wants a Save-As dialog for a
        project that has no location, and waits for an answer that cannot arrive.
        In the GUI the same call merely returns False.

        This hung two stress runs before it was traced, so the guard is tested
        rather than trusted.
        """
        pm = _FakePM(current="Untitled Project", delete_results=[True])
        out = save_project_if_safe(pm)
        self.assertTrue(out["skipped"])
        self.assertFalse(out["saved"])
        self.assertEqual(pm.saved, [], "SaveProject must not be reached at all")

    def test_save_still_happens_on_a_named_project(self):
        """The guard must not turn into 'never save', which loses real work."""
        pm = _FakePM(current="real_project", delete_results=[True])
        out = save_project_if_safe(pm)
        self.assertFalse(out["skipped"])
        self.assertTrue(out["saved"])
        self.assertEqual(len(pm.saved), 1)

    def test_save_guard_survives_having_no_current_project(self):
        pm = _FakePM(current=None, delete_results=[True])
        out = save_project_if_safe(pm)
        self.assertTrue(out["skipped"])
        self.assertEqual(pm.saved, [])

    def test_closes_and_then_switches_away_when_target_is_current(self):
        """Both steps, in that order — this test used to assert the opposite.

        It previously required `closed == []` when a `switch_to` was given, i.e.
        that loading another project *replaced* closing. Measured on Studio
        19.1.3.7, that is precisely the ordering that fails: LoadProject does not
        release the session's lock on the outgoing project, so DeleteProject then
        returns False permanently — six retries a second apart all failed, while
        the same delete after a CloseProject succeeded first attempt.

        The switch is still needed, just afterwards: CloseProject drops the
        session onto a never-saved `Untitled Project` that cannot be saved, so
        the next close or switch raises a modal no script can dismiss.
        """
        pm = _FakePM(current="zz_pilot", delete_results=[True])
        out = delete_project_safely(pm, "zz_pilot", switch_to="real_project",
                                    delay_seconds=0)
        self.assertTrue(out["success"])
        self.assertEqual(pm.closed, ["zz_pilot"])
        self.assertEqual(pm.loaded, ["real_project"])

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
