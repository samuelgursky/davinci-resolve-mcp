"""Offline tests for src.utils.platform.get_resolve_paths (env-var overrides).

Resolve is not always installed under the platform default location (external
volume, custom install dir). The installer-style env vars RESOLVE_SCRIPT_API and
RESOLVE_SCRIPT_LIB must win over the built-in default, but only when they point
at something that actually exists — a stale env var must not shadow a working
default install.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils import platform as platform_utils  # noqa: E402

ENV_KEYS = ("RESOLVE_SCRIPT_API", "RESOLVE_SCRIPT_LIB")


def _env_without_overrides():
    return {k: v for k, v in os.environ.items() if k not in ENV_KEYS}


class ResolvePathEnvOverrideTest(unittest.TestCase):
    def test_defaults_used_when_env_unset(self):
        with patch.object(platform_utils, "get_platform", return_value="darwin"), \
                patch.dict(os.environ, _env_without_overrides(), clear=True):
            paths = platform_utils.get_resolve_paths()
        self.assertEqual(
            paths["lib_path"],
            "/Applications/DaVinci Resolve/DaVinci Resolve.app"
            "/Contents/Libraries/Fusion/fusionscript.so",
        )

    def test_existing_env_lib_overrides_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib = os.path.join(tmp, "fusionscript.so")
            with open(lib, "w"):
                pass
            env = _env_without_overrides()
            env["RESOLVE_SCRIPT_LIB"] = lib
            with patch.object(platform_utils, "get_platform", return_value="darwin"), \
                    patch.dict(os.environ, env, clear=True):
                paths = platform_utils.get_resolve_paths()
            self.assertEqual(paths["lib_path"], lib)

    def test_existing_env_api_also_moves_modules_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = _env_without_overrides()
            env["RESOLVE_SCRIPT_API"] = tmp
            with patch.object(platform_utils, "get_platform", return_value="darwin"), \
                    patch.dict(os.environ, env, clear=True):
                paths = platform_utils.get_resolve_paths()
            self.assertEqual(paths["api_path"], tmp)
            self.assertEqual(paths["modules_path"], os.path.join(tmp, "Modules"))

    def test_nonexistent_env_paths_fall_back_to_defaults(self):
        env = _env_without_overrides()
        env["RESOLVE_SCRIPT_API"] = "/nope/does/not/exist"
        env["RESOLVE_SCRIPT_LIB"] = "/nope/does/not/exist/fusionscript.so"
        with patch.object(platform_utils, "get_platform", return_value="darwin"), \
                patch.dict(os.environ, env, clear=True):
            paths = platform_utils.get_resolve_paths()
        self.assertEqual(
            paths["api_path"],
            "/Library/Application Support/Blackmagic Design"
            "/DaVinci Resolve/Developer/Scripting",
        )
        self.assertEqual(
            paths["lib_path"],
            "/Applications/DaVinci Resolve/DaVinci Resolve.app"
            "/Contents/Libraries/Fusion/fusionscript.so",
        )


if __name__ == "__main__":
    unittest.main()
