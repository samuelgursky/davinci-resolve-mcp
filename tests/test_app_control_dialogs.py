"""open_settings / open_app_preferences say what Resolve can actually do.

Both tools went through Resolve.GetUIManager(), which does not exist. Measured
on Studio 19.1.3.7: dir(resolve) has 23 methods and GetUIManager is not one;
getattr returns None, so the call raised "'NoneType' object is not callable",
a broad except swallowed it, an ERROR was logged, and the tool answered with a
bare "Failed to open Project Settings dialog". A tool that could never work
reported itself as one that had merely failed this time.

The fakes below model the two facts that matter about a Resolve object:
`hasattr` is True for every name, and `getattr` of a missing one is None.
"""
import unittest
from unittest import mock

from src.utils import app_control
from src.granular import resolve_control as granular


class _RemoteObject:
    """Like Resolve's PyRemoteObject: any unknown attribute reads as None."""

    def __init__(self, **methods):
        self._methods = methods
        self.called = []

    def __getattr__(self, name):
        methods = object.__getattribute__(self, "_methods")
        if name in methods:
            def _call(*args):
                self.called.append(name)
                result = methods[name]
                if isinstance(result, Exception):
                    raise result
                return result
            return _call
        return None


def _resolve_as_measured():
    """Studio 19.1.3.7: no GetUIManager at all."""
    return _RemoteObject(GetCurrentPage="edit")


def _resolve_with_ui_manager(**ui_methods):
    ui_manager = _RemoteObject(**ui_methods)
    return _RemoteObject(GetUIManager=ui_manager), ui_manager


class FakeFidelityTest(unittest.TestCase):
    def test_the_fake_fabricates_the_way_resolve_does(self):
        resolve = _resolve_as_measured()
        self.assertTrue(hasattr(resolve, "GetUIManager"))
        self.assertIsNone(getattr(resolve, "GetUIManager"))
        with self.assertRaises(TypeError):
            resolve.GetUIManager()


class OpenDialogTest(unittest.TestCase):
    def test_a_build_without_the_call_is_unsupported_not_failed(self):
        for helper, label in ((app_control.open_project_settings, "Project Settings"),
                              (app_control.open_preferences, "Preferences")):
            with self.subTest(label=label):
                with mock.patch.object(app_control.logger, "error") as logged:
                    out = helper(_resolve_as_measured())
                self.assertEqual((out["success"], out["supported"]), (False, False))
                self.assertIn(label, out["message"])
                self.assertIn("Resolve.GetUIManager does not exist", out["message"])
                # Nothing went wrong, so nothing is logged as an error.
                logged.assert_not_called()

    def test_a_ui_manager_without_the_method_is_unsupported_and_not_called(self):
        # hasattr(ui_manager, "OpenProjectSettings") is True here too; calling
        # on the strength of it is how a missing method gets "called".
        resolve, ui_manager = _resolve_with_ui_manager(FindWindow=None)
        out = app_control.open_project_settings(resolve)
        self.assertEqual((out["success"], out["supported"]), (False, False))
        self.assertIn("UIManager.OpenProjectSettings does not exist", out["message"])
        self.assertEqual(ui_manager.called, [])

    def test_a_build_that_has_the_call_is_used(self):
        resolve, ui_manager = _resolve_with_ui_manager(OpenProjectSettings=True, OpenPreferences=None)
        out = app_control.open_project_settings(resolve)
        self.assertEqual((out["success"], out["supported"]), (True, True))
        self.assertEqual(ui_manager.called, ["OpenProjectSettings"])
        # A call that returns nothing is not a refusal.
        self.assertTrue(app_control.open_preferences(resolve)["success"])

    def test_a_refusal_is_reported_not_assumed_away(self):
        # The old code discarded this return and answered True.
        resolve, _ = _resolve_with_ui_manager(OpenProjectSettings=False)
        out = app_control.open_project_settings(resolve)
        self.assertEqual((out["success"], out["supported"]), (False, True))
        self.assertIn("returned False", out["message"])

    def test_an_exception_from_the_call_is_reported(self):
        resolve, _ = _resolve_with_ui_manager(OpenPreferences=RuntimeError("no window"))
        with mock.patch.object(app_control.logger, "error"):
            out = app_control.open_preferences(resolve)
        self.assertEqual((out["success"], out["supported"]), (False, True))
        self.assertIn("no window", out["message"])


class GranularToolTest(unittest.TestCase):
    def _call(self, tool, resolve):
        with mock.patch.object(granular, "get_resolve", return_value=resolve):
            return tool()

    def test_open_settings_names_what_is_missing_and_what_to_use(self):
        out = self._call(granular.open_settings, _resolve_as_measured())
        self.assertTrue(out.startswith("Not supported:"), out)
        self.assertIn("Project Settings", out)
        self.assertIn("set_project_setting", out)

    def test_open_app_preferences_names_what_is_missing(self):
        out = self._call(granular.open_app_preferences, _resolve_as_measured())
        self.assertTrue(out.startswith("Not supported:"), out)
        self.assertIn("Preferences", out)

    def test_both_report_success_only_when_the_call_was_made(self):
        resolve, ui_manager = _resolve_with_ui_manager(OpenProjectSettings=True, OpenPreferences=True)
        self.assertEqual(self._call(granular.open_settings, resolve),
                         "Project Settings dialog opened successfully")
        self.assertEqual(self._call(granular.open_app_preferences, resolve),
                         "Preferences dialog opened successfully")
        self.assertEqual(ui_manager.called, ["OpenProjectSettings", "OpenPreferences"])

    def test_a_refusal_reaches_the_caller(self):
        resolve, _ = _resolve_with_ui_manager(OpenProjectSettings=False)
        self.assertIn("returned False", self._call(granular.open_settings, resolve))

    def test_not_connected_is_still_its_own_answer(self):
        self.assertEqual(self._call(granular.open_settings, None),
                         "Error: Not connected to DaVinci Resolve")

    def test_the_named_replacement_tools_exist(self):
        from src.granular import project
        for name in ("get_project_settings", "get_project_setting", "set_project_setting"):
            self.assertTrue(callable(getattr(project, name, None)), name)


if __name__ == "__main__":
    unittest.main()
