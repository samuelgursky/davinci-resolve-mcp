"""A string "false" must not lift the `_mcp_` name guard.

The project-lifecycle and extension kernels refuse any name that does not start
with `_mcp_` unless the caller passes allow_non_mcp_name=True. That opt-in was
read with bare truthiness in both guard helpers, so allow_non_mcp_name="false"
-- the spelling a client that stringifies its JSON scalars sends -- is truthy
and the guard stands down. safe_project_delete then deletes a project the MCP
never created, and safe_install_extension / safe_remove_extension go on to write
or unlink a Fusion, DCTL or script file under a user-owned name.

Same class as the six permission flags in tests/test_permission_flags_string_false.py.
"""

import os
import sys
import unittest

# Stub the Resolve module so server.py imports without Resolve installed.
sys.modules.setdefault('DaVinciResolveScript', type(sys)('DaVinciResolveScript'))

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.server import (  # noqa: E402
    _extension_safe_name,
    _require_disposable_project_name,
    _safe_install_extension,
    _safe_project_delete,
)

FALSE_SPELLINGS = ("false", "False", "FALSE", "no", "off", "0")
TRUE_SPELLINGS = (True, "true", "True", "yes", "on", "1")

USER_PROJECT = "Client Feature Final"


class ProjectStub:
    def __init__(self, name):
        self._name = name

    def GetName(self):
        return self._name


class ProjectManagerStub:
    def __init__(self):
        # Another project is open, so close_current is not in play.
        self.project = ProjectStub("_mcp_something_else")
        self.deleted = []

    def GetCurrentProject(self):
        return self.project

    def DeleteProject(self, name):
        self.deleted.append(name)
        return True

    def GetProjectListInCurrentFolder(self):
        return [n for n in (USER_PROJECT,) if n not in self.deleted]


class ProjectNameGuardTests(unittest.TestCase):
    def test_string_false_keeps_the_guard(self):
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                out = _require_disposable_project_name(USER_PROJECT, allow_non_mcp_name=spelling)
                self.assertIsNotNone(out)
                self.assertIn("_mcp_", out["error"]["message"])

    def test_true_spellings_still_lift_the_guard(self):
        for spelling in TRUE_SPELLINGS:
            with self.subTest(spelling=spelling):
                self.assertIsNone(_require_disposable_project_name(USER_PROJECT, allow_non_mcp_name=spelling))

    def test_safe_project_delete_refuses_a_user_project_on_string_false(self):
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                pm = ProjectManagerStub()
                out = _safe_project_delete(pm, {"name": USER_PROJECT, "allow_non_mcp_name": spelling})

                self.assertEqual(pm.deleted, [], "DeleteProject ran on a non-_mcp_ project")
                self.assertIn("error", out)


class ExtensionNameGuardTests(unittest.TestCase):
    def test_string_false_keeps_the_guard(self):
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                out = _extension_safe_name("UserFuse", allow_non_mcp_name=spelling)
                self.assertIsNotNone(out)
                self.assertIn("_mcp_", out["error"]["message"])

    def test_true_spellings_still_lift_the_guard(self):
        for spelling in TRUE_SPELLINGS:
            with self.subTest(spelling=spelling):
                self.assertIsNone(_extension_safe_name("UserFuse", allow_non_mcp_name=spelling))

    def test_safe_install_extension_refuses_a_user_name_on_string_false(self):
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                out = _safe_install_extension({
                    "extension_type": "fuse",
                    "name": "UserFuse",
                    "kind": "color_matrix",
                    "allow_non_mcp_name": spelling,
                    # Preview only: the name guard is the only thing under test.
                    "dry_run": True,
                })

                self.assertNotIn("would_install", out)
                self.assertIn("_mcp_", out["error"]["message"])


if __name__ == "__main__":
    unittest.main()
